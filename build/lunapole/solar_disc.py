"""Extended solar disc — P3's penumbra layer.

At the lunar south pole the Sun never climbs above **1.5424°**, while the
solar disc itself is **0.5334°** across (±0.2667° radius). The disc is
therefore ~35 % of the entire elevation range: treating the Sun as a point
is not an approximation, it is a different answer. A ridge can hide a third
of the disc while the "Sun" is still nominally above the horizon.

Three metrics come out of this module, and they are deliberately separate
because the app must show all three (README-SOUTHPOLE §6.4):

    sun_above_horizon  – geometry of the CENTRE point (true/false)
    disc_fraction      – fraction of the disc area above the terrain horizon
    incident_flux      – fraction of full-disc irradiance reaching a panel
                         with a given normal (default: horizontal, facing up)

Sampling is equal-solid-angle, not equal-radius: a uniform grid in radius
would over-weight the limb by 2× and bias every penumbra number. Following
the spec, sample i sits at

    r_i = R sqrt((i + 0.5) / N)          (equal AREA per sample)
    phi_i = i * 0.6180339887 mod 1       (Fibonacci spiral, no clumping)

so every sample carries the same weight, 1/N, and no RNG is involved: the
bake stays bit-for-bit reproducible.

All angles are degrees at the interface, radians internally. Azimuth is
north = 0, east = 90, clockwise — the same convention as horizon.py.
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

import math

import numpy as np

# constants.json solar.* — verified. Kept literal here so this module has no
# SPICE dependency; verify/verify_horizon.py asserts they match constants.json.
SUN_DIAMETER_DEG = 0.5334
SUN_RADIUS_DEG = SUN_DIAMETER_DEG / 2.0          # 0.2667
EARTH_DIAMETER_DEG = 1.901
EARTH_RADIUS_DEG = EARTH_DIAMETER_DEG / 2.0      # 0.9505 (3.56x the Sun)
GOLDEN_FRACTION = 0.6180339887498949

DEFAULT_SAMPLES = 512

ZENITH = np.array([0.0, 0.0, 1.0])               # ENU panel normal


def equal_solid_angle_disc(radius_deg, n=DEFAULT_SAMPLES):
    """Disc samples with equal solid angle per sample.

    Returns (r_deg, phi_rad). Sum of areas is the disc area to ~1/N, and the
    mean of r² is R²/2 regardless of N — asserted in the test suite.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    i = np.arange(n)
    r = np.asarray(radius_deg, dtype=float) * np.sqrt((i + 0.5) / n)
    phi = (i * GOLDEN_FRACTION) % 1.0 * 2.0 * np.pi
    return r, phi


def enu_from_elev_az(elev_deg, az_deg):
    """Unit vector in ENU (x=east, y=north, z=up) from elevation/azimuth."""
    e = np.radians(np.asarray(elev_deg, dtype=float))
    a = np.radians(np.asarray(az_deg, dtype=float))
    return np.stack([np.cos(e) * np.sin(a),
                     np.cos(e) * np.cos(a),
                     np.sin(e)], axis=-1)


def elev_az_from_enu(vec):
    """ENU unit vector(s) → (elev_deg, az_deg 0..360)."""
    v = np.asarray(vec, dtype=float)
    elev = np.degrees(np.arcsin(np.clip(v[..., 2], -1.0, 1.0)))
    az = np.degrees(np.arctan2(v[..., 0], v[..., 1])) % 360.0
    return elev, az


def _disc_frame(center_elev_deg, center_az_deg):
    """Centre unit vector plus an orthonormal basis of the disc plane."""
    c = enu_from_elev_az(center_elev_deg, center_az_deg)
    a = math.radians(float(center_az_deg))
    # horizontal, perpendicular to the centre direction in azimuth
    u = np.array([math.cos(a), -math.sin(a), 0.0])
    v = np.cross(c, u)
    v /= np.linalg.norm(v)
    return c, u, v


def disc_directions(center_elev_deg, center_az_deg, radius_deg,
                    n=DEFAULT_SAMPLES):
    """Unit vectors covering the disc around a centre direction.

    Returns (dirs_enu[n,3], elev_deg[n], az_deg[n], r_deg[n]).
    """
    c, u, v = _disc_frame(center_elev_deg, center_az_deg)
    r_deg, phi = equal_solid_angle_disc(radius_deg, n)
    r = np.radians(r_deg)
    dirs = (np.cos(r)[:, None] * c[None, :]
            + np.sin(r)[:, None] * (np.cos(phi)[:, None] * u[None, :]
                                    + np.sin(phi)[:, None] * v[None, :]))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    elev, az = elev_az_from_enu(dirs)
    return dirs, elev, az, r_deg


def disc_metrics(center_elev_deg, center_az_deg, radius_deg,
                 horizon_lookup, n=DEFAULT_SAMPLES, panel_normal=None):
    """Visibility and flux metrics for a disc of angular radius `radius_deg`.

    horizon_lookup : callable az_deg -> horizon elevation (deg). Accepts
                     arrays; `horizon.horizon_at(profile, az)` fits.
    panel_normal   : ENU vector; default is the local zenith (horizontal
                     panel). Pass the lander's actual panel normal to get the
                     oriented-panel flux the spec asks for.

    Returns a dict:
        center_elev_deg, center_az_deg, radius_deg, n
        sun_above_horizon : centre point strictly above the terrain horizon
        disc_fraction     : visible area fraction, 0..1
        incident_flux     : visible flux on the panel, 0..1 (1 = whole disc
                            visible and panel normal pointing at the Sun)
        horizon_at_center_deg
    """
    center_elev = float(center_elev_deg)
    center_az = float(center_az_deg) % 360.0
    horizon_center = float(horizon_lookup(np.array([center_az]))[0])

    dirs, elev, az, _ = disc_directions(center_elev, center_az, radius_deg, n)
    horizon = np.asarray(horizon_lookup(az), dtype=float)
    visible = elev > horizon

    if panel_normal is None:
        panel_normal = ZENITH
    pn = np.asarray(panel_normal, dtype=float)
    pn = pn / np.linalg.norm(pn)
    cos_inc = dirs @ pn
    flux = float(np.sum(np.clip(cos_inc, 0.0, None) * visible) / n)

    return {
        "center_elev_deg": center_elev,
        "center_az_deg": center_az,
        "radius_deg": float(radius_deg),
        "n": int(n),
        "sun_above_horizon": bool(center_elev > horizon_center),
        "disc_fraction": float(np.count_nonzero(visible) / n),
        "incident_flux": flux,
        "horizon_at_center_deg": horizon_center,
        "panel_normal": pn.tolist(),
    }


def sun_metrics(sun_elev_deg, sun_az_deg, horizon_lookup,
                n=DEFAULT_SAMPLES, panel_normal=None):
    """Convenience wrapper: the Sun's disc (0.5334° across) at a site."""
    return disc_metrics(sun_elev_deg, sun_az_deg, SUN_RADIUS_DEG,
                        horizon_lookup, n=n, panel_normal=panel_normal)


def flat_horizon(elev_deg=-90.0):
    """A horizon lookup with no terrain — useful for tests and for P5 mocks."""
    return lambda az: np.full(np.shape(az), float(elev_deg))
