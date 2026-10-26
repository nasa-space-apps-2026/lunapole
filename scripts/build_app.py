#!/usr/bin/env python3
"""Assemble the offline LUNAPOLE app bundle in app/dist/.

There is no Node build step on purpose: the app is plain ES modules, and this
script copies exactly what the browser needs. That makes the offline bundle
auditable with `rg` and reproducible with a hash, and it means a demo laptop
does not need npm.

    python scripts/build_app.py              # build app/dist
    python scripts/build_app.py --check      # dist matches sources, no writes
    python scripts/build_app.py --serve      # build, then serve on :8000

Fail-closed rules:
  * no artifacts/manifest.json -> exit 2 (bake first);
  * any planned site missing its horizon / series / terrain -> exit 2;
  * a map .bin whose header cannot be parsed -> exit 1 (corrupt artifact);
  * an expected PNG missing -> exit 2.
Nothing is silently skipped: the bundle either matches the manifest or the
build stops.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 console (degree glyphs, arrows). See _bootstrap.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402

_bootstrap.utf8_streams()

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
DIST = APP / "dist"
ARTIFACTS = ROOT / "artifacts"
DATA = ROOT / "data"
SITES_FILE = ROOT / "clps" / "sites.json"
MANIFEST = ARTIFACTS / "manifest.json"

MAP_MAGIC = b"LUNAMAP\0"
MAP_HDR = "<8sH4s16s"          # magic, version, product, region
MAP_HDR2 = "<dddI"             # span_days, step_min, grid_m, az_bins
MAP_HDR3 = "<dd"               # step_m, max_dist_km
MAP_HDR4 = "<dI"               # start_et, samples
MAP_HDR5 = "<II"               # width, height
MAP_HDR6 = "<H"                # label length
# Regions are pole-centred: maps.REGIONS.*.center_xy == (0, 0) for both.
REGION_CENTRE = {"polecap": (0.0, 0.0), "widecap": (0.0, 0.0)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_map_header(path: Path) -> dict:
    data = path.read_bytes()
    off = 0
    magic, ver, product, region = struct.unpack_from(MAP_HDR, data, off)
    off += struct.calcsize(MAP_HDR)
    if magic != MAP_MAGIC:
        raise ValueError(f"{path.name}: bad magic {magic!r}")
    if ver != 1:
        raise ValueError(f"{path.name}: unsupported version {ver}")
    span_days, step_min, grid_m, az_bins = struct.unpack_from(MAP_HDR2, data, off)
    off += struct.calcsize(MAP_HDR2)
    _step_m, _max_dist = struct.unpack_from(MAP_HDR3, data, off)
    off += struct.calcsize(MAP_HDR3)
    _start_et, samples = struct.unpack_from(MAP_HDR4, data, off)
    off += struct.calcsize(MAP_HDR4)
    width, height = struct.unpack_from(MAP_HDR5, data, off)
    off += struct.calcsize(MAP_HDR5)
    (llen,) = struct.unpack_from(MAP_HDR6, data, off)
    off += struct.calcsize(MAP_HDR6)
    label = data[off:off + llen].decode("utf-8")
    return {
        "product": product.decode().rstrip("\0"),
        "region": region.decode().rstrip("\0"),
        "span_days": span_days,
        "step_min": step_min,
        "grid_m": grid_m,
        "az_bins": int(az_bins),
        "samples": int(samples),
        "width": int(width),
        "height": int(height),
        "span_label": label,
    }


def read_terrain_index() -> dict:
    path = APP / "data" / "terrain" / "index.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {rec["site_id"]: rec for rec in payload.get("sites", [])}


def plan_bundle() -> dict:
    """Work out the file set and the app-data manifest, without copying."""
    problems: list[tuple[str, str]] = []
    if not MANIFEST.is_file():
        raise SystemExit("BLOCKED: artifacts/manifest.json missing - run "
                         "python build/lunapole/bake.py --profile demo")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sites = json.loads(SITES_FILE.read_text(encoding="utf-8"))["sites"]
    terrain_index = read_terrain_index()
    if not terrain_index:
        problems.append(("skip", "no app/data/terrain/index.json - run "
                                 "python scripts/export_terrain.py"))

    # The bundle contains exactly the sites the bake produced. `demo` bakes
    # four of the six catalogue sites; iterating sites.json here would report
    # the other two as missing artifacts and block a perfectly good build.
    baked_sites = set()
    series_by_site = {}
    for rec in manifest.get("artifacts", []):
        logical = rec.get("path", "")
        if logical.startswith("artifacts/horizon/") and logical.endswith(".bin"):
            baked_sites.add(Path(logical).stem)
        elif "/maps/timeseries/" in logical and logical.endswith(".json"):
            name = Path(logical).name
            for site in sites:
                if name.startswith(site["id"] + "_"):
                    series_by_site[site["id"]] = logical
    if not baked_sites:
        problems.append(("blocked", "manifest lists no artifacts/horizon/*.bin"))

    site_records = []
    for site in sites:
        sid = site["id"]
        if sid not in baked_sites:
            continue
        horizon = ROOT / f"artifacts/horizon/{sid}.bin"
        series_logical = series_by_site.get(sid)
        series = ROOT / series_logical if series_logical else None
        terr = terrain_index.get(sid)
        terr_path = APP / "data" / "terrain" / f"{sid}.bin"
        if not horizon.is_file():
            problems.append(("blocked", f"{horizon.relative_to(ROOT)} missing"))
        if series is None or not series.is_file():
            problems.append(("blocked", f"artifacts/maps/timeseries/{sid}_*d.json missing"))
        if terr is None or not terr_path.is_file():
            problems.append(("blocked", f"{terr_path.relative_to(ROOT)} missing"))
        if horizon.is_file() and series and series.is_file() and terr and terr_path.is_file():
            site_records.append({
                "id": sid,
                "name": site["name"],
                "lat": site["lat"],
                "lon": site["lon"],
                "horizon": f"artifacts/horizon/{sid}.bin",
                "series": f"artifacts/maps/timeseries/{series.name}",
                "terrain": f"data/terrain/{sid}.bin",
                "terrain_n": terr["n"],
                "terrain_grid_m": terr["grid_m"],
            })

    maps = []
    for bin_path in sorted((ARTIFACTS / "maps").glob("*_*d.bin")):
        png = bin_path.with_suffix(".png")
        if not png.is_file():
            problems.append(("blocked", f"{png.relative_to(ROOT)} missing"))
            continue
        hdr = read_map_header(bin_path)
        maps.append({
            "product": hdr["product"],
            "bin": f"artifacts/maps/{bin_path.name}",
            "png": f"artifacts/maps/{png.name}",
            "span_label": hdr["span_label"],
            "span_days": hdr["span_days"],
            "step_min": hdr["step_min"],
            "grid_m": hdr["grid_m"],
            "az_bins": hdr["az_bins"],
            "width": hdr["width"],
            "height": hdr["height"],
            "center": list(REGION_CENTRE.get(hdr["region"], (0.0, 0.0))),
        })
    if not maps:
        problems.append(("blocked", "artifacts/maps/*_*d.bin missing"))

    copies: list[tuple[Path, Path]] = []

    def add_dir(src: Path, dst: Path, pattern: str = "*", recursive=False):
        if not src.is_dir():
            return
        it = src.rglob(pattern) if recursive else src.glob(pattern)
        for item in sorted(it):
            if item.is_file():
                copies.append((item, dst / item.relative_to(src)))

    for name in ("index.html", "styles.css", "package.json"):
        src = APP / name
        if src.is_file():
            copies.append((src, DIST / name))
        elif name == "index.html":
            problems.append(("blocked", "app/index.html missing"))
    add_dir(APP / "src", DIST / "src", recursive=True)
    add_dir(APP / "vendor", DIST / "vendor", recursive=True)
    for rec in site_records:
        copies.append((APP / rec["terrain"], DIST / rec["terrain"]))
        copies.append((ARTIFACTS / "horizon" / f"{rec['id']}.bin",
                       DIST / "artifacts" / "horizon" / f"{rec['id']}.bin"))
        copies.append((ROOT / rec["series"], DIST / rec["series"]))
    for m in maps:
        copies.append((ROOT / m["png"], DIST / m["png"]))
    copies.append((MANIFEST, DIST / "manifest.json"))

    app_data = {
        "build": {
            "manifest_sha256": manifest.get("manifest_sha256"),
            "profile": manifest.get("build", {}).get("profile"),
            "artifacts": len(manifest.get("artifacts", [])),
            "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_manifest": "manifest.json",
        },
        "sites": site_records,
        "maps": maps,
        "notes": [
            "Every datum is a file in this bundle; there is no network access.",
            "span_label is reproduced verbatim from the map header.",
            "The verdict uses the 720-bin per-site horizon, not the map pixels.",
        ],
    }
    return {"problems": problems, "copies": copies, "app_data": app_data,
            "manifest": manifest}


def write_bundle(plan: dict) -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    for src, dst in plan["copies"]:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    payload = json.dumps(plan["app_data"], indent=2, sort_keys=True) + "\n"
    (DIST / "app-data.json").write_text(payload, encoding="utf-8")

    files = sorted(p for p in DIST.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in files)
    lines = [
        "LUNAPOLE offline bundle",
        f"files: {len(files)}",
        f"bytes: {total}",
        f"manifest_sha256: {plan['app_data']['build']['manifest_sha256']}",
        "",
        "Serve this directory over HTTP (python -m http.server 8000 --directory app/dist).",
        "Everything the app loads is relative and inside this directory.",
        "",
    ]
    lines += [f"{sha256(p)}  {p.relative_to(DIST).as_posix()}" for p in files]
    (DIST / "BUILD.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(files)} file(s), {total / 1e6:.2f} MB -> {DIST}")
    print(f"manifest_sha256 {plan['app_data']['build']['manifest_sha256']}")


def check_bundle(plan: dict) -> int:
    if not (DIST / "index.html").is_file():
        print("BLOCKED: app/dist/index.html missing", file=sys.stderr)
        return 2
    bad = 0
    for src, dst in plan["copies"]:
        if not dst.is_file():
            print(f"  [MISS] {dst.relative_to(DIST).as_posix()}")
            bad += 1
        elif sha256(src) != sha256(dst):
            print(f"  [DIFF] {dst.relative_to(DIST).as_posix()}")
            bad += 1

    # Compare the metadata itself, minus the build clock, and fail on strays.
    want = dict(plan["app_data"])
    want_build = dict(want.get("build") or {})
    want_build.pop("built_utc", None)
    want["build"] = want_build
    data_path = DIST / "app-data.json"
    if not data_path.is_file():
        print("  [MISS] app-data.json")
        bad += 1
    else:
        got = json.loads(data_path.read_text(encoding="utf-8"))
        got_build = dict(got.get("build") or {})
        got_build.pop("built_utc", None)
        got["build"] = got_build
        if got != want:
            print("  [DIFF] app-data.json (excluding build timestamp)")
            bad += 1

    expected = {dst.relative_to(DIST).as_posix() for _src, dst in plan["copies"]}
    expected |= {"app-data.json", "BUILD.txt"}
    strays = sorted(p.relative_to(DIST).as_posix() for p in DIST.rglob("*")
                    if p.is_file() and p.relative_to(DIST).as_posix() not in expected)
    for rel in strays:
        print(f"  [STRAY] {rel}")
        bad += 1
    print(f"dist check: {len(plan['copies'])} file(s), {bad} mismatch(es)")
    return 0 if bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify dist, do not write")
    ap.add_argument("--serve", action="store_true", help="build, then serve on :8000")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; 0.0.0.0 exposes the bundle to a phone "
                         "on the same hotspot (no internet needed)")
    args = ap.parse_args()

    try:
        plan = plan_bundle()
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    blocking = [msg for level, msg in plan["problems"] if level == "blocked"]
    for level, msg in plan["problems"]:
        print(f"  [{'BLOCKED' if level == 'blocked' else 'WARN'}] {msg}")
    if blocking:
        print(f"\nBLOCKED: {len(blocking)} required file(s) missing. Nothing written.",
              file=sys.stderr)
        return 2

    if args.check:
        return check_bundle(plan)

    write_bundle(plan)
    if args.serve:
        import http.server  # noqa: PLC0415
        import functools  # noqa: PLC0415

        class Handler(http.server.SimpleHTTPRequestHandler):
            """Static handler that forbids caching.

            A demo laptop that rebuilds `app/dist` and reloads must not see a
            stale ES module from the browser cache. `no-store` costs nothing on
            localhost and makes "did the rebuild take effect?" unambiguous.
            """

            def end_headers(self):
                self.send_header("Cache-Control", "no-store, max-age=0")
                super().end_headers()

        handler = functools.partial(Handler, directory=str(DIST))
        if args.host in ("0.0.0.0", "::"):
            # The phone test needs an origin the phone can reach. Print the
            # laptop's LAN address so nobody has to guess; this is a local
            # hotspot address, never a public one.
            import socket  # noqa: PLC0415
            try:
                lan = socket.gethostbyname(socket.gethostname())
            except OSError:
                lan = "<laptop-LAN-IP>"
            print(f"serving {DIST} on http://{lan}:{args.port} "
                  f"(bound to {args.host}; same hotspot only, no-store)")
        else:
            print(f"serving {DIST} on http://localhost:{args.port} "
                  f"(Ctrl-C to stop, no-store)")
        http.server.ThreadingHTTPServer((args.host, args.port), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
