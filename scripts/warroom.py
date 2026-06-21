#!/usr/bin/env python3
"""warroom.py — convene an Execution-Grounded Multi-Agent War Room.

Implements the 4-Stage Execution Pipeline exactly per specification:
  Phase 0: DynaDebate (Dynamic Path Allocation)
  Phase 1: Heterogeneous Generation (4 orthogonal personas)
  Phase 2: Execution-Grounded Cross-Review & Asymmetric Scoring (Sandbox Arbiter)
  Phase 3: Evidence-Gated Synthesis (Appellate Chairman)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

# Make the agent CLIs reachable even when spawned from launchd's thin PATH.
for _p in ("/usr/local/bin", "/opt/homebrew/bin",
           os.path.expanduser("~/.local/bin"),
           os.path.expanduser("~/.npm-global/bin")):
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = _p + ":" + os.environ.get("PATH", "")


def _load_env() -> None:
    path = os.path.expanduser("~/.hermes/.env")
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_env()

import route as RT  # PROVIDERS + _call_cli

PANEL_TIMEOUT = 120.0
ROUND2_TIMEOUT = 90.0
SYNTH_TIMEOUT = 90.0
WARROOM_DIR = os.path.expanduser("~/.hermes/meta/warrooms")

# Grounding is NON-NEGOTIABLE: every answer must be anchored to real, current facts — the live
# estate state below + the world as it actually is — not plausible-sounding speculation.
_GROUND_RULES = (
    "GROUNDING (mandatory): anchor every claim to the REAL WORLD — the GROUND TRUTH block below "
    "(the estate's actual live state) and current, real facts you know. Do NOT speculate or invent "
    "numbers. If a claim rests on an assumption, prefix it 'ASSUMPTION:'. No generic advice — be "
    "concrete and specific to THIS estate's real situation."
)

# The four panel seats with primary direct providers and transparent fallbacks.
PANEL = [
    {"display": "Claude CLI", "kind": "cli", "provider": "claude-cli", "model": ""},
    {"display": "AGY",        "kind": "cli", "provider": "agy-cli",    "model": ""},
    {"display": "DeepSeek",   "kind": "api", "provider": "deepseek",   "model": "deepseek-v4-pro"},
    {"display": "MiniMax",    "kind": "api", "provider": "minimax",    "model": "MiniMax-M3"},
]

# 5.1: Phase 0 Path Allocation Prompt
_PHASE0_PROMPT = (
    "You are the Path Allocation Engine for a multi-agent architectural debate. "
    "The user will provide a software engineering problem. Your sole job is to generate "
    "4 mutually exclusive, technically viable approaches to solving this problem. "
    "Do not write the code. Only define the architectural path.\n"
    "Output strictly in JSON format:\n"
    "{{\"paths\": [ {{\"id\": \"A\", \"description\": \"...\"}}, {{\"id\": \"B\", \"description\": \"...\"}}, {{\"id\": \"C\", \"description\": \"...\"}}, {{\"id\": \"D\", \"description\": \"...\"}} ]}}"
)

# 5.2: Phase 1 Persona Prompts
_PHASE1_PREFIX = (
    "You are participating in an execution-grounded War Room. You have been assigned an "
    "architectural approach and a specific persona constraint. You must solve the user's "
    "problem using ONLY your assigned approach and strictly adhering to your persona rules.\n\n"
    "[ESTATE TELEMETRY]\n{telemetry}\n\n"
    "[ASSIGNED PATH]\n{assigned_path}\n\n"
    "[GROUND RULES]\n{rules}\n\n"
    "{persona_rule}\n\n"
    "Give your SHARPEST take on the QUESTION: lead with your recommendation in one line; then at "
    "most 4 bullets of grounded reasoning; name the single biggest real risk. Then write the actual "
    "code solution inside python code blocks. Be decisive, no preamble. Hard limit ~250 words.\n\n"
    "QUESTION: {q}"
)

PERSONA_RULES = [
    # Agent 1 (Empiricist)
    "[PERSONA RULE]: You are the Empiricist. You are strictly prohibited from making assumptions "
    "about the environment. You must anchor every single logical step and variable reference to the "
    "live telemetry data provided above. If data is missing, write code that dynamically checks for it.",
    
    # Agent 2 (Red Team)
    "[PERSONA RULE]: You are the Red Team Logician. You must assume the user's implicit premises are "
    "flawed. Build your solution with aggressive defensive programming, bounds checking, and failure fallbacks. "
    "Prioritize security and edge-case survival over elegance.",
    
    # Agent 3 (Synthesizer)
    "[PERSONA RULE]: You are the Lateral Synthesizer. You must ignore standard, bloated industry design "
    "patterns. Seek unconventional, high-efficiency shortcuts. Use clever mathematical or bitwise logic "
    "where possible to bypass standard iterative loops.",
    
    # Agent 4 (Pragmatist)
    "[PERSONA RULE]: You are the Execution Pragmatist. You evaluate success strictly on latency, line count, "
    "and operational simplicity. Write the most direct, un-abstracted, procedural code possible. "
    "No unnecessary classes or middleware."
]

# 5.3: Phase 2 Review Prompt
_PHASE2_PROMPT = (
    "You are the Sandbox Arbiter. You will be provided with the anonymized solutions of three peers "
    "(Advisor A, Advisor B, Advisor C).\n\n"
    "Your task:\n"
    "1. Rank them from 1 (best) to 3 (worst).\n"
    "2. Critique their flaws.\n\n"
    "[CRITICAL EXECUTION MANDATE]\n"
    "You cannot fail a peer on semantic arguments or 'best practices' alone. To fail a peer you MUST "
    "supply a standalone python/bash test that exercises their code and, ONLY IF the flaw is real, prints "
    "the exact line VULN_PROVEN and exits with status code 42. If the flaw is NOT present the test must exit 0. "
    "A test that errors for any OTHER reason (its own bug, missing import, crash) is discarded and counts "
    "against nobody — so make it correct, minimal, and self-contained.\n"
    "The test runs in a NETWORK-ISOLATED, SECRET-FREE sandbox: do not attempt any file, network, or system "
    "access beyond the peer's code. No test = your critique is ignored.\n\n"
    "THE OTHER ADVISORS' TAKES:\n"
    "### Advisor A:\n{take_A}\n\n"
    "### Advisor B:\n{take_B}\n\n"
    "### Advisor C:\n{take_C}\n\n"
    "[OUTPUT FORMAT]\n"
    "Output a JSON object containing your rankings and any adversarial scripts targeting specific advisors. "
    "Use the exact keys 'rankings' (values 1 to 3) and 'adversarial_tests' (containing the python or bash script "
    "wrapped inside a markdown code block, or empty string). Follow this JSON schema exactly:\n"
    "{{\n"
    "  \"rankings\": {{\n"
    "    \"Advisor A\": 2,\n"
    "    \"Advisor B\": 1,\n"
    "    \"Advisor C\": 3\n"
    "  }},\n"
    "  \"critiques\": {{\n"
    "    \"Advisor A\": \"...\",\n"
    "    \"Advisor B\": \"...\",\n"
    "    \"Advisor C\": \"...\"\n"
    "  }},\n"
    "  \"adversarial_tests\": {{\n"
    "    \"Advisor A\": \"```python\\n...\\n```\",\n"
    "    \"Advisor B\": \"\",\n"
    "    \"Advisor C\": \"```bash\\n...\\n```\"\n"
    "  }}\n"
    "}}"
)


def _ask_api(provider: str, model: str, prompt: str, timeout: float, max_tokens: int = 2000) -> str:
    from openai import OpenAI
    cfg = RT.PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        raise RuntimeError(f"no {cfg['key_env']} in env")
    client = OpenAI(base_url=cfg["base_url"], api_key=key, timeout=timeout, max_retries=0)
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)
    return (resp.choices[0].message.content or "").strip()


def _call_source(kind: str, provider: str, model: str, prompt: str, timeout: float) -> str:
    if kind == "api":
        text = _ask_api(provider, model, prompt, timeout)
    else:
        text = RT._call_cli(provider, RT.PROVIDERS[provider], model, prompt, None, timeout)
    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def _call_source_with_fallback(seat: dict, prompt: str, timeout: float) -> tuple[str, str]:
    try:
        text = _call_source(seat["kind"], seat["provider"], seat["model"], prompt, timeout)
        return seat["display"], text
    except Exception:
        fallbacks = [
            {"display": f"{seat['display']} (Gemini fallback)", "kind": "api", "provider": "gemini", "model": "gemini-2.5-flash"},
            {"display": f"{seat['display']} (DeepSeek fallback)", "kind": "api", "provider": "deepseek", "model": "deepseek-chat"},
            {"display": f"{seat['display']} (MiniMax fallback)", "kind": "api", "provider": "minimax", "model": "MiniMax-M3"},
        ]
        for fb in fallbacks:
            if fb["provider"] == seat["provider"]:
                continue
            try:
                text = _call_source(fb["kind"], fb["provider"], fb["model"], prompt, timeout)
                return fb["display"], text
            except Exception:
                continue
        raise RuntimeError(f"All fallbacks exhausted for seat {seat['display']}")


def _estate_ground() -> str:
    try:
        import coordinator as C
        conn = C.connect()
        try:
            h = C.health(conn)
        finally:
            conn.close()
        h = re.sub(r"\*+", "", h).strip()
        return "GROUND TRUTH — the estate's live state right now:\n" + h
    except Exception:
        return "GROUND TRUTH: (live estate state unavailable this run — reason only from real, known facts)."


def extract_code(text: str) -> str:
    blocks = re.findall(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    if blocks:
        return "\n\n".join(blocks).strip()
    blocks_bash = re.findall(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    if blocks_bash:
        return "\n\n".join(blocks_bash).strip()
    return text.strip()


# ── Confined Arbiter (spec v2 §0, §5.5) ───────────────────────────────────────────────────────
# Model-generated code NEVER runs on the host. Boundary order: Docker (no host FS, no network, no
# secrets) -> macOS sandbox-exec (scrubbed env, no network, writes confined to tmp) -> REFUSE.
# A 'proven' verdict requires the test to print VULN_PROVEN AND exit 42 — a mere crash is
# CRITIQUE_FAILED_EXECUTION (neutral), so a broken test cannot masquerade as a proof.
SENTINEL = "VULN_PROVEN"
VULN_RC = 42
WALL_S = 10
_DOCKER_IMG = "python:3.11-slim"
# Defense-in-depth static screen (NOT the boundary): reject obviously hostile tests pre-exec.
_UNSAFE_TOKENS = (
    "import socket", "import requests", "urllib", "http.client", "httpx", "subprocess",
    "os.system", "os.popen", "ctypes", "shutil.rmtree", "__import__", "/Users/",
    os.path.expanduser("~"), "pty", ".fork(", "smtplib", "paramiko", "/etc/",
)
_DOCKER_IMG_OK: list[bool] = []  # memo so we only inspect/pull the image once per process


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    if _DOCKER_IMG_OK:
        return _DOCKER_IMG_OK[0]
    ok = False
    try:
        ok = subprocess.run(["docker", "image", "inspect", _DOCKER_IMG],
                            capture_output=True, timeout=15).returncode == 0
        if not ok:
            ok = subprocess.run(["docker", "pull", _DOCKER_IMG],
                                capture_output=True, timeout=180).returncode == 0
    except Exception:
        ok = False
    _DOCKER_IMG_OK.append(ok)
    return ok


def _verdict(rc: int, out: str, err: str) -> dict:
    if rc == VULN_RC and SENTINEL in (out + err):
        return {"status": "VULNERABILITY_PROVEN", "stderr": (err or out)[:2000]}
    if rc == 0:
        return {"status": "CRITIQUE_FALSIFIED", "stdout": out[:2000]}
    return {"status": "CRITIQUE_FAILED_EXECUTION", "stderr": (err or out)[:2000]}


def sandbox_arbiter(critic_test_script: str, target_code: str) -> dict:
    """Run a critic's adversarial test against a peer's code behind a REAL boundary (spec v2 §5.5).

    Returns a verdict: VULNERABILITY_PROVEN (target had the flaw), CRITIQUE_FALSIFIED (no flaw —
    critic penalised), or CRITIQUE_FAILED_EXECUTION (the critic's own test broke — neutral).
    """
    test_src = extract_code(critic_test_script)
    target_src = extract_code(target_code)
    payload = (f"{target_src}\n\n# --- CRITIC ADVERSARIAL TEST "
               f"(print {SENTINEL} & exit {VULN_RC} iff the flaw is real) ---\n{test_src}")

    if any(tok and tok in payload for tok in _UNSAFE_TOKENS):
        return {"status": "CRITIQUE_FAILED_EXECUTION", "reason": "unsafe-static-screen"}

    tmp = tempfile.mkdtemp(prefix="warroom-arb-")
    try:
        with open(os.path.join(tmp, "payload.py"), "w", encoding="utf-8") as f:
            f.write(payload)

        if _docker_ready():
            # No host FS (ro mount), no network, no host env, unprivileged, resource-capped, ephemeral.
            cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "256m",
                   "--cpus", "1", "--pids-limit", "64", "--read-only",
                   "--tmpfs", "/tmp:size=16m", "-v", f"{tmp}:/work:ro", "-w", "/work",
                   "--user", "65534", _DOCKER_IMG,
                   "timeout", str(WALL_S), "python", "/work/payload.py"]
            env = None  # docker does not forward host env into the container
        elif shutil.which("sandbox-exec"):
            py = sys.executable or "/usr/local/bin/python3"
            # HOME->tmp so expanduser('~') can't reach ~/.hermes/.env; env scrubbed of API keys;
            # writes confined to tmp; network denied. (/Users/ + home path are static-screened too.)
            profile = ("(version 1)(deny default)(allow process-fork)(allow process-exec)"
                       "(allow file-read*)"
                       f'(allow file-write* (subpath "{tmp}"))'
                       '(allow file-write* (subpath "/private/tmp") (subpath "/private/var/folders"))'
                       "(deny network*)")
            cmd = ["sandbox-exec", "-p", profile, py, os.path.join(tmp, "payload.py")]
            env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "TMPDIR": tmp}
        else:
            return {"status": "CRITIQUE_FAILED_EXECUTION", "reason": "no-sandbox-available"}

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=WALL_S + 8,
                               env=env, cwd=tmp, start_new_session=True)
        except subprocess.TimeoutExpired:
            return {"status": "CRITIQUE_FAILED_EXECUTION", "reason": "timeout"}
        return _verdict(r.returncode, r.stdout or "", r.stderr or "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def calculate_council_weights(peer_ranks: list[list[float]], grounding_penalties: list[float], iterations: int = 10) -> list[float]:
    n_agents = len(peer_ranks)
    weights = [1.0 / n_agents] * n_agents
    base_mask = [0.1 if p else 1.0 for p in grounding_penalties]
    
    for _ in range(iterations):
        take_scores = [0.0] * n_agents
        for i in range(n_agents):
            for j in range(n_agents):
                if i != j:
                    take_scores[j] += weights[i] * peer_ranks[i][j]
        new_weights = [take_scores[k] * base_mask[k] for k in range(n_agents)]
        total = sum(new_weights)
        if total > 1e-9:
            weights = [w / total for w in new_weights]
        else:
            weights = [1.0 / n_agents] * n_agents
    return weights


def parse_json(text: str) -> dict:
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass
    match_braces = re.search(r"(\{.*?\})", text, re.DOTALL)
    if match_braces:
        try:
            return json.loads(match_braces.group(1).strip())
        except Exception:
            pass
    return {}


def run_council(question: str, ground: str = "") -> dict:
    if not ground:
        ground = _estate_ground()
        
    # --- PHASE 0: Dynamic Path Allocation ---
    try:
        path_res = _call_source("api", "gemini", "gemini-2.5-flash", f"{_PHASE0_PROMPT}\n\nQuestion: {question}", 30.0)
        paths_json = parse_json(path_res)
        paths = paths_json.get("paths", [])
        if len(paths) < 4:
            raise ValueError("Insufficient paths returned")
    except Exception:
        # Fallback default paths
        paths = [
            {"id": "A", "description": "Strict verification path using robust, standard design practices."},
            {"id": "B", "description": "Redundant defensively programmed route with failover strategies."},
            {"id": "C", "description": "Lateral design optimizing for maximum execution shortcuts."},
            {"id": "D", "description": "Procedural minimalist layout reducing dependency footprints."}
        ]

    # --- PHASE 1: Heterogeneous Generation ---
    stage1_takes: list[tuple[str, str, bool]] = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = []
        for idx, seat in enumerate(PANEL):
            path_desc = f"Path {paths[idx]['id']}: {paths[idx]['description']}"
            prompt = _PHASE1_PREFIX.format(
                telemetry=ground,
                assigned_path=path_desc,
                rules=_GROUND_RULES,
                persona_rule=PERSONA_RULES[idx],
                q=question
            )
            futs.append(ex.submit(_call_source_with_fallback, seat, prompt, PANEL_TIMEOUT))
            
        for idx, f in enumerate(futs):
            try:
                disp, text = f.result()
                stage1_takes.append((disp, text, True))
            except Exception as e:
                stage1_takes.append((PANEL[idx]["display"], f"⚠️ Failed initial take: {str(e)}", False))

    # --- PHASE 2: Cross-Review & Sandbox Arbiter ---
    stage2_takes: list[tuple[str, str, bool]] = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs2 = []
        for idx, seat in enumerate(PANEL):
            if not stage1_takes[idx][2]:
                futs2.append(None)
                continue
                
            others = [j for j in range(4) if j != idx]
            take_A = f"Advisor A:\n{stage1_takes[others[0]][1]}"
            take_B = f"Advisor B:\n{stage1_takes[others[1]][1]}"
            take_C = f"Advisor C:\n{stage1_takes[others[2]][1]}"
            
            prompt2 = _PHASE2_PROMPT.format(rules=_GROUND_RULES, ground=ground, q=question,
                                     take_A=take_A, take_B=take_B, take_C=take_C)
            futs2.append(ex.submit(_call_source_with_fallback, seat, prompt2, ROUND2_TIMEOUT))
            
        for idx, f in enumerate(futs2):
            if f is None:
                stage2_takes.append((PANEL[idx]["display"], "", False))
                continue
            try:
                disp, text = f.result()
                stage2_takes.append((disp, text, True))
            except Exception as e:
                stage2_takes.append((PANEL[idx]["display"], f"⚠️ Failed critique: {str(e)}", False))

    # --- Sandbox Executions & Weight Computation ---
    peer_ranks = [[0.0] * 4 for _ in range(4)]
    grounding_penalties = [0.0] * 4
    sandbox_results = []
    
    for idx in range(4):
        if not stage2_takes[idx][2]:
            continue
        parsed = parse_json(stage2_takes[idx][1])
        rankings = parsed.get("rankings", {})
        tests = parsed.get("adversarial_tests", {})
        others = [j for j in range(4) if j != idx]
        
        # Parse Rankings
        advisor_labels = ["Advisor A", "Advisor B", "Advisor C"]
        for o_lbl, o_idx in zip(advisor_labels, others):
            rank = rankings.get(o_lbl)
            if rank in (1, 2, 3):
                peer_ranks[idx][o_idx] = float(4 - rank)
            else:
                peer_ranks[idx][o_idx] = 2.0  # Default neutral rank
                
        # Parse Adversarial Tests & Execute Sandbox
        for o_lbl, o_idx in zip(advisor_labels, others):
            test_script = tests.get(o_lbl, "").strip()
            if test_script:
                target_code = stage1_takes[o_idx][1]
                trace = sandbox_arbiter(test_script, target_code)
                sandbox_results.append({
                    "critic": stage2_takes[idx][0],
                    "target": stage1_takes[o_idx][0],
                    "status": trace["status"],
                    "stderr": trace.get("stderr", ""),
                    "stdout": trace.get("stdout", "")
                })
                
                # Asymmetric penalty (spec v2 §3): only EXECUTION decides.
                if trace["status"] == "VULNERABILITY_PROVEN":
                    grounding_penalties[o_idx] = 1.0  # target: real flaw reproduced
                elif trace["status"] == "CRITIQUE_FALSIFIED":
                    grounding_penalties[idx] = 1.0    # critic: claimed a flaw that isn't there
                # CRITIQUE_FAILED_EXECUTION => critic's own test broke → neutral, nobody penalised

    weights = calculate_council_weights(peer_ranks, grounding_penalties)
    
    # --- PHASE 3: Evidence-Gated Synthesis ---
    weights_block = "\n".join(
        f"- Advisor {idx+1} ({stage2_takes[idx][0]}): Influence Weight = {weights[idx]:.2f}"
        for idx in range(4)
    )
    sandbox_block = ""
    for r in sandbox_results:
        sandbox_block += f"### Sandbox Test: {r['critic']} targeting {r['target']}\nResult: **{r['status']}**\n"
        if r["stderr"]:
            sandbox_block += f"Stderr output:\n```\n{r['stderr']}\n```\n"
        if r["stdout"]:
            sandbox_block += f"Stdout output:\n```\n{r['stdout']}\n```\n"
        sandbox_block += "\n"
        
    transcript_block = ""
    for idx in range(4):
        status = "Active" if stage2_takes[idx][2] else "Offline"
        transcript_block += f"### Advisor {idx+1} ({stage2_takes[idx][0]}) [{status}]:\n{stage2_takes[idx][1]}\n\n"
        
    chair_prompt = _CHAIR_PROMPT.format(
        weights_block=weights_block,
        sandbox_results=sandbox_block or "(No execution tests run this round)",
        ground=ground,
        q=question,
        transcript=transcript_block
    )
    
    try:
        # Appellate Synthesis Model: DeepSeek v4 Pro (fallback to Gemini)
        try:
            synth_out = _call_source("api", "deepseek", "deepseek-chat", chair_prompt, SYNTH_TIMEOUT)
        except Exception:
            synth_out = _call_source("api", "gemini", "gemini-2.5-flash", chair_prompt, SYNTH_TIMEOUT)
    except Exception as e:
        synth_out = json.dumps({
            "decision": f"Failed synthesis: {str(e)}",
            "confidence_score": 0.50,
            "dissent_coefficient": 0.50,
            "minority_preservation": "Synthesis failed due to API connection error."
        })
        
    res_json = parse_json(synth_out)
    return {
        "decision": res_json.get("decision", "No decision output."),
        "confidence_score": res_json.get("confidence_score", 0.70),
        "dissent_coefficient": res_json.get("dissent_coefficient", 0.30),
        "minority_preservation": res_json.get("minority_preservation", ""),
        "weights": weights,
        "takes": stage2_takes,
        "sandbox": sandbox_results
    }


_CHAIR_PROMPT = (
    "You are the War Room Chairman. You must synthesize a final, production-ready solution "
    "based on the preceding debate trajectory.\n\n"
    "[EVIDENCE GATE]\n"
    "You are mathematically forbidden from accepting any peer critique or altering the baseline code "
    "UNLESS the critique is accompanied by a VULNERABILITY_PROVEN execution trace. Do not trust "
    "semantic arguments. Trust only the stderr output provided from the Sandbox Arbiter tests. "
    "Ignore critiques that resulted in CRITIQUE_FAILED_EXECUTION.\n\n"
    "Calculated Council Influence Weights:\n"
    "{weights_block}\n\n"
    "[SANDBOX EXECUTION EVIDENCE]\n"
    "{sandbox_results}\n\n"
    "[GROUND TRUTH ESTATE HEALTH]\n"
    "{ground}\n\n"
    "QUESTION: {q}\n\n"
    "ADVISORS' DEBATE TRANSCRIPT:\n"
    "{transcript}\n\n"
    "Using the reputation-weighted scores and the execution evidence, construct the final output. "
    "If you overrule valid, passing code in favor of better architecture, you must document it in the "
    "minority_preservation field. Calculate the dissent_coefficient (0.0 for total agreement, 1.0 for total "
    "chaos) based on the variance of the peer rankings.\n\n"
    "[REQUIRED JSON SCHEMA]\n"
    "wrapped in a markdown json block:\n"
    "```json\n"
    "{{\n"
    "  \"decision\": \"your decisive call and compiled code (no hedging)\",\n"
    "  \"confidence_score\": 0.95,\n"
    "  \"dissent_coefficient\": 0.3,\n"
    "  \"minority_preservation\": \"...\"\n"
    "}}\n"
    "```"
)


def _deliver(chunks: list[str], to_telegram: bool) -> None:
    if not to_telegram:
        print("\n\n".join(chunks))
        return
    try:
        import coordinator as C
        for ch in chunks:
            for i in range(0, len(ch), 3500):
                C.telegram_notify(ch[i:i + 3500])
                time.sleep(0.4)
    except Exception:
        print("\n\n".join(chunks))


def run(question: str, who: str = "?", to_telegram: bool = True) -> int:
    question = question.strip()
    if not question:
        return 2
    stamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    
    res = run_council(question)
    
    header = f"🗣️ *WAR ROOM DECISION*\n❓ _{question[:240]}_\nConvened by: {who}"
    decision = (
        f"⚖️ *Decision:* {res['decision']}\n"
        f"📈 *Confidence:* {res['confidence_score'] * 100:.0f}% | *Dissent Coefficient:* {res['dissent_coefficient']:.2f}\n"
        f"🔍 *Minority Preservation:* {res['minority_preservation']}"
    )
    
    panel_msgs = []
    for idx, (disp, take, ok) in enumerate(res["takes"]):
        status = "🟢 Active" if ok else "🔴 Offline"
        w = res["weights"][idx]
        panel_msgs.append(f"🧠 *{disp}* (Weight: {w:.2f}) [{status}]\n{take}")
        
    chunks = [f"{header}\n\n{decision}"] + panel_msgs
    
    # Persist the transcript
    try:
        os.makedirs(WARROOM_DIR, exist_ok=True)
        path = os.path.join(WARROOM_DIR, f"{stamp}-council.md")
        with open(path, "w") as fh:
            fh.write(f"# War room — {stamp}\n\n**Convened by:** {who}\n\n**Question:** {question}\n\n")
            fh.write(f"## Chair's brief\n\n{decision}\n\n")
            for idx, (disp, take, ok) in enumerate(res["takes"]):
                fh.write(f"## {disp} (Weight: {res['weights'][idx]:.2f})\n\n{take}\n\n")
    except Exception:
        pass
        
    _deliver(chunks, to_telegram)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", help="the question to put to the war room")
    ap.add_argument("--who", default="?", help="who convened it")
    ap.add_argument("--stdout", action="store_true", help="print locally instead of Telegram")
    a = ap.parse_args()
    return run(a.question, who=a.who, to_telegram=not a.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
