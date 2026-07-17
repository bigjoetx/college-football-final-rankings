#!/usr/bin/env python3
"""
scrape_carter.py — Pull final UPI Coaches Poll rankings 1950-1976 from
cwclaib.github.io/football/polls, which is the best available source for that era.

    pip install requests
    python3 scrape_carter.py --dump 1970     # one year, prints the parse
    python3 scrape_carter.py                 # 1950-1976 -> coaches_1950_1976.json

WHY THIS SOURCE
---------------
CollegeFootballData has no coaches data before 2001. Wikipedia has weekly grids
from roughly 1968 on, but nothing usable for the 50s and 60s (the 1957 page has
only an AP grid). Carter Claiborne assembled 1950-1976 from the ESPN College
Football Encyclopedia and then corrected it against newspaper archives, linking
a clipping for every single weekly poll.

Cross-checked: his 1970 final matches Wikipedia's independent grid on all 20
teams, and both match Wikipedia's prose on first-place votes (Texas 25, Ohio
State 6, Nebraska 2, from 33 of 35 voting coaches).

He also caught a trap worth knowing about: the ESPN book was AP-derived, so it
listed only 10 UPI teams for 1961-67 (the years AP ranked 10) when UPI actually
ranked 20. He went to newspapers to fill those in. That means for 1961-67 this
source is more complete than the book it started from.

PROVENANCE, HONESTLY
--------------------
This is one person's hand-assembled research, not an API. He says so himself:
"I've done my best to make an educated guess and correct the errors as needed,
but it still may not be perfect." Every poll cites its newspaper clipping, which
is more than most sources offer. Output is tagged source="carter" so the chart
can distinguish it from API data if you want it to.

FORMAT
------
Plain text. Sections headed "Dec 8 1970* - <url>", ranks like "1. Texas (25)",
ties as "T-17. Toledo" followed by " -- . Georgia Tech" (same rank). The final
poll is the last dated section; some years end with "no post-season poll".
"""

import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dep. Run:  pip install requests")

BASE = "https://cwclaib.github.io/football/polls/{year}-coaches-poll.txt"
CACHE = Path("carter_cache")
THROTTLE = 0.4
UA = "cfb-rankings-hobby/1.0 (personal project)"

# Names this era used that differ from CFBD's canonical school names.
ALIAS = {
    "Southern California": "USC",
    "Southern Cal": "USC",
    "Louisiana State": "LSU",
    "Mississippi": "Ole Miss",
    "Texas Christian": "TCU",
    "Brigham Young": "BYU",
    "Southern Methodist": "SMU",
    "Miami (Fla.)": "Miami",
    "Miami (Florida)": "Miami",
    "Miami (Fla)": "Miami",
    "Miami (Ohio)": "Miami (OH)",
    "Penn": "Pennsylvania",
    "Pitt": "Pittsburgh",
    "North Carolina State": "NC State",
    "Texas A&M;": "Texas A&M",
    "Alabama-Birmingham": "UAB",
    "Nevada-Las Vegas": "UNLV",
    "Texas-El Paso": "UTEP",
    "Louisiana-Lafayette": "Louisiana",
    "Louisiana-Monroe": "UL Monroe",
    "Bowling Green State": "Bowling Green",
    "Washington State": "Washington State",
    "Air Force Academy": "Air Force",
}


def fetch(year, use_cache=True):
    cf = CACHE / f"{year}-coaches-poll.txt"
    if use_cache and cf.exists():
        return cf.read_text()
    r = requests.get(BASE.format(year=year), headers={"User-Agent": UA}, timeout=30)
    time.sleep(THROTTLE)
    if r.status_code != 200:
        return None
    CACHE.mkdir(exist_ok=True)
    cf.write_text(r.text)
    return r.text


# a section header looks like: "Dec 8 1970* - https://..."  or  "Sep 14 1970 - no poll"
SECTION_RE = re.compile(
    r"^\s*([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\*?)\s*-\s*(.*)$", re.M)


def split_sections(text):
    """Return [(header, body), ...] in document order."""
    marks = list(SECTION_RE.finditer(text))
    out = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), text[start:end]))
    return out


