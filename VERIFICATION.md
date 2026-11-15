# LUNAPOLE — Verification Results & Corrections

**Verified:** 2026-10-12 · **Scope:** all physical constants, data sources, site coordinates, software stack, and internal arithmetic in `README-SOUTHPOLE.md`

---

## TL;DR for the team

The spec is **sound in concept and wrong in detail**. Four blocking errors, all fixable. The physics idea is strong — W1 (1 m rock → 38 m shadow) is real, verified, and genuinely the best hook in the challenge. But the numbers you compute it from, and the coordinates you compute it at, are currently wrong.

**Read `constants.json` and `sites.json` before writing any code.** Do not copy numbers from the README.

---

## ✅ VERIFIED CORRECT — safe to build on

| Claim | Value | Note |
|---|---|---|
| Max Sun elevation at pole | 1.5424° | = lunar obliquity |
| Sun apparent diameter | 0.5334° | range 0.5246–0.5425 |
| **Shadow length** | **L = 37.20 × h** | at 1.5424°. This is W1. Exact. |
| Horizon distance | √(2Rh) | 4.17/18.64/41.68 km at h=5/100/500 m |
| Earth apparent diameter | 1.901° | 3.56× the Sun |
| Libration | ±7.9° lon, ±6.68° lat | |
| Draconic cycle | 18.6 yr (6793.5 d) | |
| Max sub-lunar parallax | 0.2590° | |
| Earth elevation formula | spherical law of cosines | correct as written |
| Earth elev @ −85° | +5.0° / +11.7° / −1.7° | **exact match** to spec |
| Earth elev @ −90° | 0.00° | **exact match** |

### Mazarico citation — the spec's hedge can be removed

> Mazarico, E., Neumann, G.A., Smith, D.E., Zuber, M.T., & Torrence, M.H. (2011).
> *Illumination Conditions of the Lunar Polar Regions Using LOLA Topography.*
> **Icarus**, 209(2), 634–641. doi:10.1016/j.icarus.2010.08.015 · NASA NTRS 20120010094

The claim is **accurate**. It precomputes horizon elevation per azimuthal bin at 0.5° resolution from 240 m/px DEMs and compares sun elevation against the horizon profile — exactly the max-per-azimuthal-bin method proposed. Useful bonus: it reports Shackleton rim has **~240 days/year continuous sunlight**, which is a ready-made cross-check target for our engine.

---

## ❌ BLOCKING ERRORS

### 1. Curvature correction wrong by ~6× — affects every horizon number

The *formula* is right. The *worked examples* are wrong.

| Distance | README §7.3 | **Verified** |
|---|---|---|
| 30 km | 42.2 m | **259 m** |
| 100 km | 469 m | **2877 m** |

42.2 m is the value at **12.1 km** — a distance mislabelled as 30 km. Both examples off by the same ~6× factor.

**Impact:** this is not cosmetic. The far-field curvature correction is the mechanism that makes distant ridges cast shadows onto a site. Understating it by 6× means **systematically overestimating illumination** — the exact failure mode §7.3 warns about, just with a bigger error bar than realised.

**Fix:** use `constants.json → CORRECTED_curvature_table`. Recompute everything downstream. The good news: the correction being *larger* than assumed strengthens the argument that far-field is mandatory, which is a better story than the original.

### 2. Site coordinate table is wrong — and contains non-existent features

The README flagged these as unverified. They are not merely unverified — several are **invented**.

