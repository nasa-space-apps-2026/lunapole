# LUNAPOLE — Six-Person Work Split

**Read first:** `VERIFICATION.md` (what's wrong) · `clps/constants.json` (true numbers) · `clps/sites.json` (true coordinates)

**Rule for everyone:** no number enters the codebase that isn't in `constants.json`. No coordinate enters that isn't in `sites.json`. The README has bad values — do not copy from it.

---

## Team

| # | Owner | Role | One-line job |
|---|---|---|---|
| P1 | *(assign)* | **Data** | Resolve DEM tiles, download everything, crop per site |
| P2 | *(assign)* | **Ephemeris** | DE440 bake: sub-solar, libration, Sun/Earth vectors |
| P3 | *(assign)* | **Horizon** | Far-field horizon engine + curvature + extended solar disc |
| P4 | *(assign)* | **Maps** | 18.6-yr illumination + Earth-visibility maps |
| P5 | *(assign)* | **App** | Three panels, timeline scrubber, verdict engine |
| P6 | *(assign)* | **Integration** | Artifact pipeline, offline bundling, tests, README, demo |

**Dependency rule:** P2 → P3 → P4 runs in sequence. P1 must land first because everything reads the DEM. P5 and P6 can start immediately against mock data.

---

## P1 — Data

**Owns:** everything downloaded; `data/` directory; crop outputs.

**DONE — data acquired and verified.** `bash scripts/fetch_dem.sh && bash scripts/fetch_data.sh`

| Tile | Coverage | Res | Size |
|---|---|---|---|
| `ldem_875s_10m.jp2` | 87.5S-90S | **10 m/px** | 62 MB |
| `ldem_85s_20m.jp2` | 85S-90S | 20 m/px | 76 MB |
| `ldem_80s_20m.jp2` | 80S-90S | 20 m/px | 255 MB |

Plus 4 SPICE kernels (44 MB). All 6 catalogue sites resolve against terrain —
verify with `python3 verify/verify_dem.py`.

**DONE — per-site crops.** `python3 scripts/crop_sites.py` produces
`artifacts/dem/<site_id>.tif` for all 6 sites (25 km radius, GeoTIFF, deflate).
`python3 scripts/verify_crops.py` — all checks pass (elevation plausible,
terrain varies, crop centred, tags match). Checksums + URLs in
`data/SOURCES.md`.

**Deliverable:** `artifacts/dem/<site_id>.tif` + a `data/SOURCES.md` with every URL and SHA-256.

**Test:** open a cropped DEM, confirm elevations are plausible (south pole range roughly −8,000 m to +4,000 m), and confirm the crop is centred on the right coordinates.

**Watch for:** `ldec_` vs `ldem_`. The LOLA polar products differ by two
characters: `ldem_` is elevation in metres, `ldec_` is observation COUNT per
pixel (0..13). A `ldec_` file opens cleanly with correct geometry and is
completely wrong terrain. `verify_dem.py` rejects it — don't bypass that check.

---

## P2 — Ephemeris

**Owns:** `build/lunapole/frames.py`, `build/lunapole/ephemeris.py`

**Produces:** for each site × each time step, the baked vectors. Using SpiceyPy against `de440s.bsp` + the lunar orientation PCK.

**Critical:** the Moon **librates**. A "fixed" lunar site isn't inertially fixed — handle libration through the PCK. The original spec's likely failure mode was treating sites as inertially fixed, which puts the subsolar point degrees off at the pole.

**Time discipline:** UTC→TDB for the ephemeris. Earth rotation is UT1/GMST, not TDB — don't mix.

**Deliverable:** `artifacts/ephemeris/<site>.bin` — subsolar lat/lon, sub-Earth lat/lon, Earth distance, Earth angular diameter.

**Test (non-negotiable):** compare computed subsolar point against JPL Horizons at ≥5 epochs, including two at libration extrema. Target error **< 0.01°**. This is the single most important test in the project — it's the thing that proves the physics is real.

**Bonus:** Mazarico 2011 found Shackleton rim gets ~240 days/year continuous sun. If our engine agrees, we have strong independent validation.

**Status: DONE (2026-10-13).** `build/lunapole/frames.py` + `build/lunapole/ephemeris.py`
built with SpiceyPy 8.3.0 against the four kernels. The non-negotiable gate passes:
`verify/verify_horizons.py` compares sub-solar and sub-Earth points against JPL
Horizons (`QUANTITIES='14,15'`, geocentric observer) at 5 epochs incl. 2 libration
extrema — **worst separation 0.0076° (sub-solar) / 0.0070° (sub-Earth), target <0.01°**.
`verify/verify_ephemeris.py` (local sanity) passes 12/12. Bake of the 3 P1 sites for
one synodic month @ 5-min steps (8 505 samples/site, 0.27 MB each) is deterministic
and struct round-trips against `frames.py`. Three real bugs were found and fixed on
the way — argument-order in `subpt()` (was computing the sub-LUNAR point on the
Sun), a sign error in every elevation computation (`acos−90` vs `90−acos`), and
monthly-sampling aliasing against the 29.53-d synodic sweep. Read
`docs/spice-gotchas.md` before touching any of this.

---

## P3 — Horizon engine

**Owns:** `build/lunapole/dem.py`, `horizon.py`, `solar_disc.py`, `earth.py`

**This is the technical heart.** Far-field horizon via max-per-azimuthal-bin, following Mazarico et al. 2011 (Icarus 209(2):634–641, doi:10.1016/j.icarus.2010.08.015 — citation verified correct).

**Two things the spec got wrong that you must not repeat:**

1. **Curvature is 6× stronger than stated.** At 30 km it's **259 m**, not 42.2 m. At 100 km, **2877 m**, not 469 m. Use `constants.json → CORRECTED_curvature_table`. Understating this systematically overestimates illumination.

2. **Use `max`, never `mean`, per azimuthal bin.** The first ridge that blocks the Sun is the only one that matters. A mean underestimates occlusion risk. (Mazarico 2011 validates this approach.)

**Extended solar disc:** sample the Sun's 0.5334° disc in equal-solid-angle, not as a point. At the pole, max elevation is 1.54° — the Sun's disc is a huge fraction of that, so penumbra matters enormously. Report three separate metrics: geometric above-horizon, disc fraction visible, and incident flux on an oriented panel.

**Deliverable:** `artifacts/horizon/<site>.bin` — 720 azimuth bins × elevation, plus occluding-obstacle distance and provenance.

**Tests:**
- Curvature at 30 km = 259 m
- Shadow length at 1.5424° = 37.20 × h
- **Far-field must never lower the horizon** vs near-field (more terrain can only occlude more). If this test fails you have a sign error.

**Status: DONE (2026-10-21).** `build/lunapole/dem.py` (terrain access),
`horizon.py` (max-per-bin march), `solar_disc.py` (equal-solid-angle
penumbra), `earth.py` (topocentric parallax + disc). Gate:
`verify/verify_horizon.py` passes **all** checks on synthetic terrain *and*
on the real crops — run it in ~7 s for four sites.

What the gate actually measured:

| Claim | Measured |
|---|---|
| Curvature at 30 / 100 km | **259.00 / 2887.07 m** (42.2 m is the 12.1 km value) |
| Shadow at 1.5424° | **37.138 × h** — constants.json's 37.20 is the 1.5400° rounding |
| Flat sphere horizon | local tangent (0.000°), dip −0.1649° at 10 km |
| Far-field vs near-field | **never negative** (worst Δ = 0.000e+00); gains up to **+20.8°** of horizon (Malapert), +13.6° at Shackleton |
| Determinism | two bakes byte-identical; artifact round-trips |
| Solar disc | centre on a flat horizon → **50.0 %** of the disc; 17.3 % of the whole polar range |
| Earth | parallax **−0.2520°** at Shackleton (limit 0.2590°), disc 1.8599° |

Per-site horizons (25 km crop, 720 bins, all 6 sites, ~6 s for the bake):

```
site           elevation range      median   far-field bins
shackleton     -8.71 .. +41.96 deg  +26.54   720/720
de_gerlache   +10.04 .. +45.06 deg  +15.78   720/720
haworth        -0.33 .. +14.17 deg   +8.24   710/720
nobile         +0.84 ..  +8.56 deg   +3.83   686/720
malapert       +3.14 .. +22.21 deg  +10.12   676/720
cabeus         +1.90 .. +33.11 deg  +11.35   676/720
```

A 40°+ horizon means the site is inside a crater looking at its own wall;
that is the measured DEM, not a bug. The `far-field bins N/720` counters are
the honesty requirement in action: a ray that leaves the 25 km crop stops
there and says so (`FLAG_EDGE`), it does not invent terrain.

**Scope note (honest limitation):** the crops are 25 km radius, so the
artifact never reaches the spec's 100 km. `max_dist_km` is recorded in the
header and the per-bin flags carry the coverage. Re-crop at
`--radius-km 100` when disk allows; the engine needs no change. See
`docs/horizon-notes.md` for the method, the format, and the traps.

---

## P4 — Maps

**Owns:** `build/lunapole/maps.py`; `artifacts/maps/`

**Products:**
1. Permanent-shadow / illumination map over the **18.6-year draconic cycle** — not 1 year, or you're lying about PSRs.
2. **Earth-visibility map** — the genuine differentiator. Which terrain can see Earth, ever.
3. Per-site time series.

**Honesty requirement (spec §6.5, non-negotiable):** display the sampling period in the UI. "PSR over 18.6 yr" ≠ "PSR over 1 yr". If the full cycle doesn't finish, **label the map as 1 year and say so in the interface**. A labelled partial map beats an unlabelled incomplete one — and a judge who catches you overstating coverage will discount everything else.

**Budget reality:** 2048²×3ch maps are ~12 MB raw, 6–9 MB as PNG. If disk/time pressure bites, decimate to 1220² — it's a demo, not a paper.

**Test:** spot-check a few known PSRs against Mazarico's published map.

**Status: DONE (2026-10-22).** `build/lunapole/maps.py` bakes all three
products: a labelled 1-year illumination/PSR map (462² @320 m, 120 az
bins — 18.2 % permanent shadow, honest `span_label` in every header),
the Earth-visibility map (47.9 % of the polecap sees a limb, 41.2 % the
full disc), and per-site time series + full-cycle (18.6-yr) point runs
for the four sites. The full-cycle **map bake** variant is implemented
but not baked (expensive); per-site full-cycle runs cover the verdict
engine. Verifier: `verify/verify_maps.py` — synthetic 20/20, P3
bin-for-bin march parity, Earth closed-form parity 1.8e-15°, published
cross-checks green **31/31 (2026-10-22)**: interior-dark ✓, but the
published "rim ~80-90 %/yr" does NOT reproduce at truth resolution
(Spudis-era claim recorded, not asserted; best truthful rim 0.595/yr)
— and the map march's measured resolution bias (+0.26..+0.48 optimism
on low-horizon pixels) is documented and enforced as a check. See
`docs/maps-notes.md`.

