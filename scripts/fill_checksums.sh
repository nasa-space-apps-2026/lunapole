#!/usr/bin/env bash
# Update data/SOURCES.md with real SHA-256 checksums after data download.
# Run: bash scripts/fill_checksums.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCES="$ROOT/data/SOURCES.md"

if [[ ! -f "$SOURCES" ]]; then
  echo "ERROR: $SOURCES not found"
  exit 1
fi

echo "Computing SHA-256 checksums..."

fill() {
  local file="$1" label="$2"
  if [[ -f "$file" ]]; then
    local hash
    hash=$(sha256sum "$file" | cut -d' ' -f1)
    local short="${hash:0:16}…"
    echo "  $label: $hash"
    # Escape dots in label for sed
    local escaped
    escaped=$(printf '%s' "$label" | sed 's/\./\\./g')
    sed -i "s|\`${escaped}\`.*|& |" "$SOURCES" 2>/dev/null || true
  else
    echo "  [skip] $label not found"
  fi
}

# Compute all checksums and write them to a block at the end of SOURCES.md
{
  echo ""
  echo "### Computed checksums"
  echo ""
  echo '```'
  for f in "$ROOT"/data/dem/*.jp2 "$ROOT"/data/kernels/*; do
    if [[ -f "$f" ]]; then
      sha256sum "$f" | sed "s|$ROOT/||"
    fi
  done
  echo '```'
} > /tmp/opencode/checksums.txt

# Replace the placeholder block
python3 -c "
import re
src = open('$SOURCES').read()
chk = open('/tmp/opencode/checksums.txt').read()
# Replace everything after 'SHA-256 Checksums' heading
pat = r'(## SHA-256 Checksums\n).*'
repl = r'\1' + chk.replace('\\\\', '\\\\\\\\')
out = re.sub(pat, repl, src, flags=re.DOTALL)
open('$SOURCES', 'w').write(out)
"

echo ""
echo "Done. Checksums written to $SOURCES"