| Site | README | **Verified (IAU)** | Status |
|---|---|---|---|
| Shackleton | −89.92, 175.1 | **−89.67, 129.78** (IAU 5450) | ❌ wrong |
| de Gerlache | −86.1, 91.8 | **−88.50, −87.10** (IAU 1439) | ❌ wrong by ~170° lon |
| Haworth | −85.88, 310.4 | **−86.90, −4.00** (IAU 14502) | ❌ wrong |
| Malapert | −85.45, 30.1 | **−84.90, 12.90** (IAU 3603) | ❌ wrong |
| Nobile | −85.72, 49.65 | **−85.28, 53.27** (IAU 4321) | ⚠️ close; "Rim 1/2" isn't a feature |
| Cabeus | −84.9, 309.5 | **−84.90, −35.50** (IAU 953) | ⚠️ lat right, lon wrong |
| Connecting Ridge | −85.45, 31.4 | *no such feature* | ❌ invented |
| Leibnitz-β plateau | −85.38, 30.1 | *no such feature* | ❌ invented |
| Mount Mouton | −86.08, 45.0 | **Mons Mouton** (IAU 16070), a *mons* | ❌ wrong type + coords |
| Malapert Massif / Nobile Rim / Slater Plain | listed | Artemis descriptors, not IAU names | ⚠️ anchor only |

Leibnitz crater is real but sits at **−38.17, 179.54** — nowhere near the pole. The README placed it at −85.38. That is a fabrication, not a typo.

**Impact:** every downstream computation inherits a wrong origin. Shadow length, Earth visibility, verdict output — all wrong.

**Fix:** `sites.json` has six IAU-verified sites with feature IDs. The nine current Artemis III regions have **names only** — NASA published no coordinates — so region→crater mapping in `sites.json` is explicitly labelled our approximation, not official.

### 3. `astronomy-engine` cannot do this job

| Claim | Reality |
|---|---|
| ~116 KB bundle | **~1.8 MB** (npm `astronomy-engine@2.1.19`) |
| Computes Sun/Earth from a lunar observer | **No lunar-surface observer API exists** |

`Observer` / `VectorObserver` are Earth-surface only. `BaryState` is barycentre-relative, not Moon-centred. The library cannot answer "what is the Sun's elevation from a point on the Moon."

**Impact:** §5 and §7.6 both promise a browser-side fallback that doesn't exist. Offline still works — baked artifacts are self-sufficient — but there is no live-compute path.

**Fix:** drop the runtime fallback. Everything is baked in Python; the browser reads static files. This *simplifies* the architecture. The one thing lost is scrubbing arbitrary dates without a rebuild — mitigate by baking a wide date range up front (see team split, Person 2).

### 4. Artifacts budget is ~44× over

| Component | README says | **Reality (10 sites)** |
|---|---|---|
| Cropped DEMs | "50 Mo per site" | ~500 MB |
| Ephemeris | 23 KB/site/day → 11 MB | 5.06 KB/site/day → **92 MB** for 5 yr |
| 18.6-yr maps | not counted | 60–90 MB |
| **Total** | **< 15 MB** (§5) | **~664 MB** |

§5's "< 15 Mo" and §6.1's "50 Mo per site" contradict each other by 33× within the same document. §9.1's struct is 18 bytes/record (4×f32 + 1×i16), not 4×5=20, so the ephemeris figure is both miscounted *and* mislabelled — the real number is *smaller* per day but the 5-year total is much larger than the 11 MB claim.

**Fix options, in order of preference:**
1. **Raise the budget and say so.** ~600 MB is a big download for a judge. But at a LAN event with Wi-Fi it's fine. Honestly labelled beats a fake number.
2. **Ship 3 sites, not 10** → ~200 MB. Better demo density, faster build, same story. **Recommended.**
3. Compress DEMs to Int16+zstd and crop to 25 km instead of 50 km.

**Recommendation:** 3–4 sites. The brief says compare sites and dates; four sites is enough to show range. Ten is padding that costs download time and build time for no judge-visible gain.

---

## ⚠️ Other flags

