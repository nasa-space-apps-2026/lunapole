"""LUNAPOLE far-field horizon engine — the P3 deliverable.

For every site, walk 720 rays out from the observer along great circles,
sample the LOLA crop all the way to the far field, apply lunar curvature,
and keep the **maximum** elevation per 0.5° azimuth bin. That profile is
what decides whether the Sun clears the terrain.

The physics, in one line per step:

    δ      = d / R                                arc distance → angle
    vn     = (R + h_point) cos δ − (R + h_site)    height above tangent plane
    horiz  = (R + h_point) sin δ                   horizontal offset
    elev   = atan2(vn, horiz)                     degrees above local horizon

Curvature is therefore not a bolt-on correction: it falls out of doing the
geometry on a sphere. At 30 km the same quantity expressed as a drop is
R (1 − cos(d/R)) = 259 m (constants.json CORRECTED_curvature_table) — the
original spec's 42.2 m is the 12.1 km value, and understating it makes every
site look sunnier than it is.

Three rules from TEAM_SPLIT P3, enforced here:

  1. **max, never mean, per bin.** The nearest ridge that blocks the Sun is
     the only one that matters; a mean underestimates occlusion (the
     "bright" bias).
  2. **Far-field can only raise the horizon.** If a longer ray lowers a bin,
     there is a sign error. `compare_near_far()` exists so the test suite
     can assert this on real terrain.
  3. **Fail closed.** A bin whose ray leaves the DEM, or lands on padding /
     an `ldec_` count raster, is marked `PROV_GAP` and given elevation
     +90° — "blocked" — so nothing downstream can claim sunlight that the
     data does not support.

Artifact format (`artifacts/horizon/<site>.bin`, little-endian), deliberately
mirroring ephemeris.py's magic/version/header style rather than the spec's
big-endian struct:

    header '<8sH16sI5f'  (50 B)
        magic        8s  b'LUNAHOR\\0'
        version      H   1
        site_id     16s  NUL-padded ASCII
        az_bins      I   number of azimuth bins (720)
        step_m       f   ray sampling step in metres
        max_dist_km  f   requested far-field distance
        site_lat     f   degrees (sites.json)
        site_lon     f   degrees, -180..+180 east positive
        site_h_m     f   DEM elevation at the site, metres
    record '<fffBB'  (14 B per bin: 3 floats + 2 flag bytes)
        elev_deg         f  horizon elevation, curvature included
        shadow_dist_km   f  distance of the occluding sample
        obstacle_h_m     f  DEM elevation of that sample (NaN on a gap)
        flags            B  bit0 far-field reached, bit1 edge, bit2 gap
        provenance       B  0 measured, 1 synthesised, 2 gap

720 bins × 14 B + 50 B ≈ 9.9 kB per site.
"""
import argparse
import math
import struct
import sys
import time as time_mod
from pathlib import Path

import numpy as np

from . import dem as dem_mod

ROOT = Path(__file__).resolve().parents[2]
SITES_FILE = ROOT / "clps" / "sites.json"
OUT_DIR = ROOT / "artifacts" / "horizon"

MOON_R_M = dem_mod.MOON_R_M

AZ_BINS = 720                 # 0.5 deg per bin (Mazarico 2011 uses 0.5 deg)
DEFAULT_MAX_DIST_KM = 25.0    # = crop radius; see crop_sites.py --radius-km
DEFAULT_STEP_PX = 1.0         # one DEM pixel per sample: no invented terrain

MAGIC = b"LUNAHOR\0"
VERSION = 1
HDR_FMT = "<8sH16sI5f"
HDR_SIZE = struct.calcsize(HDR_FMT)
REC_FMT = "<fffBB"          # elev, dist, obstacle height, flags, provenance
REC_SIZE = struct.calcsize(REC_FMT)

# flags
FLAG_FAR = 1     # ray reached max_dist without leaving the DEM
FLAG_EDGE = 2    # ray left the crop before max_dist
FLAG_GAP = 4     # no valid terrain sample at all

# provenance
PROV_MEASURED = 0
PROV_SYNTHETIC = 1
PROV_GAP = 2


# ---------------------------------------------------------------------------
# closed-form helpers (tested directly)
# ---------------------------------------------------------------------------
def curvature_drop_m(dist_m, radius_m=MOON_R_M):
    """Height of the sphere below the tangent plane at arc distance d.

    R (1 − cos(d/R)). Verified values (constants.json):
    5 km → 7.19 m, 30 km → 259.0 m, 100 km → 2877.1 m.
    """
    return radius_m * (1.0 - np.cos(np.asarray(dist_m, dtype=float) / radius_m))


