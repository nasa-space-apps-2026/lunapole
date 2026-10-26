#!/usr/bin/env python3
"""Verify LUNAPOLE's horizon engine (P3): geometry, disc, Earth.

Run:  python3 verify/verify_horizon.py

This is the gate P3 must pass before P4 maps anything. It checks the three
claims the whole project rests on:

  1. **Curvature is 6x stronger than the original spec said.** 30 km → 259 m,
     100 km → 2877 m. The engine gets this from exact spherical geometry, and
     the closed-form helper is asserted against constants.json.
  2. **The far field can only LOWER the sky, never raise the terrain.** A
     longer ray may find a higher ridge; it can never find a lower horizon
     than the near-field run. If this fails there is a sign error (the
     "bright bias" the spec warns about).
  3. **The Sun is a disc, not a point.** At 1.54° maximum elevation and
     0.5334° diameter, the disc is a third of the whole range. A centre
     point exactly on a flat horizon must give 50 % of the disc visible.

Plus Earth: parallax ≤ 0.2590°, disc 1.902° mean, and the topocentric /
geocentric split agrees with the verified spherical formula in
constants.json.

Synthetic-terrain checks always run. Real-DEM checks are skipped with a
clear message when `artifacts/dem/*.tif` is absent (run scripts/crop_sites.py).
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
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

from lunapole import dem, earth, horizon, solar_disc  # noqa: E402

CONSTANTS = json.loads((ROOT / "clps" / "constants.json").read_text())
SITES = json.loads((ROOT / "clps" / "sites.json").read_text())["sites"]

failures = []
skips = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def skip(name, why):
    print(f"  [SKIP] {name}  {why}")
    skips.append(name)


def section(title):
    print(f"\n{'=' * 66}\n{title}\n{'=' * 66}")


# ---------------------------------------------------------------------------
# 1. constants and closed-form geometry
# ---------------------------------------------------------------------------
def verify_constants():
    section("constants + closed-form geometry")
    vals = {v["dist_km"]: v["h_sphere_m"]
            for v in CONSTANTS["CORRECTED_curvature_table"]["values"]}

    for km, want in [(5, 7.19), (30, 259.0), (50, 719.6), (100, 2877.1)]:
        got = float(horizon.curvature_drop_m(km * 1000.0))
        check(f"curvature at {km} km = {want:.2f} m", abs(got - want) < 0.5,
              f"{got:.2f} m (table {vals[km]})")

    # The spec's 42.2 m is the 12.1 km value, not 30 km — the trap the whole
    # project is built around. Assert both halves of that story.
    got_12 = float(horizon.curvature_drop_m(12100.0))
    got_30 = float(horizon.curvature_drop_m(30000.0))
    check("42.2 m belongs to 12.1 km, not 30 km",
          abs(got_12 - 42.2) < 0.5 and abs(got_30 - 42.2) > 150.0,
          f"12.1 km -> {got_12:.2f} m, 30 km -> {got_30:.2f} m")

    # W1: shadow length at the polar maximum.
    # constants.json quotes 37.20 x h, which is the 1.5400 deg rounding of the
    # obliquity; the exact value at 1.5424 deg is 37.138. Assert both, because
    # the 0.17 % gap is a rounding artifact worth owning rather than hiding.
    mult = horizon.shadow_length_m(1.0, 1.5424)
    check("shadow length at 1.5424 deg = 37.14 x h (exact)",
          abs(mult - 37.138) < 0.01, f"{mult:.3f} x h")
    check("the quoted 37.20 x h reproduces at 1.5400 deg",
          abs(horizon.shadow_length_m(1.0, 1.5400) - 37.20) < 0.01,
          f"{horizon.shadow_length_m(1.0, 1.5400):.3f} x h")
    check("shadow is infinite with the Sun below the horizon",
          math.isinf(horizon.shadow_length_m(1.0, -0.1)))

    # Elevation geometry reduces to the horizon dip on a flat sphere.
    for km in (5, 10, 25):
        d = km * 1000.0
        want = -math.degrees(d / (2.0 * dem.MOON_R_M))
        got = float(horizon.elevation_angle_deg(0.0, 0.0, d))
        # -d/2R is the small-angle form; exact spherical is -delta/2 too.
        check(f"flat sphere at {km} km sits {want:.4f} deg below tangent",
              abs(got - want) < 1e-3, f"{got:.4f} deg")

    # Hz distance table: a 500 m peak is visible from 41.7 km away.
    for row in CONSTANTS["horizon_distance_table"]:
        h = row["h_m"]
        want = row["horizon_km"]
        got = math.sqrt(2.0 * dem.MOON_R_M * h) / 1000.0
        check(f"horizon distance for h={h} m = {want} km",
              abs(got - want) < 0.05, f"{got:.2f} km")

    # solar_disc literals must match the verified constant file.
    solar = CONSTANTS["solar"]
    check("solar disc diameter matches constants.json",
          abs(solar_disc.SUN_DIAMETER_DEG - solar["apparent_diameter_deg"]) < 1e-12,
          f"{solar_disc.SUN_DIAMETER_DEG}")
    check("sun radius is half the diameter",
          abs(solar_disc.SUN_RADIUS_DEG - solar["apparent_diameter_deg"] / 2) < 1e-12)
    earth_c = CONSTANTS["earth"]["apparent_diameter_from_moon_deg"]
    check("Earth disc diameter matches constants.json",
          abs(solar_disc.EARTH_DIAMETER_DEG - earth_c) < 1e-12, f"{earth_c}")


# ---------------------------------------------------------------------------
# 2. synthetic terrain: azimuth convention, curvature, monotonicity
# ---------------------------------------------------------------------------
def _flat_dem(half_km=12.0, pix_m=10.0, height=0.0):
    n = int(2 * half_km * 1000 / pix_m)
    return dem.Dem.from_array(np.full((n, n), height, dtype=np.int16),
                              pix_m=pix_m)


def verify_flat_terrain():
    section("synthetic flat sphere — curvature end to end")
    d = _flat_dem(half_km=12.0, pix_m=10.0)
    prof = horizon.horizon_profile(d, lat_deg=-90.0, lon_deg=0.0,
                                   max_dist_km=10.0)

    spread = prof["elev_deg"].max() - prof["elev_deg"].min()
    check("flat terrain: every azimuth agrees (no azimuth artifacts)",
          spread < 1e-3, f"spread {spread:.2e} deg")
    # On a smooth sphere the highest terrain along any ray is the tangent
    # itself, i.e. the FIRST sample. The 10 km point sits 0.1649 deg BELOW it
    # — that dip is the curvature, and it is why a 30 km ridge needs 259 m of
    # height just to break even with the tangent plane.
    check("flat sphere horizon is the local tangent, not the far-field dip",
          abs(float(prof["elev_deg"].mean())) < 0.01,
          f"{prof['elev_deg'].mean():+.5f} deg")
    step_km = prof["step_m"] / 1000.0
    check("occluding sample is the nearest pixel (terrain only drops away)",
          np.allclose(prof["shadow_dist_km"], step_km, atol=0.002),
          f"{prof['shadow_dist_km'].min():.3f}..{prof['shadow_dist_km'].max():.3f} km")
    check("no gaps on a flat synthetic DEM",
          not np.any(prof["flags"] & horizon.FLAG_GAP))
    check("all bins reached the far field",
          np.all(prof["flags"] & horizon.FLAG_FAR))


def verify_ridge_azimuth():
    section("synthetic ridge — azimuth convention and obstacle distance")
    d = _flat_dem(half_km=12.0, pix_m=10.0)
    # +x in the projection is lon 90E; east (az=90) must run straight at it.
    col = (d.width // 2) + int(2000 / d.pix_m)
    d.values[:, col:] = 500
    d.valid = ((d.values >= dem.VALID_MIN_M)
               & (d.values <= dem.VALID_MAX_M))

    prof = horizon.horizon_profile(d, lat_deg=-90.0, lon_deg=0.0,
                                   max_dist_km=8.0)
    want = float(horizon.elevation_angle_deg(0.0, 500.0, 2000.0))

    h_east = float(horizon.horizon_at(prof, 90.0))
    h_west = float(horizon.horizon_at(prof, 270.0))
    check("ridge at az=90 raises the east horizon",
          abs(h_east - want) < 0.15, f"{h_east:.2f} deg (expected {want:.2f})")
    check("opposite azimuth stays at the tangent (flat sphere)",
          abs(h_west) < 0.02, f"{h_west:.3f} deg")
    dist_east = float(np.interp(90.0, prof["az_deg"], prof["shadow_dist_km"]))
    check("ridge distance reported as ~2 km",
          abs(dist_east - 2.0) < 0.15, f"{dist_east:.2f} km")
    near_90 = np.abs(prof["az_deg"] - 90.0) <= 1.0
    check("obstacle height is the ridge, not the site",
          np.allclose(prof["obstacle_height_m"][near_90], 500.0),
          f"{np.median(prof['obstacle_height_m'][near_90]):.0f} m")


def verify_far_field_monotonic(d):
    """Far field can only raise the horizon. Real terrain, all bins."""
    near, far, diff = horizon.compare_near_far(d, near_km=5.0, far_km=25.0)
    worst = float(np.min(diff))
    check("far-field horizon never drops below near-field (no bright bias)",
          worst > -1e-6, f"worst delta {worst:+.3e} deg")
    check("far field does raise some bins on real terrain",
          float(np.max(diff)) > 0.05,
          f"max gain {float(np.max(diff)):+.2f} deg, "
          f"{int(np.sum(diff > 0.01))}/{len(diff)} bins")


# ---------------------------------------------------------------------------
# 3. solar disc
# ---------------------------------------------------------------------------
def verify_solar_disc():
    section("extended solar disc — equal solid angle and penumbra")
    n = 4096
    r, _ = solar_disc.equal_solid_angle_disc(solar_disc.SUN_RADIUS_DEG, n)
    ratio = float(np.mean((r / solar_disc.SUN_RADIUS_DEG) ** 2))
    check("equal-solid-angle sampling: mean(r^2) = R^2/2",
          abs(ratio - 0.5) < 0.01, f"{ratio:.4f}")
    check("no sample outside the disc",
          float(r.max()) < solar_disc.SUN_RADIUS_DEG)

    flat = solar_disc.flat_horizon(0.0)
    m = solar_disc.sun_metrics(0.0, 90.0, flat)
    check("Sun centre on the horizon -> 50 % of the disc visible",
          abs(m["disc_fraction"] - 0.5) < 0.02, f"{m['disc_fraction']:.3f}")
    check("centre exactly on the horizon is not 'above' it",
          m["sun_above_horizon"] is False)
    # Flux is projected on a normal, so a horizontal panel under a Sun on the
    # horizon collects ~sin(0) = 0, NOT the visible fraction. That is the
    # physics the app has to show: half a disc of light at 0 deg elevation
    # still delivers almost no power.
    check("horizontal panel under a horizon-grazing Sun collects ~0 flux",
          m["incident_flux"] < 0.01, f"{m['incident_flux']:.4f}")

    mid = solar_disc.sun_metrics(45.0, 0.0, solar_disc.flat_horizon(-90.0))
    check("horizontal panel at 45 deg elevation collects sin(45) of full flux",
          abs(mid["incident_flux"] - math.sin(math.radians(45.0))) < 0.002,
          f"{mid['incident_flux']:.4f}")

    up = solar_disc.sun_metrics(solar_disc.SUN_RADIUS_DEG, 90.0, flat)
    down = solar_disc.sun_metrics(-solar_disc.SUN_RADIUS_DEG, 90.0, flat)
    check("disc fully clear when the limb just clears the horizon",
          up["disc_fraction"] > 0.98, f"{up['disc_fraction']:.3f}")
    check("disc fully hidden when the limb just dips below",
          down["disc_fraction"] < 0.02, f"{down['disc_fraction']:.3f}")
    check("full disc on the zenith gives flux 1.0",
          abs(solar_disc.sun_metrics(90.0, 0.0, solar_disc.flat_horizon(-90.0))
              ["incident_flux"] - 1.0) < 1e-4)

    # Monotonic penumbra: more elevation can never hide more of the disc.
    elevs = np.linspace(-0.5, 0.5, 41)
    fracs = [solar_disc.sun_metrics(float(e), 0.0, flat)["disc_fraction"]
             for e in elevs]
    check("disc fraction is monotonic in solar elevation",
          all(b >= a - 1e-9 for a, b in zip(fracs, fracs[1:])))

    # The pole's whole range is only 3.08 deg: the disc is 17 % of it.
    span = 2 * CONSTANTS["solar"]["max_elevation_at_pole_deg"]
    share = 2 * solar_disc.SUN_RADIUS_DEG / span
    check("solar disc spans >15 % of the polar elevation range",
          share > 0.15, f"{share * 100:.1f} %")

    # Oriented panel: pointing 30 deg off the Sun loses cos(30).
    panel = solar_disc.enu_from_elev_az(60.0, 180.0)
    oriented = solar_disc.sun_metrics(90.0, 0.0, flat, panel_normal=panel)
    check("oriented panel flux follows the incidence angle",
          abs(oriented["incident_flux"] - math.cos(math.radians(30.0))) < 0.01,
          f"{oriented['incident_flux']:.3f}")


# ---------------------------------------------------------------------------
# 4. Earth
# ---------------------------------------------------------------------------
def verify_earth_formula():
    section("Earth — verified spherical formula vs constant table")
    for row in CONSTANTS["earth_elevation_verified"]["values"]:
        got = earth.spherical_elevation_deg(row["site_lat"], 0.0,
                                            row["sub_earth_lat"], 0.0)
        check(f"earth elev at lat {row['site_lat']}, sub {row['sub_earth_lat']}"
              f" = {row['elev_deg']:.2f} deg",
              abs(got - row["elev_deg"]) < 0.01, f"{got:.3f} deg")

    check("Earth disc is 3.56x the Sun",
          abs(solar_disc.EARTH_DIAMETER_DEG / solar_disc.SUN_DIAMETER_DEG - 3.56)
          < 0.01,
          f"{solar_disc.EARTH_DIAMETER_DEG / solar_disc.SUN_DIAMETER_DEG:.3f}x")


def verify_earth_kernels():
    section("Earth — parallax and disc against the real ephemeris")
    kernels = ROOT / "data" / "kernels"
    needed = ["naif0012.tls", "pck00010.tpc", "de440s.bsp",
              "moon_pa_de440_200625.bpc"]
    missing = [k for k in needed if not (kernels / k).exists()]
    if missing:
        skip("Earth parallax vs kernels", f"missing {', '.join(missing)}")
        return

    site = next(s for s in SITES if s["id"] == "shackleton")
    et = frames_et("2026-10-12 00:00:00 UTC")
    lat, lon = site["lat"], site["lon"]
    height = 1515.0  # verified Shackleton rim elevation (VERIFICATION.md)

    topo, az = earth.topocentric_elev_az(et, lat, lon, height)
    geo = earth.geocentric_elevation_deg(et, lat, lon)
    par = earth.parallax_deg(et, lat, lon, height)
    diam = earth.angular_diameter_deg(et, lat, lon, height)

    check("topocentric - geocentric = reported parallax",
          abs((topo - geo) - par) < 1e-12, f"{par:+.4f} deg")
    check("parallax within the verified 0.2590 deg maximum",
          abs(par) <= CONSTANTS["parallax"]["max_sub_lunar_parallax_deg"] + 1e-6,
          f"|{par:.4f}| deg")
    check("parallax is a real correction (>0.1 deg at Shackleton)",
          abs(par) > 0.1, f"{abs(par):.4f} deg")
    check("Earth angular diameter in verified 1.802..2.012 deg range",
          1.80 <= diam <= 2.02, f"{diam:.4f} deg")
    check("Earth azimuth is in range",
          0.0 <= az < 360.0, f"{az:.2f} deg")

    # Distance from the site must be a few thousand km smaller when the site
    # is on the near side of the Moon; never negative, never absurd.
    dist = earth.distance_km(et, lat, lon, height)
    check("Earth distance plausible (356 500..406 700 km)",
          356_000 <= dist <= 407_000, f"{dist:.0f} km")


def frames_et(iso_utc):
    """UTC string -> ET without importing frames at module import time."""
    from lunapole import frames
    return frames.utc_to_et(iso_utc)


# ---------------------------------------------------------------------------
# 5. real DEMs
# ---------------------------------------------------------------------------
def real_crops():
    d = dem.DEM_DIR
    return sorted(p.stem for p in d.glob("*.tif")) if d.exists() else []


def verify_real_site(site_id):
    d = dem.Dem.for_site(site_id)
    prof = horizon.horizon_profile(d, max_dist_km=25.0)
    elev = prof["elev_deg"]

    check(f"{site_id}: 720 bins emitted", prof["az_bins"] == 720,
          f"{prof['az_bins']}")
    check(f"{site_id}: all elevations finite and within +-90 deg",
          np.all(np.isfinite(elev)) and np.all(np.abs(elev) <= 90.0),
          f"{elev.min():+.2f}..{elev.max():+.2f} deg")
    check(f"{site_id}: site elevation matches the DEM",
          abs(float(d.elevation_at(prof["site_lat"], prof["site_lon"]))
              - prof["site_h_m"]) < 1e-6,
          f"{prof['site_h_m']:.0f} m")
    check(f"{site_id}: terrain horizon is not a flat sphere",
          float(elev.max() - elev.min()) > 2.0,
          f"spread {elev.max() - elev.min():.2f} deg")
    check(f"{site_id}: occluding distances inside the crop",
          np.all(prof["shadow_dist_km"] <= prof["coverage_km"] + 0.1),
          f"max {prof['shadow_dist_km'].max():.2f} km")

    verify_far_field_monotonic(d)

    # Determinism: the bake must be byte-identical, P6's manifest depends on it.
    with tempfile.TemporaryDirectory() as tmp:
        out1, _ = horizon.bake_site(d, site_id, out_dir=tmp, max_dist_km=5.0)
        out2, _ = horizon.bake_site(d, site_id, out_dir=tmp, max_dist_km=5.0)
        check(f"{site_id}: bake is deterministic (byte-identical)",
              out1.read_bytes() == out2.read_bytes(),
              f"{out1.stat().st_size} B")

        prof_rt = horizon.read_horizon(out1)
        check(f"{site_id}: artifact round-trips through read_horizon",
              np.allclose(prof_rt["elev_deg"], horizon.horizon_profile(
                  d, max_dist_km=5.0)["elev_deg"]),
              f"{prof_rt['site_id']}")

    # Terrain-horizon sanity for the disc: just above the highest ridge the
    # Sun is fully clear; just below the lowest horizon it is fully hidden.
    horizon_fn = lambda az: horizon.horizon_at(prof, az)  # noqa: E731
    i_max, i_min = int(np.argmax(elev)), int(np.argmin(elev))
    clear = solar_disc.sun_metrics(float(elev[i_max] + 0.5),
                                   float(prof["az_deg"][i_max]), horizon_fn)
    dark = solar_disc.sun_metrics(float(elev[i_min] - 0.5),
                                  float(prof["az_deg"][i_min]), horizon_fn)
    check(f"{site_id}: Sun above the highest ridge is fully visible",
          clear["disc_fraction"] > 0.99, f"{clear['disc_fraction']:.3f}")
    check(f"{site_id}: Sun below the lowest horizon is fully hidden",
          dark["disc_fraction"] < 0.01, f"{dark['disc_fraction']:.3f}")

    return prof


def verify_real():
    section("real DEM crops — profiles, monotonicity, determinism")
    crops = real_crops()
    if not crops:
        skip("real DEM checks", "no artifacts/dem/*.tif — run scripts/crop_sites.py")
        return
    for sid in crops:
        print(f"\n  -- {sid} --")
        try:
            prof = verify_real_site(sid)
            print(f"     {horizon.summary(prof)}")
        except Exception as exc:                      # noqa: BLE001
            check(f"{sid}: horizon profile", False, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
def main():
    print("LUNAPOLE P3 — horizon engine verification")
    verify_constants()
    verify_flat_terrain()
    verify_ridge_azimuth()
    verify_solar_disc()
    verify_earth_formula()
    verify_earth_kernels()
    verify_real()

    print()
    if skips:
        print(f"Skipped: {len(skips)} group(s): {', '.join(skips)}")
    if failures:
        print(f"FAILED: {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All horizon checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
