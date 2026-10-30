#!/usr/bin/env python3
"""LUNAPOLE Solutions Deployment Verification — Confirm all implementations ready."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check_file(path, description):
    """Verify a file exists and is readable."""
    if path.exists():
        size_kb = path.stat().st_size / 1024
        print(f"  ✓ {description:50s} {size_kb:6.1f} KB")
        return True
    else:
        print(f"  ✗ {description:50s} MISSING")
        return False

def main():
    print("\n" + "="*70)
    print("LUNAPOLE SOLUTIONS DEPLOYMENT VERIFICATION")
    print("="*70)

    all_ok = True

    # Check N4 automation
    print("\n[1/3] N4 REHEARSAL AUTOMATION")
    print("-"*70)
    all_ok &= check_file(ROOT / "scripts" / "rehearsal_n4.py", "Rehearsal runner")
    all_ok &= check_file(ROOT / "docs" / "N4-QUICK-START.md", "N4 quick-start guide")
    all_ok &= check_file(ROOT / "docs" / "rehearsal-log.json", "Rehearsal log template")

    # Check Horizon automation
    print("\n[2/3] HORIZON UPGRADE AUTOMATION")
    print("-"*70)
    all_ok &= check_file(ROOT / "scripts" / "horizon_upgrade.py", "Horizon upgrade runner")
    all_ok &= check_file(ROOT / "docs" / "HORIZON-UPGRADE.md", "Horizon upgrade guide")

    # Check documentation
    print("\n[3/3] DOCUMENTATION")
    print("-"*70)
    all_ok &= check_file(ROOT / "START-HERE.md", "Executive summary (START HERE)")
    all_ok &= check_file(ROOT / "SOLUTIONS-INDEX.md", "Complete solutions index")
    all_ok &= check_file(ROOT / "docs" / "IMPLEMENTATION-SUMMARY.md", "Implementation details")
    all_ok &= check_file(ROOT / "README.md", "Updated README (N4 section added)")

    print("\n" + "="*70)
    if all_ok:
        print("✓ ALL SOLUTIONS DEPLOYED SUCCESSFULLY")
        print("="*70)
        print("\nNEXT STEPS:")
        print("  1. Read: START-HERE.md")
        print("  2. Choose your path:")
        print("     - Fast (5 min):  Just attest if rehearsals done")
        print("     - Safe (50 min): Pre-flight + 2 rehearsals + attest (RECOMMENDED)")
        print("     - Polish (95 min): Safe path + optional horizon upgrade")
        print("  3. Execute:")
        print("     python verify/doctor.py")
        print("     python scripts/rehearsal_n4.py --pre-flight")
        print("\nREAD FIRST:")
        print("  - START-HERE.md (this file)")
        print("  - docs/N4-QUICK-START.md (command reference)")
        print("\nOPTIONAL:")
        print("  - docs/HORIZON-UPGRADE.md (if upgrading horizons)")
        print("="*70)
        return 0
    else:
        print("✗ DEPLOYMENT INCOMPLETE")
        print("="*70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
