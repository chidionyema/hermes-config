# Project Status — Signal Engine

_Read-only status heartbeat, grounded in the graphify knowledge graph. Generated 2026-06-22._
_Source repo: `/Users/chidionyema/Documents/code/signalengine` · branch `salvage/c9-c10-m7-relocate` · HEAD `fddef58` (2026-06-20)._

## How this was produced
No `GRAPH_REPORT.md` exists in `graphify-out/`; the status below is derived directly from the
persisted graph artifacts built 2026-06-21:
- `graphify-out/graph.json` — full graph (**2,214 nodes / 5,169 edges**)
- `graphify-out/.graphify_analysis.json` — god nodes, 128 communities, cohesion, surprises, token metrics
- `graphify-out/manifest.json` — file-level inventory

This is a read-only, low-risk objective — no code was changed.

## Architecture (from god nodes — highest-connectivity hubs)
The graph's load-bearing types confirm the engine is organised around cost-aware strategy execution:

| Hub (god node) | Degree | Role |
|---|---|---|
| `costs.cost_model.CostModel` | 117 | Transaction-cost model — the most central type; cost-awareness pervades the engine |
| `signal_engine.config.get_settings` | 116 | Central config accessor wired throughout |
| `strategies.base.StrategyMeta` / `Strategy` | 108 / 105 | Strategy abstraction + registry metadata |
| `research.fit_store.FitStore` | 90 | Fitted-model store (research → live handoff) |
| `execution.paper.PaperVenue` | 65 | Paper-trading venue |
| `execution.killswitch.KillSwitch` | 64 | Risk kill-switch |
| `execution.venue.ExecutionVenue` | 51 | Venue abstraction (paper/live brokers) |
| `data.live_feed.LiveFeedIngestor` | 43 | Live market-data ingestion |

## Module map (`signal_engine/` packages)
`agents`, `costs`, `data` (ingest: ccxt/yfinance/stooq/news/worldview), `execution`
(oms, pretrade, stoploss, killswitch, brokers: binance live/testnet, paper), `features`,
`learning` (lifecycle, promotion), `obs`, `ops`, `portfolio`, `reconciliation`, `research`
(fit_store), `scheduler`, `signals`, `strategies` (base + library), `validation`.
Plus surfaces: `api/app.py` (signals API), `dashboard/app.py`, and `specs/` (.lux specs:
`calculate_fee`, `target_notional`).

## Communities (128 detected — largest clusters)
The graph partitions into coherent subsystems; the largest:
- **C0 (75)** — Binance live broker integration
- **C1 (62)** — cost model / cost breakdown / cost config
- **C2 (50)** — learning lifecycle + promotion config
- **C3 (49)** — signals API (`api/app.py`, active-signals)
- **C4 (49)** — OMS / order execution
- **C5 (48)** — venue specs/docs (alpaca, binance)
- **C6 (48)** — kill-switch / drawdown guard
- **C8 (42)** — pre-trade checks
- **C9–C13** — learning init, ingest, features (structure / numeric / worldview)

Overall cohesion is low per-community (most clusters 0.05–0.13), i.e. a broad, loosely-coupled
codebase with many specialised modules rather than a few tight monoliths — expected for a
multi-strategy engine spanning data, research, execution, and risk.

## Notable cross-links (graph "surprises")
- `DataFrame → FitStore` and `DataFrame → StrategyMeta` (inferred data-flow couplings via tests).
- `docs/AIDER_KICKOFF.txt → Mean Reversion Strategy / Numeric Features / Strategy Base` — the
  Aider-delegated work (per founder-fence override) is traceable into the strategy library and
  feature code in the graph.

## Tests
- `tests/` holds **50 test files / ~309 `test_*` functions**; **14** files carry `@slow` markers
  (heavy fitter / fit_universe tests deliberately marked slow per HEAD commit `fddef58` to keep
  repo-health under timeout).

## Read-out
- **Shape is healthy and intentional:** cost model + config + strategy base are the true centre of
  gravity; risk controls (killswitch, pretrade, stoploss) and execution venues are first-class,
  well-connected subsystems — appropriate for a money-adjacent trading engine.
- **Live/broker surface present:** Binance live + testnet brokers and paper venue all in-graph.
- **Branch note:** currently on a salvage/relocate branch (`salvage/c9-c10-m7-relocate`), not a
  mainline — consistent with prior notes that the M7 money rail / remainder was delegated and is
  being reintegrated. Verify-hard-on-return still applies before any money-path trust.

## Provenance / metrics
- Graph build token cost: 7,593 in / 10,518 out (DeepSeek backend, per rollout).
- Artifacts dated 2026-06-21; this report is a periodic read-only heartbeat, not a code change.
- Re-verified 2026-06-22 against live artifacts: graph still **2,214 nodes / 5,169 edges**,
  **128 communities**, god-node degrees unchanged (CostModel 117 / get_settings 116 /
  StrategyMeta 108), branch `salvage/c9-c10-m7-relocate` @ `fddef58`. No drift since last build.