- **Use `de440s.bsp`, not `de440.bsp`.** Verified live: 32.7 MB vs 114 MB, no account. Same Moon/Sun/Earth accuracy for horizon work. Saves 82 MB of your download budget.
- **`moon_pa_de440_200625.bpc` is 12.3 MB, not ~1 MB** as the spec claimed. Still public domain, still no account.
- **`LDEM_87S` does not exist** as a standard product. The spec's plan to use a "87°S band strip" is fictional.
- **LOLA DEMs are tiled, not single-file.** The spec assumed one ~1 GB file. They're distributed as tiles via PDS/Astrogeology. **This is the #1 schedule risk** — see team split, Person 1.
- **25 m/px is not achievable from LOLA.** Native is 118 m/px at the poles; 25 m/px needs LROC NAC stereo DEMs (~1–2 m/px) with patchy coverage. Decide explicitly: honest 118 m/px, or LROC NAC where available.
- **No working Gazetteer REST API.** Verified 404/HTML across multiple endpoint shapes. `sites.json` coordinates came from Wikipedia infoboxes citing IAU IDs — re-confirm by hand before publishing.
- **NumPy/SciPy need Python ≥ 3.12.** Machine has 3.14 — fine. Pin versions if others contribute.
- **Disk:** 97% full, 8.2 GB free. `~/.cache` alone is 17 GB — clear before night 1.
- **§13 roadmap is 4 nights, not 48h.** §13 claims 48h (~12–15h coding) then lists N1–N4 night-sized milestones. Both can't be true.

---

### 5. DEM: RESOLVED — and better resolution than the spec assumed

**Status: done.** Three PDS tiles fetched and verified, covering all six catalogue sites.

| Tile | Coverage | Resolution | Size |
|---|---|---|---|
| `ldem_875s_10m.jp2` | 87.5°S–90°S | **10 m/px** | 62 MB |
| `ldem_85s_20m.jp2` | 85°S–90°S | **20 m/px** | 76 MB |
| `ldem_80s_20m.jp2` | 80°S–90°S | **20 m/px** | 255 MB |

Real path (the `lro/lola/` tree is a dead end):
```
https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/jp2/
```

**Correction to the spec's ceiling:** the spec assumed 118 m/px was the best available and that 25 m/px was fantasy. **10 m/px is real** for the innermost 2.5° of latitude. This materially improves horizon precision for Shackleton and de Gerlache — the two sites that matter most.

**The trap that costs the most time: `ldem_` vs `ldec_`.** These differ by two characters and mean completely different things:
- `ldem_*` — elevation in metres
- `ldec_*` — observation **count** per pixel (0–13)

A `ldec_` file opens cleanly, reports correct raster geometry and datatype, and produces "elevations" of 0–13 m. Nothing about the file looks wrong. `verify_dem.py` caught it on first run; the assertion now rejects it explicitly.

**Verified site elevations (all 6 resolve):**

| Site | Tile | Elevation | Local range |
|---|---|---|---|
| Shackleton | 875s (10 m) | **1515 m** | 1087–1917 m |
| de Gerlache | 875s (10 m) | **−3392 m** | −3906 to −2795 m |
| Haworth | 85s (20 m) | −5713 m | −5988 to −5641 m |
| Nobile | 85s (20 m) | −6481 m | −6619 to −6419 m |
| Malapert | 80s (20 m) | −4902 m | −5383 to −4390 m |
| Cabeus | 80s (20 m) | −5607 m | −5872 to −4947 m |

Shackleton's 1515 m is on the crater's **inner slope**, not the rim peak; de Gerlache's −3392 m is near its **floor**. The local ranges confirm genuine topography, not a flat fill. (Corrected 2026-11-15 — see the re-verification section at the end: within 10 km of the Shackleton anchor the DEM drops to −5566 m, so the anchor sits roughly 1.5 km up the wall, and the often-quoted "rim" reading was wrong.)

**Two GDAL performance notes** (in `verify_dem.py`): reading all three rasters in full takes 10+ minutes — use overviews. And `GetOverview(0)` is the *highest*-resolution overview, not the coarsest; use `GetOverviewCount()-1`. These tiles are square but their polar-stereographic content is circular, so corners are sentinel padding — restrict statistics to the inscribed circle or min/max becomes meaningless.

