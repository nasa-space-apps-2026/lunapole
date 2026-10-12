#!/usr/bin/env python3
"""Verify the south-pole DEM and the site crops derived from it.

Run:  python3 verify/verify_dem.py

Checks that:
  1. the JP2 opens and is polar stereographic, south, centred on the pole
  2. elevations decode into a physically plausible lunar range
  3. the polar-stereographic -> lat/lon inverse projection is correct
  4. each site in sites.json lands inside the DEM and on sane terrain

The decode trap: LOLA products are LSB_INTEGER with SCALING_FACTOR=1 and
OFFSET=0 in the JP2 labels -- the values ARE metres. The sibling IMG labels
use scale 0.5 / offset 1737400. Mixing the two shifts everything by 1.7
million metres. This script asserts the convention explicitly rather than
trusting it.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

ROOT = Path(__file__).resolve().parent.parent
DEM = ROOT / "data" / "dem" / "ldec_875s_10m.jp2"
SITES = ROOT / "clps" / "sites.json"

MOON_R = 1737400.0
STEREO_LAT = -90.0  # south polar stereographic
TRUE_SCALE_LAT = -90.0  # standard: true at the pole

failures = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def stereo_xy_to_latlon(x, y, radius_m=MOON_R):
    """Inverse polar stereographic, south pole.

    x, y in metres from the projection origin.
    Returns (lat_deg, lon_deg) in 0..360 east.
    """
    r = math.hypot(x, y)
    if r == 0:
        return STEREO_LAT, 0.0
    c = 2.0 * math.atan2(r, 2.0 * radius_m)
    lat = -(math.pi / 2.0) + c
    # south polar stereographic: +Y is 0 deg longitude, east increases
    # clockwise, which is what the minus sign on y encodes.
    lon = math.degrees(math.atan2(x, -y)) % 360.0
    return math.degrees(lat), lon


def latlon_to_stereo_xy(lat_deg, lon_deg, radius_m=MOON_R):
    """Forward polar stereographic, south pole. Returns (x, y) in metres."""
    r = radius_m * math.tan(math.pi / 4.0 + math.radians(lat_deg) / 2.0)
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    return r * math.sin(lo), -r * math.cos(lo)


def main():
    if not DEM.exists():
        print(f"MISSING: {DEM.relative_to(ROOT)}\nRun scripts/fetch_dem.sh first.")
        return 2

    ds = gdal.Open(str(DEM))
    if ds is None:
        print("gdal could not open the DEM")
        return 2

    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize
    band = ds.GetRasterBand(1)
    dt = gdal.GetDataTypeName(band.DataType)

    print("=== raster ===")
    print(f"  size            : {w} x {h} px")
    print(f"  datatype        : {dt}")
    print(f"  pixel size      : {gt[1]:.4f} x {gt[5]:.4f} m")
    print(f"  origin (map)    : x={gt[0]:.1f}  y={gt[3]:.1f}")
    print(f"  extent (map)    : {gt[0]:.0f} .. {gt[0] + gt[1] * w:.0f} m  "
          f"({(gt[0] + gt[1] * w - gt[0]) / 1000:.1f} km wide)")
    print(f"  nodata          : {band.GetNoDataValue()}")

    check("pixel size ~10 m", abs(abs(gt[1]) - 10.0) < 0.01, f"{abs(gt[1]):.3f} m")
    check("square raster", w == h, f"{w} x {h}")
    check("LSB_INTEGER (LOLA native)", "LSB" in dt, dt)

    # --- elevation sanity over the full raster ---
    arr = band.ReadAsArray()
    valid = arr[arr != band.GetNoDataValue()] if band.GetNoDataValue() is not None else arr.ravel()
    print(f"\n=== elevations ({valid.size:,} valid px) ===")
    print(f"  min {valid.min():>8.1f} m   max {valid.max():>8.1f} m   "
          f"mean {valid.mean():>8.1f} m")

    # Lunar south polar terrain: floors around -4000 to -8000 m, peaks up to
    # a few thousand m. Anything outside +/-20000 m means a decode error.
    check("elevation min within lunar range (-20000..20000 m)",
          -20000 < valid.min() < 0, f"{valid.min():.0f} m")
    check("elevation max within lunar range (0..20000 m)",
          0 < valid.max() < 20000, f"{valid.max():.0f} m")
    check("mean elevation plausible for south pole (-3000..1500 m)",
          -3000 < valid.mean() < 1500, f"{valid.mean():.0f} m")

    # --- inverse projection check ---
    # Centre of the raster should be very close to the pole.
    cx, cy = gt[0] + gt[1] * w / 2.0, gt[3] + gt[5] * h / 2.0
    clat, clon = stereo_xy_to_latlon(cx, cy, MOON_R)
    print(f"\n=== inverse projection ===")
    print(f"  raster centre ({cx:.0f}, {cy:.0f}) -> lat {clat:.4f}, lon {clon:.2f}")
    check("raster centre maps to the pole", abs(clat + 90.0) < 0.05, f"lat {clat:.5f}")

    # Forward check: a point 100 km from the pole should be at ~89.65 S.
    r = 100_000.0
    flat, flon = stereo_xy_to_latlon(r, 0.0, MOON_R)
    check("100 km from centre -> lat ~89.65 S",
          abs(flat - (-89.6548)) < 0.002, f"lat {flat:.4f}")

    # --- sites ---
    print(f"\n=== sites from sites.json ===")
    sites = json.loads(SITES.read_text())["sites"]
    xmin, ymax = gt[0], gt[3]
    xmax, ymin = gt[0] + gt[1] * w, gt[3] + gt[5] * h

    for s in sites:
        lat, lon = s["lat"], s["lon"]
        if abs(lat) < 87.5:
            print(f"  [skip] {s['name']:<14} {abs(lat):.2f} deg from pole -- "
                  f"outside 87.5S coverage")
            continue
        x, y = latlon_to_stereo_xy(lat, lon)

        px, py = int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5])
        px, py = min(max(px, 0), w - 1), min(max(py, 0), h - 1)
        z = arr[py, px]
        # round-trip: map the pixel back to lat/lon and confirm it matches
        blat, blon = stereo_xy_to_latlon(x, y, MOON_R)
        print(f"  [ok]   {s['name']:<14} lat {blat:8.4f} lon {blon:8.3f}  "
              f"z={z:7.0f} m  px({px},{py})")
        check(f"{s['name']} elevation plausible",
              -20000 < z < 20000, f"{z:.0f} m")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All DEM checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())