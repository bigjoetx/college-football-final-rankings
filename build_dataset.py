#!/usr/bin/env python3
"""
build_dataset.py — Merge rankings.json + fbs_2026.json into a single embeddable
payload: current-FBS teams only, with contrast-corrected display colors.

    python3 build_dataset.py

Inputs : rankings.json, fbs_2026.json   (same folder)
Output : cfb_data.json                  (paste into the HTML)

Why colors get adjusted
-----------------------
Official team colors are chosen for helmets and jerseys, not for 3px bars on a
near-black background. Texas A&M's #500000 scores 1.28:1 against #080808 —
invisible. Iowa and Purdue are literally #000000. So we keep the official color
for reference and derive a `display` color: same hue and saturation, lightness
raised until it clears a contrast floor. Achromatic primaries (black/near-black)
fall back to the team's alternate color when that has usable chroma, since
brightening pure black just yields gray.
"""

import colorsys
import json
import sys
from pathlib import Path

BG_HEX = "080808"          # chart background
CONTRAST_FLOOR = 3.0       # WCAG minimum for graphical objects (4.5 is for text)
ACHROMATIC_SAT = 0.15      # below this, treat primary as black/white/gray

# Hand-picked colors win over the algorithm. Pure lightness-raising preserves
# hue but not character: maroon IS its darkness, so brightening #500000 to clear
# the contrast floor yields fire-engine red. A slightly desaturated maroon hits
# the same measured contrast while still reading as maroon. Add teams here as
# you find ones the algorithm handles badly.
COLOR_OVERRIDES = {
    "Texas A&M": "#CC2222",   # 3.64:1 — hand-picked, beats the derived #C00000
}


# ── color math ────────────────────────────────────────────────────────

def hex_to_rgb(h):
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None


def rgb_to_hex(rgb):
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02X}" for c in rgb)


def rel_luminance(rgb):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(rgb_a, rgb_b):
    la, lb = rel_luminance(rgb_a), rel_luminance(rgb_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def brighten_to_contrast(rgb, bg_rgb, floor=CONTRAST_FLOOR):
    """Raise HLS lightness until the contrast floor is met. Hue preserved."""
    h, l, s = colorsys.rgb_to_hls(*rgb)
    for step in range(101):
        cand_l = min(1.0, l + step * 0.01)
        cand = colorsys.hls_to_rgb(h, cand_l, s)
        if contrast(cand, bg_rgb) >= floor:
            return cand
    return colorsys.hls_to_rgb(h, 0.85, s)


def pick_display_color(primary, alternate, bg_rgb):
    """Return (display_hex, note) for a team."""
    p = hex_to_rgb(primary)
    a = hex_to_rgb(alternate)

    if p is None:
        return ("#CCCCCC", "no primary color; used neutral fallback")

    if contrast(p, bg_rgb) >= CONTRAST_FLOOR:
        return (rgb_to_hex(p), None)

    _, _, sat = colorsys.rgb_to_hls(*p)

    # Pure/near black has no hue to preserve — try the alternate instead.
    if sat < ACHROMATIC_SAT and a is not None:
        _, _, alt_sat = colorsys.rgb_to_hls(*a)
        if alt_sat >= ACHROMATIC_SAT:
            if contrast(a, bg_rgb) >= CONTRAST_FLOOR:
                return (rgb_to_hex(a), "used alternate color (primary achromatic)")
            return (rgb_to_hex(brighten_to_contrast(a, bg_rgb)),
                    "used brightened alternate (primary achromatic)")

    return (rgb_to_hex(brighten_to_contrast(p, bg_rgb)), "brightened for contrast")


# ── main ──────────────────────────────────────────────────────────────

def main():
    src = "rankings_merged.json" if Path("rankings_merged.json").exists() else "rankings.json"
    for f in (src, "fbs_2026.json"):
        if not Path(f).exists():
            sys.exit(f"Missing {f} — run this in the same folder as your data.")
    print(f"reading {src}")

    rankings = json.load(open(src))
    fbs = json.load(open("fbs_2026.json"))
    bg = hex_to_rgb(BG_HEX)

    schema = rankings["meta"]["schema"]
    by_school = rankings["teams"]

    teams = []
    adjusted = 0
    for t in sorted(fbs, key=lambda x: x["school"]):
        school = t["school"]
        if school in COLOR_OVERRIDES:
            display, note = COLOR_OVERRIDES[school], None
        else:
            display, note = pick_display_color(t.get("color"), t.get("alternateColor"), bg)
        if note:
            adjusted += 1

        # CFBD returns http:// logo URLs. Any https:// host — GitHub Pages, for
        # one — blocks those as mixed content and the images silently vanish.
        logos = [(l or "").replace("http://", "https://") for l in (t.get("logos") or [])]
        teams.append({
            "school": school,
            "conference": t.get("conference") or "",
            "color": (t.get("color") or "").upper(),
            "display": display,
            "logo": logos[0] if logos else None,
            "seasons": by_school.get(school, []),
        })

    ranked = [t for t in teams if t["seasons"]]
    unranked = [t for t in teams if not t["seasons"]]

    # How deep each poll actually went. A #10 in 1965 was the LAST ranked team;
    # a #10 in 2025 is a good year. Same height on a fixed 1-25 axis, so the
    # chart needs to draw where "unranked" began in each era.
    # Verified against the poll sizes derived from the data itself.
    poll_depth = {
        "ap": [[1936, 1961, 20], [1962, 1967, 10], [1968, 1988, 20], [1989, 2025, 25]],
        "coaches": [[1950, 1989, 20], [1990, 2025, 25]],
        # BCS ranked 15 teams 1998-2002, then expanded to 25 in 2003
        "bcs": [[1998, 2002, 15], [2003, 2013, 25]],
        "cfp": [[2014, 2025, 25]],
    }

    payload = {
        "meta": {
            **rankings["meta"],
            "pollDepth": poll_depth,
            "filter": "current FBS members as of 2026",
            "colorNote": (f"`display` is contrast-corrected to clear "
                          f"{CONTRAST_FLOOR}:1 on #{BG_HEX}; `color` is the "
                          f"official team color."),
        },
        "teams": teams,
    }

    out = Path("cfb_data.json")
    json.dump(payload, out.open("w"), separators=(",", ":"))

    print(f"Wrote {out}  ({out.stat().st_size/1024:.0f} KB)")
    print(f"  {len(teams)} FBS teams · {sum(len(t['seasons']) for t in teams)} ranked team-seasons")
    print(f"  {len(ranked)} with ranking history · {len(unranked)} never ranked")
    print(f"  {adjusted} colors adjusted for contrast")
    if unranked:
        print("\n  Never ranked (still selectable, will render empty):")
        print("   ", ", ".join(t["school"] for t in unranked))


if __name__ == "__main__":
    main()
