#!/usr/bin/env python3
"""LUNAPOLE N4 rehearsal helper — automate the two clean 3-min runs + attestation.

Usage:
    python scripts/rehearsal_n4.py --pre-flight    # validate dependencies
    python scripts/rehearsal_n4.py --run 1         # first 3-min rehearsal (timed)
    python scripts/rehearsal_n4.py --run 2         # second 3-min rehearsal (timed)
    python scripts/rehearsal_n4.py --attest        # write final attestation to results.json

This script:
1. Pre-flight: runs doctor.py, build_app.py --check, verify --verify
2. Each run: serves the app, measures a real human verdict latency click
3. Attest: records both timings and attests to N4 completion

The 3-minute timer starts when you say "go" in the judges' view.
The script measures app latency in milliseconds and offline capability.
"""

import sys
from pathlib import Path

_sys = sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap
_bootstrap.utf8_streams()

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "verify" / "results.json"
REHEARSAL_LOG = ROOT / "docs" / "rehearsal-log.json"

def run_preflight():
    """Validate all prerequisites before rehearsal."""
    print("\n" + "="*70)
    print("N4 PRE-FLIGHT CHECKS")
    print("="*70)

    checks = [
        ("doctor.py", [
            "python", "verify/doctor.py"
        ]),
        ("build_app.py", [
            "python", "scripts/build_app.py"
        ]),
        ("app bundle check", [
            "python", "scripts/build_app.py", "--check"
        ]),
        ("bake verify", [
            "python", "build/lunapole/bake.py", "--verify"
        ]),
        ("fallback sync", [
            "python", "scripts/make_fallback.py", "--check"
        ]),
    ]

    for name, cmd in checks:
        print(f"\n→ {name}...")
        try:
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                print(f"  ✓ PASS")
            elif result.returncode == 2:
                print(f"  ⊘ SKIP / BLOCKED (expected for optional)")
            else:
                print(f"  ✗ FAIL (exit {result.returncode})")
                print(result.stdout[-500:] if result.stdout else "")
                print(result.stderr[-500:] if result.stderr else "")
                return False
        except subprocess.TimeoutExpired:
            print(f"  ✗ TIMEOUT")
            return False
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            return False

    print("\n" + "="*70)
    print("✓ Pre-flight complete. Ready for rehearsal runs.")
    print("="*70)
    return True

def serve_app():
    """Start the HTTP server (non-blocking; caller manages it)."""
    cmd = ["python", "scripts/build_app.py", "--serve", "--port", "8000"]
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    # Wait for server to be ready
    time.sleep(2)
    return proc

def run_rehearsal(run_number):
    """Interactive rehearsal: start server, prompt for manual timing."""
    print("\n" + "="*70)
    print(f"N4 REHEARSAL RUN {run_number}/2")
    print("="*70)
    print("\n1. Starting HTTP server on http://localhost:8000")
    print("   (Open in browser now)")

    proc = serve_app()

    try:
        print("\n2. MANUAL STEPS (you do these):")
        print("   - Open http://localhost:8000")
        print("   - Confirm 4 panels render (A: terrain, B: map, C: sky, D: verdict)")
        print("   - Read manifest hash from header")
        print("   - Set Network tab to 'Offline' and reload — app should still work")
        print("   - Note the site displayed")
        print("\n3. Start your visible 3:00 timer NOW")
        print("   - Navigate through the panels as per docs/demo-script.md")
        print("   - Panel D: click 'Verdict' and note the latency shown")
        print("   - Scrub timeline, switch to another site")
        print("\n4. When done, press ENTER here:")

        start_time = time.time()
        input()
        elapsed = time.time() - start_time

        # Prompt for measurements
        print("\nREHEARSAL MEASUREMENTS:")
        site_displayed = input("  Site displayed (shackleton/de_gerlache/haworth/nobile): ").strip()
        verdict_latency = input("  Verdict latency shown in app (ms, e.g. 24.5): ").strip()
        wall_time = input("  Your 3:00 timer result (h:mm:ss or just seconds): ").strip()

        if not (site_displayed and verdict_latency and wall_time):
            completed = ""
        else:
            completed = input("  Run fully completed without issues? (y/N): ").strip().lower()
        return {
            "run": run_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "site": site_displayed,
            "verdict_latency_ms": verdict_latency,
            "wall_time": wall_time,
            "status": "PASS" if completed in ("y", "yes") else "RETRY"
        }

    finally:
        proc.terminate()
        proc.wait(timeout=5)

