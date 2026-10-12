#!/usr/bin/env bash
# Fetch LUNAPOLE's public-domain NASA data.
# Everything here is US public domain: no account, no EULA, no registration.
#
# NOTE: LOLA DEM tiles are NOT included. The original spec assumed a single
# ~1 GB LDEM_75S file; that product is distributed as tiles via PDS/Astrogeology.
# Resolving the exact tile URLs is P1's first job — see TEAM_SPLIT.md.
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

echo
echo "Done. Verify with:"
echo "  sha256sum $DATA_DIR/*"
echo
echo "NOTE: DEM tiles still unresolved. See TEAM_SPLIT.md (P1)."