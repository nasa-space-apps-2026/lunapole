"""LUNAPOLE frame and kernel utilities — the P2 foundation.

Everything about SPICE frames, kernel loading, and time conversion lives
here so ephemeris.py (and later horizon.py) never touches raw spiceypy.

Rules enforced here:
  * All 4 kernels load together; a missing one is a hard error, because the
    resulting exception (SpiceKERNELVARNOTFOUND BODY10_RADII) is cryptic.
  * Time discipline: str2et() takes UTC strings and returns TDB seconds.
    Everything stored in artifacts is TDB (et). Display code converts back.
  * IAU_MOON is where libration lives. Ask for it directly in spkpos()
    rather than doing frame gymnastics.
  * subpt() returns CARTESIAN — always run recgeo() after it.
"""

# --- UTF-8 console -------------------------------------------------------
# Prints °, +-, x and arrows. A Windows cp1252 console raises
# UnicodeEncodeError on the first of them, which kills the script after
# the work is done. Importing the bootstrap fixes the streams once.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
import _bootstrap  # noqa: E402

_bootstrap.utf8_streams()
# -------------------------------------------------------------------------

import json
import math
from pathlib import Path

import spiceypy as spice

ROOT = Path(__file__).resolve().parents[2]
KERNEL_DIR = ROOT / "data" / "kernels"

KERNELS = [
    KERNEL_DIR / "naif0012.tls",            # leapseconds
    KERNEL_DIR / "pck00010.tpc",            # body radii
    KERNEL_DIR / "de440s.bsp",              # planetary ephemeris
    KERNEL_DIR / "moon_pa_de440_200625.bpc",  # lunar orientation + libration
]

# Body constants — verified in constants.json. Equatorial radius in km,
# flattening 0.0 (spherical approximation; real flattening ~0.0012,
# documented in constants.json as negligible for our tolerance).
MOON_R_KM = 1737.4
MOON_F = 0.0
EARTH_R_KM = 6378.137

_loaded = False


def load_kernels():
    """Load all four kernels. Idempotent. Raises with a helpful message."""
    global _loaded
    if _loaded:
        return
    missing = [p for p in KERNELS if not p.exists()]
    if missing:
        names = ", ".join(str(p.relative_to(ROOT)) for p in missing)
        raise FileNotFoundError(
            f"Missing SPICE kernels: {names}. "
            f"Run: bash scripts/fetch_data.sh"
        )
    spice.furnsh([str(p) for p in KERNELS])
    _loaded = True


def utc_to_et(iso_utc: str) -> float:
    """UTC string -> ET (TDB seconds past J2000).

    str2et() handles the UTC->TDB conversion including leap seconds.
    Never mix: UT1/GMST is Earth rotation, not needed here (no Earth
    surface observer in this project).
    """
    load_kernels()
    return spice.str2et(iso_utc)


def et_to_utc(et: float, fmt: str = "C") -> str:
    """ET (TDB) -> UTC string for display. fmt: C, D, or ISOC."""
    load_kernels()
    return spice.et2utc(et, fmt, 0)


