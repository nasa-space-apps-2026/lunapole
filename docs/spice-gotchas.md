# SPICE setup notes for LUNAPOLE

Learned the hard way on 2026-10-12 (bring-up) and 2026-10-13 (validation
against JPL Horizons, which caught three real bugs). Each item cost real
debugging time; each will bite P2 and anything downstream.

---

## The four kernels you actually need

| Kernel | Why | Without it |
|---|---|---|
| `naif0012.tls` | leapseconds | `SpiceNOLEAPSECONDS` on the first `str2et()` |
| `pck00010.tpc` | **body radii** | `SpiceKERNELVARNOTFOUND: variable BODY10_RADII could not be found` |
| `de440s.bsp` | planetary ephemeris | no Sun/Earth/Moon positions |
| `moon_pa_de440_200625.bpc` | lunar orientation + libration | `IAU_MOON` frame undefined → no correct subsolar point |

`scripts/fetch_data.sh` pulls all four.

**There is no `naif0013.tls`.** Body radii live in `pck00010.tpc`. If you go
looking for a newer leapseconds file you will waste twenty minutes.

---

## API traps

### 1. `subpt()` ARGUMENT ORDER — the bug that shipped in verify_ephemeris.py

```python
# WRONG (this is what the first version of this doc taught):
cart, _ = spice.subpt('NEAR POINT', 'SUN', et, 'LT+S', 'MOON')
# -> point ON THE SUN where the MOON is at zenith, in IAU_SUN frame.

# RIGHT (sub-solar point ON THE MOON):
cart, _ = spice.subpt('NEAR POINT', 'MOON', et, 'NONE', 'SUN')
```

Signature: `subpt(method, target, et, abcorr, observer)`. The **Moon is the
target**; the Sun/Earth is the **observer**. Swapping them gives plausible
numbers (both live near the Sun–Moon line) but wrong body, wrong frame, and
a fake "libration" signal that is really IAU_SUN rotation. Caught on
2026-01-01 against Horizons: correct call gives lat −1.3444 lon 32.5959 vs
Horizons −1.3464/32.5196; the swapped call gave −2.98/299.03.

### 2. `subpt()` returns CARTESIAN coordinates, not lat/lon

```python
lon, lat, _ = spice.recgeo(cart, 1737.4, 0.0)   # returns RADIANS
lat_deg = math.degrees(lat)
lon_deg = math.degrees(lon) % 360.0
```

Treating `cart` as if it were already lat/lon gives numbers like
**36,071,277 degrees** — obviously wrong, but easy to miss if you're
eyeballing output rather than asserting a bound.

### 3. Elevation sign: it is `90 − acos`, not `acos − 90`

```python
elev = 90.0 - math.degrees(math.acos(n · unit(to_sun)))
```

`acos(dot)` is the zenith distance; elevation = 90° − zenith distance. The
first version of `verify_ephemeris.py`, `frames.elevation_of`, and the bake
in `ephemeris.py` all had `acos(dot) - 90`, which returns **−90° for a sun
at zenith**. Symmetric ±1.54° test bounds masked it for weeks. Caught on
2026-10-13 when daily sampling produced an asymmetric range that the sign
error made obvious.

### 4. `spkpos()` takes 5 positional args in spiceypy 8.x

```python
pos, _ = spice.spkpos('EARTH', et, 'J2000', 'LT+S', 'MOON')
#                              ^frame  ^abcorr  ^observer
```

Passing `obs='MOON'` positionally as the 4th arg fails — `spkpos` here wants
`(name, et, frame, abcorr, obs)`.

### 5. `BCRS` is not a registered SPICE frame

`SpiceUNKNOWNFRAME: The frame BCRS was not recognized`.

DE440's native frame is BCRS, but SPICE exposes inertial frames as `J2000`.
Use `J2000` for every `pxfrm2` / `spkpos` frame argument.

### 6. `rpd()` and `pi()` are functions, not constants (spiceypy 8.x)

`spice.rpd` is `<function rpd>`. Calling `spice.rpd()` gives radians-per-degree.
`spice.dtr` does not exist — use `spice.rpd()` or just `math.pi`.

### 7. `surfpt()` needs keyword arguments

`spice.surfpt(1.0, 1.0, 'MOON', 'SPHERE', 'NONE', 'LT+S', et, lon, lat)` raises
`TypeError: takes 5 positional arguments`.

You usually don't need it: on a sphere the surface normal at (lat, lon) in the
body-fixed frame is just `n = [cos(lat)cos(lon), cos(lat)sin(lon), sin(lat)]`.

---

## Aberration: which correction for which job

| Job | `abcorr` | Why |
|---|---|---|
| Compare sub-points vs Horizons | `NONE` | Horizons' sub-point products are geometric; `LT` differs by 0.076° (the Moon's rotation over solar light time, 499 s) |
| Shadow / illumination geometry | `LT` | photons received now left the Sun 499 s ago; shadow direction follows the retarded position. 0.076° is 5% of the 1.54° polar elevation and ~⅓ of the penumbra half-width (0.2667°) |
| `LT+S` (stellar aberration) | **avoid** | apparent-position effect; deliberately not applied to shadow geometry |

`frames.sub_point()` defaults to `NONE`; `frames.to_body_fixed()` and
`elevation_of()` default to `LT`. Both defaults are deliberate.

---

## The 1.54° trap (revised 2026-10-13 — the old table here was wrong)

