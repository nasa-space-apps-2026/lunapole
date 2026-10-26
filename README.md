# LUNAPOLE - Shadow & Horizon Planner for the Lunar South Pole

**NASA Space Apps Challenge 2026 - CLPS Lunar Mission Browser**

> For a point at the lunar south pole, show when the Sun and Earth are genuinely
> above the local horizon - accounting for LOLA topography, lunar curvature,
> libration, and the extended solar disc.

---

## Status: demo build in progress (2026-10-25)

All six parts are in the tree: P1-P4 science modules, the P5 offline app under
`app/`, and the P6 bake/verification pipeline. The public-domain inputs are
downloaded and SHA-256 checked, the six site crops are made, the terrain
heightmaps are exported, and the demo-profile bake has been promoted (16
artifacts, 14.40 MB). **No gate is claimed green here until
`verify/results.json` says so**, produced by:

```bash
python verify/run_all.py --real --check
```

| Area | Code | Data/artifacts in this checkout | Gate |
|---|---|---|---|
| P1 DEM decode + site crops | present | tiles + 6 crops present | see `results.json` |
| P2 ephemeris (SPICE) | present | 4 kernels present | see `results.json` |
| P3 horizon engine | present | for the four demo sites | see `results.json` |
| P4 illumination / Earth maps | present | baked by the demo profile | see `results.json` |
| P5 browser app | present | built by `scripts/build_app.py` | see `results.json` |
| P6 bake + manifest | present | manifest written last, hashed | see `results.json` |
| P6 README + demo script | present | rehearsal/phone still manual | N4 manual |

Measured on the build machine: Python 3.13.3, NumPy 2.2.5, spiceypy 8.3.0,
rasterio 1.5.2, Node 24.18.0, no `osgeo`. About 440 MB of public-domain data,
plus 44 MB of site crops, and 14.4 MB of demo artifacts. Keep at least 3 GB
free for the bake and its reproducibility check. Do not treat the absence of a
red error as a pass: the gate runner reports missing prerequisites as BLOCKED
(exit 2).

### What this project is not

It is not flight software, and it is not a power/thermal/radiation model. It
answers illumination and direct-to-Earth visibility questions from measured
terrain, and it publishes the span and resolution behind every answer.

---

## Quick start

`scripts/fetch_data.py` is pure standard library and works on Windows,
macOS and Linux. The older `*.sh` scripts do the same thing but need bash.

```bash
# 1. Python dependencies (3.12+)
python -m pip install numpy spiceypy rasterio
# GDAL's `osgeo` bindings are NOT required: verify_dem.py and crop_sites.py
# use rasterio, whose wheels bundle GDAL. `doctor.py` reports osgeo as optional.

# 2. Public-domain NASA data, SHA-256 checked against data/SOURCES.md
python scripts/fetch_data.py           # 4 NAIF kernels, ~44 MB
python scripts/fetch_data.py --dem     # 3 LOLA polar tiles, ~393 MB
python scripts/fetch_data.py --check --dem   # verify bytes, download nothing
python scripts/crop_sites.py --radius-km 25
python scripts/verify_crops.py

# 3. Dry run, then bake
python build/lunapole/bake.py --plan
python build/lunapole/bake.py --profile fast    # ephemeris + horizons
python build/lunapole/bake.py --profile demo    # demo artifact set
python build/lunapole/bake.py --verify
python build/lunapole/bake.py --check           # rebake in temp, compare bytes

# 4. Build and serve the offline app (no npm, no Vite)
python scripts/export_terrain.py      # small LUNATRN heightmaps for the 3D panel
python scripts/build_app.py           # app/dist, plus BUILD.txt with hashes
python scripts/build_app.py --serve   # http://localhost:8000
python scripts/build_app.py --check   # dist matches the bake
python scripts/make_fallback.py       # docs/fallback/: static no-JS page

# 5. Diagnostics and gate report
python verify/doctor.py
python verify/run_all.py --real --check --timeout 0   # --timeout 0: no watchdog
python scripts/make_fallback.py --check               # static fallback in sync
```

`app/dist` is a static bundle: plain ES modules, canvas 2D and a vendored
Three.js (`app/vendor/three`, MIT). It must be served over HTTP; a `file://`
origin blocks ES modules and `fetch`. `verify/verify_app_readers.py` cross-checks
the browser's binary parsers against the Python readers under Node.

