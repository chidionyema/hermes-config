#!/usr/bin/env python3
"""
idle_engine.py — Continuous background learning for Otto.

Instead of hourly cron, Otto runs continuous micro-cycles during idle time:
- Real-time outcome processing (learn from every task immediately)
- Micro-regression (test 5 random policies every 2 minutes)
- Log pattern mining (find recurring errors)
- Cross-project insight generation
- Proactive suggestion queuing

Makes Otto feel alive and continuously improving, not dormant between cron runs.
"""

import json
import os
import random
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
SCRIPTS = HERMES / "scripts"
STATE = HERMES / "state" / "idle_engine"
STATE.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SCRIPTS))


class IdleEngine:
    """Continuous background learning. Runs micro-cycles constantly."""
    
    def __init__(self):
        self.last_cycle = time.time()
        self.cycles_completed = 0
        self.insights_generated = 0
        self._load_state()
    
    def _load_state(self):
        sf = STATE / "state.json"
        if sf.is_file():
            try:
                d = json.loads(sf.read_text())
                self.cycles_completed = d.get("cycles", 0)
                self.insights_generated = d.get("insights", 0)
                # Survive a restart without re-processing every outcome since
                # boot; falls back to __init__'s time.time() on first run.
                if d.get("watermark"):
                    self.last_cycle = float(d["watermark"])
            except: pass
    
    def _save_state(self):
        (STATE / "state.json").write_text(json.dumps({
            "cycles": self.cycles_completed,
            "insights": self.insights_generated,
            "last_cycle": datetime.now(timezone.utc).isoformat(),
            "watermark": self.last_cycle,
        }))
    
    def run_daemon(self, interval: int = 120):
        """Run continuously, cycling every `interval` seconds."""
        print(f"🔄 Idle Engine started — {interval}s micro-cycles")
        print(f"   Processing outcomes, mining patterns, generating insights")
        
        while True:
            try:
                start = time.time()
                cycle_result = self.run_micro_cycle()
                elapsed = time.time() - start
                
                self.cycles_completed += 1
                self._save_state()
                
                if cycle_result.get("insights"):
                    print(f"  [{datetime.now().strftime('%H:%M')}] "
                          f"{cycle_result.get('outcomes_processed',0)} outcomes, "
                          f"{cycle_result.get('insights',0)} insights "
                          f"({elapsed:.1f}s)")
                
                sleep_time = max(10, interval - elapsed)
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                # A bare str(e) is not diagnosable: this loop logged the same
                # "tuple indices must be integers" 1210 times in one day with no
                # file or line, so nobody could tell which of the six phases in
                # run_micro_cycle was failing. The traceback is the whole point.
                print(f"  ⚠️ Cycle error: {e}")
                print(traceback.format_exc(), flush=True)
                time.sleep(30)
    
    def run_micro_cycle(self) -> dict:
        """One micro-cycle: process new outcomes, find patterns, generate insights.
        
        Returns dict with counts of what was done.
        """
        result = {"outcomes_processed": 0, "insights": 0, "patterns": 0}
        
        # 1. Process new outcomes (real-time learning)
        result["outcomes_processed"] = self._process_new_outcomes()
        
        # 2. Mine patterns from recent logs
        result["patterns"] = self._mine_patterns()
        
        # 3. Generate insights if patterns found
        if result["patterns"] > 0 or random.random() < 0.1:  # 10% chance of deep analysis
            insights = self._generate_insights()
            result["insights"] = len(insights)
            if insights:
                self._queue_insights(insights)
                self.insights_generated += len(insights)
        
        # 4. Micro-regression (test 3 random policies)
        if random.random() < 0.2:  # 20% chance per cycle
            self._micro_regression()
        
        return result
    
    def _process_new_outcomes(self) -> int:
        """Process outcomes that arrived since last cycle."""
        db_path = HERMES / "state" / "outcomes.db"
        if not db_path.is_file():
            return 0
        
        import sqlite3
        # Rows are addressed BY NAME below (r["domain"]). Without an explicit
        # row_factory sqlite3 hands back plain tuples and every one of those
        # lookups raises TypeError. That is not hypothetical: this loop logged
        # "tuple indices must be integers or slices, not str" 1,210 times from
        # 2026-08-05T20:27Z. It ran fine for 1,266 cycles beforehand only
        # because the early return above skips this code when no new outcome
        # rows exist — the first row written after startup killed every cycle.
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Find outcomes since last check. self.last_cycle was set once in
        # __init__ and never advanced, so this window grew without bound and
        # re-counted the same rows on every cycle. Read the watermark before
        # the query, commit it only after the fetch succeeds: a crash re-reads
        # the window rather than silently skipping it.
        since = datetime.fromtimestamp(self.last_cycle, tz=timezone.utc).isoformat()
        checkpoint = time.time()
        try:
            rows = conn.execute(
                "SELECT domain, outcome, error_type FROM task_outcomes WHERE created_at > ?",
                (since,)
            ).fetchall()
        finally:
            conn.close()
        self.last_cycle = checkpoint
        
        if not rows:
            return 0
        
        # Update per-domain stats
        domains = Counter(r["domain"] for r in rows)
        failures = sum(1 for r in rows if r["outcome"] == "failure")
        error_types = Counter(r["error_type"] for r in rows if r["error_type"])
        
        # Log to outcomes tracking
        tracker_file = HERMES / "logs" / "meta-improver" / "change-outcomes.jsonl"
        with open(tracker_file, "a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": "micro_cycle",
                "new_outcomes": len(rows),
                "failures": failures,
                "domains": dict(domains),
                "error_types": dict(error_types),
            }) + "\n")
        
        return len(rows)
    
    def _mine_patterns(self) -> int:
        """Mine recent error logs for recurring patterns."""
        error_log = HERMES / "logs" / "errors.log"
        if not error_log.is_file():
            return 0
        
        patterns_found = 0
        
        # Read last 1000 lines
        lines = error_log.read_text().splitlines()[-1000:]
        recent = [l for l in lines if datetime.now().strftime("%Y-%m-%d") in l[:20]]
        
        if len(recent) < 10:
            return 0
        
        # Find repeated error types
        error_types = Counter()
        for line in recent:
            if "ERROR" in line:
                # Extract error type from message
                msg = line.split("ERROR", 1)[-1].strip()[:80]
                # Normalize: remove timestamps, IDs, paths
                import re
                msg = re.sub(r'0x[0-9a-f]+', '0x...', msg)
                msg = re.sub(r'/[^\s]+\.py:\d+', '/file.py:NN', msg)
                msg = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', 'TIMESTAMP', msg)
                error_types[msg] += 1
        
        # Save patterns that appear 3+ times
        pattern_file = STATE / "error_patterns.jsonl"
        for msg, count in error_types.most_common(20):
            if count >= 3:
                with open(pattern_file, "a") as f:
                    f.write(json.dumps({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "pattern": msg[:120],
                        "count": count,
                        "window": "today",
                    }) + "\n")
                patterns_found += 1
        
        return patterns_found
    
    def _generate_insights(self) -> list:
        """Generate actionable insights from accumulated data."""
        insights = []
        
        # Check for emerging error patterns
        pattern_file = STATE / "error_patterns.jsonl"
        if pattern_file.is_file():
            recent_patterns = []
            for line in pattern_file.read_text().splitlines():
                if not line.strip(): continue
                try:
                    p = json.loads(line)
                    ts = p.get("ts", "")
                    if ts and ts[:10] == datetime.now().strftime("%Y-%m-%d"):
                        recent_patterns.append(p)
                except: pass
            
            if recent_patterns:
                top = sorted(recent_patterns, key=lambda x: x["count"], reverse=True)[:3]
                for p in top:
                    insights.append({
                        "type": "pattern",
                        "severity": "warning" if p["count"] > 5 else "info",
                        "text": f"Recurring error ({p['count']}x today): {p['pattern'][:100]}",
                        "action": "logs_error",
                    })
        
        # Check for domain-specific failure spikes
        outcomes_file = HERMES / "logs" / "meta-improver" / "change-outcomes.jsonl"
        if outcomes_file.is_file():
            for line in outcomes_file.read_text().splitlines():
                if not line.strip(): continue
                try:
                    d = json.loads(line)
                    if d.get("type") == "micro_cycle" and d.get("failures", 0) > 3:
                        domain = max(d.get("domains", {}), key=d.get("domains", {}).get) if d.get("domains") else "unknown"
                        insights.append({
                            "type": "spike",
                            "severity": "warning",
                            "text": f"{d['failures']} failures in {domain} this cycle — may need attention",
                            "action": f"diagnose_{domain}",
                        })
                except: pass
        
        return insights
    
    def _queue_insights(self, insights: list):
        """Queue insights for the operator to review."""
        queue_file = HERMES / "state" / "insight_queue.jsonl"
        for i in insights:
            with open(queue_file, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "type": i.get("type", "info"),
                    "severity": i.get("severity", "info"),
                    "text": i.get("text", ""),
                    "action": i.get("action", ""),
                    "acknowledged": False,
                }) + "\n")
    
    def _micro_regression(self):
        """Test 3 random policies against the regression corpus."""
        try:
            sr = _import_script("self-regression")
            policies = sr.load_policies()
            if not policies:
                return
            
            # Pick 3 random active policies
            active = [p for p in policies if p.get("status") == "active"]
            if not active:
                return
            
            sample = random.sample(active, min(3, len(active)))
            corpus = sr.load_corpus()
            
            for policy in sample:
                # Lite test: check if any corpus entry matches the policy trigger
                trigger = policy.get("trigger", "").lower()
                matches = sum(1 for c in corpus if isinstance(c, dict) and 
                            trigger and any(w in json.dumps(c).lower() for w in trigger.split()[:3]))
                
                if matches > 0:
                    sr.log_result(policy.get("id", "?"), "micro_pass", matches)
        except Exception:
            pass  # Micro-regression is best-effort


