#!/usr/bin/env python3
"""
predictor.py — Predictive intelligence (Round D1-D4).

D1: predict_credit_exhaustion() — scan errors for credit/rate-limit issues
D2: correlate_failures() — find co-occurring failure clusters
D3: detect_anomalies() — flag today vs 14-day baseline
D4: track_mttr() — compute Mean Time To Recovery from ops-monitor

Usage:
  python3 predictor.py --predict credits     # D1
  python3 predictor.py --correlate            # D2
  python3 predictor.py --anomalies            # D3
  python3 predictor.py --mttr                 # D4
  python3 predictor.py --all                  # run all
  python3 predictor.py --help                 # this message
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
ERROR_LOG = HERMES_HOME / "logs" / "errors.log"
OPS_MONITOR = HERMES_HOME / "logs" / "ops-monitor.jsonl"
WATCHDOG_LOG = HERMES_HOME / "logs" / "estate-watchdog.log"
DAILY_SNAPSHOTS = HERMES_HOME / "logs" / "self-audit" / "daily"
TICKS_PATH = Path.home() / "Documents" / "code" / "prospector" / "store" / "scheduler" / "ticks.jsonl"


def _safe_read(path: Path) -> List[str]:
    """Read file lines; return [] on any failure (missing, permission, etc.)."""
    try:
        if not path.is_file():
            return []
        return path.read_text(errors="replace").splitlines()
    except Exception:
        return []


def _safe_read_jsonl(path: Path) -> List[dict]:
    """Read JSONL file; return [] on any failure."""
    try:
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except Exception:
        return []


def _venv_python() -> str:
    """python3 to use for subprocess calls."""
    return sys.executable or "/usr/local/bin/python3"


# --- D1: Credit Exhaustion Prediction ---

def predict_credit_exhaustion() -> dict:
    """Scan errors.log for credit/rate-limit errors in last 6h, extrapolate exhaustion."""
    lines = _safe_read(ERROR_LOG)
    if not lines:
        return {"provider": "unknown", "errors_last_6h": 0, "rate_per_hour": 0,
                "estimated_exhaustion_h": None, "action": "No recent errors found."}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    credit_patterns = [
        r"credit", r"rate.?limit", r"usage limit", r"quota", r"exhausted",
        r"balance too low", r"insufficient.*credit", r"ProviderExhausted",
        r"402", r"429",
    ]
    combined = re.compile("|".join(credit_patterns), re.I)

    recent_errors = 0
    provider = "cursor"  # default
    for line in lines:
        if not combined.search(line):
            continue
        # Try to extract timestamp
        try:
            # Format: "2026-07-31 21:51:43,480 ERROR ..."
            ts_str = line[:23].strip()
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc)
        except Exception:
            # Fallback: try parsing any ISO-ish date
            ts = None
        if ts is not None and ts < cutoff:
            continue
        recent_errors += 1
        if "anthropic" in line.lower() or "claude" in line.lower():
            provider = "anthropic"

    if recent_errors == 0:
        return {"provider": provider, "errors_last_6h": 0, "rate_per_hour": 0,
                "estimated_exhaustion_h": None, "action": "No credit errors in last 6h."}

    rate_per_hour = round(recent_errors / 6.0, 2)
    estimated_h = round(24.0 / rate_per_hour, 1) if rate_per_hour > 0 else None

    if provider == "anthropic":
        action = "Top up at console.anthropic.com"
    else:
        action = "Top up at cursor.sh/account"

    return {
        "provider": provider,
        "errors_last_6h": recent_errors,
        "rate_per_hour": rate_per_hour,
        "estimated_exhaustion_h": estimated_h,
        "action": action,
    }


# --- D2: Failure Correlation Engine ---

def correlate_failures() -> dict:
    """Group failures by 30-min windows; find clusters with 2+ failure types."""
    error_lines = _safe_read(ERROR_LOG)
    ops_entries = _safe_read_jsonl(OPS_MONITOR)
    watchdog_lines = _safe_read(WATCHDOG_LOG)
    ticks_entries = _safe_read_jsonl(TICKS_PATH)

    # Collect all failure events with timestamps
    events: List[Tuple[datetime, str]] = []

    # Parse errors.log
    for line in error_lines:
        try:
            ts_str = line[:23].strip()
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if "ERROR" in line:
            events.append((ts, "log_error"))
        elif "WARNING" in line and any(kw in line.lower() for kw in ("credit", "rate", "quota")):
            events.append((ts, "credit_warning"))

    # Parse ops-monitor.jsonl
    for entry in ops_entries:
        try:
            ts = datetime.fromisoformat(entry.get("ts", ""))
        except Exception:
            continue
        etype = entry.get("type", "")
        events.append((ts, f"ops_{etype}"))

    # Parse ticks for error entries
    for entry in ticks_entries:
        try:
            ts = datetime.fromisoformat(entry.get("ts", ""))
        except Exception:
            continue
        if entry.get("error"):
            events.append((ts, "moat_error"))

    if not events:
        return {"clusters": [], "summary": "No failures found to correlate."}

    # Sort by time
    events.sort(key=lambda e: e[0])

    # Group into 30-min windows
    windows: Dict[str, set] = {}
    for ts, etype in events:
        slot = ts.replace(minute=(ts.minute // 30) * 30, second=0, microsecond=0)
        key = slot.strftime("%H:%M")
        if key not in windows:
            windows[key] = set()
        windows[key].add(etype)

    # Find windows with 2+ distinct failure types
    clusters = []
    for window_key, types in sorted(windows.items()):
        if len(types) >= 2:
            types_list = sorted(types)
            hypothesis = ""
            if any("credit" in t.lower() or "exhaust" in t.lower() for t in types_list):
                hypothesis = "shared cause: API credit exhaustion"
            elif "moat_error" in types_list and "ops_" in " ".join(types_list):
                hypothesis = "shared cause: moat health degradation"
            else:
                hypothesis = "shared cause: infrastructure instability"
            clusters.append({
                "window": window_key,
                "failure_types": types_list,
                "count": len(types_list),
                "hypothesis": hypothesis,
            })

    if not clusters:
        return {"clusters": [], "summary": "No correlated failure clusters found."}

    return {
        "clusters": clusters,
        "summary": f"{len(clusters)} failure clusters detected. "
                   f"Largest: {max(c['count'] for c in clusters)} types co-occurring.",
    }


# --- D3: Anomaly Detection ---

def detect_anomalies() -> Dict[str, Any]:
    """Load 14 days of daily snapshots; flag today if outside mean ± 2σ."""
    if not DAILY_SNAPSHOTS.is_dir():
        return {"metric": "N/A", "today": None, "baseline_mean": 0, "baseline_std": 0,
                "anomaly": False, "direction": "none", "detail": "No daily snapshots directory."}

    snapshots = []
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=14)).strftime("%Y-%m-%d")

    for fpath in sorted(DAILY_SNAPSHOTS.glob("*.json")):
        fname = fpath.stem  # "2026-08-02"
        if fname < cutoff:
            continue
        try:
            data = json.loads(fpath.read_text())
            snapshots.append(data)
        except Exception:
            continue

    if len(snapshots) < 3:
        return {"metric": "prospector_runs", "today": None, "baseline_mean": 0, "baseline_std": 0,
                "anomaly": False, "direction": "none", "detail": f"Only {len(snapshots)} snapshots available (need ≥3)."}

    # Extract a metric — try prospector_runs from raw, fallback to score
    values = []
    today_val = None
    today_str = now.strftime("%Y-%m-%d")
    for snap in snapshots:
        raw = snap.get("raw", {})
        val = raw.get("prospector_runs") or raw.get("total_ticks") or snap.get("score", 0)
        if isinstance(val, (int, float)):
            values.append(float(val))
            if snap.get("date") == today_str:
                today_val = float(val)

    if not values:
        return {"metric": "score", "today": None, "baseline_mean": 0, "baseline_std": 0,
                "anomaly": False, "direction": "none", "detail": "No numeric metric found in snapshots."}

    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = variance ** 0.5

    if today_val is None:
        today_val = values[-1]  # assume last snapshot is today

    if std == 0:
        return {"metric": "score", "today": today_val, "baseline_mean": mean, "baseline_std": 0,
                "anomaly": False, "direction": "none"}

    threshold_low = mean - 2 * std
    threshold_high = mean + 2 * std

    anomaly = today_val < threshold_low or today_val > threshold_high
    direction = "below" if today_val < threshold_low else ("above" if today_val > threshold_high else "none")

    return {
        "metric": "prospector_runs",
        "today": today_val,
        "baseline_mean": round(mean, 2),
        "baseline_std": round(std, 2),
        "anomaly": anomaly,
        "direction": direction,
    }


# --- D4: MTTR Tracking ---

def track_mttr() -> dict:
    """Compute Mean Time To Recovery from moat_auto_pause/resume events."""
    entries = _safe_read_jsonl(OPS_MONITOR)
    if not entries:
        return {"outages_this_month": 0, "avg_duration_h": 0, "last_month_avg_h": 0, "trend": "stable"}

    now = datetime.now(timezone.utc)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
    last_month_end = this_month_start - timedelta(seconds=1)

    # Collect pause/resume pairs
    pauses: List[datetime] = []
    resumes: List[datetime] = []

    for entry in entries:
        etype = entry.get("type", "")
        try:
            ts = datetime.fromisoformat(entry.get("ts", ""))
        except Exception:
            continue
        if etype == "moat_auto_pause":
            pauses.append(ts)
        elif etype == "moat_auto_resume":
            resumes.append(ts)

    # Sort both, match pauses to next resume
    pauses.sort()
    resumes.sort()

    durations_this_month: List[float] = []
    durations_last_month: List[float] = []

    resume_idx = 0
    for pause_ts in pauses:
        # Find first resume after this pause
        while resume_idx < len(resumes) and resumes[resume_idx] <= pause_ts:
            resume_idx += 1
        if resume_idx >= len(resumes):
            break
        resume_ts = resumes[resume_idx]
        duration_h = (resume_ts - pause_ts).total_seconds() / 3600.0
        # Sanity check: don't count impossibly long durations (>720h = 30 days)
        if duration_h > 720:
            continue
        if pause_ts >= this_month_start:
            durations_this_month.append(duration_h)
        elif last_month_start <= pause_ts <= last_month_end:
            durations_last_month.append(duration_h)
        resume_idx += 1

    this_month_avg = round(sum(durations_this_month) / len(durations_this_month), 1) if durations_this_month else 0
    last_month_avg = round(sum(durations_last_month) / len(durations_last_month), 1) if durations_last_month else 0

    if this_month_avg > last_month_avg * 1.2 and last_month_avg > 0:
        trend = "worsening"
    elif this_month_avg < last_month_avg * 0.8 and last_month_avg > 0:
        trend = "improving"
    else:
        trend = "stable"

    return {
        "outages_this_month": len(durations_this_month),
        "avg_duration_h": this_month_avg,
        "last_month_avg_h": last_month_avg,
        "trend": trend,
    }


def run_all() -> Dict[str, Any]:
    return {
        "credit_exhaustion": predict_credit_exhaustion(),
        "failure_correlation": correlate_failures(),
        "anomalies": detect_anomalies(),
        "mttr": track_mttr(),
    }


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("Usage: predictor.py [--predict credits|--correlate|--anomalies|--mttr|--all]")
        sys.exit(0)

    if "--predict" in args:
        result = predict_credit_exhaustion()
        print(json.dumps(result, indent=2, default=str))
    elif "--correlate" in args:
        result = correlate_failures()
        print(json.dumps(result, indent=2, default=str))
    elif "--anomalies" in args:
        result = detect_anomalies()
        print(json.dumps(result, indent=2, default=str))
    elif "--mttr" in args:
        result = track_mttr()
        print(json.dumps(result, indent=2, default=str))
    elif "--all" in args:
        print(json.dumps(run_all(), indent=2, default=str))
    else:
        print(f"Unknown arg: {args}")
        sys.exit(2)


if __name__ == "__main__":
    main()