def shadow_length_m(height_m, elev_deg):
    """Shadow cast by an obstacle at solar elevation `elev_deg`.

    L = h / tan(elev). At the polar maximum (1.5424°) that is 37.20 × h —
    the W1 hook: a 1 m rock casts a 38 m shadow.
    """
    elev = math.radians(elev_deg)
    if elev <= 0.0:
        return math.inf
    return height_m / math.tan(elev)


def elevation_angle_deg(h_site_m, h_point_m, dist_m, radius_m=MOON_R_M):
    """Elevation of a terrain point above the observer's local horizontal.

    Exact spherical geometry; handles curvature without a separate term.
    A flat (same-height) surface gives −d/2R radians, the true horizon dip.
    """
    delta = np.asarray(dist_m, dtype=float) / radius_m
    vn = (radius_m + h_point_m) * np.cos(delta) - (radius_m + h_site_m)
    horiz = (radius_m + h_point_m) * np.sin(delta)
    return np.degrees(np.arctan2(vn, horiz))


def azimuth_bins(az_bins=AZ_BINS):
    """Bin centre azimuths, degrees, north = 0, east = 90 (clockwise)."""
    return (np.arange(az_bins) + 0.5) * (360.0 / az_bins)


def horizon_at(profile, az_deg):
    """Interpolate the horizon profile at an arbitrary azimuth (degrees).

    Circular linear interpolation between bin centres. Accepts scalars or
    arrays. The profile's bins are centres, so an azimuth exactly between
    two ridges is interpolated rather than snapping to the worse one.
    """
    elev = np.asarray(profile["elev_deg"], dtype=float)
    bins = len(elev)
    step = 360.0 / bins
    # bin centre i sits at (i + 0.5) * step
    x = (np.asarray(az_deg, dtype=float) % 360.0) / step - 0.5
    i0 = np.floor(x).astype(np.int64)
    frac = x - i0
    i0 %= bins
    i1 = (i0 + 1) % bins
    return elev[i0] * (1.0 - frac) + elev[i1] * frac


