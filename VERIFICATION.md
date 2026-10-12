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

### 5. The DEM is tiled, and 25 m/px is fantasy

The spec assumed one ~1 GB `LDEM_75S` file plus a companion `LDEM_87S` "band". Reality:

- **`LDEM_87S` does not exist** as a standard product. The 87°S band plan is fictional.
- LOLA gridded products are distributed as **tiles** through PDS/Astrogeology, not a single file.
- **25 m/px cannot come from LOLA.** Native gridded resolution at the poles is 118 m/px. Getting to 25 m/px requires LROC NAC stereo DEMs (~1–2 m/px), which have limited and non-contiguous coverage.

**Impact:** the acquisition step in §6.1 is wrong in a way that blocks everything downstream. Someone must resolve exact tile URLs and decide the resolution strategy before a single DEM pixel exists.

**Good news:** all sources are US public domain. No account, no EULA, no registration anywhere. Once tiles are identified, downloads are fast and unencumbered.

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