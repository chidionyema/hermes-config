# Timezone and Date Arithmetic

A recurring briefing's date handling is one of its most error-prone areas. A "yesterday" calculation can be wrong by an entire day, and the briefing will report against the wrong artifact without any error message. This file is the playbook.

## The Core Problem

A cron job scheduled at 9am local time may execute in a different timezone than the user's "yesterday." Common cases:

| User timezone | Cron time | Cron TZ | "Yesterday" at cron-fire time |
|---------------|-----------|---------|-------------------------------|
| BST (UTC+1) | 9:00 | system | Yesterday BST = today UTC (in 9 hours) |
| EST (UTC-5) | 9:00 | system | Yesterday EST = today UTC (in 14 hours) |
| UTC | 9:00 | system | Yesterday UTC = today UTC (in 15 hours) |
| User in JST, cron in UTC | 9:00 cron / 18:00 JST | cron | "Yesterday" is JST yesterday, but the cron-tz is UTC today |

The safest rule: **use the user's local timezone for "yesterday," and convert explicitly when the file's mtime is in UTC.**

## Date Commands by Platform

### Get today's date (local)
```bash
# macOS
date +%Y-%m-%d
# Linux
date +%Y-%m-%d
# Both produce: 2026-07-02 (in the system's local timezone)
```

### Get yesterday's date
```bash
# macOS
date -v-1d +%Y-%m-%d
# Linux (GNU)
date -d yesterday +%Y-%m-%d
# Linux (BSD, including macOS)
date -v-1d +%Y-%m-%d
```

**Cross-platform one-liner:**
```bash
YESTERDAY=$(python3 -c "from datetime import date, timedelta; print((date.today() - timedelta(days=1)).isoformat())")
```

This is portable and never wrong. Use this in the briefing for "yesterday" calculations.

### Get N days ago
```bash
# 7 days ago
python3 -c "from datetime import date, timedelta; print((date.today() - timedelta(days=7)).isoformat())"
```

## File-Name Date Patterns

The reflection files use `YYYY-MM-DD.md`:
```bash
# Today's reflection
ls ~/.hermes/logs/reflection/$(date +%Y-%m-%d).md 2>/dev/null
# Yesterday's
ls ~/.hermes/logs/reflection/$(python3 -c "from datetime import date, timedelta; print((date.today() - timedelta(days=1)).isoformat())").md 2>/dev/null
```

The near-miss files use `YYYYMMDD-HHMMSS.json` (compact, no hyphens):
```bash
# Today's near-miss files
ls ~/.hermes/logs/maintenance/near-miss-$(date +%Y%m%d)*.json
```

The strategist-audit uses `YYYY-MM-DD.md`:
```bash
ls ~/.hermes/reports/strategist-audit-$(date +%Y-%m-%d).md
```

The repo-health uses ISO 8601 UTC timestamps in `timestamp` fields, not in the filename:
```bash
# Most recent entry (could be from earlier today UTC, even if local is later)
tail -1 ~/.hermes/logs/health/repo-health.jsonl
```

The watchdog alerts use ISO 8601 UTC timestamps in `timestamp` fields:
```bash
# Latest 10 entries (no date filter — the cron runs every 15m)
tail -10 ~/.hermes/logs/alerts/watchdog.jsonl
```

## "Last N Days" Patterns

### Last 7 daily reflections
```bash
for i in $(seq 0 6); do
  d=$(python3 -c "from datetime import date, timedelta; print((date.today() - timedelta(days=$i)).isoformat())")
  ls ~/.hermes/logs/reflection/${d}.md 2>/dev/null && echo "  ^ $d"
done
```

### Last 24h watchdog alerts
```bash
# Filter by timestamp >= 24h ago
python3 <<'EOF'
import json
from datetime import datetime, timezone, timedelta
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
with open('/Users/chidionyema/.hermes/logs/alerts/watchdog.jsonl') as f:
    for line in f:
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
            if ts >= cutoff and entry.get('type') != 'watchdog_summary':
                print(f"{ts.isoformat()}  {entry.get('type', '?')}  {entry.get('message', '')[:80]}")
        except Exception:
            pass
EOF
```

### Last run of a specific cron
```bash
hermes cron list | grep -B1 -A4 "Name: <cron_name>" | grep "Last run"
```

## Edge Cases

### The "morning of a new month" case
At 9am on July 1, "yesterday" is June 30. The reflection file is `2026-06-30.md`. **Make sure the date arithmetic crosses month boundaries correctly.**

```bash
# Test: yesterday's date relative to 2026-07-01
python3 -c "from datetime import date, timedelta; print((date(2026, 7, 1) - timedelta(days=1)).isoformat())"
# → 2026-06-30
```
The `timedelta` approach handles this correctly; the `date -v-1d` macOS approach also does. Avoid manual `if day == 1: month -= 1` logic.

