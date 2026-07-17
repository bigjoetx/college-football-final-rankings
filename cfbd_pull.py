#!/usr/bin/env python3
"""
cfbd_pull.py — Pull final AP / Coaches / CFP rankings from CollegeFootballData.com
and emit a compact JSON blob suitable for embedding in a flat HTML visualizer.

SETUP
-----
    pip install requests
    export CFBD_API_KEY="your_key_here"        # macOS/Linux
    set CFBD_API_KEY=your_key_here             # Windows cmd
    $env:CFBD_API_KEY="your_key_here"          # Windows PowerShell

USAGE
-----
    python cfbd_pull.py                                  # 1936-2025, writes rankings.json
    python cfbd_pull.py --start 1990 --end 2025
    python cfbd_pull.py --teams "Texas A&M" "Alabama"    # filter output to a few teams
    python cfbd_pull.py --pretty                         # readable JSON for eyeballing
    python cfbd_pull.py --no-cache                       # force re-fetch

NOTES
-----
Raw API responses are cached under ./cfbd_cache/. The transform step reads only
from cache, so re-running after the first pull costs zero API calls. Delete the
cache dir (or pass --no-cache) to refresh.

Caveat worth knowing: for most seasons before 1968 the AP "final" poll was taken
BEFORE bowl games, so a team's final ranking does not reflect its bowl result.
This script records what the polls said; it does not editorialize.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

API_BASE = "https://api.collegefootballdata.com"
CACHE_DIR = Path("cfbd_cache")
THROTTLE_SEC = 0.4          # be polite; free tier
MAX_RETRIES = 4

# Output schema for the per-season arrays.
SCHEMA = ["year", "ap", "coaches", "bcs", "cfp", "record", "conference"]

# Poll names we saw but didn't recognize. Reported at the end so the
# classifier can be tuned against reality instead of guesswork.
UNKNOWN_POLLS = set()


# ──────────────────────────────────────────────────────────────────────
# HTTP
# ──────────────────────────────────────────────────────────────────────

def get_key() -> str:
    key = os.environ.get("CFBD_API_KEY", "").strip()
    if not key:
        sys.exit(
            "CFBD_API_KEY is not set.\n"
            "Get a free key at https://collegefootballdata.com/key then:\n"
            '  export CFBD_API_KEY="your_key_here"'
        )
    return key


def api_get(session: requests.Session, path: str, params: dict, use_cache: bool):
    """GET an endpoint with disk caching, retries, and backoff."""
    slug = path.strip("/").replace("/", "_")
    tag = "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    cache_file = CACHE_DIR / f"{slug}__{tag}.json"

    if use_cache and cache_file.exists():
        with cache_file.open() as fh:
            return json.load(fh)

    url = f"{API_BASE}{path}"
    delay = 1.0

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"    network error ({exc}); retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code == 200:
            data = resp.json()
            CACHE_DIR.mkdir(exist_ok=True)
            with cache_file.open("w") as fh:
                json.dump(data, fh)
            time.sleep(THROTTLE_SEC)
            return data

        if resp.status_code in (401, 403):
            sys.exit(
                f"\nAuth failed ({resp.status_code}). Your CFBD_API_KEY looks invalid "
                f"or lacks access to {path}.\nResponse: {resp.text[:200]}"
            )

        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == MAX_RETRIES:
                resp.raise_for_status()
            print(f"    HTTP {resp.status_code}; backing off {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
            continue

        resp.raise_for_status()

    return []


# ──────────────────────────────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────────────────────────────

# Exact poll names we chart. Verified against the cache — CFBD normalizes
# these, so "AP Top 25" is the name even for 1936 when it was a top 20.
# Match must be EXACT: "FCS Coaches Poll" contains "Coaches Poll" as a
# substring, so loose matching silently merges divisions.
FBS_POLLS = {
    "ap top 25": "ap",
    "coaches poll": "coaches",
    "bcs standings": "bcs",
    "playoff committee rankings": "cfp",
}

# Known non-FBS polls. Deliberately excluded, and listed here so they don't
# clutter the "unrecognized" report at the end of a run.
IGNORED_POLLS = {
    "afca division ii coaches poll",
    "afca division iii coaches poll",
    "fcs coaches poll",
}


def classify_poll(name):
    """Map a CFBD poll name onto one of our four FBS series, or None."""
    n = (name or "").strip().lower()
    if n in FBS_POLLS:
        return FBS_POLLS[n]
    if n and n not in IGNORED_POLLS:
        UNKNOWN_POLLS.add(name)
    return None


def fetch_rankings(session, year, use_cache):
    """
    Return {poll_key: {school: rank}} for the FINAL poll of the season.

    We pull both regular and postseason because the "last" poll lives in
    different places depending on the era. Postseason wins if present;
    otherwise the highest regular-season week.
    """
    entries = []
    for stype in ("regular", "postseason"):
        data = api_get(session, "/rankings",
                       {"year": year, "seasonType": stype}, use_cache)
        for entry in data or []:
            entries.append((stype, entry))

    # For each poll series, keep the latest entry.
    best = {}  # poll_key -> (priority, week, ranks)
    for stype, entry in entries:
        week = entry.get("week") or 0
        priority = 1 if stype == "postseason" else 0
        for poll in entry.get("polls", []) or []:
            key = classify_poll(poll.get("poll"))
            if not key:
                continue
            cand = (priority, week)
            if key not in best or cand > best[key][0]:
                best[key] = (cand, poll.get("ranks", []) or [])

    out = {}
    for key, (_, ranks) in best.items():
        out[key] = {
            r["school"]: r["rank"]
            for r in ranks
            if r.get("school") and r.get("rank")
        }
    return out


def fetch_records(session, year, use_cache):
    """Return {school: {"record": "9-1", "conference": "SEC"}}."""
    data = api_get(session, "/records", {"year": year}, use_cache)
    out = {}
    for row in data or []:
        school = row.get("team")
        if not school:
            continue
        total = row.get("total") or {}
        wins = total.get("wins", 0)
        losses = total.get("losses", 0)
        ties = total.get("ties", 0)
        record = f"{wins}-{losses}" + (f"-{ties}" if ties else "")
        out[school] = {"record": record, "conference": row.get("conference") or ""}
    return out


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=int, default=1936, help="first season (AP starts 1936)")
    ap.add_argument("--end", type=int, default=2025, help="last season")
    ap.add_argument("--out", default="rankings.json", help="output path")
    ap.add_argument("--teams", nargs="*", default=None,
                    help="only include these schools (exact CFBD names)")
    ap.add_argument("--pretty", action="store_true", help="indented JSON")
    ap.add_argument("--no-cache", action="store_true", help="ignore cached responses")
    args = ap.parse_args()

    use_cache = not args.no_cache
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {get_key()}",   # CFBD requires the Bearer prefix
        "Accept": "application/json",
    })

    # school -> {year -> {ap, coaches, cfp, record, conference}}
    table = defaultdict(dict)

    years = range(args.start, args.end + 1)
    for year in years:
        print(f"  {year} ...", end="", flush=True)
        try:
            polls = fetch_rankings(session, year, use_cache)
            records = fetch_records(session, year, use_cache)
        except Exception as exc:
            print(f" FAILED ({exc})")
            continue

        ranked = set()
        for key, mapping in polls.items():
            for school, rank in mapping.items():
                table[school].setdefault(year, {})[key] = rank
                ranked.add(school)

        for school in ranked:
            meta = records.get(school, {})
            slot = table[school][year]
            slot["record"] = meta.get("record", "")
            slot["conference"] = meta.get("conference", "")

        found = ", ".join(f"{k}:{len(v)}" for k, v in sorted(polls.items())) or "no polls"
        print(f" {found}")

    # Flatten to compact arrays.
    teams_out = {}
    for school, by_year in table.items():
        if args.teams and school not in args.teams:
            continue
        rows = []
        for year in sorted(by_year):
            d = by_year[year]
            rows.append([
                year,
                d.get("ap"),
                d.get("coaches"),
                d.get("bcs"),
                d.get("cfp"),
                d.get("record", ""),
                d.get("conference", ""),
            ])
        if rows:
            teams_out[school] = rows

    payload = {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "CollegeFootballData.com",
            "range": [args.start, args.end],
            "schema": SCHEMA,
            "caveat": ("Final AP polls prior to 1968 were generally taken before "
                       "bowl games and do not reflect bowl results."),
            "coverage": {
                "ap": "1936-2025 (complete)",
                "coaches": "2001-2025 only — CFBD has no coaches poll before 2001",
                "bcs": "2001-2013 only — BCS ran 1998-2013; CFBD is missing 1998-2000",
                "cfp": "2014-2025 (complete)",
            },
        },
        "teams": teams_out,
    }

    out_path = Path(args.out)
    with out_path.open("w") as fh:
        if args.pretty:
            json.dump(payload, fh, indent=2)
        else:
            json.dump(payload, fh, separators=(",", ":"))

    total_rows = sum(len(v) for v in teams_out.values())
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path}")
    print(f"  {len(teams_out)} teams · {total_rows} ranked team-seasons · {size_kb:.0f} KB")

    if UNKNOWN_POLLS:
        print("\n  Poll names seen but NOT charted "
              "(check whether any of these should be):")
        for name in sorted(UNKNOWN_POLLS):
            print(f"    · {name}")
    print(f"  cache: {CACHE_DIR}/ ({len(list(CACHE_DIR.glob('*.json')))} files)"
          if CACHE_DIR.exists() else "")


if __name__ == "__main__":
    main()
