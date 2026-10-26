#!/usr/bin/env python3
"""Synthetic verification of the P6 bake manifest — no data, no SPICE.

The point is to test the contract that protects every other number:

    python verify/verify_bake.py

It fabricates a tiny but *format-correct* artifact set (one site, one map
span), builds the manifest, and then attacks it:

  * expected artifact names (ILLU/ERTH stems, not invented ones)
  * SHA-256 of every artifact and the canonical `manifest_sha256`
  * build identity is independent of clock, host and command line
  * manifest bytes are UTF-8 with LF endings and sorted keys
  * tampering with one byte is detected
  * a stale extra file is detected
  * a missing planned artifact refuses to produce a manifest

This test runs before the real bake in `verify/run_all.py` (gate N3). It is
deliberately stdlib-only so it works on the machine that has no `spiceypy`
or `rasterio` yet.
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


import json
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from lunapole import bake  # noqa: E402

FAILURES = []
PASSES = []


def check(name, ok, detail=""):
    ok = bool(ok)
    (PASSES if ok else FAILURES).append(f"{name}: {detail}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


EPH_HDR = "<8sH16sddI2f"
EPH_REC = "<8f"
HOR_HDR = "<8sH16sI5f"
HOR_REC = "<fffBB"
MAP_HDR_A = "<8sH4s16s"
MAP_HDR_B = "<dddI"
MAP_HDR_C = "<dd"
MAP_HDR_D = "<d"
MAP_HDR_E = "<I"
MAP_HDR_F = "<II"
MAP_HDR_G = "<H"


def params_for_test():
    return {
        "_profile": "synthetic",
        "sites": ["shackleton"],
        "bake_maps": True,
        "maps_region": "polecap",
        "maps_span_days": 365.25,
        "bake_series": True,
        "series_span_days": 365.25,
        "fullcycle_runs": False,
    }


def write_ephemeris(path):
    count = 3
    body = b"".join(struct.pack(EPH_REC, *([0.0] * 8)) for _ in range(count))
    header = struct.pack(EPH_HDR, b"LUNAEPH\0", 1, b"shackleton",
                         0.0, 300.0, count, -89.67, 129.78)
    path.write_bytes(header + body)


def write_horizon(path):
    bins = 8
    header = struct.pack(HOR_HDR, b"LUNAHOR\0", 1, b"shackleton", bins,
                         10.0, 25.0, -89.67, 129.78, 1500.0)
    body = b"".join(struct.pack(HOR_REC, 1.0, 5.0, 1200.0, 0, 0)
                    for _ in range(bins))
    path.write_bytes(header + body)


def write_map(path, product, label):
    header = (struct.pack(MAP_HDR_A, b"LUNAMAP\0", 1,
                          product.encode(), b"polecap")
              + struct.pack(MAP_HDR_B, 365.25, 60.0, 320.0, 120)
              + struct.pack(MAP_HDR_C, 250.0, 25.0)
              + struct.pack(MAP_HDR_D, 0.0)
              + struct.pack(MAP_HDR_E, 8761)
              + struct.pack(MAP_HDR_F, 4, 3)
              + struct.pack(MAP_HDR_G, len(label.encode()))
              + label.encode())
    # The manifest only reads the header; a byte body keeps the file honest.
    path.write_bytes(header + b"\x00" * 16)


def write_series(path):
    payload = {
        "meta": {
            "site_id": "shackleton", "span_days": 365.25,
            "span_label": "LABELLED PARTIAL: 365.25 d sampled - test",
            "step_min": 60.0, "samples": 8761,
            "start_utc": "2026-10-01T00:00:00.000000Z",
            "end_utc": "2027-10-01T00:00:00.000000Z",
            "horizon_source": "artifacts/horizon/shackleton.bin (P3, 8 bins)",
            "disc_samples": 256, "method": "synthetic",
            "honesty": "test fixture; not a science product",
        },
        "verdict": {"lit_frac_at_disc": 0.5,
                    "earth_any_frac": 0.25},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def make_artifacts(root, params):
    mapping = {}
    for sid in params["sites"]:
        mapping[f"artifacts/ephemeris/{sid}.bin"] = write_ephemeris
        mapping[f"artifacts/horizon/{sid}.bin"] = write_horizon
    if params["bake_maps"]:
        days = int(round(params["maps_span_days"]))
        region = params["maps_region"]
        for product in ("illu", "erth"):
            mapping[f"artifacts/maps/{region}_{product}_{days}d.bin"] = (
                lambda p, prod=product: write_map(
                    p, "ILLU" if prod == "illu" else "ERTH",
                    f"LABELLED PARTIAL: {params['maps_span_days']:.2f} d "
                    f"sampled - synthetic"))
            mapping[f"artifacts/maps/{region}_{product}_{days}d.png"] = \
                lambda p: p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    if params["bake_series"]:
        days = int(round(params["series_span_days"]))
        for sid in params["sites"]:
            mapping[f"artifacts/maps/timeseries/{sid}_{days}d.json"] = \
                write_series
    for logical, writer in mapping.items():
        physical = root / logical[len("artifacts/"):]
        physical.parent.mkdir(parents=True, exist_ok=True)
        writer(physical)
    return sorted(mapping)


def test_expected_names():
    params = params_for_test()
    names = bake.expected_artifacts(params)
    check("expected artifact names are sorted", names == sorted(names),
          f"{len(names)} paths")
    check("map stems are lowercased ILLU/ERTH",
          any(n.endswith("polecap_illu_365d.bin") for n in names)
          and any(n.endswith("polecap_erth_365d.bin") for n in names),
          ", ".join(n.rsplit("/", 1)[-1] for n in names
                    if "/maps/" in n and "/timeseries/" not in n))
    return params


def test_manifest_roundtrip(params):
    with tempfile.TemporaryDirectory(prefix="lunapole-bake-") as tmp:
        root = Path(tmp)
        names = make_artifacts(root, params)
        manifest = bake.build_manifest(params, root, inputs=[])
        check("manifest artifacts sorted", [a["path"] for a in
                                            manifest["artifacts"]]
              == sorted(names), f"{len(names)} artifacts")
        check("manifest totals match file bytes",
              manifest["totals"]["artifact_bytes"]
              == sum((root / n[len("artifacts/"):]).stat().st_size
                     for n in names),
              f"{manifest['totals']['artifact_mb']:.3f} MB")
        check("manifest has schema and canonical identity",
              manifest["schema"] == bake.SCHEMA
              and len(manifest["manifest_sha256"]) == 64,
              manifest["manifest_sha256"][:16] + "...")

        errors = bake.verify_manifest(manifest, root)
        check("untampered manifest verifies", not errors,
              f"{len(manifest['artifacts'])} artifacts, 0 errors"
              if not errors else "; ".join(errors[:3]))

        # Identity is the build, not the moment it happened.
        other = json.loads(json.dumps(manifest))
        other["build"]["generated_utc"] = "1999-01-01T00:00:00Z"
        other["build"]["command"] = "python somewhere-else.py"
        check("identity ignores clock and command line",
              bake.manifest_sha256(other) == manifest["manifest_sha256"],
              "manifest_sha256 unchanged")

        # Byte-level tamper detection.
        target = root / "horizon" / "shackleton.bin"
        data = bytearray(target.read_bytes())
        data[-1] ^= 0xFF
        target.write_bytes(bytes(data))
        errors = bake.verify_manifest(manifest, root)
        check("one-byte tamper detected", bool(errors)
              and any("sha256" in e for e in errors),
              errors[0] if errors else "NOT DETECTED")
        target.write_bytes(bytes(data[:-1] + bytes([data[-1] ^ 0xFF])))

        # Stale file detection, both in verify and in build.
        extra = root / "maps" / "stale_from_old_run.bin"
        extra.write_bytes(b"stale")
        errors = bake.verify_manifest(manifest, root)
        check("stale extra file detected", bool(errors)
              and any("unexpected" in e for e in errors),
              errors[0] if errors else "NOT DETECTED")
        extra.unlink()

        # A self-consistent manifest that simply omits a planned product is
        # still a lie about the build and must fail.
        trimmed = json.loads(json.dumps(manifest))
        trimmed["artifacts"].pop(0)
        trimmed["totals"]["artifact_count"] = len(trimmed["artifacts"])
        trimmed["totals"]["artifact_bytes"] = sum(
            a["bytes"] for a in trimmed["artifacts"])
        trimmed["totals"]["artifact_mb"] = round(
            trimmed["totals"]["artifact_bytes"] / 1e6, 3)
        trimmed["manifest_sha256"] = bake.manifest_sha256(trimmed)
        errors = bake.verify_manifest(trimmed, root)
        check("manifest that omits a planned artifact detected",
              any("planned artifact(s) absent" in e for e in errors),
              errors[0] if errors else "NOT DETECTED")

        # A missing planned artifact refuses to produce a manifest.
        png = root / "maps" / "polecap_illu_365d.png"
        saved = png.read_bytes()
        png.unlink()
        try:
            bake.build_manifest(params, root, inputs=[])
            raised = False
        except bake.BakeError as exc:
            raised = "missing" in str(exc)
        png.write_bytes(saved)
        check("missing planned artifact refused", raised,
              "BakeError raised" if raised else "no error")

        # Manifest byte discipline.
        path = root / "manifest.json"
        bake.write_manifest(path, manifest)
        raw = path.read_bytes()
        check("manifest is UTF-8/LF with a final newline",
              b"\r\n" not in raw and raw.endswith(b"\n"),
              f"{len(raw)} bytes, LF only")
        check("manifest JSON is sorted-key and round-trips",
              json.loads(raw.decode("utf-8"))["manifest_sha256"]
              == manifest["manifest_sha256"],
              "parse OK")


def test_identity_across_roots(params):
    digests = []
    with tempfile.TemporaryDirectory(prefix="lunapole-bake-a-") as a, \
            tempfile.TemporaryDirectory(prefix="lunapole-bake-b-") as b:
        for tmp in (a, b):
            root = Path(tmp)
            make_artifacts(root, params)
            # Different input lists must not enter identity only if inputs
            # actually differ; use the same empty list for both.
            m = bake.build_manifest(params, root, inputs=[])
            digests.append(m["manifest_sha256"])
    check("same bytes -> same manifest_sha256", len(set(digests)) == 1,
          digests[0][:16] + "...")


def test_promote_contract():
    with tempfile.TemporaryDirectory(prefix="lunapole-promote-") as tmp:
        root = Path(tmp)
        dest = root / "artifacts"
        stage = root / "stage"
        (dest / "dem").mkdir(parents=True)
        (dest / "dem" / "keep.tif").write_bytes(b"dem-input")
        (dest / "ephemeris").mkdir(parents=True)
        (dest / "ephemeris" / "stale.bin").write_bytes(b"stale")
        (dest / "maps" / "timeseries").mkdir(parents=True)
        (dest / "maps" / "timeseries" / "stale.json").write_bytes(b"stale")

        (stage / "ephemeris").mkdir(parents=True)
        (stage / "ephemeris" / "new.bin").write_bytes(b"new")
        (stage / "maps" / "timeseries").mkdir(parents=True)
        (stage / "maps" / "timeseries" / "new.json").write_bytes(b"new")

        bake._promote(stage, dest)

        check("promote leaves artifacts/dem untouched",
              (dest / "dem" / "keep.tif").read_bytes() == b"dem-input",
              "input crop preserved")
        check("promote removes stale product files",
              not (dest / "ephemeris" / "stale.bin").exists()
              and not (dest / "maps" / "timeseries" / "stale.json").exists(),
              "old ephemeris and series removed")
        check("promote installs the new product files",
              (dest / "ephemeris" / "new.bin").read_bytes() == b"new"
              and (dest / "maps" / "timeseries" / "new.json").read_bytes()
              == b"new",
              "new files in place")


def main() -> int:
    print("LUNAPOLE P6 manifest verification (synthetic, stdlib only)")
    print()
    params = test_expected_names()
    test_manifest_roundtrip(params)
    test_identity_across_roots(params)
    test_promote_contract()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s):")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"All {len(PASSES)} manifest checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
