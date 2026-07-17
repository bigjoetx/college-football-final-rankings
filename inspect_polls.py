#!/usr/bin/env python3
"""
inspect_polls.py — Read the cached CFBD responses and report every distinct
poll name, with the years it appears in and how many teams it ranks.

No API calls. No dependencies. Run it in the same folder as cfbd_cache/.

    python3 inspect_polls.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

CACHE_DIR = Path("cfbd_cache")

if not CACHE_DIR.exists():
    sys.exit("No cfbd_cache/ directory here. Run this from your project folder.")

# poll name -> {years: set, max_teams: int, weeks: set}
polls = defaultdict(lambda: {"years": set(), "max_teams": 0, "weeks": set()})

for path in sorted(CACHE_DIR.glob("rankings__*.json")):
    try:
        data = json.load(path.open())
    except json.JSONDecodeError:
        print(f"  skipping unreadable {path.name}", file=sys.stderr)
        continue

    for entry in data or []:
        year = entry.get("season")
        week = entry.get("week")
        for poll in entry.get("polls", []) or []:
            name = poll.get("poll") or "(unnamed)"
            ranks = poll.get("ranks", []) or []
            rec = polls[name]
            rec["years"].add(year)
            rec["weeks"].add(week)
            rec["max_teams"] = max(rec["max_teams"], len(ranks))

if not polls:
    sys.exit("Found no rankings__*.json files in cfbd_cache/.")

print(f"\n{len(polls)} distinct poll names across the cache:\n")
print(f"{'poll name':44} {'yrs':>4} {'range':<12} {'max':>4}  weeks")
print("-" * 88)

for name in sorted(polls, key=lambda n: (-len(polls[n]["years"]), n)):
    rec = polls[name]
    yrs = sorted(y for y in rec["years"] if y is not None)
    span = f"{yrs[0]}-{yrs[-1]}" if yrs else "?"
    weeks = sorted(w for w in rec["weeks"] if w is not None)
    wk = f"{min(weeks)}-{max(weeks)}" if weeks else "?"
    print(f"{name:44} {len(yrs):>4} {span:<12} {rec['max_teams']:>4}  {wk}")

print("\nPolls containing 'coaches' (the collision source):")
for name in sorted(polls):
    if "coaches" in name.lower():
        yrs = sorted(y for y in polls[name]["years"] if y is not None)
        print(f"  · {name}   [{yrs[0] if yrs else '?'}-{yrs[-1] if yrs else '?'}]")
