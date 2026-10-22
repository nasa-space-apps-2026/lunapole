"""LUNAPOLE map products — the P4 deliverable.

Three products (TEAM_SPLIT P4):

  1. **Illumination / permanent-shadow map** over a labelled time span.
     Per map pixel: fraction of samples illuminated, longest continuous
     sunlit run, longest continuous dark run. The last one is the
     "PSR-ish" quantity — and it means NOTHING unless the span is honest,
     which is why the span and its label are baked into every artifact
     header, every PNG name, and every JSON meta block.

  2. **Earth-visibility map** — the differentiator. Per pixel: fraction of
     samples with any part of Earth's disc above the local horizon (DTE
     "some limb visible"), the same for the full disc, and longest
     continuous windows of each.

  3. **Per-site time series** — hourly rows (Sun/Earth elevation,
     azimuth, extended-disc fraction, flux on a horizontal panel) plus a
     verdict block, directly consumable by the P5 app.

Method, locked to P3's conventions (same geometry, same fail-closed rules):

  * Horizon per map pixel = max-per-azimuthal-bin march over the LOLA
    tile, computed in batches (pixels x bins chunked over distance
    steps). Same closed form as horizon.py — imported from it, not
    re-derived, so P3/P4 cannot disagree about physics.
  * Azimuth bins for the map are coarser than P3's 720 (default 120 =
    3 deg) and the resolution/step/span travel in the header as labelled
    method parameters. Per-site verdicts (product 3) still use P3's
    720-bin artifacts; the coarse map is for the overview picture.
  * Sun elevation per pixel/timestep from the subsolar direction dot the
    pixel normal (law of cosines). Earth elevation is fully topocentric:
        elev = atan2(D cos(theta) - r, D sin(theta))
    with theta the pixel-sub-Earth separation, r the pixel radius
    (including its DEM height) and D the Earth distance — the 0.259 deg
    parallax that earth.py requires, now per pixel. No approximation.
  * "Illuminated" here is the geometric centre of the solar disc above
    the horizon (Mazarico-style). Disc-averaged metrics exist per site
    in the time series; per-pixel disc integration is deliberately NOT
    done — it would multiply the time loop by the disc sample count.

Honesty requirements enforced here (TEAM_SPLIT P4, non-negotiable):

  * A 1-year map may never present itself as an 18.6-year PSR map. The
    artifact header carries span_days, span_label and az resolution;
    verify/verify_maps.py refuses artifacts whose label lies.
  * Pixels outside the tile or on invalid DEM values are UNKNOWN, not
    "dark". Fail-closed for illumination would overstate PSRs — the
    opposite of what "fail closed" means here — so no-data is reported
    as no-data in its own plane.

Binary artifact format (artifacts/maps/, little-endian):

    header '<8sH4s16sIddd' + '<3dI3I' + '<H' + label bytes
        magic       8s  b'LUNAMAP\\0'
        version     H   1
        product     4s  b'ILLU' | b'ERTH'
        region      16s NUL-padded ASCII
        span_days   f64   labelled coverage of the bake
        step_min    f64   timestep in minutes
        grid_m      f64   map pixel size, metres
        az_bins     I     horizon azimuth bins per pixel
        step_m      f64   horizon ray sample stride, metres
        max_dist_km f64   horizon ray length
        start_et    f64   first epoch, TDB seconds past J2000
        samples     I     timesteps baked
        width       I     map pixels (columns)
        height      I     map pixels (rows)
        label_len   H     span_label byte length
        label       ...   span_label UTF-8 (honesty string, shown in UI)
    planes, row-major, one plane per listed field, in order:

    ILLU planes (u1 | f4):
        cov          u1  1 = DEM sample valid, 0 = UNKNOWN (excluded)
        dem_elev     f4  metres
        lit_frac     f4  fraction of samples with sun centre above horizon
        long_lit_h   f4  longest continuous lit run, hours
        long_dark_h  f4  longest continuous dark run, hours
        far_frac     f4  fraction of horizon bins that reached far field
    ERTH planes:
        cov          u1
        dem_elev     f4
        ever_any     u1  any part of Earth's disc ever above horizon
        frac_any     f4  fraction of samples "any limb visible"
        long_any_h   f4  longest continuous any-part-visible run, hours
        frac_full    f4  fraction of samples with FULL disc visible
        long_full_h  f4  longest continuous full-disc run, hours

Earth visibility rule: topocentric Earth-disc-CENTRE elevation margin
against the horizon; "any" = margin > -disc radius, "full" =
margin > +disc radius (per-epoch apparent disc radius). A sloped horizon
can differ from limb tests by <~1 deg of az/2 — documented approximation,
checked at spot epochs against solar_disc.disc_metrics in the verifier.
"""
import argparse
import json
import math
import struct
import sys
import time as time_mod
import zlib
from pathlib import Path

import numpy as np

from . import dem as dem_mod
from . import frames
from . import horizon as horizon_mod
from . import solar_disc

ROOT = Path(__file__).resolve().parents[2]
TILES_DIR = ROOT / "data" / "dem"
SITES_FILE = ROOT / "clps" / "sites.json"
OUT_DIR = ROOT / "artifacts" / "maps"
EPHEM_DIR = ROOT / "artifacts" / "ephemeris"

MOON_R_M = dem_mod.MOON_R_M
EARTH_R_KM = frames.EARTH_R_KM
DRACONIC_YEARS = 18.6
DRACONIC_DAYS = DRACONIC_YEARS * 365.25

MAGIC = b"LUNAMAP\0"
VERSION = 1

ILLU_PLANES = ["cov", "dem_elev", "lit_frac", "long_lit_h",
               "long_dark_h", "far_frac"]
ERTH_PLANES = ["cov", "dem_elev", "ever_any", "frac_any",
               "long_any_h", "frac_full", "long_full_h"]

# map azimuth resolution (label in header). P3 per-site profiles use 720;
# the map trades azimuth resolution for per-pixel coverage and is
# explicitly labelled with whatever it ran at.
DEFAULT_MAP_AZ_BINS = 120

# horizon ray sampling for the map (label in header)
DEFAULT_MAP_STEP_M = 250.0
DEFAULT_MAP_MAX_DIST_KM = 25.0


