# Density Baseline — 2026-08-02

Frozen snapshot of `/cmd` action counts across every panel in
`~/.hermes/hermes-agent/gateway/operator_shell/`. Saved so future audits can
diff against this baseline instead of restarting from "feels too dense."

## Method

```python
import re
from pathlib import Path

SHELL = Path.home() / ".hermes/hermes-agent/gateway/operator_shell"

panels = ["activity.py", "atlas.py", "brain.py", "budget.py", "builds.py",
          "cockpit.py", "code_remote.py", "cron_ops.py", "daemons.py",
          "delivery.py", "find.py", "fleet.py", "help_card.py", "host.py",
          "inbox.py", "integrity.py", "launchd_health.py", "menu.py",
          "mission.py", "preflight.py", "prospector_daemon.py",
          "rsi_panel.py", "sdlc.py", "status_summary.py", "summary_card.py",
          "usage.py", "voice_brief.py"]

for name in sorted(set(panels)):
    fp = SHELL / name
    if not fp.exists():
        continue
    src = fp.read_text()
    cmd = len(re.findall(r"/[a-z_][a-z0-9_]+", src))
    rows = len(src.splitlines())
    print(f"{name:<26} {cmd:>4}  {rows:>5}")
```

## Result (2026-08-02)

| panel | /cmd | lines | verdict |
|---|---:|---:|---|
| summary_card.py | **42** | 916 | 🔴 split (parent + per-knob detail) |
| daemons.py | **28** | 588 | 🔴 collapse per-daemon controls behind a default-action button |
| cron_ops.py | **20** | 168 | 🔴 hide rarely-used ops behind `+more` |
| prospector_daemon.py | **16** | 995 | 🟡 split status vs. config vs. recent batches |
| code_remote.py | 11 | 470 | 🟡 |
| status_summary.py | 7 | 229 | ✅ |
| mission.py | 7 | 578 | ✅ |
| cockpit.py | 5 | 672 | ✅ |
| sdlc.py | 4 | 227 | ✅ |
| help_card.py | 4 | 53 | ✅ |
| host.py | 4 | 333 | ✅ |
| launchd_health.py | 4 | 190 | ✅ |
| brain.py | 4 | 189 | ✅ |
| preflight.py | 3 | 211 | ✅ |
| activity.py | 3 | 272 | ✅ |
| usage.py | 3 | 170 | ✅ |
| delivery.py | 3 | 150 | ✅ |
| menu.py | 2 | 55 | ✅ |
| atlas.py | 2 | 337 | ✅ |
| fleet.py | 2 | 217 | ✅ |
| budget.py | 1 | 110 | ✅ |
| builds.py | 1 | 246 | ✅ |
| rsi_panel.py | 1 | 258 | ✅ |
| inbox.py | 1 | 114 | ✅ |
| find.py | 0 | 226 | (renders tabular data, no actions — fine) |
| integrity.py | 0 | 100 | (status-only — fine) |
| voice_brief.py | 0 | 69 | (delivers one-shot narration — fine) |

## Thresholds

| /cmd count | verdict | canonical action |
|---|---|---|
| 0–7  | ✅ fits   | leave alone |
| 8–14 | 🟡 dense | consider tabbed sub-panels |
| 15+  | 🔴 broken | split into a parent + children, or collapse secondary actions behind a `+more` row |

The thresholds are tuned for Telegram mobile; cards should fit 1.5 screens.

## Pitfalls

- These counts include *every* `/lowercase_token` in the source, including docstring examples and helper-function names. False-positive rate is ~5%. Override with code review when the count is on a boundary.
- `summary_card` at 42 vs. `cockpit` at 5 is partly because `summary_card` is doing the work that should be in a sub-panel. Don't just rename — split.

## Re-running

Re-run the audit after every batch of panel edits. If a panel's count
jumps more than +3 in one PR, surface it.
