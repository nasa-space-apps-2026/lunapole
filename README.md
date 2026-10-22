# LUNAPOLE — Shadow & Horizon Planner for the Lunar South Pole

**NASA Space Apps Challenge 2026** — Challenge: *CLPS Lunar Mission Browser*

> For any point at the lunar south pole, show when the Sun and Earth are genuinely visible above the
> local horizon — accounting for LOLA topography, lunar curvature, libration, and the extended solar disc.

---

## ⚠️ Read this before contributing

The original design document (`README-SOUTHPOLE.md`) contains **verified factual errors**.
Do not copy numbers or coordinates from it.

| File | Use it for |
|---|---|
| `VERIFICATION.md` | What was checked, what's wrong, how it was fixed |
| `clps/constants.json` | **The only source of truth for physical constants** |
| `clps/sites.json` | **The only source of truth for coordinates** (IAU-verified) |
| `TEAM_SPLIT.md` | Roles, dependencies, nightly gates, stop rule |
| `docs/horizon-notes.md` | Horizon engine: method, artifact format, coverage limits |
| `README-SOUTHPOLE.md` | Original spec — design intent only. Numbers untrusted. |

### Known errors in the original spec

1. **Lunar curvature correction wrong by ~6×** — 259 m at 30 km, not 42.2 m
2. **Site coordinate table partly fabricated** — `Connecting Ridge` and `Leibnitz-β plateau` are not real features
3. **`astronomy-engine` cannot compute a lunar-surface observer** — no such API exists
4. **Artifacts budget ~44× over** — ~664 MB actual vs "< 15 MB" claimed
5. **`LDEM_87S` does not exist**; 25 m/px is unreachable from LOLA (118 m/px native)

---

## Status

Pre-build. Verification complete; implementation in progress.

- [x] Physical constants verified
- [x] Site coordinates verified against IAU Gazetteer
- [x] Data sources confirmed available
- [x] DEM acquisition
- [x] Ephemeris bake
- [x] Horizon engine
- [x] Map products (1-yr labelled bake + full-cycle point runs; see `docs/maps-notes.md`)
- [ ] Application

---

## The idea

At the lunar south pole the Sun never rises more than **1.54°** above the horizon. A **1-metre rock casts a 38-metre shadow**. That single fact makes terrain resolution a first-order problem for solar power, thermal survival, and direct-to-Earth communications — and it's what this tool makes explorable.

Three demos drive the project:

- **W1** — shadow length scaling, with a live obstacle-height control
- **W2** — Earth visibility over the 18.6-year draconic cycle (the differentiator)
- **W3** — one-click site verdict

---

## Stack

Python 3.12+ (NumPy · SciPy · SpiceyPy · GDAL/rasterio) for offline computation;
TypeScript · Vite · Three.js for the offline-first browser app.

All data sources are **US public domain**. No accounts, no EULAs.

## References

- Mazarico et al. (2011), *Illumination Conditions of the Lunar Polar Regions Using LOLA Topography*, Icarus 209(2):634–641 — doi:10.1016/j.icarus.2010.08.015
- NASA CLPS providers & Artemis III candidate landing regions
- USGS/IAU Gazetteer of Planetary Nomenclature

---

## Team

See `TEAM_SPLIT.md`.