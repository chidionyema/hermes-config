# Execution-Grounded Multi-Agent War Room Spec

## 1. Executive Summary & Rationale

Standard multi-agent LLM systems ("Debate Clubs") suffer from Critique-Induced Confusion (CIC) and Conformity Cascades. When models evaluate each other purely on semantic text, they default to polite sycophancy, often degrading perfectly valid code to appease hallucinated critiques.

The Execution-Grounded War Room abandons semantic consensus. Instead, it operates as an **Adversarial Crucible**. It enforces cognitive diversity through orthogonal path allocation, replaces semantic arguing with sandbox execution testing, and synthesizes final decisions using an asymmetric, reputation-weighted algorithm.

**The Mandate:** The system must mathematically and empirically prove it can resolve complex software engineering tasks with a higher success rate than a zero-shot frontier model (e.g., Claude 4.6 / DeepSeek V4 Pro) via a falsifiable CI testing harness.

---

## 2. The 4-Stage Execution Pipeline (`scripts/warroom.py`)

### Phase 0: Dynamic Path Allocation (DynaDebate)
* **Objective:** Prevent homogeneity before the debate even begins.
* **Mechanism:** A fast, low-latency model (e.g., Gemini 3.5 Flash) acts as the Path Generator. Given the user's prompt, it generates 4 mutually exclusive architectural approaches to the problem.
* **Output:** `[Path A, Path B, Path C, Path D]`

### Phase 1: Heterogeneous Generation
* **Objective:** Force independent, persona-driven generation.
* **Mechanism:** Four distinct LLM calls are executed in parallel. Each agent receives the master prompt, the live estate state (`coordinator.health()`), a unique persona, and a specific path from Phase 0.
  * **Agent 1 (Empiricist - DeepSeek):** Must anchor all logic to estate telemetry. Executing Path A.
  * **Agent 2 (Red Team - Claude CLI):** Assumes the premise is flawed; hunts for edge cases. Executing Path B.
  * **Agent 3 (Synthesizer - MiniMax):** Ignores standard patterns; seeks high-efficiency lateral shortcuts. Executing Path C.
  * **Agent 4 (Pragmatist - AGY):** Optimizes strictly for latency, line count, and operational simplicity. Executing Path D.

### Phase 2: Execution-Grounded Cross-Review & Asymmetric Scoring
* **Objective:** Anonymized peer review where critiques must be backed by code execution, not just text.
* **Mechanism:**
  1. Agents are presented with the anonymized outputs of their peers (Advisor A, B, C).
  2. Agents must rank the takes and provide critiques.
  3. **The Sandbox Arbiter:** If an agent claims a peer's code has a flaw, it must write an adversarial unit test (Python/Bash) to prove it. The `.hermes` sandbox runs this test.
  4. **Reputation Weighting:** If the test fails (proving the vulnerability), the critic gains PageRank reputation, and the target loses it. If the test passes (meaning the critic hallucinated the flaw), the critic's voting weight is slashed to near-zero.

### Phase 3: Evidence-Gated Synthesis
* **Objective:** Final decision compilation based on empirical survival, not democratic voting.
* **Mechanism:** The Chairman model receives the entire trajectory, including the sandbox stderr/stdout results and the mathematically adjusted peer reputation weights.
* **The Evidence Gate:** The Chairman is system-prompted to reject any critique or proposed code change that was not empirically proven in Phase 2.
* **Output Schema:**
  ```json
  {
    "decision": "Final compiled code and implementation steps.",
    "confidence_score": 0.0 - 1.0,
    "dissent_coefficient": 0.0 - 1.0,
    "minority_preservation": "Record of valid but overruled architectural concerns."
  }
  ```

---

## 3. Mathematical Core: Reputation-Weighted Borda Count

Standard peer ranking averages the scores. This system uses a recursive matrix to weigh votes based on the voter's execution-backed accuracy.

* **Initial State:** All agents start with weight $W_i = 0.25$.
* **The Penalty Matrix:** Any agent caught hallucinating a critique (`SandboxArbiter` returns `CRITIQUE_FAILED_EXECUTION`) has its base weight masked (e.g., multiplied by 0.1).
* **Recursive Update:** An agent's score is calculated by how its peers ranked it, multiplied by those peers' current weights. This loops 10 times to stabilize.

$$\text{Take Score } T_j = \sum_{i \neq j} W_i \cdot R_{ij}$$

* **Result:** A model that writes brilliant code but hallucinates critiques will lose its ability to influence the final Chairman synthesis, preventing "confident but wrong" models from hijacking the war room.

---

## 4. The Falsifiable Proof Harness (`scripts/warroom_eval.py`)

To satisfy the mandate of objective superiority, the system relies on a **Continuous Integration (CI) Duel**, moving away from static, memorizable benchmarks.

### The "SwingArena" Methodology
* **Target Selection:** The script dynamically selects 10-20 historically resolved, complex bugs from the local `signalengine` or `estate_watchdog` Git commit history.
* **State Reversion:** The local repository is reverted to the state exactly one commit before the bug was fixed.
* **Control Run (Single Frontier):** The bug report is fed to a single zero-shot model (e.g., Claude 4.6 Thinking). The generated patch is applied, and the local pytest suite is executed. Success/Failure is logged.
* **Test Run (War Room):** The exact same bug report and reverted state are fed into `scripts/warroom.py`. The War Room executes its 4-stage pipeline, applies the patch, and runs pytest.
* **Objective Evaluation:** The final output is a deterministic markdown report (`meta/warrooms/eval/LATEST.md`) comparing the raw pass rates of the single model vs. the War Room against real, local infrastructure.

### Key Metric Tracked: Dissent-to-Accuracy Ratio
The evaluation must prove that high internal disagreement (Dissent Coefficient > 0.6) does not negatively impact the final empirical accuracy of the War Room, proving the system effectively filters noise and extracts signal.
