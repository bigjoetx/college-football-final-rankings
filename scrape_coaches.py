#!/usr/bin/env python3
"""
scrape_coaches.py — Pull final Coaches Poll (UPI, later USA Today) rankings for
1950-2000 from Wikipedia, since CollegeFootballData has no coaches data before 2001.

    pip install requests beautifulsoup4
    python3 scrape_coaches.py --dump 1970      # inspect one year, change nothing
    python3 scrape_coaches.py                  # full run -> coaches_pre2001.json

HOW THE PAGES ARE ACTUALLY BUILT
--------------------------------
Not as a final-poll table. Each poll is a *weekly progression grid*: rows are
ranks 1-20, columns are weeks, cells are "Texas (10-0) (25)" = team, record,
first-place votes. The final poll is simply the last column. The AP and Coaches
grids are distinguished by the nearest preceding heading.

SELF-VALIDATION
---------------
Both grids get scraped. Your AP data from CFBD is already verified, so the
scraped AP column is a free check on the parse: if AP matches CFBD for a season,
the coaches column from that same page is trustworthy. If it doesn't, the season
is flagged rather than silently trusted. Point --rankings at your rankings.json.

TWO THINGS THIS DOES NOT DECIDE FOR YOU
---------------------------------------
1. 1982-1990 ran two competing coaches polls, UPI and USA Today/CNN, and they
   disagreed - in 1990 UPI crowned Georgia Tech while USA Today/CNN went with
   Colorado. This follows Wikipedia and takes whichever grid sits under a
   "Coaches Poll" heading, which for those years is UPI.
2. Before 1974 the final coaches poll was taken BEFORE the bowls. Texas 1970 is
   Coaches #1 and AP #3 and both are correct. Recorded as-is; the chart explains it.
"""

import argparse, json, re, sys, time
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing deps. Run:  pip install requests beautifulsoup4")

API = "https://en.wikipedia.org/w/api.php"
UA = ("cfb-rankings-hobby-project/1.0 "
      "(personal research; contact: put-your-email-or-github-here)")
CACHE = Path("wiki_cache")
THROTTLE = 1.0          # sleep after EVERY request, hit or miss
MISS_FILE = CACHE / "_missing_titles.json"


def title_candidates(year):
    """
    Wikipedia renamed the division over time, and the year tells us which name
    applies. Ordering by era means the first guess is normally the right one,
    which matters: every wrong guess is a wasted request against a rate limit.
    """
    if year <= 1972:
        primary = f"{year} NCAA University Division football rankings"
    elif year <= 1977:
        primary = f"{year} NCAA Division I football rankings"
    elif year <= 2005:
        primary = f"{year} NCAA Division I-A football rankings"
    else:
        primary = f"{year} NCAA Division I FBS football rankings"

    rest = [
        f"{year} college football rankings",
        f"{year} NCAA Division I-A football rankings",
        f"{year} NCAA University Division football rankings",
        f"{year} NCAA Division I football rankings",
        f"{year} NCAA Division I FBS football rankings",
    ]
    seen, out = {primary}, [primary]
    for t in rest:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def _load_misses():
    if MISS_FILE.exists():
        try:
            return set(json.loads(MISS_FILE.read_text()))
        except Exception:
            return set()
    return set()


def _save_misses(misses):
    CACHE.mkdir(exist_ok=True)
    MISS_FILE.write_text(json.dumps(sorted(misses)))


MISSING = _load_misses()


def fetch_page(title, use_cache=True):
    """Return (html, reason). Sleeps after every request, hit or miss."""
    cf = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", title) + ".html")
    if use_cache and cf.exists():
        return cf.read_text(), "cache"
    if use_cache and title in MISSING:
        return None, "missingtitle (known)"

    delay = 5.0
    for attempt in range(4):
        try:
            r = requests.get(API, params={"action": "parse", "page": title,
                                          "prop": "text", "format": "json",
                                          "formatversion": "2", "redirects": "1"},
                             headers={"User-Agent": UA}, timeout=30)
        except requests.RequestException as e:
            time.sleep(delay); delay *= 2
            if attempt == 3:
                return None, f"network: {type(e).__name__}"
            continue

        time.sleep(THROTTLE)          # ALWAYS — a miss is still a request

        if r.status_code in (429, 503) or r.status_code >= 500:
            wait = delay
            ra = r.headers.get("Retry-After")
            if ra:
                try:
                    wait = max(wait, float(ra))
                except ValueError:
                    pass
            if attempt == 3:
                return None, f"http {r.status_code} after retries"
            print(f"           throttled ({r.status_code}); waiting {wait:.0f}s",
                  flush=True)
            time.sleep(wait); delay *= 2
            continue
        if r.status_code != 200:
            return None, f"http {r.status_code}"

        try:
            data = r.json()
        except ValueError:
            return None, "bad json"
        if "error" in data:
            code = data["error"].get("code", "api error")
            if code == "missingtitle":
                MISSING.add(title); _save_misses(MISSING)
            return None, code

        html = data["parse"]["text"]
        CACHE.mkdir(exist_ok=True)
        cf.write_text(html)
        return html, "fetched"
    return None, "gave up"


