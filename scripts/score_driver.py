#!/usr/bin/env python3
"""
score_driver.py — Score-driven improvement (Round H1, H3, H4).

H1: score_burndown() — current score vs target, biggest gap, action
H3: check_score_regression() — detect 2+ consecutive drops
H4: score_leaderboard() — weekly score averages with sparkline

Usage:
  python3 score_driver.py --burndown        # H1
  python3 score_driver.py --regression      # H3
  python3 score_driver.py --leaderboard     # H4
  python3 score_driver.py --help
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
VELOCITY_LOG = HERMES_HOME / "logs" / "velocity.jsonl"
DAILY_SNAPSHOTS = HERMES_HOME / "logs" / "self-audit" / "daily"


def _venv_python() -> str:
    return sys.executable or "/usr/local/bin/python3"


def _safe_read_jsonl(path: Path) -> List[dict]:
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


def _get_current_score() -> float:
    """Get current score from the most recent daily snapshot."""
    if not DAILY_SNAPSHOTS.is_dir():
        return 0.0

    snapshots = sorted(DAILY_SNAPSHOTS.glob("*.json"))
    if not snapshots:
        return 0.0

    try:
        data = json.loads(snapshots[-1].read_text())
        return float(data.get("score", 0))
    except Exception:
        return 0.0


def _get_score_breakdown() -> dict:
    """Get score breakdown from most recent snapshot."""
    if not DAILY_SNAPSHOTS.is_dir():
        return {}

    snapshots = sorted(DAILY_SNAPSHOTS.glob("*.json"))
    if not snapshots:
        return {}

    try:
        data = json.loads(snapshots[-1].read_text())
        return data.get("score_breakdown", {})
    except Exception:
        return {}


# --- H1: Score Burn-down ---

def score_burndown() -> dict:
    """Current score vs target; identify biggest gap; recommend action."""
    current = _get_current_score()
    breakdown = _get_score_breakdown()
    target = 0.50

    gap = target - current
    pct_complete = round((current / target) * 100, 1) if target > 0 else 0

    # Find the factor with the biggest gap to its max contribution
    max_per_factor = {
        "auto_fixes": 0.10,
        "injection_relevance": 0.10,
        "policy_firings": 0.15,
        "learning": 0.05,
        "estate_health": 0.10,
    }

    biggest_gap_factor = "policy_firings"
    biggest_gap_value = 0.0
    actions: Dict[str, str] = {
        "auto_fixes": "Run more prospector ticks to generate auto-fix opportunities.",
        "injection_relevance": "Improve injection pipeline relevance — tune injection filters.",
        "policy_firings": "Run agent_simulator to generate traffic that triggers policy firings.",
        "learning": "Run idle-learning pipeline to generate new policies.",
        "estate_health": "Fix failing daemons — check `daemons` panel.",
    }

    for factor, max_val in max_per_factor.items():
        current_val = breakdown.get(factor, 0)
        factor_gap = max_val - current_val
        if factor_gap > biggest_gap_value:
            biggest_gap_value = factor_gap
            biggest_gap_factor = factor

    action_text = actions.get(biggest_gap_factor, "Run agent_simulator to generate traffic.")

    return {
        "current_score": current,
        "target_score": target,
        "gap": round(gap, 2),
        "pct_complete": pct_complete,
        "biggest_gap": {
            "factor": biggest_gap_factor,
            "current": breakdown.get(biggest_gap_factor, 0),
            "max": max_per_factor.get(biggest_gap_factor, 0.15),
            "gap": round(biggest_gap_value, 3),
        },
        "action": action_text,
        "summary": (f"Score {current} → target {target}. "
                     f"Biggest gap: {biggest_gap_factor} "
                     f"({breakdown.get(biggest_gap_factor, 0)}). "
                     f"Action: {action_text}"),
    }


# --- H3: Score Regression Check ---

def check_score_regression() -> dict:
    """Check last 3 days of scores for consecutive drops; alert if 2+."""
    if not DAILY_SNAPSHOTS.is_dir():
        return {"regression": False, "detail": "No daily snapshots available."}

    snapshots = sorted(DAILY_SNAPSHOTS.glob("*.json"))
    if len(snapshots) < 3:
        return {"regression": False, "detail": f"Only {len(snapshots)} snapshots available (need ≥3)."}

    # Get scores from last 3 snapshots
    recent_scores: List[tuple] = []
    for sp in snapshots[-3:]:
        try:
            data = json.loads(sp.read_text())
            score = data.get("score", 0)
            recent_scores.append((sp.stem, float(score)))
        except Exception:
            continue

    if len(recent_scores) < 3:
        return {"regression": False, "detail": "Not enough parsed snapshots."}

    scores = [s for _, s in recent_scores]
    drops = 0
    trend_lines = []
    for i in range(1, len(scores)):
        delta = scores[i] - scores[i-1]
        direction = "↓" if delta < 0 else ("↑" if delta > 0 else "→")
        trend_lines.append(f"{recent_scores[i-1][0]}: {scores[i-1]} {direction} {recent_scores[i][0]}: {scores[i]}")
        if delta < 0:
            drops += 1

    regression = drops >= 2
    alert_msg = ""
    if regression:
        alert_msg = (f"⚠️ Score declining: {scores[0]} → {scores[1]} → {scores[2]}. "
                     "Check policy firings and injection relevance.")

    return {
        "regression": regression,
        "consecutive_drops": drops,
        "scores": scores,
        "trend": trend_lines,
        "alert": alert_msg,
    }


# --- H4: Score Leaderboard ---

def score_leaderboard() -> dict:
    """Weekly score averages from daily snapshots."""
    if not DAILY_SNAPSHOTS.is_dir():
        return {"weeks": [], "summary": "No daily snapshots available."}

    snapshots = sorted(DAILY_SNAPSHOTS.glob("*.json"))
    if not snapshots:
        return {"weeks": [], "summary": "No daily snapshots available."}

    # Group by ISO week
    weeks: Dict[str, List[float]] = {}
    for sp in snapshots:
        try:
            date_str = sp.stem
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            iso_year, iso_week, _ = dt.isocalendar()
            week_key = f"{iso_year}-W{iso_week:02d}"
            data = json.loads(sp.read_text())
            score = float(data.get("score", 0))
            if week_key not in weeks:
                weeks[week_key] = []
            weeks[week_key].append(score)
        except Exception:
            continue

    week_entries = []
    for week_key in sorted(weeks.keys()):
        vals = weeks[week_key]
        avg = round(sum(vals) / len(vals), 2)
        # Build sparkline: ↑ if avg > previous, ↓ if lower
        spark = ""
        if week_entries:
            prev_avg = week_entries[-1]["avg_score"]
            if avg > prev_avg:
                spark = "↑"
            elif avg < prev_avg:
                spark = "↓"
            else:
                spark = "→"
        week_entries.append({
            "week": week_key,
            "avg_score": avg,
            "days": len(vals),
            "spark": spark,
        })

    # Build summary line
    parts = []
    for w in week_entries:
        parts.append(f"{w['week']}: {w['avg_score']} {w['spark']}".strip())
    summary = " · ".join(parts) if parts else "No scores recorded yet."

    return {
        "weeks": week_entries,
        "summary": summary,
    }


def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("Usage: score_driver.py [--burndown|--regression|--leaderboard]")
        sys.exit(0)

    if "--burndown" in args:
        result = score_burndown()
        print(json.dumps(result, indent=2, default=str))
    elif "--regression" in args:
        result = check_score_regression()
        print(json.dumps(result, indent=2, default=str))
    elif "--leaderboard" in args:
        result = score_leaderboard()
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Unknown arg: {args}")
        sys.exit(2)


if __name__ == "__main__":
    main()