`--plan` and `python verify/doctor.py` work without SPICE, GDAL, data or an
app. They are the commands to run first on a new machine.

### Bake profiles

| Profile | Sites | Products | Use |
|---|---|---|---|
| `fast` | 4 | 29.53 d ephemeris at 5 min, 720-bin / 25 km horizons | quick N1/N2 loop |
| `demo` (default) | 4 | `fast` + labelled 1-year ILLU and ERTH polecap maps + 1-year hourly per-site series | the demo set |
| `full` | 6 | `demo` + 18.6-yr per-site point runs at 120 min | heavy; still not an 18.6-yr map bake |

The demo sites are `shackleton`, `de_gerlache`, `haworth` and `nobile`; `full`
adds `malapert` and `cabeus`. The map region is `polecap` (the 87.5S-90S,
10 m/px tile). P4's map start is fixed at **2026-10-01 00:00 UTC**; the
ephemeris and series use the profile start, which is the same date.

Useful overrides:

```bash
python build/lunapole/bake.py --sites shackleton,malapert --no-maps --no-series
python build/lunapole/bake.py --profile demo --maps-span-days 30 --maps-step-min 120
python build/lunapole/bake.py --manifest-only --force   # hash an existing set
```

A partial time span is always written with a `LABELLED PARTIAL` string in the
artifact header and in the per-site JSON. Nothing silently rounds 1 year up to
the 18.6-year draconic cycle.

---

## Artifacts and manifest

The bake owns `artifacts/ephemeris`, `artifacts/horizon` and `artifacts/maps`.
`artifacts/dem` is an **input** (per-site crops) and is never modified.

```
artifacts/
  ephemeris/<site>.bin              LUNAEPH: sub-solar/sub-Earth per timestep
  horizon/<site>.bin                LUNAHOR: max elevation per 0.5 deg azimuth
  maps/<region>_illu_<days>d.bin    LUNAMAP: illumination/PSR planes
  maps/<region>_illu_<days>d.png    deterministic RGB preview
  maps/<region>_erth_<days>d.bin    LUNAMAP: Earth any/full-disc planes
  maps/<region>_erth_<days>d.png
  maps/timeseries/<site>_<days>d.json
  manifest.json                     written last, atomically
```

Every header carries its own parameters: site, span, step, azimuth bins,
curvature-aware horizon distance, disc samples, and the honesty label. A file
cannot be read without knowing what was actually computed.

`artifacts/manifest.json` (`lunapole.manifest/1`) records:

- SHA-256 and byte count for **every artifact**, plus parsed header facts;
- SHA-256 for every kernel, DEM tile and site crop used;
- build parameters, tool versions, git commit, totals;
- a canonical `manifest_sha256`.

The canonical identity covers parameters, inputs, artifacts and totals. It
deliberately **excludes** the wall clock, hostname, CLI line and the git-dirty
flag. Two builds with the same inputs and parameters must produce the same
`manifest_sha256`; `bake.py --check` proves byte identity by rebaking into a
temporary directory and comparing every artifact hash.

The bake writes into `artifacts/.stage-<pid>/`, promotes the files, then writes
the manifest. Files in the product directories that are not in the new plan are
removed. A killed bake leaves the previous manifest in place, so `--verify`
fails loudly instead of blessing a half-written set.

Exit codes: `0` pass, `1` FAIL (bad input hash, bake or manifest mismatch),
`2` BLOCKED (missing prerequisite). `SOURCE_DATE_EPOCH` and `--threads 1` are
supported for reproducible timestamps and thread pinning.

**Cross-machine caveat:** byte identity is tested on the same OS, Python,
NumPy and kernel versions. Different libm/BLAS builds can change the last bits;
the manifest will report that as a mismatch rather than hiding it.

---

## The app (P5)

`app/dist` is four panels and one timeline, all fed by baked files:

