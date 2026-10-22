# P4 — map products: how they were built

`build/lunapole/maps.py` bakes the three P4 deliverables from TEAM_SPLIT:

1. **Illumination / permanent-shadow map** — `artifacts/maps/<region>_illum_<days>d.bin` (+ `.png`)
2. **Earth-visibility map** — `artifacts/maps/<region>_earth_<days>d.bin` (+ `.png`)
3. **Per-site time series** — `artifacts/maps/timeseries/<site>_<days>d.json` and `<site>_fullcycle_runs.json`

Nothing here re-derives physics: the horizon march imports its formulas
from `horizon.py` (P3), the disc metrics come from `solar_disc.py` (P3),
and the ephemeris conventions are the ones `ephemeris.py` (P2) set
(spkpos IAU_MOON, abcorr `LT` — the retarded position, because that is
where shadow geometry actually points).

## Method

**Horizon per map pixel.** Same rule as P3: walk every 3° azimuth bin
(default `--az-bins 120`, recorded in the header) outward on the sphere,
sample the LOLA tile every 250 m up to 25 km, and keep the **maximum**
terrain elevation angle per bin. Never a mean — the nearest ridge that
hides the Sun decides, not the average view. The batched march is
pixel-block × azimuth-bin × distance-chunk, and `verify_maps` proves it
is bin-for-bin identical to P3's per-site march (worst |Δ| = 2.6e-11° on
synthetic terrain at matched resolution).

**Illumination accounting.** Per timestep, per pixel: Sun elevation =
asin(sub-solar direction · pixel normal); lit iff elevation > horizon at
the Sun's azimuth bin (nearest bin, labelled — P3's per-site 720-bin
interpolated lookup stays the per-site source of truth). "Illuminated"
is the geometric **centre** of the solar disc, Mazarico-style.
Disc-averaged penumbra metrics are computed per site in the time series
(product 3); per-pixel disc integration is deliberately skipped — it
would multiply the time loop by ~256 for numbers the app shows only per
site anyway.

**Earth visibility is fully topocentric, per pixel.** The exact closed
form, derived once and verified against `earth.py`'s vector path
(≤1e-9° in the verifier):

    elev_topo = atan2(D·cosθ − r,  D·sinθ)      θ = pixel—sub-Earth angle
                                                r = pixel radius incl. DEM z

The 0.259° parallax and the per-pixel height both fall out for free.
Two regimes are stored: `ever_any` / `frac_any` (margin > −disc radius —
a limb peeking over the ridge counts, which is the normal case for a
1.9° disc) and `frac_full` / `long_full_h` (margin > +disc radius).

**Run-length convention.** A run of R consecutive samples claims
(R−1) intervals of continuously sampled time. The planes and the JSON
verdicts use the same conservative rule.

## Honesty rules, enforced

* Every artifact header carries `span_days`, `step_min`, `az_bins`,
  `step_m`, `max_dist_km` and a UTF-8 `span_label`. A 1-year bake is
  labelled `LABELLED PARTIAL: … NOT the 18.6-yr draconic cycle …`, verbatim,
  and `verify_maps` refuses artifacts whose label lies. A full-cycle
  bake is labelled as such. The UI must render the label, not a
  prettier version of it.
* Pixels outside the tile or on invalid DEM values are **UNKNOWN**
  (`cov = 0` plane, grey in the PNG), never "permanently dark".
  Fail-closed for shading would *over*-state PSRs — the opposite of
  what fail-closed means for a map.
* `far_frac` records, per pixel, the fraction of horizon bins whose ray
  stayed inside measured terrain to max_dist. A low far_frac means the
  horizon for that pixel was cut short by data, not by physics.

## Artifact format (little-endian)

    header magic 8s b'LUNAMAP\0'
           version H
           product 4s  'ILLU' | 'ERTH'
           region  16s NUL-padded
           span_days f64, step_min f64, grid_m f64, az_bins u32
           step_m f64, max_dist_km f64, start_et f64
           samples u32, width u32, height u32
           label H + UTF-8 bytes

Planes, row-major (row 0 = +y = lon-180 edge, same orientation as the
GeoTIFF crops), u1 or f4 as listed in the module docstring:
ILLU: cov, dem_elev, lit_frac, long_lit_h, long_dark_h, far_frac —
ERTH: cov, dem_elev, ever_any, frac_full, long_any_h, frac_any,
long_full_h (order as in `ERTH_PLANES`).

## Traps hit while building this (already paid for)

