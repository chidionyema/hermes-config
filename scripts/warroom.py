#!/usr/bin/env python3
"""warroom.py — convene a multi-AI war room on one question, from Telegram.

The founder runs the estate from his phone. "Otto, war room: <question>" fans the
question out to THREE independent advisors in parallel —

    • DeepSeek  (deepseek-v4-pro, direct API)
    • Claude    (Claude Code CLI, subscription/OAuth)
    • AGY       (agy CLI, independent backend)

— collects their sharpest takes, then a synthesizer distills consensus, the real
disagreements, and a single recommended decision. The whole transcript is DM'd back
to Telegram and saved to meta/warrooms/.

Design rules (why it is built this way):
  • DETACHED. The otto-inbound hook spawns this as a fire-and-forget subprocess and
    acks immediately, so a 2-3 minute panel never blocks the gateway's event loop.
  • BOUNDED. Every panelist has a hard timeout; one slow/broken advisor cannot wedge
    the room — it reports "unavailable" and the room proceeds with whoever answered.
  • DIRECT PROVIDERS ONLY. Reuses route.py's PROVIDERS/_call_cli — no OpenRouter
    (founder ALL-DIRECT fence). Advisory only: the room produces OPINIONS, it never
    touches money/identity/code, so it is safe to run on an explicit founder command.

Usage:
    warroom.py "should we ship the auth-hold rail before OIDC?"          # → Telegram
    warroom.py "..." --stdout            # print locally, no Telegram (for testing)
    warroom.py "..." --who chidi         # attribute who convened it
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
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
    """Load ~/.hermes/.env (KEY=VALUE) into os.environ without clobbering existing vars,
    so provider API keys are present no matter who spawned us (launchd gateway, cron, shell)."""
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

PANEL_TIMEOUT = 200.0   # per-advisor hard ceiling (CLIs are slow); room waits at most this
SYNTH_TIMEOUT = 120.0
WARROOM_DIR = os.path.expanduser("~/.hermes/meta/warrooms")

# Each advisor answers the SAME framed question. Kept short so the phone digest is readable
# and so a slow CLI has less to generate.
_FRAME = (
    "You are a senior advisor in a war room for the Hermes autonomous AI estate "
    "(a founder running multiple software products + an autonomous agent estate, solo, "
    "from his phone). Give your SHARPEST, most concrete take on the question below.\n"
    "Rules: lead with your recommendation in one line; then at most 4 bullets of reasoning; "
    "name the biggest risk; disagree with the obvious answer if you have reason to. "
    "Be specific and decisive — no hedging, no preamble. Hard limit ~180 words.\n\n"
    "QUESTION: {q}"
)

# The founder's NAMED TRIO (DeepSeek, AGY, Claude CLI) + MiniMax as a paid 4th. Each seat is a
# dict so a seat can carry a FALLBACK: if the primary source is empty/down, the seat heals to a
# second source that preserves the SAME lens, so the trio is never thin. AGY's lens = Google's
# model: primary is the `agy` CLI (free, daily-quota-fragile), fallback is the DIRECT paid Gemini
# API (gemini-2.5-flash) — so the AGY/Google seat is ALWAYS up, never a ⚠️ on quota exhaustion.
# NOTE: API panelists may be REASONING models (deepseek-v4-pro) — max_tokens must be generous or
# hidden reasoning tokens starve the visible answer (empty/truncated output).
PANEL = [
    {"display": "DeepSeek",   "kind": "api", "provider": "deepseek",   "model": "deepseek-v4-pro"},
    {"display": "Claude CLI", "kind": "cli", "provider": "claude-cli", "model": ""},
    {"display": "AGY",        "kind": "cli", "provider": "agy-cli",    "model": "",
     "fallback": {"kind": "api", "provider": "gemini", "model": "gemini-2.5-flash", "note": "via Gemini direct"}},
    {"display": "MiniMax",    "kind": "api", "provider": "minimax",    "model": "MiniMax-M3"},
]


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


def _call_source(kind: str, provider: str, model: str, prompt: str) -> str:
    """One source (api or cli). Empty output is treated as FAILURE (quota-burnt CLIs exit 0 with
    no text) so a seat with a fallback actually heals instead of reporting '(empty response)'."""
    if kind == "api":
        text = _ask_api(provider, model, prompt, PANEL_TIMEOUT)
    else:
        text = RT._call_cli(provider, RT.PROVIDERS[provider], model, prompt, None, PANEL_TIMEOUT)
    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def _ask_one(seat: dict, question: str) -> tuple[str, str, bool]:
    """Return (display, answer_text, ok). Never raises. Tries the seat's primary source; on
    failure/empty, heals to its fallback (same lens) if one is defined."""
    display = seat["display"]
    prompt = _FRAME.format(q=question)
    t0 = time.monotonic()
    try:
        text = _call_source(seat["kind"], seat["provider"], seat["model"], prompt)
        dt_s = time.monotonic() - t0
        return display, f"{text}\n\n_({display}, {dt_s:.0f}s)_", True
    except Exception as primary_err:  # noqa: BLE001 - one advisor failing must not sink the room
        fb = seat.get("fallback")
        if fb:
            try:
                text = _call_source(fb["kind"], fb["provider"], fb["model"], prompt)
                dt_s = time.monotonic() - t0
                tag = fb.get("note", "fallback")
                return display, f"{text}\n\n_({display} · {tag}, {dt_s:.0f}s)_", True
            except Exception:  # noqa: BLE001 - fall through to unavailable
                pass
        return display, f"⚠️ _unavailable: {type(primary_err).__name__}: {str(primary_err)[:140]}_", False


def _synthesize(question: str, takes: list[tuple[str, str, bool]]) -> str:
    """Distill the panel into consensus / disagreement / recommendation. Uses DeepSeek
    (fast, paid, not quota-fragile). Falls back to a plain join if the synth call fails."""
    answered = [(d, t) for d, t, ok in takes if ok]
    if not answered:
        return "⚠️ No advisor answered — all three were unavailable. Check provider keys/limits."
    if len(answered) == 1:
        return f"Only *{answered[0][0]}* answered; treat as a single opinion, not a panel."
    panel_block = "\n\n".join(f"### {d}\n{t}" for d, t in answered)
    synth_prompt = (
        "You are the chair of a war room. Below are independent advisor takes on one "
        "question. Produce a crisp decision brief for a solo founder reading on his phone:\n"
        "1. CONSENSUS — what they agree on (1-3 bullets).\n"
        "2. DISAGREEMENT — where they genuinely differ and why it matters (1-3 bullets).\n"
        "3. RECOMMENDATION — your single decisive call + the one risk to watch.\n"
        "Be terse. Hard limit ~160 words. No restating the question.\n\n"
        f"QUESTION: {question}\n\n{panel_block}"
    )
    # Synthesizer = deepseek-v4-flash: non-reasoning, fast, reliable visible output (the
    # -pro reasoner can emit all-reasoning/empty content). Empty result → escalate to fallback.
    try:
        out = _ask_api("deepseek", "deepseek-v4-flash", synth_prompt, SYNTH_TIMEOUT, max_tokens=1200).strip()
        if not out:
            raise RuntimeError("empty synthesis")
        return out
    except Exception:
        try:  # second chance: Claude CLI
            out = RT._call_cli("claude-cli", RT.PROVIDERS["claude-cli"], "",
                               synth_prompt, None, SYNTH_TIMEOUT).strip()
            if out:
                return out
        except Exception:
            pass
        # Last resort: stitch the leading lines of each take so the founder still gets a digest.
        heads = "\n".join(f"• *{d}:* {t.splitlines()[0][:160]}" for d, t in answered)
        return f"_(auto-synthesis unavailable — advisor headlines:)_\n{heads}"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "topic"


def _deliver(chunks: list[str], to_telegram: bool) -> None:
    if not to_telegram:
        print("\n\n".join(chunks))
        return
    import coordinator as C
    for ch in chunks:
        # Telegram hard-caps ~4096 chars; keep a margin and send sequentially.
        for i in range(0, len(ch), 3500):
            C.telegram_notify(ch[i:i + 3500])
            time.sleep(0.4)  # gentle pacing so messages arrive in order


def run(question: str, who: str = "?", to_telegram: bool = True) -> int:
    question = question.strip()
    if not question:
        return 2
    stamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    # Fan out to the panel in parallel — wall-clock = the slowest single advisor, not the sum.
    with cf.ThreadPoolExecutor(max_workers=len(PANEL)) as ex:
        futs = [ex.submit(_ask_one, seat, question) for seat in PANEL]
        takes = []
        for f in futs:
            try:
                takes.append(f.result(timeout=PANEL_TIMEOUT + 30))
            except Exception as e:  # noqa: BLE001
                takes.append(("?", f"⚠️ _panel slot failed: {str(e)[:100]}_", False))

    synthesis = _synthesize(question, takes)
    answered_n = sum(1 for _, _, ok in takes if ok)

    header = (f"🗣️ *WAR ROOM* — {answered_n}/{len(PANEL)} advisors reported\n"
              f"❓ _{question[:240]}_")
    decision = f"⚖️ *CHAIR'S BRIEF*\n{synthesis}"
    panel_msgs = [f"🧠 *{d}*\n{t}" for d, t, _ in takes]

    # Telegram: lead with the decision (what the founder acts on), then the raw takes.
    chunks = [f"{header}\n\n{decision}"] + panel_msgs

    # Persist the full transcript.
    try:
        os.makedirs(WARROOM_DIR, exist_ok=True)
        path = os.path.join(WARROOM_DIR, f"{stamp}-{_slug(question)}.md")
        with open(path, "w") as fh:
            fh.write(f"# War room — {stamp}\n\n**Convened by:** {who}\n\n**Question:** {question}\n\n")
            fh.write(f"## Chair's brief\n\n{synthesis}\n\n")
            for d, t, ok in takes:
                fh.write(f"## {d} {'✅' if ok else '⚠️'}\n\n{t}\n\n")
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
