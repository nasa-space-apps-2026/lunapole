#!/usr/bin/env python3
"""Build the static, no-JavaScript fallback page from the promoted bake.

Why: docs/demo-script.md promises a fallback if the app or the demo laptop
dies. Copying the folder and opening index.html is not possible (the app needs
an HTTP origin), so this script bakes a plain HTML page instead: same PNG maps,
same verbatim span labels, same per-site numbers, read straight from
artifacts/. A static page cannot disagree with the artifact set, and it opens
from file:// with no server, no JavaScript and no network.

Usage:
    python scripts/make_fallback.py            # write docs/fallback/
    python scripts/make_fallback.py --check    # verify it matches the bake

Exit codes: 0 ok, 2 no bake (run bake.py first), 1 mismatch in --check.
"""

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import _bootstrap  # noqa: E402

_bootstrap.utf8_streams()

from build.lunapole import maps  # noqa: E402

ARTIFACTS = ROOT / "artifacts"
MANIFEST = ARTIFACTS / "manifest.json"
OUT_DIR = ROOT / "docs" / "fallback"
PRODUCT_TITLE = {"ILLU": "Sun illumination", "ERTH": "Earth visibility"}


def _load_manifest():
    if not MANIFEST.exists():
        raise SystemExit("no artifacts/manifest.json - run "
                         "python build/lunapole/bake.py --profile demo")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _verdict_row(entry):
    path = ROOT / entry["path"]
    series = json.loads(path.read_text(encoding="utf-8"))
    meta = series["meta"]
    v = series["verdict"]
    disc = series["rows"]["earth_disc_frac"]
    full_at = 1.0 - 0.5 / float(meta.get("disc_samples") or 256)
    full = sum(1 for x in disc if x >= full_at) / len(disc) if disc else 0.0
    return {
        "id": meta["site_id"],
        "name": meta.get("site_name") or meta["site_id"],
        "span_label": meta["span_label"],
        "lit_pct": 100.0 * v["lit_frac_at_disc"],
        "dark_h": v["longest_dark_h"],
        "earth_any_pct": 100.0 * v["earth_any_frac"],
        "earth_full_pct": 100.0 * full,
    }


