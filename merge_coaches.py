#!/usr/bin/env python3
"""
merge_coaches.py — Fold the pre-2001 coaches poll data into rankings.json.

    python3 merge_coaches.py

Inputs : rankings.json            (CFBD: AP 1936-2025, coaches/BCS/CFP 2001+)
         coaches_1950_1976.json   (Carter, UPI finals)
         coaches_pre2001.json     (Wikipedia, UPI / USA Today finals)
         fbs_2026.json            (canonical names, colours)
         conferences.json         (real per-season conference + record, from cache)
         bcs_wiki.json            (BCS standings 1998-2013, from Wikipedia)
         ap_wiki.json             (AP finals from Wikipedia — used to repair 2001-02)
         co_2001_2025.json        (Coaches finals from Wikipedia — same)
Output : rankings_merged.json

Coaches poll provenance after merge:
    1936-1949  none — the poll did not exist before 1950
    1950-1976  carter     (newspaper-sourced; cross-validated vs Wikipedia on 1970)
    1977-2000  wikipedia  (AP column independently verified against CFBD)
    2001-2025  cfbd       (API)

Source is uniform per season, so it's recorded once in meta rather than on every
row. The chart can colour or caveat by era from that.

NAME MAPPING IS EXPLICIT, NOT FUZZY
-----------------------------------
Only three names across 89 needed mapping, and one of them is why fuzzy matching
is banned here: Wikipedia's 1997 page says "Mississippi", and the closest string
match is "Mississippi State" — a different school. "Mississippi" is Ole Miss.
A fuzzy matcher would have silently moved a #22 finish to the wrong program.
"""

import json
import sys
from pathlib import Path

ALIAS = {
    "Mississippi": "Ole Miss",        # NOT Mississippi State. See docstring.
    "Hawaii": "Hawai'i",
    "San Jose State": "San José State",
    "North Texas State": "North Texas",   # renamed from North Texas State in 1988
    "Miami (FL)": "Miami",                # CFBD calls the Florida school "Miami"
                                          # and the Ohio one "Miami (OH)"
    "Connecticut": "UConn",               # BCS #25 in 2007 — a real ranked season
}

# CFBD's BCS column is replaced outright, not patched. It holds only 2001 and
# 2007-2013, and at least two of those are the wrong week: it reported Missouri
# as 2007 BCS #1 (really #6) and Alabama as 2008 #1 (really #4) — mid-November
# standings served as finals. Wikipedia covers all 16 seasons in one format, and
# every #1 matches the known top seed.
REPLACE_BCS = True

# CFBD's 2001 and 2002 AP and Coaches polls are PRE-BOWL, and not because the
# postseason entry is missing — it exists, is labelled postseason week 1, and
# contains the December poll. 2002 has Miami #1 and Ohio State #2; Ohio State
# went 14-0 and beat Miami in the Fiesta Bowl. Diffing every rank against
# Wikipedia (which agrees with CFBD on 78 of 84 AP seasons) shows 2001 and 2002
# disagreeing on 21 of 23 and 22 of 22 teams respectively. Nothing structural
# catches this: the ranks are contiguous, the names are real, the depth is 25.
# It is simply the wrong week. Both seasons are rebuilt from Wikipedia.
REBUILD_FROM_WIKI = {2001, 2002}

SOURCE_BY_YEAR = [
    (1950, 1976, "carter"),
    (1977, 2000, "wikipedia"),
    (2001, 2025, "cfbd"),
]


def source_for(year):
    for a, b, s in SOURCE_BY_YEAR:
        if a <= year <= b:
            return s
    return None


