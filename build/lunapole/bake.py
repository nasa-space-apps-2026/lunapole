#!/usr/bin/env python3
"""LUNAPOLE deterministic bake orchestrator — the P6 deliverable.

One command turns the P1–P4 stages into a reproducible artifact set plus
`artifacts/manifest.json`:

    python build/lunapole/bake.py --plan          # what would be built
    python build/lunapole/bake.py --profile demo  # bake + manifest
    python build/lunapole/bake.py --verify        # manifest vs disk
    python build/lunapole/bake.py --check         # rebake in temp, compare
    python build/lunapole/bake.py --manifest-only # hash an existing build

Design rules, all deliberate:

* **The bake owns `artifacts/ephemeris|horizon|maps`.** Files that are not
  in the plan are removed during promote, so a stale artifact cannot silently
  survive a parameter change. `artifacts/dem/` is an input and is never touched.
* **Staging, then promote.** Every product is written under
  `artifacts/.stage-<pid>/` first. The manifest is written last, atomically.
  A killed bake leaves the previous manifest in place; `--verify` then fails
  loudly rather than pretending the half-written set is good.
* **Hash the inputs too.** The manifest records SHA-256 for kernels, DEM
  tiles and per-site crops, and cross-checks the public sources listed in
  `data/SOURCES.md`. A changed kernel is a different build.
* **Fixed ordering and 1 thread by default.** No RNG, no wall-clock in the
  build identity, sorted JSON, LF-newline manifest bytes. `--check` rebakes
  into a temporary directory and compares SHA-256 per artifact.
* **No heavy imports at module load.** `--plan`, `--verify` and
  `--manifest-only` work without SPICE, rasterio, or data present. This is
  what lets `verify/doctor.py` explain what is missing instead of crashing.
* **Fail closed.** Missing prerequisites return exit code 2 (BLOCKED),
  a failed bake or a hash mismatch returns 1. Silent fallbacks are banned.

Manifest identity (`manifest_sha256`) covers the build parameters, input
hashes, artifact hashes and totals — not the timestamp, hostname, CLI line,
or git dirty flag. Two machines with the same inputs and parameters must
produce the same `manifest_sha256`.
"""
from __future__ import annotations

# --- UTF-8 console -------------------------------------------------------
# Prints °, +-, x and arrows. A Windows cp1252 console raises
# UnicodeEncodeError on the first of them, which kills the script after
# the work is done. Importing the bootstrap fixes the streams once.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
import _bootstrap  # noqa: E402

_bootstrap.utf8_streams()
# -------------------------------------------------------------------------


import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = ROOT / "build"
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

ARTIFACTS = ROOT / "artifacts"
DATA = ROOT / "data"
DEM_DIR = ARTIFACTS / "dem"
SITES_FILE = ROOT / "clps" / "sites.json"
CONSTANTS_FILE = ROOT / "clps" / "constants.json"
SOURCES_FILE = DATA / "SOURCES.md"
MANIFEST = ARTIFACTS / "manifest.json"

SCHEMA = "lunapole.manifest/1"
PRODUCT_DIRS = ("ephemeris", "horizon", "maps")

KERNELS = [
    "naif0012.tls",
    "pck00010.tpc",
    "de440s.bsp",
    "moon_pa_de440_200625.bpc",
]

# The map region -> LOLA tile dependency. Kept local so `--plan` does not
# import maps.py (which pulls in numpy/SPICE on some paths).
TILE_BY_REGION = {
    "polecap": "ldem_875s_10m.jp2",
    "southcap": "ldem_85s_20m.jp2",
}

# Demo = four contrasting sites, one synodic month of ephemeris, 1-year
# labelled map + per-site series. Full = all six sites + 18.6-yr point runs.
PROFILES = {
    "demo": {
        "start_utc": "2026-10-01 00:00:00",
        "sites": ["shackleton", "de_gerlache", "haworth", "nobile"],
        "ephemeris_days": 29.530588,
        "ephemeris_step_min": 5.0,
        "horizon_az_bins": 720,
        "horizon_max_dist_km": 25.0,
        "horizon_step_px": 1.0,
        "bake_maps": True,
        "maps_region": "polecap",
        "maps_span_days": 365.25,
        "maps_step_min": 60.0,
        "maps_grid_m": None,
        "maps_az_bins": 120,
        "bake_series": True,
        "series_span_days": 365.25,
        "series_step_min": 60.0,
        "series_disc_samples": 256,
        "fullcycle_runs": False,
        "fullcycle_step_min": 120.0,
    },
    "fast": {
        "start_utc": "2026-10-01 00:00:00",
        "sites": ["shackleton", "de_gerlache", "haworth", "nobile"],
        "ephemeris_days": 29.530588,
        "ephemeris_step_min": 5.0,
        "horizon_az_bins": 720,
        "horizon_max_dist_km": 25.0,
        "horizon_step_px": 1.0,
        "bake_maps": False,
        "maps_region": "polecap",
        "maps_span_days": 365.25,
        "maps_step_min": 60.0,
        "maps_grid_m": None,
        "maps_az_bins": 120,
        "bake_series": False,
        "series_span_days": 365.25,
        "series_step_min": 60.0,
        "series_disc_samples": 256,
        "fullcycle_runs": False,
        "fullcycle_step_min": 120.0,
    },
    "full": {
        "start_utc": "2026-10-01 00:00:00",
        "sites": ["shackleton", "de_gerlache", "haworth", "nobile",
                  "malapert", "cabeus"],
        "ephemeris_days": 29.530588,
        "ephemeris_step_min": 5.0,
        "horizon_az_bins": 720,
        "horizon_max_dist_km": 25.0,
        "horizon_step_px": 1.0,
        "bake_maps": True,
        "maps_region": "polecap",
        "maps_span_days": 365.25,
        "maps_step_min": 60.0,
        "maps_grid_m": None,
        "maps_az_bins": 120,
        "bake_series": True,
        "series_span_days": 365.25,
        "series_step_min": 60.0,
        "series_disc_samples": 256,
        "fullcycle_runs": True,
        "fullcycle_step_min": 120.0,
    },
}


