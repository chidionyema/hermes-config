"""
Circuit breaker for self-healing operations. Stops infinite retry loops.

The audit found: summarizer (463 heal attempts), strategist-audit (382), 
hermes-config-auto-push (71). These runaway retries waste resources.

This module adds exponential backoff + hard circuit breaking after K failures.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps


class CircuitBreakerOpen(Exception):
    """Raised when a circuit is open — stop retrying."""
    pass


class CircuitBreaker:
    """Stateful circuit breaker with half-open reset.
    
    States: CLOSED (normal) → OPEN (stop trying) → HALF_OPEN (test once)
    
    After max_failures consecutive failures, circuit OPENS and blocks
    all further attempts for reset_timeout seconds. After timeout,
    enters HALF_OPEN — allows one attempt. If it succeeds, closes.
    If it fails, re-opens with doubled timeout (exponential backoff).
    """
    
    def __init__(self, name: str, state_dir: Path = None, 
                 max_failures: int = 5, reset_timeout: int = 300):
        self.name = name
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.state_dir = state_dir or Path.home() / ".hermes" / "state" / "circuit_breakers"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
    
    def _state_file(self) -> Path:
        return self.state_dir / f"{self.name}.json"
    
    def _load_state(self):
        sf = self._state_file()
        if sf.is_file():
            try:
                state = json.loads(sf.read_text())
                self.failures = state.get("failures", 0)
                self.last_failure_time = state.get("last_failure_time", 0)
                self.total_attempts = state.get("total_attempts", 0)
                self.current_timeout = state.get("current_timeout", self.reset_timeout)
                self.state = state.get("state", "closed")
            except (json.JSONDecodeError, KeyError):
                self._reset()
        else:
            self._reset()
    
    def _save_state(self):
        self._state_file().write_text(json.dumps({
            "name": self.name,
            "failures": self.failures,
            "last_failure_time": self.last_failure_time,
            "total_attempts": self.total_attempts,
            "current_timeout": self.current_timeout,
            "state": self.state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2))
    
    def _reset(self):
        self.failures = 0
        self.last_failure_time = 0
        self.total_attempts = 0
        self.current_timeout = self.reset_timeout
        self.state = "closed"
    
    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            self._load_state()  # Re-read state (may have been updated by another process)
            
            if self.state == "open":
                elapsed = time.time() - self.last_failure_time
                if elapsed > self.current_timeout:
                    # Enter half-open — allow one test attempt
                    self.state = "half_open"
                    self._save_state()
                else:
                    remaining = int(self.current_timeout - elapsed)
                    raise CircuitBreakerOpen(
                        f"Circuit OPEN for '{self.name}'. "
                        f"{self.failures} failures. Retry in {remaining}s. "
                        f"({self.total_attempts} total attempts)"
                    )
            
            try:
                result = func(*args, **kwargs)
                # Success! Reset the circuit
                self._reset()
                self._save_state()
                return result
            except Exception as e:
                self.failures += 1
                self.total_attempts += 1
                self.last_failure_time = time.time()
                
                if self.failures >= self.max_failures:
                    self.state = "open"
                    # Exponential backoff: double timeout each time we re-open
                    if self.failures > self.max_failures:
                        self.current_timeout = min(self.current_timeout * 2, 86400)  # Cap at 24h
                    self._save_state()
                    raise CircuitBreakerOpen(
                        f"Circuit OPENED for '{self.name}' after {self.failures} "
                        f"consecutive failures. Blocked for {self.current_timeout}s."
                    ) from e
                
                self._save_state()
                raise
        
        return wrapper
    
    def reset(self):
        """Manually reset the circuit breaker."""
        self._reset()
        self._save_state()
    
    def status(self) -> dict:
        """Get current circuit breaker status."""
        return {
            "name": self.name,
            "state": self.state,
            "failures": self.failures,
            "total_attempts": self.total_attempts,
            "current_timeout": self.current_timeout,
            "max_failures": self.max_failures,
        }


# Pre-initialized breakers for known runaway jobs
BREAKERS = {
    "summarizer": CircuitBreaker("summarizer", max_failures=3, reset_timeout=3600),
    "strategist_audit": CircuitBreaker("strategist-audit", max_failures=3, reset_timeout=3600),
    "config_auto_push": CircuitBreaker("hermes-config-auto-push", max_failures=5, reset_timeout=600),
    "self_healer": CircuitBreaker("self-healer", max_failures=10, reset_timeout=1800),
    "self_improve": CircuitBreaker("self-improve-runner", max_failures=3, reset_timeout=900),
}


def get_breaker(name: str) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    if name in BREAKERS:
        return BREAKERS[name]
    return CircuitBreaker(name)


def list_breakers() -> list[dict]:
    """List all circuit breaker states."""
    return [b.status() for b in BREAKERS.values()]


# ── CLI ──
def main():
    import argparse
    p = argparse.ArgumentParser(description="Circuit breaker management")
    p.add_argument("--list", action="store_true", help="List all breakers")
    p.add_argument("--reset", metavar="NAME", help="Reset a breaker")
    args = p.parse_args()
    
    if args.list:
        for status in list_breakers():
            icon = {"closed": "🟢", "half_open": "🟡", "open": "🔴"}.get(status["state"], "⚪")
            print(f"{icon} {status['name']}: {status['state']} "
                  f"({status['failures']} failures, {status['total_attempts']} total)")
    
    if args.reset:
        cb = get_breaker(args.reset)
        cb.reset()
        print(f"✅ Reset {args.reset}")


if __name__ == "__main__":
    main()
