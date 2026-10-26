#!/usr/bin/env python3
"""Crop per-site DEM windows from the LOLA polar tiles.

Reads sites from clps/sites.json and produces one GeoTIFF per site in
artifacts/dem/<site_id>.tif.  Uses windowed reads (rasterio) — never loads
a full tile into memory.

Usage:
    python3 scripts/crop_sites.py [--radius-km 25]

The default 25 km radius gives a 50 km square crop around each site centre,
which is enough for far-field horizon work (curvature at 25 km ≈ 180 m).
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

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import from_bounds

ROOT = Path(__file__).resolve().parent.parent
DEM_DIR = ROOT / "data" / "dem"
SITES_FILE = ROOT / "clps" / "sites.json"
OUT_DIR = ROOT / "artifacts" / "dem"

MOON_R = 1737400.0  # from constants.json


def latlon_to_stereo_xy(lat_deg, lon_deg, radius_m=MOON_R):
    """Forward polar stereographic, south pole, spherical aspect.

    rho = 2R tan(pi/4 + lat/2).  Matches verify_dem.py exactly.
    """
    r = 2.0 * radius_m * math.tan(math.pi / 4.0 + math.radians(lat_deg) / 2.0)
    lo = math.radians(lon_deg)
    return r * math.sin(lo), -r * math.cos(lo)


# tile key -> (filename, coverage latitude south, m/px)
TILES = {
    "875s": ("ldem_875s_10m.jp2", 87.5, 10.0),
    "85s":  ("ldem_85s_20m.jp2",  85.0, 20.0),
    "80s":  ("ldem_80s_20m.jp2",  80.0, 20.0),
}


def pick_tile(lat_deg):
    """Choose the finest-resolution tile that covers this latitude."""
    dist_from_pole = 90.0 - abs(lat_deg)
    # Sort candidates by coverage (smallest first = finest resolution)
    candidates = []
    for key, (fname, cover, mpp) in TILES.items():
        tile_reach = 90.0 - cover  # degrees from pole
        if dist_from_pole <= tile_reach + 0.05:
            path = DEM_DIR / fname
            if path.exists():
                candidates.append((key, fname, cover, mpp, tile_reach))
    # finest first = smallest coverage circle
    candidates.sort(key=lambda c: c[4])
    return candidates[0] if candidates else None


def crop_site(site, radius_km):
    """Crop a square window around a site and write it as a GeoTIFF."""
    sid = site["id"]
    lat, lon = site["lat"], site["lon"]
    radius_m = radius_km * 1000.0

    tile_info = pick_tile(lat)
    if tile_info is None:
        print(f"  [SKIP] {sid}: no tile covers lat {lat}")
        return False

    key, fname, cover, mpp, _ = tile_info
    tile_path = DEM_DIR / fname

    # Site centre in stereo coords
    cx, cy = latlon_to_stereo_xy(lat, lon)

    with rasterio.open(tile_path) as src:
        gt = src.transform
        pix = abs(gt.a)  # m/px

        # Pixel coords of site centre
        px = (cx - gt.c) / gt.a
        py = (cy - gt.f) / gt.e

        # Window in pixels
        half_px = int(math.ceil(radius_m / pix))
        col_off = int(px) - half_px
        row_off = int(py) - half_px
        width = 2 * half_px
        height = 2 * half_px

        # Clamp to raster bounds
        col_off_c = max(0, col_off)
        row_off_c = max(0, row_off)
        width_c = min(width - (col_off_c - col_off), src.width - col_off_c)
        height_c = min(height - (row_off_c - row_off), src.height - row_off_c)

        if width_c <= 0 or height_c <= 0:
            print(f"  [SKIP] {sid}: window falls outside raster")
            return False

        window = Window(col_off_c, row_off_c, width_c, height_c)
        data = src.read(1, window=window)

        # Compute transform for the cropped window
        win_transform = src.window_transform(window)

        out_path = OUT_DIR / f"{sid}.tif"
        profile = {
            "driver": "GTiff",
            "dtype": data.dtype,
            "width": width_c,
            "height": height_c,
            "count": 1,
            "crs": src.crs,
            "transform": win_transform,
            "compress": "deflate",
            "predictor": 2,
        }
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data, 1)
            dst.update_tags(
                site_id=sid,
                site_name=site["name"],
                site_lat=str(lat),
                site_lon=str(lon),
                source_tile=fname,
                source_resolution_m=str(mpp),
                crop_radius_km=str(radius_km),
                units="metres",
            )

    fsize = out_path.stat().st_size
    zmin, zmax = float(data.min()), float(data.max())
    print(f"  [OK]   {sid:<14} tile {key:<5} ({mpp:.0f} m/px)  "
          f"{width_c}x{height_c} px  "
          f"z=[{zmin:.0f}, {zmax:.0f}] m  "
          f"{fsize / 1e6:.1f} MB")
    return True


def main():
    parser = argparse.ArgumentParser(description="Crop per-site DEM windows")
    parser.add_argument("--radius-km", type=float, default=25.0,
                        help="Half-width of the crop square in km (default: 25)")
    args = parser.parse_args()

    if not SITES_FILE.exists():
        print(f"ERROR: {SITES_FILE} not found")
        return 1

    sites = json.loads(SITES_FILE.read_text())["sites"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Cropping {len(sites)} sites, radius {args.radius_km} km\n")

    ok = 0
    for site in sites:
        if crop_site(site, args.radius_km):
            ok += 1

    print(f"\n{ok}/{len(sites)} sites cropped → {OUT_DIR}/")

    if ok == 0:
        print("\nNo sites cropped. Did you run scripts/fetch_dem.sh first?")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
