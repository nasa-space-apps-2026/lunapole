#!/usr/bin/env python3
"""LUNAPOLE verification runner — one command, four gates, measured output.

    python verify/run_all.py                 # safe checks (no network, no real terrain)
    python verify/run_all.py --real          # add the real-map checks (N2/N3)
    python verify/run_all.py --check         # add bake --verify and --check (N3)
    python verify/run_all.py --real --check  # everything automatable
    python verify/run_all.py --no-network    # skip the JPL Horizons comparison
    python verify/run_all.py --list          # show checks without running

Every check is a real subprocess or a real file inspection. Nothing is
declared correct because a script exists. Missing packages, data, artifacts or
P5 deliverables are reported as BLOCKED (exit 2), not as a pass. Manual checks
(N4 rehearsal, phone-offline, UI latency) stay BLOCKED until a human attests
them with `--attest <check-id>=<note>`; the attestation is written to
`verify/results.json` with the note, so the claim is traceable.

Status model:
    PASS     ran and exited 0
    FAIL     ran and exited 1, timed out, or was present but wrong
    SKIP     optional check not requested in this invocation
    BLOCKED  cannot run: missing package/input/manifest/app, or exit 2

Exit codes:
    0  every gate PASS
    1  at least one FAIL
    2  no FAIL, but at least one BLOCKED (or all gates not yet passing)
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
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from lunapole import bake  # noqa: E402

RESULTS_PATH = ROOT / "verify" / "results.json"
APP_DIR = ROOT / "app"
DIST_DIR = APP_DIR / "dist"
SITES_FILE = ROOT / "clps" / "sites.json"
ALL_TILES = (
    "ldem_875s_10m.jp2",
    "ldem_85s_20m.jp2",
    "ldem_80s_20m.jp2",
)
GATE_TITLES = {
    "N1": "tiles + decode, ephemeris vs Horizons, P5 computed-Sun panels",
    "N2": "horizon + extended disc, 1-year illumination map",
    "N3": "Earth map, browser/Python parity, verdict < 1 s, reproducible bake",
    "N4": "offline bundle on a phone, bundle matches bake, demo rehearsed",
}
MANUAL_IDS = {"app_panels", "verdict_latency", "demo_rehearsal",
              "offline_phone"}
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


# ---------------------------------------------------------------------------
# check definitions
# ---------------------------------------------------------------------------
def check(gate, cid, title, *, script=None, args=(), packages=(),
          inputs=(), network=False, manual=False, help_text="",
          optional_when=()):
    return {
        "gate": gate,
        "id": cid,
        "title": title,
        "script": script,
        "args": tuple(args),
        "packages": tuple(packages),
        "inputs": tuple(inputs),
        "network": bool(network),
        "manual": bool(manual),
        "help": help_text,
        "optional_when": tuple(optional_when),
    }


CHECKS = [
    check("N1", "dem", "DEM tiles decode + six site elevations/crops",
          script="verify/verify_dem.py", packages=("numpy", "rasterio"),
          inputs=("tiles",),
          help_text="one DEM cropped and decoded as elevation, not ldec_ counts"),
    check("N1", "ephemeris", "SPICE ephemeris sanity (sub-solar sweep etc.)",
          script="verify/verify_ephemeris.py", packages=("spiceypy",),
          inputs=("kernels",),
          help_text="kernel chain loads; sub-solar point behaves"),
    check("N1", "horizons", "sub-solar / sub-Earth vs JPL Horizons < 0.01 deg",
          script="verify/verify_horizons.py", packages=("spiceypy",),
          inputs=("kernels",), network=True,
          help_text="the gate's measured astronomy error, in degrees"),
    check("N1", "app_panels", "P5 panels render a computed Sun", manual=True,
          inputs=("app",),
          help_text="visual check: three panels, Sun computed from artifacts"),

    check("N2", "horizon", "horizon profile, curvature, extended solar disc",
          script="verify/verify_horizon.py", packages=("spiceypy",),
          help_text="max-per-azimuth horizon; curvature table; disc metrics"),
    check("N2", "maps", "map products + 1-year illumination (synthetic)",
          script="verify/verify_maps.py", packages=("spiceypy",),
          help_text="ILLU/ERTH I/O, flat/wall cases, determinism"),

    check("N3", "maps_real", "real terrain Earth parity + 1-month shard",
          script="verify/verify_maps.py", args=("--real",),
          packages=("spiceypy", "rasterio"), inputs=("tiles",),
          optional_when=("no_real",),
          help_text="real-map checks; enable with --real"),
    check("N3", "manifest_unit", "manifest hashes, tamper and staleness contract",
          script="verify/verify_bake.py",
          help_text="synthetic fixture; no data or SPICE required"),
    check("N3", "bake_verify", "manifest, hashes, headers and file set agree",
          script="build/lunapole/bake.py", args=("--verify",),
          inputs=("manifest",),
          help_text="the SHA-256 manifest verifies against disk"),
    check("N3", "bake_check", "rebake in temp, byte-identical artifacts",
          script="build/lunapole/bake.py", args=("--check",),
          packages=("numpy", "spiceypy", "rasterio"),
          inputs=("kernels", "tiles", "crops", "manifest"),
          optional_when=("no_check",),
          help_text="full reproducibility; enable with --check"),
    check("N3", "app_readers", "browser readers agree with the Python bakers",
          script="verify/verify_app_readers.py",
          inputs=("manifest", "terrain"),
          help_text="Node runs app/src/artifacts.js against the baked binaries"),
    check("N3", "earth_map", "1-year Earth-visibility map exists and labels span",
          help_text="reads the ERTH artifact header; no unlabelled partial"),
    check("N3", "verdict_latency", "one-click verdict returns in < 1 s",
          manual=True, inputs=("app",),
          help_text="time the P5 verdict in the demo browser; attest seconds"),

    check("N4", "app_bundle", "app/dist matches the bake (hashes + no strays)",
          script="scripts/build_app.py", args=("--check",),
          inputs=("manifest", "terrain", "app"),
          help_text="bundle index, app-data.json and file set vs the manifest"),
    check("N4", "offline_bundle", "zero-CDN offline bundle",
          help_text="app/dist has no external runtime URL; Three.js vendored"),
    check("N4", "demo_script", "docs/demo-script.md exists and is timed",
          help_text="3-minute script with fallback and honesty lines"),
    check("N4", "readme_honest", "README has limitations/measured/manifest",
          help_text="limitations, measured verification, manifest sections"),
    check("N4", "demo_rehearsal", "3-minute demo rehearsed twice",
          manual=True, inputs=("app",),
          help_text="two clean runs on the demo laptop; attest timings"),
    check("N4", "offline_phone", "demo runs offline on the target phone",
          manual=True, inputs=("app",),
          help_text="airplane mode, no LAN; attest device and result"),
]


# ---------------------------------------------------------------------------
# requirements
# ---------------------------------------------------------------------------
def load_sites():
    return json.loads(SITES_FILE.read_text(encoding="utf-8"))["sites"]


def missing_packages(names):
    return [n for n in names if importlib.util.find_spec(n) is None]


def missing_inputs(kinds, sites):
    missing = []
    if "kernels" in kinds:
        missing.extend(f"data/kernels/{n}" for n in bake.KERNELS
                       if not (ROOT / "data" / "kernels" / n).exists())
    if "tiles" in kinds:
        missing.extend(f"data/dem/{n}" for n in ALL_TILES
                       if not (ROOT / "data" / "dem" / n).exists())
    if "crops" in kinds:
        missing.extend(f"artifacts/dem/{s['id']}.tif" for s in sites
                       if not (ROOT / "artifacts" / "dem"
                               / f"{s['id']}.tif").exists())
    if "manifest" in kinds and not bake.MANIFEST.exists():
        missing.append("artifacts/manifest.json")
    if "app" in kinds and not (DIST_DIR / "index.html").exists():
        missing.append("app/dist/index.html")
    if "terrain" in kinds:
        index = APP_DIR / "data" / "terrain" / "index.json"
        if not index.exists():
            missing.append("app/data/terrain/index.json")
    return missing


# ---------------------------------------------------------------------------
# output parsing
# ---------------------------------------------------------------------------
CHECK_LINE = re.compile(r"^\s*\[(PASS|FAIL|SKIP)\]\s*(.*)$")
INTERESTING = re.compile(
    r"(deg|km\b| m\b|%|worst|median|range|curvature|sha256|MB|hours|lit|dark|"
    r"elev|error|delta|samples?|bytes)",
    re.IGNORECASE,
)


def parse_output(stdout, stderr):
    text = (stdout or "") + "\n" + (stderr or "")
    evidence = []
    for line in text.splitlines():
        m = CHECK_LINE.match(line)
        if m:
            evidence.append(f"[{m.group(1)}] {m.group(2)}".strip())
    tail = [ln.rstrip() for ln in text.splitlines() if ln.strip()][-25:]
    return evidence, tail


def numeric_evidence(evidence, limit=6):
    out = []
    for line in evidence:
        if INTERESTING.search(line) and re.search(r"\d", line):
            out.append(line)
        if len(out) >= limit:
            break
    return out


def classify(returncode, output):
    if returncode == 0:
        return "PASS", ""
    if returncode == 2:
        return "BLOCKED", "verifier returned 2 (missing prerequisite)"
    if re.search(r"ModuleNotFoundError|No module named|ImportError:",
                 output):
        return "BLOCKED", "import failure (missing Python package)"
    return "FAIL", f"exit code {returncode}"


# ---------------------------------------------------------------------------
# internal checks
# ---------------------------------------------------------------------------
def internal_app_panels(args, sites):
    if not (DIST_DIR / "index.html").exists():
        return "BLOCKED", "app/dist/index.html missing — P5 not landed", []
    if args.attest.get("app_panels"):
        return ("PASS", f"attested: {args.attest['app_panels']}",
                [f"[PASS] panels attested: {args.attest['app_panels']}"])
    return ("SKIP", "manual: three panels with a computed Sun",
            ["[SKIP] visual check not automatable; attest with "
             "--attest app_panels=<note>"])


def internal_earth_map(args, sites):
    maps = sorted((ROOT / "artifacts" / "maps").glob("*_erth_*d.bin"))
    if not maps:
        return "BLOCKED", "no artifacts/maps/*_erth_*d.bin — bake the ERTH map", []
    ev = []
    bad = []
    for path in maps:
        logical = "artifacts/" + path.relative_to(ROOT / "artifacts").as_posix()
        rec = bake.describe_artifact(logical, path)
        hdr = rec["header"]
        label = hdr.get("span_label") or "(no label)"
        ev.append(f"[PASS] {path.name}: {hdr.get('samples')} samples, "
                  f"{hdr.get('width')}x{hdr.get('height')} px, "
                  f"span {hdr.get('span_days'):.2f} d; {label}")
        if hdr.get("product") != "ERTH":
            bad.append(f"{path.name}: product {hdr.get('product')!r} != ERTH")
        if not hdr.get("span_label"):
            bad.append(f"{path.name}: no span_label")
    if bad:
        return "FAIL", "; ".join(bad), ev
    return "PASS", f"{len(maps)} Earth map(s) parse; span labels present", ev


def internal_verdict_latency(args, sites):
    if not (DIST_DIR / "index.html").exists():
        return "BLOCKED", "app/dist/index.html missing — cannot time verdict", []
    if args.attest.get("verdict_latency"):
        return ("PASS", f"attested: {args.attest['verdict_latency']}",
                [f"[PASS] verdict latency attested: "
                 f"{args.attest['verdict_latency']}"])
    return ("SKIP", "manual: time the one-click verdict (< 1 s)",
            ["[SKIP] no automated P5 latency harness; attest with "
             "--attest verdict_latency='0.42 s in Chrome'"])


def internal_offline_bundle(args, sites):
    if not (DIST_DIR / "index.html").exists():
        return "BLOCKED", "app/dist/index.html missing — nothing to scan", []
    refs = []
    scanned = 0
    for path in DIST_DIR.rglob("*"):
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        if path.suffix.lower() not in {".html", ".htm", ".js", ".mjs",
                                       ".css", ".json"}:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in EXTERNAL_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            refs.append(f"{path.relative_to(ROOT).as_posix()}:{line}")

    three = []
    for base in (APP_DIR / "node_modules" / "three",
                 APP_DIR / "vendor" / "three", APP_DIR / "vendor",
                 APP_DIR / "public" / "vendor"):
        if base.exists():
            three.extend(base.rglob("three.module*.js"))
    pinned = None
    pkg_path = APP_DIR / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            pinned = (pkg.get("dependencies", {}).get("three")
                      or pkg.get("devDependencies", {}).get("three"))
        except json.JSONDecodeError:
            pinned = None

    ev = [f"[PASS] scanned {scanned} text file(s) in app/dist"]
    if three:
        ev.append(f"[PASS] Three.js source: "
                  f"{three[0].relative_to(ROOT).as_posix()}")
    elif pinned:
        ev.append(f"[PASS] Three.js pinned in app/package.json: {pinned}")
    if refs:
        return ("FAIL", f"{len(refs)} external runtime reference(s); "
                f"first: {refs[0]}", ev + [f"[FAIL] {r}" for r in refs[:10]])
    if not three and not pinned:
        return ("FAIL", "no vendored Three.js source and no pin in package.json",
                ev)
    ev.append("[PASS] no external runtime URL in app/dist")
    return "PASS", "zero-CDN bundle; no external URLs found", ev


def internal_demo_script(args, sites):
    path = ROOT / "docs" / "demo-script.md"
    if not path.exists():
        return "FAIL", "docs/demo-script.md missing", []
    text = path.read_text(encoding="utf-8", errors="replace")
    ev = [f"[PASS] {path.relative_to(ROOT).as_posix()}: "
          f"{len(text.splitlines())} lines"]
    need = {
        "timed 3-minute run": re.search(r"3:00|180\s*s|3\s*min", text, re.I),
        "fallback": re.search(r"fallback|screencast|recording", text, re.I),
        "pre-flight": re.search(r"pre-?flight|before you start", text, re.I),
        "honesty line": re.search(r"honest|limitation|partial|label", text, re.I),
    }
    missing = [name for name, hit in need.items() if not hit]
    if missing:
        return "FAIL", f"demo script missing: {', '.join(missing)}", ev
    ev.append("[PASS] timed run, fallback, pre-flight and honesty line present")
    return "PASS", "script has timing, fallback, pre-flight, honesty", ev


def internal_readme(args, sites):
    path = ROOT / "README.md"
    if not path.exists():
        return "FAIL", "README.md missing", []
    text = path.read_text(encoding="utf-8", errors="replace")
    need = {
        "limitations": re.search(r"(?im)^#{1,3}\s+.*limitation", text),
        "measured verification": re.search(
            r"(?im)^#{1,3}\s+.*(measured|verification)", text),
        "manifest": re.search(r"(?im)^#{1,3}\s+.*manifest", text),
    }
    missing = [name for name, hit in need.items() if not hit]
    ev = [f"[PASS] README.md: {len(text.splitlines())} lines"]
    if missing:
        return "FAIL", f"README missing section(s): {', '.join(missing)}", ev
    ev.append("[PASS] limitations, measured verification, manifest sections")
    return "PASS", "README has the three honest sections", ev


def internal_demo_rehearsal(args, sites):
    if args.attest.get("demo_rehearsal"):
        return ("PASS", f"attested: {args.attest['demo_rehearsal']}",
                [f"[PASS] rehearsal attested: "
                 f"{args.attest['demo_rehearsal']}"])
    return ("SKIP", "manual: two clean 3-minute runs",
            ["[SKIP] attest with --attest demo_rehearsal='2 runs, 2:58 / 3:00'"])


def internal_offline_phone(args, sites):
    if args.attest.get("offline_phone"):
        return ("PASS", f"attested: {args.attest['offline_phone']}",
                [f"[PASS] phone-offline attested: "
                 f"{args.attest['offline_phone']}"])
    return ("SKIP", "manual: airplane-mode run on the target phone",
            ["[SKIP] attest with --attest offline_phone='iPhone 13, "
             "airplane mode, PASS'"])


INTERNAL = {
    "app_panels": internal_app_panels,
    "earth_map": internal_earth_map,
    "verdict_latency": internal_verdict_latency,
    "offline_bundle": internal_offline_bundle,
    "demo_script": internal_demo_script,
    "readme_honest": internal_readme,
    "demo_rehearsal": internal_demo_rehearsal,
    "offline_phone": internal_offline_phone,
}


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------
def run_external(spec, args, sites):
    packages = missing_packages(spec["packages"])
    inputs = missing_inputs(spec["inputs"], sites)
    if packages or inputs:
        bits = []
        if packages:
            bits.append("missing package(s): " + ", ".join(packages))
        if inputs:
            bits.append("missing input(s): " + ", ".join(inputs))
        return {
            "status": "BLOCKED",
            "reason": "; ".join(bits),
            "evidence": [],
            "tail": [],
            "command": " ".join([spec["script"], *spec["args"]]),
            "exit_code": None,
            "duration_s": 0.0,
        }

    argv = [sys.executable, str(ROOT / spec["script"]), *spec["args"]]
    display = " ".join(["python", spec["script"], *spec["args"]])
    env = os.environ.copy()
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONHASHSEED": "0",
        "OMP_NUM_THREADS": str(args.threads),
        "OPENBLAS_NUM_THREADS": str(args.threads),
        "MKL_NUM_THREADS": str(args.threads),
        "NUMEXPR_NUM_THREADS": str(args.threads),
        "VECLIB_MAXIMUM_THREADS": str(args.threads),
    })
    t0 = time.monotonic()
    watchdog = args.timeout if args.timeout > 0 else None
    try:
        proc = subprocess.run(
            argv, cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=watchdog)
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - t0
        out = (exc.stdout or "") + "\n" + (exc.stderr or "")
        evidence, tail = parse_output(
            out if isinstance(out, str) else "", "")
        return {
            "status": "FAIL",
            "reason": f"timeout after {args.timeout:g} s",
            "evidence": evidence,
            "tail": tail[-15:],
            "command": display,
            "exit_code": None,
            "duration_s": round(duration, 2),
        }
    duration = time.monotonic() - t0
    evidence, tail = parse_output(proc.stdout, proc.stderr)
    status, reason = classify(proc.returncode, proc.stdout + proc.stderr)
    return {
        "status": status,
        "reason": reason,
        "evidence": evidence,
        "tail": tail,
        "command": display,
        "exit_code": proc.returncode,
        "duration_s": round(duration, 2),
    }


def run_internal(spec, args, sites):
    t0 = time.monotonic()
    status, reason, evidence = INTERNAL[spec["id"]](args, sites)
    return {
        "status": status,
        "reason": reason,
        "evidence": evidence,
        "tail": evidence,
        "command": f"internal:{spec['id']}",
        "exit_code": None,
        "duration_s": round(time.monotonic() - t0, 3),
    }


def gate_status(records):
    fails = [r for r in records if r["status"] == "FAIL"]
    blocked = [r for r in records if r["status"] == "BLOCKED"]
    open_manual = [r for r in records if r["manual"] and r["status"] == "SKIP"]
    skipped = [r for r in records if r["status"] == "SKIP" and not r["manual"]]
    if fails:
        status = "FAIL"
        reason = "failed: " + ", ".join(r["id"] for r in fails)
    elif blocked:
        status = "BLOCKED"
        reason = "blocked: " + ", ".join(r["id"] for r in blocked)
    elif open_manual:
        status = "BLOCKED"
        reason = "manual attestation outstanding: " + ", ".join(
            r["id"] for r in open_manual)
    elif skipped:
        status = "BLOCKED"
        reason = "not run in this invocation: " + ", ".join(
            r["id"] for r in skipped)
    else:
        status = "PASS"
        reason = "all required checks passed"
    return status, reason


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_attest(values):
    out = {}
    for raw in values or ():
        if "=" not in raw:
            raise SystemExit(f"--attest needs ID=NOTE, got {raw!r}")
        key, note = raw.split("=", 1)
        key = key.strip()
        if key not in MANUAL_IDS:
            raise SystemExit(
                f"--attest {key!r} is not a manual check; manual ids: "
                f"{', '.join(sorted(MANUAL_IDS))}")
        if not note.strip():
            raise SystemExit(f"--attest {key}: note must not be empty")
        out[key] = note.strip()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Run LUNAPOLE verifiers and publish measured gate results")
    ap.add_argument("--real", action="store_true",
                    help="run real-terrain map checks (verify_maps --real)")
    ap.add_argument("--check", action="store_true",
                    help="run bake --verify and bake --check (reproducibility)")
    ap.add_argument("--no-network", action="store_true",
                    help="skip the JPL Horizons network comparison")
    ap.add_argument("--timeout", type=float, default=3600.0,
                    help="per-check wall-clock timeout in seconds; 0 disables "
                         "it (host sleep inflates wall time and can fake a "
                         "timeout on a completed check)")
    ap.add_argument("--threads", type=int, default=1,
                    help="thread count pinned for subprocesses (default 1)")
    ap.add_argument("--attest", action="append", metavar="ID=NOTE",
                    help="attest a manual check (repeatable)")
    ap.add_argument("--only", metavar="ID[,ID]",
                    help="run only these check ids and merge them into an "
                         "existing --results record (does not rebake unless "
                         "bake_check is listed)")
    ap.add_argument("--results", default=str(RESULTS_PATH),
                    help="path for the JSON result record")
    ap.add_argument("--list", action="store_true",
                    help="list checks and exit without running")
    args = ap.parse_args(argv)
    args.attest = parse_attest(args.attest)

    known = {spec["id"] for spec in CHECKS}
    only = []
    if args.only:
        only = [x.strip() for x in args.only.split(",") if x.strip()]
        unknown = [x for x in only if x not in known]
        if unknown:
            ap.error(f"unknown check id(s): {', '.join(unknown)}; "
                     f"known: {', '.join(sorted(known))}")
        if not Path(args.results).exists():
            # Fail closed: a partial run must never write a fresh record that
            # looks like a full gate report.
            print(f"--only needs an existing base record at {args.results}; "
                  f"run the full suite first", file=sys.stderr)
            return 2

    if args.list:
        print("gate  id                 required  title")
        for spec in CHECKS:
            req = "manual" if spec["manual"] else "auto"
            print(f"{spec['gate']}    {spec['id']:<18} {req:<8}  "
                  f"{spec['title']}")
        print("\nManual ids: " + ", ".join(sorted(MANUAL_IDS)))
        return 0

    sites = load_sites()
    started = datetime.now(timezone.utc)
    selected = [s for s in CHECKS if not only or s["id"] in only]
    print("LUNAPOLE verification")
    print(f"  root  {ROOT}")
    print(f"  mode  real={'yes' if args.real else 'no'}  "
          f"check={'yes' if args.check else 'no'}  "
          f"network={'no' if args.no_network else 'yes'}")
    if only:
        print(f"  only  {', '.join(only)}  (merged into {args.results})")
    print()

    records = []
    for spec in selected:
        reason = ""
        optional = ("no_real" in spec["optional_when"] and not args.real) or \
                   ("no_check" in spec["optional_when"] and not args.check) or \
                   (spec["network"] and args.no_network)
        if optional:
            rec = {
                "status": "SKIP",
                "reason": ("not requested (--real)" if "no_real"
                           in spec["optional_when"]
                           else "not requested (--check)" if "no_check"
                           in spec["optional_when"]
                           else "skipped (--no-network)"),
                "evidence": [], "tail": [], "command": "not run",
                "exit_code": None, "duration_s": 0.0,
                "manual": spec["manual"], "attested": False,
            }
        elif spec["id"] in INTERNAL:
            rec = run_internal(spec, args, sites)
            rec["manual"] = spec["manual"]
            rec["attested"] = spec["id"] in args.attest
        else:
            rec = run_external(spec, args, sites)
            rec["manual"] = False
            rec["attested"] = False
        rec.update({
            "id": spec["id"], "gate": spec["gate"],
            "title": spec["title"], "help": spec["help"],
            "run_utc": datetime.now(timezone.utc).replace(microsecond=0)
                               .isoformat().replace("+00:00", "Z"),
        })
        records.append(rec)

        tag = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP",
               "BLOCKED": "BLOCK"}[rec["status"]]
        print(f"{spec['gate']}  [{tag:5}] {spec['id']:<18} "
              f"{rec['reason'] or spec['title']}  ({rec['duration_s']:g}s)")
        for line in numeric_evidence(rec["evidence"]):
            print(f"          {line}")
        if rec["status"] == "FAIL":
            for line in [e for e in rec["evidence"] if e.startswith("[FAIL]")][:10]:
                print(f"          {line}")
            for line in rec["tail"][-12:]:
                print(f"          | {line}")

    # ---- merge a targeted rerun into the existing record ----
    base = None
    if only and Path(args.results).exists():
        try:
            base = json.loads(Path(args.results).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"cannot merge into {args.results}: {exc}", file=sys.stderr)
            return 1
        if base.get("schema") != "lunapole.verify/1":
            print(f"cannot merge: {args.results} has schema "
                  f"{base.get('schema')!r}", file=sys.stderr)
            return 1
        by_id = {r["id"]: r for r in base.get("checks", [])}
        for rec in records:
            by_id[rec["id"]] = rec
        records = [by_id[spec["id"]] for spec in CHECKS
                   if spec["id"] in by_id]

    # ---- gate roll-up ----
    print()
    gates = {}
    for gate, title in GATE_TITLES.items():
        subset = [r for r in records if r["gate"] == gate]
        status, reason = gate_status(subset)
        gates[gate] = {
            "status": status,
            "reason": reason,
            "title": title,
            "checks": [r["id"] for r in subset],
        }
        print(f"{gate}  {status:<7} {reason}")

    counts = {s: sum(1 for r in records if r["status"] == s)
              for s in ("PASS", "FAIL", "SKIP", "BLOCKED")}
    gate_counts = {s: sum(1 for g in gates.values() if g["status"] == s)
                   for s in ("PASS", "FAIL", "BLOCKED")}
    print(f"\nchecks: {counts['PASS']} pass, {counts['FAIL']} fail, "
          f"{counts['BLOCKED']} blocked, {counts['SKIP']} skipped")
    print(f"gates : {gate_counts['PASS']} pass, {gate_counts['FAIL']} fail, "
          f"{gate_counts['BLOCKED']} blocked")

    if gate_counts["FAIL"]:
        overall = "FAIL"
    elif gate_counts["PASS"] == len(GATE_TITLES):
        overall = "PASS"
    else:
        overall = "BLOCKED"
    print(f"\n{overall}")

    stamp = started.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    options = {
        "real": args.real,
        "check": args.check,
        "network": not args.no_network,
        "timeout_s": args.timeout,
        "threads": args.threads,
        "attest": args.attest,
    }
    payload = {
        "schema": "lunapole.verify/1",
        "generated_utc": stamp,
        "root": str(ROOT),
        "options": options,
        "overall": overall,
        "counts": counts,
        "gates": gates,
        "checks": records,
    }
    if base is not None:
        # A targeted rerun must not rewrite history: keep the original run
        # stamp and options, append this rerun as its own record, and let the
        # merged checks/gates/counts above be the current truth.
        merged = dict(base.get("options") or {})
        merged["attest"] = {**(merged.get("attest") or {}), **args.attest}
        payload["generated_utc"] = base.get("generated_utc", stamp)
        payload["options"] = merged
        payload["updated_utc"] = stamp
        reruns = list(base.get("reruns") or [])
        reruns.append({
            "utc": stamp,
            "only": only,
            "options": options,
            "results": {r["id"]: r["status"] for r in records
                        if r["id"] in only},
        })
        payload["reruns"] = reruns
    out = Path(args.results)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"results: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")

    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[overall]


if __name__ == "__main__":
    sys.exit(main())