| Panel | Shows | Source of truth |
|---|---|---|
| A - Terrain | 3D relief, 3x vertical exaggeration, far-field horizon ring | `app/data/terrain/<site>.bin` (nearest samples of the verified crop at about 130 m/px for display; horizons use the full-resolution crop) and `artifacts/horizon/<site>.bin` |
| B - Baked map | sun or Earth pole-cap map, span label copied verbatim from the header | `artifacts/maps/*_illu_*.png` / `*_erth_*.png` |
| C - Sky | horizon silhouette with Sun and Earth markers at the scrubbed instant | the same P3 horizon plus the baked series |
| D - Verdict | one click: solar class, Earth link, longest dark run, measured latency | the 1-year hourly series, evaluated in the browser |
| Timeline | Sun vs horizon and Earth elevation over the labelled span, lit shading | `artifacts/maps/timeseries/<site>_<days>d.json` |

The header prints the first 12 hex digits of the manifest hash. Every panel
states its resolution; the map's `span_label` is rendered character-for-character
from the artifact header, never retyped. `scripts/build_app.py --check` compares
the bundle against the bake, including a stray-file check.

If the app or the laptop dies, `docs/fallback/index.html` is a plain-HTML page
generated from the same manifest: the two PNG maps, the verbatim span labels and
one verdict row per site. No JavaScript, no network, opens from `file://`.
`python scripts/make_fallback.py --check` fails if it drifts from the bake.

---

## Measured verification

Run the individual verifiers, or let the runner publish a record:

```bash
python verify/verify_bake.py        # P6 manifest contract, stdlib only
python verify/verify_dem.py         # GDAL, DEM decode, site crops
python verify/verify_ephemeris.py   # SPICE kernel/time/frame sanity
python verify/verify_horizons.py    # JPL Horizons comparison (network)
python verify/verify_horizon.py     # horizon/curvature/disc
python verify/verify_maps.py --real # map products on real terrain
python verify/verify_maps.py --mazarico  # map vs 720-bin truth + anchors
python verify/verify_app_readers.py # browser readers vs Python, under Node
python scripts/build_app.py --check # app/dist matches the bake
python verify/run_all.py --real --check
```

`verify/run_all.py` writes `verify/results.json`, maps every check to N1-N4,
and refuses to mark a manual check green without an explicit, note-bearing
attestation:

```bash
python verify/run_all.py --real --check \
  --attest demo_rehearsal="2 clean runs, 2:58 / 3:01" \
  --attest offline_phone="iPhone 13, airplane mode, local server, PASS" \
  --attest app_panels="all four panels, Sun and Earth from artifacts" \
  --attest verdict_latency="9.9-27.2 ms over 6 clicks, in-app timer"
```

The timeout is wall-clock. A laptop that sleeps during the long
`bake.py --check` can trip the watchdog on an already-finished check, so use
`--timeout 0` for the full run (or keep the machine awake). The overnight
record from that failure is kept at
`verify/results-2026-10-25-sleep-timeout.json`; it is superseded by the next
clean run, not deleted.

### Measured on this checkout (2026-10-25)

Demo profile: **16 artifacts, 14.40 MB**, manifest
`9b8961f8ab7aa9bdd66d66344f1ede49b3fc09607b8fdbf74e10bcaf8c5462b4`
(four sites; 1-year labelled partial maps plus hourly series). `bake.py
--verify` passes and `bake.py --check` rebakes into a temporary directory and
reproduces every artifact byte-for-byte. `verify/results.json` is the
machine-readable record; the table is a summary of it.

