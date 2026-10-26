#!/usr/bin/env python3
"""LUNAPOLE environment + artifact doctor.

Answers one question in one command: *what is stopping the demo right now?*

    python verify/doctor.py            # human-readable
    python verify/doctor.py --hash     # also hash the big DEM tiles
    python verify/doctor.py --json     # report, then machine-readable JSON

It deliberately imports no SPICE, rasterio, GDAL or numpy at module load, so
it still runs on a machine where the pipeline cannot. Absence is the thing
it is looking for.

Exit codes:
    0  READY    every required check passed
    1  FAIL     something is present but wrong (bad package, hash mismatch,
                unlabelled artifacts, manifest that does not verify)
    2  BLOCKED  a required input, tool or teammate deliverable is missing

Statuses are PASS / FAIL / SKIP / BLOCKED. SKIP means "not today's problem"
(optional package, network-only check); BLOCKED means "cannot proceed without
someone doing something". Missing P5 app is BLOCKED, not FAIL: P6 does not own
it, but the N4 demo cannot ship without it.
"""
from __future__ import annotations

# --- UTF-8 console -------------------------------------------------------
# Prints °, +-, x and arrows. A Windows cp1252 console raises
# UnicodeEncodeError on the first of them, which kills the script after
# the work is done. Importing the bootstrap fixes the streams once.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402

_bootstrap.utf8_streams()
# -------------------------------------------------------------------------


import argparse
import importlib.metadata
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from lunapole import bake  # noqa: E402  (stdlib-only by design)

SITES_FILE = ROOT / "clps" / "sites.json"
APP_DIR = ROOT / "app"
DIST_DIR = APP_DIR / "dist"
RESULTS = []

# All three published LOLA tiles are needed to crop the six catalogue sites,
# even though only two of them feed a map region.
ALL_TILES = (
    "ldem_875s_10m.jp2",
    "ldem_85s_20m.jp2",
    "ldem_80s_20m.jp2",
)


def record(group, name, status, detail, measured=None):
    RESULTS.append({
        "group": group,
        "check": name,
        "status": status,
        "detail": detail,
        "measured": measured,
    })
    tag = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP",
           "BLOCKED": "BLOCK"}[status]
    print(f"  [{tag:5}] {name}: {detail}")


def load_sites():
    return json.loads(SITES_FILE.read_text(encoding="utf-8"))["sites"]


def pkg_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def human_bytes(n):
    for unit in ("B", "kB", "MB", "GB"):
        if abs(n) < 1000.0 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1000.0
    return f"{n:.1f} GB"


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------
def check_python():
    got = sys.version_info
    ok = got >= (3, 12)
    record("environment", "python", "PASS" if ok else "FAIL",
           f"{sys.version.split()[0]} ({'>= 3.12' if ok else '< 3.12'})",
           measured={"major": got.major, "minor": got.minor,
                     "micro": got.micro})


def check_packages():
    required = {
        "numpy": "numerics for every product",
        "spiceypy": "P2/P3 astronomy (de440s + moon_pa)",
        "rasterio": "DEM crops and map windows",
    }
    for name, why in required.items():
        present = importlib.util.find_spec(name) is not None
        version = pkg_version(name) if present else None
        record("environment", f"package:{name}",
               "PASS" if present else "BLOCKED",
               f"{version or 'missing'} — {why}",
               measured={"installed": present, "version": version})

    # verify_dem.py reads tiles through rasterio; the GDAL bindings are
    # not required. Report them only if the machine happens to have them.
    present = importlib.util.find_spec("osgeo") is not None
    record("environment", "package:osgeo", "SKIP",
           f"{'installed' if present else 'absent'} - optional; "
           f"verify_dem.py uses rasterio",
           measured={"installed": present})

    for name in ("scipy", "zstandard"):
        present = importlib.util.find_spec(name) is not None
        record("environment", f"package:{name}", "SKIP",
               f"{pkg_version(name) if present else 'absent'} — "
               f"not imported by current code (optional)",
               measured={"installed": present})


