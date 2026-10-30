# LUNAPOLE N4 Quick Start — Rehearsal & Attestation

**Goal:** Complete the two 3-minute demonstrations and attest N4 gates to PASS.

**Timeline:** 30 min (pre-flight) + 2 × 3 min (rehearsals) + 10 min (attestation) = ~50 min total.

---

## ONE-SHOT COMMAND (if you trust the build)

```bash
# Values in <> placeholders are yours to fill AFTER doing the runs —
# never attest a rehearsed run you have not physically performed.
python verify/run_all.py --real --check \
  --attest demo_rehearsal="2 clean runs, <h:mm:ss> / <h:mm:ss>" \
  --attest offline_phone="<device>, airplane mode, <network>, PASS" \
  --attest app_panels="four panels at 1280 px and 390 px; Sun/Earth read from baked artifacts" \
  --attest verdict_latency="<x.x-x.x ms over 4 sites, in-app timer, no network>"
```

This writes the attestations directly to `verify/results.json` and marks N4 = PASS (if N1-N3 are already passing).

---

## SAFE PATH (Recommended) — Step-by-step

### Phase 1: Pre-flight (T-30 min)

**What:** Validate all prerequisites before rehearsal.

```bash
python scripts/rehearsal_n4.py --pre-flight
```

**What it does:**
- Runs `doctor.py` (checks Python, packages, data)
- Runs `build_app.py` (rebuilds the offline bundle)
- Runs `build_app.py --check` (verifies bundle matches bake)
- Runs `bake.py --verify` (hashes all artifacts)
- Runs `make_fallback.py --check` (validates static fallback)

**Expected output:** All checks PASS or SKIP (optional). If any FAIL, stop and fix it.

---

### Phase 2a: First Rehearsal (T-0 min, 3:00)

**What:** Live demo run #1, measured.

```bash
python scripts/rehearsal_n4.py --run 1
```

**What you do manually:**
1. Script starts HTTP server on `http://localhost:8000`
2. Open the URL in your browser
3. You have **3 minutes** (use a visible timer)
   - Navigate through panels A, B, C, D as per `docs/demo-script.md`
   - Panel D: click "Verdict" and note the latency shown
   - Scrub the timeline to a different date
4. When done, press ENTER
5. Answer prompts:
   - `Site displayed:` (shackleton/de_gerlache/haworth/nobile)
   - `Verdict latency:` (e.g., 24.5 ms)
   - `Wall time:` (e.g., 2:58 or 178 seconds)

**What gets saved:** Run 1 data → `docs/rehearsal-log.json`

---

### Phase 2b: Second Rehearsal (T+5 min, 3:00)

**Repeat the same process:**

```bash
python scripts/rehearsal_n4.py --run 2
```

**Same as Phase 2a** — navigation, measurements, save to log.

---

### Phase 3: Write Attestation (T+10 min)

**What:** Convert measured rehearsals into formal attestations.

```bash
python scripts/rehearsal_n4.py --attest
```

**What it does:**
- Reads `docs/rehearsal-log.json` (both runs)
- Builds human-readable attestation strings
- Writes to `verify/results.json` with status PASS

**Output (format only — numbers are real only when YOU produce them):**
```
Demo rehearsal: 2 clean runs, <t1> / <t2>, sites <s1> / <s2>
App panels: Four panels at 1280 px and 390 px; verdict latencies <x> ms / <y> ms
Offline phone: <device>, airplane mode, <network>, PASS   ← only if really performed

✓ Attestation written to verify/results.json
```

---

### Phase 4: Final Gate Pass (T+20 min)

**Optional:** Re-run the full verification suite with the new attestations:

```bash
python verify/run_all.py --real --check --timeout 0
```

**Expected output:**
```
N1: ... (should already be PASS)
N2: ... (should already be PASS)
N3: ... (should already be PASS)
N4: ... now PASS (demo_rehearsal + offline_phone attested)

Overall: 17 PASS, 0 FAIL, 0 SKIP
Exit code: 0 (green)
```

---

## Phone Test (Manual, separate from timing)

The 3-minute rehearsal is on a laptop. The phone test is separate:

### Before the demo:

1. **Put phone in airplane mode**
2. **Laptop starts hotspot** (or use local Wi-Fi)
3. **Start HTTP server on all interfaces:**
   ```bash
   python scripts/build_app.py --serve --host 0.0.0.0
   ```
   Output will show: `http://192.168.x.x:8000`
4. **On phone:** open that URL
5. **Verify:**
   - 4 panels render
   - Open DevTools (if possible) → check Network tab shows 0 external URLs
   - Verdict button works
   - Numbers match the laptop version

**If phone test passes:** You can manually attest with:
```bash
python verify/run_all.py --real --check --timeout 0 \
  --attest offline_phone="<device>, airplane mode, <network>, PASS"
```

**If phone test fails:** Say so honestly. N4 stays BLOCKED for phone. The laptop-only demo still passes N1-N3.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `doctor.py` says "missing spiceypy" | `pip install spiceypy` |
| `build_app.py --check` fails | `python build/lunapole/bake.py --verify` first |
| App shows blank page | Reload once; try `http://127.0.0.1:8000` instead |
| Verdict takes > 1 sec | Note it in the log; N3 latency is still measured |
| Phone cannot access `192.168.x.x` | Verify both on same network; try hotspot instead of venue Wi-Fi |
| Timer runs over 3:00 | Cut the Earth map segment (2:15-2:40); keep verdict + limitations |

---

## What Each Attestation Means

| Attestation | What it says |
|-------------|------------|
| `demo_rehearsal` | "I ran the 3-min demo twice, both complete, both under 3:00" |
| `offline_phone` | "I tested on a real phone in airplane mode, it worked" |
| `app_panels` | "I saw all 4 panels render, Sun/Earth from artifacts" |
| `verdict_latency` | "The verdict click took X ms, measured by the app's own timer" |

---

## Files Touched

- `scripts/rehearsal_n4.py` — new helper script
- `docs/rehearsal-log.json` — logs your runs
- `docs/demo-script.md` — the 3-minute narrative (read this first)
- `verify/results.json` — final gate record

---

## Next Steps After N4 PASS

1. **Push to repo:**
   ```bash
   git add verify/results.json docs/rehearsal-log.json
   git commit -m "N4: complete rehearsals + phone attestation"
   git push origin main
   ```

2. **Optional: Re-crop horizon at 50 km** (if time permits)
   ```bash
   python scripts/crop_sites.py --radius-km 50
   python build/lunapole/bake.py --profile demo --sites shackleton
   # Re-run verification
   ```

3. **Ship:** You're done. All four gates are now green.

---

## Questions?

- **How long does pre-flight take?** ~30 seconds if everything is cached, ~2 min on first run
- **Can I run rehearsals on different days?** Yes; log is persistent
- **Do I need to re-attest if I fix something?** Yes; re-run `rehearsal_n4.py --attest`
- **What if the 3-min timer is strict (2:59 or fail)?** Keep the verdict + limitations (non-negotiable). Drop the Earth map instead
- **Can the phone test be skipped?** Only if you attest "iPhone test not available" — be honest

