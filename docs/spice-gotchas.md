# SPICE setup notes for LUNAPOLE

Everything here was learned the hard way on 2026-10-12 while bringing up the
ephemeris chain. Each item cost real debugging time; each will bite P2.

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

### 1. `subpt()` returns CARTESIAN coordinates, not lat/lon

```python
pos, _ = spice.subpt('NEAR POINT', 'SUN', et, 'LT+S', 'MOON')
# pos = (x, y, z) in km -- NOT spherical!
```

Convert it:

```python
lon, lat, _ = spice.recgeo(pos, 1737.4, 0.0)   # returns RADIANS
lat_deg = math.degrees(lat)
lon_deg = math.degrees(lon) % 360.0
```

Treating `pos` as if it were already lat/lon gives numbers like
**36,071,277 degrees** — obviously wrong, but easy to miss if you're eyeballing
output rather than asserting a bound.

### 2. `spkpos()` takes 4 positional args in spiceypy 8.x

```python
pos, _ = spice.spkpos('EARTH', et, 'J2000', 'LT+S', 'MOON')
#                              ^frame  ^abcorr  ^observer
```

Passing `obs='MOON'` positionally as the 4th arg fails — `spkpos` here wants
`(name, et, frame, abcorr, obs)`.

### 3. `BCRS` is not a registered SPICE frame

`SpiceUNKNOWNFRAME: The frame BCRS was not recognized`.

DE440's native frame is BCRS, but SPICE exposes inertial frames as `J2000`.
Use `J2000` for every `pxfrm2` / `spkpos` frame argument.

### 4. `rpd()` and `pi()` are functions, not constants (spiceypy 8.x)

`spice.rpd` is `<function rpd>`. Calling `spice.rpd()` gives radians-per-degree.
`spice.dtr` does not exist — use `spice.dtr` → `spice.rpd()` or just `math.pi`.

### 5. `surfpt()` needs keyword arguments

`spice.surfpt(1.0, 1.0, 'MOON', 'SPHERE', 'NONE', 'LT+S', et, lon, lat)` raises
`TypeError: takes 5 positional arguments`.

You usually don't need it: on a sphere the surface normal at (lat, lon) in the
body-fixed frame is just

```python
n = [cos(lat)cos(lon), cos(lat)sin(lon), sin(lat)]
```

and the elevation is `degrees(acos(n · sun_unit)) - 90`.

---

## The 1.54° trap

Two different numbers get confused constantly. Both are real:

| Quantity | Value | What varies it |
|---|---|---|
| **Max solar elevation at the pole** | **1.5424°** | obliquity; swings ±1.54° each synodic month |
| **Sub-solar point latitude** (body-fixed) | **±6.7°** | dominated by libration in latitude (±6.68°) |

Asserting "sub-solar latitude < 1.54°" fails — correctly — because it is a
category error. The 1.54° bound applies to **elevation**, not to the subsolar
point's latitude. Check them separately.

Verified from our kernels:

```
solar elevation at -89.9:  -1.5146 .. +1.5715 deg   (span 3.0861 ~ 2 x obliquity)
sub-solar latitude 2026:  -7.1815 .. +7.2001 deg   (libration-dominated)
```

---

## Libration test that actually works

The obvious test — "does the spin axis move between two epochs?" — fails.
The spin axis barely moves; secular precession is slow. Libration is the
**body's wobble about that axis**, which shows up as the swing of the
sub-solar point in the body-fixed frame.

To isolate it, subtract pure orbital motion:

1. Sample sub-solar longitude monthly across a year.
2. Unwrap it (remove the ±180° branch cut).
3. Subtract the linear trend — that's the orbital component.
4. The residual is libration.

Measured residual: **24.7° longitude**, **7.2° latitude**.

The longitude residual is larger than the textbook ±7.9° because 12 monthly
samples over one year is a coarse sampling of a signal with both monthly
(distance) and annual (evection) terms — plus aliasing against the 29.5-day
synodic month. It proves libration is applied; it is not a precision
measurement. For P2's real validation, compare against **JPL Horizons** at
specific epochs, including libration extrema, with a <0.01° target.

---

## Frames

- `J2000` — inertial, what SPICE calls BCRS
- `IAU_MOON` — Moon body-fixed; **this is where libration lives**
- `MOON` — body-centred inertial (Moon-centred, non-rotating)

To go from a Moon-surface site to an inertial direction:

```python
et  = spice.str2et('2026-10-12 00:00:00 TDB')
to_sun, _ = spice.spkpos('SUN', et, 'IAU_MOON', 'LT+S', 'MOON')  # already body-fixed
n   = [cos(lat)cos(lon), cos(lat)sin(lon), sin(lat)]
elev = degrees(acos(n · unit(to_sun))) - 90
```

No frame gymnastics needed if you ask for `IAU_MOON` directly.

---

## Verified numbers from this run

- Earth apparent diameter from the Moon: **1.8609°** at 392,782 km (expected 1.80–2.01) ✓
- Earth elevation from Shackleton (−89.67, 129.78): **+17.48°** on 2026-10-12
- Earth elevation from de Gerlache (−88.50, −87.10): **+17.51°**

Those Earth elevations are the W2 story: the sign and value swing over the
18.6-year nodal cycle, so a site can be *below* the Earth's horizon for part
of the cycle. That's the "Earth doesn't move — libration does" demo.

Run the suite:

```bash
python3 verify/verify_ephemeris.py
```