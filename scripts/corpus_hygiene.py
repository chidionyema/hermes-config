#!/usr/bin/env python3
"""corpus_hygiene.py — collapse health-bridge spam into unique failure classes.

The self-regression corpus ballooned to ~1500 near-identical "repo dirty / timeout"
lines (0.3% coverage theater). This keeps ONE entry per templated (trigger, fix)
class, archives the rest, and optionally writes a coverage-friendly corpus.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone

HERMES = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
CORPUS = os.path.join(HERMES, "logs", "self-regression-corpus.json")
ARCHIVE_DIR = os.path.join(HERMES, "logs", "corpus-archive")


def template_key(entry: dict) -> str:
    """Normalize count noise so dirty(2)/dirty(18) collapse."""
    trig = (entry.get("trigger") or "").lower()
    fix = (entry.get("fix") or "").lower()
    trig = re.sub(r"\d+", "N", trig)
    trig = re.sub(r"\s+", " ", trig).strip()[:160]
    fix = re.sub(r"\d+", "N", fix)
    fix = re.sub(r"\s+", " ", fix).strip()[:160]
    domain = (entry.get("domain") or "").split("/")[0] or "general"
    return f"{domain}|{trig}|{fix}"


def is_health_bridge_spam(entry: dict) -> bool:
    trig = (entry.get("trigger") or "").lower()
    domain = (entry.get("domain") or "").lower()
    if "infra/process-management" in domain and (
        "uncommitted" in trig or "dirty" in trig or "timeout" in trig
    ):
        return True
    if "has uncommitted changes" in trig or "tests failed:" in trig:
        return True
    return False


def hygienize(corpus: list) -> tuple[list, list, dict]:
    kept, dropped = [], []
    seen = {}
    stats = {"input": len(corpus), "spam_collapsed": 0, "other_dupes": 0}
    for e in corpus:
        key = template_key(e)
        if key in seen:
            dropped.append(e)
            if is_health_bridge_spam(e):
                stats["spam_collapsed"] += 1
            else:
                stats["other_dupes"] += 1
            continue
        # Prefer a templated trigger without concrete counts for readability
        neat = dict(e)
        neat["trigger"] = re.sub(r"\d+", "N", neat.get("trigger") or "")[:120]
        neat["fix"] = re.sub(r"\d+", "N", neat.get("fix") or "")[:200]
        neat["test"] = neat.get("test") or f"Would policy now prevent: '{neat['trigger']}'?"
        neat["hygiene_key"] = key
        seen[key] = neat
        kept.append(neat)
    stats["kept"] = len(kept)
    stats["dropped"] = len(dropped)
    return kept, dropped, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        args.dry_run = True

    corpus = json.load(open(CORPUS)) if os.path.exists(CORPUS) else []
    kept, dropped, stats = hygienize(corpus)
    print(json.dumps(stats, indent=2))
    print(f"unique classes: {len(kept)} (was {len(corpus)})")
    if args.dry_run:
        print("(dry-run — pass --apply to rewrite corpus)")
        return 0

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = os.path.join(ARCHIVE_DIR, f"self-regression-corpus.{stamp}.json")
    shutil.copy2(CORPUS, archive)
    # also stash dropped for forensics
    with open(os.path.join(ARCHIVE_DIR, f"dropped.{stamp}.json"), "w") as f:
        json.dump(dropped, f)
    with open(CORPUS, "w") as f:
        json.dump(kept, f, indent=2)
    print(f"wrote {CORPUS} ({len(kept)} entries); archive {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
