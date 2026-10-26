"""LUNAPOLE DEM access — the terrain layer P3 stands on.

Reads the per-site polar-stereographic crops produced by
`scripts/crop_sites.py` (`artifacts/dem/<site_id>.tif`, Int16 metres) and
answers the only two questions the horizon engine asks:

    * what is the elevation at this (lat, lon)?
    * what is the elevation at this (x, y) in the projection plane?

Design notes, each one a trap that has already been paid for:

  * The projection is SOUTH polar stereographic, spherical aspect, with
    `rho = 2 R tan(pi/4 + lat/2)`. The factor of 2 is required — dropping
    it halves every radius (verify_dem.py asserts the round-trip).
  * +Y is longitude 0, east increases clockwise: `x = rho sin(lon)`,
    `y = -rho cos(lon)`.
  * DEM values ARE metres (`ldem_*`, SCALING_FACTOR=1, OFFSET=0). The
    sibling `ldec_*` products are observation counts and decode to 0..13.
    A `ldec_` crop passes every geometry check and is pure fiction, so the
    validity window below rejects it the same way verify_dem.py does.
  * Sampling is NEAREST, not bilinear, on purpose: every horizon number
    must be traceable to a measured pixel. Bilinear invents sub-pixel
    terrain that LOLA never observed.
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

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEM_DIR = ROOT / "artifacts" / "dem"

MOON_R_M = 1737400.0  # constants.json lunar.radius_m

# Lunar relief window used to reject sentinel padding and, more importantly,
# `ldec_` count rasters masquerading as elevation. Same bounds rationale as
# verify/verify_dem.py: real floors reach about -13.4 km, rims about +5 km.
VALID_MIN_M = -15000.0
VALID_MAX_M = 15000.0


def latlon_to_stereo_xy(lat_deg, lon_deg, radius_m=MOON_R_M):
    """Forward south-polar stereographic, spherical aspect → metres.

    Vectorised: accepts scalars or numpy arrays. Matches
    `scripts/crop_sites.py` and `verify/verify_dem.py` exactly.
    """
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    rho = 2.0 * radius_m * np.tan(np.pi / 4.0 + lat / 2.0)
    return rho * np.sin(lon), -rho * np.cos(lon)


def stereo_xy_to_latlon(x, y, radius_m=MOON_R_M):
    """Inverse south-polar stereographic → (lat_deg, lon_deg 0..360)."""
    rho = np.hypot(x, y)
    lat = 2.0 * np.arctan2(rho, 2.0 * radius_m) - np.pi / 2.0
    lon = np.degrees(np.arctan2(x, -y)) % 360.0
    # rho == 0 is the pole itself; atan2(0, 0) is defined but lon is arbitrary.
    return np.degrees(lat), lon


class Dem:
    """A single-site DEM crop.

    Attributes are deliberately dumb (array + affine transform) so tests can
    build synthetic terrain with `Dem.from_array` and run the horizon engine
    without touching GDAL.
    """

    def __init__(self, values, transform, site_id="synthetic", crs=None,
                 tags=None, path=None):
        self.values = np.asarray(values)
        if self.values.ndim != 2:
            raise ValueError("DEM values must be 2-D")
        self.transform = transform
        self.site_id = site_id
        self.crs = crs
        self.tags = tags or {}
        self.path = path
        # affine: x = a*col + b*row + c ; y = d*col + e*row + f
        self.a, self.b, self.c, self.d, self.e, self.f = transform
        if abs(self.b) > 1e-9 or abs(self.d) > 1e-9:
            raise ValueError("rotated rasters are not supported")
        self.height, self.width = self.values.shape
        self.valid = ((self.values >= VALID_MIN_M)
                      & (self.values <= VALID_MAX_M))

    # -- constructors ----------------------------------------------------
    @classmethod
    def from_geotiff(cls, path, site_id=None):
        import rasterio  # imported lazily: proofs of geometry need no GDAL

        with rasterio.open(path) as src:
            values = src.read(1)
            transform = tuple(src.transform)[:6]
            tags = dict(src.tags())
            crs = str(src.crs) if src.crs else None
        sid = site_id or tags.get("site_id") or Path(path).stem
        return cls(values, transform, site_id=sid, crs=crs, tags=tags,
                   path=Path(path))

    @classmethod
    def for_site(cls, site_id, dem_dir=DEM_DIR):
        path = Path(dem_dir) / f"{site_id}.tif"
        if not path.exists():
            raise FileNotFoundError(
                f"missing DEM crop {path}. Run: python3 scripts/crop_sites.py")
        return cls.from_geotiff(path, site_id=site_id)

    @classmethod
    def from_array(cls, values, pix_m=10.0, site_id="synthetic"):
        """Synthetic terrain centred on the projection origin (the pole).

        Only used by tests: a flat array of zeros is a perfect sphere, which
        makes the curvature correction testable in closed form.
        """
        h, w = np.asarray(values).shape
        transform = (pix_m, 0.0, -pix_m * w / 2.0,
                     0.0, -pix_m, pix_m * h / 2.0)
        return cls(values, transform, site_id=site_id)

    # -- geometry --------------------------------------------------------
    @property
    def pix_m(self):
        return abs(self.a)

    def pixel_of(self, x, y):
        """Projection metres → fractional (col, row)."""
        return (x - self.c) / self.a, (y - self.f) / self.e

    def xy_of(self, col, row):
        return self.a * col + self.c, self.e * row + self.f

    def contains_latlon(self, lat_deg, lon_deg):
        x, y = latlon_to_stereo_xy(lat_deg, lon_deg)
        col, row = self.pixel_of(x, y)
        return 0 <= col < self.width and 0 <= row < self.height

    # -- sampling --------------------------------------------------------
    def sample_xy(self, x, y):
        """Nearest-pixel elevation at projection coordinates (metres).

        Returns (z_m, ok). `ok` is False outside the raster OR on padding /
        wrong-product pixels, so callers can fail closed instead of
        silently reading sentinel values (~-20928 m in the JP2 tiles).
        """
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        col, row = self.pixel_of(x, y)
        ci = np.floor(col).astype(np.int64)
        ri = np.floor(row).astype(np.int64)
        inside = (ci >= 0) & (ci < self.width) & (ri >= 0) & (ri < self.height)
        ci_c = np.clip(ci, 0, self.width - 1)
        ri_c = np.clip(ri, 0, self.height - 1)
        z = self.values[ri_c, ci_c].astype(float)
        ok = inside & self.valid[ri_c, ci_c]
        return z, ok

    def sample_latlon(self, lat_deg, lon_deg):
        x, y = latlon_to_stereo_xy(lat_deg, lon_deg)
        return self.sample_xy(x, y)

    def elevation_at(self, lat_deg, lon_deg):
        """Elevation at a point, raising if the DEM has no measurement there."""
        z, ok = self.sample_latlon(lat_deg, lon_deg)
        if not np.all(ok):
            raise ValueError(
                f"no valid DEM pixel at lat {lat_deg:.6f} lon {lon_deg:.6f} "
                f"in {self.site_id}")
        return float(z)

    def coverage_radius_km(self):
        """Half-width of the crop in km (the inscribed square, not diagonal).

        Horizon rays cannot go further than this without leaving the data.
        """
        return min(abs(self.a) * self.width, abs(self.e) * self.height) / 2000.0