| Check | Measured |
|---|---|
| Manifest contract: hashes, tamper, stale refusal, promote, LF bytes | **17/17 PASS** |
| N1 DEM decode and crops | **6/6 sites** round-trip; Shackleton local relief 830 m; no flat fills |
| N1 ephemeris | pole solar minimum **-1.5715 deg** (expected -1.54), span **3.0861 deg**; libration half-amplitude **6.52 deg lon / 6.79 deg lat**; Earth disc **1.8609 deg** at 392 782 km |
| N1 JPL Horizons, 6 epochs incl. 2 libration extrema | worst **0.0076 deg** sub-solar, **0.0070 deg** sub-Earth (target < 0.01) |
| N1 P5 panels | **manual**; no human attestation yet, so N1 reports BLOCKED |
| N2 horizon, curvature, extended disc | 720 bins at 25 km / 10 m; curvature **259.00 m @ 30 km**, **2877.10 m @ 100 km**; far field never lowers a bin, gains up to **+29.23 deg** (de Gerlache), **+20.81 deg** (Malapert), **+13.61 deg** (Shackleton); Sun centre on the horizon -> **50 %** of the disc |
| N2 synthetic map suite | deterministic bake, ILLU/ERTH round-trip, labelled-span rule: PASS |
| N3 real-terrain maps | **26/26 PASS**; Earth closed form vs vector path **1.8e-15 deg**; Shackleton month shard **20.6 %** of its footprint dark over the month |
| N3 map vs 720-bin truth march (`--mazarico`) | **31/31 PASS**; map optimism **+0.260** (map-best rim pixel) and **+0.268** (summit: map 0.984 vs 1-year truth 0.716); best truthful rim value **0.595**; full-cycle summit truth **0.706** |
| N3 browser readers | 4 horizons, 6 terrains (exact int16), 4 series; worst interpolation error **0.0e+00 deg** |
| N3 bake verify/check | PASS; temporary rebake **byte-identical** |
| N3 Earth map | ILLU/ERTH **462x462**, 320 m/px, 120 azimuth bins, 8767 samples, `span_label` present; map-wide **18.2 %** dark, **47.9 %** any limb, **41.2 %** full disc |
| N3 verdict latency | **9.9-27.2 ms** over six clicks; Chrome 152 / Electron 44 on Windows, 8 cores; in-app timer, no network |
| N4 offline bundle | **29 files, 7.50 MB**, 0 mismatches or strays; **0 external runtime URLs**; Three.js vendored |
| N4 demo script / README | PASS: timed run, fallback, pre-flight, limitations present |
| N4 rehearsal and phone | **BLOCKED**: two human 3-minute runs and an airplane-mode phone test are outstanding |

The in-app latency figure times evaluation and DOM update, not click-to-paint;
treat it as "well under one second", not a benchmark.

The map-wide **18.2 % / 47.9 % / 41.2 %** figures above reproduce the P4 run
exactly, as do the two anchored bias values **+0.260** (map-best rim pixel) and
**+0.268** (summit). The P4 note that the map can be optimistic by up to
**+0.48** came from a scan of eight rim-crest pixels; this rerun re-measured the
two anchors, not the eight-pixel scan. Quote the anchors unless the rim scan has
been re-run.

---

## Honest limitations

1. **Two of the six sites are not baked in the demo profile.** The demo bakes
   `shackleton`, `de_gerlache`, `haworth` and `nobile`; `malapert` and `cabeus`
   are in the catalogue but their horizons and series come only with the `full`
   profile. The app shows exactly the sites the manifest contains.
2. **No data or artifacts are committed.** Tiles, kernels, crops, maps and the
   app bundle are public-domain or derived but large and re-downloadable; they
   are git-ignored. A fresh clone must fetch and bake before the gates can run;
   that is BLOCKED, not green.
3. **25 km horizon radius.** Rays that reach the crop edge stop there and set
   `FLAG_EDGE`; they do not invent far terrain. The spec's 100 km horizon is not
   met by the default crops. Re-crop with `--radius-km 100` when disk allows;
   the engine needs no change.
4. **The map is a labelled 1-year partial, not the 18.6-year cycle.** The
   full-cycle map variant is implemented but not baked. The `full` profile bakes
   18.6-year per-site point runs for the verdict; that is not a map.
5. **Map resolution is coarser than the truth march.** The demo map is 320 m
   pixels and 120 azimuth bins, versus P3's 720 bins at 1-pixel ray steps (10 m
   on the 10 m tiles, 20 m on the 20 m tiles). Measured
   optimism is +0.260 on the map-best rim pixel and +0.268 at the summit; the
   P4 scan of eight rim crests reported up to +0.48, which this rerun did not
   repeat. Use the P3 profile when the number matters; use the map for
   spatial context.
6. **Earth visibility is a disc-centre margin against a one-dimensional
   horizon.** A sloped horizon can differ from a full limb test by up to about
   half the azimuth bin width (<~1 deg at 120 bins). This is documented in
   `docs/maps-notes.md` and spot-checked, not hidden.
7. **DEM precision is not uniform.** Shackleton and de Gerlache use the 10 m/px
   tile; the other sites use 20 m/px. Do not present one precision figure for
   all six sites.
8. **Coordinates are IAU feature coordinates sourced via Wikipedia infoboxes.**
   Re-confirm at `planetarynames.wr.usgs.gov` before any mission use. The
   Artemis III region-to-crater mapping is our approximation, not an official
   NASA mapping.
