#!/usr/bin/env python3
"""warroom_eval.py — Execution-Grounded War Room CI Duel Harness (NET-SAFE).

Measures whether the 4-stage War Room beats a single frontier model at fixing real, failing
software tests — WITHOUT ever mutating a live working tree. Two target sources:

  • --mode historical (spec v2 §4, "SwingArena"): replays real fix-commits at C~1 with the fix's
    own regression tests overlaid. PURE per the spec, but only as good as the repo's history — a
    young repo whose only single-file commits are architecture rewrites yields no measurable duel.

  • --mode mutate (default): injects a deterministic single-token bug into CURRENTLY-GREEN source
    so the target test flips green→red. Measurable BY CONSTRUCTION (HEAD passes, mutant fails,
    revert passes), so it gives real statistical n at controlled difficulty — the discriminating
    regime the spec's mandate ("higher pass rate than a single model") actually needs to be tested.

SAFETY INVARIANTS (spec v2 §0):
  • Every checkout / mutation / patch / pytest runs inside an ephemeral `git worktree`. The source
    repo's working tree is read-only to us and is NEVER modified (proven: dirty money tree intact).
  • Both modes resolve targets with REAL pytest before any LLM spend; unmeasurable targets are
    excluded honestly, and the verdict line states better / equal / regression as it truly is.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

_WT_LOCK = threading.Lock()  # serialize git worktree add/remove (shared repo index lock) under concurrency

# COST/LATENCY GUARD: cap CLI seats hard for eval runs (route.py reads this at import time, so it
# MUST be set before `import route`). The live phone war room keeps the 300s default; only this
# bounded eval run shortens the floor so a slow Claude CLI seat can't burn minutes per call.
os.environ.setdefault("HERMES_CLI_TIMEOUT", "75")

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import route as RT
from warroom import run_warroom, extract_code

DEFAULT_REPO = "/Users/chidionyema/documents/code/signalengine"  # spec §4 target
EVAL_DIR = os.path.expanduser("~/.hermes/meta/warrooms/eval")
LATEST_REPORT_PATH = os.path.join(EVAL_DIR, "LATEST.md")
PYTEST_TIMEOUT = 300
EVAL_CONCURRENCY = 2  # targets dueled at once — bounded to avoid Mac overload (per local-ai-ops)

# COST-BOUNDED eval panel: the SAME four named agents as warroom.PANEL, but on FAST transports.
# Claude stays on its CLI (API credits are dead) — hard-capped at 75s by HERMES_CLI_TIMEOUT above.
# AGY runs on Gemini DIRECT — Gemini IS AGY's real backend (its documented self-heal path), so this
# is AGY's true identity, NOT a substitution. DeepSeek + MiniMax are already API. No slow CLI fan-out.
PANEL_EVAL = [
    {"display": "Claude CLI",           "kind": "cli", "provider": "claude-cli", "model": ""},
    {"display": "AGY (Gemini · direct)", "kind": "api", "provider": "gemini",    "model": "gemini-2.5-flash"},
    {"display": "DeepSeek",             "kind": "api", "provider": "deepseek",   "model": "deepseek-v4-pro"},
    {"display": "MiniMax",              "kind": "api", "provider": "minimax",    "model": "MiniMax-M3"},
]

# Curated fast, green-at-HEAD unit tests over modules with real boundary/sign/logic — the surface
# a single-token mutation can flip into a subtle, solvable regression. (Verified fast + green.)
MUTATE_TESTS = [  # ordered so the first N hit DISTINCT modules (diverse targets, not the same file)
    "tests/test_cost_model.py",          # → costs/cost_model.py
    "tests/test_validation.py",          # → validation/cpcv.py
    "tests/test_strategy.py",            # → strategies/base.py
    "tests/test_panel_vectorization.py", # → features/numeric.py
    "tests/test_promotion_gate.py",      # → validation/promotion_gate.py
    "tests/test_risk_primitives.py",     # → costs/cost_model.py (dup site, kept as overflow)
    "tests/test_determinism.py",         # (skipped: not green at HEAD in isolation)
]

# Mutation operators, ordered subtle→blunt: boundary off-by-one first (relational), then equality,
# boolean, arithmetic sign. A mutant is kept ONLY if it flips the target test red, so swaps that land
# in comments/strings/no-op positions are self-filtered. Spaced to avoid matching inside identifiers.
_MUT_OPS = [
    (" <= ", " < "), (" >= ", " > "), (" < ", " <= "), (" > ", " >= "),
    (" == ", " != "), (" != ", " == "),
    (" and ", " or "), (" or ", " and "),
    ("True", "False"), ("False", "True"),
    (" + ", " - "), (" - ", " + "), (" += ", " -= "), (" -= ", " += "),
]
_MUT_MAX_OCC = 15  # occurrences scanned per (file, operator)


def _git(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def repo_is_dirty(repo: str) -> bool:
    return bool(_git(["status", "--porcelain"], repo).stdout.strip())


def find_swing_targets(repo: str, scan: int = 300) -> list[dict]:
    """Historical SwingArena candidates: commits that changed EXACTLY ONE source .py plus >=1 test.

    Single-source is required so a single-file patch can fairly resolve the bug; multi-file fixes are
    unmeasurable in a one-file duel. Candidates are validity-gated later, before any LLM spend."""
    res = _git(["log", "--oneline", "-n", str(scan)], repo)
    commits = []
    for line in res.stdout.strip().split("\n"):
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "message": parts[1]})

    targets: list[dict] = []
    for c in commits:
        diff = _git(["diff", "--name-only", f"{c['hash']}~1", c["hash"]], repo)
        files = [f.strip() for f in diff.stdout.strip().split("\n") if f.strip()]
        src_files = [f for f in files if f.endswith(".py") and not f.startswith("tests/")]
        test_files = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
        if len(src_files) != 1 or not test_files:
            continue
        code_file = src_files[0]
        base = os.path.splitext(os.path.basename(code_file))[0]
        primary = next((t for t in test_files if base in t), test_files[0])
        targets.append({"commit": c["hash"], "message": c["message"],
                        "code_file": code_file, "test_file": primary, "test_files": test_files})
    return targets


def _pytest_binary(repo: str) -> str | None:
    for cand in (".venv/bin/pytest", "venv/bin/pytest"):
        p = os.path.join(repo, cand)
        if os.path.exists(p):
            return p
    return None


def run_pytest(worktree: str, repo: str, test_file: str) -> tuple[bool, str]:
    """Run the target file's pytest INSIDE the worktree, isolating source imports to it.

    Uses the source repo's venv (for installed deps) but cwd + PYTHONPATH point at the worktree,
    so `import <pkg>` resolves to the reverted/mutated copy, not the live tree."""
    pytest_bin = _pytest_binary(repo)
    if not pytest_bin:
        return False, "no venv pytest found in source repo"
    env = dict(os.environ)
    env["PYTHONPATH"] = worktree + os.pathsep + env.get("PYTHONPATH", "")
    try:
        res = subprocess.run([pytest_bin, test_file, "-q", "-p", "no:cacheprovider"], cwd=worktree,
                             env=env, capture_output=True, text=True, timeout=PYTEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "pytest timed out"
    return res.returncode == 0, (res.stderr or res.stdout)


def _apply(code_abs: str, code: str) -> None:
    os.makedirs(os.path.dirname(code_abs), exist_ok=True)
    with open(code_abs, "w", encoding="utf-8") as f:
        f.write(code)


def _duel(wt: str, repo: str, code_abs: str, code_file: str, test_file: str,
          buggy_code: str, bug_prompt: str, result: dict) -> dict:
    """Shared duel core: with a worktree already holding the buggy source + overlaid tests, run the
    single-model CONTROL then the full War Room TEST, each patches `code_abs` and is scored by real
    pytest, resetting to `buggy_code` between. Mutates ONLY the worktree. Sets result in place."""
    # CONTROL — single frontier model (zero-shot)
    try:
        single_code = extract_code(RT.route("executor", bug_prompt, timeout=90, max_tokens=8000).text)
        if single_code:
            _apply(code_abs, single_code)
            result["single_ok"], _ = run_pytest(wt, repo, test_file)
        _apply(code_abs, buggy_code)  # reset for the War Room run
    except Exception as e:
        print(f"  single-model error: {e}")
        _apply(code_abs, buggy_code)

    # TEST — the Execution-Grounded War Room (4-stage pipeline)
    try:
        wr = run_warroom(bug_prompt, ground="GROUND TRUTH: WAR ROOM CI DUEL (isolated worktree).",
                         panel=PANEL_EVAL)
        result["dissent"] = float(wr.get("dissent_coefficient", 0.0) or 0.0)
        wr_code = wr.get("code") or extract_code(wr.get("decision", ""))
        if wr_code:
            _apply(code_abs, wr_code)
            result["warroom_ok"], _ = run_pytest(wt, repo, test_file)
    except Exception as e:
        print(f"  war-room error: {e}")

    print(f"  single={result['single_ok']} warroom={result['warroom_ok']} dissent={result['dissent']:.2f}")
    return result


def evaluate_target(idx: int, target: dict, repo: str, validate_only: bool = False) -> dict:
    """HISTORICAL mode: validity-gate a fix-commit (cheap, no LLM), then duel if measurable."""
    commit, msg = target["commit"], target["message"]
    code_file, test_file = target["code_file"], target["test_file"]
    test_files = target.get("test_files", [test_file])
    print(f"[{idx+1}] {commit}: {msg[:55]}...")

    result = {"commit": commit, "message": msg, "code_file": code_file, "test_file": test_file,
              "valid": False, "single_ok": False, "warroom_ok": False, "dissent": 0.0}

    wt = tempfile.mkdtemp(prefix="swingarena-wt-")
    try:
        with _WT_LOCK:
            add = _git(["worktree", "add", "--detach", wt, f"{commit}~1"], repo)
        if add.returncode != 0:
            print(f"  ⚠️ worktree add failed ({add.stderr.strip()[:120]}) — skip")
            return result
        code_abs = os.path.join(wt, code_file)
        if not os.path.exists(code_abs):
            print("  ⚠️ source absent at pre-fix state — skip")
            return result
        with open(code_abs, encoding="utf-8") as f:
            pre_fix = f.read()

        # Overlay EVERY regression test at its fixed-commit version (they shipped with the fix).
        for t in test_files:
            _apply(os.path.join(wt, t), _git(["show", f"{commit}:{t}"], repo).stdout)

        # ── VALIDITY GATE (no LLM): buggy source must FAIL, real single-file fix must PASS ──
        baseline_ok, baseline = run_pytest(wt, repo, test_file)
        if baseline_ok:
            print("  ⚠️ baseline passes → test doesn't capture the bug — exclude")
            return result
        fixed_src = _git(["show", f"{commit}:{code_file}"], repo).stdout
        _apply(code_abs, fixed_src)
        ref_ok, ref_out = run_pytest(wt, repo, test_file)
        if not ref_ok:
            print("  ⚠️ reference single-file fix does NOT pass → multi-file/unmeasurable — exclude")
            return result
        result["valid"] = True
        _apply(code_abs, pre_fix)  # reset to buggy for the duel
        if validate_only:
            print("  ✓ measurable (buggy fails, reference fix passes)")
            return result
        print("  ✓ measurable (buggy fails, reference fix passes) — running duel")

        bug_prompt = (
            f"Fix this bug. Output the FULL corrected file inside one ```python ... ``` block.\n"
            f"Bug: {msg}\n\n--- BUGGY FILE ({code_file}) ---\n{pre_fix}\n--- END ---\n\n"
            f"--- TEST FAILURE ---\n{baseline[-1200:]}\n--- END ---")
        _duel(wt, repo, code_abs, code_file, test_file, pre_fix, bug_prompt, result)
    finally:
        with _WT_LOCK:
            _git(["worktree", "remove", "--force", wt], repo)
        shutil.rmtree(wt, ignore_errors=True)
    return result


def _replace_nth(s: str, old: str, new: str, n: int) -> str | None:
    """Replace the n-th (0-based) occurrence of `old` with `new`; None if there aren't enough."""
    i = -1
    for _ in range(n + 1):
        i = s.find(old, i + 1)
        if i == -1:
            return None
    return s[:i] + new + s[i + len(old):]