---

## P5 — App / frontend

**Status: DONE (2026-10-28).** `app/index.html` + `app/src/*.js` +
vendored Three.js, assembled into `app/dist` by `scripts/build_app.py`. Browser
parsers are cross-checked against the Python readers under Node by
`verify/verify_app_readers.py`; the phone/rehearsal items remain manual.

**Owns:** `app/` (vanilla ES modules + canvas 2D + vendored Three.js; no npm or
Vite build step by design), four panels, timeline, verdict engine

**Panels as built (§11 and the P6 demo):**
- **A** - 3D terrain with the far-field horizon ring
- **B** - baked pole-cap illumination / Earth-visibility map, span label verbatim
- **C** - first-person sky view
- **D** - one-click verdict, measured latency
- **Timeline** - Sun vs measured horizon over the labelled span

**Critical:** the shadow shown on screen and the flux in the numbers must come from the **same source**. If the picture and the table disagree, the app is worse than useless.

**The clean-failure banner (§7.9) is mandatory.** At the pole the Sun is below the horizon most of the time. A naive app looks broken. Instead always show: current elevation, next sunrise, and **why** it's dark (which ridge, at what distance). This converts "broken" into "the science says no."

**Rendering:** depth ratio between a local observer and the real Earth (~384,400 km) is ~10⁷. Use floating-origin + logarithmic depth buffer or you'll get z-fighting everywhere.