# ---------------------------------------------------------------------------
# regions
# ---------------------------------------------------------------------------
REGIONS = {
    # The demo map: 87.5S-90S pole cap from the 10 m/px LOLA tile.
    # Disc radius 75.8 km covers Shackleton + de Gerlache + the pole.
    "polecap": {
        "tile": "ldem_875s_10m.jp2",
        "center_xy": (0.0, 0.0),
        "side_m": 148_000.0,      # inside the tile's 151.68 km square
        "default_grid_m": 320.0,
    },
    # Wider 85S-90S cap (20 m/px tile): adds Haworth; coarser DEM.
    "southcap": {
        "tile": "ldem_85s_20m.jp2",
        "center_xy": (0.0, 0.0),
        "side_m": 298_000.0,
        "default_grid_m": 600.0,
    },
}


def load_sites():
    return json.loads(SITES_FILE.read_text())["sites"]


# ---------------------------------------------------------------------------
# PNG writer — stdlib only, deterministic (offline-first, zero CDN)
# ---------------------------------------------------------------------------
def write_png(path, rgb_u8):
    """Minimal deterministic 8-bit RGB PNG writer (no filter, zlib lvl 6)."""
    h, w, _ = rgb_u8.shape
    raw = b"".join(b"\0" + rgb_u8[i].tobytes() for i in range(h))
    def chunk(tag, payload):
        c = struct.pack(">I", len(payload)) + tag + payload
        return c + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


# ---------------------------------------------------------------------------
# tile access — windowed read so the 230 M-pixel tile never loads whole
# ---------------------------------------------------------------------------
def read_tile_window(tile_path, cx_m, cy_m, side_m, margin_m=0.0):
    """Read the square [cx±(side/2+margin), cy±...] window of a JP2 tile
    into a dem.Dem. Transform is rebased so absolute stereo coords work."""
    import rasterio

    half = side_m / 2.0 + margin_m
    x0, x1 = cx_m - half, cx_m + half
    y0, y1 = cy_m - half, cy_m + half

    with rasterio.open(tile_path) as src:
        gt = src.transform
        pix = abs(gt.a)
        # NOTE: +y is "up" in stereo coords but rows grow with -e;
        # rasterio's window is in (col, row) space directly in pixels.
        col0 = int((min(x0, x1) - gt.c) / gt.a)
        row0 = int((max(y0, y1) - gt.f) / gt.e)   # e is negative
        col1 = int((max(x0, x1) - gt.c) / gt.a) + 1
        row1 = int((min(y0, y1) - gt.f) / gt.e) + 1
        col0 = max(0, min(col0, src.width - 1))
        row0 = max(0, min(row0, src.height - 1))
        col1 = max(col0 + 1, min(col1, src.width))
        row1 = max(row0 + 1, min(row1, src.height))

        from rasterio.windows import Window
        win = Window(col0, row0, col1 - col0, row1 - row0)
        values = src.read(1, window=win)
        wt = src.window_transform(win)

    dem = dem_mod.Dem(values, tuple(wt)[:6], site_id=Path(tile_path).stem)
    dem.tags = {"source_tile": str(tile_path)}
    return dem


# ---------------------------------------------------------------------------
# pixel grid
# ---------------------------------------------------------------------------
class PixelGrid:
    """Map lattice in south-polar stereographic coords.

    Row 0 is the +y edge (lon-180 direction), col 0 the -x edge — same
    orientation as the GeoTIFF crops (row grows with -y), so P5's panel A
    can render map and DEM in one convention.
    """

    def __init__(self, width, height, grid_m, cx_m, cy_m, dem):
        self.width = int(width)
        self.height = int(height)
        self.grid_m = float(grid_m)
        self.cx_m = float(cx_m)
        self.cy_m = float(cy_m)

        cols = np.arange(self.width) - (self.width - 1) / 2.0
        rows = (self.height - 1) / 2.0 - np.arange(self.height)
        x = self.cx_m + cols * self.grid_m
        y = self.cy_m + rows * self.grid_m
        X, Y = np.meshgrid(x, y)
        self.X = X.ravel()
        self.Y = Y.ravel()

        lat, lon = dem_mod.stereo_xy_to_latlon(self.X, self.Y)
        self.lat = lat
        self.lon = lon

        L = np.radians(lat)
        LO = np.radians(lon)
        self.n = np.stack([np.cos(L) * np.cos(LO),
                           np.cos(L) * np.sin(LO),
                           np.sin(L)], axis=1)
        self.east = np.stack([-np.sin(LO), np.cos(LO),
                              np.zeros_like(LO)], axis=1)
        self.north = np.stack([-np.sin(L) * np.cos(LO),
                               -np.sin(L) * np.sin(LO),
                               np.cos(L)], axis=1)

        self.z_m, self.ok = dem.sample_xy(self.X, self.Y)
        self.r_m = MOON_R_M + np.where(self.ok, self.z_m, 0.0)

    @property
    def count(self):
        return self.width * self.height

    def pixel_index_of(self, lat_deg, lon_deg):
        """Nearest grid cell to a lat/lon (for spot checks), or None."""
        x, y = dem_mod.latlon_to_stereo_xy(lat_deg, lon_deg)
        col = int(round((x - self.cx_m) / self.grid_m + (self.width - 1) / 2.0))
        row = int(round(((self.height - 1) / 2.0) - (y - self.cy_m) / self.grid_m))
        if 0 <= col < self.width and 0 <= row < self.height:
            return row * self.width + col
        return None


def make_grid(region_name, grid_m=None, dem=None, tile_path=None):
    reg = REGIONS[region_name]
    if dem is None:
        if tile_path is None:
            tile_path = TILES_DIR / reg["tile"]
        dem = read_tile_window(tile_path, reg["center_xy"][0],
                               reg["center_xy"][1], reg["side_m"],
                               margin_m=reg.get("margin_m", 0.0))
    grid_m = grid_m or reg["default_grid_m"]
    width = int(round(reg["side_m"] / grid_m))
    grid_m = reg["side_m"] / width            # exact, for determinism
    return PixelGrid(width, width, grid_m, reg["center_xy"][0],
                     reg["center_xy"][1], dem), dem