Three quantities, three different periods. The old version of this doc
claimed sub-solar latitude swings ±6.7°; that was measured on the wrong
sub-point (bug #1) and is false.

| Quantity | Amplitude | Period | Why |
|---|---|---|---|
| Solar elevation at the EXACT pole | ±1.54° | **annual** | equals −(sub-solar latitude); longitude drops out of the dot product at the pole. The Sun circles the horizon: up ~half the year, down ~half. It does NOT rise and set monthly at the exact pole |
| Sub-solar point latitude (body-fixed) | ±1.54° | **annual** | the Sun stays in the ecliptic (|lat_sun| ≈ 0 from the Moon); only the 1.54° equator tilt projects on it |
| Sub-EARTH point latitude | ±6.68° | **monthly** | Earth's direction moves ±5.14° off the ecliptic as seen from the Moon (inclined orbit) + the same 1.54° tilt. **This** is libration in latitude |

Near-polar sites (not the exact pole) get a small monthly rise/set from the
cos(longitude) term: amplitude cos(89.67°) ≈ 0.33° at Shackleton.

Verified from our kernels, 2026-10-13 (corrected):

```
solar elevation at -89.9, monthly 2026:  -1.5715 .. +1.5146 deg  (span 3.0861 = 2 x obliquity)
sub-solar latitude monthly 2026:         -1.5560 .. +1.4779 deg  (span 3.0339, annual)
sub-Earth latitude, 70 daily samples:    -6.742  .. +6.830  deg  (half-amp 6.79 ~ 6.68)
sub-Earth longitude half-amp:            6.52 deg (~7.9 textbook; window-limited)
```

---

## Sampling aliasing: match the cadence to the signal

Two traps, both cost real time on 2026-10-13:

1. **Sub-solar longitude sweeps 360° per SYNODIC month (29.53 d).**
   Monthly samples (30.4 d spacing) alias each step down to ~−11°; unwrap
   cannot recover the true step (the alias IS a valid unwrapped path). Use
   **daily** sampling: 35 daily steps measure ~415°.
2. **Sub-solar latitude and polar elevation are ANNUAL.** 35 daily samples
   only cover a 0.9° arc of the 3.03° annual swing. Use **monthly** samples
   over a year.

The libration test that actually works is the **sub-EARTH point wobble**
sampled daily for ≥70 days (covers >2 anomalistic months and ~2 evection
periods, so longitude extremes are actually reached; a 40-day window
measured only 5.4° of the ~7.9°). No detrending needed — the sub-Earth
point sits near lon 0 (that IS tidal locking) and wobbles in place, unlike
the sub-solar longitude which sweeps the whole circle.

---

## JPL Horizons API notes (for verify_horizons.py)

- `CENTER='500@301'` with target `301` is rejected: *"Observer table for
  observer=target disallowed."* Use `CENTER='500@399'` (geocentre); the
  sub-points on the Moon are properties of the Moon, independent of the
  observer location.
- Quantity **14** = `ObsSub-LON, ObsSub-LAT` (sub-EARTH point on the Moon).
  Quantity **15** = `SunSub-LON, SunSub-LAT` (sub-SOLAR point). Combos work:
  `QUANTITIES='14,15'`.
- CSV column order is **LON then LAT**, not lat/lon. Swapping them yields
  separations of tens of degrees that look like a physics failure.
- Horizons calendar strings are `2026-Mar-01 00:00`. Sorting them
  lexicographically is **not chronological** (Apr < Feb < Jan < Jul < Jun <
  Mar < May) — parse to a real date key before any unwrap/detrend.
- Epoch matching: convert the calendar string with `utc2et()`, never rely
  on the output JD (TDB/UTC offset ~69 s = 0.01° at 13.2°/day).

---

## Frames

- `J2000` — inertial, what SPICE calls BCRS
- `IAU_MOON` — Moon body-fixed; **this is where libration lives**
- `MOON` — body-centred inertial (Moon-centred, non-rotating)

To go from a Moon-surface site to a shadow direction:

```python
et  = spice.str2et('2026-10-12 00:00:00 TDB')
to_sun, _ = spice.spkpos('SUN', et, 'IAU_MOON', 'LT', 'MOON')  # retarded, body-fixed
n    = [cos(lat)cos(lon), cos(lat)sin(lon), sin(lat)]
elev = 90.0 - degrees(acos(n · unit(to_sun)))
```

No frame gymnastics needed if you ask for `IAU_MOON` directly.

---

## Verified numbers from this run (2026-10-13, corrected)

- Earth apparent diameter from the Moon: **1.8609°** at 392,782 km ✓
- Earth elevation from Shackleton (−89.67, 129.78) on 2026-10-12:
  **−6.30°** — the Earth is BELOW the horizon there today. The old doc said
  +17.48°; that number came from the swapped `subpt()` call (it was the
  sub-LUNAR point on Earth, in IAU_EARTH coordinates, used as if lunar).
- Earth elevation from de Gerlache (−88.50, −87.10): **−6.15°** (was +17.51).

The W2 story survives the correction, in stronger form: not only does the
sign swing over the 18.6-year nodal cycle, it is negative *today* from
Shackleton — "Earth doesn't move — libration does" has a live
demonstration.

Run the suite:

```bash
python3 verify/verify_ephemeris.py   # local kernel sanity
python3 verify/verify_horizons.py    # vs JPL Horizons, < 0.01 deg gate
```