9. **No arbitrary-date scrubbing.** Everything is baked. The UI must show the
   baked span and must render `span_label` verbatim; there is no browser-side
   astronomy fallback (the `astronomy-engine` lunar-observer path does not
   exist).
10. **Not flight software.** No thermal, power, radiation, communications-link
    or landing-hazard model. Illumination geometry only; spherical Moon
    approximation (flattening ~0.0012, negligible here).
11. **No single-file or native mobile build.** `app/dist` is ES modules and
    `fetch`, so it needs an HTTP origin; opening `index.html` from `file://`
    fails by design. For a phone, serve the bundle from the laptop on a local
    hotspot and bind it to the network:

    ```bash
    python scripts/build_app.py --serve --host 0.0.0.0
    ```

    The command prints the laptop's hotspot address; open that on the phone.
    Never use the venue Wi-Fi. The phone run itself is still untested here,
    which is why the gate reports it BLOCKED rather than green. The static
    `docs/fallback/index.html` does work from `file://` and is the no-server
    fallback for the phone.

---

## Manifest and reproducibility (command reference)

```bash
python build/lunapole/bake.py --plan            # parameters, blockers, expected files
python build/lunapole/bake.py --profile demo    # stage -> promote -> manifest last
python build/lunapole/bake.py --verify          # manifest vs disk, headers, extra files
python build/lunapole/bake.py --verify --verify-inputs
python build/lunapole/bake.py --check           # temp rebake, byte comparison
python build/lunapole/bake.py --manifest-only   # hash an existing set (needs --force if manifest exists)
```

`--verify` re-hashes every artifact and re-reads every header. It also fails on
unexpected files in the product directories, because a stale artifact from an
old parameter set is a lie about the current build. `--verify-inputs` re-hashes
the kernels, tiles and crops recorded in the manifest.

---

## Repository map

| Path | Contents |
|---|---|
| `build/lunapole/` | P2 frames/ephemeris, P3 horizon/earth/disc, P4 maps, P6 `bake.py` |
| `app/` | P5 offline browser app: panel A terrain (Three.js), B baked map, C sky, D verdict, timeline; vendored Three.js |
| `scripts/` | data fetch, site cropping, crop sanity check, terrain export, offline bundle, static fallback page |
| `verify/` | verifiers, `doctor.py`, `run_all.py`, `verify_bake.py`, `verify_app_readers.py` |
| `clps/` | verified constants and site catalogue (source of truth) |
| `docs/` | horizon/maps/SPICE notes, demo script, generated static fallback |
| `data/SOURCES.md` | public-domain sources and SHA-256 checksums |
| `TEAM_SPLIT.md` | ownership, nightly gates, stop rule |
| `VERIFICATION.md` | what was checked, what the original spec got wrong |

Do not copy numbers or coordinates from `README-SOUTHPOLE.md`; it is design
intent only. Use `clps/constants.json` and `clps/sites.json`, then rerun the
verifiers.

---

## References

- Mazarico, E., Neumann, G.A., Smith, D.E., Zuber, M.T., & Torrence, M.H.
  (2011). *Illumination Conditions of the Lunar Polar Regions Using LOLA
  Topography.* Icarus 209(2), 634-641. doi:10.1016/j.icarus.2010.08.015
- NASA PDS Geosciences Node, LRO LOLA polar gridded DEMs (public domain).
- NASA NAIF/JPL SPICE kernels: `de440s.bsp`, `moon_pa_de440_200625.bpc`,
  `naif0012.tls`, `pck00010.tpc` (public domain).
- USGS/IAU Gazetteer of Planetary Nomenclature (feature IDs in `clps/sites.json`).
- NASA (2024), *NASA Provides Update on Artemis III Moon Landing Regions.*
- NASA CLPS task order and provider information.
- JGR Planets (2025), *Assessing Potential Landing Sites With Favorable
  Illumination and Accessible, Potentially Volatile-Rich Permanently Shadowed
  Regions Within Artemis Candidate Landing Regions.* doi:10.1029/2025JE009434

All data sources are US public domain. Attribution is appreciated, not
required. See `data/SOURCES.md` for URLs, sizes and checksums.

---

## Team

Roles, dependencies, nightly gates and the stop rule: `TEAM_SPLIT.md`.
The demo script and fallback plan: `docs/demo-script.md`.
