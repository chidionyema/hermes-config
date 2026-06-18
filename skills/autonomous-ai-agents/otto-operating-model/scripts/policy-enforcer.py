#!/usr/bin/env python3
"""
Policy enforcer — runtime pre-action gate.
Classifies every action by resource needs (auto_exec / needs_human / needs_clarification).
Zero question-form detection. Whitelist-based.
See ~/.hermes/scripts/policy-enforcer.py for the live version.
This is a symlink reference — the actual file lives at ~/.hermes/scripts/policy-enforcer.py
"""
import sys
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from policy_enforcer import enforce  # noqa