class BakeError(RuntimeError):
    """A build error that should be reported as FAIL, not a traceback."""


class PrerequisiteError(BakeError):
    """Missing input/environment: report BLOCKED (exit 2), not FAIL."""


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------
def load_sites() -> list:
    return json.loads(SITES_FILE.read_text())["sites"]


def site_map() -> dict:
    return {s["id"]: s for s in load_sites()}


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_string(params: dict) -> str:
    start = params["start_utc"]
    return start if start.upper().endswith("UTC") else start + " UTC"


def _iso_from_epoch(epoch: str | None) -> str:
    if epoch is not None and str(epoch).strip():
        try:
            dt = datetime.fromtimestamp(int(epoch), timezone.utc)
        except (TypeError, ValueError) as exc:
            raise BakeError(f"invalid SOURCE_DATE_EPOCH {epoch!r}") from exc
    else:
        dt = datetime.now(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), *args],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _tool_versions() -> dict:
    versions = {"python": sys.version.split()[0]}
    for name in ("numpy", "spiceypy", "rasterio", "scipy"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _thread_env() -> dict:
    keys = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")
    return {k: os.environ.get(k) for k in keys}


def pin_threads(n: int) -> None:
    """Set thread controls before numpy/SPICE are imported."""
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[key] = str(n)


# ---------------------------------------------------------------------------
# parameters + expected artifact set
# ---------------------------------------------------------------------------
def resolve_params(profile: str, sites: str | None = None, *,
                   no_maps: bool = False, no_series: bool = False,
                   fullcycle_runs: bool = False,
                   ephemeris_days: float | None = None,
                   ephemeris_step_min: float | None = None,
                   maps_span_days: float | None = None,
                   maps_step_min: float | None = None,
                   maps_grid_m: float | None = None,
                   maps_az_bins: int | None = None) -> dict:
    if profile not in PROFILES:
        raise BakeError(f"unknown profile {profile!r}; choose {sorted(PROFILES)}")
    params = json.loads(json.dumps(PROFILES[profile]))
    if sites:
        params["sites"] = [s.strip() for s in sites.split(",") if s.strip()]
    known = site_map()
    unknown = [s for s in params["sites"] if s not in known]
    if unknown:
        raise BakeError(f"unknown site id(s): {', '.join(unknown)} "
                        f"(known: {', '.join(sorted(known))})")
    if no_maps:
        params["bake_maps"] = False
    if no_series:
        params["bake_series"] = False
    if fullcycle_runs:
        params["fullcycle_runs"] = True
    for key, value in (
        ("ephemeris_days", ephemeris_days),
        ("ephemeris_step_min", ephemeris_step_min),
        ("maps_span_days", maps_span_days),
        ("maps_step_min", maps_step_min),
        ("maps_grid_m", maps_grid_m),
        ("maps_az_bins", maps_az_bins),
    ):
        if value is not None:
            params[key] = value
    if params["bake_maps"] and params["maps_region"] not in TILE_BY_REGION:
        raise BakeError(f"unknown map region {params['maps_region']!r}")
    return params


def expected_artifacts(params: dict) -> list:
    """Logical, repo-relative artifact paths for a parameter set."""
    out = []
    for sid in params["sites"]:
        out.append(f"artifacts/ephemeris/{sid}.bin")
        out.append(f"artifacts/horizon/{sid}.bin")
    if params["bake_maps"]:
        days = int(round(params["maps_span_days"]))
        region = params["maps_region"]
        # maps.py writes stems from the product codes ILLU/ERTH, lowercased.
        for product in ("illu", "erth"):
            out.append(f"artifacts/maps/{region}_{product}_{days}d.bin")
            out.append(f"artifacts/maps/{region}_{product}_{days}d.png")
    if params["bake_series"]:
        days = int(round(params["series_span_days"]))
        for sid in params["sites"]:
            out.append(f"artifacts/maps/timeseries/{sid}_{days}d.json")
    if params["fullcycle_runs"]:
        for sid in params["sites"]:
            out.append(f"artifacts/maps/timeseries/{sid}_fullcycle_runs.json")
    # Manifest records are sorted so the canonical identity is order-stable.
    return sorted(out)


def _required_inputs(params: dict, dem_dir: Path) -> list:
    """(logical path, physical path, role) required for this parameter set."""
    req = []
    for name in KERNELS:
        req.append((f"data/kernels/{name}", DATA / "kernels" / name, "kernel"))
    for sid in params["sites"]:
        req.append((f"artifacts/dem/{sid}.tif", dem_dir / f"{sid}.tif",
                    "dem_crop"))
    if params["bake_maps"]:
        tile = TILE_BY_REGION[params["maps_region"]]
        req.append((f"data/dem/{tile}", DATA / "dem" / tile, "dem_tile"))
    return req


def _missing_packages() -> list:
    """Packages every bake path needs: numerics, SPICE, GeoTIFF reads.

    `--plan`, `--verify` and `--manifest-only` never call this, so they still
    work on a machine that cannot bake.
    """
    need = ["numpy", "spiceypy", "rasterio"]
    missing = []
    for name in need:
        if importlib.util.find_spec(name) is None:
            missing.append(f"python package: {name}")
    return missing


def prerequisites(params: dict, dem_dir: Path = DEM_DIR) -> list:
    """Human-readable list of BLOCKING problems. Empty == ready to bake."""
    missing = []
    if not SITES_FILE.exists():
        missing.append(f"missing {SITES_FILE.relative_to(ROOT)}")
    if not CONSTANTS_FILE.exists():
        missing.append(f"missing {CONSTANTS_FILE.relative_to(ROOT)}")
    missing.extend(_missing_packages())
    for logical, physical, _role in _required_inputs(params, dem_dir):
        if not physical.exists():
            missing.append(f"missing {logical}")
    if params["bake_maps"] and not SOURCES_FILE.exists():
        missing.append("missing data/SOURCES.md (checksum provenance)")
    return missing


def expected_hashes() -> dict:
    """filename -> sha256 parsed from data/SOURCES.md tables/code blocks."""
    if not SOURCES_FILE.exists():
        return {}
    out = {}
    for line in SOURCES_FILE.read_text(encoding="utf-8").splitlines():
        name = re.search(r"\b([A-Za-z0-9_.-]+\.(?:jp2|lbl|bsp|bpc|tls|tpc))\b",
                         line)
        digest = re.search(r"\b([0-9a-f]{64})\b", line)
        if name and digest:
            out[name.group(1)] = digest.group(1)
    return out


# ---------------------------------------------------------------------------
# header readers (stdlib only: --verify must work without SPICE/rasterio)
# ---------------------------------------------------------------------------
EPHEMERIS_HDR = "<8sH16sddI2f"
HORIZON_HDR = "<8sH16sI5f"


def _read_ephemeris_header(path: Path) -> dict:
    with open(path, "rb") as f:
        raw = f.read(struct.calcsize(EPHEMERIS_HDR))
    magic, ver, sid, et_start, step_s, count, lat, lon = \
        struct.unpack(EPHEMERIS_HDR, raw)
    if magic != b"LUNAEPH\0":
        raise BakeError(f"{path}: bad ephemeris magic {magic!r}")
    return {
        "site_id": sid.rstrip(b"\0").decode(),
        "version": ver,
        "et_start": et_start,
        "step_s": step_s,
        "count": count,
        "site_lat": lat,
        "site_lon": lon,
    }


def _read_horizon_header(path: Path) -> dict:
    with open(path, "rb") as f:
        raw = f.read(struct.calcsize(HORIZON_HDR))
    magic, ver, sid, az_bins, step_m, max_dist_km, lat, lon, h = \
        struct.unpack(HORIZON_HDR, raw)
    if magic != b"LUNAHOR\0":
        raise BakeError(f"{path}: bad horizon magic {magic!r}")
    return {
        "site_id": sid.rstrip(b"\0").decode(),
        "version": ver,
        "az_bins": az_bins,
        "step_m": step_m,
        "max_dist_km": max_dist_km,
        "site_lat": lat,
        "site_lon": lon,
        "site_h_m": h,
    }


def _read_map_header(path: Path) -> dict:
    with open(path, "rb") as f:
        data = f.read(8192)
    off = 0
    magic, ver, product, region = struct.unpack_from("<8sH4s16s", data, off)
    off += struct.calcsize("<8sH4s16s")
    if magic != b"LUNAMAP\0":
        raise BakeError(f"{path}: bad map magic {magic!r}")
    span_days, step_min, grid_m, az_bins = struct.unpack_from("<dddI",
                                                              data, off)
    off += struct.calcsize("<dddI")
    step_m, max_dist_km = struct.unpack_from("<dd", data, off)
    off += struct.calcsize("<dd")
    (start_et,) = struct.unpack_from("<d", data, off)
    off += struct.calcsize("<d")
    (samples,) = struct.unpack_from("<I", data, off)
    off += struct.calcsize("<I")
    width, height = struct.unpack_from("<II", data, off)
    off += struct.calcsize("<II")
    (llen,) = struct.unpack_from("<H", data, off)
    off += struct.calcsize("<H")
    label = data[off:off + llen].decode("utf-8", "replace")
    return {
        "product": product.decode().strip("\0"),
        "region": region.decode().rstrip("\0"),
        "version": ver,
        "span_days": span_days,
        "step_min": step_min,
        "grid_m": grid_m,
        "az_bins": az_bins,
        "step_m": step_m,
        "max_dist_km": max_dist_km,
        "start_et": start_et,
        "samples": samples,
        "width": width,
        "height": height,
        "span_label": label,
    }


def describe_artifact(logical: str, physical: Path) -> dict:
    """Hash + kind + header facts for one artifact."""
    suffix = physical.suffix.lower()
    kind = "unknown"
    header: dict = {}
    if logical.startswith("artifacts/ephemeris/") and suffix == ".bin":
        kind = "ephemeris"
        header = _read_ephemeris_header(physical)
    elif logical.startswith("artifacts/horizon/") and suffix == ".bin":
        kind = "horizon"
        header = _read_horizon_header(physical)
    elif "/maps/timeseries/" in logical and suffix == ".json":
        kind = "timeseries"
        payload = json.loads(physical.read_text(encoding="utf-8"))
        meta = payload.get("meta", {})
        header = {k: meta.get(k) for k in (
            "site_id", "span_days", "span_label", "step_min", "samples",
            "start_utc", "end_utc", "horizon_source", "disc_samples",
            "method", "honesty",
        )}
        header["verdict"] = payload.get("verdict", {})
    elif "/maps/" in logical and suffix == ".bin":
        kind = "map"
        header = _read_map_header(physical)
    elif "/maps/" in logical and suffix == ".png":
        kind = "map_png"
    return {
        "path": logical,
        "kind": kind,
        "bytes": physical.stat().st_size,
        "sha256": hash_file(physical),
        "header": header,
    }


# ---------------------------------------------------------------------------
# input hashing
# ---------------------------------------------------------------------------
def collect_inputs(params: dict, dem_dir: Path, *, strict: bool) -> tuple:
    """Return (inputs, missing, mismatched). In strict mode raise instead."""
    expected = expected_hashes()
    inputs, missing, mismatched = [], [], []
    for logical, physical, role in _required_inputs(params, dem_dir):
        if not physical.exists():
            missing.append(logical)
            continue
        digest = hash_file(physical)
        want = expected.get(physical.name)
        match = (want is None) or (want == digest)
        rec = {
            "path": logical,
            "role": role,
            "bytes": physical.stat().st_size,
            "sha256": digest,
            "expected_sha256": want,
            "match": match,
        }
        inputs.append(rec)
        if not match:
            mismatched.append((logical, want, digest))
    if strict and missing:
        raise PrerequisiteError(
            "missing required input(s):\n  - " + "\n  - ".join(missing))
    if strict and mismatched:
        lines = [f"{p}: expected {w}, got {g}" for p, w, g in mismatched]
        raise BakeError("input SHA-256 mismatch:\n  - " + "\n  - ".join(lines))
    return inputs, missing, mismatched


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
def _canonical_payload(manifest: dict) -> dict:
    """The part that defines a build identity. No clock, host, or CLI line."""
    return {
        "schema": manifest["schema"],
        "params": manifest["build"]["params"],
        "inputs": manifest["inputs"],
        "missing_inputs": manifest.get("missing_inputs", []),
        "artifacts": manifest["artifacts"],
        "totals": manifest["totals"],
    }


def manifest_sha256(manifest: dict) -> str:
    payload = json.dumps(_canonical_payload(manifest), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(params: dict, artifact_root: Path,
                   inputs: list, missing_inputs: list | None = None,
                   ) -> dict:
    artifacts = []
    missing = []
    for logical in expected_artifacts(params):
        physical = artifact_root / logical[len("artifacts/"):]
        if not physical.exists():
            missing.append(logical)
            continue
        artifacts.append(describe_artifact(logical, physical))
    if missing:
        raise BakeError("expected artifact(s) missing:\n  - "
                        + "\n  - ".join(missing))

    # No extra files in the product dirs: a stale map or old site must not
    # survive a parameter change and masquerade as part of this build.
    expected = set(expected_artifacts(params))
    extras = []
    for product in PRODUCT_DIRS:
        d = artifact_root / product
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                logical = "artifacts/" + p.relative_to(artifact_root).as_posix()
                if logical not in expected:
                    extras.append(logical)
    if extras:
        raise BakeError("unexpected artifact(s) in output root:\n  - "
                        + "\n  - ".join(extras))

    total_bytes = sum(a["bytes"] for a in artifacts)
    manifest = {
        "schema": SCHEMA,
        "build": {
            "profile": params.get("_profile"),
            "params": params,
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain")),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "generated_utc": _iso_from_epoch(os.environ.get("SOURCE_DATE_EPOCH")),
            "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH"),
            "threads": _thread_env(),
            "tool_versions": _tool_versions(),
            "command": " ".join(sys.argv),
        },
        "inputs": inputs,
        "missing_inputs": missing_inputs or [],
        "artifacts": artifacts,
        "totals": {
            "artifact_count": len(artifacts),
            "artifact_bytes": total_bytes,
            "artifact_mb": round(total_bytes / 1e6, 3),
        },
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    # write_bytes avoids Windows newline translation: manifest bytes are stable.
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def load_manifest(path: Path = MANIFEST) -> dict:
    if not path.exists():
        raise PrerequisiteError(
            f"no manifest at {path.relative_to(ROOT)} — run the bake first")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BakeError(f"{path}: invalid JSON: {exc}") from exc


def verify_manifest(manifest: dict, artifact_root: Path = ARTIFACTS, *,
                    check_inputs: bool = False) -> list:
    """Return a list of human-readable errors. Empty == good."""
    errors = []
    if manifest.get("schema") != SCHEMA:
        errors.append(f"schema {manifest.get('schema')!r} != {SCHEMA!r}")
        return errors
    try:
        want = manifest["manifest_sha256"]
    except KeyError:
        return ["manifest_sha256 missing"]
    try:
        got = manifest_sha256(manifest)
    except (KeyError, TypeError) as exc:
        return [f"manifest cannot be canonicalised: {exc}"]
    if want != got:
        errors.append(f"manifest_sha256 mismatch: recorded {want}, computed {got}")

    records = manifest.get("artifacts", [])
    paths = [r.get("path") for r in records]
    if paths != sorted(paths):
        errors.append("artifact list is not sorted")
    if len(paths) != len(set(paths)):
        errors.append("duplicate artifact paths in manifest")

    # The plan is derivable from the parameters, so a manifest that quietly
    # omits a planned artifact must fail even if its own hashes are consistent.
    try:
        planned = expected_artifacts(manifest["build"]["params"])
    except (KeyError, TypeError, AttributeError) as exc:
        errors.append(f"build.params cannot derive expected artifacts: {exc}")
    else:
        missing_planned = sorted(set(planned) - set(paths))
        unplanned = sorted(set(paths) - set(planned))
        if missing_planned:
            errors.append("planned artifact(s) absent from manifest: "
                          + ", ".join(missing_planned))
        if unplanned:
            errors.append("artifact(s) not in the plan: "
                          + ", ".join(unplanned))

    total = 0
    for rec in records:
        logical = rec.get("path", "")
        if not logical.startswith("artifacts/"):
            errors.append(f"{logical!r}: not under artifacts/")
            continue
        physical = artifact_root / logical[len("artifacts/"):]
        if not physical.exists():
            errors.append(f"{logical}: missing")
            continue
        size = physical.stat().st_size
        total += size
        if size != rec.get("bytes"):
            errors.append(f"{logical}: size {size} != recorded {rec.get('bytes')}")
        digest = hash_file(physical)
        if digest != rec.get("sha256"):
            errors.append(f"{logical}: sha256 {digest} != recorded {rec.get('sha256')}")
            continue
        try:
            fresh = describe_artifact(logical, physical)
        except Exception as exc:  # noqa: BLE001 - manifest verification reports all
            errors.append(f"{logical}: header unreadable: {exc}")
            continue
        if fresh["kind"] != rec.get("kind"):
            errors.append(f"{logical}: kind {fresh['kind']} != {rec.get('kind')}")
        if fresh["header"] != rec.get("header"):
            errors.append(f"{logical}: header fields differ from manifest")

    recorded_total = manifest.get("totals", {}).get("artifact_bytes")
    if recorded_total is not None and total != recorded_total:
        errors.append(f"totals.artifact_bytes {total} != recorded {recorded_total}")

    expected = {r.get("path") for r in records}
    for product in PRODUCT_DIRS:
        d = artifact_root / product
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                logical = "artifacts/" + p.relative_to(artifact_root).as_posix()
                if logical not in expected:
                    errors.append(f"{logical}: unexpected file not in manifest")

    if check_inputs:
        for rec in manifest.get("inputs", []):
            logical = rec.get("path", "")
            physical = ROOT / logical
            if not physical.exists():
                errors.append(f"input {logical}: missing")
                continue
            if physical.stat().st_size != rec.get("bytes"):
                errors.append(f"input {logical}: size changed")
            digest = hash_file(physical)
            if digest != rec.get("sha256"):
                errors.append(f"input {logical}: sha256 {digest} != recorded {rec.get('sha256')}")
    return errors


# ---------------------------------------------------------------------------
# baking
# ---------------------------------------------------------------------------
def _bake_ephemeris(params: dict, stage: Path, log) -> None:
    from lunapole import ephemeris, frames  # lazy: SPICE only when baking

    out_dir = stage / "ephemeris"
    out_dir.mkdir(parents=True, exist_ok=True)
    step_s = params["ephemeris_step_min"] * 60.0
    count = int(params["ephemeris_days"] * 86400.0 / step_s) + 1
    et_start = frames.utc_to_et(_utc_string(params))
    log(f"  ephemeris: {len(params['sites'])} site(s), {count} samples "
        f"@ {params['ephemeris_step_min']:g} min")

    # P2's bake_site writes to its module-level OUT_DIR. Redirect for the
    # staging directory, then restore on every path.
    previous = ephemeris.OUT_DIR
    ephemeris.OUT_DIR = out_dir
    try:
        for sid in params["sites"]:
            site = site_map()[sid]
            out = ephemeris.bake_site(
                site, et_start, step_s, count,
                progress_every=2000 if count > 5000 else 0)
            log(f"    {sid:<12} {out.stat().st_size / 1024:8.1f} kB")
    finally:
        ephemeris.OUT_DIR = previous


def _bake_horizons(params: dict, stage: Path, dem_dir: Path, log) -> None:
    from lunapole import dem as dem_mod, horizon

    out_dir = stage / "horizon"
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"  horizons: {params['horizon_az_bins']} bins, "
        f"{params['horizon_max_dist_km']:g} km, "
        f"{params['horizon_step_px']:g} px step")
    for sid in params["sites"]:
        d = dem_mod.Dem.for_site(sid, dem_dir=dem_dir)
        out, prof = horizon.bake_site(
            d, sid, out_dir=out_dir,
            az_bins=params["horizon_az_bins"],
            max_dist_km=params["horizon_max_dist_km"],
            step_px=params["horizon_step_px"])
        log(f"    {sid:<12} {horizon.summary(prof)}")


def _bake_maps(params: dict, stage: Path, log) -> None:
    from lunapole import maps

    log(f"  maps: {params['maps_region']} {params['maps_span_days']:.2f} d "
        f"@ {params['maps_step_min']:g} min, {params['maps_az_bins']} az bins")
    maps.build_region_map(
        params["maps_region"], params["maps_span_days"],
        params["maps_step_min"], grid_m=params["maps_grid_m"],
        az_bins=params["maps_az_bins"], out_dir=stage / "maps")


def _bake_series(params: dict, stage: Path, log) -> None:
    from lunapole import frames, maps

    step_s = params["series_step_min"] * 60.0
    span = params["series_span_days"]
    count = int(round(span * 86400.0 / step_s)) + 1
    et_start = frames.utc_to_et(_utc_string(params))
    log(f"  per-site series: {span:.2f} d @ "
        f"{params['series_step_min']:g} min ({count} samples)")
    ephem = maps.build_ephem_table(et_start, step_s, count, log_every=0)

    if abs(span - maps.DRACONIC_DAYS) < 1.0:
        label = (f"full {maps.DRACONIC_YEARS:g}-yr draconic cycle "
                 f"({maps.DRACONIC_DAYS:.0f} d)")
    else:
        label = (f"LABELLED PARTIAL: {span:.2f} d sampled — NOT the "
                 f"{maps.DRACONIC_YEARS:g}-yr draconic cycle")
    for sid in params["sites"]:
        out, payload = maps.site_time_series(
            site_map()[sid], ephem, params["series_step_min"],
            horizon_dir=stage / "horizon",
            disc_samples=params["series_disc_samples"],
            out_dir=stage / "maps", span_days=span, span_label=label)
        verdict = payload["verdict"]
        log(f"    {sid:<12} lit {verdict['lit_frac_at_disc']:.3f}  "
            f"Earth {verdict['earth_any_frac']:.3f}  "
            f"-> {out.name}")


def _bake_fullcycle(params: dict, stage: Path, log) -> None:
    from lunapole import frames, maps

    step_s = params["fullcycle_step_min"] * 60.0
    span = maps.DRACONIC_DAYS
    count = int(round(span * 86400.0 / step_s)) + 1
    et_start = frames.utc_to_et(_utc_string(params))
    log(f"  full-cycle point runs: {span:.0f} d @ "
        f"{params['fullcycle_step_min']:g} min ({count} samples)")
    ephem = maps.build_ephem_table(et_start, step_s, count, log_every=5000)
    for sid in params["sites"]:
        lookup = maps.horizon_lookup_from_artifact(
            sid, out_dir=stage / "horizon")
        out, payload = maps.site_fullcycle_runs(
            site_map()[sid], ephem, params["fullcycle_step_min"], lookup,
            out_dir=stage / "maps")
        v = payload["verdict"]
        log(f"    {sid:<12} lit {v['lit_frac']:.3f}  "
            f"Earth {v['earth_vis_frac']:.3f}  -> {out.name}")


def _promote(stage: Path, dest: Path) -> None:
    """Move each product file into place; remove stale files in the products.

    `artifacts/dem/` is an input and is never touched. The manifest is
    written by the caller only after this function succeeds.
    """
    for product in PRODUCT_DIRS:
        src = stage / product
        dst = dest / product
        planned = set()
        if src.exists():
            planned = {p.relative_to(src).as_posix()
                       for p in src.rglob("*") if p.is_file()}
        if not src.exists() or not planned:
            if dst.exists():
                shutil.rmtree(dst)
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for rel in sorted(planned):
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src / rel, target)
        files = sorted((p for p in dst.rglob("*") if p.is_file()),
                       key=lambda p: len(p.parts), reverse=True)
        for p in files:
            if p.relative_to(dst).as_posix() not in planned:
                p.unlink()
        dirs = sorted((p for p in dst.rglob("*") if p.is_dir()),
                      key=lambda p: len(p.parts), reverse=True)
        for p in dirs:
            if not any(p.iterdir()):
                p.rmdir()


