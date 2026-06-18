#!/usr/bin/env python3
"""
Async Job Queue — Background task dispatch and job state persistence.

Provides a simple job queue built on terminal-based dispatching
(background=true, notify_on_complete=true) with crash-safe state persistence.

Job lifecycle:
    queued → running → done | failed | blocked

State persists to ~/.hermes/task-queue/jobs.json so crashes don't lose work.

Usage:
    # Create and dispatch a job
    job = Job.create(goal="Run tests", command="pytest tests/")
    job.dispatch()

    # Check status
    job = Job.load(job_id)
    print(job.status, job.result)

    # Get pending recoveries
    pending = get_pending_jobs()
    for job in pending:
        job.execute_recovery()

    # List all jobs
    for job in list_jobs():
        print(job.id, job.status)
"""

import json
import time
import uuid
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Callable

from task_result import TaskResult, classify_task_output


# ── Paths ────────────────────────────────────────────────────────────────────

QUEUE_DIR = Path.home() / ".hermes" / "task-queue"
QUEUE_FILE = QUEUE_DIR / "jobs.json"


def _ensure_queue_dir():
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)


# ── Job dataclass ────────────────────────────────────────────────────────────

class Job:
    """
    A single async job/task with lifecycle management.

    Attributes:
        id: Unique job identifier
        goal: Human-readable task description
        command: Shell command to execute (for terminal-based dispatch)
        status: "queued" | "running" | "done" | "failed" | "blocked"
        result: TaskResult (populated on completion)
        created_at: ISO timestamp
        updated_at: ISO timestamp
        session_id: terminal background session_id (if running)
        metadata: Arbitrary extra data
    """

    def __init__(
        self,
        goal: str,
        command: Optional[str] = None,
        job_id: Optional[str] = None,
        status: str = "queued",
        result: Optional[TaskResult] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        self.id: str = job_id or str(uuid.uuid4())
        self.goal: str = goal
        self.command: Optional[str] = command
        self.status: str = status
        self.result: Optional[TaskResult] = result
        self.created_at: str = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at: str = updated_at or self.created_at
        self.session_id: Optional[str] = session_id
        self.metadata: dict = metadata or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "command": self.command,
            "status": self.status,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        result = None
        if data.get("result"):
            result = TaskResult(**data["result"])
        return cls(
            job_id=data.get("id"),
            goal=data.get("goal", ""),
            command=data.get("command"),
            status=data.get("status", "queued"),
            result=result,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            session_id=data.get("session_id"),
            metadata=data.get("metadata", {}),
        )

    def save(self):
        """Persist this job to the queue file."""
        _ensure_queue_dir()
        jobs = _load_all_jobs()
        jobs[self.id] = self
        _save_all_jobs(jobs)

    @classmethod
    def load(cls, job_id: str) -> Optional["Job"]:
        """Load a job by ID from the queue file."""
        jobs = _load_all_jobs()
        return jobs.get(job_id)

    def dispatch(
        self,
        workdir: Optional[str] = None,
        timeout: int = 600,
    ) -> str:
        """
        Dispatch this job using terminal(background=true).

        Updates status to "running", saves the session_id, and returns
        the session_id for tracking.

        Args:
            workdir: Working directory for the command
            timeout: Command timeout in seconds (default: 600)

        Returns:
            session_id for the background process
        """
        from task_state import save_task_state

        if not self.command:
            raise ValueError("Job has no command to dispatch")

        self.status = "running"
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()

        # Save task state before dispatch
        save_task_state(
            task_description=f"[JOB {self.id}] {self.goal}",
            last_action=f"dispatched job {self.id}",
            metadata={"job_id": self.id, "command": self.command},
        )

        # Start the background process
        result = subprocess.run(
            ["hermes", "terminal", "--background", "--notify-on-complete",
             "--timeout", str(timeout),
             "--command", self.command],
            capture_output=True, text=True, timeout=10,
        )

        # Parse session_id from output
        # Hermes returns something like "Session ID: xxx"
        output = result.stdout + result.stderr
        session_id = None
        for line in output.splitlines():
            if "session" in line.lower() and ":" in line:
                parts = line.split(":", 1)
                if len(parts) > 1:
                    session_id = parts[1].strip()
                    break

        if session_id:
            self.session_id = session_id
            self.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()

        return session_id or output

    def complete(self, result: TaskResult):
        """
        Mark this job as completed with the given result.

        Sets status based on result.is_success:
          - success → "done"
          - failure + transient → "done" (retry handled externally)
          - failure + logic → "failed"
          - failure + blocked → "blocked"
        """
        if result.error_class == "blocked":
            self.status = "blocked"
        elif result.error_class == "logic":
            self.status = "failed"
        elif result.is_success:
            self.status = "done"
        else:
            self.status = "failed"

        self.result = result
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()

    def execute_recovery(self) -> Optional[TaskResult]:
        """
        Execute recovery for a failed/blocked job.

        Returns:
            TaskResult after recovery, or None if nothing to recover.
        """
        if self.status == "done":
            return self.result

        if self.status == "blocked":
            from recovery_loop import surface_blocked
            return surface_blocked(
                goal=self.goal,
                last_result=self.result or TaskResult(
                    status="failure",
                    error="Unknown blocker",
                    error_class="blocked",
                ),
            )

        if self.status in ("failed", "running"):
            from recovery_loop import retry_transient
            return retry_transient(
                dispatch_fn=lambda: self._re_dispatch_sync(),
                goal=self.goal,
                attempt=1,
                last_result=self.result or TaskResult(
                    status="failure",
                    error="No result recorded",
                    error_class="transient",
                ),
                total_retries=3,
            )

        return None

    def _re_dispatch_sync(self) -> TaskResult:
        """Re-dispatch the command synchronously and return a TaskResult."""
        if not self.command:
            return TaskResult(
                status="failure",
                error="No command to re-dispatch",
                error_class="blocked",
            )
        try:
            proc = subprocess.run(
                self.command,
                shell=True, capture_output=True, text=True, timeout=300,
            )
            result = classify_task_output(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
            self.complete(result)
            return result
        except subprocess.TimeoutExpired:
            return TaskResult(
                status="failure",
                error="Command timed out during re-dispatch",
                error_class="transient",
            )
        except Exception as e:
            return TaskResult(
                status="failure",
                error=str(e),
                error_class="transient",
            )

    def __repr__(self) -> str:
        return f"Job(id={self.id}, goal={self.goal!r}, status={self.status})"


# ── Queue persistence ────────────────────────────────────────────────────────

def _load_all_jobs() -> dict[str, Job]:
    """Load all jobs from the queue file."""
    if not QUEUE_FILE.exists():
        return {}
    try:
        data = json.loads(QUEUE_FILE.read_text())
        return {jid: Job.from_dict(jdata) for jid, jdata in data.items()}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def _save_all_jobs(jobs: dict[str, Job]):
    """Save all jobs to the queue file."""
    _ensure_queue_dir()
    data = {jid: job.to_dict() for jid, job in jobs.items()}
    QUEUE_FILE.write_text(json.dumps(data, indent=2))


# ── Queue operations ─────────────────────────────────────────────────────────

def create_job(
    goal: str,
    command: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Job:
    """
    Create a new job in the queue.

    Args:
        goal: Human-readable description
        command: Shell command to execute (or None for manual dispatch)
        metadata: Extra data to attach

    Returns:
        The new Job (status="queued")
    """
    job = Job(goal=goal, command=command, metadata=metadata or {})
    job.save()
    return job


def get_job(job_id: str) -> Optional[Job]:
    """Get a job by ID."""
    return Job.load(job_id)


def get_pending_jobs() -> List[Job]:
    """
    Get all jobs that need attention (failed, blocked, or running without session).

    Returns:
        List of Job objects needing recovery or cleanup.
    """
    return [j for j in _load_all_jobs().values()
            if j.status in ("failed", "blocked", "running")]


def list_jobs(
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> List[Job]:
    """
    List all jobs, optionally filtered by status.

    Args:
        status_filter: "queued" | "running" | "done" | "failed" | "blocked" | None
        limit: Maximum number of jobs to return (default: 50)

    Returns:
        List of Job objects, sorted by created_at descending.
    """
    jobs = list(_load_all_jobs().values())
    if status_filter:
        jobs = [j for j in jobs if j.status == status_filter]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs[:limit]


def cleanup_old_jobs(max_age_hours: int = 72) -> int:
    """
    Remove jobs older than max_age_hours from the queue.

    Args:
        max_age_hours: Maximum age in hours (default: 72)

    Returns:
        Number of jobs removed.
    """
    from dateutil.parser import isoparse  # stdlib workaround below
    # Manual ISO parsing for stdlib-only compatibility
    now = datetime.now(timezone.utc)
    cutoff_seconds = max_age_hours * 3600

    jobs = _load_all_jobs()
    to_remove = []

    for jid, job in jobs.items():
        try:
            created = datetime.fromisoformat(job.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = (now - created).total_seconds()
            if age > cutoff_seconds:
                to_remove.append(jid)
        except (ValueError, TypeError):
            to_remove.append(jid)  # Remove malformed entries

    for jid in to_remove:
        del jobs[jid]

    _save_all_jobs(jobs)
    return len(to_remove)


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: async_queue.py [create|list|get|pending|cleanup]")
        print("\nCommands:")
        print("  create <goal> [--command <cmd>]  — create a new job")
        print("  list [status]                    — list jobs (optionally filtered)")
        print("  get <job_id>                     — show job details")
        print("  pending                          — show pending/failed/blocked jobs")
        print("  cleanup [hours]                  — remove old jobs (default: 72h)")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "create":
        if len(sys.argv) < 3:
            print("Usage: async_queue.py create <goal> [--command <cmd>]")
            sys.exit(1)
        goal = sys.argv[2]
        command = None
        if "--command" in sys.argv:
            idx = sys.argv.index("--command")
            command = " ".join(sys.argv[idx + 1:]) if len(sys.argv) > idx + 1 else None
        job = create_job(goal=goal, command=command)
        print(json.dumps(job.to_dict(), indent=2))

    elif cmd == "list":
        status_filter = sys.argv[2] if len(sys.argv) > 2 else None
        jobs = list_jobs(status_filter=status_filter)
        if jobs:
            for job in jobs:
                print(f"  [{job.status:>7}] {job.id[:8]}...  {job.goal[:60]}")
        else:
            print("No jobs found")

    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Usage: async_queue.py get <job_id>")
            sys.exit(1)
        job = get_job(sys.argv[2])
        if job:
            print(json.dumps(job.to_dict(), indent=2))
        else:
            print(f"Job not found: {sys.argv[2]}")

    elif cmd == "pending":
        jobs = get_pending_jobs()
        if jobs:
            print("Pending jobs:")  # noqa: F821 (intentionally)
            for job in jobs:
                print(f"  [{job.status:>7}] {job.id[:8]}...  {job.goal[:60]}")
        else:
            print("No pending jobs")

    elif cmd == "cleanup":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 72
        removed = cleanup_old_jobs(max_age_hours=hours)
        print(f"Removed {removed} old job(s)")
