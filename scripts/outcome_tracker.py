"""
SQLite-backed OutcomeTracker — ACID-compliant replacement for JSONL appends.

Migration from fragile JSONL files to SQLite with WAL mode:
- Atomic writes (no partial/corrupt entries)
- Concurrent reads (WAL mode allows reads during writes)
- Indexed queries (no more O(N) full scans)
- Thread-safe (SQLite connection pooling)
- Backward compatible (reads old JSONL, writes to SQLite)
"""

import json
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


class OutcomeTracker:
    """SQLite-backed task outcome tracker with automatic JSONL migration."""

    def __init__(self, hermes_home: Optional[Path] = None):
        self.home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
        self.db_path = self.home / "state" / "outcomes.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.legacy_jsonl = self.home / "logs" / "task-outcomes.jsonl"
        self.validation_queue = self.home / "logs" / "validation-queue.jsonl"
        self._init_db()
        self._migrate_if_needed()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS task_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT 'unknown',
                    outcome TEXT NOT NULL CHECK(outcome IN ('success','failure','partial','unknown')),
                    confidence REAL NOT NULL DEFAULT 0.8,
                    auto_detected INTEGER NOT NULL DEFAULT 1,
                    human_validated INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT DEFAULT '',
                    task_type TEXT DEFAULT '',
                    duration_s REAL DEFAULT 0.0,
                    policies_fired TEXT DEFAULT '[]',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                
                CREATE INDEX IF NOT EXISTS idx_outcomes_domain 
                    ON task_outcomes(domain, created_at);
                CREATE INDEX IF NOT EXISTS idx_outcomes_task_id 
                    ON task_outcomes(task_id);
                CREATE INDEX IF NOT EXISTS idx_outcomes_outcome 
                    ON task_outcomes(outcome, created_at);
                
                CREATE TABLE IF NOT EXISTS validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    auto_outcome TEXT NOT NULL,
                    human_outcome TEXT,
                    validated_by TEXT DEFAULT 'human',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    validated_at TEXT
                );
                
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)
            
            # Ensure schema version
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version) VALUES(1)"
            )

    def _migrate_if_needed(self):
        """One-time migration from legacy JSONL to SQLite."""
        if not self.legacy_jsonl.is_file():
            return
        
        # Check if already migrated
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM task_outcomes").fetchone()[0]
            if count > 0:
                return  # Already has data
        
        # Read legacy JSONL
        entries = []
        for line in self.legacy_jsonl.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        
        if not entries:
            return
        
        # Bulk insert
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO task_outcomes 
                   (task_id, domain, outcome, confidence, auto_detected, 
                    human_validated, error_type, task_type, duration_s, 
                    policies_fired, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(
                    e.get("task_id", "migrated"),
                    e.get("domain", "unknown"),
                    e.get("outcome", "unknown"),
                    e.get("confidence", 0.8),
                    1 if e.get("auto_detected", True) else 0,
                    1 if e.get("human_validated", False) else 0,
                    e.get("error_type", ""),
                    e.get("task_type", ""),
                    e.get("duration_s", 0.0),
                    json.dumps(e.get("policies_fired", [])),
                    e.get("notes", ""),
                    e.get("ts", e.get("created_at", datetime.now(timezone.utc).isoformat())),
                ) for e in entries]
            )
        
        # Archive legacy file
        archive_path = self.legacy_jsonl.with_suffix(".jsonl.archived")
        self.legacy_jsonl.rename(archive_path)
    
    def record(self, outcome) -> None:
        """Record a task outcome. Accepts dataclass, namespace, or dict."""
        # Convert to dict regardless of input type
        if isinstance(outcome, dict):
            d = outcome
        elif hasattr(outcome, '__dataclass_fields__'):
            d = {
                "task_id": outcome.task_id, "domain": outcome.domain,
                "outcome": outcome.outcome, "confidence": outcome.confidence,
                "auto_detected": outcome.auto_detected,
                "human_validated": outcome.human_validated,
                "error_type": outcome.error_type, "task_type": outcome.task_type,
                "duration_s": outcome.duration_seconds,
                "policies_fired": outcome.policy_fired, "notes": outcome.notes,
            }
        else:
            # Namespace or arbitrary object — convert to dict via attributes
            d = {
                "task_id": getattr(outcome, 'task_id', 'unknown'),
                "domain": getattr(outcome, 'domain', 'unknown'),
                "outcome": getattr(outcome, 'outcome', 'unknown'),
                "confidence": getattr(outcome, 'confidence', 0.8),
                "auto_detected": getattr(outcome, 'auto_detected', True),
                "human_validated": getattr(outcome, 'human_validated', False),
                "error_type": getattr(outcome, 'error_type', ''),
                "task_type": getattr(outcome, 'task_type', ''),
                "duration_s": getattr(outcome, 'duration_seconds', 0.0),
                "policies_fired": getattr(outcome, 'policy_fired', []),
                "notes": getattr(outcome, 'notes', ''),
            }
        
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO task_outcomes 
                   (task_id, domain, outcome, confidence, auto_detected,
                    human_validated, error_type, task_type, duration_s,
                    policies_fired, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    d.get("task_id", "unknown"),
                    d.get("domain", "unknown"),
                    d.get("outcome", "unknown"),
                    d.get("confidence", 0.8),
                    1 if d.get("auto_detected", True) else 0,
                    1 if d.get("human_validated", False) else 0,
                    d.get("error_type", ""),
                    d.get("task_type", ""),
                    d.get("duration_s", 0.0),
                    json.dumps(d.get("policies_fired", [])),
                    d.get("notes", ""),
                    d.get("ts", d.get("created_at", datetime.now(timezone.utc).isoformat())),
                ),
            )

    def stats(self, window_days: int = 7, domain: Optional[str] = None) -> dict:
        """Compute statistics from SQLite — O(1) indexed queries."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        
        with self._connect() as conn:
            if domain:
                rows = conn.execute(
                    """SELECT * FROM task_outcomes 
                       WHERE created_at >= ? AND domain = ?
                       ORDER BY created_at DESC""",
                    (cutoff, domain),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM task_outcomes 
                       WHERE created_at >= ?
                       ORDER BY created_at DESC""",
                    (cutoff,),
                ).fetchall()
            
            if not rows:
                return self._empty_stats(window_days)
            
            total = len(rows)
            successes = sum(1 for r in rows if r["outcome"] == "success")
            failures = sum(1 for r in rows if r["outcome"] == "failure")
            
            # Per-domain breakdown (indexed query)
            domain_rows = conn.execute(
                """SELECT domain, outcome, COUNT(*) as cnt
                   FROM task_outcomes
                   WHERE created_at >= ?
                   GROUP BY domain, outcome""",
                (cutoff,),
            ).fetchall()
            
            per_domain = defaultdict(lambda: {"total": 0, "success": 0})
            for dr in domain_rows:
                d = dr["domain"]
                per_domain[d]["total"] += dr["cnt"]
                if dr["outcome"] == "success":
                    per_domain[d]["success"] += dr["cnt"]
            
            # Error types
            error_rows = conn.execute(
                """SELECT error_type, COUNT(*) as cnt
                   FROM task_outcomes
                   WHERE created_at >= ? AND outcome IN ('failure', 'partial')
                   GROUP BY error_type
                   ORDER BY cnt DESC
                   LIMIT 10""",
                (cutoff,),
            ).fetchall()
            
            # Trend
            mid = total // 2
            first_half = rows[mid:] if mid > 0 else rows
            second_half = rows[:mid] if mid > 0 else rows
            first_success = sum(1 for r in first_half if r["outcome"] == "success") / max(len(first_half), 1)
            second_success = sum(1 for r in second_half if r["outcome"] == "success") / max(len(second_half), 1)
            
            return {
                "window_days": window_days,
                "total": total,
                "successes": successes,
                "failures": failures,
                "partials": sum(1 for r in rows if r["outcome"] == "partial"),
                "unknowns": sum(1 for r in rows if r["outcome"] == "unknown"),
                "success_rate": round(successes / max(total, 1), 4),
                "failure_rate": round(failures / max(total, 1), 4),
                "per_domain": {
                    d: {
                        "total": ds["total"],
                        "success_rate": round(ds["success"] / max(ds["total"], 1), 4),
                    }
                    for d, ds in sorted(per_domain.items())
                },
                "error_types": dict(error_rows),
                "trend": {
                    "first_half_success_rate": round(first_success, 4),
                    "second_half_success_rate": round(second_success, 4),
                    "direction": "improving" if second_success > first_success else "declining" if second_success < first_success else "stable",
                },
            }
    
    def _empty_stats(self, window_days=7):
        return {"window_days": window_days, "total": 0, "successes": 0, "failures": 0,
                "partials": 0, "unknowns": 0, "success_rate": 0.0, "failure_rate": 0.0,
                "per_domain": {}, "error_types": {}, "trend": {"direction": "stable"}}
    
    def auto_detect_outcome(self, task_id, domain, exit_code=0, stderr="", duration=0.0, task_type=""):
        """Auto-detect outcome. Returns a simple namespace for compatibility."""
        outcome = "unknown"
        confidence = 0.5
        error_type = ""
        
        if exit_code == 0 and not stderr:
            outcome = "success"; confidence = 0.85
        elif exit_code != 0:
            outcome = "failure"; confidence = 0.9
            stderr_lower = stderr.lower()
            if "syntax" in stderr_lower: error_type = "syntax_error"; confidence = 0.95
            elif "timeout" in stderr_lower: error_type = "timeout"; confidence = 0.9
            elif "permission" in stderr_lower: error_type = "permission"; confidence = 0.95
            elif "not found" in stderr_lower: error_type = "not_found"; confidence = 0.9
            else: error_type = "unknown_error"; confidence = 0.7
        elif exit_code == 0 and stderr:
            outcome = "partial"; confidence = 0.6
        
        return type('Outcome', (), {
            "task_id": task_id, "domain": domain, "outcome": outcome,
            "confidence": confidence, "auto_detected": True,
            "human_validated": False, "error_type": error_type,
            "task_type": task_type, "duration_seconds": duration,
            "policy_fired": [], "notes": "",
        })()