def missing_raw_inputs():
    missing = []
    for name in bake.KERNELS:
        path = ROOT / "data" / "kernels" / name
        if not path.exists():
            missing.append(path)
    for tile in ALL_TILES:
        path = ROOT / "data" / "dem" / tile
        if not path.exists():
            missing.append(path)
    return missing


def missing_crops(sites):
    return [sid for sid in sites
            if not (ROOT / "artifacts" / "dem" / f"{sid}.tif").exists()]


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
def check_disk(sites):
    usage = shutil.disk_usage(ROOT)
    free = usage.free
    raw_missing = missing_raw_inputs()
    crops_missing = missing_crops(sites)
    have_manifest = bake.MANIFEST.exists()

    # Conservative planning estimate, not a measurement of the final tree.
    raw_bytes = 392_600_000 + 45_700_000
    if raw_missing:
        raw_cost = (raw_bytes if len(raw_missing) == 3 + len(bake.KERNELS)
                    else 80_000_000 * len(raw_missing))
    else:
        raw_cost = 0
    crop_cost = len(crops_missing) * 30_000_000
    artifact_cost = 0 if have_manifest else 30_000_000
    need = int((raw_cost + crop_cost + artifact_cost) * 1.25)

    if free < 250_000_000:
        status = "FAIL"
    elif free < need:
        status = "BLOCKED"
    else:
        status = "PASS"
    record("environment", "disk", status,
           f"{human_bytes(free)} free; planning need ~{human_bytes(need)} "
           f"(raw {human_bytes(raw_cost)}, crops {human_bytes(crop_cost)}, "
           f"artifacts {human_bytes(artifact_cost)}, +25% headroom)",
           measured={"free_bytes": free, "planning_need_bytes": need,
                     "raw_missing": len(raw_missing),
                     "crops_missing": len(crops_missing)})


def check_kernels(do_hash):
    expected = bake.expected_hashes()
    present = 0
    for name in bake.KERNELS:
        path = ROOT / "data" / "kernels" / name
        if not path.exists():
            record("inputs", f"kernel:{name}", "BLOCKED", "missing",
                   measured={"path": str(path.relative_to(ROOT))})
            continue
        present += 1
        size = path.stat().st_size
        want = expected.get(name)
        detail = human_bytes(size)
        status = "PASS"
        if do_hash and want:
            got = bake.hash_file(path)
            if got != want:
                status = "FAIL"
                detail = f"sha256 {got[:12]}… != published {want[:12]}…"
            else:
                detail += f", sha256 {got[:12]}… matches SOURCES.md"
        elif want:
            detail += ", published digest present (use --hash to check)"
        record("inputs", f"kernel:{name}", status, detail,
               measured={"bytes": size, "sha256_expected": want})
    record("inputs", "kernels summary",
           "PASS" if present == len(bake.KERNELS) else "BLOCKED",
           f"{present}/{len(bake.KERNELS)} kernels present")


def check_tiles(do_hash):
    expected = bake.expected_hashes()
    tiles = ALL_TILES
    present = 0
    for name in tiles:
        path = ROOT / "data" / "dem" / name
        if not path.exists():
            record("inputs", f"tile:{name}", "BLOCKED", "missing")
            continue
        present += 1
        size = path.stat().st_size
        want = expected.get(name)
        status, detail = "PASS", human_bytes(size)
        if do_hash and want:
            got = bake.hash_file(path)
            if got != want:
                status = "FAIL"
                detail = f"sha256 {got[:12]}… != published {want[:12]}…"
            else:
                detail += f", sha256 {got[:12]}… matches SOURCES.md"
        elif want:
            detail += ", published digest present (use --hash to check)"
        record("inputs", f"tile:{name}", status, detail,
               measured={"bytes": size, "sha256_expected": want})
    record("inputs", "tiles summary",
           "PASS" if present == len(tiles) else "BLOCKED",
           f"{present}/{len(tiles)} DEM tiles present")


