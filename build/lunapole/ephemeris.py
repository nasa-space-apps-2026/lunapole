"""LUNAPOLE ephemeris bake — P2 deliverable.

Bakes per-site, per-timestep vectors into artifacts/ephemeris/<site>.bin:
sub-solar lat/lon, sub-Earth lat/lon, Earth distance, Earth angular
diameter, and (for the frontend's convenience) geometric Sun/Earth
elevation at the site.

One design decision that matters: each timestep calls spkpos() ONCE for
the Sun and ONCE for the Earth (IAU_MOON, abcorr 'LT' -- the retarded
position, which is where shadow geometry actually points), then derives
everything from those two vectors — sub-points by normalising, elevations
by dotting with the site's surface normal. This guarantees the subsolar
point and the solar elevation shown in the app can never disagree
(TEAM_SPLIT P5's "same source" rule), and it is ~3x faster than separate
subpt() calls.

Binary format (little-endian):
  header: '<8sH16sddI2f'
    magic      8s   b'LUNAEPH\\0'
    version    H    1
    site_id   16s   NUL-padded ASCII
    et_start   f64  TDB seconds past J2000
    step_s     f64  seconds between samples
    count      I    number of records
    site_lat   f32  site latitude (deg)
    site_lon   f32  site longitude (deg, -180..+180 east positive)
  record: '<8f' (32 bytes)
    sub_solar_lat, sub_solar_lon, sub_earth_lat, sub_earth_lon (deg)
    earth_dist_km, earth_ang_diam_deg, sun_elev_deg, earth_elev_deg

Record values are f32 for size; validation (verify_horizons.py) runs in
f64 in-memory and does not go through the file. A year of hourly samples
is ~280 KB/site; the full 18.6-year cycle hourly is ~5.2 MB/site.
"""
import argparse
import math
import struct
import sys
import time as time_mod
from pathlib import Path

from . import frames

ROOT = Path(__file__).resolve().parents[2]
SITES_FILE = ROOT / "clps" / "sites.json"
OUT_DIR = ROOT / "artifacts" / "ephemeris"

MAGIC = b"LUNAEPH\0"
VERSION = 1
HDR_FMT = "<8sH16sddI2f"
HDR_SIZE = struct.calcsize(HDR_FMT)
REC_FMT = "<8f"
REC_SIZE = struct.calcsize(REC_FMT)

# Lunar synodic month (constants.json cycles are draconic; synodic is the
# illumination period). 29.530588 Earth days.
SYNODIC_MONTH_S = 29.530588 * 86400.0
DRACONIC_YEARS = 18.6  # constants.json


def bake_site(site: dict, et_start: float, step_s: float, count: int,
              progress_every: int = 0) -> Path:
    """Bake one site. Returns the output path.

    Deterministic: no RNG, no threading, fixed iteration order. Running
    this twice with the same arguments produces byte-identical files,
    which is what P6's manifest needs.
    """
    frames.load_kernels()
    sid = site["id"]
    lat, lon = site["lat"], site["lon"]
    n = frames.surface_normal(lat, lon)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{sid}.bin"

    recs = bytearray()
    t0 = time_mod.monotonic()
    for i in range(count):
        et = et_start + i * step_s

        sun = frames.to_body_fixed("SUN", et)
        earth = frames.to_body_fixed("EARTH", et)

        sun_d = math.sqrt(sum(c * c for c in sun))
        earth_d = math.sqrt(sum(c * c for c in earth))
        sun_u = [c / sun_d for c in sun]
        earth_u = [c / earth_d for c in earth]

        ss_lat, ss_lon = frames.body_fixed_to_latlon(
            [c * frames.MOON_R_KM for c in sun_u])
        se_lat, se_lon = frames.body_fixed_to_latlon(
            [c * frames.MOON_R_KM for c in earth_u])

        # elevation = 90 - zenith_distance. (The first version had the
        # sign backwards: acos(dot) - 90 stored NEGATED elevations.)
        sun_elev = 90.0 - math.degrees(math.acos(
            max(-1.0, min(1.0, sum(n[i] * sun_u[i] for i in range(3))))))
        earth_elev = 90.0 - math.degrees(math.acos(
            max(-1.0, min(1.0, sum(n[i] * earth_u[i] for i in range(3))))))
        earth_ang = 2.0 * math.degrees(math.asin(frames.EARTH_R_KM / earth_d))

        recs += struct.pack(REC_FMT,
                            ss_lat, ss_lon, se_lat, se_lon,
                            earth_d, earth_ang, sun_elev, earth_elev)

        if progress_every and (i + 1) % progress_every == 0:
            el = time_mod.monotonic() - t0
            rate = (i + 1) / el if el > 0 else 0
            eta = (count - i - 1) / rate if rate > 0 else 0
            print(f"    {sid}: {i + 1}/{count}  ({eta:.0f}s left)")

    header = struct.pack(HDR_FMT, MAGIC, VERSION, sid.encode(), et_start,
                         step_s, count, lat, lon)
    out.write_bytes(header + recs)
    return out


