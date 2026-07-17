# College Football Final Rankings, 1936–2025

A single self-contained HTML page showing every FBS team's final season rankings —
AP, Coaches, BCS, and CFP — with no build step, no server, and no network calls.
Pick a team and the chart, era bands, and colors follow.

**Live:** https://USERNAME.github.io/REPO/

## What's in it

| Series | Years | Source |
|---|---|---|
| AP Poll | 1936–2025 | CollegeFootballData API |
| Coaches Poll (UP → UPI → USA Today) | 1950–1976 | Carter Claiborne's newspaper archive |
| Coaches Poll | 1977–2000 | Wikipedia season ranking pages |
| Coaches Poll | 2001–2025 | CollegeFootballData API |
| BCS Standings | 1998–2013 | Wikipedia season ranking pages |
| CFP Committee | 2014–2025 | CollegeFootballData API |

2,052 ranked team-seasons across the 138 teams that were FBS members in 2026.

## Credit where it's owed

The 1950–1976 Coaches Poll data comes from
**[Carter Claiborne's poll archive](https://cwclaib.github.io/football/polls/)**.
He assembled it from the *ESPN College Football Encyclopedia* and then corrected it
against newspaper archives, citing a clipping for every weekly poll. He notes the
ESPN book was AP-derived and therefore listed only 10 UPI teams for 1961–67 — the
years the AP ranked 10 — when UPI actually ranked 20, so he went to the papers to
fill them in. That data is not available anywhere else in a usable form.

Other sources: [CollegeFootballData.com](https://collegefootballdata.com) (free API,
key required) and Wikipedia's per-season rankings pages.

## Things this dataset knows that are easy to get wrong

**The AP and Coaches polls named different champions eleven times** — 1954, 1957,
1965, 1970, 1973, 1974, 1978, 1990, 1991, 1997, 2003. In those years two teams
carry a star. That's the history, not a bug.

**Before 1974 the final Coaches Poll was taken *before* the bowls** while the AP's
came after. Texas 1970 is Coaches #1 and AP #3, and both are correct. Final AP polls
before 1968 were also pre-bowl, so a team's listed record can include a bowl its
ranking never saw.

**BCS and CFP standings are seedings, not results.** They were published before the
title game to decide who played in it. The 2003 BCS ranked Oklahoma #1; LSU won the
game and USC won the AP without playing in it. The 2024 CFP ranked Oregon #1; Ohio
State won it from #6. Champions here come from the polls — the Coaches Poll was
contractually bound to rank the BCS/CFP winner first — never from the seeding.

**Poll depth changed.** The AP ranked 20 teams through 1961, **10 from 1962–67**, 20
through 1988, then 25. The Coaches ranked 20 through 1989, then 25. The BCS ranked 15
through 2002, then 25. A #10 in 1965 was the last team ranked; a #10 in 2025 is a good
season. The chart shades the floor so they don't look identical.

**1982–1990 had two competing coaches polls**, UPI and USA Today/CNN, and they
disagreed — in 1990 UPI crowned Georgia Tech while USA Today/CNN went with Colorado.
This follows Wikipedia and uses UPI.

## Known gaps

- Nine early rows have no record on file (CFBD's `/records` doesn't have them).
- Conference era bands are derived from ranked seasons, so a boundary can land a year
  off when a team wasn't ranked during its move.
- Season notes are hand-written and currently only cover Texas A&M.

## Rebuilding the data

Everything but `index.html` is the pipeline. You need a free CFBD API key.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install requests beautifulsoup4
export CFBD_API_KEY="your_key_here"

python3 cfbd_pull.py                      # AP 1936-2025, coaches/BCS/CFP 2001+
python3 extract_conferences.py            # per-season conference + record, from cache
python3 scrape_carter.py                  # coaches 1950-1976
python3 scrape_coaches.py                 # coaches 1977-2000  (Wikipedia)
python3 scrape_coaches.py --series bcs    # BCS 1998-2013      (Wikipedia)
python3 merge_coaches.py                  # -> rankings_merged.json
python3 build_dataset.py                  # -> cfb_data.json
python3 inject.py                         # -> index.html
```

Every scraper caches to disk, so re-runs are free. `inspect_polls.py` dumps the
distinct poll names in the CFBD cache — worth running if anything looks off, since
that's what caught the FBS coaches poll being silently overwritten by the Division III
one.

Scrapers throttle and identify themselves. Please keep it that way.
# college-football-final-rankings
