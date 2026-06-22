# Estate Audit — 2026-06-21 23:34
_Reproducible on command (`Otto audit`). Deterministic ground-truth, nothing hidden._

## Verdict: 🔴 BROKEN

**Broken (blocks the hands-off goal):**
- Autopilot PARKED — 0 active tasks, 42 all terminal; the loop isn't advancing work.
- 31/42 tasks (73%) escalated into SILENCE — no ask-for-help handoff fires; you're never told. (R3/R4)

**Degraded (works, but not heavenly yet):**
- Reliability watchdog (`ai.hermes.watchdog`) down — `launchctl kickstart -k gui/$(id -u)/ai.hermes.watchdog`
- Self-improvement progress (`ai.hermes.progress`) down — `launchctl kickstart -k gui/$(id -u)/ai.hermes.progress`
- RSI learning loop (`ai.hermes.rsi`) down — `launchctl kickstart -k gui/$(id -u)/ai.hermes.rsi`
- Coordinator alive but last tick advanced 0 tasks — idling.
- Estate never speaks first (`gateway_notify_interval: 0`) — nothing pings you when a task blocks or needs approval. (R4)
- Self-improvement is DISARMED — the estate is not learning right now (`Otto arm self-improvement` to enable).
- All 1 mission(s) unfinished — no operator project shipped. (R2)
- Cron `daily-self-reflection` last_status=error (5h ago) — a scheduled loop is failing.
- Cron `proving-ground-audit` last_status=error (43m ago) — a scheduled loop is failing.
- loop-library skill NOT installed — the loop-discipline rubric the redesign depends on isn't available locally.
- 3/112 scripts are UNDOCUMENTED (no docstring/header) — the estate can't explain what they do or why they exist.

## 1. Runtime (launchd daemons)
- ✅ `ai.hermes.gateway` — Telegram gateway (PID 62582)
- ✅ `ai.hermes.coordinator` — Autopilot coordinator (PID 91858)
- ❌ `ai.hermes.watchdog` — Reliability watchdog **DOWN**
- ❌ `ai.hermes.progress` — Self-improvement progress **DOWN**
- ❌ `ai.hermes.rsi` — RSI learning loop **DOWN**

