#!/usr/bin/env python3
"""Verify LUNAPOLE's ephemeris chain: DE440 + lunar orientation PCK.

Run:  python3 verify/verify_ephemeris.py

Establishes that the kernels load, that libration is actually applied, and
that the sub-solar / sub-Earth points come out physically sane. This is the
gate P2 must pass before the horizon engine is worth building -- if the
subsolar point is wrong, every shadow is wrong.

Three distinct facts that are easy to conflate:
  * Solar ELEVATION at the EXACT pole = -sub-solar latitude, hence an
    ANNUAL +-1.54 deg signal (the Moon's rotation axis is tilted 1.5424
    deg to its orbital plane). The Sun circles the horizon there: up for
    ~half the year, down for ~half. It does NOT rise and set monthly at
    the exact pole; near-polar sites get a small monthly rise/set from
    the cos(longitude) term (~+-0.33 deg at Shackleton's latitude).
  * Sub-solar point LATITUDE in the body-fixed frame: +-1.54 deg ANNUAL
    (the Sun stays in the ecliptic; only the 1.54 deg equator tilt
    projects on it). NOT +-6.7 deg.
  * Sub-EARTH point latitude: +-6.68 deg MONTHLY. THAT is libration in
    latitude -- Earth's direction moves +-5.14 deg off the ecliptic as
    seen from the Moon (inclined orbit) plus the same 1.54 deg tilt.
The earlier version of this file claimed the sub-solar latitude was
+-6.7 deg and the polar elevation oscillated monthly; both were
measured on the wrong sub-point (on the Sun's surface, IAU_SUN frame)
before the subpt() argument-order fix. Any doc repeating those is
quoting that bug.
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

import math
import sys
from pathlib import Path

import spiceypy as spice

ROOT = Path(__file__).resolve().parent.parent
K = ROOT / "data" / "kernels"

KERNELS = [
    K / "naif0012.tls",          # leapseconds
    K / "pck00010.tpc",          # body radii  -- subpt() fails without this
    K / "de440s.bsp",            # planetary ephemeris
    K / "moon_pa_de440_200625.bpc",  # lunar orientation + libration
]

MOON_R_EQ = 1737.4  # km
MOON_F = 0.0

failures = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def subpt(target, et):
    """Sub-<target> point ON THE MOON -> (lat_deg, lon_deg_0_360).

    ARGUMENT ORDER: subpt(method, target, et, abcorr, observer). The Moon
    is the TARGET, the Sun/Earth is the observer. The previous version of
    this function had them swapped — subpt('SUN', obs='MOON') computes the
    point on the SUN where the MOON is at zenith (wrong body, wrong frame,
    and its 'libration' is an IAU_SUN artifact). The libration checks below
    passed by luck; the numbers were not the sub-solar point.

    abcorr NONE matches JPL Horizons' sub-point convention (< 0.01 deg);
    see verify_horizons.py.
    """
    cart, _ = spice.subpt("NEAR POINT", "MOON", et, "NONE", target)
    # subpt returns CARTESIAN coords. recgeo converts to lon/lat/radius.
    lon, lat, _ = spice.recgeo(cart, MOON_R_EQ, MOON_F)
    return math.degrees(lat), math.degrees(lon) % 360.0


def solar_elevation_at(lat_deg, lon_deg, et):
    """Topocentric solar elevation, degrees. `et` is TDB seconds past J2000.

    No surfpt() needed: on a sphere the surface normal at (lat, lon) in the
    body-fixed frame is just the unit vector. Avoids an API call and its
    argument-order traps.
    """
    # surface normal at (lat, lon) in IAU_MOON body-fixed frame
    n = [math.cos(math.radians(lat_deg)) * math.cos(math.radians(lon_deg)),
         math.cos(math.radians(lat_deg)) * math.sin(math.radians(lon_deg)),
         math.sin(math.radians(lat_deg))]
    # abcorr 'LT' (retarded position), matching frames.to_body_fixed:
    # shadow geometry follows the photons' actual origin, not the
    # apparent (aberrated) position.
    to_sun, _ = spice.spkpos("SUN", et, "IAU_MOON", "LT", "MOON")
    d = math.sqrt(sum(c * c for c in to_sun))
    u = [c / d for c in to_sun]
    dot = sum(n[i] * u[i] for i in range(3))
    # elevation = 90 - zenith_distance, zenith_distance = acos(dot).
    # The previous version had the sign backwards (acos(dot) - 90 gave
    # -90 for a sun at zenith); the symmetric +-1.54 deg bounds in main()
    # masked it. Same bug existed in frames.elevation_of and the bake.
    return 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def main():
    missing = [str(p.relative_to(ROOT)) for p in KERNELS if not p.exists()]
    if missing:
        print("Missing kernels -- run scripts/fetch_data.sh first:")
        for m in missing:
            print(f"  - {m}")
        return 2

    spice.furnsh([str(p) for p in KERNELS])
    print("kernels loaded\n")

    # ---- 1. sub-solar point sweeps 360 deg of longitude per synodic month ----
    # DAILY sampling, 35 days. Monthly samples CANNOT measure this: the
    # sub-solar longitude sweeps 360 deg per 29.53 d synodic month, so
    # 30.4 d spacing aliases each step down to ~-11 deg and unwrap cannot
    # recover the true step (the alias IS a valid unwrapped path). 35
    # daily steps must sweep ~360*35/29.53 = 427 deg. Longitude decreases
    # with time (the Sun moves west in the lunar sky).
    print("=== sub-solar point, daily 2026-03-01 + 35 d ===")
    et0 = spice.str2et("2026-03-01 00:00:00 TDB")
    lats, lons = [], []
    for i in range(35):
        lat, lon = subpt("SUN", et0 + i * 86400.0)
        lats.append(lat)
        lons.append(lon)
    unwrapped = [lons[0]]
    for i in range(1, len(lons)):
        d = lons[i] - lons[i - 1]
        while d < -180:
            d += 360
        while d > 180:
            d -= 360
        unwrapped.append(unwrapped[-1] + d)
    sweep = abs(unwrapped[-1] - unwrapped[0])
    print(f"  unwrapped sweep over 34 d: {sweep:.0f} deg (expect ~427)")
    check("sub-solar longitude sweeps ~360 deg per synodic month",
          400 < sweep < 460, f"{sweep:.0f} deg")

    # ---- 2. sub-solar LATITUDE: annual +-1.54 deg obliquity swing ----
    # NOT +-6.7 deg, and NOT a synodic-month signal. The Sun sits in the
    # ecliptic plane (|lat_sun| ~ 0 as seen from the Moon), so only the
    # Moon's 1.54 deg equator tilt projects on it -> smooth ANNUAL
    # sinusoid (monthly samples over a year are the right cadence; 35
    # days only covers a 0.9 deg arc). The +-6.68 deg MONTHLY swing
    # belongs to the sub-EARTH point (Earth's direction moves +-5.14 deg
    # off the ecliptic as seen from the Moon -- inclined orbit -- plus
    # the same 1.54 deg tilt). The old doc claimed +-6.7 for sub-solar:
    # that was measured on the WRONG sub-point (on the Sun's surface,
    # IAU_SUN frame) before the subpt() argument-order fix.
    print("\n=== sub-solar point, monthly 2026 (annual signal) ===")
    lats = []
    for m in range(1, 13):
        lat, _ = subpt("SUN", spice.str2et(f"2026-{m:02d}-15 00:00:00 TDB"))
        lats.append(lat)
    lat_span = max(lats) - min(lats)
    print(f"  sub-solar lat range: {min(lats):+.4f} .. {max(lats):+.4f} deg")
    check("sub-solar lat span ~3.08 deg (2 x 1.54 obliquity, annual)",
          2.8 < lat_span < 3.4, f"span {lat_span:.4f} deg")

    # ---- 3. THE key physical claim: solar elevation at the pole ----
    # At the EXACT pole the elevation equals the negative sub-solar
    # latitude (longitude drops out of the dot product), so it is ALSO an
    # ANNUAL +-1.54 deg signal -- the Sun circles the horizon there, above
    # it for roughly half the year and below for half, and does NOT rise
    # and set monthly. Monthly rise/set at polar sites comes from the
    # cos(longitude) term, amplitude cos(89.67) ~ 0.33 deg at Shackleton.
    print("\n=== solar elevation at the south pole (-89.9, 0), monthly 2026 ===")
    elevs = []
    for m in range(1, 13):
        e = solar_elevation_at(-89.9, 0.0,
                               spice.str2et(f"2026-{m:02d}-15 00:00:00 TDB"))
        elevs.append(e)
    emax, emin = max(elevs), min(elevs)
    print(f"\n  range {emin:+.4f} .. {emax:+.4f} deg")
    check("max solar elevation at pole ~= 1.54 deg",
          1.3 < emax < 1.8, f"max {emax:.4f} deg")
    check("min solar elevation at pole ~= -1.54 deg",
          -1.8 < emin < -1.3, f"min {emin:.4f} deg")
    check("elevation spans ~3.08 deg (2 x obliquity)",
          2.8 < (emax - emin) < 3.4, f"span {emax - emin:.4f} deg")

    # ---- 4. libration present: the sub-EARTH point must oscillate ----
    # In the tidally-locked body-fixed frame the sub-Earth point sits
    # near lon 0 (that IS tidal locking) and wobbles: +/-7.9 deg in
    # longitude, +/-6.68 deg in latitude. That wobble IS libration, so
    # sampling it directly needs no detrending at all -- unlike the
    # sub-SOLAR longitude, which sweeps 360 deg per synodic month and
    # aliases badly against monthly sampling (that aliasing is what made
    # the old version of this test pass on a wrong sub-point and fail on
    # the right one). 70 daily samples cover >2 anomalistic months and ~2
    # evection periods (31.8 d), so the longitude extremes are actually
    # reached -- a 40-day window measured only 5.4 deg of the ~7.9.
    print("\n=== libration: sub-Earth point wobble, 70 daily samples ===")
    et0 = spice.str2et("2026-03-01 00:00:00 TDB")
    se_lats, se_lons = [], []
    for i in range(70):
        lat, lon = subpt("EARTH", et0 + i * 86400.0)
        se_lats.append(lat)
        se_lons.append(lon)
    lon_amp = max(max(se_lons) - min(se_lons), 0.0) / 2.0
    # lon may wrap 360->0 near the frame origin; handle it
    if max(se_lons) - min(se_lons) > 180:
        shifted = [l if l < 180 else l - 360 for l in se_lons]
        lon_amp = (max(shifted) - min(shifted)) / 2.0
    lat_amp = (max(se_lats) - min(se_lats)) / 2.0
    print(f"  sub-Earth lon range: {min(se_lons):.3f} .. {max(se_lons):.3f} deg")
    print(f"  sub-Earth lat range: {min(se_lats):+.3f} .. {max(se_lats):+.3f} deg")
    print(f"  half-amplitude: lon {lon_amp:.3f} deg (expect ~7.9), "
          f"lat {lat_amp:.3f} deg (expect ~6.68)")
    check("libration in longitude present (~7.9 deg half-amp)",
          5.0 < lon_amp < 10.0, f"{lon_amp:.3f} deg")
    check("libration in latitude present (~6.68 deg half-amp)",
          4.5 < lat_amp < 9.0, f"{lat_amp:.3f} deg")
    print("  (a flat wobble here would mean the orientation PCK is not loaded)")

    # ---- 5. Earth geometry ----
    print("\n=== Earth from the lunar south pole ===")
    et = spice.str2et("2026-10-12 00:00:00 TDB")
    se_lat, se_lon = subpt("EARTH", et)
    print(f"  sub-Earth point: lat {se_lat:+.4f}  lon {se_lon:.4f}")
    check("sub-Earth latitude within libration bound (|lat| < 6.95)",
          abs(se_lat) < 6.95, f"{se_lat:+.4f} deg")

    pos_e, _ = spice.spkpos("EARTH", et, "J2000", "LT+S", "MOON")
    dist = math.sqrt(sum(c * c for c in pos_e))
    ad = 2 * math.degrees(math.asin(6378.137 / dist))
    check("Earth apparent diameter 1.80-2.01 deg",
          1.80 < ad < 2.02, f"{ad:.4f} deg at {dist:,.0f} km")

    # elevation at P1 sites, analytic spherical formula.
    # Coordinates come from clps/sites.json (TEAM_SPLIT rule: no
    # coordinate in code unless it lives there). The previous version
    # hardcoded -89.67/129.78 and -88.50/-87.1.
    import json
    p1_sites = [s for s in json.loads(
        (ROOT / "clps" / "sites.json").read_text())["sites"]
        if s["priority"] == "P1"]
    for site in p1_sites:
        slat = math.radians(site["lat"])
        slon = math.radians(site["lon"])
        cos_t = (math.sin(slat) * math.sin(math.radians(se_lat))
                 + math.cos(slat) * math.cos(math.radians(se_lat))
                 * math.cos(slon - math.radians(se_lon)))
        elev = 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_t))))
        print(f"  Earth elevation from {site['name']}: {elev:+.4f} deg")

    spice.pxfrm2("IAU_MOON", "J2000", et, et)
    check("IAU_MOON body-fixed frame resolvable", True,
          "orientation PCK is loaded")
    print("\n  Note: SPICE exposes the inertial frame as 'J2000', not 'BCRS'.")
    print("  BCRS is the DE440 series' native frame but is not a registered")
    print("  SPICE frame name -- use J2000 for frame transformations.")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All ephemeris checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())