def _import_script(name: str):
    """Import a script module by filename."""
    import importlib.util
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    import argparse
    p = argparse.ArgumentParser(description="Idle Engine — continuous background learning")
    p.add_argument("--daemon", action="store_true", help="Run continuously")
    p.add_argument("--interval", type=int, default=120, help="Cycle interval in seconds")
    p.add_argument("--once", action="store_true", help="Run one cycle and exit")
    p.add_argument("--insights", action="store_true", help="Show queued insights")
    args = p.parse_args()
    
    engine = IdleEngine()
    
    if args.insights:
        queue_file = HERMES / "state" / "insight_queue.jsonl"
        if queue_file.is_file():
            lines = queue_file.read_text().splitlines()
            unacked = []
            for line in lines:
                if not line.strip(): continue
                try:
                    d = json.loads(line)
                    if not d.get("acknowledged"):
                        unacked.append(d)
                except: pass
            
            if unacked:
                print(f"💡 {len(unacked)} unacknowledged insights:")
                for u in unacked[-10:]:
                    icon = {"warning": "🟡", "info": "🔵"}.get(u.get("severity", "info"), "⚪")
                    print(f"  {icon} [{u.get('type','?')}] {u.get('text','')[:100]}")
            else:
                print("✅ No pending insights")
        else:
            print("No insights yet. Start the daemon to generate them.")
        return
    
    if args.once:
        result = engine.run_micro_cycle()
        print(f"Cycle complete: {result}")
        return
    
    if args.daemon:
        engine.run_daemon(interval=args.interval)
    else:
        print("Usage: python3 idle_engine.py --daemon [--interval 120]")
        print("       python3 idle_engine.py --once")
        print("       python3 idle_engine.py --insights")


if __name__ == "__main__":
    main()