# ---------------------------------------------------------------------------
# batched horizon march — same physics as horizon.py, pixels x bins
# ---------------------------------------------------------------------------
def march_map_horizons(grid, dem, az_bins=DEFAULT_MAP_AZ_BINS,
                       step_m=DEFAULT_MAP_STEP_M,
                       max_dist_km=DEFAULT_MAP_MAX_DIST_KM,
                       block_px=4096, step_chunk=16, log_every=0):
    """Max-per-azimuth-bin horizon for every valid map pixel.

    Returns (H, far_frac):
        H        (P, az_bins) float32 — horizon elevation per bin,
                 +90 deg where NO valid sample exists (fail closed,
                 identical to horizon.py's PROV_GAP rule).
        far_frac (P,) float32 — per-pixel fraction of bins whose ray
                 stayed inside measured terrain to max_dist.

    Differences from horizon.py's per-site march (documented, both
    checked by verify_maps):
      * contiguity is carried ACROSS distance-step chunks here (P3's site
        march recomputes per chunk — equivalent for convex crops; carrying
        is strictly safer, so the map does that).
      * contiguity is measured against DEM validity (ok), matching
        horizon.py's inside-crop semantics.
    """
    P = grid.count
    B = az_bins
    max_dist_m = float(max_dist_km) * 1000.0
    n_steps = int(math.ceil(max_dist_m / step_m))
    d_all = (np.arange(n_steps) + 1) * step_m

    n = grid.n
    east = grid.east
    north = grid.north
    lat_r = np.radians(grid.lat)
    lon_r = np.radians(grid.lon)
    h_site = np.where(grid.ok, grid.z_m, 0.0).astype(np.float64)

    az_c = horizon_mod.azimuth_bins(B)                  # bin centres, deg

    H = np.zeros((P, B), dtype=np.float32)
    far_frac = np.zeros(P, dtype=np.float32)

    for b0 in range(0, P, block_px):
        b1 = min(b0 + block_px, P)
        bp = b1 - b0
        n_b = n[b0:b1]
        e_b = east[b0:b1]
        nt_b = north[b0:b1]
        hs = h_site[b0:b1][:, None, None]   # broadcast over (B, S)

        # tangent direction per bin centre (bp, B, 3)
        ca = np.cos(np.radians(az_c))[None, :, None]
        sa = np.sin(np.radians(az_c))[None, :, None]
        tangents = ca * nt_b[:, None, :] + sa * e_b[:, None, :]

        best = np.full((bp, B), -np.inf)
        best_d = np.zeros((bp, B))
        best_z = np.full((bp, B), np.nan)
        cont = np.ones((bp, B), dtype=bool)
        covered = np.zeros((bp, B))

        for s0 in range(0, n_steps, step_chunk):
            s1 = min(s0 + step_chunk, n_steps)
            d = d_all[s0:s1]
            delta = d / MOON_R_M
            cd, sd = np.cos(delta), np.sin(delta)

            p = (cd[None, :, None] * n_b[:, None, None, :]
                 + sd[None, :, None] * tangents[:, :, None, :])

            px_, py_, pz_ = p[..., 0], p[..., 1], p[..., 2]
            # p is a UNIT direction (cosδ·n + sinδ·t, n ⟂ t): latitude from
            # the z component directly. (Dividing by R here was the first
            # bug found in this march: every sample collapsed onto the
            # equator and fail-closed to +90 deg.)
            lat_p = np.degrees(np.arcsin(np.clip(pz_, -1.0, 1.0)))
            lon_p = np.degrees(np.arctan2(py_, px_))

            x, y = dem_mod.latlon_to_stereo_xy(lat_p, lon_p)
            z, ok = dem.sample_xy(x, y)

            ang = horizon_mod.elevation_angle_deg(
                hs, z, d[None, None, :], radius_m=MOON_R_M)
            ang = np.where(ok, ang, -np.inf)

            cont_chunk = cont[:, :, None] & np.cumprod(ok, axis=2, dtype=bool)
            masked = np.where(cont_chunk, ang, -np.inf)
            lbl = masked.max(axis=2)
            lidx = masked.argmax(axis=2)
            lz = np.take_along_axis(
                np.where(cont_chunk, z, np.nan), lidx[:, :, None], axis=2
            )[:, :, 0]
            take = lbl > best
            best = np.where(take, lbl, best)
            best_d = np.where(take, d[lidx], best_d)
            best_z = np.where(take, lz, best_z)

            lasti = cont_chunk.sum(axis=2) - 1
            cov = np.where(lasti >= 0, d[np.clip(lasti, 0, s1 - s0 - 1)],
                           0.0)
            with np.errstate(invalid="ignore"):
                covered = np.maximum(covered, cov)
            # carry contiguity across chunks: AND of this chunk's validity
            cont &= ok.all(axis=2)

        gap = ~np.isfinite(best)
        H[b0:b1] = np.where(gap, 90.0, best).astype(np.float32)
        far = covered >= (max_dist_m - step_m * 0.5)
        ok_px = grid.ok[b0:b1]
        far_frac[b0:b1] = np.where(
            ok_px, far.sum(axis=1) / float(B), 0.0).astype(np.float32)

        if log_every and (b0 // block_px) % log_every == 0:
            pct = 100.0 * b1 / P
            print(f"    march {pct:5.1f}%  ({b1}/{P} px)", flush=True)

    return H, far_frac


# ---------------------------------------------------------------------------
# ephemeris table — one time grid for the whole map (site-independent)
# ---------------------------------------------------------------------------
def build_ephem_table(et_start, step_s, count, log_every=2000):
    """Sub-solar & sub-Earth barycentre directions per timestep, body-fixed.

    Same conventions as P2's ephemeris bake: spkpos IAU_MOON with 'LT'
    (retarded position — shadow geometry), one spkpos per body per step.
    Returns dict of (T,) float64 arrays; subsolar lat/lon recorded too so
    the artifact documents its astronomy.
    """
    frames.load_kernels()
    sun_u = np.empty((count, 3))
    earth_u = np.empty((count, 3))
    earth_d = np.empty(count)
    et = np.empty(count)

    for i in range(count):
        e = et_start + i * step_s
        et[i] = e
        s = np.asarray(frames.to_body_fixed("SUN", e, abcorr="LT"), float)
        ev = np.asarray(frames.to_body_fixed("EARTH", e, abcorr="LT"), float)
        d = float(np.linalg.norm(ev))
        earth_d[i] = d
        sun_u[i] = s / np.linalg.norm(s)
        earth_u[i] = ev / d
        if log_every and (i + 1) % log_every == 0:
            print(f"    ephemeris {i + 1}/{count}", flush=True)

    return {"et": et, "sun_u": sun_u, "earth_u": earth_u,
            "earth_d_km": earth_d}


def mock_ephem_table(acs):
    """Test double: acs = list of (elev_deg, az_deg) or
    (elev_deg, az_deg, earth_elev_deg, earth_az_deg) tuples, given in the
    ENU frame of lat=-89.99, lon=0. Built from explicit ENU geometry so it
    is an INDEPENDENT construction the engine must decode back."""
    lat = math.radians(-89.99)
    lon = 0.0
    n = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon),
                  math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon),
                      -math.sin(lat) * math.sin(lon), math.cos(lat)])

    def dir_from(elev_deg, az_deg):
        e = math.radians(elev_deg)
        a = math.radians(az_deg)
        d = (math.cos(e) * (math.cos(a) * north + math.sin(a) * east)
             + math.sin(e) * n)
        return d / np.linalg.norm(d)

    T = len(acs)
    tab = {"et": np.arange(T, dtype=float),
           "sun_u": np.array([dir_from(a[0], a[1]) for a in acs]),
           "earth_u": np.array([dir_from(a[2] if len(a) > 2 else 60.0,
                                         a[3] if len(a) > 3 else 0.0)
                                for a in acs]),
           "earth_d_km": np.full(T, 384400.0)}
    return tab