def run_build(params: dict, dest_root: Path, dem_dir: Path, *,
              commit: bool, log=print) -> dict:
    """Build the full artifact set under dest_root. Returns the manifest."""
    stage = dest_root / f".stage-{os.getpid()}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    try:
        inputs, missing, _ = collect_inputs(params, dem_dir, strict=True)
        _bake_ephemeris(params, stage, log)
        _bake_horizons(params, stage, dem_dir, log)
        if params["bake_maps"]:
            _bake_maps(params, stage, log)
        if params["bake_series"]:
            _bake_series(params, stage, log)
        if params["fullcycle_runs"]:
            _bake_fullcycle(params, stage, log)
        manifest = build_manifest(params, stage, inputs, missing)
        if commit:
            dest_root.mkdir(parents=True, exist_ok=True)
            _promote(stage, dest_root)
            write_manifest(dest_root / "manifest.json", manifest)
        else:
            write_manifest(stage / "manifest.json", manifest)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def _print_plan(params: dict, dem_dir: Path) -> None:
    print(f"profile: {params.get('_profile', 'custom')}")
    print("parameters:")
    for key in sorted(params):
        if key.startswith("_"):
            continue
        print(f"  {key:22} {params[key]}")
    print(f"\nsites ({len(params['sites'])}): {', '.join(params['sites'])}")

    missing = prerequisites(params, dem_dir)
    print("\nprerequisites:")
    if missing:
        for item in missing:
            print(f"  [MISSING] {item}")
    else:
        print("  [OK] all required inputs and packages present")

    print("\nexpected artifacts:")
    step_s = params["ephemeris_step_min"] * 60.0
    count = int(params["ephemeris_days"] * 86400.0 / step_s) + 1
    eph_bytes = struct.calcsize(EPHEMERIS_HDR) + count * 32
    for logical in expected_artifacts(params):
        hint = ""
        if logical.startswith("artifacts/ephemeris/"):
            hint = f"  (~{eph_bytes / 1024:.1f} kB)"
        elif logical.startswith("artifacts/horizon/"):
            hint = "  (~9.9 kB)"
        print(f"  {logical}{hint}")
    print(f"\n{len(expected_artifacts(params))} artifact(s) planned")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")


