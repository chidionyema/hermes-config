# Otto Session Objectives
*Auto-managed. Update after each task completion.*

## Active Objectives

| ID | Objective | Success Criteria | Status | Started | 
|----|-----------|-----------------|--------|---------|
| | | | | |

## Completed

| ID | Objective | Outcome | Completed |
|----|-----------|---------|-----------|
| | | | |

## Pattern for success criteria

Every task assigned to Otto should have explicit success criteria before dispatch:
- **TRANSIENT failures:** retry 3x with backoff (2s, 5s, 15s)
- **LOGIC failures:** escalate to strategist for replan
- **BLOCKED failures:** queue, report to user
- **PASS:** capture positive policy if exceptional
- **PASS + exceptional:** positive policy candidate (documented at creation time)