def main():
    for f in ("rankings.json", "coaches_1950_1976.json",
              "coaches_pre2001.json", "fbs_2026.json", "conferences.json",
              "bcs_wiki.json", "ap_wiki.json", "co_2001_2025.json"):
        if not Path(f).exists():
            sys.exit(f"missing {f}")

    rk = json.load(open("rankings.json"))
    carter = json.load(open("coaches_1950_1976.json"))["seasons"]
    wiki = json.load(open("coaches_pre2001.json"))
    fbs = json.load(open("fbs_2026.json"))
    confs = json.load(open("conferences.json"))
    bcs_wiki = json.load(open("bcs_wiki.json"))
    ap_wiki = json.load(open("ap_wiki.json"))
    co_wiki = json.load(open("co_2001_2025.json"))

    S = rk["meta"]["schema"]
    Y, AP, CO, BCS, CFP, REC, CONF = (S.index(k) for k in
        ("year", "ap", "coaches", "bcs", "cfp", "record", "conference"))

    canon = {t["school"] for t in fbs}

    # year -> {canonical team: rank}
    incoming, dropped = {}, {}
    for blob in (carter, wiki):
        for ys, rows in blob.items():
            y = int(ys)
            for team, rank in rows.items():
                name = ALIAS.get(team, team)
                if name not in canon:
                    dropped.setdefault(name, set()).add(y)
                    continue
                incoming.setdefault(y, {})[name] = rank

    teams = rk["teams"]

    # CFBD only created a key for teams it saw in a poll it knew about, and it
    # had never heard of the pre-2001 coaches poll or the full BCS. Iterating
    # teams.items() alone silently drops any team whose ONLY ranked seasons come
    # from the new sources — New Mexico (coaches #16 in 1964) and UConn (BCS #25
    # in 2007) both vanished that way, while the picker called them never-ranked.
    # Walk the union instead, creating keys as needed.
    incoming_names = set()

    filled = added = conflict = 0
    conflicts, no_meta = [], []

    # BCS: wipe CFBD's column, then rebuild it from Wikipedia.
    bcs_in, bcs_dropped = {}, set()
    for ys, rows in bcs_wiki.items():
        y = int(ys)
        for team, rank in rows.items():
            name = ALIAS.get(team, team)
            if name not in canon:
                bcs_dropped.add(name)
                continue
            bcs_in.setdefault(y, {})[name] = rank

    # 2001-02: wipe CFBD's pre-bowl AP and Coaches, rebuild from Wikipedia
    rebuilt = {}
    for series_i, blob in ((AP, ap_wiki), (CO, co_wiki)):
        for ys, rows in blob.items():
            y = int(ys)
            if y not in REBUILD_FROM_WIKI:
                continue
            for team, rank in rows.items():
                name = ALIAS.get(team, team)
                if name in canon:
                    rebuilt.setdefault(y, {}).setdefault(series_i, {})[name] = rank

    prebowl_wiped = 0
    for rows in teams.values():
        for r in rows:
            if r[Y] in REBUILD_FROM_WIKI:
                for i in (AP, CO):
                    if r[i] is not None:
                        r[i] = None
                        prebowl_wiped += 1

    incoming_names |= {t for y in rebuilt for i in rebuilt[y] for t in rebuilt[y][i]}
    incoming_names |= {t for m in incoming.values() for t in m}
    incoming_names |= {t for m in bcs_in.values() for t in m}
    created = 0
    for name in sorted(incoming_names):
        if name not in teams:
            teams[name] = []
            created += 1

    wiped = 0
    if REPLACE_BCS:
        for rows in teams.values():
            for r in rows:
                if r[BCS] is not None:
                    r[BCS] = None
                    wiped += 1

    for team in list(teams):
        rows = teams[team]
        by_year = {r[Y]: r for r in rows}
        for y, mapping in incoming.items():
            if team not in mapping:
                continue
            rank = mapping[team]
            row = by_year.get(y)
            if row is None:
                # coaches-ranked but unranked by AP: brand new row.
                # Real conference/record from the CFBD cache, never inferred —
                # a carried-forward guess put North Texas in the American
                # Athletic in 1977, a conference founded in 2013.
                meta = confs.get(str(y), {}).get(team, {})
                new = [None] * len(S)
                new[Y], new[CO] = y, rank
                new[REC] = meta.get("record", "")
                new[CONF] = meta.get("conference", "")
                by_year[y] = new
                added += 1
                if not meta:
                    no_meta.append((team, y))
            elif row[CO] is None:
                row[CO] = rank
                filled += 1
            elif row[CO] != rank:
                conflict += 1
                conflicts.append((team, y, row[CO], rank))

        # 2001-02 AP/Coaches rebuilt from Wikipedia
        for y, series_map in rebuilt.items():
            for series_i, mapping in series_map.items():
                if team not in mapping:
                    continue
                row = by_year.get(y)
                if row is None:
                    meta = confs.get(str(y), {}).get(team, {})
                    row = [None] * len(S)
                    row[Y] = y
                    row[REC] = meta.get("record", "")
                    row[CONF] = meta.get("conference", "")
                    by_year[y] = row
                    added += 1
                row[series_i] = mapping[team]

        # BCS from Wikipedia
        for y, mapping in bcs_in.items():
            if team not in mapping:
                continue
            row = by_year.get(y)
            if row is None:
                meta = confs.get(str(y), {}).get(team, {})
                new = [None] * len(S)
                new[Y], new[BCS] = y, mapping[team]
                new[REC] = meta.get("record", "")
                new[CONF] = meta.get("conference", "")
                by_year[y] = new
                added += 1
            else:
                row[BCS] = mapping[team]

        teams[team] = [by_year[k] for k in sorted(by_year)]

    rk["meta"]["repairedSeasons"] = {
        "2001": "AP + Coaches rebuilt from Wikipedia; CFBD served the pre-bowl poll",
        "2002": "AP + Coaches rebuilt from Wikipedia; CFBD served the pre-bowl poll "
                "(had Miami #1 over 14-0 Ohio State, who beat them in the Fiesta Bowl)",
    }
    rk["meta"]["knownDiscrepancies"] = [
        "AP 1945: sources disagree on #2/#3 (Alabama vs Navy) — unresolved",
        "AP 1950 Tulsa, AP 1951 Clemson, AP 2005 Oregon, Coaches 2010 LSU: "
        "one-rank disagreements between CFBD and Wikipedia, likely tie handling "
        "— unresolved, CFBD retained",
        "AP 1936-1941: no Wikipedia grid exists, so never independently verified",
    ]
    rk["meta"]["bcsProvenance"] = {
        "1998-2013": "wikipedia (final BCS standings; replaces CFBD, which held "
                     "only 2007-2013 plus a partial 2001 and served pre-final weeks)",
    }
    rk["meta"]["bcsNote"] = (
        "The final BCS standings were published in early December to decide who "
        "played in the title game. They are a seeding, not a result: the 2011 BCS "
        "ranked LSU first and Alabama won the game. The BCS ranked 15 teams from "
        "1998-2002 and 25 from 2003."
    )
    rk["meta"]["coachesProvenance"] = {
        "1936-1949": "none - Coaches Poll did not exist before 1950",
        "1950-1976": "carter (cwclaib.github.io, newspaper-sourced)",
        "1977-2000": "wikipedia (UPI / USA Today finals)",
        "2001-2025": "cfbd (API)",
    }
    rk["meta"]["coachesNote"] = (
        "Before 1974 the final Coaches Poll was taken BEFORE the bowl games, so a "
        "team can hold Coaches #1 and a lower AP finish in the same season "
        "(Texas 1970). For 1982-1990 the 'Coaches Poll' here is UPI; a separate "
        "USA Today/CNN poll ran alongside it and disagreed - notably in 1990, "
        "where UPI chose Georgia Tech and USA Today/CNN chose Colorado."
    )
    json.dump(rk, open("rankings_merged.json", "w"), separators=(",", ":"))

    kb = Path("rankings_merged.json").stat().st_size / 1024
    print(f"Wrote rankings_merged.json ({kb:.0f} KB)")
    print(f"  coaches ranks filled into existing rows : {filled}")
    print(f"  new rows (coaches-ranked, AP-unranked)  : {added}")
    print(f"  teams that had no key at all            : {created}")
    print(f"  conflicts with existing data            : {conflict}")
    print(f"  CFBD bcs values discarded               : {wiped}")
    print(f"  CFBD pre-bowl 2001-02 ap/coaches wiped  : {prebowl_wiped}")
    print(f"  2001-02 ap/coaches rebuilt from wiki    : "
          f"{sum(len(m) for y in rebuilt for m in rebuilt[y].values())}")
    print(f"  bcs values written from Wikipedia       : "
          f"{sum(len(v) for v in bcs_in.values())}")
    if bcs_dropped:
        print(f"  bcs names dropped as non-FBS-2026       : {sorted(bcs_dropped)}")
    for c in conflicts[:10]:
        print(f"      {c[0]} {c[1]}: had {c[2]}, incoming {c[3]}")
    if no_meta:
        print(f"\n  new rows with no cached record/conference ({len(no_meta)}): "
              f"{no_meta[:8]}")
    if dropped:
        print(f"\n  names dropped as non-FBS-2026 ({len(dropped)}):")
        print("    " + ", ".join(sorted(dropped)[:20]))


if __name__ == "__main__":
    main()
