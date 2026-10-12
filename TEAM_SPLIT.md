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

**First task, before anything else — this gates the whole project:**
1. Find exact LOLA tile URLs for the south pole. The spec's assumed single-file `LDEM_75S` doesn't exist; products are tiled via PDS/Astrogeology.
2. Download `de440s.bsp` (32.7 MB, verified live) — **not** the 114 MB `de440.bsp`.
3. Download `moon_pa_de440_200625.bpc` (12.3 MB).
4. Clear disk first — you're at 97% full with 8.2 GB free.

**Then:** crop a DEM per site from `sites.json`. Decision to make and document: **118 m/px LOLA** (honest, contiguous) or **LROC NAC stereo** (better, patchy). Recommend starting with 118 m/px and upgrading if time allows.

**Deliverable:** `artifacts/dem/<site_id>.tif` + a `data/SOURCES.md` with every URL and SHA-256.

**Test:** open a cropped DEM, confirm elevations are plausible (south pole range roughly −8,000 m to +4,000 m), and confirm the crop is centred on the right coordinates.

**Watch for:** the LOLA decode trap. `height_m = pixel_value * scale + offset`. Get this wrong and everything is off by millions of metres. Write the test first.

---

## P2 — Ephemeris

**Owns:** `build/lunapole/frames.py`, `build/lunapole/ephemeris.py`

**Produces:** for each site × each time step, the baked vectors. Using SpiceyPy against `de440s.bsp` + the lunar orientation PCK.

**Critical:** the Moon **librates**. A "fixed" lunar site isn't inertially fixed — handle libration through the PCK. The original spec's likely failure mode was treating sites as inertially fixed, which puts the subsolar point degrees off at the pole.

**Time discipline:** UTC→TDB for the ephemeris. Earth rotation is UT1/GMST, not TDB — don't mix.

**Deliverable:** `artifacts/ephemeris/<site>.bin` — subsolar lat/lon, sub-Earth lat/lon, Earth distance, Earth angular diameter.

**Test (non-negotiable):** compare computed subsolar point against JPL Horizons at ≥5 epochs, including two at libration extrema. Target error **< 0.01°**. This is the single most important test in the project — it's the thing that proves the physics is real.

**Bonus:** Mazarico 2011 found Shackleton rim gets ~240 days/year continuous sun. If our engine agrees, we have strong independent validation.

---

## P3 — Horizon engine

**Owns:** `build/lunapole/horizon.py`, `solar_disc.py`, `earth.py`

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

---

## P5 — App / frontend

**Owns:** `app/` (Vite + TypeScript + Three.js), three panels, timeline, verdict engine

**Panels (spec §11):**
- **A** — polar stereo DEM map, shadows from computed flux
- **B** — horizon diagram (azimuth × elevation)
- **C** — first-person sky view

**Critical:** the shadow shown on screen and the flux in the numbers must come from the **same source**. If the picture and the table disagree, the app is worse than useless.

**The clean-failure banner (§7.9) is mandatory.** At the pole the Sun is below the horizon most of the time. A naive app looks broken. Instead always show: current elevation, next sunrise, and **why** it's dark (which ridge, at what distance). This converts "broken" into "the science says no."

**Rendering:** depth ratio between a local observer and the real Earth (~384,400 km) is ~10⁷. Use floating-origin + logarithmic depth buffer or you'll get z-fighting everywhere.

**Start now, against mock data.** Don't wait for P1–P4.

---

## P6 — Integration, quality, demo

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