**Start now, against mock data.** Don't wait for P1–P4.

---

## P6 — Integration, quality, demo

**Status: DONE except the human-only gates (2026-10-28).** Bake, manifest,
artifact pipeline, `verify/` and the demo script are in place and measured. The
published record (`verify/results.json`, 2026-10-27) is 17 PASS / 0 FAIL /
2 SKIP: N1, N2 and N3 are green, including the byte-identical `bake --check`,
with the four panels attested at 1280 px and 390 px. The 3-minute rehearsals
and the airplane-mode phone test are still outstanding (N4).

**Owns:** `build/lunapole/bake.py`, artifact pipeline, `verify/`, README, demo script

**Responsibilities:**
- Orchestrate the bake; deterministic builds (seeded RNG, fixed thread count) so artifacts are reproducible
- Manifest with SHA-256 per artifact
- `verify/` scripts publishing **measured precision** — a real error number beats a claim of correctness
- Zero-CDN offline bundling (vendor Three.js; judges' wifi will fail otherwise)
- Final README with cited sources and honest limitations
- **Own the 3-minute demo script and rehearse it.** Write it Saturday night, not Sunday.

**Also the integration risk-holder:** if P1 is blocked on DEM tiles or P4 can't finish 18.6 years, P6 makes the call on shipping a labelled partial map rather than letting the team discover it at 2am.

---

## Nightly gates

| Night | Gate — everyone must hit this |
|---|---|
| **N1** | P1: tiles downloaded, one DEM cropped, decode test passes. P2: subsolar point matches Horizons < 0.01°. P5: three panels render with a *computed* Sun. |
| **N2** | P3: horizon profile + extended disc done, curvature test green. P4: 1-year illumination map working. |
| **N3** | P4: Earth-visibility map. P5: verdict in < 1s. P6: full bake reproducible. |
| **N4** | Offline on a phone, demo script rehearsed, README honest. |

**Stop rule (spec §14):** if N3 ends without the Earth-visibility map *and* the verdict, cut everything else and ship. Those two are the demo. The rest is polish.

---

## Two open decisions (flagging, not blocking)

1. **3 sites or 10?** I recommend **3–4**. Fixes the ~664 MB artifact problem, halves build time, and four sites is enough to demonstrate range. Ten is padding nobody at a judging table will notice.
2. **18.6 years or 1 year?** Attempt 18.6. If N3 is tight, ship 1 year **and label it**. Never ship an unlabelled partial.

---

## Pre-flight checklist (before night 1)

- [ ] Clear disk — 97% full, `~/.cache` is 17 GB
- [ ] Install: `spiceypy` `rasterio` `numpy` `scipy` `zstandard` (all verified working)
- [ ] Everyone reads `VERIFICATION.md`
- [ ] Assign the six roles
- [ ] Confirm Python ≥ 3.12 (machine has 3.14 ✓)