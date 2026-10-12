# CLPS Lunar Mission Browser — Weekend Build Plan

## The problem, in one sentence

Mission planners, educators, and the public need to **compare lunar landing sites ×
dates** and instantly see Sun/Earth position above the local horizon — to judge
power-generation potential and direct-to-Earth (DTE) comms windows — because the
south pole's extreme lighting and geometry make or break a mission.

Your deliverable: pick two sites and two dates, and the tool shows which site is
viable and why. That is the whole demo.

---

## 1. The data (all public, all small)

### Site table — Artemis III candidate landing regions

NASA's 13 candidate regions (2022 release), each ~15 × 15 km, with landing sites
of ~100 m radius inside them. All within 6° of the south pole.

| # | Region | Notes |
|---|---|---|
| 1 | Faustini Rim A | Near Faustini crater |
| 2 | Peak Near Shackleton | Closest to the pole; high illumination |
| 3 | Connecting Ridge | 9 qualifying sites per AGU study |
| 4 | Connecting Ridge Extension | Only 1.9% of area landable — tight |
| 5 | de Gerlache Rim 1 | Eastern rim of de Gerlache crater |
| 6 | de Gerlache Rim 2 | Overlaps dGR1; largest landable fraction |
| 7 | de Gerlache-Kocher Massif | |
| 8 | Haworth | |
| 9 | Malapert Massif | Near IM-1's Malapert A |
| 10 | Leibnitz Beta Plateau | |
| 11 | Nobile Rim 1 | |
| 12 | Nobile Rim 2 | Best landable area: 56.9 km², 14% |
| 13 | Amundsen Rim | |

**Note:** NASA updated this to **9 regions** in 2024. Use the 13 for breadth in
the UI, but flag the 9 as the current set — judges like seeing you know the
difference.

### Precise coordinates (from AGU 2025 study, open access)

Verified lat/lon for real candidate sites — seed these directly into your DB:

**de Gerlache Rim 1 (dGR1)**
| Site | Latitude | Longitude |
|---|---|---|
| dGR101 | −88.5130 | −68.0150 |
| dGR102 | −88.9490 | −74.2120 |
| dGR103 | −88.4450 | −62.4910 |
| dGR104 | −88.4290 | −64.8770 |
| dGR105 | −88.6210 | −57.1840 |

**de Gerlache Rim 2 (dGR2)**
| Site | Latitude | Longitude |
|---|---|---|
| dGR201 | −88.3890 | −68.8650 |
| dGR202 | −88.0370 | −75.0440 |
| dGR203 | −88.1410 | −71.6960 |
| dGR204 | −88.1380 | −74.3330 |
| dGR205 | −88.0650 | −62.0740 |
| dGR206 | −87.9470 | −62.0980 |
| dGR2_K2023 | −88.4500 | −67.8590 |

Source: *"Assessing Potential Landing Sites With Favorable Illumination and
Accessible, Potentially Volatile-Rich Permanently Shadowed Regions Within
Artemis Candidate Landing Regions"*, JGR Planets, 2025 (doi:10.1029/2025JE009434).
Free full text — the Appendix has the full coordinate table. Mine it.

### CLPS task-order table (the "CLPS" in the title)

| Task Order | Vendor / Mission | Landing site | Status |
|---|---|---|---|
| TO2-AB | Astrobotic Peregrine 1 | — | Failed, no landing |
| TO2-IM | IM-1 Odysseus (Nova-C) | Malapert A, **80.13°S, 1.44°E** | Landed Feb 2024 |
| TO PRIME-1 | IM-2 Athena (Nova-C) | Mons Mouton | Landed Mar 2025 |
| TO 19D | Firefly Blue Ghost 1 | Mare Crisium | Landed Mar 2025 |
| CS-3 | Firefly Blue Ghost 2 | Lunar far side | Planned |
| TO CP-11 | IM-3 (Nova-C) | Reiner Gamma | Planned |
| TO 20A | Astrobotic Griffin (VIPER) | Lunar South Pole | Cancelled |
| TO CP-22 | IM (Nova-C) | Lunar South Pole | Planned |