def resolve(year, use_cache=True):
    reasons = []
    for t in title_candidates(year):
        html, why = fetch_page(t, use_cache)
        if html:
            return t, html, reasons
        reasons.append(f"{t[:44]} -> {why}")
    return None, None, reasons


def nearest_heading(tbl):
    h = tbl.find_previous(["h2", "h3", "h4"])
    return h.get_text(" ", strip=True).lower() if h else ""


def is_weekly_grid(tbl):
    head = tbl.find("tr")
    if not head:
        return False
    cells = [c.get_text(" ", strip=True).lower() for c in head.find_all(["th", "td"])]
    return sum(1 for c in cells if c.startswith(("week", "preseason", "final"))) >= 3


def clean_team(cell):
    """
    Cells look like "Texas (10-0) (25)" — team, record, first-place votes.

    Strip ONLY the numeric parentheticals. Stripping all of them eats the
    disambiguator too: "Miami (FL)" and "Miami (OH)" both collapse to "Miami",
    and then two different schools share a key. That silently deleted Miami (OH)
    from the 2003 BCS standings, where they were #11 at 13-1.
    "Miami (FL)" -> "Miami" is handled downstream by an explicit alias.
    """
    a = cell.find("a")
    txt = a.get_text(" ", strip=True) if a else cell.get_text(" ", strip=True)
    txt = re.sub(r"\s*\([\d\s\u2013\u2014.\-]+\)", "", txt)   # (10-0), (25), (10-0-1)
    txt = txt.replace("\u0442", "").strip(" .;\u0442").strip()
    # placeholder rows (an em-dash where a team would be) are not teams
    if not any(ch.isalnum() for ch in txt):
        return ""
    return txt


def _tied_with_next(cell):
    """
    Wikipedia hides tie groups in CSS: a cell whose border-bottom is painted the
    same colour as its own background has that border erased, visually merging it
    with the row below. That merge IS the tie. Consecutive-'т' counting can't
    recover this — in 1970 four rows carry 'т' but they are two pairs, not one
    group of four (verified against Carter's T-17 / T-19).
    """
    style = (cell.get("style") or "").replace(" ", "").lower()
    bg = re.search(r"background-color:(#[0-9a-f]{3,6})", style)
    bb = re.search(r"border-bottom:[^;]*?(#[0-9a-f]{3,6})", style)
    return bool(bg and bb and bg.group(1) == bb.group(1))


def final_column(tbl):
    """
    Rows are ranks, columns are weeks; read the last week column.
    Row position is NOT the rank when ties are present — tied teams share the
    rank of the first row in their group.
    """
    entries = []
    for tr in tbl.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        m = re.match(r"(\d+)", cells[0].get_text(" ", strip=True))
        if not m:
            continue
        pos = int(m.group(1))
        if not 1 <= pos <= 25:
            continue
        cell = cells[-2]
        team = clean_team(cell)
        if team:
            entries.append((pos, team, _tied_with_next(cell)))

    out, group_rank = {}, None
    for i, (pos, team, tied_next) in enumerate(entries):
        if group_rank is None:
            group_rank = pos                 # first row of a new group
        out[team] = min(group_rank, out.get(team, 99))
        if not tied_next:
            group_rank = None                # group closes on this row
    return out


COACHES_HEAD = ("coaches", "upi", "up poll", "united press",
                "usa today", "usa today/cnn", "usa today/espn")
BCS_HEAD = ("bcs", "bowl championship series")


def heading_kind(head):
    """
    Which series a grid belongs to, from the heading above it.

    The coaches poll changed names over the decades: UP (pre-1958) -> UPI ->
    USA Today/CNN -> USA Today/ESPN. Wikipedia describes the BCS era pages as
    "two human polls and one formulaic ranking" — the formulaic one is the BCS,
    published on the same pages in the same weekly-grid format.

    Order matters: check BCS before coaches, since a heading like "BCS Standings"
    can sit near coaches-poll prose.
    """
    h = head.lower()
    if any(k in h for k in BCS_HEAD):
        return "bcs"
    if any(k in h for k in COACHES_HEAD):
        return "coaches"
    if "ap poll" in h or "associated press" in h:
        return "ap"
    return None


def extract_grids(soup):
    grids = {}
    for tbl in soup.find_all("table", class_="wikitable"):
        if not is_weekly_grid(tbl):
            continue
        key = heading_kind(nearest_heading(tbl))
        if key and key not in grids:
            grids[key] = final_column(tbl)
    return grids