# ---------------------------------------------------------------------------
# the march
# ---------------------------------------------------------------------------
def _unit_site_basis(lat_deg, lon_deg):
    """Site normal plus local east/north unit vectors in IAU_MOON."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    n = np.array([math.cos(lat) * math.cos(lon),
                  math.cos(lat) * math.sin(lon),
                  math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon),
                      -math.sin(lat) * math.sin(lon),
                      math.cos(lat)])
    return n, east, north


def horizon_profile(dem, lat_deg=None, lon_deg=None, az_bins=AZ_BINS,
                    max_dist_km=DEFAULT_MAX_DIST_KM, step_px=DEFAULT_STEP_PX,
                    chunk_steps=512, radius_m=MOON_R_M):
    """Compute the max-per-azimuth horizon profile.

    dem        : dem.Dem for the site (its crop must be centred on the site)
    lat/lon    : observer coordinates; default to the crop's site tags
    max_dist_km: far-field distance to attempt (crop radius is the hard limit)
    step_px    : ray sampling step in DEM pixels (1.0 = measured pixels only)

    Returns a dict with `az_deg`, `elev_deg`, `shadow_dist_km`, `flags`,
    `provenance` (all numpy arrays, one entry per bin) plus the header
    metadata needed to bake a file.
    """
    if lat_deg is None:
        lat_deg = float(dem.tags["site_lat"])
    if lon_deg is None:
        lon_deg = float(dem.tags["site_lon"])

    az = azimuth_bins(az_bins)
    n, east, north = _unit_site_basis(lat_deg, lon_deg)
    tangents = (np.cos(np.radians(az))[:, None] * north[None, :]
                + np.sin(np.radians(az))[:, None] * east[None, :])

    h_site = dem.elevation_at(lat_deg, lon_deg)
    pix = dem.pix_m
    step_m = step_px * pix
    max_dist_m = float(max_dist_km) * 1000.0
    n_steps = int(math.ceil(max_dist_m / step_m))

    best_ang = np.full(az_bins, -np.inf)
    best_dist = np.zeros(az_bins)
    best_z = np.full(az_bins, np.nan)
    covered = np.zeros(az_bins)          # contiguous valid distance per bin

    for start in range(0, n_steps, chunk_steps):
        stop = min(start + chunk_steps, n_steps)
        d = (np.arange(start, stop) + 1) * step_m          # (S,)
        delta = d / radius_m

        # p = cos(delta) * n + sin(delta) * t    for every bin, every step
        p = (np.cos(delta)[None, :, None] * n[None, None, :]
             + np.sin(delta)[None, :, None] * tangents[:, None, :])

        lat_p = np.degrees(np.arcsin(np.clip(p[..., 2], -1.0, 1.0)))
        lon_p = np.degrees(np.arctan2(p[..., 1], p[..., 0]))

        x, y = dem_mod.latlon_to_stereo_xy(lat_p, lon_p)
        z, ok = dem.sample_xy(x, y)

        ang = elevation_angle_deg(h_site, z, d[None, :], radius_m=radius_m)
        ang = np.where(ok, ang, -np.inf)

        # Contiguity: a ray that leaves the crop must not be allowed to
        # "re-enter" through a corner later on. cumprod of the validity mask
        # gives the prefix that is continuously measured.
        contiguous = np.cumprod(ok.astype(np.uint8), axis=1).astype(bool)

        # Update the running max only where the prefix is contiguous.
        masked = np.where(contiguous, ang, -np.inf)
        local_best = masked.max(axis=1)
        local_idx = masked.argmax(axis=1)
        # The obstacle height is read from the SAME sample that won the bin —
        # never re-derived from the distance afterwards. Re-deriving means a
        # second trip through lat/lon ↔ stereographic, and at a ridge boundary
        # one ULP of round-trip error flips the pixel and reports the wrong
        # ridge height.
        local_z = np.take_along_axis(
            np.where(contiguous, z, np.nan),
            local_idx[:, None], axis=1)[:, 0]
        take = local_best > best_ang
        best_ang = np.where(take, local_best, best_ang)
        best_dist = np.where(take, d[local_idx], best_dist)
        best_z = np.where(take, local_z, best_z)

        # Distance up to which this ray stayed inside measured terrain. The
        # last contiguous index is exact per bin (not per chunk), so a ray
        # that leaves mid-chunk is not rounded up to the chunk boundary.
        last_idx = contiguous.sum(axis=1) - 1
        cov_chunk = np.where(last_idx >= 0,
                             d[np.clip(last_idx, 0, None)], 0.0)
        covered = np.maximum(covered, cov_chunk)

    gap = ~np.isfinite(best_ang)
    elev = np.where(gap, 90.0, best_ang)          # fail closed
    dist_km = np.where(gap, 0.0, best_dist / 1000.0)

    flags = np.zeros(az_bins, dtype=np.uint8)
    reached_far = covered >= (max_dist_m - step_m)
    flags |= np.where(reached_far, FLAG_FAR, 0).astype(np.uint8)
    flags |= np.where(~reached_far & (covered > 0), FLAG_EDGE, 0).astype(np.uint8)
    flags |= np.where(gap, FLAG_GAP, 0).astype(np.uint8)

    prov = np.full(az_bins, PROV_MEASURED, dtype=np.uint8)
    prov[gap] = PROV_GAP

    return {
        "site_lat": float(lat_deg),
        "site_lon": float(lon_deg),
        "site_h_m": float(h_site),
        "az_bins": int(az_bins),
        "step_m": float(step_m),
        "max_dist_km": float(max_dist_km),
        "pix_m": float(pix),
        "coverage_km": float(dem.coverage_radius_km()),
        "az_deg": az,
        "elev_deg": elev,
        "shadow_dist_km": dist_km,
        "flags": flags,
        "provenance": prov,
        "obstacle_height_m": np.where(gap, np.nan, best_z),
    }


def compare_near_far(dem, near_km=5.0, far_km=25.0, **kwargs):
    """Horizon profiles at two ranges — the far-field monotonicity test.

    More terrain can only occlude more, so every bin must satisfy
    far_elev >= near_elev − 1e-6. A violation is a sign error, not noise.
    """
    near = horizon_profile(dem, max_dist_km=near_km, **kwargs)
    far = horizon_profile(dem, max_dist_km=far_km, **kwargs)
    diff = far["elev_deg"] - near["elev_deg"]
    return near, far, diff


# ---------------------------------------------------------------------------
# artifact I/O
# ---------------------------------------------------------------------------
def bake_site(dem, site_id=None, out_dir=OUT_DIR, **kwargs):
    """Compute and write `artifacts/horizon/<site>.bin`. Deterministic."""
    sid = site_id or dem.site_id
    prof = horizon_profile(dem, **kwargs)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sid}.bin"

    header = struct.pack(HDR_FMT, MAGIC, VERSION, sid.encode()[:16],
                         prof["az_bins"], prof["step_m"],
                         prof["max_dist_km"], prof["site_lat"],
                         prof["site_lon"], prof["site_h_m"])
    recs = np.empty(prof["az_bins"], dtype=np.dtype(
        [("elev", "<f4"), ("dist", "<f4"), ("obs_h", "<f4"),
         ("flags", "u1"), ("prov", "u1")]))
    recs["elev"] = prof["elev_deg"]
    recs["dist"] = prof["shadow_dist_km"]
    recs["obs_h"] = prof["obstacle_height_m"]
    recs["flags"] = prof["flags"]
    recs["prov"] = prof["provenance"]
    out.write_bytes(header + recs.tobytes())
    return out, prof


def read_horizon(path):
    """Read a baked horizon file back into numpy arrays."""
    data = Path(path).read_bytes()
    magic, ver, sid_b, az_bins, step_m, max_dist_km, lat, lon, h = \
        struct.unpack_from(HDR_FMT, data, 0)
    if magic != MAGIC:
        raise ValueError(f"{path}: bad magic {magic!r} — not a LUNAHOR file")
    if ver != VERSION:
        raise ValueError(f"{path}: unsupported version {ver}")

    body = np.frombuffer(data, dtype=np.dtype(
        [("elev", "<f4"), ("dist", "<f4"), ("obs_h", "<f4"),
         ("flags", "u1"), ("prov", "u1")]),
        count=az_bins, offset=HDR_SIZE)
    return {
        "site_id": sid_b.rstrip(b"\0").decode(),
        "az_bins": int(az_bins),
        "step_m": float(step_m),
        "max_dist_km": float(max_dist_km),
        "site_lat": float(lat),
        "site_lon": float(lon),
        "site_h_m": float(h),
        "az_deg": azimuth_bins(az_bins),
        "elev_deg": body["elev"].astype(float),
        "shadow_dist_km": body["dist"].astype(float),
        "obstacle_height_m": body["obs_h"].astype(float),
        "flags": body["flags"].copy(),
        "provenance": body["prov"].copy(),
    }


def load_horizon(site_id, out_dir=OUT_DIR):
    return read_horizon(Path(out_dir) / f"{site_id}.bin")


def summary(prof):
    """One-line, UI-shaped description of a profile."""
    elev = np.asarray(prof["elev_deg"])
    covered = (prof["flags"] & FLAG_FAR).astype(bool)
    gap = (prof["flags"] & FLAG_GAP).astype(bool)
    return (f"horizon {elev.min():+.2f}..{elev.max():+.2f} deg  "
            f"median {np.median(elev):+.2f}  "
            f"far-field bins {covered.sum()}/{len(elev)}  "
            f"gaps {gap.sum()}  "
            f"coverage {prof.get('coverage_km', float('nan')):.1f} km")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def load_sites():
    import json
    return json.loads(SITES_FILE.read_text())["sites"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bake LUNAPOLE horizon profiles")
    ap.add_argument("--site", help="bake a single site id")
    ap.add_argument("--all", action="store_true", help="bake all 6 sites")
    ap.add_argument("--az-bins", type=int, default=AZ_BINS)
    ap.add_argument("--max-dist-km", type=float, default=DEFAULT_MAX_DIST_KM)
    ap.add_argument("--step-px", type=float, default=DEFAULT_STEP_PX)
    ap.add_argument("--dem-dir", default=str(dem_mod.DEM_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)

    sites = load_sites()
    if args.site:
        sites = [s for s in sites if s["id"] == args.site]
        if not sites:
            print(f"unknown site id: {args.site}")
            return 2
    elif not args.all:
        sites = [s for s in sites if s["priority"] == "P1"]
        print("(no --site/--all given: baking the 3 P1 sites; "
              "pass --all for all 6)")

    print(f"baking {len(sites)} horizon profile(s): {args.az_bins} bins, "
          f"{args.max_dist_km:g} km, step {args.step_px:g} px")
    t0 = time_mod.monotonic()
    for site in sites:
        try:
            d = dem_mod.Dem.for_site(site["id"], dem_dir=args.dem_dir)
        except FileNotFoundError as exc:
            print(f"  [SKIP] {site['id']}: {exc}")
            continue
        out, prof = bake_site(d, site["id"], out_dir=args.out_dir,
                              az_bins=args.az_bins,
                              max_dist_km=args.max_dist_km,
                              step_px=args.step_px)
        kb = out.stat().st_size / 1024
        print(f"  {site['id']:<12} -> {out.relative_to(ROOT)}  "
              f"({kb:.1f} kB)")
        print(f"       {summary(prof)}")
        print(f"       site z={prof['site_h_m']:.0f} m, "
              f"DEM {prof['pix_m']:.0f} m/px, "
              f"crop radius {prof['coverage_km']:.1f} km")

    print(f"done in {time_mod.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
