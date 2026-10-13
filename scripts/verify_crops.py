#!/usr/bin/env python3
"""Quick sanity check on cropped site DEMs in artifacts/dem/.

Verifies:
  1. Each site in sites.json has a corresponding .tif
  2. Elevation range is lunar-plausible
  3. The crop is centred on the right coordinates
  4. GeoTIFF tags match the site metadata

Usage:  python3 scripts/verify_crops.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parent.parent
SITES_FILE = ROOT / "clps" / "sites.json"
CROP_DIR = ROOT / "artifacts" / "dem"

MOON_R = 1737400.0
failures = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def stereo_xy_to_latlon(x, y, radius_m=MOON_R):
    r = math.hypot(x, y)
    if r == 0:
        return -90.0, 0.0
    lat = 2.0 * math.atan2(r, 2.0 * radius_m) - math.pi / 2.0
    lon = math.degrees(math.atan2(x, -y)) % 360.0
    return math.degrees(lat), lon


def main():
    if not SITES_FILE.exists():
        print(f"ERROR: {SITES_FILE} not found")
        return 1
    if not CROP_DIR.exists():
        print(f"ERROR: {CROP_DIR} not found. Run scripts/crop_sites.py first.")
        return 1

    sites = json.loads(SITES_FILE.read_text())["sites"]

    for site in sites:
        sid = site["id"]
        tif = CROP_DIR / f"{sid}.tif"
        print(f"\n{sid} ({site['name']}):")

        check(f"{sid}: .tif exists", tif.exists())
        if not tif.exists():
            continue

        with rasterio.open(tif) as src:
            data = src.read(1)
            gt = src.transform

            zmin, zmax = float(data.min()), float(data.max())
            check(f"{sid}: elevation plausible",
                  -15000 < zmin and zmax < 15000,
                  f"[{zmin:.0f}, {zmax:.0f}] m")
            check(f"{sid}: terrain varies (not flat fill)",
                  (zmax - zmin) > 100,
                  f"range {zmax - zmin:.0f} m")

            # Centre of the crop in lat/lon
            cx = gt.c + gt.a * src.width / 2
            cy = gt.f + gt.e * src.height / 2
            clat, clon = stereo_xy_to_latlon(cx, cy)

            # Normalize longitudes to compare
            expect_lon = site["lon"] % 360.0
            check(f"{sid}: crop centred on site lat",
                  abs(clat - site["lat"]) < 0.1,
                  f"crop {clat:.4f} vs site {site['lat']:.4f}")
            check(f"{sid}: crop centred on site lon",
                  abs(clon - expect_lon) < 0.2,
                  f"crop {clon:.3f} vs site {expect_lon:.3f}")

            # Check tags
            tags = src.tags()
            if "site_id" in tags:
                check(f"{sid}: tag site_id matches",
                      tags["site_id"] == sid,
                      tags.get("site_id", ""))

            print(f"         {src.width}x{src.height} px, "
                  f"{tif.stat().st_size / 1e6:.1f} MB")

    print(f"\n{'=' * 50}")
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print(f"All {len(sites)} crop checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
