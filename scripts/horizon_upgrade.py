#!/usr/bin/env python3
"""LUNAPOLE horizon re-crop helper — upgrade from 25 km to 50 km radius.

This increases horizon coverage and typically gains 5-15° of visibility on far terrain.

Usage:
    python scripts/horizon_upgrade.py --info          # show current state
    python scripts/horizon_upgrade.py --crop 50       # re-crop at 50 km
    python scripts/horizon_upgrade.py --bake          # re-bake with new crops
    python scripts/horizon_upgrade.py --verify        # verify new horizons

This is OPTIONAL and does NOT block N4. Run it only if:
- You have > 2 GB free disk space
- You have 15-20 minutes
- You want to demonstrate better horizon coverage
"""

import sys
from pathlib import Path

_sys_path = sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap
_bootstrap.utf8_streams()

import argparse
import json
import subprocess
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "artifacts" / "dem"
BACKUP_DIR = ROOT / "artifacts" / "dem.backup-25km"

def show_info():
    """Display current crop status and estimates."""
    print("\n" + "="*70)
    print("HORIZON RE-CROP: 25 km → 50 km")
    print("="*70)

    # Current state
    if ARTIFACTS_DIR.exists():
        crops = list(ARTIFACTS_DIR.glob("*.tif"))
        print(f"\n✓ Current crops: {len(crops)} files")
        for crop in sorted(crops):
            size_mb = crop.stat().st_size / (1024**2)
            print(f"  - {crop.name:30s} {size_mb:6.1f} MB")
        total_mb = sum(c.stat().st_size for c in crops) / (1024**2)
        print(f"  Total: {total_mb:.1f} MB")
    else:
        print("\n✗ No crops found. Run fetch_data.py and crop_sites.py first.")
        return

    print("\n" + "─"*70)
    print("UPGRADE ESTIMATES:")
    print("─"*70)
    print("  Crop radius:      25 km → 50 km")
    print("  Area multiplier:  1× → 4×")
    print("  Current size:     ~44 MB → ~180 MB (estimate)")
    print("  Bake time:        ~10s → ~30s (demo profile)")
    print("  Horizon gains:    +5 to +15° typical far terrain")
    print("  Disk requirement: > 2 GB free (crops + bake temp)")
    print("\n" + "─"*70)
    print("DECISION TREE:")
    print("─"*70)
    print("  1. If disk < 2 GB free     → STOP (not enough space)")
    print("  2. If time pressure        → SKIP (not critical for N4)")
    print("  3. If want better demo     → RUN: --crop 50, then --bake, --verify")
    print("\n")

def backup_current():
    """Save current 25 km crops as backup."""
    if BACKUP_DIR.exists():
        print(f"  → Backup already exists at {BACKUP_DIR}")
        return

    print(f"\n  → Backing up current 25 km crops...")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    for crop in ARTIFACTS_DIR.glob("*.tif"):
        dst = BACKUP_DIR / crop.name
        shutil.copy2(crop, dst)
        print(f"    ✓ {crop.name}")

    print(f"  → Backup complete at {BACKUP_DIR}")

def crop_sites(radius_km):
    """Re-crop all sites at new radius."""
    print(f"\n  → Re-cropping sites at {radius_km} km radius...")

    cmd = [
        "python", "scripts/crop_sites.py",
        f"--radius-km", str(radius_km)
    ]

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300
    )

    if result.returncode == 0:
        print(f"  ✓ Crops complete")
        # Count new crops
        crops = list(ARTIFACTS_DIR.glob("*.tif"))
        total_mb = sum(c.stat().st_size for c in crops) / (1024**2)
        print(f"    {len(crops)} files, {total_mb:.1f} MB total")
    else:
        print(f"  ✗ Crop failed (exit {result.returncode})")
        print(result.stdout[-500:] if result.stdout else "")
        return False

    return True

def rebake_demo():
    """Re-bake horizon and maps with new crops."""
    print(f"\n  → Re-baking demo profile with new crops...")

    cmd = [
        "python", "build/lunapole/bake.py",
        "--profile", "demo",
        "--force"
    ]

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600
    )

    if result.returncode == 0:
        print(f"  ✓ Bake complete")
    else:
        print(f"  ✗ Bake failed (exit {result.returncode})")
        print(result.stdout[-500:] if result.stdout else "")
        return False

    return True

def verify_horizons():
    """Compare old vs new horizons."""
    print(f"\n  → Verifying new horizons...")

    cmd = [
        "python", "verify/verify_horizon.py"
    ]

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode == 0:
        print(f"  ✓ Horizon verification PASS")
        # Extract gains
        lines = result.stdout.split("\n")
        for line in lines:
            if "far-field" in line or "gain" in line or "MAX" in line:
                print(f"    {line.strip()}")
    else:
        print(f"  ✗ Verification failed (exit {result.returncode})")
        return False

    return True

def main():
    parser = argparse.ArgumentParser(
        description="Horizon re-crop: 25 km → 50 km (optional)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--info", action="store_true",
                      help="Show current state and estimates")
    group.add_argument("--crop", type=int, choices=[50, 100],
                      help="Re-crop all sites at 50 or 100 km radius")
    group.add_argument("--bake", action="store_true",
                      help="Re-bake demo profile (requires --crop first)")
    group.add_argument("--verify", action="store_true",
                      help="Verify new horizons")
    group.add_argument("--full-run", type=int, choices=[50, 100],
                      help="Full pipeline: crop → bake → verify")
    group.add_argument("--restore", action="store_true",
                      help="Restore 25 km crops from backup")

    args = parser.parse_args()

    if args.info:
        show_info()

    elif args.crop:
        backup_current()
        if not crop_sites(args.crop):
            sys.exit(1)
        print(f"\n✓ Crops updated to {args.crop} km")
        print(f"  Next: python scripts/horizon_upgrade.py --bake")

    elif args.bake:
        if not rebake_demo():
            sys.exit(1)
        print(f"\n✓ Bake complete")
        print(f"  Next: python scripts/horizon_upgrade.py --verify")

    elif args.verify:
        if not verify_horizons():
            sys.exit(1)
        print(f"\n✓ New horizons verified")

    elif args.full_run:
        print(f"\n" + "="*70)
        print(f"FULL RE-CROP PIPELINE: 25 km → {args.full_run} km")
        print(f"="*70)
        backup_current()
        if not crop_sites(args.full_run):
            sys.exit(1)
        if not rebake_demo():
            sys.exit(1)
        if not verify_horizons():
            sys.exit(1)
        print(f"\n" + "="*70)
        print(f"✓ COMPLETE: Horizon upgraded to {args.full_run} km")
        print(f"="*70)
        print(f"\n  Run: python verify/run_all.py --real --check")
        print(f"  to update the gate record with new horizons.")

    elif args.restore:
        if not BACKUP_DIR.exists():
            print("✗ No backup found")
            sys.exit(1)
        print(f"\n  → Restoring 25 km crops from backup...")
        for crop in BACKUP_DIR.glob("*.tif"):
            dst = ARTIFACTS_DIR / crop.name
            shutil.copy2(crop, dst)
            print(f"    ✓ {crop.name}")
        print(f"  ✓ Restored to 25 km")

if __name__ == "__main__":
    main()
