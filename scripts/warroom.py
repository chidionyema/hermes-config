#!/usr/bin/env python3
"""warroom.py — convene a multi-AI war room with 3-stage council debate.

Upgrades (war-room 2026-06-21):
  1. Heterogeneous Slicing: strictly orthogonal personas for all 4 models.
  2. Asymmetric PageRank Matrix: recursive reputation-weighted Borda peer ranking.
  3. Trajectory Chairman: JSON output containing dissent coefficient and preservation.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
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

import route as RT  # PROVIDERS + _call_cli (tested timeout/limit-aware CLI harness)

PANEL_TIMEOUT = 120.0
ROUND2_TIMEOUT = 90.0
SYNTH_TIMEOUT = 90.0
WARROOM_DIR = os.path.expanduser("~/.hermes/meta/warrooms")

# The founder's FOUR named agents. Fallbacks are used transparently to maintain panel size.
PANEL = [
    {"display": "Claude CLI", "kind": "cli", "provider": "claude-cli", "model": ""},
    {"display": "AGY",        "kind": "cli", "provider": "agy-cli",    "model": ""},
    {"display": "DeepSeek",   "kind": "api", "provider": "deepseek",   "model": "deepseek-v4-pro"},
    {"display": "MiniMax",    "kind": "api", "provider": "minimax",    "model": "MiniMax-M3"},
]

# Heterogeneous Slicing Personas
PERSONAS = [
    # Agent 1: The Empiricist (Claude CLI / Index 0)
    "Role: The Empiricist.\n"
    "Constraint: You are strictly prohibited from making assumptions. Every single logical step you take "
    "must be anchored directly to the live output of coordinator.health() (provided in the GROUND TRUTH block). "
    "Cite specific metrics, tasks, or statuses from that block to justify your points. Do not extrapolate.",
    
    # Agent 2: The Red Team Logician (AGY / Index 1)
    "Role: The Red Team Logician.\n"
    "Constraint: You must assume the user's implicit premises in the question are flawed. Hunt exclusively for "
    "edge-case vulnerabilities, hidden dependencies, race conditions, and single-points-of-failure in the proposed course of action.",
    
    # Agent 3: The Lateral Synthesizer (DeepSeek / Index 2)
    "Role: The Lateral Synthesizer.\n"
    "Constraint: Ignore standard industry design patterns. Find unconventional, high-efficiency shortcuts, "
    "out-of-the-box workarounds, and elegant hacks that bypass complexity entirely while maintaining core correctness.",
    
    # Agent 4: The Execution Pragmatist (MiniMax / Index 3)
    "Role: The Execution Pragmatist.\n"
    "Constraint: Evaluate the question strictly on execution metrics: latency, line count, dependency footprint, "
    "and operational simplicity. Reject any design that increases maintenance overhead or operational risk."
]

_GROUND_RULES = (
    "GROUNDING (mandatory): anchor every claim to the REAL WORLD — the GROUND TRUTH block below "
    "(the estate's actual live state) and current, real facts you know. Do NOT speculate or invent "
    "numbers. If a claim rests on an assumption, prefix it 'ASSUMPTION:'. No generic advice — be "
    "concrete and specific to THIS estate's real situation."
)

_FRAME1 = (
    "You are a senior advisor in a live war room for the Hermes autonomous AI estate "
    "(a solo founder running multiple software products + an autonomous agent estate, from his phone).\n\n"
    "YOUR EXPERT PERSONA CONSTRAINTS:\n{persona}\n\n"
    "GROUND RULES:\n{rules}\n\n"
    "{ground}\n\n"
    "Give your SHARPEST take on the QUESTION: lead with your recommendation in one line; then at "
    "most 4 bullets of grounded reasoning; name the single biggest real risk. Be decisive, no preamble. "
    "Hard limit ~170 words.\n\n"
    "QUESTION: {q}"
)

_FRAME2 = (
    "You are a senior advisor in the same war room. You are presented with the takes of 3 other advisors. "
    "To prevent brand bias, their takes have been anonymized as Advisor A, Advisor B, and Advisor C.\n\n"
    "GROUND RULES:\n{rules}\n\n"
    "{ground}\n\n"
    "QUESTION: {q}\n\n"
    "THE OTHER ADVISORS' TAKES:\n"
    "--- START TAKES ---\n"
    "### Advisor A:\n{take_A}\n\n"
    "### Advisor B:\n{take_B}\n\n"
    "### Advisor C:\n{take_C}\n"
    "--- END TAKES ---\n\n"
    "Critique their takes in ~110 words: (1) where they are wrong or make ungrounded claims (cite facts to disprove them), "
    "(2) what they got right, and (3) your final call.\n\n"
    "UNGROUNDED CLAIM DETECTION (CRITICAL):\n"
    "If any advisor made a false or ungrounded claim (not backed by the live ground truth or real facts), you must explicitly "
    "flag it by outputting this exact phrase on a new line (replace X with A, B, or C, and specify the reason):\n"
    "FLAG: Advisor X made a false/ungrounded claim because [reason]\n\n"
    "PEER RANKING (CRITICAL):\n"
    "You must rank the other 3 advisors' takes from 1 to 3, where 1 is the best/most-convincing take and 3 is the least. "
    "At the very end of your response, output a single line matching this exact format:\n"
    "RANKS: Advisor A: [1, 2, or 3], Advisor B: [1, 2, or 3], Advisor C: [1, 2, or 3]\n"
    "Do not rank your own take. Use each rank 1, 2, 3 exactly once."
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
    """Call the panel member, falling back to direct API models if it fails."""
    try:
        text = _call_source(seat["kind"], seat["provider"], seat["model"], prompt, timeout)
        return seat["display"], text
    except Exception:
        # Fallbacks to ensure 4 panel participants are always active
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


def parse_chairman_json(text: str) -> dict:
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
    # Fallback structure
    return {
        "decision": text[:200] + "...",
        "confidence_score": 0.70,
        "dissent_coefficient": 0.30,
        "minority_preservation": "Could not parse minority preservation details."
    }


def run_council(question: str, ground: str = "") -> dict:
    if not ground:
        ground = _estate_ground()
        
    # --- STAGE 1: Parallel initial takes ---
    stage1_takes: list[tuple[str, str, bool]] = []
    with cf.ThreadPoolExecutor(max_workers=len(PANEL)) as ex:
        futs = []
        for idx, seat in enumerate(PANEL):
            prompt = _FRAME1.format(persona=PERSONAS[idx], rules=_GROUND_RULES, ground=ground, q=question)
            futs.append(ex.submit(_call_source_with_fallback, seat, prompt, PANEL_TIMEOUT))
            
        for idx, f in enumerate(futs):
            try:
                disp, text = f.result()
                stage1_takes.append((disp, text, True))
            except Exception as e:
                stage1_takes.append((PANEL[idx]["display"], f"⚠️ Failed initial take: {str(e)}", False))

    # --- STAGE 2: Parallel anonymized review ---
    stage2_takes: list[tuple[str, str, bool]] = []
    with cf.ThreadPoolExecutor(max_workers=len(PANEL)) as ex:
        futs2 = []
        for idx, seat in enumerate(PANEL):
            if not stage1_takes[idx][2]:
                # If stage 1 failed, skip stage 2 and map empty response
                futs2.append(None)
                continue
                
            others = [j for j in range(len(PANEL)) if j != idx]
            take_A = f"Advisor A:\n{stage1_takes[others[0]][1]}"
            take_B = f"Advisor B:\n{stage1_takes[others[1]][1]}"
            take_C = f"Advisor C:\n{stage1_takes[others[2]][1]}"
            
            prompt2 = _FRAME2.format(rules=_GROUND_RULES, ground=ground, q=question,
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

    # --- Matrix Calculation ---
    peer_ranks = [[0.0] * 4 for _ in range(4)]
    grounding_penalties = [0.0] * 4
    
    for idx in range(4):
        if not stage2_takes[idx][2]:
            continue
        text = stage2_takes[idx][1]
        text_lower = text.lower()
        others = [j for j in range(len(PANEL)) if j != idx]
        
        # Parse RANKS
        ranks_match = re.search(
            r"ranks:\s*advisor\s*a:\s*([123]),\s*advisor\s*b:\s*([123]),\s*advisor\s*c:\s*([123])",
            text_lower
        )
        if ranks_match:
            try:
                r_A = int(ranks_match.group(1))
                r_B = int(ranks_match.group(2))
                r_C = int(ranks_match.group(3))
                peer_ranks[idx][others[0]] = float(4 - r_A)
                peer_ranks[idx][others[1]] = float(4 - r_B)
                peer_ranks[idx][others[2]] = float(4 - r_C)
            except Exception:
                # Default ranking
                for o_idx in others:
                    peer_ranks[idx][o_idx] = 2.0
        else:
            # Default ranking
            for o_idx in others:
                peer_ranks[idx][o_idx] = 2.0
                
        # Parse FLAGS
        for match in re.finditer(r"flag:\s*advisor\s*([abc])", text_lower):
            lbl = match.group(1)
            if lbl == "a":
                grounding_penalties[others[0]] = 1.0
            elif lbl == "b":
                grounding_penalties[others[1]] = 1.0
            elif lbl == "c":
                grounding_penalties[others[2]] = 1.0

    weights = calculate_council_weights(peer_ranks, grounding_penalties)
    
    # --- STAGE 3: Trajectory Chairman Synthesis ---
    weights_block = "\n".join(
        f"- Advisor {idx+1} ({stage2_takes[idx][0]}): Council weight = {weights[idx]:.2f}"
        for idx in range(4)
    )
    transcript_block = ""
    for idx in range(4):
        status = "Active" if stage2_takes[idx][2] else "Offline"
        transcript_block += f"### Advisor {idx+1} ({stage2_takes[idx][0]}) [{status}]:\n{stage2_takes[idx][1]}\n\n"
        
    chair_prompt = _CHAIR_PROMPT.format(
        weights_block=weights_block,
        ground=ground,
        q=question,
        transcript=transcript_block
    )
    
    try:
        # Synthesizer: DeepSeek API (falls back to Gemini)
        try:
            synth_out = _call_source("api", "deepseek", "deepseek-chat", chair_prompt, SYNTH_TIMEOUT)
        except Exception:
            synth_out = _call_source("api", "gemini", "gemini-2.5-flash", chair_prompt, SYNTH_TIMEOUT)
    except Exception as e:
        synth_out = json.dumps({
            "decision": f"Failed synthesis due to error: {str(e)}",
            "confidence_score": 0.50,
            "dissent_coefficient": 0.50,
            "minority_preservation": "Chairman failed to convene."
        })
        
    res_json = parse_chairman_json(synth_out)
    return {
        "decision": res_json.get("decision", "No decision output."),
        "confidence_score": res_json.get("confidence_score", 0.70),
        "dissent_coefficient": res_json.get("dissent_coefficient", 0.30),
        "minority_preservation": res_json.get("minority_preservation", ""),
        "weights": weights,
        "takes": stage2_takes
    }


_CHAIR_PROMPT = (
    "You are the CHAIR of a war room that has now completed a 2-round debate. "
    "Your job is to act as an appellate judge evaluating the entire debate trajectory. "
    "You must completely abandon 'consensus seeking' and politeness. Strip out filler. "
    "Evaluate the arguments based on their logical merit, grounding, and the calculated peer reputation weights below.\n\n"
    "Calculated Council Influence Weights (reputation based on peer-review ranking and grounding checks):\n"
    "{weights_block}\n\n"
    "{ground}\n\n"
    "QUESTION: {q}\n\n"
    "ADVISORS' DEBATE TRANSCRIPT:\n"
    "{transcript}\n\n"
    "Provide your analysis of the debate trajectory, weighting their arguments accordingly. "
    "At the very end of your response, you MUST output a strict JSON block wrapped in a markdown code block of type json:\n"
    "```json\n"
    "{{\n"
    "  \"decision\": \"your single decisive call and reasoning summary, grounded in the facts (no hedging)\",\n"
    "  \"confidence_score\": [float between 0.0 and 1.0 based on consensus and quality of argumentation],\n"
    "  \"dissent_coefficient\": [float between 0.0 and 1.0 representing the degree of valid, unresolvable disagreement in the room],\n"
    "  \"minority_preservation\": \"brief explanation of the strongest minority viewpoint/dissent and why it was overruled or how to mitigate its risk\"\n"
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
