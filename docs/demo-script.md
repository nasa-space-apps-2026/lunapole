# LUNAPOLE demo script - 3:00, offline, honest

**Owner:** P6. **Hard limit:** 3 minutes. **Rule:** never cut the honesty line to
save time; cut the Earth map instead.

> **Status (2026-10-28):** the app, the bake and the verifiers are in the tree.
> The published gate record (`verify/results.json`, 2026-10-27) is 17 PASS /
> 0 FAIL / 2 SKIP: N1, N2 and N3 are green, including a byte-identical
> `bake --check`, and the four panels are attested at 1280 px and 390 px. The
> two human items are still outstanding: two clean 3-minute runs and the
> airplane-mode phone test. Until a human does them and attests them, N4 is
> BLOCKED. There is a static, no-JavaScript fallback page at
> `docs/fallback/index.html` (no video yet). Run
> `python verify/run_all.py --real --check --timeout 0` first. If any gate is
> still blocked, say which one before you start.

---

## Pre-flight (T-30 minutes)

Run these in order. Stop at the first failure and fix it; do not "present around"
a missing artifact.

```bash
python verify/doctor.py
python scripts/export_terrain.py
python scripts/build_app.py              # rebuild app/dist from the bake
python scripts/build_app.py --check      # app/dist matches the bake
python scripts/make_fallback.py --check  # static fallback matches the bake
python build/lunapole/bake.py --verify   # every artifact hash re-checked
python verify/run_all.py --real --check --timeout 0   # no wall-clock watchdog
```

Expected before a real demo: doctor READY (or only optional SKIPs), the bundle
check at 0 mismatches, `bake.py --verify` PASS with a manifest SHA-256, N2 and
N3 PASS, and `verify/results.json` showing exactly which manual N1/N4 items are
still BLOCKED. `verify/results.json` is the evidence file; keep it open in a tab.

Then:

1. Serve the offline build locally (do not open `file://`; the app uses ES
   modules and `fetch`, which a `file://` origin blocks):

   ```bash
   python scripts/build_app.py --serve --port 8000
   # equivalently: python -m http.server 8000 --directory app/dist
   ```

   Open `http://localhost:8000`. The header shows the first 12 hex digits of
   the manifest hash; the footer shows the bundle build time.

2. Open DevTools -> Network, reload, and confirm **zero external requests**.
   Then set Network to Offline and reload once. The demo must still work.
3. Phone check: put the target phone in airplane mode. The bundle needs an HTTP
   origin (ES modules and `fetch`), so serve `app/dist` from the laptop on a
   local hotspot - never the venue Wi-Fi - and bind it to the network:

   ```bash
   python scripts/build_app.py --serve --host 0.0.0.0
   ```

   The command prints the hotspot address; open it on the phone. There is no
   single-file mobile build. If the phone cannot load it this way, N4 is not met:
   say so; do not show a laptop screenshot and call it a phone test. As a
   no-server last resort, `docs/fallback/index.html` opens from `file://` on the
   phone, but it is static and must be described as such.
4. Close notifications, chat, updates and extra tabs. Set zoom to 125%. Start a
   visible 3:00 timer. Start the screen recording (this is also the fallback).
5. Confirm `docs/demo-fallback.mp4` exists, plays with sound, and is the same
   build. If it does not exist, record it now; do not plan to improvise.
6. Have these backup tabs open: `artifacts/maps/polecap_illu_365d.png`,
   `artifacts/maps/polecap_erth_365d.png`, and `verify/results.json`.

**Fallback rule:** if the live app fails twice, switch to the screencast and say
plainly: "This is a recording from the build that passed the verifier." Do not
claim a live run you did not do.

---

## The 3:00 run

The times are cumulative. `[read from screen]` means read the number the app is
showing; do not substitute a remembered number.