def _print_manifest_summary(manifest: dict) -> None:
    totals = manifest["totals"]
    print(f"  manifest_sha256 {manifest['manifest_sha256']}")
    print(f"  artifacts       {totals['artifact_count']} files, "
          f"{totals['artifact_mb']:.2f} MB")
    print(f"  params          profile={manifest['build'].get('profile')!r}")
    labels = {a["header"].get("span_label")
              for a in manifest["artifacts"]
              if a["header"].get("span_label")}
    for label in sorted(labels):
        print(f"  span_label      {label}")


def _budget_check(manifest: dict, max_mb: float) -> bool:
    used = manifest["totals"]["artifact_mb"]
    ok = used <= max_mb
    print(f"  budget          {used:.2f} MB / {max_mb:g} MB "
          f"{'OK' if ok else 'OVER BUDGET'}")
    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="LUNAPOLE deterministic bake + SHA-256 manifest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""modes:
  (default)        bake the selected profile, promote, write manifest
  --plan           show parameters, blockers and expected artifacts
  --manifest-only  hash an existing artifact set and write the manifest
  --verify         verify manifest, artifacts, headers and staleness
  --check          rebake into a temp dir and compare SHA-256 per artifact
""")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--manifest-only", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--check", action="store_true")

    ap.add_argument("--profile", default="demo", choices=sorted(PROFILES))
    ap.add_argument("--sites", help="comma-separated site ids (overrides profile)")
    ap.add_argument("--no-maps", action="store_true", help="skip map products")
    ap.add_argument("--no-series", action="store_true", help="skip per-site JSON")
    ap.add_argument("--full-cycle-runs", action="store_true",
                    help="also bake 18.6-yr per-site point runs (expensive)")
    ap.add_argument("--ephemeris-days", type=float)
    ap.add_argument("--ephemeris-step-min", type=float)
    ap.add_argument("--maps-span-days", type=float)
    ap.add_argument("--maps-step-min", type=float)
    ap.add_argument("--maps-grid-m", type=float)
    ap.add_argument("--maps-az-bins", type=int)
    ap.add_argument("--dem-dir", default=str(DEM_DIR),
                    help="input crop directory (default artifacts/dem)")
    ap.add_argument("--threads", type=int, default=1,
                    help="thread count pinned for BLAS/OMP (default 1)")
    ap.add_argument("--source-date-epoch",
                    help="fixed timestamp for reproducible manifests")
    ap.add_argument("--max-artifact-mb", type=float, default=50.0)
    ap.add_argument("--force", action="store_true",
                    help="allow --manifest-only to overwrite an existing manifest")
    ap.add_argument("--verify-inputs", action="store_true",
                    help="with --verify, re-hash the recorded inputs too")
    args = ap.parse_args(argv)

    if args.source_date_epoch is not None:
        os.environ["SOURCE_DATE_EPOCH"] = args.source_date_epoch
    pin_threads(args.threads)

    try:
        if args.verify:
            manifest = load_manifest()
            errors = verify_manifest(manifest, check_inputs=args.verify_inputs)
            if errors:
                print(f"FAIL — {len(errors)} problem(s):")
                for err in errors:
                    print(f"  - {err}")
                return 1
            print("PASS — manifest, artifact hashes, headers and file set agree")
            _print_manifest_summary(manifest)
            _budget_check(manifest, args.max_artifact_mb)
            return 0

        if args.check:
            old = load_manifest()
            errors = verify_manifest(old)
            if errors:
                print("cannot --check: current manifest is not valid")
                for err in errors:
                    print(f"  - {err}")
                return 1
            params = old["build"]["params"]
            tmp = Path(tempfile.mkdtemp(prefix=".check-", dir=str(ARTIFACTS)))
            try:
                print("rebaking into a temporary directory for comparison...")
                new = run_build(params, tmp, Path(args.dem_dir), commit=False)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            old_map = {a["path"]: a["sha256"] for a in old["artifacts"]}
            new_map = {a["path"]: a["sha256"] for a in new["artifacts"]}
            diffs = []
            for path in sorted(set(old_map) | set(new_map)):
                if old_map.get(path) != new_map.get(path):
                    diffs.append(path)
            if old["manifest_sha256"] != new["manifest_sha256"]:
                diffs.append("manifest_sha256")
            if diffs:
                print(f"FAIL — not reproducible: {len(diffs)} difference(s)")
                for d in diffs:
                    print(f"  - {d}")
                return 1
            print("PASS — byte-identical artifacts; manifest identity matches")
            print(f"  manifest_sha256 {new['manifest_sha256']}")
            return 0

        params = resolve_params(
            args.profile, args.sites,
            no_maps=args.no_maps, no_series=args.no_series,
            fullcycle_runs=args.full_cycle_runs,
            ephemeris_days=args.ephemeris_days,
            ephemeris_step_min=args.ephemeris_step_min,
            maps_span_days=args.maps_span_days,
            maps_step_min=args.maps_step_min,
            maps_grid_m=args.maps_grid_m,
            maps_az_bins=args.maps_az_bins)
        params["_profile"] = args.profile
        dem_dir = Path(args.dem_dir)

        if args.plan:
            _print_plan(params, dem_dir)
            return 0

        if args.manifest_only:
            if MANIFEST.exists() and not args.force:
                raise BakeError(
                    f"{MANIFEST.relative_to(ROOT)} already exists; pass --force")
            missing_artifacts = [
                logical for logical in expected_artifacts(params)
                if not (ARTIFACTS / logical[len("artifacts/"):]).exists()
            ]
            if missing_artifacts:
                print(f"BLOCKED — {len(missing_artifacts)} expected "
                      f"artifact(s) missing:")
                for logical in missing_artifacts:
                    print(f"  - {logical}")
                print("\nBake first, or point --profile/--sites at the set "
                      "that exists.")
                return 2
            inputs, missing, mismatched = collect_inputs(
                params, dem_dir, strict=False)
            manifest = build_manifest(params, ARTIFACTS, inputs, missing)
            write_manifest(MANIFEST, manifest)
            print("wrote manifest from existing artifacts")
            _print_manifest_summary(manifest)
            for path, want, got in mismatched:
                print(f"  WARNING input {path}: expected {want}, got {got}")
            _budget_check(manifest, args.max_artifact_mb)
            return 0

        missing = prerequisites(params, dem_dir)
        if missing:
            print(f"BLOCKED — {len(missing)} prerequisite(s) missing:")
            for item in missing:
                print(f"  - {item}")
            print("\nSee: python verify/doctor.py")
            return 2

        print(f"baking profile {args.profile!r}: "
              f"{len(params['sites'])} site(s), {len(expected_artifacts(params))} "
              f"artifact(s)")
        manifest = run_build(params, ARTIFACTS, dem_dir, commit=True)
        print("\nPASS — build promoted; manifest written")
        _print_manifest_summary(manifest)
        if not _budget_check(manifest, args.max_artifact_mb):
            print("  (budget is a warning; lower resolution or fewer sites)")
        return 0
    except PrerequisiteError as exc:
        print(f"BLOCKED — {exc}")
        return 2
    except BakeError as exc:
        print(f"FAIL — {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
