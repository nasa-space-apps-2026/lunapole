#!/usr/bin/env python3
"""Cross-platform downloader for LUNAPOLE's public-domain inputs.

This exists because scripts/*.sh are POSIX shell: on Windows they need a
bash that understands LF endings, and CRLF checkouts break their shebangs.
This script needs only Python 3.11+ and its standard library.

    python scripts/fetch_data.py --check     # verify files already present
    python scripts/fetch_data.py             # fetch whatever is missing
    python scripts/fetch_data.py --dem       # DEM tiles too (~410 MB)

Every file is written to <name>.part, the SHA-256 is checked against
data/SOURCES.md, and only then is it atomically renamed into place. A mismatch
deletes the partial file and exits non-zero, so a corrupt download can never be
mistaken for a valid input.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCES = DATA / "SOURCES.md"

KERNEL_BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/"
DEM_BASE = ("https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/"
            "lrolol_1xxx/data/lola_gdr/polar/jp2/")

KERNELS = {
    "de440s.bsp": KERNEL_BASE + "spk/planets/de440s.bsp",
    "moon_pa_de440_200625.bpc": KERNEL_BASE + "pck/moon_pa_de440_200625.bpc",
    "naif0012.tls": KERNEL_BASE + "lsk/naif0012.tls",
    "pck00010.tpc": KERNEL_BASE + "pck/pck00010.tpc",
}

DEMS = {
    "ldem_875s_10m.jp2": DEM_BASE + "ldem_875s_10m.jp2",
    "ldem_875s_10m_jp2.lbl": DEM_BASE + "ldem_875s_10m_jp2.lbl",
    "ldem_85s_20m.jp2": DEM_BASE + "ldem_85s_20m.jp2",
    "ldem_85s_20m_jp2.lbl": DEM_BASE + "ldem_85s_20m_jp2.lbl",
    "ldem_80s_20m.jp2": DEM_BASE + "ldem_80s_20m.jp2",
    "ldem_80s_20m_jp2.lbl": DEM_BASE + "ldem_80s_20m_jp2.lbl",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_expected() -> dict[str, str]:
    """SHA-256 per filename, read from the single source of truth."""
    text = SOURCES.read_text(encoding="utf-8", errors="replace")
    expected: dict[str, str] = {}
    for name, digest in re.findall(
            r"\|\s*`([^`]+)`\s*\|[^|]*\|[^|]*\|[^|]*\|\s*`([0-9a-f]{64})`\s*\|",
            text):
        expected[name] = digest
    return expected


def check(files: dict[str, str], expected: dict[str, str], label: str) -> bool:
    ok = True
    for name in files:
        path = DATA / label / name
        if not path.is_file():
            print(f"  [MISS] {label}/{name}")
            ok = False
            continue
        want = expected.get(name)
        if want is None:
            print(f"  [WARN] {label}/{name}: no SHA-256 listed in SOURCES.md")
            continue
        got = sha256(path)
        if got == want:
            print(f"  [ OK ] {label}/{name}  {path.stat().st_size} B")
        else:
            print(f"  [FAIL] {label}/{name}\n         want {want}\n         got  {got}")
            ok = False
    return ok


def fetch(files: dict[str, str], expected: dict[str, str], label: str) -> bool:
    dest_dir = DATA / label
    dest_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, url in files.items():
        dest = dest_dir / name
        want = expected.get(name)
        if dest.is_file() and want and sha256(dest) == want:
            print(f"  [skip] {label}/{name}")
            continue
        part = dest.with_suffix(dest.suffix + ".part")
        print(f"  [get ] {label}/{name}  <- {url}")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, \
                    part.open("wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                seen = 0
                for chunk in iter(lambda: resp.read(1 << 20), b""):
                    out.write(chunk)
                    seen += len(chunk)
                    if total:
                        print(f"\r         {seen / 1e6:7.1f} / "
                              f"{total / 1e6:7.1f} MB", end="", flush=True)
            print()
        except Exception as exc:  # noqa: BLE001 - report and fail closed
            part.unlink(missing_ok=True)
            print(f"  [FAIL] download failed: {exc}")
            ok = False
            continue
        if want:
            got = sha256(part)
            if got != want:
                part.unlink(missing_ok=True)
                print(f"  [FAIL] SHA-256 mismatch for {name}\n"
                      f"         want {want}\n         got  {got}")
                ok = False
                continue
        part.replace(dest)
        print(f"  [done] {label}/{name}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dem", action="store_true",
                    help="also fetch the ~410 MB LOLA DEM tiles")
    ap.add_argument("--check", action="store_true",
                    help="only verify what is already present; never download")
    args = ap.parse_args()

    expected = load_expected()
    if not expected:
        print(f"no SHA-256 table found in {SOURCES}", file=sys.stderr)
        return 1

    ok = True
    groups = [("kernels", KERNELS)]
    if args.dem:
        groups.append(("dem", DEMS))
    for label, files in groups:
        print(f"{label}:")
        ok &= (check(files, expected, label) if args.check
               else fetch(files, expected, label))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
