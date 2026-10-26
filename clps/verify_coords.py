#!/usr/bin/env python3
"""Verify lunar feature coordinates against Wikipedia (which cites IAU Gazetteer feature IDs).

Run:  python3 verify_coords.py
Emits a markdown table for pasting into sites.json / the spec.
"""

# --- UTF-8 console -------------------------------------------------------
# Prints °, +-, x and arrows. A Windows cp1252 console raises
# UnicodeEncodeError on the first of them, which kills the script after
# the work is done. Importing the bootstrap fixes the streams once.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402

_bootstrap.utf8_streams()
# -------------------------------------------------------------------------

import json
import re
import subprocess
import sys
import time

UA = "LUNAPOLE-verify/1.0 (NASA Space Apps Challenge 2026)"

# (label, wikipedia title, expected category)
FEATURES = [
    ("Shackleton (crater)",       "Shackleton (crater)"),
    ("Nobile (crater)",           "Nobile (crater)"),
    ("Malapert (crater)",         "Malapert (crater)"),
    ("Cabeus (crater)",           "Cabeus (crater)"),
    ("Haworth (crater)",          "Haworth (crater)"),
    ("de Gerlache (crater)",      "De Gerlache (crater)"),
    ("Mons Mouton",               "Mons Mouton"),
    ("Mons Kocher",               "Mons Kocher"),
    ("Mons Malapert",             "Mons Malapert"),
    ("Cabeus B (crater)",         "Cabeus B (crater)"),
    ("Connecting Ridge",          "Connecting Ridge"),
    ("Malapert Massif",           "Malapert Massif"),
    ("Leibnitz-Beta plateau",     "Leibnitz-Beta plateau"),
    ("Slater Plain",              "Slater Plain"),
]

COORD = re.compile(r"\{\{coord\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)")
FEATID = re.compile(r"planetarynames\.wr\.usgs\.gov/Feature/(\d+)")


def _api(url: str):
    p = subprocess.run(
        ["curl", "-sL", "--max-time", "30", "-A", UA, url],
        capture_output=True, text=True,
    )
    if not p.stdout.strip():
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def coords(title: str):
    """Structured coords from the API (authoritative infobox value)."""
    d = _api(
        "https://en.wikipedia.org/w/api.php?action=query&prop=coordinates"
        "&format=json&redirects=1&titles=" + title.replace(" ", "_")
    )
    if not d or "query" not in d:
        return None, None
    for page in d["query"]["pages"].values():
        if "missing" in page:
            return None, None
        co = page.get("coordinates")
        if co:
            return float(co[0]["lat"]), float(co[0]["lon"])
    return None, None


def iau_id(title: str):
    """IAU Gazetteer feature number, cited in the article reference."""
    url = (
        "https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext"
        "&format=json&redirects=1&page=" + title.replace(" ", "_")
    )
    d = _api(url)
    if not d or "parse" not in d:
        return None
    m = FEATID.search(d["parse"]["wikitext"]["*"])
    return m.group(1) if m else None


def main():
    print(f"{'Feature':<24}{'Lat':>9}{'Lon':>11}{'IAU ID':>9}   note")
    print("-" * 74)
    out = {}
    for label, title in FEATURES:
        lat, lon = coords(title)
        fid = iau_id(title)
        if lat is None:
            print(f"{label:<24}{'—':>9}{'—':>11}{(fid or '—'):>9}   no coords / no article")
            out[label] = None
        else:
            print(f"{label:<24}{lat:>9.4f}{lon:>11.4f}{(fid or '—'):>9}")
            out[label] = {"lat": lat, "lon": lon, "iau_id": fid, "title": title}
        time.sleep(0.25)

    with open("coords_verified.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nwrote coords_verified.json")


if __name__ == "__main__":
    sys.exit(main())