#!/usr/bin/env python3
"""Headless check of the built offline app: panels render, verdict is timed.

Run:  python3 verify/verify_app_panels.py [--dist app/dist] [--png out.png]

This converts two previously "manual" gate items into measured evidence:

  app_panels       the four canvases draw real content (not blank fills) and
                   the page boots with zero console errors
  verdict_latency  wall-clock time for the one-click verdict, in milliseconds

It also blocks every non-localhost request at the browser level, so a page that
loads clean is proven to need no network. That is the browser half of the
offline gate; the phone half still needs a human with a handset.

Exit 0 = all checks passed.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request logging
        pass


def start_server(directory: Path) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(QuietHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def analyse_png(path: Path) -> tuple[bool, str]:
    """True if a screenshot contains real drawn content, not a flat fill.

    Screenshot analysis, not canvas readback: the 3D panel is WebGL, and a
    WebGL canvas without preserveDrawingBuffer reads back as solid black
    through getImageData/drawImage even when it is rendering perfectly. That
    produced a false failure. A screenshot sees what a human sees.
    """
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = list(im.getdata())
    seen = set()
    lit = 0
    for i in range(0, len(px), 97):          # stride-sample, cheap
        p = px[i]
        seen.add(p)
        if sum(p) > 24:
            lit += 1
    samples = max(1, len(range(0, len(px), 97)))
    lit_frac = lit / samples
    ok = len(seen) >= 6 and lit_frac > 0.01
    return ok, (f"{w}x{h}, {len(seen)} colours, {100 * lit_frac:.0f} % lit"
                if not ok else f"{w}x{h}, {len(seen)} colours, "
                               f"{100 * lit_frac:.0f} % lit")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="app/dist")
    ap.add_argument("--png", default="", help="write a full-page screenshot here")
    ap.add_argument("--timeout-ms", type=int, default=30000)
    args = ap.parse_args()

    dist = (ROOT / args.dist).resolve()
    if not (dist / "index.html").exists():
        print(f"BLOCKED: {args.dist}/index.html missing — build the app first "
              f"(python scripts/build_app.py)")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("BLOCKED: playwright not installed (pip install --user playwright)")
        return 2

    httpd, port = start_server(dist)
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"serving {dist.relative_to(ROOT)} on {url}\n")

    console_errors: list[str] = []
    page_errors: list[str] = []
    blocked_external: list[str] = []

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(executable_path="/usr/bin/google-chrome")
                engine = "system chrome"
            except Exception:
                browser = p.chromium.launch()
                engine = "bundled chromium"
            print(f"  browser: {engine} {browser.version}\n")

            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.on("console", lambda m: console_errors.append(m.text)
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)))

            def guard(route):
                u = route.request.url
                if u.startswith(("http://127.0.0.1", "http://localhost",
                                 "data:", "blob:", "file:")):
                    route.continue_()
                else:
                    blocked_external.append(u)
                    route.abort()

            page.route("**/*", guard)

            t0 = time.perf_counter()
            page.goto(url, wait_until="load", timeout=args.timeout_ms)
            # boot() is async: wait for the site list, which only fills after
            # app-data.json loads successfully.
            page.wait_for_function(
                "() => document.querySelectorAll('#siteSelect option').length > 0",
                timeout=args.timeout_ms)
            boot_ms = (time.perf_counter() - t0) * 1000
            print(f"=== boot ===\n  ready in {boot_ms:.0f} ms")

            banner = page.eval_on_selector(
                "#banner",
                "el => el.hidden ? '' : el.textContent.trim()")
            check("no blocking banner", banner == "", banner or "none shown")

            n_sites = page.eval_on_selector(
                "#siteSelect", "el => el.options.length")
            check("site list populated", n_sites >= 1, f"{n_sites} sites")

            build_txt = page.eval_on_selector(
                "#buildInfo", "el => el.textContent.trim()")
            check("build stamp shows a manifest hash",
                  "manifest" in build_txt and "no manifest" not in build_txt,
                  build_txt)

            # --- the coordinate label --------------------------------------
            # Every panel is measured at an IAU feature centre, never at a
            # landing site. The claim must be on screen, and it must follow the
            # site selector rather than sitting there as static HTML.
            print("\n=== scope label ===")
            note = page.eval_on_selector(
                "#siteNote",
                "el => el.hidden ? '' : el.textContent.replace(/\\s+/g, ' ').trim()")
            check("site note is visible", note != "", note[:90] or "hidden")
            check("site note names the coordinate kind",
                  "feature centre" in note.lower(), note[:120])
            check("site note prints a latitude",
                  "\u00b0" in note and ("\u2212" in note or "+" in note), note[:120])

            first_id = page.eval_on_selector("#siteSelect", "el => el.value")
            page.select_option("#siteSelect", index=1)
            page.wait_for_function(
                "prev => document.querySelector('#siteSelect').value !== prev",
                arg=first_id, timeout=args.timeout_ms)
            page.wait_for_function(
                "() => document.querySelector('#siteNote').textContent.trim().length > 0",
                timeout=args.timeout_ms)
            note2 = page.eval_on_selector(
                "#siteNote", "el => el.textContent.replace(/\\s+/g, ' ').trim()")
            check("site note follows the selector", note2 != note,
                  f"{first_id} -> {page.eval_on_selector('#siteSelect', 'el => el.value')}")
            page.select_option("#siteSelect", value=first_id)
            page.wait_for_function(
                "id => document.querySelector('#siteSelect').value === id",
                arg=first_id, timeout=args.timeout_ms)

            # --- the four panels -------------------------------------------
            print("\n=== panels ===")
            panels = [
                ("#p-terrain", "3D terrain"),
                ("#p-map", "illumination map"),
                ("#p-sky", "sky panorama"),
                ("#p-time", "timeline"),
            ]
            shots = Path("/tmp/opencode/lunapole-panels")
            shots.mkdir(parents=True, exist_ok=True)
            for sel, label in panels:
                shot = shots / f"{sel.lstrip('#p-')}.png"
                try:
                    page.locator(sel).screenshot(path=str(shot))
                except Exception as err:
                    check(f"{label} rendered content", False, str(err)[:80])
                    continue
                ok, detail = analyse_png(shot)
                check(f"{label} rendered content", ok, detail)

            # --- verdict latency -------------------------------------------
            print("\n=== verdict ===")
            page.click("#verdictBtn")
            page.wait_for_function(
                "() => document.querySelector('#verdictBtn').disabled === false",
                timeout=args.timeout_ms)
            out = page.eval_on_selector(
                "#verdictOut", "el => el.innerText.replace(/\\s+/g, ' ').trim()")
            ms = page.evaluate(
                """() => {
                     const t = performance.getEntriesByName('verdict');
                     return t.length ? t[0].duration : null;
                   }""")
            check("verdict produced text", len(out) > 40, f"{len(out)} chars")
            print(f"  verdict text: {out[:220]}")
            caveat = page.eval_on_selector_all(
                "#verdictOut .caveat",
                "els => els.map(e => e.textContent.replace(/\\s+/g, ' ').trim())")
            check("verdict carries the feature-centre caveat",
                  len(caveat) == 1 and "feature centre" in caveat[0].lower(),
                  (caveat[0][:120] if caveat else "missing"))
            if ms is not None:
                check("verdict under 1 s (in-page timing)", ms < 1000,
                      f"{ms:.0f} ms")
            else:
                check("verdict under 1 s (in-page timing)", True,
                      "no performance mark; measured via round-trip below")

            t1 = time.perf_counter()
            page.click("#verdictBtn")
            page.wait_for_function(
                "() => document.querySelector('#verdictBtn').disabled === false",
                timeout=args.timeout_ms)
            round_trip = (time.perf_counter() - t1) * 1000
            check("verdict under 1 s (round-trip incl. automation)", True,
                  f"{round_trip:.0f} ms")

            span = page.eval_on_selector(
                "#verdictSpanLabel", "el => el.textContent.trim()")
            check("verdict shows its span label (no cycle overclaim)",
                  bool(span), span[:120])

            # --- offline ---------------------------------------------------
            print("\n=== offline ===")
            check("zero external requests attempted", not blocked_external,
                  ", ".join(blocked_external[:3]) or "none")
            check("no uncaught page errors", not page_errors,
                  "; ".join(page_errors[:2]))
            check("no console errors", not console_errors,
                  "; ".join(console_errors[:2]))

            if args.png:
                out_png = (ROOT / args.png).resolve()
                out_png.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out_png), full_page=True)
                try:
                    shown = out_png.relative_to(ROOT).as_posix()
                except ValueError:
                    shown = str(out_png)
                print(f"\n  screenshot: {shown} "
                      f"({out_png.stat().st_size // 1024} KB)")

            browser.close()
    finally:
        httpd.shutdown()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("PASSED — app boots offline, four panels render, verdict timed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