def _module_files(test_abs: str, wt: str) -> list[tuple[str, str]]:
    """Resolve the `signal_engine.*` modules a test imports to (relpath, abspath) source files.

    Ordered so the module whose basename matches the test name is mutated first (most on-topic),
    then deeper modules — keeps config/base constants from being the default mutation site."""
    try:
        with open(test_abs, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return []
    test_stem = os.path.splitext(os.path.basename(test_abs))[0].replace("test_", "")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for dotted in re.findall(r"(?:from|import)\s+(signal_engine[\w.]*)", txt):
        parts = dotted.split(".")
        for depth in range(len(parts), 1, -1):
            rel = os.path.join(*parts[:depth]) + ".py"
            if rel in seen:
                break
            if os.path.exists(os.path.join(wt, rel)):
                seen.add(rel)
                out.append((rel, os.path.join(wt, rel)))
                break
    out.sort(key=lambda ra: (os.path.splitext(os.path.basename(ra[0]))[0] not in test_stem
                             and test_stem not in os.path.splitext(os.path.basename(ra[0]))[0],
                             -ra[0].count(os.sep)))
    return out


def find_mutant(wt: str, repo: str, test_file: str) -> dict | None:
    """Find one deterministic single-token mutation in a module imported by `test_file` that flips
    the (green-at-HEAD) target test to red. Returns the target dict, or None if the test isn't green
    or no mutation discriminates. Leaves the worktree restored to original. No LLM."""
    test_abs = os.path.join(wt, test_file)
    green_ok, _ = run_pytest(wt, repo, test_file)
    if not green_ok:
        print("  ⚠️ test not green at HEAD (flaky/env) — skip pair")
        return None
    for rel, code_abs in _module_files(test_abs, wt):
        with open(code_abs, encoding="utf-8") as f:
            original = f.read()
        for old, new in _MUT_OPS:
            for occ in range(_MUT_MAX_OCC):
                mutant = _replace_nth(original, old, new, occ)
                if mutant is None:
                    break
                if mutant == original:
                    continue
                _apply(code_abs, mutant)
                broke, out = run_pytest(wt, repo, test_file)
                _apply(code_abs, original)  # restore immediately
                if not broke:
                    continue
                desc = f"mutated `{old.strip()}`→`{new.strip()}` (occ {occ}) in {rel}"
                print(f"  ✓ measurable mutant: {desc}")
                return {"code_file": rel, "test_file": test_file, "original": original,
                        "mutant": mutant, "desc": desc, "fail_out": out,
                        "message": f"Single-token regression in {rel} — {test_file} fails."}
    print("  ⚠️ no discriminating single-token mutation found — skip pair")
    return None


def evaluate_mutant(idx: int, test_file: str, repo: str, validate_only: bool = False) -> dict:
    """MUTATE mode: inject a measurable single-token bug into green code, then duel if not dry-run."""
    print(f"[{idx+1}] {test_file}")
    result = {"commit": "mutant", "message": "", "code_file": "", "test_file": test_file,
              "valid": False, "single_ok": False, "warroom_ok": False, "dissent": 0.0}
    wt = tempfile.mkdtemp(prefix="warroom-mut-")
    try:
        with _WT_LOCK:
            add = _git(["worktree", "add", "--detach", wt, "HEAD"], repo)
        if add.returncode != 0:
            print(f"  ⚠️ worktree add failed ({add.stderr.strip()[:120]}) — skip")
            return result
        m = find_mutant(wt, repo, test_file)
        if not m:
            return result
        result.update(valid=True, code_file=m["code_file"], message=m["desc"])
        if validate_only:
            return result
        code_abs = os.path.join(wt, m["code_file"])
        _apply(code_abs, m["mutant"])  # plant the bug for the duel
        bug_prompt = (
            f"Fix this bug. Output the FULL corrected file inside one ```python ... ``` block.\n"
            f"A regression was introduced in {m['code_file']}; its unit test now fails.\n\n"
            f"--- BUGGY FILE ({m['code_file']}) ---\n{m['mutant']}\n--- END ---\n\n"
            f"--- TEST FAILURE ---\n{m['fail_out'][-1200:]}\n--- END ---")
        _duel(wt, repo, code_abs, m["code_file"], test_file, m["mutant"], bug_prompt, result)
    finally:
        with _WT_LOCK:
            _git(["worktree", "remove", "--force", wt], repo)
        shutil.rmtree(wt, ignore_errors=True)
    return result


def make_ascii_bar(val: float, max_len: int = 20) -> str:
    filled = int(val * max_len)
    return "[" + "█" * filled + " " * (max_len - filled) + "]"


def write_report(repo: str, results: list[dict], examined: int, excluded: int, mode: str) -> tuple[float, float]:
    """results = ONLY measurable targets (valid). Returns (single_acc, warroom_acc)."""
    total = len(results) or 1
    single_correct = sum(1 for r in results if r["single_ok"])
    warroom_correct = sum(1 for r in results if r["warroom_ok"])
    single_acc, warroom_acc = single_correct / total, warroom_correct / total

    def cat_acc(runs):
        return (sum(1 for r in runs if r["warroom_ok"]) / len(runs)) if runs else 0.0
    low = [r for r in results if r["dissent"] < 0.3]
    med = [r for r in results if 0.3 <= r["dissent"] <= 0.6]
    high = [r for r in results if r["dissent"] > 0.6]

    if warroom_acc > single_acc:
        verdict = f"✅ War Room BEAT the single model (+{(warroom_acc-single_acc)*100:.1f} pts)."
    elif warroom_acc == single_acc:
        verdict = "➖ NO IMPROVEMENT — War Room tied the single model on this set."
    else:
        verdict = f"🔻 REGRESSION — War Room was WORSE by {(single_acc-warroom_acc)*100:.1f} pts."

    meth = ("each fix commit replayed in an ISOLATED git worktree at `C~1` with the fix's own "
            "regression tests overlaid; resolved by real pytest" if mode == "historical" else
            "a deterministic single-token bug injected into CURRENTLY-GREEN source inside an "
            "ISOLATED git worktree (measurable by construction: HEAD passes, mutant fails, revert "
            "passes); resolved by real pytest")

    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(LATEST_REPORT_PATH, "w") as f:
        f.write("# CI Duel — Execution-Grounded War Room vs Single Frontier Model\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Repository:** `{os.path.basename(repo.rstrip('/'))}`  ·  **Mode:** `{mode}`\n")
        f.write(f"**Measurable targets:** {len(results)} (examined {examined}; {excluded} excluded — unmeasurable)\n")
        f.write(f"**Methodology:** {meth}; live tree NEVER mutated.\n\n")
        f.write(f"## Verdict\n\n{verdict}\n\n")
        f.write("## Comparative Accuracy\n\n")
        f.write("| Condition | Score | Accuracy | Bar |\n| --- | --- | --- | --- |\n")
        f.write(f"| Single Frontier Model | {single_correct}/{total} | {single_acc*100:.1f}% | {make_ascii_bar(single_acc)} |\n")
        f.write(f"| **Execution-Grounded War Room** | **{warroom_correct}/{total}** | **{warroom_acc*100:.1f}%** | **{make_ascii_bar(warroom_acc)}** |\n\n")
        f.write("## Dissent-to-Accuracy\n\n| Dissent | Runs | War Room Acc | Chart |\n| --- | --- | --- | --- |\n")
        f.write(f"| Low (<0.3) | {len(low)} | {cat_acc(low)*100:.1f}% | {make_ascii_bar(cat_acc(low))} |\n")
        f.write(f"| Med (0.3-0.6) | {len(med)} | {cat_acc(med)*100:.1f}% | {make_ascii_bar(cat_acc(med))} |\n")
        f.write(f"| High (>0.6) | {len(high)} | {cat_acc(high)*100:.1f}% | {make_ascii_bar(cat_acc(high))} |\n\n")
        f.write("## Per-Target Results (measurable only)\n\n")
        f.write("| Target | Detail | Code File | Test File | Single | War Room | Dissent |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for r in results:
            s = "🟢 Pass" if r["single_ok"] else "🔴 Fail"
            c = "🟢 Pass" if r["warroom_ok"] else "🔴 Fail"
            f.write(f"| `{r['commit']}` | {r['message'][:48]} | `{r['code_file']}` | `{r['test_file']}` | {s} | {c} | {r['dissent']:.2f} |\n")
    print(f"\n{verdict}\n📄 {LATEST_REPORT_PATH}")
    return single_acc, warroom_acc


def main() -> int:
    ap = argparse.ArgumentParser(description="Execution-Grounded War Room CI Duel (worktree-isolated)")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="source repo (default: signalengine)")
    ap.add_argument("--mode", choices=["mutate", "historical"], default="mutate",
                    help="mutate: inject solvable bugs into green code (default); historical: spec §4 fix-commits")
    ap.add_argument("--count", type=int, default=4, help="measurable targets to duel (cost-bounded)")
    ap.add_argument("--concurrency", type=int, default=EVAL_CONCURRENCY, help="targets dueled at once")
    ap.add_argument("--dry-run", action="store_true", help="find/validate targets only; no LLM calls")
    a = ap.parse_args()

    repo = os.path.abspath(os.path.expanduser(a.repo))
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"❌ {repo} is not a git repo.")
        return 2
    name = os.path.basename(repo.rstrip("/"))
    if repo_is_dirty(repo):
        # Spec §4 reverts the repo; we do it in an isolated worktree, so the live tree (incl. any
        # uncommitted money work) is NEVER touched — a dirty tree is safe.
        print(f"ℹ️ {name} has uncommitted changes; safe — worktree-isolated, live tree untouched.")
    if not _pytest_binary(repo):
        print(f"❌ no .venv/venv pytest in {name} — cannot resolve targets. Aborting (never mutate live tree).")
        return 5

    conc = max(1, a.concurrency)
    print(f"🚀 War Room CI Duel — repo={name}  mode={a.mode}  want={a.count} measurable  "
          f"concurrency={conc}{'  [DRY-RUN: targets only, no LLM]' if a.dry_run else ''}")

    if a.mode == "historical":
        items: list = find_swing_targets(repo)
        print(f"Scanned history → {len(items)} single-source fix-with-test candidate(s).")
        runner = lambda i, vo: evaluate_target(i, items[i], repo, validate_only=vo)
    else:
        items = list(MUTATE_TESTS)
        print(f"Curated mutation pairs → {len(items)} green test(s).")
        runner = lambda i, vo: evaluate_mutant(i, items[i], repo, validate_only=vo)

    if not items:
        print("❌ No candidates.")
        return 1

    # ── PASS 1 (no LLM, cheap): validity-gate candidates until we have `count` measurable targets. ──
    measurable: list[int] = []
    val_results: dict[int, dict] = {}
    examined = 0
    for i in range(len(items)):
        if len(measurable) >= a.count:
            break
        examined += 1
        r = runner(i, True)
        if r.get("valid"):
            measurable.append(i)
            val_results[i] = r
    excluded = examined - len(measurable)

    print(f"\n{'DRY-RUN: ' if a.dry_run else ''}{len(measurable)} measurable / {examined} examined "
          f"({excluded} excluded).")
    if a.dry_run:
        for i in measurable:
            r = val_results[i]
            print(f"  ✓ {r['code_file']} ← {r['test_file']}  ({r['message'][:60]})")
        return 0 if measurable else 1
    if not measurable:
        print("❌ No measurable targets — nothing to score honestly.")
        return 1

    # ── PASS 2 (the LLM duel): exactly `len(measurable)` targets, `conc` at a time. ──
    print(f"⚔️  Dueling {len(measurable)} target(s), {conc} at a time …")
    out: dict[int, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=conc) as ex:
        futs = {ex.submit(runner, i, False): i for i in measurable}
        for f in cf.as_completed(futs):
            out[futs[f]] = f.result()
    results = [out[i] for i in measurable if out.get(i, {}).get("valid")]

    single_acc, warroom_acc = write_report(repo, results, examined, excluded, a.mode)
    return 0 if warroom_acc >= single_acc else 1


if __name__ == "__main__":
    raise SystemExit(main())