* The march's ray samples are **unit directions** — latitude comes from
  `arcsin(p_z)` directly. Dividing `p_z` by the Moon radius (as one
  would for a position vector) collapses every sample onto the equator
  and everything fail-closes to +90°: whole-map shadow. Caught by the
  synthetic flat test in `verify_maps`.
* The spherical dip is **negative** (−0.1649° at 10 km, −0.00082° at
  250 m). A test comparing horizons to a positive "dip" will pass on
  broken code and fail on correct code.
* Mock ephemerides are built in ONE reference ENU frame; each pixel
  decodes azimuths in its OWN local frame. A wall test that expects one
  half of the map to be lit on a global "east/west" flip is testing the
  mock frame, not the engine — the honest invariant is bin-for-bin
  conformance with P3's profile plus a per-pixel recomputation of the
  lit-frac assembly (`verify_maps::test_wall`).
* Edge pixels legitimately have no-data bins (their rays leave the
  raster): those bins are +90° by the fail-closed rule. Assertions about
  illumination must be restricted to pixels with `far_frac == 1`.

## Measured results (bakes of 2026-10-22)

**polecap 1-year bake** (grid 462×462 @ 320 m, 213,444 valid px, 120 az bins,
span 365.25 d @ 60 min, start 2026-10-01, ~13 min horizon march + ~13 min
time pass):

* 18.2 % of the valid pixels are dark over the whole labelled span
  (38,809 px) — the crater floors (Shackleton, de Gerlache, Faustini,
  Neuenschwander...), classic PSR pattern.
* lit_frac: median 0.197, max 0.984 (a 1,621 m summit at lat −87.17,
  lon 217.3, whose horizon never rises above 0°).
* far_frac: mean 0.794; 44 % of pixels march the full 25 km inside
  measured terrain (the rest exit the raster — their horizon bins are
  computed from what the tile contains, and the deficit is recorded).
* Earth map: **47.9 %** of pixels see at least a limb of Earth during the
  year; 41.2 % ever see the full disc. Best pixel sees the full disc for
  8,766 h — the whole labelled span.

**Per-site disc series** (`artifacts/maps/timeseries/`, 1 yr @ 60 min,
256-sample disc):

| site | lit frac (disc) | longest lit | longest dark | Earth any-frac | longest Earth |
|---|---|---|---|---|---|
| shackleton | 0.279 | 244 h | 511 h | 0.000 | — |
| de_gerlache | 0.000 | 0 h | 8,766 h (all) | 0.000 | — |
| haworth | 0.077 | 75 h | 2,821 h | 0.115 | 153 h (any) / 83 h (full) |
| nobile | 0.061 | 95 h | 5,627 h | 0.371 | 253 h (any) / 181 h (full) |

Full-cycle point runs (18.6 yr @ 120 min): shackleton lit 0.272, longest
lit 242 h; de_gerlache lit 0.000 (never lit in 18.6 yr — a real PSR);
haworth lit 0.063, Earth visible 21.4 % of the cycle; nobile lit 0.044,
Earth visible 34.0 % — gone for only 458 h at a time (best DTE
candidate of the four).

**Published-figure cross-checks** (see `verify_maps --real --mazarico`):
the literature basis for Shackleton is rim peaks lit ~80–90 % of the
year / interior in perpetual darkness (Mazarico 2011 heritage; Spudis
1995). Measured: 20.3 % of the 21-km footprint dark over the span, best
footprint pixel lit 0.855. The oft-quoted "240 continuous days at the
rim" is **not** attached to Shackleton in the sources we could check and
is treated as unverified; our best season-scale continuous run anywhere
in the polecap is 84 days (18.6-yr, best pixel).

**Honesty showcase** — the best-map pixel (lit 0.984 over the 2026–2027
labelled year) drops to **0.706 over the full 18.6-yr cycle**: the
2026-10 epoch sits in a favourable notch of the draconic cycle. This is
exactly why a 1-year map may never be labelled as PSR ground truth, and
why the full-cycle per-site runs exist in the verdict engine.

## Regenerating

    python3 scripts/fetch_dem.sh && python3 scripts/fetch_data.sh
    python3 scripts/crop_sites.py --radius-km 25
    python3 -m build.lunapole.horizon --all
    python3 -m build.lunapole.maps --region polecap            # 1 yr, labelled
    python3 -m build.lunapole.maps --region polecap --full-cycle   # heavy
    python3 -m build.lunapole.maps --skip-map --site shackleton --full-cycle

Determinism: same inputs → byte-identical artifacts and PNGs (fixed
plane order/dtypes, fixed iteration order, zlib level 6, no RNG).