def render():
    """Return {relative path: bytes} for the whole fallback page."""
    man = _load_manifest()
    build = man["build"]
    files = {}

    maps_by_product = {}
    for entry in man["artifacts"]:
        if entry["kind"] != "map":
            continue
        path = ROOT / entry["path"]
        parsed = maps.read_map(path)
        png = path.with_suffix(".png")
        if not png.exists():
            raise SystemExit(f"map PNG missing for {entry['path']}: {png}")
        name = f"map_{str(parsed['product']).lower()}.png"
        files[name] = png.read_bytes()
        maps_by_product[parsed["product"]] = {
            "bin": entry["path"],
            "png": name,
            "parsed": parsed,
            "sha256": entry["sha256"],
        }

    rows = [_verdict_row(e) for e in man["artifacts"]
            if e["kind"] == "timeseries"]
    rows.sort(key=lambda r: r["name"].lower())

    figures = []
    for product in ("ILLU", "ERTH"):
        m = maps_by_product.get(product)
        if not m:
            continue
        p = m["parsed"]
        figures.append(f"""
    <figure>
      <img src="{html.escape(m['png'])}" width="462" height="462"
           alt="{html.escape(PRODUCT_TITLE[product])} pole-cap map">
      <figcaption>
        <strong>{html.escape(PRODUCT_TITLE[product])}</strong> -
        {p['width']}&times;{p['height']} px, {p['grid_m']:.0f} m/px,
        {p['az_bins']} azimuth bins, {p['step_min']:g} min step,
        {p['samples']} samples, {p['width'] * p['grid_m'] / 1000:.0f} km cap.
        <span class="label">{html.escape(p['span_label'])}</span>
      </figcaption>
    </figure>""")

    table = []
    for r in rows:
        table.append(
            "<tr>"
            f"<td>{html.escape(r['name'])}</td>"
            f"<td class=\"num\">{r['lit_pct']:.1f} %</td>"
            f"<td class=\"num\">{r['dark_h']:.0f} h</td>"
            f"<td class=\"num\">{r['earth_any_pct']:.1f} %</td>"
            f"<td class=\"num\">{r['earth_full_pct']:.1f} %</td>"
            "</tr>")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LUNAPOLE - static fallback (manifest {html.escape(man['manifest_sha256'][:12])})</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; padding: 24px; background: #0b0e13; color: #e6e9ef;
         font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 17px; margin: 26px 0 10px; }}
  .banner {{ border-left: 4px solid #ffd166; background: #1a1d24;
             padding: 10px 14px; margin: 14px 0 20px; }}
  .meta {{ color: #9aa4b2; font-size: 13px; }}
  .meta code {{ color: #cfe3ff; }}
  .maps {{ display: flex; flex-wrap: wrap; gap: 22px; }}
  figure {{ margin: 0; max-width: 462px; }}
  img {{ width: 100%; height: auto; image-rendering: pixelated;
        border: 1px solid #2b3038; }}
  figcaption {{ font-size: 12.5px; color: #b7c0cc; margin-top: 6px; }}
  .label {{ display: block; margin-top: 6px; color: #ffd166; }}
  table {{ border-collapse: collapse; margin-top: 6px; }}
  th, td {{ padding: 5px 12px 5px 0; text-align: left;
           border-bottom: 1px solid #232830; }}
  th {{ color: #9aa4b2; font-weight: 600; }}
  td.num {{ font-variant-numeric: tabular-nums; text-align: right; }}
  footer {{ margin-top: 26px; color: #8d97a5; font-size: 12.5px; }}
</style>
</head>
<body>
<h1>LUNAPOLE static fallback</h1>
<p class="meta">Baked profile <code>{html.escape(str(build.get('profile')))}</code>,
generated <code>{html.escape(str(build.get('generated_utc')))}</code>,
manifest <code>{html.escape(man['manifest_sha256'][:12])}</code>
({man['totals']['artifact_count']} artifacts, {man['totals']['artifact_mb']:.2f} MB).</p>

<div class="banner">
  <strong>This is the fallback page.</strong> It is generated from the same
  promoted bake as the app, but it is plain HTML with no JavaScript and no
  network access. If you are reading this, say that the live app is unavailable
  and keep going - do not describe this page as an interactive demo.
</div>

<h2>Baked pole-cap maps</h2>
<div class="maps">{''.join(figures)}
</div>
<p class="note">Grey = outside the measured DEM. Deep blue = zero sunlight
across the whole labelled span (Sun map) or no limb at any sample (Earth map).
The app draws site markers; this page does not. Nobile and Haworth lie outside
the 148 km cap, so their verdicts come from their own 720-bin horizons.</p>

<h2>Per-site verdicts (1-year labelled span, IAU feature centres)</h2>
<table>
  <thead><tr><th>Site</th><th class="num">Sun lit</th>
  <th class="num">Longest dark</th><th class="num">Earth any limb</th>
  <th class="num">Earth full disc</th></tr></thead>
  <tbody>{''.join(table)}</tbody>
</table>
<p class="note">{html.escape(rows[0]['span_label'] if rows else '')}</p>
<p class="note">Each row is measured at the IAU Gazetteer feature <em>centre</em>,
not at a landing site and not at the rim peak that published illumination
figures usually describe. On this DEM the Shackleton centre sits about 1.5 km up
the crater's inner slope, with terrain 7 km lower within 10 km.</p>

<footer>
  Generated by <code>scripts/make_fallback.py</code> from
  <code>artifacts/manifest.json</code> and the artifacts it lists. Do not edit
  this page by hand; re-run the script after a new bake. Numbers are fractions
  of the labelled span, not promises beyond it.
</footer>
</body>
</html>
"""
    files["index.html"] = page.encode("utf-8")
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="compare docs/fallback with a fresh render; no writes")
    args = ap.parse_args(argv)

    files = render()

    if args.check:
        bad = []
        for name, want in sorted(files.items()):
            path = OUT_DIR / name
            if not path.exists():
                bad.append(f"missing {path.relative_to(ROOT)}")
            elif path.read_bytes() != want:
                bad.append(f"stale {path.relative_to(ROOT)}")
        extra = sorted(
            p.name for p in OUT_DIR.glob("*")
            if p.is_file() and p.name not in files) if OUT_DIR.exists() else []
        for name in extra:
            bad.append(f"stray docs/fallback/{name}")
        if bad:
            print("fallback check: FAIL")
            for line in bad:
                print(f"  {line}")
            return 1
        print(f"fallback check: PASS ({len(files)} files match the bake)")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*"):
        if stale.is_file() and stale.name not in files:
            stale.unlink()
    for name, data in files.items():
        (OUT_DIR / name).write_bytes(data)
    print(f"fallback page: {OUT_DIR.relative_to(ROOT)} ({len(files)} files)")
    print(f"  open: {OUT_DIR / 'index.html'}")
    print("  check: python scripts/make_fallback.py --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
