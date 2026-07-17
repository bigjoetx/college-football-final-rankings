import json, re
from pathlib import Path

data = json.load(open("cfb_data.json"))

# Joe's hand-written A&M notes, preserved. The API can't produce these.
NOTES = {
 "Texas A&M|1939": "AP National Champion · Sugar Bowl (beat Tulane 14-13)",
 "Texas A&M|1955": "Bear Bryant's 2nd year — big jump from 1-9 in '54",
 "Texas A&M|1956": "Bear Bryant · SWC Champions · came within inches of perfection",
 "Texas A&M|1957": "John David Crow wins Heisman Trophy",
 "Texas A&M|1985": "Sherrill Cotton Bowl win vs Auburn (36-16)",
 "Texas A&M|1987": "Sherrill Cotton Bowl win vs Notre Dame (35-10)",
 "Texas A&M|1991": "SWC Champions (8-0 conf)",
 "Texas A&M|1992": "SWC Champions · two straight",
 "Texas A&M|1993": "SWC Champions · three straight",
 "Texas A&M|1994": "NCAA probation · no bowl, no Coaches Poll eligibility",
 "Texas A&M|1998": "Big 12 Champions · BCS Sugar Bowl (lost to Ohio St 14-24)",
 "Texas A&M|2012": "Johnny Manziel wins Heisman · first SEC season",
 "Texas A&M|2020": "COVID season · Orange Bowl champions · just missed CFP",
 "Texas A&M|2025": "First CFP appearance · #7 seed · lost to Miami in Round 1",
}

tpl = Path("template.html").read_text()
out = tpl.replace("__DATA__", json.dumps(data, separators=(",", ":")))
out = out.replace("__NOTES__", json.dumps(NOTES, indent=1))
Path("cfb_rankings.html").write_text(out)

kb = Path("cfb_rankings.html").stat().st_size / 1024
assert "__DATA__" not in out and "__NOTES__" not in out
print(f"cfb_rankings.html  {kb:.0f} KB")
print(f"  teams embedded: {len(data['teams'])}")
print(f"  notes embedded: {len(NOTES)}")
