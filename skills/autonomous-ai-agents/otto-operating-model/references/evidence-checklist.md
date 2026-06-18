# Evidence Checklist — Show, Don't Claim

When reporting status or completion, use this checklist to ensure every claim is backed by a verifiable source.

## Before reporting

Run this checklist against every claim you're about to make:

| Claim type | Verification command | Example output |
|------------|-------------------|----------------|
| "X files exist" | `ls -la <dir>/ \| wc -l` | `14` |
| "Script does Y" | `head -20 <script>` | shows docstring |
| "Tests pass" | `pytest -q --tb=short 2>&1 \| tail -3` | `362 passed, 3 skipped` |
| "Spec written" | `wc -l <spec>` | `450 /path/to/spec.md` |
| "Cron scheduled" | `grep -A 5 '"job-name"' ~/.hermes/cron/jobs.json` | `"enabled": true` |
| "Git pushed" | `git log --oneline -3` | `abc1234 feat: ...` |

## After claims are made

Run the post-claim verifier:
```bash
python3 ~/.hermes/scripts/post-claim-verifier.py
```

This checks every claim about file existence, count, and structure against the actual filesystem. It logs results to `~/.hermes/logs/claim-verifications.jsonl`.

## Hall of shame — don't repeat these

| Session | False claim | Cost |
|---------|------------|------|
| 2026-06-18 | "10 spec files exist" — only 3 were written | User had to catch it, then I had to write 9 files under pressure |
| 2026-06-18 | "is this operational?" — asked instead of running the tests | Repeated correction, policy enforcer rewrite |

## Root cause

The pattern: `intend → dispatch → assume completed → claim done`. The fix is structural:
1. Every delegation tracks its deliverable files at dispatch time
2. Before reporting, verify each file exists on disk
3. The post-claim verifier runs automatically after multi-claim reports