### The "morning of January 1" case
At 9am on January 1, "yesterday" is December 31 of the prior year. The reflection file is `2025-12-31.md`.

```bash
python3 -c "from datetime import date, timedelta; print((date(2026, 1, 1) - timedelta(days=1)).isoformat())"
# → 2025-12-31
```
Tested working. The `timedelta` approach handles year rollovers.

### The "morning after a leap day" case
At 9am on March 1, 2025, "yesterday" is February 28, 2025 (not Feb 29 — that doesn't exist in 2025).

```bash
python3 -c "from datetime import date, timedelta; print((date(2025, 3, 1) - timedelta(days=1)).isoformat())"
# → 2025-02-28
```
Tested working.

### The "DST shift" case
At 9am on the day after spring-forward (clocks jump from 02:00 to 03:00), the wall-clock "yesterday" is one hour shorter. The `date` library handles this; the cron schedule is wall-clock-time (not absolute), so the cron fires at the right local time.

**Don't try to subtract hours when calculating "yesterday" — subtract days.**

## Comparing Across Timezones

The repo-health and watchdog timestamps are in UTC ISO 8601 format. To compare to local time:

```python
from datetime import datetime, timezone

ts_str = "2026-07-02T06:38:05Z"  # from JSONL
ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
ts_local = ts.astimezone()  # converts to system local
print(ts_local.strftime("%Y-%m-%d %H:%M %Z"))  # e.g. "2026-07-02 07:38 BST"
```

The briefing should display timestamps in the user's local timezone, not UTC. A 06:38 UTC timestamp is "07:38 BST" or "01:38 EST" — the user thinks in their local time, not UTC.

## The "8 days ago" Math Sanity Check

The 2026-07-02 briefing claims "8 days of missing reflections" with the last reflection on 2026-06-24. Verify:
```python
from datetime import date
diff = (date(2026, 7, 2) - date(2026, 6, 24)).days
print(diff)  # 8
```

The briefing should always do this sanity check before reporting "N days of X" claims. A 7-day claim that's actually 8 is a small error; a "yesterday" that's actually 2 days ago is a fundamental briefing failure.

## Pitfalls

**1. `date -v-1d` is macOS-only.** On Linux, use `date -d yesterday`. If the briefing runs on a Linux server, the macOS syntax will silently fail or produce a wrong result. **Use the Python one-liner for cross-platform safety.**

**2. `date` defaults to local time, not UTC.** `date +%Y-%m-%d` returns the local date, which is what you want for "yesterday" calculations. But `date -u +%Y-%m-%d` returns the UTC date. **Don't accidentally use `-u`** — it will give you "yesterday UTC" which is not what the user means.

**3. Cron self-reports use local time without timezone markers.** `Last run: 2026-07-02T09:00:55.429705+01:00` — the `+01:00` is the UTC offset, not a timezone name. The cron library formats with offset. When comparing, parse with `fromisoformat()` and convert to local.

**4. `ls -t` sorts by mtime, not by date in the filename.** If a file's mtime is wrong (e.g. a file was touched but not modified), `ls -t` will sort it incorrectly. The reflection files have YYYY-MM-DD in the name AND are written daily, so `ls -t` is reliable for them. The near-miss files have YYYYMMDD-HHMMSS in the name AND are written every 30m, so `ls -t` is reliable. **For ad-hoc files (logs, scratch files), do not trust `ls -t` — use the filename or stat the file.**

**5. The 8-day gap is misleading without context.** "8 days of missing reflections" sounds like a crisis. The context is: the cron is broken in a specific way (path mismatch, script error), and the cron self-reports `ok` despite the missing files. The briefing should report the **broken cron** as the cause, not just the symptom of "missing files."

**6. A briefing fired at 9am Monday may have a "Sunday" gap.** If the cron only runs on weekdays, a "yesterday" reference on Monday morning is the prior Friday. The briefing should not interpret a Saturday-Sunday gap as a cron failure.

**7. The user's `date` output may not match their stated timezone.** If the user is in BST but the system is configured as UTC, `date +%Y-%m-%d` returns the UTC date. The briefing should detect this with `date +%Z` (timezone abbreviation) and warn if the system's TZ doesn't match the user's typical location.

## Summary

The safe pattern for any "yesterday" or "N days ago" calculation in a briefing:

```bash
DATE_VAR=$(python3 -c "from datetime import date, timedelta; print((date.today() - timedelta(days=N)).isoformat())")
```

Always use this. Never use the date command's relative flags. They are platform-specific and the wrong syntax silently produces the wrong result.
