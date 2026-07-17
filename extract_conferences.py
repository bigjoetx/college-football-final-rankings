#!/usr/bin/env python3
"""
extract_conferences.py — Pull real per-season conference (and record) for every
team out of the CFBD cache you already have. No API calls, no key needed.

    python3 extract_conferences.py        # -> conferences.json

WHY
---
merge_coaches.py adds rows for teams that were coaches-ranked but AP-unranked.
Those rows have no conference, because the original pull only recorded metadata
for teams it saw in a poll — and it had never heard of the pre-2001 coaches poll.

The stopgap was to carry the conference from a team's nearest known season. That
is wrong in a way that invents history: North Texas was coaches-ranked #16 in
1977, their nearest known season is modern, so the row came out "American
Athletic" — a conference founded in 2013. Left in, it draws an AAC era band back
through the Carter administration.

Your cfbd_cache/records__year-*.json files have the actual answer for every team
in every season. This just reads them.
"""

import json
import re
import sys
from pathlib import Path

CACHE = Path("cfbd_cache")

if not CACHE.exists():
    sys.exit("No cfbd_cache/ here. Run this from your project folder.")

files = sorted(CACHE.glob("records__year-*.json"))
if not files:
    sys.exit("No records__year-*.json in cfbd_cache/. Re-run cfbd_pull.py first.")

out = {}
for path in files:
    m = re.search(r"year-(\d{4})", path.name)
    if not m:
        continue
    year = m.group(1)
    try:
        rows = json.load(path.open())
    except json.JSONDecodeError:
        print(f"  skipping unreadable {path.name}", file=sys.stderr)
        continue

    season = {}
    for row in rows or []:
        team = row.get("team")
        if not team:
            continue
        total = row.get("total") or {}
        w, l, t = total.get("wins", 0), total.get("losses", 0), total.get("ties", 0)
        season[team] = {
            "conference": row.get("conference") or "",
            "record": f"{w}-{l}" + (f"-{t}" if t else ""),
        }
    if season:
        out[year] = season

Path("conferences.json").write_text(json.dumps(out, separators=(",", ":")))

yrs = sorted(out)
n = sum(len(v) for v in out.values())
kb = Path("conferences.json").stat().st_size / 1024
print(f"Wrote conferences.json ({kb:.0f} KB)")
print(f"  {len(yrs)} seasons {yrs[0]}-{yrs[-1]} · {n} team-seasons")

probe = out.get("1977", {}).get("North Texas")
if probe:
    print(f"\n  sanity check — North Texas 1977: {probe}")
    print("  (the carry-forward guess was 'American Athletic', founded 2013)")
