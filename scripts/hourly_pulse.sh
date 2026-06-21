#!/bin/bash
# Otto Hourly Improvement Pulse
# Runs every hour. Reflects on the last hour and surfaces improvement ideas.
# Silent unless there's something worth surfacing.

REFLECTION_DIR="$HOME/.hermes/logs/improvement-pulse"
mkdir -p "$REFLECTION_DIR"
PULSE_FILE="$REFLECTION_DIR/$(date +%Y-%m-%d-%H).md"
CORRECTION_LOG="$HOME/.hermes/logs/corrections.md"
NEVER_AGAIN="$HOME/.hermes/skills/autonomous-ai-agents/otto-operating-model/SKILL.md"
DAILY_REFLECTION="$HOME/.hermes/logs/reflection/$(date +%Y-%m-%d).md"

# ---- Metrics for this hour ----

# 1. How many times was I corrected this session? (count "Corrected" entries in the reflection)
CORRECTIONS_TODAY=$(grep -c "Corrected" "$DAILY_REFLECTION" 2>/dev/null || echo "0")

# 2. How many items in the Never Again list am I repeating?
REPEATED=$(grep -c "\[ \]" "$NEVER_AGAIN" 2>/dev/null || echo "0")

# 3. Any orphaned processes?
STALE_PROCS=$(ps aux | grep -E "pytest|claude" | grep -v grep | wc -l | tr -d ' ')

# 4. How long since last user interaction? (check last modified on this script's trigger)
# Skip this if we can't determine it.

# ---- Improvement ideas ----
# These are templates I should reflect on each hour:

IDEAS_FILE="$REFLECTION_DIR/ideas.md"

if [ ! -f "$IDEAS_FILE" ]; then
  cat > "$IDEAS_FILE" << 'IDEAEOF'
# Improvement Ideas — add new ones as they occur

- [ ] Could I have dispatched this work in parallel instead of sequentially?
- [ ] Did I present options when I should have just acted?
- [ ] Did I wait for instruction when the priority was clear?
- [ ] Is there a cron job I should set up to make this automatic?
- [ ] Is there a skill I should write to encode this pattern?
- [ ] Could a cheaper model have done this work?
- [ ] Did I surface something to the user that I could have resolved myself?
- [ ] Is there a "Never Again" entry I should add?
IDEAEOF
fi

# ---- Build pulse ----
HOUR=$(date +%H)

# Only surface on specific hours to avoid spam
# Surface at :00 past each hour but only write to file
# Only send to Telegram if there's something noteworthy

NOTEWORTHY=""

# Check for stale processes
if [ "$STALE_PROCS" -gt 5 ]; then
  NOTEWORTHY="$NOTEWORTHY\n⚠️ $STALE_PROCS stale processes running"
fi

# Check for repeated corrections
if [ "$REPEATED" -gt 0 ]; then
  NOTEWORTHY="$NOTEWORTHY\n⚠️ $REPEATED Never Again items unchecked — review SKILL.md"
fi

# Write the pulse
cat > "$PULSE_FILE" << EOF
# Hourly Pulse — $(date "+%Y-%m-%d %H:00")

Corrections today: $CORRECTIONS_TODAY
Never Again unchecked: $REPEATED
Stale processes: $STALE_PROCS

## Reflection
- What did I do this hour that I should never do again?
- What did I do this hour that I should always do?
- What did I learn?

## Improvements for next hour
1. 
2. 
3. 
EOF

# Surface if noteworthy (silenced to prevent theater alerts)
# if [ -n "$NOTEWORTHY" ]; then
#   echo -e "🔄 **Hourly Pulse**$NOTEWORTHY"
# fi

# Every 4th hour (00, 04, 08, 12, 16, 20) surface proactively with an improvement suggestion (silenced)
# HOUR_NUM=$(date +%H | sed 's/^0//')
# if [ $((HOUR_NUM % 4)) -eq 0 ] && [ "$STALE_PROCS" -le 5 ] && [ "$REPEATED" -eq 0 ]; then
#   echo "🔄 Pulse — all clear. Next improvement idea: $(head -1 "$IDEAS_FILE" | grep -oP '(?<=\[ \] ).*' || echo 'check ideas.md')"
# fi