def parse_section(body):
    """Parse rank lines. Ties: 'T-17. X' then ' -- . Y' -> both rank 17."""
    out, last_rank = {}, None
    for line in body.splitlines():
        line = line.rstrip()
        if not line or line.startswith(("Others Receiving", "*")):
            continue
        m = re.match(r"\s*(?:T-)?(\d+)\.\s*(.+)", line)
        if m:
            last_rank = int(m.group(1))
            team = m.group(2)
        else:
            m2 = re.match(r"\s*-{2,}\s*\.\s*(.+)", line)
            if not m2 or last_rank is None:
                continue
            team = m2.group(1)          # tie continuation keeps last_rank
        team = re.sub(r"\s*\(\d+\)\s*$", "", team).strip()
        if not team or team.upper() == "N/A":
            continue
        if not 1 <= last_rank <= 25:
            continue
        out.setdefault(team, last_rank)
    return out


def final_poll(text):
    """Last dated section that actually contains rankings."""
    for header, body in reversed(split_sections(text)):
        rows = parse_section(body)
        if len(rows) >= 5:
            return header, rows
    return None, {}


def build_namemap(fbs_path="fbs_2026.json"):
    """canonical CFBD names + their alternates, for normalising Carter's names."""
    if not Path(fbs_path).exists():
        return None
    fbs = json.load(open(fbs_path))
    lookup = {}
    for t in fbs:
        lookup[t["school"].lower()] = t["school"]
        for alt in t.get("alternateNames") or []:
            lookup.setdefault(alt.lower(), t["school"])
    return lookup


def normalise(team, lookup):
    """-> (canonical_name_or_None, how)"""
    t = ALIAS.get(team, team)
    if lookup is None:
        return t, "no-map"
    if t.lower() in lookup:
        return lookup[t.lower()], "exact"
    # Carter has occasional typos ("Arkanasa", "Arkansasas")
    close = difflib.get_close_matches(t.lower(), lookup.keys(), n=1, cutoff=0.85)
    if close:
        return lookup[close[0]], f"fuzzy<-{team}"
    return None, "unmatched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1950)
    ap.add_argument("--end", type=int, default=1976)
    ap.add_argument("--dump", type=int)
    ap.add_argument("--out", default="coaches_1950_1976.json")
    ap.add_argument("--fbs", default="fbs_2026.json")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    use_cache = not args.no_cache
    lookup = build_namemap(args.fbs)
    if lookup is None:
        print(f"note: {args.fbs} not found — names will not be normalised\n")

    if args.dump:
        text = fetch(args.dump, use_cache)
        if not text:
            sys.exit(f"no file for {args.dump}")
        secs = split_sections(text)
        print(f"{len(secs)} dated sections; last few headers:")
        for h, _ in secs[-3:]:
            print(f"   {h}")
        header, rows = final_poll(text)
        print(f"\nFINAL POLL: {header}  ({len(rows)} teams)\n")
        for team, rank in sorted(rows.items(), key=lambda x: x[1]):
            canon, how = normalise(team, lookup)
            flag = "" if how in ("exact", "no-map") else f"   [{how}]"
            print(f"  {rank:>2}  {team:<24} -> {canon or '(not FBS 2026)'}{flag}")
        return

    result, unmatched, misses = {}, {}, []
    for year in range(args.start, args.end + 1):
        text = fetch(year, use_cache)
        if not text:
            print(f"  {year}  no file")
            misses.append(year)
            continue
        header, rows = final_poll(text)
        if not rows:
            print(f"  {year}  no final poll parsed")
            misses.append(year)
            continue
        clean = {}
        for team, rank in rows.items():
            canon, how = normalise(team, lookup)
            if canon:
                clean[canon] = rank
            else:
                unmatched.setdefault(team, []).append(year)
        top = min(rows, key=rows.get)
        print(f"  {year}  {len(rows):>2} teams · #1 {top:<20} ({header}) "
              f"-> {len(clean)} FBS-2026")
        result[str(year)] = clean

    Path(args.out).write_text(json.dumps(
        {"meta": {"source": "cwclaib.github.io/football/polls",
                  "note": "UPI Coaches Poll finals, hand-assembled from ESPN CFB "
                          "Encyclopedia + newspaper archives; ties share a rank",
                  "range": [args.start, args.end]},
         "seasons": result}, indent=1))
    print(f"\nWrote {args.out} — {len(result)} seasons, "
          f"{sum(len(v) for v in result.values())} team-seasons")
    if unmatched:
        print(f"\n  names not matched to an FBS 2026 school ({len(unmatched)}):")
        for name, yrs in sorted(unmatched.items())[:25]:
            print(f"    {name:<26} {yrs[0]}-{yrs[-1]} ({len(yrs)}x)")
        print("  most of these are Ivies/defunct programs and are correctly dropped;")
        print("  scan for anything that looks like a typo of a real team.")
    if misses:
        print(f"\n  no data: {misses}")


if __name__ == "__main__":
    main()
