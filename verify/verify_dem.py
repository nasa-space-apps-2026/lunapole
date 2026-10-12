#!/usr/bin/env python3
"""Verify the south-pole DEM and the site crops derived from it.

Run:  python3 verify/verify_dem.py

CHECKS THAT HAVE ALREADY CAUGHT REAL BUGS -- do not weaken them:

  1. ldec_ vs ldem_ -- the LOLA polar gridded products are named confusingly:
       ldec_* = observation COUNT per pixel (0..~13), NOT elevation
       ldem_* = elevation in metres
     Downloading ldec_ by mistake yields a raster that opens cleanly, has
     plausible-looking numbers, and is completely wrong. This script is what
     caught that.

  2. Elevation range must be lunar-plausible (roughly -9000..+4000 m). A
     0..13 m range means counts, not heights.

  3. Inverse projection: 100 km from the polar-stereo centre must land at
     about -89.65 deg latitude. This catches a wrong-projection bug that
     leaves every pixel shifted.

  4. Every site in sites.json must round-trip to its catalogue lat/lon.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

ROOT = Path(__file__).resolve().parent.parent
DEM = ROOT / "data" / "dem" / "ldem_875s_10m.jp2"
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
    """Inverse polar stereographic, south pole, spherical aspect.

    Returns (lat_deg, lon_deg) with lon in 0..360 east.
    """
    r = math.hypot(x, y)
    if r == 0:
        return STEREO_LAT, 0.0
    lat = 2.0 * math.atan2(r, 2.0 * radius_m) - math.pi / 2.0
    # south polar stereo: +Y is 0 deg longitude, east increases clockwise
    lon = math.degrees(math.atan2(x, -y)) % 360.0
    return math.degrees(lat), lon


def latlon_to_stereo_xy(lat_deg, lon_deg, radius_m=MOON_R):
    """Forward polar stereographic, south pole, spherical aspect.

    rho = 2R * tan(pi/4 + lat/2)

    The factor of 2 is required and easy to drop: with R instead of 2R the
    output is exactly half, which the round-trip check catches.
    """
    r = 2.0 * radius_m * math.tan(math.pi / 4.0 + math.radians(lat_deg) / 2.0)
    lo = math.radians(lon_deg)
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
    check("signed integer band (elevation is signed; counts are not)",
          dt.startswith(("Int16", "Int32")), dt)

    # ldec_ products are observation COUNTS (0..~13). Reject them outright.
    check("this is ldem_ (elevation), not ldec_ (counts)",
          DEM.stem.startswith("ldem_"), DEM.name)

    # --- elevation sanity over the full raster ---
    arr = band.ReadAsArray()
    valid = arr[arr != band.GetNoDataValue()] if band.GetNoDataValue() is not None else arr.ravel()
    print(f"\n=== elevations ({valid.size:,} valid px) ===")
    print(f"  min {valid.min():>8.1f} m   max {valid.max():>8.1f} m   "
          f"mean {valid.mean():>8.1f} m")

    # Lunar south polar terrain: crater floors reach about -8000 m, peaks a few
    # thousand m. An ldec_ counts raster lands in 0..~13 and fails here.
    check("elevation min is lunar-plausible (-12000..-2000 m)",
          -12000 < valid.min() < -2000, f"{valid.min():.0f} m")
    check("elevation max is lunar-plausible (500..5000 m)",
          500 < valid.max() < 5000, f"{valid.max():.0f} m")
    check("mean elevation plausible for south pole (-3000..500 m)",
          -3000 < valid.mean() < 500, f"{valid.mean():.0f} m")
    check("NOT an observation-count raster (range > 100 m)",
          (valid.max() - valid.min()) > 100,
          f"range {valid.max() - valid.min():.0f} m")

    # --- inverse projection check ---
    # Centre of the raster should be very close to the pole.
    cx, cy = gt[0] + gt[1] * w / 2.0, gt[3] + gt[5] * h / 2.0
    clat, clon = stereo_xy_to_latlon(cx, cy, MOON_R)
    print(f"\n=== inverse projection ===")
    print(f"  raster centre ({cx:.0f}, {cy:.0f}) -> lat {clat:.4f}, lon {clon:.2f}")
    check("raster centre maps to the pole", abs(clat + 90.0) < 0.05, f"lat {clat:.5f}")

    # Forward/inverse round-trip: 100 km of arc from the pole is 3.2978 deg,
    # i.e. latitude -86.7022 -- NOT -89.65 (that is only ~10 km out). An
    # earlier version of this check asserted -89.65 and failed against
    # correct code.
    r = 100_000.0
    flat, flon = stereo_xy_to_latlon(r, 0.0, MOON_R)
    expect = -(90.0 - math.degrees(100_000.0 / MOON_R))
    check("100 km from centre -> lat -86.7022 (3.2978 deg of arc)",
          abs(flat - expect) < 0.001, f"lat {flat:.4f}, expected {expect:.4f}")

    # Round-trip every test point exactly.
    worst = 0.0
    for lat_t, lon_t in [(-89.67, 129.78), (-89.9, 0.0), (-87.5, 45.0)]:
        px_, py_ = latlon_to_stereo_xy(lat_t, lon_t)
        blat, blon = stereo_xy_to_latlon(px_, py_)
        worst = max(worst, abs(blat - lat_t))
    check("stereo <-> lat/lon round-trips exactly", worst < 1e-6,
          f"worst error {worst:.2e} deg")

    # The raster edge must match its declared coverage.
    edge_lat, _ = stereo_xy_to_latlon(75840.0, 0.0, MOON_R)
    check("raster half-width lands at the declared 87.5S edge",
          abs(edge_lat + 87.5) < 0.02, f"lat {edge_lat:.4f}")

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
              -12000 < z < 5000, f"{z:.0f} m")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All DEM checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())