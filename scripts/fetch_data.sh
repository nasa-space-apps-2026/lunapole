#!/usr/bin/env bash
# Fetch LUNAPOLE's public-domain NASA data.
# Everything here is US public domain: no account, no EULA, no registration.
#
# NOTE: LOLA DEM tiles are NOT downloaded here. They are handled by
# `scripts/fetch_dem.sh` (three polar tiles, ~393 MB, public domain).
# Run both scripts before cropping.
set -euo pipefail

DATA_DIR="${DATA_DIR:-data/kernels}"
mkdir -p "$DATA_DIR"

fetch() {
  local url="$1" dest="$2"
  if [[ -s "$dest" ]]; then
    echo "  [skip] $(basename "$dest") already present"
    return
  fi
  echo "  [get ] $(basename "$dest")"
  curl -fL --retry 3 --retry-delay 2 -o "$dest.part" "$url"
  mv "$dest.part" "$dest"
}

echo "NAIF/JPL ephemeris + orientation kernels"

# Use de440s.bsp (33 MB), NOT de440.bsp (114 MB): same Moon/Sun/Earth accuracy
# for horizon work, 82 MB smaller. Full kernel is the documented fallback.
fetch "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp" \
      "$DATA_DIR/de440s.bsp"

# Lunar orientation + libration PCK. Spec claimed ~1 MB; actual 12.3 MB.
fetch "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/moon_pa_de440_200625.bpc" \
      "$DATA_DIR/moon_pa_de440_200625.bpc"

# --- two more kernels SPICE needs before anything works ---
# Verified the hard way: without each of these you get a confusing error.

# Leapseconds. Without it: SpiceNOLEAPSECONDS on the first str2et().
fetch "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls" \
      "$DATA_DIR/naif0012.tls"

# Body radii. Without it: SpiceKERNELVARNOTFOUND, "variable BODY10_RADII
# could not be found". This is what makes subpt() work. There is no
# naif0013.tls -- do not go looking for one.
fetch "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00010.tpc" \
      "$DATA_DIR/pck00010.tpc"

echo
echo "Done. Verify with:"
echo "  sha256sum $DATA_DIR/*"
echo
echo "Sanity-check the whole chain:"
echo "  python3 verify/verify_ephemeris.py"
echo
echo "NOTE: DEM tiles are fetched separately: bash scripts/fetch_dem.sh"