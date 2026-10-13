# LUNAPOLE — Data Sources

All data used in this project is **US public domain**. No accounts, no EULAs,
no registration required. Attribution appreciated, not legally required.

Verified: 2026-10-12

---

## DEM Tiles (LOLA Gridded Data Products)

Source: NASA PDS Geosciences Node / LRO LOLA RDR  
Base URL: `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/jp2/`

| File | Coverage | Resolution | Size | SHA-256 |
|---|---|---|---|---|
| `ldem_875s_10m.jp2` | 87.5°S–90°S | 10 m/px | 61.88 MB | `0f93158a9d591f6acadc90c5ba6470558242f6e5a318ad22c319c826410ceae7` |
| `ldem_875s_10m_jp2.lbl` | label | — | 6.3 KB | `d610ec32d2926da09f67e84b4c79b34b42492f1e38399751d9441be00a87afeb` |
| `ldem_85s_20m.jp2` | 85°S–90°S | 20 m/px | 75.48 MB | `66b8cafd638f7b710c11bfe962f35a5be8bffe744991e1eea848c24eb8dabc7c` |
| `ldem_85s_20m_jp2.lbl` | label | — | 6.3 KB | `61b5c47cf1a83160945cb264f9e96bd89b2a88c9d892e4c9fa73bf6f80d750b6` |
| `ldem_80s_20m.jp2` | 80°S–90°S | 20 m/px | 255.2 MB | `a38177093626d85ab6d38ffbd48bba6ac6842d5efee610aebc41cd9c54438dc6` |
| `ldem_80s_20m_jp2.lbl` | label | — | 6.3 KB | `48d80b4e0fd6dac9a5224f5e49904fa2c223119899cec1d19d8dd29f968a92ce` |

Downloaded 2026-10-13. Local path: `data/dem/`.

**CRITICAL:** `ldem_*` = elevation in metres. `ldec_*` = observation count per
pixel (0–13). They differ by two characters, open identically with GDAL, and
produce completely wrong results. `verify/verify_dem.py` rejects `ldec_` files.

Projection: polar stereographic, south pole, true scale at pole.  
Values: signed Int16, direct metres (SCALING_FACTOR=1, OFFSET=0 in JP2).

License: US public domain (NASA/LRO/LOLA).

---

## SPICE Kernels (NAIF/JPL)

Source: NASA NAIF Generic Kernels  
Base URL: `https://naif.jpl.nasa.gov/pub/naif/generic_kernels/`

| File | Type | Size | URL | SHA-256 |
|---|---|---|---|---|
| `de440s.bsp` | Planetary ephemeris (short) | 32 726 016 B | `spk/planets/de440s.bsp` | `c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2` |
| `moon_pa_de440_200625.bpc` | Lunar orientation + libration | 12 863 488 B | `pck/moon_pa_de440_200625.bpc` | `60cd55aa401ea2ea97360636f567554bfe4e37bb829f901b4460a455dfaf783f` |
| `naif0012.tls` | Leapseconds kernel | 5 257 B | `lsk/naif0012.tls` | `678e32bdb5a744117a467cd9601cd6b373f0e9bc9bbde1371d5eee39600a039b` |
| `pck00010.tpc` | Body radii (planetary constants) | 126 143 B | `pck/pck00010.tpc` | `59468328349aa730d18bf1f8d7e86efe6e40b75dfb921908f99321b3a7a701d2` |

Downloaded 2026-10-13. Local path: `data/kernels/`. Byte counts match
`constants.json → data_sources_verified` exactly.

**Note:** Use `de440s.bsp` (33 MB), NOT `de440.bsp` (114 MB). Same Moon/Sun/Earth
accuracy for horizon work, 82 MB smaller.

License: US public domain (NAIF/JPL).

---

## Site Coordinates

Source: IAU Gazetteer of Planetary Nomenclature  
URL: `https://planetarynames.wr.usgs.gov/`

Coordinates in `clps/sites.json` were verified against IAU feature IDs cited in
Wikipedia infoboxes. The REST API returns 404; verification was done by manual
lookup on the web interface.

| Site | IAU ID | Latitude | Longitude |
|---|---|---|---|
| Shackleton | 5450 | −89.67° | 129.78° |
| de Gerlache | 1439 | −88.50° | −87.10° |
| Haworth | 14502 | −86.90° | −4.00° |
| Nobile | 4321 | −85.28° | 53.27° |
| Malapert | 3603 | −84.90° | 12.90° |
| Cabeus | 953 | −84.90° | −35.50° |

---

## References

- Mazarico, E., Neumann, G.A., Smith, D.E., Zuber, M.T., & Torrence, M.H.
  (2011). *Illumination Conditions of the Lunar Polar Regions Using LOLA
  Topography.* Icarus, 209(2), 634–641. doi:10.1016/j.icarus.2010.08.015

- NASA (2022). *NASA Identifies Candidate Regions for Landing Next Americans on
  Moon.* 13 Artemis III candidate landing regions.

- NASA (2024). *NASA Provides Update on Artemis III Moon Landing Regions.*
  Updated to 9 regions.

- JGR Planets (2025). *Assessing Potential Landing Sites With Favorable
  Illumination and Accessible, Potentially Volatile-Rich Permanently Shadowed
  Regions Within Artemis Candidate Landing Regions.*
  doi:10.1029/2025JE009434

---

## SHA-256 Checksums

Computed 2026-10-13 on this machine after download:

```
a38177093626d85ab6d38ffbd48bba6ac6842d5efee610aebc41cd9c54438dc6  data/dem/ldem_80s_20m.jp2
66b8cafd638f7b710c11bfe962f35a5be8bffe744991e1eea848c24eb8dabc7c  data/dem/ldem_85s_20m.jp2
0f93158a9d591f6acadc90c5ba6470558242f6e5a318ad22c319c826410ceae7  data/dem/ldem_875s_10m.jp2
48d80b4e0fd6dac9a5224f5e49904fa2c223119899cec1d19d8dd29f968a92ce  data/dem/ldem_80s_20m_jp2.lbl
61b5c47cf1a83160945cb264f9e96bd89b2a88c9d892e4c9fa73bf6f80d750b6  data/dem/ldem_85s_20m_jp2.lbl
d610ec32d2926da09f67e84b4c79b34b42492f1e38399751d9441be00a87afeb  data/dem/ldem_875s_10m_jp2.lbl
c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2  data/kernels/de440s.bsp
60cd55aa401ea2ea97360636f567554bfe4e37bb829f901b4460a455dfaf783f  data/kernels/moon_pa_de440_200625.bpc
678e32bdb5a744117a467cd9601cd6b373f0e9bc9bbde1371d5eee39600a039b  data/kernels/naif0012.tls
59468328349aa730d18bf1f8d7e86efe6e40b75dfb921908f99321b3a7a701d2  data/kernels/pck00010.tpc
```

To re-verify:
```bash
sha256sum data/dem/*.jp2 data/dem/*.lbl data/kernels/*
```
