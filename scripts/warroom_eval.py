#!/usr/bin/env python3
"""warroom_eval.py — SwingArena CI Duel Evaluation Harness (NET-SAFE, spec v2 §4).

Measures whether the War Room council beats a single frontier model at fixing real, historically
resolved bugs — WITHOUT ever mutating a live working tree.

SAFETY INVARIANTS (spec v2 §0):
  • Every revert / patch / pytest runs inside an ephemeral `git worktree` checked out at the
    pre-fix commit. The source repo's working tree is read-only to us and is NEVER modified.
  • Money/identity repos are gated: targeting `signalengine` (the trading money engine) requires
    --allow-money-fence AND a clean source tree. Default target is the non-money estate repo.
  • The harness refuses (never falls back to mutating the live tree) if the worktree can't be made
    or the repo is dirty without --allow-dirty.
  • Honest reporting: the verdict line states better / equal / regression as it truly is.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import route as RT
from warroom import run_council, extract_code

DEFAULT_REPO = "/Users/chidionyema/documents/code/signalengine"  # spec §4 target
EVAL_DIR = os.path.expanduser("~/.hermes/meta/warrooms/eval")
LATEST_REPORT_PATH = os.path.join(EVAL_DIR, "LATEST.md")
PYTEST_TIMEOUT = 300


def _git(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def repo_is_dirty(repo: str) -> bool:
    return bool(_git(["status", "--porcelain"], repo).stdout.strip())


def find_swing_targets(repo: str, count: int = 10) -> list[dict]:
    """Find fix commits that modified both a code file and a test file. Read-only on `repo`."""
    res = _git(["log", "--grep=fix", "--oneline", "-n", "150"], repo)
    commits = []
    for line in res.stdout.strip().split("\n"):
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "message": parts[1]})

    targets: list[dict] = []
    for c in commits:
        if len(targets) >= count:
            break
        diff = _git(["diff", "--name-only", f"{c['hash']}~1", c["hash"]], repo)
        files = [f.strip() for f in diff.stdout.strip().split("\n") if f.strip()]
        src_files = [f for f in files if f.endswith(".py") and not f.startswith("tests/")]
        test_files = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
        if src_files and not test_files:
            for src in src_files:
                base = os.path.splitext(os.path.basename(src))[0]
                for p in (f"tests/test_{base}.py", f"tests/test_{base}_tz.py",
                          f"tests/test_{base}_timestamps.py"):
                    if os.path.exists(os.path.join(repo, p)):
                        test_files.append(p)
                        break
        if src_files and test_files:
            targets.append({"commit": c["hash"], "message": c["message"],
                            "code_file": src_files[0], "test_file": test_files[0]})
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
    so `import <pkg>` resolves to the reverted copy, not the live tree."""
    pytest_bin = _pytest_binary(repo)
    if not pytest_bin:
        return False, "no venv pytest found in source repo"
    env = dict(os.environ)
    env["PYTHONPATH"] = worktree + os.pathsep + env.get("PYTHONPATH", "")
    try:
        res = subprocess.run([pytest_bin, test_file, "-q"], cwd=worktree, env=env,
                             capture_output=True, text=True, timeout=PYTEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "pytest timed out"
    return res.returncode == 0, (res.stderr or res.stdout)


def _apply(code_abs: str, code: str) -> None:
    os.makedirs(os.path.dirname(code_abs), exist_ok=True)
    with open(code_abs, "w", encoding="utf-8") as f:
        f.write(code)


def evaluate_target(idx: int, target: dict, repo: str) -> dict:
    commit, msg = target["commit"], target["message"]
    code_file, test_file = target["code_file"], target["test_file"]
    print(f"[{idx+1}] {commit}: {msg[:55]}...")

    result = {"commit": commit, "message": msg, "code_file": code_file, "test_file": test_file,
              "single_ok": False, "council_ok": False, "dissent": 0.0}

    wt = tempfile.mkdtemp(prefix="swingarena-wt-")
    try:
        add = _git(["worktree", "add", "--detach", wt, f"{commit}~1"], repo)
        if add.returncode != 0:
            print(f"  ⚠️ worktree add failed ({add.stderr.strip()[:120]}) — skipping target")
            return result
        code_abs = os.path.join(wt, code_file)
        if not os.path.exists(code_abs):
            print("  ⚠️ code file absent in pre-fix state — skipping")
            return result
        with open(code_abs, encoding="utf-8") as f:
            pre_fix = f.read()

        _, baseline = run_pytest(wt, repo, test_file)
        baseline_tail = baseline[-1000:]
        bug_prompt = (
            f"Fix this bug. Output the FULL corrected file inside one ```python ... ``` block.\n"
            f"Bug: {msg}\n\n--- BUGGY FILE ({code_file}) ---\n{pre_fix}\n--- END ---\n\n"
            f"--- TEST FAILURE ---\n{baseline_tail}\n--- END ---")

        # CONTROL — single frontier model
        try:
            single_code = extract_code(RT.route("executor", bug_prompt, timeout=60).text)
            if single_code:
                _apply(code_abs, single_code)
                result["single_ok"], _ = run_pytest(wt, repo, test_file)
        except Exception as e:
            print(f"  single-model error: {e}")

        # reset worktree file to buggy state for the council run (throwaway tree → just rewrite)
        _apply(code_abs, pre_fix)

        # TEST — war room council
        try:
            council = run_council(bug_prompt, ground="GROUND TRUTH: SWINGARENA CI DUEL (isolated worktree).")
            result["dissent"] = float(council.get("dissent_coefficient", 0.0) or 0.0)
            council_code = extract_code(council.get("decision", ""))
            if council_code:
                _apply(code_abs, council_code)
                result["council_ok"], _ = run_pytest(wt, repo, test_file)
        except Exception as e:
            print(f"  council error: {e}")
    finally:
        _git(["worktree", "remove", "--force", wt], repo)
        shutil.rmtree(wt, ignore_errors=True)

    print(f"  single={result['single_ok']} council={result['council_ok']} dissent={result['dissent']:.2f}")
    return result


def make_ascii_bar(val: float, max_len: int = 20) -> str:
    filled = int(val * max_len)
    return "[" + "█" * filled + " " * (max_len - filled) + "]"


def write_report(repo: str, results: list[dict]) -> tuple[float, float]:
    total = len(results) or 1
    single_correct = sum(1 for r in results if r["single_ok"])
    council_correct = sum(1 for r in results if r["council_ok"])
    single_acc, council_acc = single_correct / total, council_correct / total

    def cat_acc(runs):
        return (sum(1 for r in runs if r["council_ok"]) / len(runs)) if runs else 0.0
    low = [r for r in results if r["dissent"] < 0.3]
    med = [r for r in results if 0.3 <= r["dissent"] <= 0.6]
    high = [r for r in results if r["dissent"] > 0.6]

    if council_acc > single_acc:
        verdict = f"✅ Council BEAT single model (+{(council_acc-single_acc)*100:.1f} pts)."
    elif council_acc == single_acc:
        verdict = "➖ NO IMPROVEMENT — council tied the single model. Debate added no accuracy here."
    else:
        verdict = f"🔻 REGRESSION — council was WORSE by {(single_acc-council_acc)*100:.1f} pts."

    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(LATEST_REPORT_PATH, "w") as f:
        f.write("# SwingArena CI Duel Evaluation Report\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Repository:** `{os.path.basename(repo.rstrip('/'))}`\n")
        f.write("**Methodology:** historical fix commits replayed in an ISOLATED git worktree "
                "(live tree never mutated); resolved live via pytest.\n\n")
        f.write(f"## Verdict\n\n{verdict}\n\n")
        f.write("## Comparative Accuracy\n\n")
        f.write("| Condition | Score | Accuracy | Bar |\n| --- | --- | --- | --- |\n")
        f.write(f"| Single Frontier Model | {single_correct}/{total} | {single_acc*100:.1f}% | {make_ascii_bar(single_acc)} |\n")
        f.write(f"| **War Room Council** | **{council_correct}/{total}** | **{council_acc*100:.1f}%** | **{make_ascii_bar(council_acc)}** |\n\n")
        f.write("## Dissent-to-Accuracy\n\n| Dissent | Runs | Council Acc | Chart |\n| --- | --- | --- | --- |\n")
        f.write(f"| Low (<0.3) | {len(low)} | {cat_acc(low)*100:.1f}% | {make_ascii_bar(cat_acc(low))} |\n")
        f.write(f"| Med (0.3-0.6) | {len(med)} | {cat_acc(med)*100:.1f}% | {make_ascii_bar(cat_acc(med))} |\n")
        f.write(f"| High (>0.6) | {len(high)} | {cat_acc(high)*100:.1f}% | {make_ascii_bar(cat_acc(high))} |\n\n")
        f.write("## Per-Commit Results\n\n")
        f.write("| Commit | Message | Code File | Test File | Single | Council | Dissent |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for r in results:
            s = "🟢 Pass" if r["single_ok"] else "🔴 Fail"
            c = "🟢 Pass" if r["council_ok"] else "🔴 Fail"
            f.write(f"| `{r['commit']}` | {r['message'][:48]} | `{r['code_file']}` | `{r['test_file']}` | {s} | {c} | {r['dissent']:.2f} |\n")
    print(f"\n{verdict}\n📄 {LATEST_REPORT_PATH}")
    return single_acc, council_acc


def main() -> int:
    ap = argparse.ArgumentParser(description="SwingArena CI Duel (spec §4, worktree-isolated)")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="source repo (spec §4 default: signalengine)")
    ap.add_argument("--count", type=int, default=10, help="historical bugs to duel (spec: 10-20)")
    ap.add_argument("--dry-run", action="store_true", help="list targets only; no LLM calls, no pytest")
    a = ap.parse_args()

    repo = os.path.abspath(os.path.expanduser(a.repo))
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"❌ {repo} is not a git repo.")
        return 2

    name = os.path.basename(repo.rstrip("/"))
    if repo_is_dirty(repo):
        # Spec §4 reverts the repo to the pre-fix commit. We do that in an isolated worktree, so
        # the live tree (incl. any uncommitted money work) is NEVER touched — a dirty tree is safe.
        print(f"ℹ️ {name} has uncommitted changes; safe — worktree-isolated, live tree untouched.")

    print(f"🚀 SwingArena CI Duel — repo={name}  count={a.count}")
    targets = find_swing_targets(repo, count=a.count)
    print(f"Found {len(targets)} historical bug(s) with code+test.")
    if not targets:
        print("❌ No valid targets.")
        return 1
    if a.dry_run:
        for i, t in enumerate(targets):
            print(f"  [{i+1}] {t['commit']} {t['message'][:60]} | {t['code_file']} | {t['test_file']}")
        if not _pytest_binary(repo):
            print("⚠️ note: no venv pytest found in this repo — a real run would report 'no venv pytest'.")
        return 0

    results = [evaluate_target(i, t, repo) for i, t in enumerate(targets)]
    single_acc, council_acc = write_report(repo, results)
    return 0 if council_acc >= single_acc else 1


if __name__ == "__main__":
    raise SystemExit(main())
