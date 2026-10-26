#!/usr/bin/env python3
"""Validate the LUNAPOLE ephemeris chain against JPL Horizons.

Run:  python3 verify/verify_horizons.py

This is P2's non-negotiable gate (TEAM_SPLIT.md): compare the computed
sub-solar and sub-Earth points against JPL Horizons at >= 5 epochs,
including two at libration extrema. Target error: < 0.01 deg angular
separation.

Method:
  1. Query the Horizons API once for the Moon's sub-solar point
     (QUANTITIES=15, "SunSub-LON/LAT") and sub-Earth point (QUANTITIES=14,
     "ObsSub-LON/LAT") from the Earth-Moon barycentre (geocentre), daily
     over a 6-month window. The sub-points on the Moon are properties of
     the Moon, so the geocentric observer is fine and is Horizons' own
     convention.
  2. Independently compute the same points from our SPICE chain
     (de440s + moon_pa PCK, IAU_MOON frame, abcorr=NONE — see the
     rotation-over-light-time note in build/lunapole/frames.py).
  3. Epochs are matched by UTC calendar string -> utc2et(), never by the
     output JD, so no TDB/UTC offset can leak in.
  4. Libration extrema: detrend our own daily sub-EARTH longitude track
     (unwrap, least-squares remove the linear trend); max/min residual
     epochs are the extrema, and both are included in the compared set.
     The sub-EARTH track is used because that is where libration in
     longitude lives (+/-7.9 deg about lon 0); the sub-SOLAR track is a
     linear sweep whose residual is only +-0.3 deg -- extrema of that
     would not be libration extrema.
  5. Error metric = great-circle separation between our point and
     Horizons'. Both use east-positive longitudes.

Requires network access to ssd.jpl.nasa.gov. Unreachable => exit 2;
a network-less run is NOT a pass.
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
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build.lunapole import frames  # noqa: E402

HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
WIN_START = "2026-01-01"
WIN_STOP = "2026-07-02"    # ~182 daily samples
SEP_TOL_DEG = 0.01         # TEAM_SPLIT target

_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}

failures = []


def cal_key(cal: str):
    """Sort key for Horizons calendar strings.

    '2026-Mar-01 00:00' -> (2026, 3, 1). sorted() on the raw string is
    LEXICOGRAPHIC: Apr < Feb < Jan < Jul < Jun < Mar < May. Using that
    order for the longitude unwrap/detrend silently produces garbage
    residuals (tens of degrees) that look like a physics failure.
    """
    date = cal.split(" ", 1)[0]
    y, m, d = date.split("-")
    return int(y), _MONTHS[m], int(d)


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def horizons_subpoints_daily():
    """Fetch daily sub-Earth + sub-solar points on the Moon -> {iso: tuple}.

    Returns {iso: (obs_lat, obs_lon, sun_lat, sun_lon)} where obs = sub-Earth
    and sun = sub-solar, both ON THE MOON (Horizons' "crtr" quantities).
    """
    params = {
        "format": "text",
        "COMMAND": "'301'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'500@399'",
        "MAKE_EPHEM": "'YES'",
        "QUANTITIES": "'14,15'",
        "START_TIME": f"'{WIN_START}'",
        "STOP_TIME": f"'{WIN_STOP}'",
        "STEP_SIZE": "'1 d'",
        "CSV_FORMAT": "'YES'",
        "OBJ_DATA": "'NO'",
    }
    url = f"{HORIZONS}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "LUNAPOLE-verify/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    if "$$SOE" not in text:
        raise RuntimeError(
            "Horizons returned no data block. Response head:\n" + text[:800])

    body = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    out = {}
    for line in body.strip().splitlines():
        cols = [c.strip().strip('"') for c in line.split(",")]
        nums = []
        for c in cols[1:]:
            try:
                nums.append(float(c))
            except ValueError:
                pass
        if len(nums) < 4:
            continue
        cal = cols[0].strip()
        # Horizons CSV column order is LON then LAT for both quantities:
        # [ObsSub-LON, ObsSub-LAT, SunSub-LON, SunSub-LAT]. Return
        # (obs_lat, obs_lon, sun_lat, sun_lon) -- lat first, to match our
        # sub_point() convention. Swapping these gives separations of
        # tens of degrees and looks like a physics failure.
        out[cal] = (nums[1], nums[0], nums[3], nums[2])
    return out


def sep_deg(lat1, lon1, lat2, lon2) -> float:
    """Great-circle separation, degrees."""
    a1, o1, a2, o2 = map(math.radians, (lat1, lon1, lat2, lon2))
    cos = (math.sin(a1) * math.sin(a2)
           + math.cos(a1) * math.cos(a2) * math.cos(o1 - o2))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def cal_to_spice(cal: str) -> str:
    """'2026-Jan-01 00:00' -> SPICE-parseable UTC string."""
    date, time = cal.split(" ", 1)
    y, m, d = date.split("-")
    return f"{y} {m.upper()} {d} {time}:00"


def main() -> int:
    print("=== LUNAPOLE ephemeris vs JPL Horizons ===\n")

    print(f"fetching Horizons sub-points, {WIN_START} + 6 months, daily...")
    try:
        hz = horizons_subpoints_daily()
    except Exception as e:
        print(f"cannot reach Horizons API: {e}")
        print("network-less run is NOT a pass (exit 2)")
        return 2
    print(f"  got {len(hz)} daily samples\n")

    frames.load_kernels()

    iso_days = sorted(hz.keys(), key=cal_key)
    ours_solar, ours_earth, et_by_iso = {}, {}, {}
    for cal in iso_days:
        et = frames.utc_to_et(cal_to_spice(cal))
        et_by_iso[cal] = et
        ours_solar[cal] = frames.sub_point("SUN", et)
        ours_earth[cal] = frames.sub_point("EARTH", et)

    # Libration extrema from our own sub-EARTH longitude track -- that is
    # where libration in longitude actually lives (+/-7.9 deg wobble
    # about lon 0, the tidal-locking direction). The sub-SOLAR track is a
    # near-perfect linear sweep (12.19 deg/day); its least-squares
    # residual is only +-0.3 deg (evection/annual terms), so extrema of
    # THAT are not libration extrema at all. Measured side by side on
    # 2026-10-14: sub-solar resid +-0.3 deg vs sub-Earth -7.35..+5.58 deg.
    # Least-squares detrend, NOT endpoint-anchored: anchoring at
    # unwrapped[0] forces resid[0]=0, so the min is always the first
    # sample and is not a real extremum.
    lons = [ours_earth[c][1] for c in iso_days]
    unwrapped = [lons[0]]
    for i in range(1, len(lons)):
        d = lons[i] - lons[i - 1]
        while d < -180:
            d += 360
        while d > 180:
            d -= 360
        unwrapped.append(unwrapped[-1] + d)
    n = len(unwrapped)
    t = list(range(n))
    t_bar = sum(t) / n
    u_bar = sum(unwrapped) / n
    rate = (sum((t[i] - t_bar) * (unwrapped[i] - u_bar) for i in range(n))
            / sum((t[i] - t_bar) ** 2 for i in range(n)))
    intercept = u_bar - rate * t_bar
    resid = [unwrapped[i] - (intercept + rate * t[i]) for i in range(n)]
    lo = min(range(n), key=lambda i: resid[i])
    hi = max(range(n), key=lambda i: resid[i])

    # >=5 epochs: both extrema + 4 spread across the window
    spread = [iso_days[i * len(iso_days) // 4] for i in range(4)]
    epochs = []
    for cal in (iso_days[hi], iso_days[lo], *spread):
        if cal not in epochs:
            epochs.append(cal)

    print(f"libration extrema (sub-EARTH lon residual): max {iso_days[hi]} "
          f"(+{resid[hi]:.2f} deg), min {iso_days[lo]} ({resid[lo]:.2f} deg)")
    print(f"comparing {len(epochs)} epochs "
          f"(2 extrema + {len(epochs) - 2} spread):\n")

    print(f"  {'epoch':<18} {'solar sep':>10} {'earth sep':>10}  note")
    worst_solar = worst_earth = 0.0
    for cal in epochs:
        if cal not in hz:
            check(f"Horizons has data for {cal}", False)
            continue
        hlat, hlon, hs_lat, hs_lon = hz[cal]
        s_lat, s_lon = ours_solar[cal]
        e_lat, e_lon = ours_earth[cal]
        s_sep = sep_deg(s_lat, s_lon, hs_lat, hs_lon)
        e_sep = sep_deg(e_lat, e_lon, hlat, hlon)
        worst_solar = max(worst_solar, s_sep)
        worst_earth = max(worst_earth, e_sep)
        tag = " *libration extremum*" if cal in (iso_days[hi], iso_days[lo]) else ""
        print(f"  {cal:<18} {s_sep:9.4f}  {e_sep:9.4f}  {tag}")

    print(f"\n  worst sub-solar separation: {worst_solar:.4f} deg")
    print(f"  worst sub-Earth separation: {worst_earth:.4f} deg "
          f"(target < {SEP_TOL_DEG} each)")
    check(f"sub-solar point matches Horizons < {SEP_TOL_DEG} deg at all "
          f"{len(epochs)} epochs (incl. 2 libration extrema)",
          worst_solar < SEP_TOL_DEG, f"worst {worst_solar:.4f} deg")
    check(f"sub-Earth point matches Horizons < {SEP_TOL_DEG} deg at all "
          f"{len(epochs)} epochs (incl. 2 libration extrema)",
          worst_earth < SEP_TOL_DEG, f"worst {worst_earth:.4f} deg")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All Horizons comparison checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