| Time | Action | Say |
|---|---|---|
| 0:00-0:15 | Title / terrain view | "At the lunar south pole the Sun never rises more than **1.54 degrees**. A one-metre rock throws a **37-metre shadow**. Terrain, not latitude, decides who gets power - and who can phone home." |
| 0:15-0:35 | Point at the layout | "LUNAPOLE answers two questions for a chosen site: when is the Sun above the measured horizon, and when is Earth visible? Everything is baked from LOLA topography and NAIF ephemerides. Nothing is fetched at runtime - the header shows the manifest hash." |
| 0:35-0:55 | Panel A: terrain + horizon ring | "This is the measured terrain, three-times exaggerated, with the far-field horizon ring. The engine marches 720 azimuth bins out to 25 km and applies lunar curvature - **259 metres of drop at 30 km**. Rays that leave the crop are flagged, not invented. Relief shading only, not cast shadows." |
| 0:55-1:25 | Panel C: sky at the site | "Panel C is the sky at this site: the grey silhouette is the measured horizon, the gold marker is the Sun, the blue one is Earth. Both elevations are computed from the kernels, then tested against that silhouette. Here the Sun is at [read] degrees and the horizon is at [read] degrees." |
| 1:25-1:50 | Timeline, scrub | "The timeline is the labelled span - a **one-year partial**, not the 18.6-year draconic cycle, and the label stays on screen under each panel. Sun elevation is tested sample by sample against the local horizon. Scrub to [date]: the Sun drops below this site's measured horizon; the map's bright rim pixels are the places that stay lit more often." |
| 1:50-2:15 | Panel D: switch site to **Nobile**, one-click verdict | "Shackleton was the terrain story; Nobile is the Earth-link story. One click: Sun above the measured horizon **6.1 %** of the year, longest dark run **5627 h (234.5 d)**, Earth any limb **37.1 %**, full disc **26.1 %**. The app measures its own latency and prints it - [read] milliseconds, no network request." |
| 2:15-2:40 | Panel B: Earth map tab | "This is the differentiator: Earth visibility, not just Sun. Across this one-year, 148-kilometre cap, **47.9 %** of pixels see a limb and **41.2 %** see the full disc. The label under the map is copied byte-for-byte from the artifact header. Grey is outside the measured DEM. Nobile lies outside this cap, so its verdict comes from its own 720-bin horizon." |
| 2:40-2:55 | Limitations slide / README | "What we do not claim: a one-year map, a 25-kilometre horizon, 320-metre pixels. The map is optimistic by **+0.26 and +0.27**; the 720-bin profile is the precision path. Coordinates need IAU reconfirmation." |
| 2:55-3:00 | Close | "Measured terrain, labelled span, offline. The manifest is in the repo." |

If the judge's clock is strict, drop the Earth map (2:15-2:40) and give those 25
seconds to the verdict and limitations. Never drop the span label or the
limitations line.

**Timing budget:** the spoken column is 407 words over 180 seconds - about 136
words per minute, which leaves room for the `[read from screen]` pauses. That is
a word count, not a rehearsal; only a human run proves the pace. If a revision
adds more than ~20 words, cut the Earth map segment, not the limitations.

### Exact honesty lines (use at least these)

- "This map is a **one-year labelled partial**, not an 18.6-year PSR claim."
- "Horizons stop at **25 km**; bins that did not reach the far field are flagged,
  not filled in."
- "The map is **320 m and 120 azimuth bins**; the verdict uses the 720-bin
  per-site horizon. Our two anchored checks are optimistic by **+0.26 and
  +0.27**; a P4 rim scan saw up to **+0.48**."
- "Coordinates are IAU feature coordinates sourced via Wikipedia infoboxes;
  reconfirm at the IAU Gazetteer before mission use."
- "This is illumination geometry, not a power, thermal or communications link
  model."

---

## If something fails

| Symptom | Do this | Do not do this |
|---|---|---|
| Blank app | Reload once. If still blank, run `scripts/build_app.py --serve` again (`app/dist` needs an HTTP origin), then open `docs/fallback/index.html`. | Debug live for 30 seconds while the clock runs. |
| 404 on an artifact | Show `bake.py --verify` output and the PNG backup; explain the blocker. | Hand-wave or show an older map. |
| Map legend has no span label | Stop the map segment. Show the P3 horizon/verdict instead. | Present an unlabelled map. |
| Verdict takes > 1 s | Note it; N3 latency is not met. | Hide the spinner or claim "instant". |
| Phone fails offline | Say N4 is not met; show the laptop offline build and the manifest. | Use the venue Wi-Fi and call it offline. |
| Running over time | Cut the Earth map, keep verdict + limitations. | Cut the limitations. |

---

## Judge Q&A (short answers)

- **Your number is lower than the published figure.** Correct, and it is the
  same model, not a different one. Every site in the catalogue is an **IAU
  feature centre** — the Gazetteer's anchor for the named feature — and the
  strip above the panels says so on every site. Published percentages describe
  a **rim peak or a candidate landing pixel**, which can sit a kilometre or
  more above and several kilometres away from the centre. On this DEM the
  Shackleton centre is 1515 m with terrain 7 km lower within 10 km: it is on
  the crater's inner slope, not the rim. The engine is coordinate-driven
  (`horizon_profile(dem, lat, lon)`), so pointing it at a rim coordinate
  returns the rim number. The label was the problem; the arithmetic was not.
- **Why only one year?** The 18.6-year map is implemented (`maps.py --full-cycle`)
  but not baked; a labelled 1-year map is honest, an unlabelled 18.6-year claim is
  not. The `full` profile adds 18.6-year per-site point runs for the verdict.
- **How accurate is the astronomy?** Reproduced on this checkout over six epochs
  including two libration extrema: **0.0076 deg sub-solar / 0.0070 deg
  sub-Earth** worst separation against JPL Horizons, target < 0.01 deg. Rerun
  `verify/verify_horizons.py` to confirm on another machine.