# ---------------------------------------------------------------------------
# the time pass — Sun + Earth accumulators, vectorised over pixels
# ---------------------------------------------------------------------------
def _init_acc(P):
    acc = {}
    f32 = lambda: np.zeros(P, dtype=np.float32)
    i32 = lambda: np.zeros(P, dtype=np.int32)
    acc.update(lit_n=i32(), lit_cur=i32(), lit_max=i32(),
               dark_cur=i32(), dark_max=i32(),
               eany_n=i32(), eany_cur=i32(), eany_max=i32(),
               efull_n=i32(), efull_cur=i32(), efull_max=i32(),
               ever_any=np.zeros(P, dtype=bool))
    return acc


def map_time_pass(grid, H, ephem, progress_every=1000):
    """Accumulate illumination + Earth-visibility statistics over `ephem`'s
    time grid. Returns accumulator dict (fractional planes normalised by
    the caller). Per timestep the work is ~15 vector ops over P pixels."""
    P = grid.count
    B = H.shape[1]
    bin_deg = 360.0 / B
    T = len(ephem["et"])

    n = grid.n
    east = grid.east
    north = grid.north
    ok = grid.ok
    r_km = np.where(ok, grid.r_m, MOON_R_M) / 1000.0

    valid = ok.astype(bool)

    acc = _init_acc(P)
    bin_base = np.arange(P) * B
    rows = np.arange(P)

    t0 = time_mod.monotonic()
    for i in range(T):
        su = ephem["sun_u"][i]
        eu = ephem["earth_u"][i]
        D = ephem["earth_d_km"][i]

        # --- Sun (point-source direction is topocentric for all purposes)
        c_s = n @ su
        elev_s = np.degrees(np.arcsin(np.clip(c_s, -1.0, 1.0)))
        az_s = np.degrees(np.arctan2(east @ su, north @ su)) % 360.0
        b_s = (az_s / bin_deg).astype(np.int64)
        b_s = np.clip(b_s, 0, B - 1)
        h_s = H[rows, b_s]
        lit = (elev_s > h_s) & valid

        a = acc
        a["lit_n"] += lit
        a["lit_cur"] = np.where(lit, a["lit_cur"] + 1, 0)
        a["lit_max"] = np.maximum(a["lit_max"], a["lit_cur"])
        a["dark_cur"] = np.where(lit, 0, a["dark_cur"] + 1)
        a["dark_max"] = np.maximum(a["dark_max"], a["dark_cur"])

        # --- Earth, fully topocentric
        c_e = n @ eu
        sin_t = np.sqrt(np.clip(1.0 - c_e * c_e, 0.0, 1.0))
        elev_e = np.degrees(np.arctan2(D * c_e - r_km, D * sin_t))
        az_e = np.degrees(np.arctan2(east @ eu, north @ eu)) % 360.0
        b_e = np.clip((az_e / bin_deg).astype(np.int64), 0, B - 1)
        h_e = H[rows, b_e]
        margin = elev_e - h_e
        disc_r = math.degrees(math.asin(min(1.0, EARTH_R_KM / D)))
        any_vis = (margin > -disc_r) & valid
        full_vis = (margin > disc_r) & valid

        a["eany_n"] += any_vis
        a["efull_n"] += full_vis
        a["ever_any"] |= any_vis
        a["eany_cur"] = np.where(any_vis, a["eany_cur"] + 1, 0)
        a["eany_max"] = np.maximum(a["eany_max"], a["eany_cur"])
        a["efull_cur"] = np.where(full_vis, a["efull_cur"] + 1, 0)
        a["efull_max"] = np.maximum(a["efull_max"], a["efull_cur"])

        if progress_every and (i + 1) % progress_every == 0:
            el = time_mod.monotonic() - t0
            print(f"    time pass {(i + 1) / T * 100:5.1f}%  "
                  f"({el:.0f}s elapsed, eta {el / (i + 1) * (T - i - 1):.0f}s)",
                  flush=True)

    acc["lit_frac"] = acc["lit_n"] / float(T)
    acc["frac_any"] = acc["eany_n"] / float(T)
    acc["frac_full"] = acc["efull_n"] / float(T)
    return acc


