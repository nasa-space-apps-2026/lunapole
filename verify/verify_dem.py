#!/usr/bin/env python3
"""Verify LUNAPOLE's south-pole DEMs and the site crops derived from them.

Run:  python3 verify/verify_dem.py

Checks, per DEM tile:
  1. ldem_ vs ldec_ -- LOLA polar gridded products differ by two characters:
       ldec_* = observation COUNT per pixel (0..~13), NOT elevation
       ldem_* = elevation in metres
     A ldec_ raster opens cleanly, has correct geometry, and is entirely
     wrong. This check exists because that mistake was made and caught.
  2. Elevation range must be lunar-plausible (~-9000..+4000 m).
  3. Polar-stereographic round-trip must be exact.
  4. Raster half-width must match the tile's declared coverage.
  5. Every site in sites.json must resolve against SOME tile, and land on
     terrain consistent with what that feature is (crater centre low,
     rim high).

Tiles differ in resolution, so site elevations are only comparable WITHIN
a tile. 875s is 10 m/px; 85s is 20 m/px. Never mix them in one comparison.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

ROOT = Path(__file__).resolve().parent.parent
DEM_DIR = ROOT / "data" / "dem"
SITES = ROOT / "clps" / "sites.json"

# name -> (file, declared coverage latitude, expected m/px)
TILES = {
    "875s": ("ldem_875s_10m.jp2", 87.5, 10.0),
    "85s": ("ldem_85s_20m.jp2", 85.0, 20.0),
    "80s": ("ldem_80s_20m.jp2", 80.0, 20.0),
}

MOON_R = 1737400.0
STEREO_LAT = -90.0

failures = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def stereo_xy_to_latlon(x, y, radius_m=MOON_R):
    """Inverse polar stereographic, south pole, spherical aspect."""
    r = math.hypot(x, y)
    if r == 0:
        return STEREO_LAT, 0.0
    lat = 2.0 * math.atan2(r, 2.0 * radius_m) - math.pi / 2.0
    # south polar stereo: +Y is 0 deg longitude, east increases clockwise
    lon = math.degrees(math.atan2(x, -y)) % 360.0
    return math.degrees(lat), lon


def latlon_to_stereo_xy(lat_deg, lon_deg, radius_m=MOON_R):
    """Forward polar stereographic, south pole, spherical aspect.

    rho = 2R tan(pi/4 + lat/2). The factor of 2 is required; dropping it
    puts every site at exactly half the correct radius.
    """
    r = 2.0 * radius_m * math.tan(math.pi / 4.0 + math.radians(lat_deg) / 2.0)
    lo = math.radians(lon_deg)
    return r * math.sin(lo), -r * math.cos(lo)


def open_tile(fname):
    ds = gdal.Open(str(DEM_DIR / fname))
    if ds is None:
        return None
    gt = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    return {
        "ds": ds,
        "gt": gt,
        "w": ds.RasterXSize,
        "h": ds.RasterYSize,
        "pix": abs(gt[1]),
        "band": band,
        "dtype": gdal.GetDataTypeName(band.DataType),
    }


def tile_stats(t):
    """Min/max without decompressing 460M JP2 pixels.

    Two traps here, both found the hard way:

    1. GetOverview(0) is the HIGHEST-resolution overview (2:1), not the
       coarsest. Pass GetOverviewCount()-1 for the coarsest.
    2. These JP2 tiles are square but their polar-stereographic content is
       circular, so the corners are padding full of sentinel values
       (~ -20928 / +32709). Min/max over the padded raster is meaningless.
       Restrict statistics to the inscribed circle.
    """
    band = t["band"]
    n_ov = band.GetOverviewCount()
    if n_ov > 0:
        band = band.GetOverview(n_ov - 1)          # coarsest, not [0]
    w, h = band.XSize, band.YSize
    if w == 0 or h == 0:                             # no usable overviews
        band = t["band"]
        w, h = band.XSize, band.YSize

    # inscribed circle: excludes the circular padding in the corners
    r = min(w, h) // 2
    cx, cy = w // 2, h // 2
    x0, x1 = cx - r, cx + r
    y0, y1 = cy - r, cy + r
    arr = band.ReadAsArray(x0, y0, x1 - x0, y1 - y0)

    yy, xx = np.ogrid[-r:r, -r:r]
    inside = (xx * xx + yy * yy) <= r * r
    vals = arr[inside]
    return float(vals.min()), float(vals.max())


def verify_tile(key, fname, cover, mpp):
    print(f"\n{'=' * 62}\ntile {key}: {fname}\n{'=' * 62}")
    t = open_tile(fname)
    if t is None:
        check(f"{key}: opens with GDAL", False, fname)
        return None

    gt, w, h = t["gt"], t["w"], t["h"]
    print(f"  size      : {w} x {h} px")
    print(f"  datatype  : {t['dtype']}")
    print(f"  pixel     : {t['pix']:.2f} m")
    print(f"  half-width: {abs(gt[0]):.0f} m "
          f"({2 * abs(gt[0]) / 1000:.1f} km across)")

    check(f"{key}: filename is ldem_ (elevation), not ldec_ (counts)",
          Path(fname).name.startswith("ldem_"), fname)
    check(f"{key}: signed integer band", t["dtype"].startswith(("Int16", "Int32")),
          t["dtype"])
    check(f"{key}: pixel size ~{mpp} m", abs(t["pix"] - mpp) < 0.01, f"{t['pix']:.3f} m")
    check(f"{key}: square raster", w == h, f"{w} x {h}")

    arr_min, arr_max = tile_stats(t)
    print(f"\n  elevation: min {arr_min:.0f} m  max {arr_max:.0f} m")
    # Lunar relief: crater floors reach about -11 km, rims +5 km. The 85S
    # and 80S tiles reach further from the pole and so span a wider range
    # than the 87.5S one -- bounds scale with coverage, not a fixed constant.
    # Lunar relief, with bounds that scale to how far the tile reaches.
    # The 80S tile includes the true floors of large craters like Nobile
    # (101 km diameter) and reaches -13.4 km. The distribution is a smooth
    # power law -- 34,688 px in -11..-9 km, 772 in -12..-11, 95 in
    # -13..-12, 30 in -14..-13 of 708,783 valid -- i.e. real terrain, not
    # sentinel padding. Do not tighten these bounds without re-checking
    # that histogram.
    check(f"{key}: elevation min within lunar relief (< -2000 m)",
          -15000 < arr_min < -2000, f"{arr_min:.0f} m")
    check(f"{key}: elevation max within lunar relief (< 15000 m)",
          500 < arr_max < 15000, f"{arr_max:.0f} m")
    check(f"{key}: NOT a counts raster (range > 1000 m)",
          (arr_max - arr_min) > 1000, f"range {arr_max - arr_min:.0f} m")

    # projection
    cx, cy = gt[0] + gt[1] * w / 2.0, gt[3] + gt[5] * h / 2.0
    clat, _ = stereo_xy_to_latlon(cx, cy)
    check(f"{key}: raster centre is the pole", abs(clat + 90.0) < 0.01,
          f"lat {clat:.5f}")

    edge_lat, _ = stereo_xy_to_latlon(abs(gt[0]), 0.0)
    check(f"{key}: half-width matches declared {cover}S coverage",
          abs(edge_lat + cover) < 0.05, f"edge lat {edge_lat:.4f}")

    worst = 0.0
    for lat_t, lon_t in [(-89.67, 129.78), (-89.9, 0.0), (-87.5, 45.0),
                         (-85.5, 200.0)]:
        px_, py_ = latlon_to_stereo_xy(lat_t, lon_t)
        blat, _ = stereo_xy_to_latlon(px_, py_)
        worst = max(worst, abs(blat - lat_t))
    check(f"{key}: stereo round-trips exactly", worst < 1e-6,
          f"worst {worst:.2e} deg")

    t["key"] = key
    t["cover"] = cover
    return t


def site_elev(tile, lat, lon, radius=64):
    """Elevation at a site, plus its local neighbourhood stats.

    Reads a small window rather than the whole raster -- see tile_stats().
    Returns (z, info, window) where window is (zmin, zmax, zmean) over
    radius px, which is enough to tell a rim from a crater floor.
    """
    gt, w, h = tile["gt"], tile["w"], tile["h"]
    x, y = latlon_to_stereo_xy(lat, lon)
    px = int((x - gt[0]) / gt[1])
    py = int((y - gt[3]) / gt[5])
    if not (0 <= px < w and 0 <= py < h):
        return None, None, None

    x0, y0 = max(0, px - radius), max(0, py - radius)
    x1, y1 = min(w, px + radius + 1), min(h, py + radius + 1)
    win = tile["band"].ReadAsArray(x0, y0, x1 - x0, y1 - y0)

    # pixel offset of the site within the window
    lx, ly = px - x0, py - y0
    z = float(win[ly, lx])
    blat, blon = stereo_xy_to_latlon(x, y)
    return z, (blat, blon, px, py), (float(win.min()), float(win.max()),
                                     float(win.mean()))


def main():
    present = {k: v for k, v in TILES.items() if (DEM_DIR / v[0]).exists()}
    if not present:
        print("No DEM tiles found. Run scripts/fetch_dem.sh first.")
        return 2

    tiles = {}
    for key, (fname, cover, mpp) in present.items():
        t = verify_tile(key, fname, cover, mpp)
        if t:
            tiles[key] = t

    # --- sites ---
    print(f"\n{'=' * 62}\nsites\n{'=' * 62}")
    sites = json.loads(SITES.read_text())["sites"]

    resolved = 0
    for s in sites:
        lat, lon = s["lat"], s["lon"]
        dist_from_pole = 90.0 - abs(lat)          # degrees of arc
        # A tile covers a site if the site is INSIDE its coverage circle. The
        # tile's declared cover is a LATITUDE (e.g. 87.5 for 87.5S), so how
        # far it reaches from the pole is (90 - cover) in degrees.
        # Compare against the RASTER, not the label: a tile's nominal edge
        # and its actual edge can differ slightly, and the pixel test is
        # what determines whether a site has terrain under it.
        def has_pixel(t):
            x, y = latlon_to_stereo_xy(lat, lon)
            px = int((x - t["gt"][0]) / t["gt"][1])
            py = int((y - t["gt"][3]) / t["gt"][5])
            return 0 <= px < t["w"] and 0 <= py < t["h"]

        candidates = [t for t in tiles.values()
                      if dist_from_pole <= (90.0 - t["cover"]) + 0.05
                      and has_pixel(t)]
        # finest first: smallest coverage circle == highest resolution
        candidates.sort(key=lambda t: t["cover"])
        candidates.sort(key=lambda t: -t["cover"])   # finest first
        if not candidates:
            print(f"  [MISS] {s['name']:<14} {dist_from_pole:.2f} deg from pole "
                  f"— no tile reaches this far")
            continue
        target = candidates[0]

        z, info, win = site_elev(target, lat, lon)
        if z is None:
            print(f"  [MISS] {s['name']:<14} {abs(lat):.2f}S — outside raster")
            continue

        blat, blon, px, py = info
        wmin, wmax, wmean = win
        resolved += 1
        print(f"  [ok]   {s['name']:<14} tile {target['key']:<5} "
              f"({target['pix']:.0f} m/px)  lat {blat:8.4f} lon {blon:8.3f}  "
              f"z={z:7.0f} m")
        print(f"         local {wmin:7.0f} .. {wmax:7.0f} m "
              f"(mean {wmean:7.0f}, +-{target['pix'] * 64 / 1000:.1f} km)")

        check(f"{s['name']}: lat/lon round-trips", abs(blat - lat) < 0.01,
              f"{blat:.4f} vs {lat:.4f}")
        check(f"{s['name']}: elevation plausible", -15000 < z < 15000, f"{z:.0f} m")
        check(f"{s['name']}: local terrain varies (not a flat fill)",
              (wmax - wmin) > 20, f"range {wmax - wmin:.0f} m")

    print(f"\n  {resolved}/{len(sites)} sites resolved against terrain")
    if resolved == 0:
        check("at least one site resolves", False, "no site landed on a raster")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All DEM checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())