- **What do the map-wide numbers mean?** Over the labelled 1-year span, **47.9 %**
  of valid pixels see the Earth's limb at some sample and **41.2 %** see the full
  disc at some sample. That is a map statistic, not a promise for any one site;
  Nobile's **37.1 % / 26.1 %** comes from its own 720-bin horizon.
- **Why 25 km?** That is the crop radius; the curvature drop at 30 km is 259 m,
  so far terrain matters. Rays that leave the crop are flagged. Re-crop at 100 km
  when disk allows; the engine does not change.
- **Why four sites?** Four contrasting terrains demonstrate range without a
  600 MB artifact set or a six-site build. `full` adds the other two. The demo
  map covers 148 km, so Nobile and Haworth fall outside it; their verdicts use
  the per-site horizons, and the map note says so on screen.
- **Is it really offline?** `app/dist` is scanned for external runtime URLs by
  `verify/run_all.py` (zero found); DevTools shows no external requests. The
  airplane-mode phone test is still outstanding unless a human has attested it;
  do not claim it on stage if the attestation is missing.
- **Where are the sources and checksums?** `data/SOURCES.md`; every kernel, tile
  and crop hash is also in `artifacts/manifest.json`.
- **Can I reproduce the build?** `bake.py --check` rebakes into a temporary
  directory and compares SHA-256 per artifact and the canonical manifest
  identity. Same bytes, same `manifest_sha256`.

---

## Fallback page, then screencast

Two fallbacks, best first:

1. **Static page:** `docs/fallback/index.html` - plain HTML, no JavaScript, no
   network, opens from `file://` on the laptop or phone. It is generated by
   `python scripts/make_fallback.py` from the same manifest and artifacts, so
   the maps, the span labels and the per-site numbers cannot disagree with the
   bake. It has no site markers and no scrubbing; say that if you use it.
2. **Recording:** `docs/demo-fallback.mp4` (git-ignored if large). **Not
   recorded yet** - the file is absent.
- Record after a clean `--real --check` run, at 1080p, with cursor and audio, at
  the same 3:00 pace.
- Verify it plays with sound on the demo laptop **and** the phone before leaving.
- If there is no recording and the app fails, open `docs/fallback/index.html`,
  show `verify/results.json`, and say exactly which gate is blocked. That is a
  worse demo but a true one.

---

## Rehearsal log

N4 requires **two clean runs**. Fill this in, then attest with the real timings:

| Date | Run | Time | N1-N4 | Failure | Fix |
|---|---|---|---|---|---|
| | 1 | | | | |
| | 2 | | | | |

No human rehearsal or phone attestation is recorded in this checkout. The
browser checks on 2026-10-27 did verify the four panels at 1280 px and 390 px
and measured the verdict at **21.4-29.4 ms across the four demo sites**
(headless Chrome 154, in-app timer, no network). That observation is recorded
as the `app_panels` and `verdict_latency` attestation, but it does not cover
`demo_rehearsal` or `offline_phone`:

```bash
# N1/N3 only: visual panels + measured verdict latency
python verify/run_all.py --real --check --timeout 0 \
  --attest app_panels="four panels rendered at 1280 px and 390 px; Sun/Earth read from baked artifacts" \
  --attest verdict_latency="21.4-29.4 ms over 4 sites, in-app timer, headless Chrome 154, no network"

# N4: run only after the two human rehearsals and the airplane-mode phone test
python verify/run_all.py --real --check --timeout 0 \
  --attest demo_rehearsal="2 clean runs, 2:58 / 3:01, no gate failures" \
  --attest offline_phone="iPhone 13, airplane mode, local server, PASS" \
  --attest app_panels="...your measured note..." \
  --attest verdict_latency="...your measured note..."
```

An attestation is a human claim with a note, not automated proof. Do not attest
a run you did not do. The two N4 rows above stay BLOCKED until a human fills
the rehearsal log and tests the real phone.

---

## What P5 must expose for this script to work

The app as built meets items 1-5; item 6 (phone) is built but untested. This is
the checklist, not a claim:

1. The artifact's `span_label` **verbatim**, on the map and in the verdict.
2. Sun and Earth values with units, plus the span and resolution that produced
   them.
3. A visible map legend that states the span and the 320 m / 120-bin resolution.
4. A one-click verdict that completes in under one second on the demo laptop.
5. No external runtime requests; Three.js and all data are local.
6. A phone-sized layout that works in airplane mode, plus an HTTP-origin story
   for the phone (local server, or a laptop on a local hotspot). Copying the
   folder and opening `index.html` will not work.

If P5 cannot meet one of these, tell P6 before the rehearsal and we will cut the
segment rather than overstate it.
