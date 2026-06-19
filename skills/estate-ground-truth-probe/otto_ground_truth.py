#!/usr/bin/env python3
"""otto_ground_truth_v3 — widened estate reality probe"""
import json, os, subprocess, sqlite3, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.path.expanduser("~"))

def hr(t): print("\n"+"="*72); print(t); print("="*72)
def _t(): return time.monotonic()
def _elapsed(t0): return f"({time.monotonic()-t0:.1f}s)"
def run(cmd, timeout=10):
    try:
        p=subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=timeout)
        return p.returncode,p.stdout.rstrip(),p.stderr.rstrip()
    except subprocess.TimeoutExpired: return -1,"",f"TIMEOUT {timeout}s"
    except Exception as e: return -2,"",str(e)
def now(): return datetime.now(timezone.utc).isoformat()

print("OTTO GROUND-TRUTH PROBE v3"); print(f"captured_at_utc: {now()}")
print(f"host_user: {os.environ.get('USER','unknown')}  home: {HOME}")
rc,uname,_=run("uname -a"); print(f"uname: {uname}")

# ---- 0. profile discovery ----
hr("0. HERMES PROFILES")
cands=set([HOME/".hermes"])
for base in [HOME/".hermes-profiles", HOME/".config"/"hermes", HOME]:
    if base.exists():
        for p in base.glob("*"):
            if p.is_dir() and ((p/"cron").exists() or (p/"config.yaml").exists() or (p/"skills").exists()):
                cands.add(p)
if os.environ.get("HERMES_HOME"): cands.add(Path(os.environ["HERMES_HOME"]))
rc,out,_=run(f"find '{HOME}' -maxdepth 4 -name jobs.json 2>/dev/null | head -20")
for l in (out.splitlines() if out else []): cands.add(Path(l).parent.parent)
profiles=sorted({c for c in cands if c.exists()})
print(f"HERMES_HOME env: {os.environ.get('HERMES_HOME','(unset)')}")
for p in profiles: print(f"  - {p}")

# ---- 1. never-run job diagnosis ----
hr("1. NEVER-RUN JOB DIAGNOSIS (the 3 null last_run jobs)")
for prof in profiles:
    jj=prof/"cron"/"jobs.json"
    if not jj.exists(): continue
    try:
        data=json.loads(jj.read_text())
        jobs=data if isinstance(data,list) else data.get("jobs",data)
        if isinstance(jobs,dict): jobs=list(jobs.values())
        for j in jobs:
            if j.get("last_run_at") in (None,"","null"):
                print(f"\nNEVER RAN: {str(j.get('id'))[:12]}  {j.get('name')}")
                print(f"  schedule: {json.dumps(j.get('schedule'))}")
                print(f"  enabled={j.get('enabled')} state={j.get('state')} next_run_at={j.get('next_run_at')}")
                print(f"  model={j.get('model')} provider={j.get('provider')}")
                print(f"  skills={j.get('skills')} script={j.get('script')}")
                print(f"  created_at={j.get('created_at')}")
    except Exception as e: print(f"  !! {jj}: {e}")

# ---- 2. daemon watchdog diagnosis ----
# Iterate profiles and STOP early — .claude/.codex project dirs have millions of memory files.
# Only look under .hermes for daemon files. Use a bounded find instead of rglob.
hr("2. DAEMON WATCHDOG DIAGNOSIS (signal-engine)")
hermes_only = [p for p in profiles if p.name == ".hermes"]
for prof in hermes_only:
    for guess in ["scripts/signal-engine-daemon-watchdog.sh",
                  "scripts/signal-engine-daemon-watchdog.py",
                  "scripts/signalengine-watchdog.sh"]:
        f = prof / guess
        if f.exists():
            print(f"\n--- {f} (first 40 lines) ---")
            print("\n".join(f.read_text(errors='replace').splitlines()[:40]))
# bounded find under .hermes (maxdepth 4) for any daemon file
rc,out,_=run(f"find '{HOME}/.hermes' -maxdepth 4 -type f \\( -iname '*daemon*' -o -iname '*signal*watch*' \\) 2>/dev/null | head -20")
print(f"\ndaemon/signal-watch files under .hermes (maxdepth 4):")
print(out if out else "  (none)")
# signalengine dir hunt — bounded
rc,out,_=run(f"find '{HOME}' -maxdepth 5 -iname '*signalengine*' -type d 2>/dev/null | head")
print(f"\nsignalengine dirs (maxdepth 5): {out or '(none found)'}")
# and check if the actual daemon entrypoint is alive by checking the process listing
print("\nactual daemon process check:")
rc,out,_=run("ps aux 2>/dev/null | grep -E 'signal.engine|signal_engine' | grep -v grep | head")
print(out if out else "  (no signal-engine / signal_engine process found)")

