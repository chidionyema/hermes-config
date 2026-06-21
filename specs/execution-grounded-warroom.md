# Execution-Grounded Multi-Agent War Room Spec — v2 (NET-SAFE)

> v2 supersedes v1. The architecture is unchanged; v1's two host-level hazards are closed.
> v1 ran model-generated code on the estate host with real secrets in env (RCE), and the CI
> Duel `git checkout`-reverted the **live `signalengine` money repo** working tree. v2 keeps the
> 4-stage pipeline but moves all code execution behind a real boundary and all repo mutation
> into disposable worktrees. **No behavioural claim is asserted; the harness reports the truth,
> including "no improvement" — v1's own run tied a single model at 20%/20%.**

---

## 0. Safety Invariants (MUST hold — a build that violates any of these is rejected)

1. **No model-generated code ever runs on the host.** Every Phase-2 adversarial test executes
   inside a confinement boundary (Docker → `sandbox-exec` → refuse), never via bare `python3 -c`.
2. **No secrets reach executed code.** The sandbox env is scrubbed: never `os.environ`
   (it holds DEEPSEEK/MINIMAX/GEMINI/OpenRouter keys). Minimal env, `HOME`=tempdir only.
3. **No network from executed code.** Docker `--network none`; seatbelt denies outbound.
4. **The eval never mutates a live working tree.** All reverts/pytest happen in an ephemeral
   `git worktree`, removed afterwards. The source repo's working tree is read-only to us.
5. **Money repos are evaluated in-vitro only.** `signalengine` (money engine) IS the spec §4 target,
   but every revert/patch/pytest happens in a disposable worktree and is destroyed afterward —
   **no council-generated patch is ever persisted to the real money tree.** Founder fence holds:
   money/identity code is never auto-merged into anything real; this is a throwaway experiment.
6. **A crash is not a proof.** A "vulnerability proven" verdict requires a *sentinel* signal from
   the test, not merely a non-zero exit (else a critic games the system with a broken test).
7. **Bounded.** Caps on sandbox execs/round, paths, reputation iterations, per-call tokens, and
   total wall-clock. Direct providers only (no OpenRouter).
8. **Honest reporting.** The harness prints the real result — including regression — with no
   success theater. Transcripts contain no secrets.

---

## 1. Executive Summary & Rationale

Standard multi-agent LLM systems ("Debate Clubs") suffer from Critique-Induced Confusion and
Conformity Cascades: judging on semantic text alone, models default to sycophancy and degrade
valid code to appease hallucinated critiques. The Execution-Grounded War Room replaces semantic
arguing with **execution evidence** — a critique only counts if a confined test reproduces the
flaw — enforces cognitive diversity via orthogonal path allocation, and synthesizes via an
asymmetric, reputation-weighted algorithm.

**The Mandate (falsifiable, not assumed):** empirically *measure* whether the war room resolves
software tasks at a higher pass rate than a zero-shot frontier model, via a CI harness that
cannot be gamed and reports the unembellished number.

---

## 2. The 4-Stage Execution Pipeline (`scripts/warroom.py`)

### Phase 0 — Dynamic Path Allocation (DynaDebate)
Fast model (Gemini 3.5 Flash / deepseek-v4-flash) generates 4 mutually exclusive approaches.
Output: `{"paths":[{"id":"A","description":"…"}, …]}`. Bounded `max_tokens`; on failure the
pipeline degrades to 4 identical "open" paths (debate still runs).

### Phase 1 — Heterogeneous Generation (parallel, 4 agents)
Each agent gets the master prompt, live estate state (`coordinator.health()`), a persona, and a
path. Personas: **Empiricist** (DeepSeek, anchor to telemetry), **Red Team** (Claude CLI, assume
premise flawed), **Lateral Synthesizer** (MiniMax, unconventional shortcuts), **Pragmatist**
(AGY, latency/simplicity). A genuinely-down agent (e.g. AGY free-quota) reports `unavailable`
honestly — never substituted by another model.

