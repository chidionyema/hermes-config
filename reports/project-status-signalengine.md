# Project Status — Signal Engine

_Generated 2026-06-22, re-verified against disk 2026-06-24 (all figures re-confirmed, graph still
in sync with HEAD). Source of truth for this report:
`/Users/chidionyema/Documents/code/signalengine/graphify-out/graph.json` +
`.graphify_analysis.json`. Per earned-trust discipline, every claim below cites the artifact it
came from; nothing is asserted from memory._

## Provenance / freshness

- **Graph built at commit:** `fddef58` (`graph.json` → `built_at_commit`:
  `fddef58732ac868a16e444c993a3594f24ad30fd`).
- **Current repo HEAD:** `fddef58` (`git rev-parse HEAD`). **Graph is in sync with HEAD** — no
  drift between the analyzed snapshot and the working tree.
- Graph artifact mtime: `Jun 21 12:43 2026` (`stat graphify-out/graph.json`).
- HEAD commit: `fddef58 2026-06-20 "test: mark heavy fitter/fit_universe tests @slow to fix
  repo-health timeout"` (`git log -1`).
- No `GRAPH_REPORT.md` exists in `graphify-out/`; the machine artifacts (`graph.json`,
  `.graphify_analysis.json`) were read directly.

## Scale (graph + repo)

- **2214 nodes, 5169 edges** in the knowledge graph (`graph.json` node/link counts).
- **128 detected communities** (`.graphify_analysis.json` → `communities`).
- Repo: **97 Python files** under `signal_engine/`, **~15,827 LOC**, **53 test files** under
  `tests/` (`find`/`wc`).
- Graphify analysis cost for this build: 7,593 input / 10,518 output tokens
  (`analysis → tokens`).

## God nodes (highest-degree hubs — the load-bearing core)

From `.graphify_analysis.json → gods` (degree = total edges touching the node):

| Rank | Component | Degree | Role |
|------|-----------|--------|------|
| 1 | `CostModel` (`costs/cost_model.py`) | 117 | Transaction-cost model — the most-connected node in the system |
| 2 | `get_settings()` (`config.py`) | 116 | Global settings accessor — config reaches almost everything |
| 3 | `StrategyMeta` (`strategies/base.py`) | 108 | Strategy metadata base |
| 4 | `Strategy` (`strategies/base.py`) | 105 | Strategy base class |
| 5 | `FitStore` (`research/fit_store.py`) | 90 | Fitted-model persistence/lookup |
| 6 | `PaperVenue` (`execution/paper.py`) | 65 | Paper-trading execution venue |
| 7 | `KillSwitch` (`execution/killswitch.py`) | 64 | Trading kill switch / safety gate |
| 8 | `ExecutionVenue` (`execution/venue.py`) | 51 | Venue abstraction |
| 9 | `FittedModel` (`research/fit_store.py`) | 47 | Fitted-model value object |
| 10 | `LiveFeedIngestor` (`data/live_feed.py`) | 43 | Live market-data ingestion |

**Read:** the architecture's gravity centers are **costs**, **config**, **strategy base**, and
the **fit/store research layer** — consistent with the memory note that the fit/infer split and
`FitStore` are central ([[scale-fit-infer-architecture]]). Two safety-critical nodes (`KillSwitch`
deg 64, `ExecutionVenue` deg 51) are also top hubs, i.e. the execution-safety layer is
well-integrated rather than bolted on.

## Subsystems (top communities by size, themed from node prefixes)

| Community | Size | Dominant theme |
|-----------|------|----------------|
| C0 | 75 | execution + Binance brokers (live/testnet) |
| C1 | 62 | execution + cost model + their tests |
| C2 | 50 | validation + tests |
| C3 | 49 | api / obs (observability) |
| C4 | 49 | scheduler + execution + signals |
| C5 | 48 | docs + specs |
| C6 | 48 | reconciliation + execution |
| C7 | 43 | popdd (PDD/prompt-driven-dev docs) |
| C8 | 42 | execution + portfolio |
| C9 | 40 | learning + validation |
| C10 | 38 | ingest + signals |
| C11 | 37 | features + signals |

Top-level packages present (`ls signal_engine/`): `agents, costs, data, execution, features,
learning, obs, ops, portfolio, reconciliation, research, scheduler, signals, strategies,
validation` plus `cli.py`, `config.py`, `control.py`, `daemon.py`.

## Cohesion (community internal density — `analysis → cohesion`)

- Most communities sit in the **0.05–0.13** range (loosely-coupled, which is normal for a
  layered Python service — most edges cross module boundaries via the config/cost hubs).
- **Outlier C24 = 0.255**, ~2× the next densest — the single most internally self-contained
  cluster in the graph. (Worth a look if isolating/extracting a module; it is the tightest seam.)
- Lowest cohesion is C5 (`0.0505`, the docs/specs cluster) — expected, since docs reference many
  unrelated code areas.

## Surprises (non-obvious / inferred cross-cutting links — `analysis → surprises`)

- `DataFrame → FitStore` and `DataFrame → StrategyMeta` (confidence **INFERRED**, relation
  `uses`): pandas `DataFrame` is a peripheral node that reaches two hubs, bridging separate
  communities. These are inferred, not explicit in source — flagged as a hidden coupling: the
  research/strategy hubs are tied to raw `DataFrame` shape across `tests/` and
  `signal_engine/research/`, `strategies/base.py`. **HYPOTHESIS:** this is the cross-sectional
  vectorization coupling noted in memory ([[scale-fit-infer-architecture]]); confirm by reading
  the `DataFrame` usage at `research/fit_store.py` and `strategies/base.py`.
- `Aider Kickoff Instructions (docs/AIDER_KICKOFF.txt) → Mean Reversion Strategy` /
  `→ Numeric Features` (confidence **EXTRACTED**): doc↔code references — the kickoff doc still
  points at live strategy/feature modules, i.e. the doc layer tracks real code.

## Caveats / unproven items

- Subsystem **themes are derived** by me from node-name prefixes (first underscore-token
  frequency per community), not labeled by graphify — directionally reliable but not authoritative
  per-node.
- This report describes **graph structure only**. It does **not** assert test pass/fail status,
  runtime health, or correctness — none of that is in the graph artifacts. For live/daemon health
  see [[signal-engine-daemon-entrypoint]]; for the uncommitted optimization-layer review state see
  [[uncommitted-optimization-layer-review]].
- The two `DataFrame → hub` links are **INFERRED** by the analyzer (their own `confidence` field),
  so treat as leads, not facts.