def load_cfbd_ap(path):
    """{year: {team: ap_rank}} from your verified rankings.json."""
    if not Path(path).exists():
        return None
    data = json.load(open(path))
    schema = data["meta"]["schema"]
    yi, ai = schema.index("year"), schema.index("ap")
    out = {}
    for team, rows in data["teams"].items():
        for r in rows:
            if r[ai] is not None:
                out.setdefault(r[yi], {})[team] = r[ai]
    return out


def check_ap(scraped_ap, cfbd_year):
    """Compare on teams whose names match exactly. Returns (agree, disagree)."""
    if not cfbd_year:
        return (0, 0)
    agree = dis = 0
    for team, rank in cfbd_year.items():
        if team in scraped_ap:
            if scraped_ap[team] == rank:
                agree += 1
            else:
                dis += 1
    return (agree, dis)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="coaches", choices=["coaches", "bcs", "ap"],
                    help="which grid to extract")
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    ap.add_argument("--dump", type=int)
    ap.add_argument("--probe", type=int, help="show what the API says for each candidate title")
    ap.add_argument("--out")
    ap.add_argument("--rankings", default="rankings.json",
                    help="your CFBD pull, used to validate the AP column")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    use_cache = not args.no_cache

    # sensible defaults per series: coaches 1950-2000 (CFBD covers 2001+),
    # BCS 1998-2013 (its whole life; CFBD only has 2007-13 plus a partial 2001)
    if args.start is None: args.start = 1998 if args.series == "bcs" else 1950
    if args.end is None:   args.end = 2013 if args.series == "bcs" else 2000
    if args.out is None:
        args.out = {"bcs": "bcs_wiki.json", "ap": "ap_wiki.json"}.get(
            args.series, "coaches_pre2001.json")
    want = args.series

    if args.probe:
        for t in title_candidates(args.probe):
            html, why = fetch_page(t, use_cache)
            mark = "OK " if html else "-- "
            print(f"  {mark}{t:52} {why}")
            if html:
                soup = BeautifulSoup(html, "html.parser")
                heads = [nearest_heading(x) for x in soup.find_all("table", class_="wikitable")
                         if is_weekly_grid(x)]
                print(f"      weekly grids under headings: {heads}")
        return

    if args.dump:
        title, html, reasons = resolve(args.dump, use_cache)
        if not html:
            sys.exit(f"No page for {args.dump}. Tried:\n  " + "\n  ".join(reasons))
        print(f"page: {title}\n")
        soup = BeautifulSoup(html, "html.parser")
        for i, t in enumerate(soup.find_all("table")):
            grid = is_weekly_grid(t) if t.find("tr") else False
            print(f"  [{i}] class={t.get('class')} weekly_grid={grid}")
            print(f"      heading above: {nearest_heading(t)[:60]!r}")
        print()
        for k, g in extract_grids(soup).items():
            top = sorted(g.items(), key=lambda x: x[1])[:8]
            print(f"  {k.upper():8} ({len(g)} teams): " +
                  ", ".join(f"{r}.{t}" for t, r in top))
        return

    cfbd = load_cfbd_ap(args.rankings)
    if cfbd is None:
        print(f"note: {args.rankings} not found — running without AP validation\n")

    result, flagged, misses = {}, [], []
    for year in range(args.start, args.end + 1):
        title, html, reasons = resolve(year, use_cache)
        if not html:
            print(f"  {year}  UNRESOLVED")
            for rr in reasons:
                print(f"           {rr}")
            misses.append(year)
            continue
        grids = extract_grids(BeautifulSoup(html, "html.parser"))
        coaches = grids.get(want)
        if not coaches:
            found = ", ".join(sorted(grids)) or "none"
            print(f"  {year}  page ok ({title[:40]}), grids found: {found}")
            misses.append(year)
            continue

        agree, dis = (0, 0) if want == "ap" else \
            check_ap(grids.get("ap", {}), (cfbd or {}).get(year, {}))
        top = min(coaches, key=coaches.get)
        status = "ok"
        if want == "ap":
            status = "(no cross-check: AP is the series being replaced)"
        elif cfbd is not None:
            if dis > 0 or agree < 5:
                status = f"CHECK (ap agree={agree} disagree={dis})"
                flagged.append(year)
            else:
                status = f"ap-verified ({agree})"
        print(f"  {year}  {len(coaches):>2} teams · #1 {top:<16} {status}")
        result[str(year)] = coaches

    Path(args.out).write_text(json.dumps(result, indent=1))
    print(f"\nWrote {args.out} — {len(result)} seasons, "
          f"{sum(len(v) for v in result.values())} team-seasons")
    if flagged:
        print(f"  AP cross-check failed ({len(flagged)}): {flagged}")
        print("  -> parse is suspect for these; --dump one to see why")
    if misses:
        print(f"  no data ({len(misses)}): {misses}")


if __name__ == "__main__":
    main()
