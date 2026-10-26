#!/usr/bin/env python3
"""Export compact terrain heightmaps for the offline app (P5 asset).

The browser has no GeoTIFF or JPEG-2000 decoder, and shipping one would mean
vendoring more code than the app itself. This reads the already-verified P1
crop and writes one small binary per site.

    python scripts/export_terrain.py                # every site with a crop
    python scripts/export_terrain.py --size 512
    python scripts/export_terrain.py --check        # verify, do not write

Format (little-endian):

    header '<8sH16sIddd'    (54 B)
      magic   8s  b'LUNATRN\\0'
      version H   1
      site   16s  NUL-padded ASCII
      n       I   samples per side
      grid_m  d   spacing between samples, metres
      cx_m    d   projected x of the crop centre (south polar stereo)
      cy_m    d   projected y of the crop centre
    body    n*n '<i2' metres, row 0 = north (+y), direct nearest-neighbour
            samples of the crop. Nothing is averaged or interpolated: every
            height in the 3D view is a measured LOLA pixel.

Sampling is NEAREST on purpose. A bilinear mesh would look smoother and would
hide the fact that the source is 20 m/px in places; the app labels the sampled
spacing instead.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

# UTF-8 console: this script prints degree glyphs. See _bootstrap.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402

_bootstrap.utf8_streams()

import numpy as np  # noqa: E402
import rasterio  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CROPS = ROOT / "artifacts" / "dem"
OUT = ROOT / "app" / "data" / "terrain"
SITES_FILE = ROOT / "clps" / "sites.json"

MAGIC = b"LUNATRN\0"
VERSION = 1
HDR_FMT = "<8sH16sIddd"
HDR_SIZE = struct.calcsize(HDR_FMT)
DEFAULT_N = 384


def load_sites():
    return json.loads(SITES_FILE.read_text(encoding="utf-8"))["sites"]


def export_one(site: dict, n_target: int) -> dict:
    sid = site["id"]
    crop = CROPS / f"{sid}.tif"
    if not crop.is_file():
        raise FileNotFoundError(f"{crop} missing - run scripts/crop_sites.py")

    with rasterio.open(crop) as src:
        z = src.read(1)
        px_m = abs(src.transform.a)
        cx = src.transform.c + src.transform.a * (src.width / 2.0)
        cy = src.transform.f + src.transform.e * (src.height / 2.0)
        height, width = src.height, src.width

    if height != width:
        raise ValueError(f"{crop}: expected a square crop, got {width}x{height}")
    n = min(int(n_target), width)
    idx = np.rint(np.linspace(0, width - 1, n)).astype(np.int64)
    small = z[np.ix_(idx, idx)].astype("<i2")
    grid_m = px_m * (width - 1) / (n - 1)
    side_m = grid_m * (n - 1)

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{sid}.bin"
    hdr = struct.pack(HDR_FMT, MAGIC, VERSION, sid.encode()[:16], n,
                      grid_m, cx, cy)
    out.write_bytes(hdr + small.tobytes())

    return {
        "site_id": sid,
        "file": f"data/terrain/{sid}.bin",
        "n": n,
        "grid_m": grid_m,
        "side_m": side_m,
        "cx_m": cx,
        "cy_m": cy,
        "source_crop": f"artifacts/dem/{sid}.tif",
        "source_px_m": px_m,
        "source_px": width,
        "min_m": int(small.min()),
        "max_m": int(small.max()),
        "sampling": "nearest",
        "bytes": out.stat().st_size,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--size", type=int, default=DEFAULT_N,
                    help=f"samples per side (default {DEFAULT_N})")
    ap.add_argument("--sites", nargs="*", help="site ids (default: all with crops)")
    ap.add_argument("--check", action="store_true",
                    help="verify existing exports, do not write")
    args = ap.parse_args()

    sites = load_sites()
    if args.sites:
        wanted = set(args.sites)
        sites = [s for s in sites if s["id"] in wanted]
        missing = wanted - {s["id"] for s in sites}
        if missing:
            print(f"unknown site id(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

    have = [s for s in sites if (CROPS / f"{s['id']}.tif").is_file()]
    absent = [s["id"] for s in sites if s not in have]
    if absent:
        print(f"no crop for: {', '.join(absent)} (skipped)")
    if not have:
        print("BLOCKED: no crops in artifacts/dem - run scripts/crop_sites.py",
              file=sys.stderr)
        return 2

    index_path = OUT / "index.json"
    if args.check:
        if not index_path.is_file():
            print("BLOCKED: no app/data/terrain/index.json", file=sys.stderr)
            return 2
        meta = json.loads(index_path.read_text(encoding="utf-8"))
        ok = True
        for rec in meta["sites"]:
            path = OUT / f"{rec['site_id']}.bin"
            if not path.is_file():
                print(f"  [MISS] {path.name}")
                ok = False
                continue
            size = path.stat().st_size
            want = HDR_SIZE + rec["n"] * rec["n"] * 2
            good = size == want
            print(f"  [{'OK' if good else 'FAIL'}] {path.name}  {size} B"
                  f" (want {want})")
            ok &= good
        return 0 if ok else 1

    records = []
    for site in have:
        rec = export_one(site, args.size)
        records.append(rec)
        print(f"  [OK] {rec['site_id']:<12} {rec['n']}x{rec['n']} "
              f"{rec['grid_m']:.1f} m/sample  "
              f"z {rec['min_m']}..{rec['max_m']} m  "
              f"{rec['bytes'] / 1024:.0f} kB")

    payload = {
        "format": "LUNATRN v1, int16 little-endian, nearest sampling",
        "sites": records,
    }
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    print(f"\n{len(records)} terrain export(s) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
