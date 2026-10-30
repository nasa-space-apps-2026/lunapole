# LUNAPOLE Horizon Upgrade — Optional 25 km → 50 km Re-crop

**Status:** Optional. Not required for N4 to pass. Improves demo quality if time/disk allows.

**Timeline:** 30–45 minutes (crop ~10 min, bake ~30 min, verify ~5 min).

**Benefit:** Horizon coverage increases from 25 km to 50 km. Far-terrain visibility typically improves 5–15° per site.

---

## Quick Decision

| Your situation | Recommendation |
|---|---|
| N4 rehearsal happening now | **SKIP** — finish N4 first; upgrade is polish |
| Disk > 3 GB free | **TRY** `--full-run 50` (safest path) |
| Disk 1–3 GB free | **SKIP** (bake + temp directories need headroom) |
| Time pressure (< 1 hour) | **SKIP** (crops take ~10 min, bake ~30 min) |
| Want maximum demo quality | **RUN** `--full-run 50` after N4 passes |

---

## One-Shot Command (if go/no-go is clear)

```bash
# Check status and estimates
python scripts/horizon_upgrade.py --info

# If decision is GO: full pipeline
python scripts/horizon_upgrade.py --full-run 50

# Then re-verify
python verify/run_all.py --real --check --timeout 0
```

---

## Step-by-Step Path

### Step 1: Check Current State

```bash
python scripts/horizon_upgrade.py --info
```

**Output example:**
```
✓ Current crops: 6 files
  - shackleton.tif        44.2 MB
  - de_gerlache.tif       41.8 MB
  ...
  Total: 264.5 MB

UPGRADE ESTIMATES:
  Crop radius:      25 km → 50 km
  Area multiplier:  1× → 4×
  Current size:     ~44 MB → ~180 MB (per site, estimate)
  Bake time:        ~10s → ~30s (demo profile)
  Horizon gains:    +5 to +15° typical far terrain
  Disk requirement: > 2 GB free (crops + bake temp)
```

**Decision:**
- If `Disk requirement > available`, **STOP**
- If time < 1 hour, **SKIP**
- Otherwise, proceed to Step 2

---

### Step 2: Backup Current Crops

```bash
python scripts/horizon_upgrade.py --crop 50
```

**What happens:**
1. Backs up current 25 km crops to `artifacts/dem.backup-25km/`
2. Re-crops all 6 sites at 50 km radius (takes ~5–10 min)
3. Saves new TIF files to `artifacts/dem/` (overwriting old ones)

**Output:**
```
→ Backing up current 25 km crops...
  ✓ shackleton.tif
  ✓ de_gerlache.tif
  ...
→ Backup complete at artifacts/dem.backup-25km/

→ Re-cropping sites at 50 km radius...
✓ Crops complete
  6 files, 180.2 MB total
```

---

### Step 3: Re-bake Horizons & Maps

```bash
python scripts/horizon_upgrade.py --bake
```

**What happens:**
1. Runs `bake.py --profile demo` with new 50 km crops
2. Regenerates all horizons and maps (takes ~25–35 min)
3. Writes new artifacts to `artifacts/` (overwrites old ones)

**Output:**
```
→ Re-baking demo profile with new crops...
✓ Bake complete
  16 artifacts written, manifest updated
```

---

### Step 4: Verify New Horizons

```bash
python scripts/horizon_upgrade.py --verify
```

**What happens:**
1. Compares horizon profiles (coverage, elevation range, far-field gains)
2. Checks that far-field never lowers (sanity check)
3. Reports gains vs 25 km baseline

**Output example:**
```
→ Verifying new horizons...
✓ Horizon verification PASS
  Shackleton: 720/720 far-field bins (was 720/720), gain +3.2° avg
  de Gerlache: 720/720 far-field bins, gain +8.1° avg
  Haworth: 710/720 far-field bins (3 edge flags), gain +1.8° avg
  ...
```

---

## Full Pipeline (All-In-One)

If you're confident and have time/disk:

```bash
python scripts/horizon_upgrade.py --full-run 50
```

This runs steps 1–4 in sequence:
- Backs up
- Crops at 50 km
- Re-bakes
- Verifies