def check_crops(sites):
    present = 0
    for site in sites:
        sid = site["id"]
        path = ROOT / "artifacts" / "dem" / f"{sid}.tif"
        if path.exists() and path.stat().st_size > 0:
            present += 1
            record("inputs", f"crop:{sid}", "PASS",
                   human_bytes(path.stat().st_size))
        else:
            record("inputs", f"crop:{sid}", "BLOCKED",
                   "missing — run scripts/crop_sites.py")
    record("inputs", "crops summary",
           "PASS" if present == len(sites) else "BLOCKED",
           f"{present}/{len(sites)} site crops present "
           f"(artifacts/dem/<site>.tif)")


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------
def artifact_inventory():
    roots = [ROOT / "artifacts" / name for name in bake.PRODUCT_DIRS]
    files = []
    for root in roots:
        if root.exists():
            files.extend(p for p in root.rglob("*") if p.is_file())
    return files


def check_artifacts():
    files = artifact_inventory()
    total = sum(p.stat().st_size for p in files)
    if not files:
        record("artifacts", "artifact set", "BLOCKED",
               "none — run python build/lunapole/bake.py")
    else:
        record("artifacts", "artifact set", "PASS",
               f"{len(files)} file(s), {human_bytes(total)}",
               measured={"files": len(files), "bytes": total})

    if not bake.MANIFEST.exists():
        record("artifacts", "manifest", "BLOCKED",
               "artifacts/manifest.json missing — bake, or use "
               "--manifest-only for an existing build")
        return
    if not files:
        record("artifacts", "manifest", "FAIL",
               "manifest exists but no artifacts: stale or hand-written")
        return
    try:
        manifest = bake.load_manifest()
        errors = bake.verify_manifest(manifest)
    except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
        record("artifacts", "manifest", "FAIL", f"invalid: {exc}")
        return
    if errors:
        record("artifacts", "manifest", "FAIL",
               f"{len(errors)} problem(s); first: {errors[0]}",
               measured={"errors": errors})
    else:
        record("artifacts", "manifest", "PASS",
               f"{manifest['totals']['artifact_count']} artifact(s), "
               f"{manifest['totals']['artifact_mb']:.2f} MB, "
               f"manifest_sha256 {manifest['manifest_sha256'][:16]}…",
               measured={"manifest_sha256": manifest["manifest_sha256"],
                         "artifact_count": manifest["totals"]["artifact_count"],
                         "artifact_mb": manifest["totals"]["artifact_mb"]})