**Resolution caveat for the UI:** sites differ by tile (10 m vs 20 m), so horizon precision differs between them. Say so rather than implying uniform precision.

---

## Scope decision (per your instruction: I decide, and flag)

**Cut, from the bottom:**

| Cut | Why |
|---|---|
| ML/SHAP stretch goal | Already optional in spec; scientifically weakest, most verbose |
| 10 sites → 3–4 | Fixes artifact budget, build time, and demo focus in one move |
| Browser runtime fallback | Doesn't exist (§ above); baked-only is simpler and honest |
| 3D globe rendering | Spec already says no; keep it that way |
| Educator mode | Nice-to-have, only if time remains |

**Keep — this is the moat:**
- W1 shadow demo (verified, visceral, 10-second hook)
- W2 Earth-visibility map — the differentiator
- W3 one-click verdict
- Terrain-aware far-field horizon (6× stronger than believed → better science story)

**Fallback if the 18.6-year map won't finish:** ship a 1-year map and **label it as 1 year** in the UI. §6.5 already mandates this honesty. A labelled 1-year map beats an unlabelled incomplete 18.6-year one.
---

## Re-verification, 2026-11-15 — the coordinates and the illumination figures

Trigger: the demo verdict (Shackleton 27.8 % lit, 511 h longest dark run) reads low
against figures commonly quoted in the literature. Three hypotheses were tested;
two died.

**1. Longitude sign — no bug.** `planetarynames.wr.usgs.gov/Feature/5450` was fetched
on the day and returns `Coordinate System: Planetographic, +East, -180 - 180`,
`Center Latitude -89.67 °`, `Center Longitude 129.78 °`. That is byte-for-byte
`clps/sites.json`, and it matches the code's east-positive
`x = rho · sin(lon)`. The Gazetteer also lists older centre solutions from other
control networks; the newest one is the one in the catalogue.

**2. A 1-year span versus 18.6 years — not the explanation.** Rebaked per-site point
runs over the full lunar precession cycle (`/tmp/opencode/reverify_cycle.py`):

| Site | 1 yr, centre | 18.6 yr, centre | 1 yr, best pixel in crop |
|---|---|---|---|
| Shackleton | 27.6 % | 27.2 % | 66.8 % (67.3 % at 18.6 yr) |
| de Gerlache | 0.0 % | 0.0 % | 50.4 % (49.1 %) |
| Haworth | 7.7 % | — | 50.6 % |

Span moves the centre number by 0.4 points. It cannot turn 27 % into a
literature-grade number.

**3. The label — this was the real defect.** The baked values reproduce exactly
(27.79 % stored vs 27.6 % recomputed for a centre-of-Sun metric; the difference is
the metric, since the bake counts *any* part of the solar disc). What differs is the
**pixel**: published figures describe a rim peak or a candidate landing site, and the
catalogue stores the IAU feature **centre**. Measured on the same crop, the centre
sits high on Shackleton's inner slope: 1515 m, with terrain **−5566 m** inside a 10 km
radius. de Gerlache's anchor sits at −3392 m with −4709 m within 5 km, so its horizon
never drops below 10.04° and its centre never sees direct sun at all.

**Resolution: label, do not re-bake.** Every site now carries
`"site_kind": "IAU feature centre"` in `clps/sites.json` and `_meta.point_kind`
explaining it. `scripts/build_app.py` copies the field into `app-data.json`, and the
app prints the kind next to the coordinate above the panels and again in the verdict.
No number in the UI changed, and no literature value was pasted in.

**Nearest-pixel sampling is still deliberate.** Bilinear sampling of the same crop
gives Shackleton 41.9 % instead of 27.6 % — a smoother model, not a correction. The
project's contract is that every horizon number is traceable to one measured pixel;
that stays true.