## 2. Autopilot (coordinator task loop)
- Tasks: **42** — 11 done · 31 escalated · 0 active · 0 awaiting-approval (done=11, escalated=31)
- Last tick: `91858|advanced=0 reaped=0`
- **Every unfinished task (31):**
  - `79cad721` [escalated] · 2 fails — failure: memory-hygiene
  - `5be61da1` [escalated] · 2 fails — failure: health-watchdog
  - `1e091ea2` [escalated] · 2 fails — failure: repo-health
  - `5f2b2235` [escalated] · 2 fails — failure: repo-health
  - `f9a6bb0b` [escalated] · 2 fails — failure: health-watchdog
  - `bd290d3d` [escalated] · 2 fails — failure: health-watchdog
  - `b7b2fb42` [escalated] · 2 fails — signalengine pytest full suite hangs indefinitely (>3min, ne
  - `5b65dd3e` [escalated] · 2 fails — BACKLOG (tech-debt, from repo-health fix 2026-06-20): signal
  - `c3dc3d62` [escalated] · 2 fails — BACKLOG (signalengine, low-pri): the full pytest suite hangs
  - `3dcbf128` [escalated] · 2 fails — failure: health-watchdog
  - `f319366f` [escalated] · 2 fails — failure: repo-health
  - `02f1614f` [escalated] · 2 fails — failure: repo-health
  - `c34430c3` [escalated] · 2 fails — failure: health-watchdog
  - `82f3762f` [escalated] · 2 fails — failure: health-watchdog
  - `1db094d3` [escalated] · 2 fails — failure: repo-health
  - `9c6810e3` [escalated] · 3 fails — failure: health-watchdog
  - `71e3bf78` [escalated] · 3 fails — failure: health-watchdog
  - `413e5f80` [escalated] · 3 fails — failure: health-watchdog
  - `fe69ffb9` [escalated] · 2 fails — failure: health-watchdog
  - `004d594e` [escalated] · 2 fails — failure: health-watchdog
  - `67da3d13` [escalated] · 2 fails — audit the estate and full workflow and your audit and workfl
  - `b43a9c4f` [escalated] · 2 fails — who is handling this ?
  - `947e0ec8` [escalated] · 2 fails — failure: prospector generation failed (exit 1): Current dire
  - `0c69837d` [escalated] · 2 fails — failure: CRON_ERROR: prospector-daily-generation errored: Sc
  - `8541d635` [escalated] · 2 fails — failure: prospector generation exceeded 110s budget (cron ca
  - `d0e39683` [escalated] · 2 fails — failure: prospector: transient CWD race (repo rewrite) — wil
  - `f43a743d` [escalated] · 2 fails — Prospector: Status report for Prospector: read its graphify-
  - `56c534d1` [escalated] · 2 fails — Signal Engine: Status report for Signal Engine: read its gra
  - `46e51b23` [escalated] · 2 fails — Introduction Exchange: Status report for Introduction Exchan
  - `77bd5993` [escalated] · 2 fails — Haworks Platform: Status report for Haworks Platform: read i
  - `5018043d` [escalated] · 2 fails — failure: CRON_ERROR: daily-self-reflection errored: Script e

## 3. Operator surface (does the estate speak first?)
- `gateway_notify_interval`: `0`  (0 = pull-only, estate never pings first)

## 4. Self-improvement (RSI / learning loop)
- Tuner: ⚪ DISARMED (idle until armed)
- Self-signed receipts: 1 (not counted as proof)
- Improver versions logged: 1 · RSI eval-sets: 2
- Verified learning ledger: 1 receipt(s); last = PASS (23h ago)
- Autonomy trend: 67% ↘︎ 26% over 29 snapshots
- **RSI plans — the 3 dimensions the orchestrator runs:**
  - Autonomous Skill Generation: writes and verifies skills to close gap-finding loops.
  - Prompt Template Tuning: optimizes and regression-tests prompts.
  - Self-Code Refactoring: optimizes codebase helper scripts via temp worktree sandboxing.
- **RSI machinery (10 scripts — every one, with its job):**
  - `evidence_verify.py` — ⚠️ undocumented
  - `improvement-probe.sh` — Self-improvement probe: finds common gaps and files structured failure entries
  - `improver-switcher.py` — Improver versioning and swap tracking.
  - `meta-improver.py` — Core meta-improvement loop for Otto.
  - `otto-learn.py` — otto-learn — Policy management CLI for Otto's correction-learning loop.
  - `progress.py` — make self-improvement OBSERVABLE.
  - `prove_learning.py` — falsifiable proof of the operational-learning loop.
  - `prove_rsi.py` — falsifiable, hermetic proof of the RSI improvement-gate.
  - `rsi-autorun.sh` — rsi-autorun.sh — fenced, autonomous RSI self-improvement tick (cron-driven).
  - `rsi-orchestrator.py` — Recursive Self-Improvement (RSI) loop for the Hermes/Otto agent.

## 5. Self-reflection
- 4 reflections; latest `2026-06-21.md` (8m ago)

## 6. Self-healing (watchdog)
- Last run: 3m ago
- Auto-restarts performed: gateway (22h ago)
- Wedge alerts seen: coordinator_wedged (22h ago), gateway_wedged (18h ago)

## 7. Missions & milestones (the work portfolio)
- 🔧 *Prospector* — blocked
- Milestones: 5 (active=1, pending=4)

## 8. Scheduled loops (cron)
- **22 jobs registered (18 active / 4 paused) — every one:**
  - ⏸ **Run health check on all projects: check for outd**  `0 9 * * *`  ·  last: ok (3d ago)
      ↳ sh: cd ~/Documents/code && for repo in lux signalengine prospector; do ech
      ⏸ paused: superseded by repo-health-check.py (parallel, existence-aware, no || echo maskin
  - ▶️ **Summarize today's activity across all projects. **  `0 18 * * *`  ·  last: ok (5h ago)
      ↳ prompt: Summarize today's activity across all projects. List: which functions 
  - ▶️ **Run lux verify on all projects with specs. Repor**  `0 0 * * 0`  ·  last: ok (23h ago)
      ↳ sh: weekly-lux-verify.sh
  - ▶️ **hermes-config-auto-push**  `0 * * * *`  ·  last: ok (34m ago)
      ↳ sh: auto-push.sh
  - ▶️ **uncommitted-watch**  `every 360m`  ·  last: ok (3h ago)
      ↳ sh: uncommitted-watch.sh
  - ▶️ **daily-self-reflection**  `0 18 * * *`  ·  last: error (5h ago)
      ↳ sh: daily_reflection.py
      ⚠️ last_error: Script exited with code 1
stderr:
Reflection failed: [Errno 1] Operation not per
  - ▶️ **morning-briefing**  `0 9 * * *`  ·  last: ok (14h ago)
      ↳ skill: autonomous-ai-agents/otto-operating-model
  - ⏸ **otto-improvement-pulse**  `0 * * * *`  ·  last: ok (23h ago)
      ↳ sh: hourly_pulse.sh
      ⏸ paused: theater: blank-template hourly pulse superseded by the evidence ledger (Claude 2
  - ▶️ **idle-continuous-learning**  `every 30m`  ·  last: ok (8m ago)
      ↳ sh: idle-learning-run.sh
  - ▶️ **daily-strategist-audit**  `0 8 * * *`  ·  last: ok (14h ago)
      ↳ skill: autonomous-ai-agents/otto-operating-model
  - ▶️ **improvement-probe**  `every 15m`  ·  last: ok (2m ago)
      ↳ sh: improvement-probe.sh
  - ▶️ **health-watchdog**  `every 15m`  ·  last: ok (2m ago)
      ↳ sh: watchdog-cron.py
  - ▶️ **repo-health-check**  `every 120m`  ·  last: ok (43m ago)
      ↳ sh: repo-health-check.py
  - ▶️ **estate-inventory-audit**  `0 6 * * *`  ·  last: ok (16h ago)
      ↳ sh: estate-full-run.sh
  - ▶️ **idle-curiosity**  `every 30m`  ·  last: ok (11m ago)
      ↳ sh: idle-curiosity.py
  - ▶️ **prospector-daily-generation**  `0 * * * *`  ·  last: ok (34m ago)
      ↳ sh: prospector-run.sh
  - ▶️ **signal-engine-daemon-watchdog**  `*/5 * * * *`  ·  last: ok (4m ago)
      ↳ sh: signal-engine-daemon-watchdog.sh
  - ▶️ **proving-ground-audit**  `every 120m`  ·  last: error (43m ago)
      ↳ sh: proving-ground.py
      ⚠️ last_error: Script exited with code 1
stdout:
PROVING GROUND — Self-Integrity Audit (existen
  - ▶️ **queue-curator**  `*/5 * * * *`  ·  last: ok (4m ago)
      ↳ sh: queue-curate.sh
  - ⏸ **otto-dispatch**  `1-59/5 * * * *`  ·  last: ok (32h ago)
      ↳ sh: otto-dispatch.sh
  - ▶️ **pytest-orphan-cleanup**  `every 5m`  ·  last: ok (4m ago)
      ↳ sh: pytest-orphan-cleanup.sh
  - ⏸ **goal-of-the-moment**  `every 60m`  ·  last: ok (32h ago)
      ↳ sh: goal-of-the-moment.sh

## 9. Governance & founder fence
- Self-improvement OFF_SWITCH: DISARMED
- Tasks awaiting your approval (fence): 0
- Claude single-writer lane: `coordinator.py`, `config.yaml`, `plugins/otto-inbound/`, `gateway/`
- Fenced from all agents: money · identity · contract · migrations

## 10. Assets — what each is FOR (purpose from its own docstring/frontmatter)
- **Skills (89 total — every one, with what it's FOR):**
  - _~/.claude/skills (1):_
    - `graphify` — Use for any question about a codebase, its architecture, file relationships, or project content — especially when graphify-out/ exists, wher
  - _~/.hermes/skills (88):_
    - `apple/apple-notes` — Manage Apple Notes via memo CLI: create, search, edit.
    - `apple/apple-reminders` — Apple Reminders via remindctl: add, list, complete.
    - `apple/findmy` — Track Apple devices/AirTags via FindMy.app on macOS.
    - `apple/imessage` — Send and receive iMessages/SMS via the imsg CLI on macOS.
    - `apple/macos-computer-use` — |
    - `autonomous-ai-agents/agy` — Monitor, interact with, and troubleshoot agy (Antigravity / Gemini Cloud Code) coding agent sessions — log inspection, brain state, PTY inte
    - `autonomous-ai-agents/claude-code` — Continuous Claude Code consultation via persistent tmux channel (Otto's default), plus print mode and interactive PTY orchestration. Hermes 
    - `autonomous-ai-agents/codex` — Delegate coding to OpenAI Codex CLI (features, PRs).
    - `autonomous-ai-agents/hermes-agent` — Configure, extend, or contribute to Hermes Agent.
    - `autonomous-ai-agents/opencode` — Delegate coding to OpenCode CLI (features, PR review).
    - `autonomous-ai-agents/otto-operating-model` — Otto's operating model — autonomous project coordinator across Signal Engine, LUX, Prospector
    - `creative/architecture-diagram` — Dark-themed SVG architecture/cloud/infra diagrams as HTML.
    - `creative/ascii-art` — ASCII art: pyfiglet, cowsay, boxes, image-to-ascii.
    - `creative/ascii-video` — ASCII video: convert video/audio to colored ASCII MP4/GIF.
    - `creative/baoyu-infographic` — Infographics: 21 layouts x 21 styles (信息图, 可视化).
    - `creative/claude-design` — Design one-off HTML artifacts (landing, deck, prototype).
    - `creative/comfyui` — Generate images, video, and audio with ComfyUI — install, launch, manage nodes/models, run workflows with parameter injection. Uses the offi
    - `creative/design-md` — Author/validate/export Google's DESIGN.md token spec files.
    - `creative/excalidraw` — Hand-drawn Excalidraw JSON diagrams (arch, flow, seq).
    - `creative/humanizer` — Humanize text: strip AI-isms and add real voice.
    - `creative/manim-video` — Manim CE animations: 3Blue1Brown math/algo videos.
    - `creative/p5js` — p5.js sketches: gen art, shaders, interactive, 3D.
    - `creative/popular-web-designs` — 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS.
    - `creative/pretext` — Use when building creative browser demos with @chenglou/pretext — DOM-free text layout for ASCII art, typographic flow around obstacles, tex
    - `creative/sketch` — Throwaway HTML mockups: 2-3 design variants to compare.
    - `creative/songwriting-and-ai-music` — Songwriting craft and Suno AI music prompts.
    - `creative/touchdesigner-mcp` — Control a running TouchDesigner instance via twozero MCP — create operators, set parameters, wire connections, execute Python, build real-ti
    - `data-science/jupyter-live-kernel` — Iterative Python via live Jupyter kernel (hamelnb).
    - `devops/kanban-orchestrator` — Decomposition playbook + anti-temptation rules for an orchestrator profile routing work through Kanban. The "don't do the work yourself" rul
    - `devops/kanban-worker` — Pitfalls, examples, and edge cases for Hermes Kanban workers. The lifecycle itself is auto-injected into every worker's system prompt as KAN
    - `dogfood` — Exploratory QA of web apps: find bugs, evidence, reports.
    - `dropped-ball-prevention` — Otto's hard rules from the 16-dropped-balls session (2026-06-18) — when a rule is stated twice, relay gaps are dropped balls, submit-yoursel
    - `email/himalaya` — Himalaya CLI: IMAP/SMTP email from terminal.
    - `estate-ground-truth-probe` — When the user asks for "estate", "estate state", "estate audit", "ground truth", "what's actually running", "real state", "actual state", "p
    - `external-audience-writing` — Write documents for audiences OUTSIDE the project — hiring managers (CVs, cover letters), potential contributors (READMEs, package intros), 
    - `github/codebase-inspection` — Inspect codebases w/ pygount: LOC, languages, ratios.
    - `github/github-auth` — GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login.
    - `github/github-code-review` — Review PRs: diffs, inline comments via gh or REST.
    - `github/github-issues` — Create, triage, label, assign GitHub issues via gh or REST.
    - `github/github-pr-workflow` — GitHub PR lifecycle: branch, commit, open, CI, merge.
    - `github/github-repo-management` — Clone/create/fork repos; manage remotes, releases.
    - `lux-proof-driven-development` — PDD: Write formal specifications. Prove correctness. Auto-verify every change. TDD + mathematical guarantees. Use this for ALL code changes.
    - `lux-proof-driven-development/popdd-on-lux` — Add POPDD (Proof of Proof-Driven Development) DecisionReceipts to any project. Cryptographically chain agent actions to verification results
    - `lux-proof-driven-development/popdd-python-prototype-archived-2026-06-17` — ARCHIVED — Python prototype of POPDD DecisionReceipts. SUPERSEDED by the TypeScript implementation in ~/Documents/code/lux/src/proof/receipt
    - `media/gif-search` — Search/download GIFs from Tenor via curl + jq.
    - `media/heartmula` — HeartMuLa: Suno-like song generation from lyrics + tags.
    - `media/songsee` — Audio spectrograms/features (mel, chroma, MFCC) via CLI.
    - `media/youtube-content` — YouTube transcripts to summaries, threads, blogs.
    - `mlops/evaluation/lm-evaluation-harness` — lm-eval-harness: benchmark LLMs (MMLU, GSM8K, etc.).
    - `mlops/evaluation/weights-and-biases` — W&B: log ML experiments, sweeps, model registry, dashboards.
    - `mlops/huggingface-hub` — HuggingFace hf CLI: search/download/upload models, datasets.
    - `mlops/inference/llama-cpp` — llama.cpp local GGUF inference + HF Hub model discovery.
    - `mlops/inference/vllm` — vLLM: high-throughput LLM serving, OpenAI API, quantization.
    - `mlops/models/audiocraft` — AudioCraft: MusicGen text-to-music, AudioGen text-to-sound.
    - `mlops/models/segment-anything` — SAM: zero-shot image segmentation via points, boxes, masks.
    - `note-taking/obsidian` — Read, search, create, and edit notes in the Obsidian vault.
    - `otto-coordinator-rules-2026-06-18` — Otto's operating rules learned in the 20+ dropped-balls session — the substrate of corrections that must persist across sessions
    - `popdd-inline-attestation` — Integrate POPDD receipts inline into every verify/edit action. Not post-hoc scripts — per-action, continuous, chained attestation.
    - `productivity/airtable` — Airtable REST API via curl. Records CRUD, filters, upserts.
    - `productivity/google-workspace` — Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python.
    - `productivity/maps` — Geocode, POIs, routes, timezones via OpenStreetMap/OSRM.
    - `productivity/nano-pdf` — Edit PDF text/typos/titles via nano-pdf CLI (NL prompts).
    - `productivity/notion` — Notion API + ntn CLI: pages, databases, markdown, Workers.
    - `productivity/ocr-and-documents` — Extract text from PDFs/scans (pymupdf, marker-pdf).
    - `productivity/powerpoint` — Create, read, edit .pptx decks, slides, notes, templates.
    - `productivity/teams-meeting-pipeline` — Operate the Teams meeting summary pipeline via Hermes CLI — summarize meetings, inspect pipeline status, replay jobs, manage Microsoft Graph
    - `research/arxiv` — Search arXiv papers by keyword, author, category, or ID.
    - `research/blogwatcher` — Monitor blogs and RSS/Atom feeds via blogwatcher-cli tool.
    - `research/llm-wiki` — Karpathy's LLM Wiki: build/query interlinked markdown KB.
    - `research/polymarket` — Query Polymarket: markets, prices, orderbooks, history.
    - `research/research-paper-writing` — Write ML papers for NeurIPS/ICML/ICLR: design→submit.
    - `smart-home/openhue` — Control Philips Hue lights, scenes, rooms via OpenHue CLI.
    - `social-media/xurl` — X/Twitter via xurl CLI: post, search, DM, media, v2 API.
    - `software-development/estate-management` — Estate lifecycle: inventory, drift detection, optimization scanning, auto-remediation, and daily audit cadence for complex Hermes configurat
    - `software-development/hermes-agent-skill-authoring` — Author in-repo SKILL.md: frontmatter, validator, structure.
    - `software-development/hermes-self-audit` — Generate a complete audit of the Hermes setup — architecture, config, state, integrations, and task lifecycle.
    - `software-development/node-inspect-debugger` — Debug Node.js via --inspect + Chrome DevTools Protocol CLI.
    - `software-development/plan` — Plan mode: write an actionable markdown plan to .hermes/plans/, no execution. Bite-sized tasks, exact paths, complete code.
    - `software-development/project-health-audit` — Periodic health check across multiple projects: outdated dependencies, npm audit vulnerabilities, test coverage scan, complexity hotspots. D
    - `software-development/python-debugpy` — Debug Python: pdb REPL + debugpy remote (DAP).
    - `software-development/requesting-code-review` — Pre-commit review: security scan, quality gates, auto-fix.
    - `software-development/simplify-code` — Parallel 3-agent cleanup of recent code changes.
    - `software-development/spike` — Throwaway experiments to validate an idea before build.
    - `software-development/systematic-debugging` — 4-phase root cause debugging: understand bugs before fixing.
    - `software-development/test-driven-development` — TDD: enforce RED-GREEN-REFACTOR, tests before code.
    - `supervised-process-contract` — How to supervise long-running daemons in Otto (launchd + thin wrapper, exit-cause captured by parent, circuit breaker, stderr split, OOM hyp
    - `task-resilience` — Auto-recover interrupted tasks, dispatch parallel work without blocking the user, size subagents to stay interruptible, fix defects before d
    - `yuanbao` — Yuanbao (元宝) groups: @mention users, query info/members.
- **Gateway plugins (1):**
  - `otto-inbound` — otto-inbound — inbound Telegram bridge + ground-truth self-knowledge (Switch 2).
- **Specs (4):**
  - `ESTATE-V2-ARCHITECTURE.md` — Estate v2 — One Loop Runtime
  - `execution-grounded-warroom.md` — Execution-Grounded Multi-Agent War Room Spec — v2 (NET-SAFE)
  - `otto-system` — (directory)
  - `policy-enforcer-redesign.md` — Policy Enforcer Redesign — Structurally Sound Approach
- **Scripts: 78 .py + 34 .sh — every one, with its purpose:**
  - `alert-resolver.py` — Alert Resolution System — PROBE-VERIFIED resolution (Fire 4-LF fix).
  - `append-regression-trend.py` — Appends coverage % + timestamp to regression-trend.jsonl.
  - `audit-trail.py` — Audit Trail Recorder.
  - `claude_handback_gate.py` — claude_handback_gate — stop Otto from self-fixing an issue Claude already owns.
  - `conflict-resolver.py` — F3 — Conflict Resolution Engine for Otto.
  - `coordinator.py` — the persistent autonomous-estate coordinator (Phases 2-5).
  - `cross-project-bridge.py` — Cross-Project Pattern Bridge.
  - `daily_reflection.py` — ⚠️ undocumented (no docstring/header)
  - `dispatch-guard.py` — Pre-dispatch enforcement for delegate_task.
  - `dispatch_gate.py` — Dispatch gate — structural guard against asking when I should be doing.
  - `dropped-ball-tracker.py` — dropped-ball-tracker — telemetry probe for Otto's own failures (Ball 19 addendum).
  - `estate-audit.py` — the FULL estate audit, reproducible on command (Telegram: "Otto audit").
  - `estate-auto-remediation.py` — Estate Auto-Remediation — takes the optimization report and actually
  - `estate-drift-detector.py` — Estate Drift Detector — compares today's inventory to last snapshot.
  - `estate-inventory.py` — Estate Inventory — complete map of every component.
  - `estate-optimization-scanner.py` — Estate Optimization Scanner — reads all analysis outputs from the
  - `estate_alert.py` — estate_alert — gateway-INDEPENDENT operator alerting.
  - `estate_watchdog.py` — independent supervisor so Telegram is never silently down.
  - `eval-confidence.py` — F2 — Eval confidence scoring + divergence detection for Otto.
  - `evidence_verify.py` — ⚠️ undocumented (no docstring/header)
  - `flight.py` — the MISSION ENGINE (autopilot) for the autonomous estate.
  - `gap-finding.py` — Gap-Finding Engine (#3 of the Continuous Learning Build).
  - `gateway_crashloop_watch.py` — gateway_crashloop_watch — detect a crash-looping gateway and alert the operator.
  - `gateway_preflight.py` — gateway_preflight — validate edit-prone gateway modules BEFORE going live.
  - `hermes_claims.py` — Dropped-ball watchdog — catches self-certification at the substrate level.
  - `hermes_fingerprint.py` — Canonical alert/event fingerprinting — single source of truth.
  - `hermes_gateway.py` — hermes_gateway.gateway_liveness — load-immune gateway liveness.
  - `hermes_queue.py` — Hermes relay queue — Otto-side ingestion of cron/probe/watchdog events.
  - `hermes_subprocess.py` — hermes_subprocess.run_bounded — the ONE safe way to run a child with a deadline.
  - `idle-consolidation.py` — Idle Consolidation Engine (#1 of the Continuous Learning Build).
  - `idle-curiosity.py` — Idle Curiosity Pass — runs every 2h during idle time, does genuine learning work.
  - `improver-switcher.py` — Improver versioning and swap tracking.
  - `known_classes.py` — known_classes — the proactive dispatcher's decision table.
  - `memory-hygiene.py` — memory-hygiene — enforce a last_verified stamp on every memory entry. Item 6.
  - `memory_retrieval.py` — Memory retrieval — Phase 3: embedding-based retrieval layer.
  - `mentor-reflect.py` — mentor-reflect — Claude is Otto's permanent mentor (continuous, not session-bound).
  - `meta-improver.py` — Core meta-improvement loop for Otto.
  - `near-miss-analyzer.py` — Near-Miss Analyzer: finds patterns that almost triggered but didn't.
  - `otto-correction-gate.py` — structural enforcement for the most common dropped balls.
  - `otto-correction-scan.py` — Continuous-audit trigger — operationalizes the user's rule:
  - `otto-dispatch.py` — otto-dispatch — the proactive relay step (Ball 17 + proactive-substrate).
  - `otto-introspect.py` — Introspection surface for Otto's operational state.
  - `otto-learn.py` — otto-learn — Policy management CLI for Otto's correction-learning loop.
  - `otto-why.py` — Rationale reconstruction for Otto decisions.
  - `outcome-accelerator.py` — Outcome Accelerator: logs every completed task as a mini-outcome record.
  - `outcome-evaluator.py` — F2-aware outcome evaluator.
  - `policy-composer.py` — Slope maximisation via policy co-firing analysis.
  - `policy-enforcer.py` — Runtime pre-action gate.
  - `post-claim-verifier.py` — Post-claim verifier — runs automatically after every significant claim.
  - `progress.py` — make self-improvement OBSERVABLE.
  - `proof-probe.py` — ⚠️ undocumented (no docstring/header)
  - `prove_learning.py` — falsifiable proof of the operational-learning loop.
  - `prove_rsi.py` — falsifiable, hermetic proof of the RSI improvement-gate.
  - `proving-ground-probe.py` — proving-ground-probe — READ-ONLY verdict for the proving-ground failure class.
  - `proving-ground.py` — self-integrity auditor (existence-aware: MISSING != PASS).
  - `reflect-on-correction.py` — Post-correction reflection runner.
  - `repo-health-check.py` — Multi-repo health check — PARALLEL, budgeted (Ball: 5c).
  - `repo-health-probe.py` — repo-health-probe — READ-ONLY verifier for the repo-health failure class.
  - `route.py` — route(role, prompt) — per-role provider rotation for the autonomous estate.
  - `rsi-orchestrator.py` — Recursive Self-Improvement (RSI) loop for the Hermes/Otto agent.
  - `self-detect.py` — Self-detected failure handler (B).
  - `self-healer.py` — Self-Healer: reads watchdog alerts and auto-fixes what it CAN — honestly.
  - `self-regression.py` — Self-Regression Engine (#2 of the Continuous Learning Build).
  - `set-cockpit-menu.py` — give the operator a curated, tappable Otto cockpit in Telegram.
  - `setup-embedding-model.py` — Download the ONNX embedding model for the F1 retrieval layer.
  - `skill-hygiene.py` — skill-hygiene — flag orphan skills (created, never wired). Item 6.
  - `test_coordinator.py` — Proof for coordinator.py — Phases 2-5 of the heavenly-estate design.
  - `test_cost.py` — Hermetic proof of the cost + seamlessness controls in coordinator.py:
  - `test_flight.py` — Hermetic proof of the Mission Engine (flight.py): a mission is plotted, flown
  - `test_resolution_disease.py` — Deterministic proof for the resolution-disease fix (war-room root cause).
  - `test_route.py` — Proof for route.py — Phase 1 of the heavenly-estate design.
  - `trend-analyzer.py` — Cross-session Trend Analyzer.
  - `warroom.py` — convene an Execution-Grounded Multi-Agent War Room.
  - `warroom_eval.py` — Execution-Grounded War Room CI Duel Harness (NET-SAFE).
  - `watchdog-cron.py` — cron-boundary wrapper for watchdog.py (exit-contract fix).
  - `watchdog-state-probe.py` — watchdog-state-probe — read-only health verdict from the watchdog's OWN recorded state.
  - `watchdog.py` — Continuous Health Watchdog — GRADED on invariants (exit-code honest).
  - `weekly-progress-digest.py` — weekly-progress-digest — the visible-evidence dashboard the user asked for.
  - `alert-resolver-probe.sh` — alert-resolver-probe — receipt for the Fire 4-LF false-clear fix.
  - `auto-push.sh` — no-agent config auto-push
  - `closed-loop-proof.sh` — closed-loop-proof — Item 9. Proves the WHOLE relay loop end-to-end in one isolated
  - `coordinator-daemon.sh` — Launchd wrapper for the autonomous coordinator. launchd gives a bare environment:
  - `daemon-stability-probe.sh` — daemon-stability-probe — fires when signal_engine.daemon restarts 2+ times in 1h.
  - `dropped-ball-probe.sh` — dropped-ball-probe — receipt for the dropped-ball watchdog (hermes_claims.py).
  - `estate-full-run.sh` — Estate Full Report — runs the entire estate pipeline:
  - `git-pre-commit-hook.sh` — pre-commit guard for the Hermes estate. Two jobs:
  - `goal-of-the-moment.sh` — goal-of-the-moment.sh
  - `hourly_pulse.sh` — Otto Hourly Improvement Pulse
  - `idle-learning-probe.sh` — idle-learning-probe — fires (exit 2) when idle-continuous-learning has exited
  - `idle-learning-run.sh` — Idle-Time Self-Improvement Pipeline (resilient).
  - `improvement-probe.sh` — Self-improvement probe: finds common gaps and files structured failure entries
  - `launch-report.sh` — Launch status report — aggregated view for all projects.
  - `memory-capacity-probe.sh` — memory-capacity-probe — substrate prevention for the "memory tool fails to add" wall.
  - `methodology-probe.sh` — methodology-probe.sh — Watches for POPDD/PDD compliance drift.
  - `otto-correction-scan-probe.sh` — otto-correction-scan-probe — receipt for the continuous-audit trigger.
  - `otto-dispatch-probe.sh` — otto-dispatch-probe — receipt for the PROACTIVE dispatcher (registry + auto-claim + dedup).
  - `otto-dispatch.sh` — otto-dispatch.sh — cron wrapper for the Otto relay step (Ball 17).
  - `popdd-init.sh` — popdd-init.sh — Initialize/append a POPDD session receipt to today's chain.
  - `progress-snapshot.sh` — progress-snapshot.sh — decoupled autonomy-trend snapshot (cron-driven).
  - `prospector-run.sh` — prospector-run.sh — hourly guard/liveness probe for prospector generation (Ball: 5b).
  - `proving-ground-probe.sh` — proving-ground-probe — receipt for the existence-aware audit (Ball 19).
  - `publish-lux-stack.sh` — publish-lux-stack.sh — Automated publish of LUX/POPDD packages
  - `pytest-orphan-cleanup.sh` — pytest-orphan-cleanup.sh — kills pytest processes whose PPID is 1
  - `queue-curate.sh` — queue-curate — Otto's curation pass over the relay queue (FIRE 0 consumer).
  - `queue-probe.sh` — queue-probe — FIRE 0 receipt.
  - `rsi-autorun.sh` — rsi-autorun.sh — fenced, autonomous RSI self-improvement tick (cron-driven).
  - `sign-interpreters.sh` — sign-interpreters.sh — ad-hoc codesign the Python interpreters the estate runs, so macOS stops
  - `signal-engine-daemon-watchdog.sh` — signal-engine-daemon-watchdog — silent when healthy.
  - `signal-engine-watchdog-probe.sh` — signal-engine-watchdog-probe — FIRE 1 loop-closer.
  - `uncommitted-watch.sh` — uncommitted-watch.sh — silent watchdog for uncommitted work.
  - `watchdog-probe.sh` — watchdog-probe — receipt for exit-code grading (hidden-restart-loop fix).
  - `weekly-lux-verify.sh` — weekly-lux-verify.sh — Weekly `lux verify` across all projects with specs.

## 11. Dependencies & runtimes
- **AI model dependencies (per-role provider fallback chains):**
  - coordinator: deepseek/deepseek-v4-flash → claude-cli
  - strategist: claude-cli → agy-cli → deepseek/deepseek-v4-pro
  - executor: minimax/MiniMax-M3 → deepseek/deepseek-v4-flash → gemini/gemini-2.5-flash
- Daemon interpreter (`/usr/local/opt/python@3.14/bin/python3.14`): Python 3.14.6
- Gateway venv (`hermes-agent/venv`): Python 3.11.15 · 135 packages installed
- Declared dependency manifests: `hermes-agent/pyproject.toml`, `recovery/requirements-frozen.txt` (136 pinned)
- **Direct Python dependencies (28 — every one):**
  - `openai==2.24.0`
  - `certifi==2026.5.20`
  - `python-dotenv==1.2.2`
  - `fire==0.7.1`
  - `httpx[socks]==0.28.1`
  - `rich==14.3.3`
  - `tenacity==9.1.4`
  - `pyyaml==6.0.3`
  - `ruamel.yaml==0.18.17`
  - `requests==2.33.0`
  - `jinja2==3.1.6`
  - `pydantic==2.13.4`
  - `prompt_toolkit==3.0.52`
  - `croniter==6.0.0`
  - `packaging==26.0`
  - `Markdown==3.10.2`
  - `PyJWT[crypto]==2.13.0`
  - `urllib3>=2.7.0,<3`
  - `tzdata==2025.3; sys_platform == 'win32'`
  - `is this PID alive`
  - `psutil==7.2.2`
  - `websockets==15.0.1`
  - `pathspec==1.1.1`
  - `fastapi>=0.104.0,<1`
  - `uvicorn[standard]>=0.24.0,<1`
  - `ptyprocess>=0.7.0,<1; sys_platform != 'win32'`
  - `pywinpty>=2.0.0,<3; sys_platform == 'win32'`
  - `Pillow==12.2.0`

## 12. Git repos (uncommitted work)
- 1 repos dirty (top): .hermes=28