**This is your differentiation.** The brief says "CLPS" — most teams will draw
Artemis boxes and stop. Layering the actual CLPS task orders on top, with real
landing coordinates and mission status, shows you read the source material.

### Basemaps and terrain

- **LPI Lunar South Pole Atlas** — https://www.lpi.usra.edu/lunar/lunar-south-pole-atlas/ — polar maps covering 85°S→pole, plus the Shackleton–de Gerlache corridor. Free PNGs.
- **LRO imagery** — Lunar Reconnaissance Orbiter products, the source NASA used to pick the sites.
- Quick win: NASA SVS has a ready-made **Artemis III Landing Region Candidates** visualization (svs.gsfc.nasa.gov/5013) — good reference for what the "official" view looks like.

---

## 2. The ephemeris engine

This is the whole technical core, and it's a solved problem.

**Use `skyfield` (Python) with JPL DE440 or DE441.**

```
pip install skyfield
```

```python
from skyfield.api import load
from skyfield.api import Topos  # careful at the poles — see gotcha below

ts = load.timescale()
eph = load('de440s.bsp')  # ~32 MB, downloads from JPL

earth = eph['earth']
moon  = eph['moon']
sun   = eph['sun']

# observer at a lunar surface site
moon_site = moon + Topos(latitude_deg=-88.5130,
                         longitude_deg=-68.0150,
                         elevation_m=0.0)
```

Then `alt, az, dist = (moon_site).at(t).observe(sun).apparent().altaz()` gives
Sun elevation above the local horizon. Same for Earth.

**Pre-compute, don't compute live.** Sample Sun/Earth elevation every hour for a
full lunar day (29.5 Earth days = ~708 samples) per site. That's trivially small
— cache it as JSON and the frontend is instant.

### The gotchas (these are what separate a real build from a toy)

1. **Librations matter.** The Moon wobbles, so a "fixed" site isn't inertially
   fixed. `skyfield`'s `Topos` on a `moon` vector handles this via the ephemeris'
   libration terms — do **not** naively treat the site as fixed in an inertial
   frame or your answers will be wrong by degrees.
2. **Frame conventions.** Confirm east/west sign conventions for lunar longitude
   against a known answer before trusting any output (see validation below).
3. **Lunar vs terrestrial time.** Don't mix TDB and UTC carelessly. Pick one
   convention for the UI (UTC is friendlier) and label it.
4. **Polar geometry is degenerate.** At −88°, az is nearly meaningless and small
   coordinate errors move the terminator a lot. Report **elevation** as the
   primary variable — that's what determines power anyway — and treat azimuth as
   secondary/illustrative.

### Sanity check (do this before anything else)

Verify your engine against a **published fact**: NASA states all 13 Artemis III
regions contain sites with **continuous sunlight throughout a 6.5-day surface
mission**. If your code says Peak Near Shackleton spends days in shadow at a
reasonable date, your frames are wrong. This single check catches ~90% of
coordinate-frame bugs.

---

## 3. Derived products (the actual features)

From hourly Sun/Earth elevation series, compute:

| Product | Why it's the point |
|---|---|
| **Sun elevation curve** | The core visualization. Over one lunar day, per site. |
| **Continuous-sunlight duration** | Longest unbroken stretch above horizon. Directly answers "can a 6.5-day mission survive here?" |
| **Power-generation potential** | Simple proxy: integrate a cosine of Sun elevation, × a panel-orientation assumption. Label it clearly as an estimate. |
| **Earth visibility / DTE windows** | Earth elevation over time → when can the lander talk to the Deep Space Network directly? |
| **Site × date matrix** | The "compare" feature the brief explicitly asks for. Rows = sites, columns = dates, cells = viable/not. |
| **Shadow/PSR proximity** | Distance from site to permanently shadowed regions (ice science access). Use the AGU paper's PSR tables. |

---

## 4. Weekend schedule