### Phase 2 — Execution-Grounded Cross-Review & Asymmetric Scoring
1. Agents see peers' outputs **anonymized** (Advisor A/B/C) — no self-review, no brand bias.
2. Each ranks peers and may critique.
3. **Confined Arbiter (was "Sandbox Arbiter"):** a critique claiming a flaw MUST ship a standalone
   test that, *iff the flaw exists*, prints the sentinel line `VULN_PROVEN` and exits **42**.
   The test runs inside the boundary (§5.5). Verdicts:
   * exit **42** + sentinel, within budget → `VULNERABILITY_PROVEN` (critic credited).
   * exit **0** → `CRITIQUE_FALSIFIED` (flaw not reproduced → critic's weight slashed).
   * any other exit / traceback / timeout / unsafe-static-screen → `CRITIQUE_FAILED_EXECUTION`
     (the critic's own test is broken → **discarded, neither credited nor penalised**).
   This split is the §0.6 fix: a broken or crashing test can no longer masquerade as a proof.
4. **Reputation Weighting:** see §3.

### Phase 3 — Evidence-Gated Synthesis
Chairman receives the full trajectory: anonymized takes, every arbiter verdict with its
stdout/stderr, and the reputation-adjusted weights. **Evidence Gate:** reject any critique not
carrying a `VULNERABILITY_PROVEN` trace; trust execution over rhetoric. Output:
```json
{"decision":"…","confidence_score":0.0,"dissent_coefficient":0.0,"minority_preservation":"…"}
```
`run(question, who, to_telegram)` is **preserved** (otto-inbound contract): it returns 0 and DMs a
phone-readable brief (decision + confidence + dissent + per-advisor weight/status), saving the
transcript to `meta/warrooms/`.

---

## 3. Mathematical Core: Reputation-Weighted Borda Count
* Init `W_i = 0.25`.
* **Penalty:** an agent whose critique returns `CRITIQUE_FALSIFIED` has its weight masked (×0.1);
  `CRITIQUE_FAILED_EXECUTION` is neutral (no credit, no penalty).
* **Recursive update:** `T_j = Σ_{i≠j} W_i · R_ij`, normalized, iterated 10× (deterministic).
* Result: a model that writes well but hallucinates critiques loses influence over synthesis.

---

## 4. Falsifiable Proof Harness (`scripts/warroom_eval.py`) — worktree-isolated CI Duel

### SwingArena Methodology (SAFE)
* **Target repo:** default `signalengine` (spec §4), overridable with `--repo`. Safety comes from
  worktree isolation (below), **not** from refusing to run — a dirty live tree is fine because we
  never touch it. No money patch is ever persisted (§0.5).
* **Isolation:** for each target fix commit `C`, `git worktree add --detach <TMP> C~1` creates a
  throwaway checkout at the pre-fix state. **All** reverts, patch application, and `pytest` run
  **inside `<TMP>`**; `git worktree remove --force <TMP>` on exit (and in a `finally`). The live
  working tree is never modified — closes §0.4. pytest uses the source repo's venv but `cwd` +
  `PYTHONPATH` point at `<TMP>`, so imports resolve to the reverted copy, not the live tree.
* **Control:** single zero-shot model patches the worktree → pytest → log pass/fail.
* **Test:** same reverted worktree → `warroom.py` pipeline → patch → pytest → log.
* **Refusals:** abort cleanly if `.venv` is absent or worktree creation fails — never fall back to
  mutating the live tree.
* **Report:** deterministic `meta/warrooms/eval/LATEST.md` — raw pass rates, per-commit table,
  dissent column, and an explicit verdict line incl. *"no improvement"* / *"regression"* when true.

### Mutation Methodology (`--mode mutate`, default) — empirical power
The historical SwingArena is spec-pure but only as good as the repo's history: a young repo whose
only single-source fix commits are architecture rewrites (e.g. signalengine `c520399`, a 101-line
process-pool overhaul) yields targets neither contestant can solve zero-shot → 0/0 ties that prove
nothing. To actually test the mandate ("higher pass rate than a single model") the duel needs
*solvable, controlled, statistically-plural* targets. So `mutate` injects a deterministic
single-token bug (relational off-by-one first, then equality / boolean / arithmetic-sign) into a
module imported by a **currently-green** unit test, inside the same `git worktree` isolation. A
mutant is kept ONLY if it flips that test green→red, so it is **measurable by construction**
(HEAD passes · mutant fails · revert passes) — every kept target is fairly resolvable, and swaps
that land in comments/strings/no-op positions self-filter. Both contestants receive the identical
mutated file + real pytest failure; neither is told the mutation. Same `_duel` core, same report.

### Metric: Dissent-to-Accuracy
Report (do not assume) whether high disagreement (dissent > 0.6) correlates with lower accuracy.

---

## 5. System Prompts & Implementation Spec

### 5.0 Provider rules
Direct providers only (route.py PROVIDERS), no OpenRouter. Panelist `max_tokens ≥ 2000`
(deepseek-v4-pro is a reasoner; low caps starve output). Synthesis uses non-reasoning
deepseek-v4-flash. Bounded timeouts per phase; parallel within each phase.

### 5.1–5.4 Phase prompts
As v1 (Path Allocation, four persona prompts, Cross-Review, Evidence-Gated Synthesis) — with one
change to the Cross-Review mandate: *"Your adversarial test MUST print `VULN_PROVEN` and exit code
42 only if the flaw is real; exit 0 otherwise. A test that errors/crashes for any other reason is
discarded and does not count against your target."*

### 5.5 System Wiring — the **confined** arbiter (replaces v1's `python3 -c`)

```python
import os, shutil, subprocess, tempfile

SENTINEL = "VULN_PROVEN"
VULN_RC = 42
WALL_S = 10
# Defense-in-depth pre-screen (NOT the boundary): reject obviously hostile tests before running.
_UNSAFE = ("import socket", "import requests", "urllib", "subprocess", "os.system", "os.popen",
           "ctypes", "shutil.rmtree", "__import__", "/Users/", os.path.expanduser("~"), "open('/'",
           "pty", "fork(")

def confined_run(test_src: str) -> dict:
    """Run an adversarial test with NO host access, NO secrets, NO network. Returns a verdict.
    Boundary order: Docker (best) -> macOS sandbox-exec -> refuse (never bare python3 -c)."""
    if any(tok in test_src for tok in _UNSAFE):
        return {"status": "CRITIQUE_FAILED_EXECUTION", "reason": "unsafe-static-screen"}

    tmp = tempfile.mkdtemp(prefix="warroom-arb-")
    try:
        with open(os.path.join(tmp, "test.py"), "w") as f:
            f.write(test_src)

        if shutil.which("docker"):
            cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "256m",
                   "--cpus", "1", "--pids-limit", "64", "--read-only",
                   "--tmpfs", "/tmp:size=16m", "-v", f"{tmp}:/work:ro", "-w", "/work",
                   "--user", "65534", "python:3.11-slim",
                   "timeout", str(WALL_S), "python", "/work/test.py"]
            env = None  # docker provides a clean env; host env never forwarded
        elif shutil.which("sandbox-exec"):
            profile = ("(version 1)(deny default)"
                       "(allow process-fork)(allow process-exec)"
                       f'(allow file-read* (subpath "{tmp}"))'
                       f'(allow file-write* (subpath "{tmp}"))'
                       '(allow file-read* (literal \"/usr/local/bin/python3\") (subpath \"/usr/local/lib\") (subpath \"/usr/lib\"))'
                       "(deny network*)")
            cmd = ["sandbox-exec", "-p", profile, "/usr/local/bin/python3", os.path.join(tmp, "test.py")]
            env = {"PATH": "/usr/bin:/bin", "HOME": tmp}  # scrubbed: NO api keys
        else:
            return {"status": "CRITIQUE_FAILED_EXECUTION", "reason": "no-sandbox-available"}

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=WALL_S + 5,
                               env=env, cwd=tmp, start_new_session=True)
        except subprocess.TimeoutExpired:
            return {"status": "CRITIQUE_FAILED_EXECUTION", "reason": "timeout"}

        if r.returncode == VULN_RC and SENTINEL in (r.stdout + r.stderr):
            return {"status": "VULNERABILITY_PROVEN", "stderr": r.stderr[:2000]}
        if r.returncode == 0:
            return {"status": "CRITIQUE_FALSIFIED", "stdout": r.stdout[:2000]}
        return {"status": "CRITIQUE_FAILED_EXECUTION", "reason": f"rc={r.returncode}",
                "stderr": r.stderr[:2000]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```

Notes: Docker mounts the test **read-only** (`-v …:ro`) as UID 65534 (nobody), no network, memory/
pid/cpu capped, ephemeral. The seatbelt fallback scrubs env (no keys), confines FS writes to the
tempdir, denies network. Either way: a hostile test cannot read `.env`, reach the network, or
touch the estate. The CI Duel's worktree pytest (§4) is the *trusted* repo's own suite — separate
from this untrusted-critique path — and likewise runs only inside a disposable worktree.

---

## 6. What v2 deliberately keeps honest
The pipeline is interesting but unproven; v1's harness measured **council 20% == single 20%** on 5
real bugs. v2's job is to make the experiment **safe and repeatable**, then let the number — better,
equal, or worse — stand on its own. If the council does not beat a single model after this is run
clean, that is a finding, not a failure to hide.