# ---------------------------------------------------------------------------
# artifact I/O
# ---------------------------------------------------------------------------
def bake_map(product, region, grid, acc, ephem, span_days, step_min,
             az_bins, step_m, max_dist_km, far_frac, out_dir=OUT_DIR,
             span_label=None):
    """Write artifacts/maps/<region>_<product>_<days>d.bin. Deterministic:
    fixed plane order, fixed dtypes, fixed iteration order, no RNG."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    days = int(round(span_days))
    stem = f"{region}_{product.lower()}_{days}d"
    out = out_dir / f"{stem}.bin"

    if span_label is None:
        if abs(span_days - DRACONIC_DAYS) < 1.0:
            span_label = (f"full {DRACONIC_YEARS:g}-year draconic cycle "
                          f"({DRACONIC_DAYS:.0f} d)")
        else:
            span_label = (f"LABELLED PARTIAL: {span_days:.2f} d sampled — "
                          f"NOT the {DRACONIC_YEARS:g}-yr draconic cycle; "
                          f"PSR/dark-run claims are valid for this span only")
    label_b = span_label.encode()

    W, Hh = grid.width, grid.height
    ok = grid.ok.astype(bool)

    if product == "ILLU":
        planes = [
            ok.astype(np.uint8).reshape(Hh, W).ravel(),
            np.where(ok, grid.z_m, 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
            np.where(ok, acc["lit_frac"], 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
            # run of R consecutive samples claims (R-1) intervals of
            # continuously measured time — the honest conservatif claim
            np.where(ok, np.clip(acc["lit_max"] - 1, 0, None)
                     * step_min / 60.0, 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
            np.where(ok, np.clip(acc["dark_max"] - 1, 0, None)
                     * step_min / 60.0, 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
            np.where(ok, far_frac, 0.0).astype("<f4").reshape(Hh, W).ravel(),
        ]
    else:
        planes = [
            ok.astype(np.uint8).reshape(Hh, W).ravel(),
            np.where(ok, grid.z_m, 0.0).astype("<f4").reshape(Hh, W).ravel(),
            np.where(ok, acc["ever_any"].astype(np.uint8), 0
                     ).astype(np.uint8).reshape(Hh, W).ravel(),
            np.where(ok, acc["frac_any"], 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
            np.where(ok, np.clip(acc["eany_max"] - 1, 0, None)
                     * step_min / 60.0, 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
            np.where(ok, acc["frac_full"], 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
            np.where(ok, np.clip(acc["efull_max"] - 1, 0, None)
                     * step_min / 60.0, 0.0).astype(
                "<f4").reshape(Hh, W).ravel(),
        ]

    hdr = (struct.pack("<8sH4s16s", MAGIC, VERSION, product.encode(),
                       region.encode()[:16])
           + struct.pack("<dddI", span_days, step_min, grid.grid_m, az_bins)
           + struct.pack("<dd", step_m, max_dist_km)
           + struct.pack("<d", float(ephem["et"][0]))
           + struct.pack("<I", len(ephem["et"]))
           + struct.pack("<II", W, Hh)
           + struct.pack("<H", len(label_b)) + label_b)
    body = b"".join(np.ascontiguousarray(p).tobytes() for p in planes)
    out.write_bytes(hdr + body)

    png = out_dir / f"{stem}.png"
    write_png(png, colorize(product, planes, Hh, W, ok))
    return out


def colorize(product, planes, Hh, W, ok):
    """Offline-first pretty plane (web view uses artifacts directly)."""
    rgb = np.full((Hh * W, 3), 170, dtype=np.uint8)      # unknown = grey
    if product == "ILLU":
        lit = planes[2]
        dark_long = planes[4]
        # dark over the whole labelled span -> PSR-labelled deep blue
        psr = ok & (planes[0] == 1) & (lit <= 1e-9)
        rgb[psr] = (16, 12, 64)
        litpx = ok.reshape(-1) & ~psr
        t = np.clip(lit, 0.0, 1.0)[ok]
        rgb[ok.reshape(-1)] = np.stack(
            [40 + 215 * t, 60 + 195 * t, 120 - 100 * t], axis=1).astype(
            np.uint8)
        rgb[ok.reshape(-1) & (dark_long > 0) & (lit.reshape(-1) < 0.02)] = \
            (30, 30, 90)
        _ = dark_long
    else:
        fany = planes[3]
        ever = (planes[2] == 1) & ok
        full = planes[5]
        t = np.clip(fany, 0.0, 1.0)[ok]
        rgb[ok.reshape(-1)] = np.stack(
            [30 + 225 * t, 90 + 165 * t, 110 + 145 * t], axis=1).astype(
            np.uint8)
        rgb[ok.reshape(-1) & ~ever] = (8, 28, 52)
        hot = ok.reshape(-1) & (full.reshape(-1) > 0.5)
        rgb[hot] = np.clip(rgb[hot].astype(int) + 25, 0, 255).astype(np.uint8)
    rgb[~ok] = 170
    return rgb.reshape(Hh, W, 3)


def read_map(path):
    """Parse a LUNAMAP artifact back into planes + header dict."""
    data = Path(path).read_bytes()
    off = 0
    magic, ver, product, region = struct.unpack_from("<8sH4s16s", data, off)
    off += struct.calcsize("<8sH4s16s")
    if magic != MAGIC:
        raise ValueError(f"{path}: bad magic {magic!r}")
    if ver != VERSION:
        raise ValueError(f"{path}: unsupported version {ver}")
    (span_days, step_min, grid_m, az_bins) = struct.unpack_from("<dddI",
                                                                data, off)
    off += struct.calcsize("<dddI")
    step_m, max_dist_km = struct.unpack_from("<dd", data, off)
    off += struct.calcsize("<dd")
    (start_et,) = struct.unpack_from("<d", data, off)
    off += struct.calcsize("<d")
    (samples,) = struct.unpack_from("<I", data, off)
    off += struct.calcsize("<I")
    (W, Hh) = struct.unpack_from("<II", data, off)
    off += struct.calcsize("<II")
    (llen,) = struct.unpack_from("<H", data, off)
    off += struct.calcsize("<H")
    label = data[off:off + llen].decode()
    off += llen

    P = W * Hh
    hdr = {
        "product": product.decode().strip("\0"),
        "region": region.decode().rstrip("\0"),
        "span_days": span_days, "step_min": step_min, "grid_m": grid_m,
        "az_bins": az_bins, "step_m": step_m, "max_dist_km": max_dist_km,
        "start_et": start_et, "samples": samples,
        "width": W, "height": Hh, "span_label": label,
    }
    names = ILLU_PLANES if hdr["product"] == "ILLU" else ERTH_PLANES
    planes = {}
    for nm in names:
        if nm == "cov" or nm in ("ever_any",):
            planes[nm] = np.frombuffer(data, dtype=np.uint8, count=P,
                                       offset=off).reshape(Hh, W)
            off += P
        else:
            planes[nm] = np.frombuffer(data, dtype="<f4", count=P,
                                       offset=off).reshape(Hh, W)
            off += 4 * P
    hdr["planes"] = planes
    hdr["_end"] = off
    return hdr


# ---------------------------------------------------------------------------
# product 3 — per-site time series + verdicts
# ---------------------------------------------------------------------------
def horizon_lookup_from_artifact(site_id, out_dir=ROOT / "artifacts" / "horizon"):
    prof = horizon_mod.load_horizon(site_id, out_dir=out_dir)
    return lambda az: horizon_mod.horizon_at(prof, az)


def _series_rows(site, ephem, horizon_lookup, disc_samples):
    """Row arrays for one site over `ephem`'s grid. Point elevation/azimuth
    is computed once per timestep; extended-disc metrics come from P3's
    solar_disc disc_metrics on the SAME horizon profile, so the app's
    picture and these numbers share one source."""
    lat, lon = site["lat"], site["lon"]
    n = np.asarray(frames.surface_normal(lat, lon), float)
    L = math.radians(lat)
    LO = math.radians(lon)
    east = np.array([-math.sin(LO), math.cos(LO), 0.0])
    north = np.array([-math.sin(L) * math.cos(LO),
                      -math.sin(L) * math.sin(LO), math.cos(L)])

    sun_u = ephem["sun_u"]
    earth_u = ephem["earth_u"]
    D = ephem["earth_d_km"]

    sun_elev = np.degrees(np.arcsin(np.clip(sun_u @ n, -1.0, 1.0)))
    sun_az = np.degrees(np.arctan2(sun_u @ east, sun_u @ north)) % 360.0

    c_e = earth_u @ n
    r_km = MOON_R_M / 1000.0           # site on the reference sphere; the
    # per-site height correction is inside the DEM horizon already
    elev_e = np.degrees(np.arctan2(
        D * c_e - r_km, D * np.sqrt(np.clip(1 - c_e * c_e, 0.0, None))))
    az_e = np.degrees(np.arctan2(earth_u @ east, earth_u @ north)) % 360.0

    earth_r_deg = 0.5 * np.degrees(2.0 * np.arcsin(
        np.clip(EARTH_R_KM / D, 0.0, 1.0)))

    T = len(sun_elev)
    sun_frac = np.empty(T)
    sun_flux = np.empty(T)
    earth_frac = np.empty(T)
    earth_flux = np.empty(T)
    for i in range(T):
        sm = solar_disc.sun_metrics(float(sun_elev[i]), float(sun_az[i]),
                                    horizon_lookup, n=disc_samples)
        dm = solar_disc.disc_metrics(float(elev_e[i]), float(az_e[i]),
                                     float(earth_r_deg[i]),
                                     horizon_lookup, n=disc_samples)
        sun_frac[i] = sm["disc_fraction"]
        sun_flux[i] = sm["incident_flux"]
        earth_frac[i] = dm["disc_fraction"]
        earth_flux[i] = dm["incident_flux"]
        if i and i % 2000 == 0:
            print(f"    series {i + 1}/{T}", flush=True)

    return {
        "sun_elev_deg": sun_elev, "sun_az_deg": sun_az,
        "sun_disc_frac": sun_frac, "sun_flux": sun_flux,
        "earth_elev_deg": elev_e, "earth_az_deg": az_e,
        "earth_disc_frac": earth_frac, "earth_flux": earth_flux,
        "earth_disc_radius_deg": earth_r_deg,
    }


def site_time_series(site, ephem, step_min, horizon_dir=ROOT / "artifacts"
                     / "horizon", disc_samples=256, out_dir=OUT_DIR,
                     span_days=None, span_label=None, timezone_note="UTC"):
    """Hourly (or whatever step) Sun/Earth rows for the P5 app.

    The honesty block travels with the file: span, span_label, method and
    the exact P3 horizon artifact used. UI must render span_label verbatim.
    """
    sid = site["id"]
    out_dir = Path(out_dir) / "timeseries"
    out_dir.mkdir(parents=True, exist_ok=True)
    days = int(round(span_days)) if span_days is not None else \
        int(round(len(ephem["et"]) * step_min / 1440.0))
    out = out_dir / f"{sid}_{days}d.json"

    horizon_lookup = horizon_lookup_from_artifact(sid, out_dir=horizon_dir)
    rows = _series_rows(site, ephem, horizon_lookup, disc_samples)

    T = len(ephem["et"])
    lit = rows["sun_disc_frac"] > 0.0
    runs_lit = _runs_hours(lit, step_min)
    runs_dark = _runs_hours(~lit, step_min)
    any_vis = rows["earth_disc_frac"] > 0.0
    runs_eany = _runs_hours(any_vis, step_min)
    full_vis = rows["earth_disc_frac"] >= (1.0 - 0.5 / disc_samples)
    runs_efull = _runs_hours(full_vis, step_min)

    payload = {
        "meta": {
            "site_id": sid, "site_name": site["name"],
            "site_lat": site["lat"], "site_lon": site["lon"],
            "span_days": span_days,
            "span_label": span_label,
            "step_min": step_min, "samples": int(T),
            "start_utc": frames.et_to_utc(float(ephem["et"][0]), "ISOC"),
            "end_utc": frames.et_to_utc(float(ephem["et"][-1]), "ISOC"),
            "timezone": timezone_note,
            "horizon_source": f"artifacts/horizon/{sid}.bin (P3, 720 bins)",
            "disc_samples": disc_samples,
            "method": ("solar_disc equal-solid-angle disc metrics vs "
                       "P3 max-per-bin DEM horizon; ephemeris de440s+"
                       "moon_pa PCK via SpiceyPy (abcorr LT)"),
            "honesty": ("A partial span is LABELLED PARTIAL and never "
                        "represents an 18.6-yr draconic PSR claim."),
        },
        "verdict": {
            "lit_frac_at_disc": float(round(
                (rows["sun_disc_frac"] > 0.0).mean(), 6)),
            "longest_lit_h": runs_lit["max_hours"],
            "longest_dark_h": runs_dark["max_hours"],
            "earth_any_frac": float((rows["earth_disc_frac"] > 0.0).mean()),
            "earth_longest_any_h": runs_eany["max_hours"],
            "earth_longest_full_h": runs_efull["max_hours"],
            "max_sun_elev_deg": float(round(float(rows["sun_elev_deg"].max()), 4)),
            "max_earth_elev_deg": float(round(float(rows["earth_elev_deg"].max()), 4)),
        },
        "runs": {
            "longest_lit": {
                "hours": runs_lit["max_hours"],
                "start_utc": (frames.et_to_utc(
                    float(ephem["et"][runs_lit["max_start"]]), "ISOC")
                    if runs_lit["max_start"] is not None else None),
            },
            "longest_dark": {
                "hours": runs_dark["max_hours"],
                "start_utc": (frames.et_to_utc(
                    float(ephem["et"][runs_dark["max_start"]]), "ISOC")
                    if runs_dark["max_start"] is not None else None),
            },
            "earth_longest_any": {
                "hours": runs_eany["max_hours"],
                "start_utc": (frames.et_to_utc(
                    float(ephem["et"][runs_eany["max_start"]]), "ISOC")
                    if runs_eany["max_start"] is not None else None),
            },
        },
        "rows": {
            "et_tdb": [round(float(e), 3) for e in ephem["et"]],
            "sun_elev_deg": [round(float(v), 4) for v in rows["sun_elev_deg"]],
            "sun_az_deg": [round(float(v), 3) for v in rows["sun_az_deg"]],
            "sun_disc_frac": [round(float(v), 4) for v in rows["sun_disc_frac"]],
            "sun_flux": [round(float(v), 4) for v in rows["sun_flux"]],
            "earth_elev_deg": [round(float(v), 4) for v in rows["earth_elev_deg"]],
            "earth_az_deg": [round(float(v), 3) for v in rows["earth_az_deg"]],
            "earth_disc_frac": [round(float(v), 4) for v in rows["earth_disc_frac"]],
            "earth_flux": [round(float(v), 4) for v in rows["earth_flux"]],
        },
    }
    out.write_text(json.dumps(payload, indent=1))
    return out, payload


def _runs_hours(flags, step_min):
    """Run-length summary of a boolean series: longest run + start index.

    Duration convention (same as the map planes): a run of R consecutive
    samples claims (R-1) intervals of continuously sampled time.
    """
    best_len = 0
    best_at = None
    cur = 0
    n = len(flags)
    for i in range(n):
        if flags[i]:
            cur += 1
            if cur > best_len:
                best_len = cur
                best_at = i - cur + 1
        else:
            cur = 0
    hours = float(max(best_len - 1, 0) * step_min / 60.0) if best_len else 0.0
    return {"max_hours": hours,
            "max_start": int(best_at) if best_at is not None else None,
            "count": int(best_len), "n": n}


def site_fullcycle_runs(site, ephem_point, step_min, horizon_lookup,
                        out_dir=OUT_DIR):
    """18.6-yr PER-SITE verdict without a big map: point-source Sun runs +
    Earth runs over the full draconic cycle, written as interval lists
    (light: cheap at P=1 per site — this is where honesty says the full
    cycle is affordable).

    Runs are computed from the geometric centre of the disc (the numbers
    Mazarico 2011 style cross-checks use); the labelled-disc series over a
    1-year grid lives in site_time_series.
    """
    sid = site["id"]
    out_dir = Path(out_dir) / "timeseries"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sid}_fullcycle_runs.json"

    lat, lon = site["lat"], site["lon"]
    n = np.asarray(frames.surface_normal(lat, lon), float)
    L = math.radians(lat)
    LO = math.radians(lon)
    east = np.array([-math.sin(LO), math.cos(LO), 0.0])
    north = np.array([-math.sin(L) * math.cos(LO),
                      -math.sin(L) * math.sin(LO), math.cos(L)])

    su, eu, D = ephem_point["sun_u"], ephem_point["earth_u"], \
        ephem_point["earth_d_km"]
    T = len(D)
    sun_elev = np.degrees(np.arcsin(np.clip(su @ n, -1.0, 1.0)))
    sun_az = np.degrees(np.arctan2(su @ east, su @ north)) % 360.0
    c_e = eu @ n
    r_km = MOON_R_M / 1000.0
    elev_e = np.degrees(np.arctan2(
        D * c_e - r_km, D * np.sqrt(np.clip(1 - c_e * c_e, 0.0, None))))
    az_e = np.degrees(np.arctan2(eu @ east, eu @ north)) % 360.0

    h_s = horizon_lookup(sun_az)
    h_e = horizon_lookup(az_e)
    lit = sun_elev > h_s
    e_vis = elev_e > h_e

    payload = {
        "meta": {
            "site_id": sid,
            "span_days": float(T * step_min / 1440.0),
            "span_label": (f"full {DRACONIC_YEARS:g}-yr draconic cycle "
                           f"({DRACONIC_DAYS:.0f} d), point-source "
                           "geometric metric"),
            "step_min": step_min, "samples": int(T),
            "start_utc": frames.et_to_utc(float(ephem_point["et"][0]), "ISOC"),
            "note": "interval lists in hours from start_utc; lit = sun "
                    "elevation above P3 720-bin DEM horizon",
        },
        "verdict": {
            "lit_frac": float(lit.mean()),
            "longest_lit_h": float(_runs_hours(lit, step_min)["max_hours"]),
            "longest_dark_h": float(_runs_hours(~lit, step_min)["max_hours"]),
            "earth_vis_frac": float(e_vis.mean()),
            "earth_longest_vis_h": float(_runs_hours(e_vis, step_min)
                                         ["max_hours"]),
            "earth_longest_gone_h": float(_runs_hours(~e_vis, step_min)
                                          ["max_hours"]),
        },
    }
    out.write_text(json.dumps(payload, indent=1))
    return out, payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_region_map(region, span_days, step_min, grid_m=None, az_bins=None,
                     full_cycle=False, log_every=1, out_dir=OUT_DIR):
    """Full bake of one region: horizon march + Sun/Earth time pass + files.
    Deterministic given the same arguments."""
    grid, dem = make_grid(region, grid_m=grid_m)
    az_bins = az_bins or DEFAULT_MAP_AZ_BINS
    P = grid.count
    valid = grid.ok
    print(f"[{region}] grid {grid.width}x{grid.height} = {P} px "
          f"at {grid.grid_m:g} m  ({valid.sum()} valid)  "
          f"tile {dem.tags.get('source_tile', '?')}")

    t0 = time_mod.monotonic()
    print(f"  horizon march: {az_bins} az bins, {DEFAULT_MAP_STEP_M:g} m step, "
          f"{DEFAULT_MAP_MAX_DIST_KM:g} km")
    H, far_frac = march_map_horizons(grid, dem, az_bins=az_bins,
                                     step_m=DEFAULT_MAP_STEP_M,
                                     max_dist_km=DEFAULT_MAP_MAX_DIST_KM,
                                     log_every=log_every)
    print(f"  horizon march done in {time_mod.monotonic() - t0:.1f}s")

    step_s = step_min * 60.0
    count = int(round(span_days * 86400.0 / step_s)) + 1
    et_start = frames.utc_to_et("2026-10-01 00:00:00 UTC")
    print(f"  ephemeris: {count} samples @ {step_min:g} min "
          f"({span_days:.2f} d labelled)")
    t0 = time_mod.monotonic()
    ephem = build_ephem_table(et_start, step_s, count, log_every=2000)
    print(f"  ephemeris done in {time_mod.monotonic() - t0:.1f}s")

    t0 = time_mod.monotonic()
    acc = map_time_pass(grid, H, ephem, progress_every=500)
    print(f"  time pass done in {time_mod.monotonic() - t0:.1f}s")

    days = int(round(span_days))
    out_illum = bake_map("ILLU", region, grid, acc, ephem, span_days,
                         step_min, az_bins, DEFAULT_MAP_STEP_M,
                         DEFAULT_MAP_MAX_DIST_KM, far_frac,
                         out_dir=out_dir)
    out_earth = bake_map("ERTH", region, grid, acc, ephem, span_days,
                         step_min, az_bins, DEFAULT_MAP_STEP_M,
                         DEFAULT_MAP_MAX_DIST_KM, far_frac,
                         out_dir=out_dir)
    for p in (out_illum, out_earth):
        print(f"  -> {p.relative_to(ROOT)} ({p.stat().st_size / 1e6:.1f} MB)"
              f" + .png")

    return out_illum, out_earth


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Bake LUNAPOLE P4 map products + per-site series")
    ap.add_argument("--region", default="polecap",
                    help="map region key (polecap|southcap)")
    ap.add_argument("--grid-m", type=float, default=None)
    ap.add_argument("--az-bins", type=int, default=DEFAULT_MAP_AZ_BINS)
    ap.add_argument("--span-days", type=float, default=365.25,
                    help="labelled time span (default: 1 year)")
    ap.add_argument("--step-min", type=float, default=60.0)
    ap.add_argument("--full-cycle", action="store_true",
                    help="bake the full 18.6-yr draconic span (plan a "
                         "coarser grid / longer runtime)")
    ap.add_argument("--site", help="per-site time series for one site id")
    ap.add_argument("--series-span-days", type=float, default=365.25)
    ap.add_argument("--series-disc-samples", type=int, default=256)
    ap.add_argument("--skip-map", action="store_true",
                    help="only run the per-site series")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)

    if args.full_cycle:
        span_days = DRACONIC_DAYS
    else:
        span_days = args.span_days

    did_something = False
    if not args.skip_map:
        if args.full_cycle:
            print("FULL-CYCLE MAP: heavy bake (18.6 yr). If the clock wins, "
                  "ship the labelled 1-year map instead (spec stop rule).")
        build_region_map(args.region, span_days, args.step_min,
                         grid_m=args.grid_m, az_bins=args.az_bins,
                         out_dir=args.out_dir)
        did_something = True

    sites = load_sites()
    if args.site:
        sites = [s for s in sites if s["id"] == args.site]
        if not sites:
            print(f"unknown site id: {args.site}")
            return 2
        did_something = True
        site = sites[0]
        step_s = args.step_min * 60.0
        series_days = DRACONIC_DAYS if (args.full_cycle and args.skip_map) \
            else args.series_span_days
        count = int(round(series_days * 86400.0 / step_s)) + 1
        et_start = frames.utc_to_et("2026-10-01 00:00:00 UTC")
        ephem = build_ephem_table(et_start, step_s, count, log_every=0)
        print(f"  site series: {site['id']}  {series_days:.2f} d @ "
              f"{args.step_min:g} min ({count} samples)")

        if args.full_cycle and args.skip_map:
            out, payload = site_fullcycle_runs(site, ephem, args.step_min,
                                               horizon_lookup_from_artifact(
                                                   site["id"]),
                                               out_dir=args.out_dir)
            v = payload["verdict"]
            print(f"  {site['id']}: full-cycle runs -> {out.relative_to(ROOT)}")
            print(f"    lit_frac {v['lit_frac']:.3f}  "
                  f"longest lit {v['longest_lit_h']:.0f} h "
                  f"({v['longest_lit_h'] / 24:.1f} d)  "
                  f"longest dark {v['longest_dark_h']:.0f} h")
            print(f"    earth vis frac {v['earth_vis_frac']:.3f}  "
                  f"longest vis {v['earth_longest_vis_h']:.0f} h  "
                  f"longest gone {v['earth_longest_gone_h']:.0f} h")
        else:
            span_lbl = (f"LABELLED PARTIAL: {series_days:.2f} d sampled — "
                        f"NOT the full {DRACONIC_YEARS:g}-yr draconic cycle"
                        if abs(series_days - DRACONIC_DAYS) > 1.0 else
                        f"full {DRACONIC_YEARS:g}-yr draconic cycle "
                        f"({DRACONIC_DAYS:.0f} d)")
            out, payload = site_time_series(
                site, ephem, args.step_min,
                disc_samples=args.series_disc_samples,
                out_dir=args.out_dir, span_days=series_days,
                span_label=span_lbl)
            v = payload["verdict"]
            print(f"  {site['id']}: verdict -> {out.relative_to(ROOT)}")
            print(f"    lit_frac(disc) {v['lit_frac_at_disc']:.3f}  "
                  f"longest lit {v['longest_lit_h']:.1f} h  "
                  f"longest dark {v['longest_dark_h']:.1f} h")
            print(f"    earth any-frac {v['earth_any_frac']:.3f}  "
                  f"longest any {v['earth_longest_any_h']:.1f} h  "
                  f"longest full {v['earth_longest_full_h']:.1f} h")

    if not did_something:
        print("nothing requested (pass --region/--site; see --help)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
