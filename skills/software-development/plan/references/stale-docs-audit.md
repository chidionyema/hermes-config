# Stale-Docs Audit Pattern

Use this when a handover document, README, or spec claims a codebase is in a certain state — but you want to verify against actual files before planning work.

## Trigger

- Handover doc says "feature X is missing" — check if it's actually there
- Handover doc says "test suite is broken" — run it yourself
- Handover doc says "only N tests pass" — count what actually passes
- The doc has a date older than 2-3 days in an active development phase

## Exact Commands

### Test suite health
```bash
ulimit -n 2048  # avoid "Too many open files" on macOS
cd /path/to/project && python -m pytest -q --tb=short --no-header 2>&1 | tail -5
```

### Features exist?
```bash
grep -rn "keyFeature\|ClassName\|function_name" src/ --include="*.py" --include="*.cs" --include="*.ts" -l | head -5
```

### Check the file system for expected artifacts
```bash
ls -la store/dossiers/ | wc -l  # how many dossiers exist
ls -la data_store/*.duckdb      # does the DB have real data?
ls -la fixtures/                # does the golden set exist?
```

### Check for CORS/config/auth that docs say are missing
```bash
grep -c "UseCors\|AddCors" Program.cs  # 0 = missing as claimed
grep -c "X-Internal-Key\|FixedTimeEquals" Program.cs  # 0 = auth not implemented
```

## Parallel Audit Pattern (subagents)

For a full project audit against its documented state, dispatch 2-3 subagents concurrently:

```python
delegate_task(
    tasks=[
        {
            "goal": "Audit store/catalog codebase — check delivery endpoints, fulfilment, auth, CORS",
            "context": f"Project at {path}. Handover says delivery endpoints are missing. Verify.",
            "toolsets": ["terminal", "file"],
        },
        {
            "goal": "Audit publish/bridge path — verify R2 upload is real or stubbed",
            "context": f"Project at {path}. Check bridge.py and publish.py.",
            "toolsets": ["terminal", "file"],
        },
        {
            "goal": "Run golden set test and check CI status",
            "context": f"Project at {path}. Run: cd {path} && python -m pytest tests/test_golden_set.py -v",
            "toolsets": ["terminal"],
        },
    ]
)
```

## What to Do With Results

| Outcome | Action |
|---------|--------|
| Docs said missing, actually built | Delete from todo list. Don't re-build. |
| Docs said built, actually missing | Add to todo list. Update the doc. |
| Docs said broken, actually passing | Remove blocker. Proceed. |
| Docs said green, actually failing | P0 — needs investigation. Report to user. |

## Real Example: Prospector Session (2026-06-17)

Two handover documents (GO_LIVE_SPEC.md, HANDOVER_BRIDGE_TO_LAUNCH.md) were dated 2026-06-16 and claimed:

| Claim in Doc | Actual State | Action |
|---|---|---|
| API tests broken (TestClient Starlette/httpx version drift) | **All 13 passing** | Removed blocker, proceeded |
| Fulfilment chain absent | **Fully built** (Orders, Entitlements, delivery endpoints, R2 upload, email) | Deleted from todo |
| Port mismatch (:5000 vs :5291) | **Bridge.py already correct**; only Next.js client needed fixing | Fixed 1 file instead of 2 |
| CORS middleware missing | **Confirmed missing** | Built it |
| CI pipeline absent | **Confirmed absent** | Built it |

**Lesson:** A 1-day-old handover in an active development phase can be wrong on 5+ claims. Verify before building.

## Why This Matters

Shipping duplicate work because you trusted stale docs is worse than spending 2 minutes verifying. A 2026-06-16 handover document read on 2026-06-17 can be wrong by 5+ features in an active development phase.