### Friday evening — "Walking skeleton" (3–4h)
- [ ] `pip install skyfield`, download DE440s, run one site, get a Sun elevation curve.
- [ ] **Run the sanity check.** Does Peak Near Shackleton get near-continuous sun? If not, stop and fix frames.
- [ ] Seed the site DB: 13 regions + the AGU coordinates + CLPS task orders.
- [ ] Deploy the API as a single serverless function returning precomputed JSON.

**Friday done = risk eliminated.** Everything after this is frontend and polish.

### Saturday — Build the interface (full day)
- [ ] **One main view:** a polar map (LPI atlas basemap) with sites as pins.
- [ ] Click a site → Sun/Earth elevation panel appears.
- [ ] **Date scrubber** — drag through a lunar day, Sun arcs across the sky.
- [ ] **Compare mode** — 2–3 sites side by side. This is the money screenshot.
- [ ] Site × date viability matrix.
- [ ] CLPS task-order layer toggle.

### Sunday morning — Polish + story (3–4h)
- [ ] Mobile check. Judges open links on phones.
- [ ] Write the 3-minute demo script (below).
- [ ] Pre-record a fallback screencast in case the venue Wi-Fi fails.
- [ ] One README with data sources cited.

**Schedule the demo script Saturday night, not Sunday.** Teams that improvise the
pitch always run long.

---

## 5. The 3-minute demo script

> "Planning a lunar landing at the south pole is a lighting and communications
> problem, not just a geography problem. Existing tools can do this — they're
> built for specialists.
>
> *(click site)* Here's de Gerlache Rim 2. Watch the Sun's elevation over a full
> lunar day. At this site you get continuous sunlight for X days — enough to
> power a 6.5-day surface mission.
>
> *(switch to compare)* Now compare it with Nobile Rim 2 for the same date.
> *(pause)* Nobile has more landable area, but loses the Sun sooner.
>
> *(toggle CLPS)* And here's where NASA has actually landed — IM-1 at Malapert A,
> IM-2 at Mons Mouton — so planners can see how future sites relate to proven
> ones.
>
> *(matrix)* Finally, the decision view: sites against dates. Green means a
> viable 6.5-day mission. This is the tool a mission planner, a teacher, or a
> curious member of the public can actually use."

**Rule of thumb:** talk for 90 seconds, let the tool move for 90 seconds.

---

## 6. Stretch goals (only if Sunday is free)

- Terrain-aware horizon — use LRO DEM to compute the *actual* local horizon
  instead of a flat sphere. This catches ridge shadows that flat geometry misses,
  and is genuinely how NASA does it. Highest-value technical addition.
- Real DSN geometry — model Earth as a disc, not a point; compute actual
  elevation/azimuth needed for a fixed lander antenna.
- "Educator mode" — a guided walkthrough explaining why south-pole sun behaves
  this way (it skims the horizon instead of rising/setting).

---

## 7. What not to do

- **Don't try full 3D globe rendering.** It eats a day and adds nothing the polar
  map doesn't already show.
- **Don't compute ephemerides live in the browser.** Precompute server-side.
- **Don't fake the numbers.** Judges at a NASA event include people who will
  notice. Use real DE440 data and cite it.
- **Don't skip the sanity check** to save 20 minutes on Friday.

---

## 8. Source list

| What | Where |
|---|---|
| Ephemerides DE440/DE441 | ssd.jpl.nasa.gov/planets/eph_export.html |
| skyfield docs | rhodesmill.org/skyfield |
| SPICE / WebGeocalc (cross-check) | naif.jpl.nasa.gov/naif/webgeocalc.html |
| 13 Artemis III regions (release) | nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/ |
| 2024 update (9 regions) | nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/ |
| **Site coordinates + PSR analysis** | doi:10.1029/2025JE009434 (open access — mine Appendix A) |
| CLPS task orders | nasa.gov/commercial-lunar-payload-services/clps-providers/ |
| CLPS science data + DOIs | pds-geosciences.wustl.edu/missions/clps/index.htm |
| Polar basemaps | lpi.usra.edu/lunar/lunar-south-pole-atlas/ |
| Reference visualization | svs.gsfc.nasa.gov/5013 |
