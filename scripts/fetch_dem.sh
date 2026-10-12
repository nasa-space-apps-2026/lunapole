#!/usr/bin/env bash
# Fetch LUNAPOLE's south-pole DEMs. NASA PDS / LRO -- US public domain,
# no account, no EULA.
#
# CRITICAL: ldem_ vs ldec_
#   ldem_* = ELEVATION in metres. This is what we want.
#   ldec_* = observation COUNT per pixel (0..~13). Opens cleanly, has
#            plausible-looking numbers, and is completely wrong terrain.
# The two differ by two characters. verify_dem.py asserts you got ldem_.
set -euo pipefail

DATA_DIR="${DATA_DIR:-data/dem}"
mkdir -p "$DATA_DIR"

# The real tree is lro/lro-l-lola-3-rdr-v1/... -- lro/lola/ is a dead end.
BASE="https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/jp2"

fetch() {
  local name="$1"
  if [[ -s "$DATA_DIR/$name" ]]; then
    echo "  [skip] $name already present"
    return
  fi
  echo "  [get ] $name"
  curl -fL --retry 3 --retry-delay 2 -o "$DATA_DIR/$name.part" "$BASE/$name"
  mv "$DATA_DIR/$name.part" "$DATA_DIR/$name"
}

echo "Polar gridded DEMs (polar stereographic, south, true at pole)"

# 87.5S-90S at 10 m/px, 62 MB. Covers Shackleton (-89.67) and
# de Gerlache (-88.50). This is the core tile.
fetch "ldem_875s_10m_jp2.lbl"
fetch "ldem_875s_10m.jp2"

# 85S-90S at 20 m/px, 79 MB. Needed for the other four catalogue sites
# (Haworth, Nobile, Malapert, Cabeus are all at 84.9-86.9 S, outside the
# 87.5S tile). Uncomment when those sites are in scope.
# fetch "ldem_85s_20m_jp2.lbl"
# fetch "ldem_85s_20m.jp2"

echo
echo "Done. Verify with:"
echo "  python3 verify/verify_dem.py"
echo
echo "Decode: JP2 values ARE metres (SCALING_FACTOR=1, OFFSET=0). The sibling"
echo "IMG labels use scale 0.5 / offset 1737400 -- do not mix the two."