Takes ~45 minutes total.

---

## Restore to 25 km (if needed)

```bash
python scripts/horizon_upgrade.py --restore
```

This copies crops back from `artifacts/dem.backup-25km/` to `artifacts/dem/`, reverting to the original 25 km radius.

Then re-bake:
```bash
python build/lunapole/bake.py --profile demo --force
```

---

## What Changes in the Demo

| Element | 25 km | 50 km | Impact |
|---------|-------|-------|--------|
| Horizon range | 25 km radius | 50 km radius | Captures more far terrain |
| Typical far-field gain | — | +5 to +15° | Sites near rim see more earth/sun |
| Map region | unchanged | unchanged | 148 km polecap, still same |
| Verdict latency | 21–29 ms | ~22–30 ms | Minimal impact |
| Artifact size | ~14 MB | ~16 MB | +2 MB (negligible) |

**Visual:** The horizon ring in Panel A gets taller (more distant terrain visible). Shackleton rim shows more of the surrounding basin occluding the distant sun at twilight.

---

## Caveats

1. **Same OS/Python/NumPy requirement:** Byte identity may differ if your build machine's PNG encoder or NumPy version differs from the original. That's OK — re-verify gates and update `results.json`.

2. **Manifest changes:** The new bake produces a different `manifest_sha256`. This is expected and correct (same inputs, different parameters → different manifest).

3. **Flag interpretation:** New `FLAG_EDGE` locations in the horizon binary. The verifier checks this automatically.

4. **Not reversible without backup:** Once you re-bake at 50 km, the 25 km crops are gone. Use `--restore` to go back.

---

## After Upgrade: Update Gates

Once the new crops, horizons, and maps are baked, re-run verification:

```bash
python verify/run_all.py --real --check --timeout 0
```

**Expected:**
- All checks still pass (horizon structure is the same, just larger)
- New `manifest_sha256` recorded
- Horizon gains noted in the output

**If any check fails:**
```bash
python scripts/horizon_upgrade.py --restore
python build/lunapole/bake.py --profile demo --force
# Then re-verify with original 25 km
```

---

## Why 50 km and Not 100 km?

| Radius | Crop size | Bake time | Horizon coverage | Notes |
|--------|-----------|-----------|------------------|-------|
| 25 km | 44 MB | ~5s | Complete at crop edge | Current demo |
| 50 km | 180 MB | ~30s | Typically 95%+ of "horizon ceiling" | Sweet spot |
| 100 km | 500 MB | ~90s | Max curvature effect visible | Expensive; diminishing returns |

**Recommendation:** 50 km is the best trade-off. It captures the critical far-terrain effects (curvature drop, distant ridges blocking low-sun rays) without excessive bake time.

If you have time and disk, 100 km is also valid — just takes longer. Uncomment that option in the script.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `crop_sites.py: rasterio error` | Verify DEM tiles are present: `ls data/dem/*.jp2` |
| `bake.py: KeyError in maps` | Run `bake.py --plan` first to validate parameters |
| `verify_horizon.py: timeout` | Increase timeout; `--verify` re-hashes all artifacts |
| `Disk full during bake` | Clear cache: `rm -rf artifacts/.stage-*` and `build/**/__pycache__` |
| New manifest doesn't match published | Expected! Parameters changed (crop radius). Old → new is not byte-identical |

---

## When to Skip This

- **N4 rehearsal is happening now** — focus on that first
- **Disk < 2 GB free** — upgrade is postponed
- **Time budget < 1 hour** — too tight
- **Risk-averse** — the 25 km demo is already solid; 50 km is optional polish

---

## When to Do This

- **After N4 passes** — you have confirmed all gates work; now optimize
- **Disk > 3 GB free** — comfortable margin for crops + temp + bake
- **Time available** — 45 min for full pipeline
- **Want best-case demo** — horizon expansion is visible in Panel A

---

## Next Steps

1. **Run `--info` to decide** (2 min)
2. **If GO:** `--full-run 50` (45 min)
3. **Re-verify gates** (5 min)
4. **Commit new artifacts** (1 min)
5. **Demo with better horizons** ✓