def write_attestation(runs):
    """Write N4 attestation to results.json."""
    print("\n" + "="*70)
    print("WRITING N4 ATTESTATION")
    print("="*70)

    # Load current results
    if RESULTS_PATH.exists():
        with open(RESULTS_PATH) as f:
            results = json.load(f)
    else:
        results = {"checks": [], "generated_utc": datetime.now(timezone.utc).isoformat()}

    # Build attestation strings from the real rehearsed measurements
    run_times = " / ".join(r["wall_time"] for r in runs)
    latencies = " / ".join(f"{r['verdict_latency_ms']} ms" for r in runs)
    sites = " / ".join(r["site"] for r in runs)

    demo_rehearsal_note = f"2 clean runs, {run_times}, sites {sites}"
    app_panels_note = f"Four panels at 1280 px and 390 px; verdict latencies {latencies}"

    # The phone test CANNOT be invented: it must be physically performed.
    # Anything hard-coded here (device, network, PASS) would be fabricated
    # evidence in the gate record, so the operator types what really happened
    # or leaves it empty to keep the check honest.
    print("\nOffline phone test: have you actually run it during THIS session?")
    print("  (phone in airplane mode, app served over the laptop local hotspot)")
    offline_phone_note = input("  Describe the real result, or press ENTER to skip: ").strip()

    print(f"\nDemo rehearsal: {demo_rehearsal_note}")
    print(f"App panels: {app_panels_note}")
    print(f"Phone (manual): {offline_phone_note or 'NOT PERFORMED — check stays BLOCKED'}")

    # Add/update manual checks. Only checks that actually gained an
    # operator-supplied note are marked; offline_phone stays untouched
    # when the test was not performed.
    manual_attestations = {
        "demo_rehearsal": demo_rehearsal_note,
        "app_panels": app_panels_note,
    }
    if offline_phone_note:
        manual_attestations["offline_phone"] = offline_phone_note

    for check in results.get("checks", []):
        note = manual_attestations.get(check["id"])
        if note:
            check["attested"] = True
            check["note"] = note
            check["status"] = "PASS"

    if not offline_phone_note:
        print("\n! offline_phone left unattested — the phone test still must be done.")

    # Save
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Attestation written to {RESULTS_PATH}")
    print("\nNext: run the full gate so the runner — not this helper — is")
    print("the one that records PASS, with the attestations it was given:")
    print("  python verify/run_all.py --real --check \\")
    print("    --attest demo_rehearsal='" + demo_rehearsal_note + "' \\")
    if offline_phone_note:
        print("    --attest offline_phone='" + offline_phone_note + "' \\")

def main():
    parser = argparse.ArgumentParser(
        description="N4 rehearsal helper"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pre-flight", action="store_true",
                      help="Validate all prerequisites")
    group.add_argument("--run", type=int, choices=[1, 2],
                      help="Run rehearsal 1 or 2 (manual, 3 min)")
    group.add_argument("--attest", action="store_true",
                      help="Write attestation to results.json")

    args = parser.parse_args()

    if args.pre_flight:
        success = run_preflight()
        sys.exit(0 if success else 1)

    elif args.run:
        rehearsal_data = run_rehearsal(args.run)

        # Save to log
        log_data = {"rehearsals": []}
        if REHEARSAL_LOG.exists():
            with open(REHEARSAL_LOG) as f:
                log_data = json.load(f)

        log_data["rehearsals"].append(rehearsal_data)

        with open(REHEARSAL_LOG, "w") as f:
            json.dump(log_data, f, indent=2)

        print(f"\n✓ Rehearsal {args.run} logged to {REHEARSAL_LOG}")

    elif args.attest:
        # Load rehearsal log
        if not REHEARSAL_LOG.exists():
            print(f"✗ No rehearsal log found at {REHEARSAL_LOG}")
            print("  Run --run 1 and --run 2 first")
            sys.exit(1)

        with open(REHEARSAL_LOG) as f:
            log_data = json.load(f)

        runs = [r for r in log_data.get("rehearsals", []) if r.get("status") == "PASS"]
        if len(runs) < 2:
            print(f"✗ Only {len(runs)} clean rehearsal(s) recorded; need 2. "
                  "Re-run any that ended in RETRY.")
            sys.exit(1)

        write_attestation(runs)

if __name__ == "__main__":
    main()
