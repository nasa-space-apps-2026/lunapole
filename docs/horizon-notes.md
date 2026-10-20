# Horizon engine notes (P3)

Written 2026-10-21, after the engine passed its gate. Read this before
touching `build/lunapole/horizon.py`, `solar_disc.py`, `earth.py` or `dem.py`.

This document records **why** the code looks the way it does. The numbers
live in `clps/constants.json`; nothing here overrides it.

---

## What the engine answers

Three questions, three separate numbers — never one blended "visibility":

| Question | Function | Unit |
|---|---|---|
| How high is the terrain in each direction? | `horizon.horizon_profile` | deg, 720 bins |
| Is the Sun's **centre** above that terrain? | `solar_disc.disc_metrics` → `sun_above_horizon` | bool |
| How much of the Sun's **disc** is visible, and what flux reaches a panel? | same → `disc_fraction`, `incident_flux` | 0..1 |

Earth uses the identical disc machinery (`earth.earth_metrics`), so a ridge
that hides the Sun hides the DSN link in exactly the same way. That is the
"same source" rule from TEAM_SPLIT P5.

---

## The geometry, and why curvature is not a correction term

For a terrain sample at arc distance `d` and elevation `h_point`, seen from a
site at `h_site`:

```
δ     = d / R
vn    = (R + h_point) cos δ − (R + h_site)     # above the tangent plane
horiz = (R + h_point) sin δ                    # sideways
elev  = atan2(vn, horiz)
```

Curvature is therefore implicit: at 30 km the same quantity written as a drop
is `R (1 − cos(d/R)) = 259.00 m`, which `verify_horizon.py` asserts against
`CORRECTED_curvature_table`. The original spec's 42.2 m belongs to **12.1 km**
— using it at 30 km understates the drop by ~6× and makes every site look
sunnier than it is.

Consequence worth keeping in mind when reading profiles: on a **smooth**
sphere the horizon is the local tangent (≈0°), because the nearest sample is
always the highest. Curvature only shows up when distant terrain is tall
enough to beat the drop — a ridge at 30 km needs to be >259 m above the site
just to break even with the tangent plane. That is the entire argument for
far-field.

---

## max-per-bin, never mean

Each 0.5° bin keeps the **highest** elevation found along its ray (and the
distance/height of the sample that produced it). The first ridge that blocks
the Sun is the only one that matters; averaging under-estimates occlusion —
the "bright bias" the spec warns about.

`compare_near_far()` exists so the test suite can assert the invariant on real
terrain: **the far-field profile can never be lower than the near-field one**.
A violation means a sign error, not noise.

---

## Fail closed, and what "provenance" means

Per bin:

| flag | meaning |
|---|---|
| `FLAG_FAR` | ray reached `max_dist_km` inside measured terrain |
| `FLAG_EDGE` | ray left the DEM crop before that |
| `FLAG_GAP` | no valid terrain sample at all |

`provenance` is 0 for measured (LOLA DEM), 2 for gap. There is deliberately no
"1 = synthesised" path in the horizon engine: inventing terrain in a product
about terrain is how projects lose a judge.

A gap is written as **+90° elevation — blocked** — not as an open horizon. If
the data cannot prove the Sun is visible, the engine says it is not.

---

## Coverage honesty (25 km crops vs the 100 km spec)

`scripts/crop_sites.py` cuts a 50 km square (25 km radius) per site. The spec
§6.3 asks for 100 km rays. Those are incompatible with the current artifacts,
so the engine reports what it actually has:

* `max_dist_km` defaults to 25 and the CLI records it in the artifact header;
* bins that stop early carry `FLAG_EDGE`;
* `summary()` prints `far-field bins N/720`, so a partial profile is visible
  at a glance instead of being silently over-claimed.

To go to 100 km, re-crop with `--radius-km 100` and re-bake; nothing else
changes. Check disk first: a 100 km radius at 10 m/px is 20000² px ≈ 800 MB
per site uncompressed.

---

## Artifact format — and the one deviation from the spec

`artifacts/horizon/<site>.bin`, **little-endian**, 50-byte header + 14 bytes
per bin (≈9.9 kB/site). Full layout is in the `horizon.py` module docstring.

The spec §9.2 drew a big-endian `struct` with a scalar `far_field_mask`. We
deviate on purpose:

1. **Little-endian**, matching `ephemeris.py`. Every artifact stays readable
   by the same `struct`/numpy path, and the frontend reads one convention.
2. **Per-bin flags** instead of one scalar mask. A 16-bit mask cannot describe
   720 bins; coverage genuinely varies per direction once a ray leaves the
   crop, and flattening that into one number hides exactly the honesty the
   spec §6.5 demands.
3. **`shadow_dist_km` and the obstacle's elevation** are both stored, so the
   UI can say *which ridge* and *how tall* — not just "blocked".

---

## Traps already paid for

* **`ldec_` vs `ldem_`.** Observation counts open cleanly, have correct
  geometry, and decode to 0..13 m. `dem.py` rejects values outside
  −15 000..+15 000 m, the same window `verify/verify_dem.py` uses.
* **Nearest-pixel sampling, on purpose.** Bilinear invents sub-pixel terrain.
  Every number must trace to a measured LOLA pixel.
* **Re-deriving the obstacle position.** The first version recomputed the
  winning sample's lat/lon from its distance; at a ridge boundary one ULP of
  round-trip error picks the pixel on the *other* side and reports 0 m instead
  of 500 m. The height is now carried along with the winning angle.
* **Azimuth at the pole.** At −90° the local east/north basis is still
  well-defined; the stratospheric case is a site at *exactly* the pole, where
  azimuth is meaningful only relative to the projection's +Y axis. Tests use
  lat = −90 and a synthetic wall at lon 90E to pin the convention (az 90 →
  +x in the projection).
* **Flux is not "fraction visible".** A horizontal panel under a Sun sitting
  on the horizon collects ~0 flux while half the disc is visible. Both numbers
  are reported separately for exactly that reason.

---

## Running it

```bash
python3 scripts/crop_sites.py          # DEM crops  -> artifacts/dem/
python3 verify/verify_horizon.py       # the gate  (synthetic + real DEM)
python3 -m lunapole.horizon --all      # bake      -> artifacts/horizon/
# (from build/: PYTHONPATH=build python3 -m lunapole.horizon --all)
python3 -m lunapole.horizon --site shackleton --max-dist-km 25
```

The bake is deterministic: same DEM + same arguments ⇒ byte-identical file
(asserted in the test suite; P6's manifest depends on it).
