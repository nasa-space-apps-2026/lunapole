"""Earth visibility from a lunar surface site — P3 / W2.

The differentiator: Earth is not "in the sky" at the south pole. It sits
within ±6.7° of the horizon, so the same ridges that hide the Sun can hide
the Deep Space Network. Three effects have to be handled, and the original
spec got two of them wrong:

  1. **Parallax is not optional.** The Moon's radius is 0.45 % of the
     Earth-Moon distance, so an observer standing on the surface sees Earth
     displaced by up to **0.2590°** (constants.json) relative to the Moon's
     centre. That is 14 % of Earth's 1.901° disc — bigger than the solar
     radius. Computing the geocentric direction and calling it "Earth
     elevation" is wrong at the scale of the whole story.
  2. **Earth's disc is 1.901° across, 3.56× the Sun.** Partial-disc
     visibility (the limb peeking over a ridge) is the normal case, not an
     edge case.
  3. **Libration moves the sub-Earth point ±6.68° monthly**, so a site's
     Earth window is not a fixed property — it depends on the date. That is
     W2 and it comes from the ephemeris (P2), not from this module.

Everything here works in the IAU_MOON body-fixed frame, on top of the
vectors baked by `frames.to_body_fixed`, so the Earth direction used for
occlusion is the same one the ephemeris artifacts contain.
"""
import math

import numpy as np

from . import dem as dem_mod
from . import frames
from . import solar_disc

EARTH_RADIUS_KM = frames.EARTH_R_KM     # 6378.137, constants.json
MOON_R_M = dem_mod.MOON_R_M


def site_position_body_fixed(lat_deg, lon_deg, height_m=0.0):
    """Site position from the Moon's centre in IAU_MOON, km.

    `height_m` is the DEM elevation; using 0 puts the observer on the
    reference sphere, which is wrong by up to 13 km in radius — still tiny
    against 384 400 km, but it is free to do it right.
    """
    n = frames.surface_normal(lat_deg, lon_deg)
    r_km = (MOON_R_M + float(height_m)) / 1000.0
    return np.asarray(n, dtype=float) * r_km


def earth_vector_from_site(et, lat_deg, lon_deg, height_m=0.0,
                           abcorr="LT"):
    """Topocentric Moon→Earth vector in IAU_MOON, km.

    This is the vector the parallax lives in: subtract the site's own
    offset from the Moon's centre before taking the direction.
    """
    centre = np.asarray(frames.to_body_fixed("EARTH", et, abcorr=abcorr))
    return centre - site_position_body_fixed(lat_deg, lon_deg, height_m)


def _enu_components(vec_km, lat_deg, lon_deg):
    """Project a body-fixed vector onto local east / north / up."""
    n = np.asarray(frames.surface_normal(lat_deg, lon_deg), dtype=float)
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon),
                      -math.sin(lat) * math.sin(lon),
                      math.cos(lat)])
    v = np.asarray(vec_km, dtype=float)
    return float(v @ east), float(v @ north), float(v @ n)


def topocentric_elev_az(et, lat_deg, lon_deg, height_m=0.0, abcorr="LT"):
    """Earth elevation/azimuth as seen from the site → (elev_deg, az_deg)."""
    v = earth_vector_from_site(et, lat_deg, lon_deg, height_m, abcorr)
    e, n, u = _enu_components(v, lat_deg, lon_deg)
    elev = math.degrees(math.atan2(u, math.hypot(e, n)))
    az = math.degrees(math.atan2(e, n)) % 360.0
    return elev, az


def geocentric_elevation_deg(et, lat_deg, lon_deg, abcorr="LT"):
    """Earth elevation ignoring the site's displacement (for parallax only).

    Equivalent to `frames.elevation_of('EARTH', ...)`; kept here so the
    topocentric and geocentric numbers are always computed from one place.
    """
    return frames.elevation_of("EARTH", et, lat_deg, lon_deg, abcorr=abcorr)


def parallax_deg(et, lat_deg, lon_deg, height_m=0.0, abcorr="LT"):
    """Topocentric − geocentric elevation, degrees.

    Should stay inside ±0.2590° (constants.json max_sub_lunar_parallax_deg).
    Sign depends on which limb of the Moon the site is on.
    """
    topo, _ = topocentric_elev_az(et, lat_deg, lon_deg, height_m, abcorr)
    return topo - geocentric_elevation_deg(et, lat_deg, lon_deg, abcorr)


def angular_diameter_deg(et, lat_deg, lon_deg, height_m=0.0, abcorr="LT"):
    """Apparent Earth diameter from the site, degrees (≈1.901 mean)."""
    v = earth_vector_from_site(et, lat_deg, lon_deg, height_m, abcorr)
    d = float(np.linalg.norm(v))
    return 2.0 * math.degrees(math.asin(EARTH_RADIUS_KM / d))


def distance_km(et, lat_deg, lon_deg, height_m=0.0, abcorr="LT"):
    v = earth_vector_from_site(et, lat_deg, lon_deg, height_m, abcorr)
    return float(np.linalg.norm(v))


def spherical_elevation_deg(lat_site_deg, lon_site_deg,
                            lat_sub_deg, lon_sub_deg):
    """Verified spherical law of cosines (constants.json earth_elevation_verified).

    Kept as an independent formula so the vector pipeline can be checked
    against arithmetic that has no frames in it at all.
    """
    p1 = math.radians(lat_site_deg)
    p2 = math.radians(lat_sub_deg)
    dl = math.radians(lon_site_deg - lon_sub_deg)
    cos_theta = (math.sin(p1) * math.sin(p2)
                 + math.cos(p1) * math.cos(p2) * math.cos(dl))
    return 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))


def earth_metrics(et, lat_deg, lon_deg, horizon_lookup, height_m=0.0,
                  n=solar_disc.DEFAULT_SAMPLES, panel_normal=None,
                  abcorr="LT"):
    """Full Earth picture for one epoch: elevation, parallax, disc, flux.

    `horizon_lookup` is the same callable the Sun path uses — pass
    `horizon.horizon_at(profile, az)`. Sun and Earth then share one terrain
    horizon, which is what keeps the app's picture and numbers in agreement.
    """
    elev, az = topocentric_elev_az(et, lat_deg, lon_deg, height_m, abcorr)
    geo = geocentric_elevation_deg(et, lat_deg, lon_deg, abcorr)
    diam = angular_diameter_deg(et, lat_deg, lon_deg, height_m, abcorr)
    disc = solar_disc.disc_metrics(elev, az, diam / 2.0, horizon_lookup,
                                   n=n, panel_normal=panel_normal)
    return {
        "et": float(et),
        "elev_deg": elev,
        "az_deg": az,
        "geocentric_elev_deg": geo,
        "parallax_deg": elev - geo,
        "distance_km": distance_km(et, lat_deg, lon_deg, height_m, abcorr),
        "angular_diameter_deg": diam,
        "above_horizon": disc["sun_above_horizon"],
        "disc_fraction": disc["disc_fraction"],
        "incident_flux": disc["incident_flux"],
        "horizon_at_center_deg": disc["horizon_at_center_deg"],
    }