def latlon_to_body_fixed(lat_deg: float, lon_deg: float,
                         radius_km: float = MOON_R_KM) -> list:
    """(lat, lon) in IAU_MOON -> Cartesian position vector [x,y,z] km.

    Convention: planetographic, lon -180..+180 east positive (sites.json).
    recgeo/rdrec use the same convention, so this round-trips exactly.
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    return [
        radius_km * math.cos(lat) * math.cos(lon),
        radius_km * math.cos(lat) * math.sin(lon),
        radius_km * math.sin(lat),
    ]


def body_fixed_to_latlon(pos_km: list) -> tuple:
    """Cartesian [x,y,z] km in IAU_MOON -> (lat_deg, lon_deg 0..360).

    Uses recgeo which returns radians. lon normalized to 0..360 to match
    the sub-point convention used by SPICE reports.
    """
    lon, lat, _ = spice.recgeo(pos_km, MOON_R_KM, MOON_F)
    return math.degrees(lat), math.degrees(lon) % 360.0


def sub_point(target: str, et: float, abcorr: str = "NONE") -> tuple:
    """Sub-<target> point ON THE MOON -> (lat_deg, lon_deg 0..360).

    target: 'SUN' or 'EARTH'. 'NEAR POINT' on a sphere.

    ARGUMENT ORDER TRAP (found 2026-10-13 against Horizons):
    subpt(method, target, et, abcorr, observer) computes the point on
    TARGET where OBSERVER is at zenith. The sub-solar point ON THE MOON
    is therefore subpt(..., 'MOON', ..., 'SUN') — the Sun is the observer,
    the Moon is the target. Writing subpt(..., 'SUN', ..., 'MOON') gives
    the sub-LUNAR point on the Sun's surface: plausible-looking numbers
    (near the Sun-Moon line) but wrong by up to ~8 deg latitude and tens
    of degrees longitude, and its 'libration' signal is an artifact of
    IAU_SUN rotation. Verified 2026-01-01: correct call gives
    lat -1.3444 lon 32.5959 vs Horizons -1.3464/32.5196.

    ABERRATION DEFAULT 'NONE': JPL Horizons' sub-point convention matches
    geometric direction to < 0.01 deg (that is what verify_horizons.py
    asserts). LT shifts longitude by 0.076 deg — the Moon's rotation
    during solar light time. Real physics for shadows (see to_body_fixed)
    but not what Horizons reports; pass abcorr='LT' explicitly when you
    want the retarded direction.
    """
    load_kernels()
    cart, _ = spice.subpt("NEAR POINT", "MOON", et, abcorr, target)
    return body_fixed_to_latlon(list(cart))


def to_body_fixed(target: str, et: float, abcorr: str = "LT") -> list:
    """Position vector of target from Moon centre in IAU_MOON, km.

    This is the one call the horizon engine needs: the Sun/Earth
    direction in the body-fixed frame where the DEM horizon profile
    lives.

    ABERRATION DEFAULT 'LT': photons received now left the Sun 499 s ago;
    shadow geometry follows the Sun's RETARDED position. In the
    body-fixed frame the Moon-Sun relative geometry shifts ~0.076 deg
    over solar light time — 5% of the 1.54 deg max solar elevation and a
    third of the solar penumbra half-width (0.2667 deg). Stellar
    aberration ('LT+S') is an apparent-position effect and is deliberately
    NOT applied to shadow geometry. For comparisons against Horizons'
    sub-point products use sub_point() (default NONE) instead.
    """
    load_kernels()
    pos, _ = spice.spkpos(target, et, "IAU_MOON", abcorr, "MOON")
    return list(pos)


def surface_normal(lat_deg: float, lon_deg: float) -> list:
    """Unit outward normal at (lat, lon) in IAU_MOON, spherical body."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    return [
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    ]


def elevation_of(target: str, et: float,
                 site_lat: float, site_lon: float,
                 abcorr: str = "LT") -> float:
    """Elevation of target (SUN/EARTH) above the local horizon, degrees.

    Geometric point-source elevation: positive = above the spherical
    horizon. Terrain occlusion is horizon.py's job, not ours — this is
    the value the far-field engine compares against the DEM horizon.
    abcorr defaults to 'LT' (retarded position), matching to_body_fixed.
    """
    n = surface_normal(site_lat, site_lon)
    pos = to_body_fixed(target, et, abcorr)
    d = math.sqrt(sum(c * c for c in pos))
    u = [c / d for c in pos]
    dot = sum(n[i] * u[i] for i in range(3))
    # elevation = 90 - zenith_distance. (The first version of this file
    # had the sign backwards: acos(dot) - 90 returned -90 for a sun at
    # zenith. Symmetric +-1.54 deg bounds in the callers masked it.)
    return 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def earth_distance_km(et: float) -> float:
    """Earth-Moon centre distance, km, LT+S."""
    load_kernels()
    pos, _ = spice.spkpos("EARTH", et, "J2000", "LT+S", "MOON")
    return math.sqrt(sum(c * c for c in pos))


def earth_angular_diameter_deg(et: float) -> float:
    """Apparent angular diameter of Earth from the Moon centre, degrees.

    Range 1.802-2.012 deg (constants.json). Modelled as a sphere; the real
    Earth is an oblate spheroid but the difference is far below our
    tolerance at lunar distances.
    """
    dist = earth_distance_km(et)
    return 2.0 * math.degrees(math.asin(EARTH_R_KM / dist))


SUN_DIAMETER_DEG = 0.5334  # constants.json, verified. Used by solar_disc.py.
