#!/usr/bin/env bash
# UI/UX check for the Hermes agent's commercial_ui.py (Telegram UI + dashboard)
# More UI polish iterations = higher score
# Exit 0 = all critical checks pass, exit 1 = failures remain

cd /Users/chidionyema/.hermes/hermes-agent

score=0
total=0
failures=""

check() {
    local name="$1"
    local cmd="$2"
    total=$((total + 1))
    if eval "$cmd" >/dev/null 2>&1; then
        score=$((score + 1))
    else
        failures="$failures\n- $name"
    fi
}

# --- Critical UI checks ---

# 1. No em-dashes in commercial_ui.py
check "no em-dashes in commercial_ui.py" \
    "! grep -nP '[\x{2014}]' gateway/operator_shell/commercial_ui.py 2>/dev/null | head -1"

# 2. No em-dashes in health_panel.py
check "no em-dashes in health_panel.py" \
    "! grep -nP '[\x{2014}]' gateway/operator_shell/health_panel.py 2>/dev/null | head -1"

# 3. Keyboard functions exist (Telegram inline buttons)
check "keyboard rendering functions exist" \
    "grep -q 'def get_persistent_keyboard\|def render_keyboard' gateway/operator_shell/commercial_ui.py 2>/dev/null"

# 4. Health panel has status indicators
check "health panel has status checks" \
    "grep -q 'def render_health' gateway/operator_shell/health_panel.py 2>/dev/null"

# 5. Files have docstrings
check "commercial_ui has module docstring" \
    "head -20 gateway/operator_shell/commercial_ui.py | grep -q '\"\"\"'"

# 6. Type hints on public functions
check "type hints on render functions" \
    "grep -q 'def render.*->.*:' gateway/operator_shell/commercial_ui.py 2>/dev/null"

# 7. No hardcoded paths
check "no hardcoded /Users/ paths" \
    "! grep -rn '/Users/' gateway/operator_shell/commercial_ui.py gateway/operator_shell/health_panel.py 2>/dev/null | head -1"

# 8. Error handling on network calls
check "error handling on requests" \
    "grep -q 'try:.*\\n.*except' gateway/operator_shell/commercial_ui.py 2>/dev/null"

# 9. Integrity check passes (the files must be tracked)
check "operator_shell files are git-tracked" \
    "git ls-files gateway/operator_shell/commercial_ui.py gateway/operator_shell/health_panel.py | grep -q 'commercial_ui.py'"

# 10. Tests pass for operator_shell
check "operator_shell tests pass" \
    "cd ~/.hermes/hermes-agent && HERMES_LANE=claude python -m pytest tests/gateway/operator_shell/ -x --timeout=30 -q 2>/dev/null | grep -q 'passed'"

# --- Output ---
echo "SCORE: $score"
[ -n "$failures" ] && echo -e "FAILED:$failures"

# Done when score >= 9
if [ "$score" -ge 9 ]; then
    exit 0
else
    exit 1
fi