# ---------------------------------------------------------------------------
# application (P5) + demo (P6, N4)
# ---------------------------------------------------------------------------
EXTERNAL_RE = re.compile(
    r"""(?:
        (?:src|href)\s*=\s*["']\s*(?:(?:https?:)?//)
      | import\s*(?:\(\s*)?["']\s*(?:(?:https?:)?//)
      | from\s*["']\s*(?:(?:https?:)?//)
      | (?:fetch|importScripts|new\s+Worker)\s*\(\s*["']\s*(?:(?:https?:)?//)
      | new\s+URL\s*\(\s*["']\s*(?:(?:https?:)?//)
      | url\(\s*["']?\s*(?:(?:https?:)?//)
      | @import\s+(?:url\(\s*)?["']?\s*(?:(?:https?:)?//)
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def find_three():
    candidates = []
    for base in (APP_DIR / "node_modules" / "three", APP_DIR / "vendor" / "three",
                 APP_DIR / "vendor", APP_DIR / "public" / "vendor"):
        if base.exists():
            candidates.extend(base.rglob("three.module*.js"))
    return candidates


def check_app():
    if not APP_DIR.exists():
        record("app", "app tree", "BLOCKED",
               "app/ absent — P5 deliverable not landed")
        record("app", "offline bundle", "BLOCKED", "nothing to scan")
        return
    record("app", "app tree", "PASS", "app/ present")

    index = DIST_DIR / "index.html"
    if not index.exists():
        record("app", "offline build", "BLOCKED",
               "app/dist/index.html missing — run the offline build")
        record("app", "offline bundle", "BLOCKED", "no dist to scan")
        return

    three = find_three()
    pkg_path = APP_DIR / "package.json"
    pinned = None
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            pinned = (pkg.get("dependencies", {}).get("three")
                      or pkg.get("devDependencies", {}).get("three"))
        except json.JSONDecodeError:
            pinned = None
    if three or pinned:
        where = (three[0].relative_to(ROOT).as_posix() if three
                 else f"pinned in package.json ({pinned})")
        record("app", "three vendored", "PASS",
               f"offline source present: {where}")
    else:
        record("app", "three vendored", "FAIL",
               "no three.module*.js and no three pin in app/package.json — "
               "zero-CDN rule at risk")

    refs = []
    for path in DIST_DIR.rglob("*"):
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        if path.suffix.lower() not in {".html", ".htm", ".js", ".mjs",
                                       ".css", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in EXTERNAL_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            refs.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
    if refs:
        record("app", "offline bundle", "FAIL",
               f"{len(refs)} external runtime reference(s); first: {refs[0]}",
               measured={"references": refs[:50]})
    else:
        record("app", "offline bundle", "PASS",
               "no external runtime URLs in dist; vendored modules only",
               measured={"files_scanned": sum(
                   1 for p in DIST_DIR.rglob("*") if p.is_file())})


def check_demo_docs():
    script = ROOT / "docs" / "demo-script.md"
    record("demo", "demo script", "PASS" if script.exists() else "FAIL",
           "docs/demo-script.md present" if script.exists()
           else "docs/demo-script.md missing")

    readme = ROOT / "README.md"
    if not readme.exists():
        record("demo", "README honest", "FAIL", "README.md missing")
        return
    text = readme.read_text(encoding="utf-8", errors="replace")
    required = {
        "limitations": re.search(r"(?im)^#{1,3}\s+.*limitation", text),
        "measured": re.search(r"(?im)^#{1,3}\s+.*(measured|verification)", text),
        "manifest": re.search(r"(?im)^#{1,3}\s+.*manifest", text),
    }
    missing = [name for name, found in required.items() if not found]
    record("demo", "README honest",
           "PASS" if not missing else "FAIL",
           "has limitations, measured-results and manifest sections"
           if not missing else f"missing section(s): {', '.join(missing)}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="LUNAPOLE environment doctor")
    ap.add_argument("--hash", action="store_true",
                    help="hash DEM tiles as well as kernels/crops")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON after the report")
    args = ap.parse_args(argv)

    print("LUNAPOLE doctor")
    print(f"  root  {ROOT}")
    print(f"  mode  {'hash all inputs' if args.hash else 'presence + size'}"
          "\n")

    sites = load_sites()
    print("environment")
    check_python()
    check_packages()
    check_disk(sites)

    print("\ninputs")
    check_kernels(args.hash)
    check_tiles(args.hash)
    check_crops(sites)

    print("\nartifacts")
    check_artifacts()

    print("\napplication (P5)")
    check_app()

    print("\ndemo (P6 / N4)")
    check_demo_docs()

    counts = {s: sum(1 for r in RESULTS if r["status"] == s)
              for s in ("PASS", "FAIL", "SKIP", "BLOCKED")}
    if counts["BLOCKED"]:
        overall = "BLOCKED"
    elif counts["FAIL"]:
        overall = "FAIL"
    else:
        overall = "READY"
    print(f"\n{overall} — {counts['PASS']} pass, {counts['FAIL']} fail, "
          f"{counts['BLOCKED']} blocked, {counts['SKIP']} skipped")

    if counts["BLOCKED"]:
        print("\nblocking:")
        for rec in RESULTS:
            if rec["status"] == "BLOCKED":
                print(f"  - {rec['group']}/{rec['check']}: {rec['detail']}")
    if counts["FAIL"]:
        print("\nfailing:")
        for rec in RESULTS:
            if rec["status"] == "FAIL":
                print(f"  - {rec['group']}/{rec['check']}: {rec['detail']}")

    if args.json:
        print("\n" + json.dumps({
            "schema": "lunapole.doctor/1",
            "root": str(ROOT),
            "overall": overall,
            "counts": counts,
            "checks": RESULTS,
        }, indent=2, sort_keys=True))

    return {"READY": 0, "FAIL": 1, "BLOCKED": 2}[overall]


if __name__ == "__main__":
    sys.exit(main())