# ---- 3. FULL process snapshot ----
hr("3. FULL PROCESS SNAPSHOT (python/node/daemon-ish, unfiltered by our terms)")
rc,out,_=run("ps aux 2>/dev/null | grep -iE 'python|node|daemon|hermes|claude|signal|cron|agy' | grep -v grep")
print(out if out else "(none)")
print("\n-- launchd/cron registrations (Mac) --")
rc,out,_=run("launchctl list 2>/dev/null | grep -iE 'hermes|signal|otto|claude' ; crontab -l 2>/dev/null | head -30")
print(out if out else "(none / not mac / empty crontab)")

# ---- 4. deep repo git state (parallel) ----
hr("4. GIT STATE (deep, parallel)")
t4=_t()
roots=[HOME, HOME/"code", HOME/"code-backup", HOME/"Documents", HOME/"Documents"/"code", HOME/"projects"]
gitdirs=set()
# one bounded find across all roots, parallel via xargs
existing=[str(r) for r in roots if r.exists()]
if existing:
    # Run each root's find IN PARALLEL with strict per-root timeout so one slow
    # root (e.g. Documents on macOS with Time Machine snapshots) doesn't kill the rest.
    def _find_one(root):
        try:
            r=subprocess.run(["find", root, "-maxdepth", "6", "-name", ".git",
                              "-type", "d"],
                             capture_output=True, text=True, timeout=8)
            return r.stdout
        except subprocess.TimeoutExpired:
            return ""
    with ThreadPoolExecutor(max_workers=len(existing)) as ex:
        for out in ex.map(_find_one, existing):
            for l in out.splitlines():
                if l.strip():
                    gitdirs.add(Path(l).parent)
print(f"repos found: {len(gitdirs)}  (find: {_elapsed(t4)})")

def _git_check(repo):
    try:
        r=subprocess.run(["git","-C",str(repo),"status","--porcelain"],
                         capture_output=True,text=True,timeout=5)
        cnt=len(r.stdout.splitlines()) if r.stdout else 0
        r=subprocess.run(["git","-C",str(repo),"rev-parse","--abbrev-ref","HEAD"],
                         capture_output=True,text=True,timeout=5)
        br=r.stdout.strip()
        r=subprocess.run(["git","-C",str(repo),"rev-list","--count","@u..HEAD"],
                         capture_output=True,text=True,timeout=5)
        ah=r.stdout.strip()
        return str(repo), br, cnt, ah
    except Exception as e:
        return str(repo), "?", 0, f"err:{e}"

total_dirty=0
repo_list=sorted(gitdirs)
if repo_list:
    with ThreadPoolExecutor(max_workers=8) as ex:
        results=list(ex.map(_git_check, repo_list))
    for path, br, cnt, ah in sorted(results):
        total_dirty+=cnt
        flag=" <-- DIRTY" if cnt else ""
        print(f"  {path}  branch={br or '?'} uncommitted={cnt} unpushed={ah or '?'}{flag}")
print(f"\nTOTAL uncommitted files across all repos: {total_dirty}  (section 4: {_elapsed(t4)})")

# ---- 5. session DB / memory store hunt (parallel) ----
hr("5. SESSION DB / MEMORY STORE HUNT (parallel)")
t5=_t()
search_roots=[HOME/".hermes"]
for app in ["Hermes", "hermes-agent", "Otto"]:
    p = HOME/"Library"/"Application Support"/app
    if p.exists():
        search_roots.append(p)
found_dbs=[]
for r in search_roots:
    if not r.exists(): continue
    rc,out,_=run(f"find '{r}' -maxdepth 6 -type f \\( -iname '*.db' -o -iname '*.sqlite*' -o -iname '*.db3' \\) 2>/dev/null | head -40", timeout=8)
    for l in (out.splitlines() if out else []): found_dbs.append(l)
print(f"candidate DBs: {len(found_dbs)}  (find: {_elapsed(t5)})")

def _inspect(db):
    try:
        con=sqlite3.connect(f"file:{db}?mode=ro",uri=True,timeout=3)
        tabs=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()]
        rows={}
        for t in tabs:
            if any(k in t.lower() for k in ['session','message','memory','conversation','chat','fts']):
                try: rows[t]=con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception: pass
        con.close()
        return db, tabs, rows, None
    except Exception as e:
        return db, [], {}, str(e)

if found_dbs:
    with ThreadPoolExecutor(max_workers=8) as ex:
        for db, tabs, rows, err in ex.map(_inspect, found_dbs):
            print(f"\n  {db}")
            if err:
                print(f"    (unreadable: {err})"); continue
            print(f"    tables: {tabs[:20]}")
            for t, n in rows.items():
                print(f"      {t}: {n} rows")

print("\n-- memory files --")
for prof in profiles:
    for name in ["MEMORY.md","USER.md","SOUL.md"]:
        for loc in [prof/name, prof/"memory"/name]:
            if loc.exists(): print(f"  {loc}: {len(loc.read_text(errors='replace'))} chars")

hr("END v3 — paste EVERYTHING above, verbatim")
print(f"captured_at_utc: {now()}")