def read_ephemeris(path: Path) -> dict:
    """Read a baked .bin back into numpy-free Python structures.

    Returns dict with 'header' fields and 'records' as a list of tuples:
    (ss_lat, ss_lon, se_lat, se_lon, dist_km, ang_diam_deg, sun_elev, earth_elev)
    """
    data = path.read_bytes()
    magic, ver, sid_b, et_start, step_s, count, lat, lon = \
        struct.unpack_from(HDR_FMT, data, 0)
    if magic != MAGIC:
        raise ValueError(f"{path}: bad magic {magic!r} — not a LUNAEPH file")
    if ver != VERSION:
        raise ValueError(f"{path}: unsupported version {ver}")
    recs = []
    off = HDR_SIZE
    for _ in range(count):
        recs.append(struct.unpack_from(REC_FMT, data, off))
        off += REC_SIZE
    return {
        "site_id": sid_b.rstrip(b"\0").decode(),
        "et_start": et_start,
        "step_s": step_s,
        "count": count,
        "site_lat": lat,
        "site_lon": lon,
        "records": recs,
    }


def load_sites() -> list:
    import json
    return json.loads(SITES_FILE.read_text())["sites"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bake LUNAPOLE ephemeris")
    ap.add_argument("--site", help="bake a single site id")
    ap.add_argument("--all", action="store_true", help="bake all sites")
    ap.add_argument("--start", default="2026-10-01 00:00:00",
                    help="UTC start (default: 2026-10-01)")
    ap.add_argument("--days", type=float, default=29.530588,
                    help="duration in Earth days (default: one synodic month)")
    ap.add_argument("--step-min", type=float, default=5.0,
                    help="sample step in minutes (default: 5)")
    ap.add_argument("--full-cycle", action="store_true",
                    help="bake the full 18.6-year draconic cycle at the "
                         "given step (use --step-min 60 or coarser)")
    args = ap.parse_args(argv)

    sites = load_sites()
    if args.site:
        sites = [s for s in sites if s["id"] == args.site]
        if not sites:
            print(f"unknown site id: {args.site}")
            return 2
    elif not args.all:
        sites = [s for s in sites if s["priority"] == "P1"]
        print(f"(no --site/--all given: baking the 3 P1-priority sites; "
              f"pass --all for all 6)")

    days = DRACONIC_YEARS * 365.25 if args.full_cycle else args.days
    step_s = args.step_min * 60.0
    count = int(days * 86400.0 / step_s) + 1
    et_start = frames.utc_to_et(args.start + " UTC")

    span_years = count * step_s / (86400.0 * 365.25)
    print(f"baking {len(sites)} site(s): {args.start} UTC + {days:.2f} d "
          f"@ {args.step_min:g} min  ({count} samples, {span_years:.2f} yr)")
    if args.full_cycle:
        print("  FULL 18.6-YEAR CYCLE — this is the honest PSR map span. "
              "If you ship 1 year instead, the UI must say so.")

    t0 = time_mod.monotonic()
    for site in sites:
        prog = 2000 if count > 10000 else 0
        out = bake_site(site, et_start, step_s, count, progress_every=prog)
        mb = out.stat().st_size / 1e6
        print(f"  {site['id']:<12} -> {out.relative_to(ROOT)}  ({mb:.2f} MB)")
    el = time_mod.monotonic() - t0
    print(f"done in {el:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
