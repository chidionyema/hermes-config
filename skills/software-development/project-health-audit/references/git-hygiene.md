# Git Hygiene Checks

Run these checks when auditing: "is everything backed up?", "are repos clean?", or during a periodic health sweep.

## What to Check

### Per-repo status
```bash
for repo in ~/.hermes ~/Documents/code/prospector ~/Documents/code/signalengine ~/Documents/code/lux; do
  cd "$repo" && echo "--- $(basename $repo) ---"
  echo "remote: $(git remote get-url origin 2>/dev/null)"
  echo "branch: $(git branch --show-current)"
  echo "dirty: $(git status --short | wc -l) files"
  echo "last push: $(git log -1 --format='%h %ar %s' 2>/dev/null)"
  echo ""
done
```

### Untracked agent/checkpoint junk
```bash
# These directories should NEVER be committed
for dir in .agent/ .checkpoints/ .lux/receipts/; do
  found=$(find . -name "$dir" -type d 2>/dev/null)
  if [ -n "$found" ]; then
    echo "⚠️ Found $dir in repo — should be in .gitignore"
    echo "$found"
  fi
done
```

### Gitignore coverage
Check each repo has `.agent/`, `.checkpoints/`, and transient data dirs in `.gitignore`:
```bash
for repo in ~/.hermes ~/Documents/code/prospector ~/Documents/code/signalengine ~/Documents/code/lux; do
  cd "$repo"
  missing=""
  for pattern in ".agent/" ".checkpoints/" ".lux/receipts/" "*.log.jsonl"; do
    grep -q "$pattern" .gitignore 2>/dev/null || missing="$missing $pattern"
  done
  [ -n "$missing" ] && echo "⚠️ $(basename $repo): missing gitignore entries: $missing"
done
```

### Last push age
Flag any repo with last push > 48 hours ago (indicates stale backup):
```bash
for repo in ~/.hermes ~/Documents/code/prospector ~/Documents/code/signalengine ~/Documents/code/lux; do
  cd "$repo" && last=$(git log -1 --format='%ct' 2>/dev/null)
  now=$(date +%s)
  age=$(( (now - last) / 3600 ))
  [ $age -gt 48 ] && echo "🔴 $(basename $repo): last push $age hours ago"
done
```

## What to Fix

| Symptom | Fix |
|---------|-----|
| `.agent/` or `.checkpoints/` tracked in git | Add to `.gitignore`, `git rm -r --cached`, commit, push |
| Uncommitted work that matters | `git add -A && git commit -m "..." && git push` |
| `node_modules/` or `venv/` tracked | Add to `.gitignore`, `git rm -r --cached` |
| Too many agent/task files in repo | Add `*.log.ndjson` / `*.ndjson` / `delegate-jobs/` to `.gitignore` |
| `package-lock.json` missing from `.gitignore` for tool projects | Add it — only app projects should track lockfiles |

## Key Principle

Hermes config (`~/.hermes`) has an hourly auto-push cron that handles it automatically. But the first push after any session should happen manually in-session so there's no gap window. The cron only catches what was left behind.
