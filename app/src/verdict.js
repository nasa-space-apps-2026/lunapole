/* Verdict engine (P5 W3).
 *
 * The numbers are already in the baked series; this module only evaluates and
 * phrases them. The rule that matters: every number shown carries the span it
 * was measured over, and a partial span is never upgraded to a cycle claim.
 */
import { horizonAt } from "./artifacts.js";

export const pct = (x, digits = 1) => `${(100 * x).toFixed(digits)} %`;

export function hours(h) {
  if (h == null || !Number.isFinite(h)) return "n/a";
  if (h < 48) return `${h.toFixed(1)} h`;
  const d = h / 24;
  return `${h.toFixed(1)} h (${d.toFixed(1)} d)`;
}

export function deg(x, digits = 2) {
  return `${x >= 0 ? "+" : "\u2212"}${Math.abs(x).toFixed(digits)}\u00b0`;
}

export function isoShort(iso) {
  return iso ? iso.replace("T", " ").replace(/:00$/, "") : "n/a";
}

/* Evaluate one timestep against the measured horizon. */
export function evaluateAt(series, horizon, index) {
  const r = series.rows;
  const i = Math.max(0, Math.min(r.et_tdb.length - 1, index | 0));
  const sunElev = r.sun_elev_deg[i];
  const sunAz = r.sun_az_deg[i];
  const earthElev = r.earth_elev_deg[i];
  const earthAz = r.earth_az_deg[i];
  const horizonElev = horizonAt(horizon, sunAz);
  const earthHorizon = horizonAt(horizon, earthAz);
  return {
    i,
    et: r.et_tdb[i],
    sunElev,
    sunAz,
    earthElev,
    earthAz,
    sunDisc: r.sun_disc_frac[i],
    sunFlux: r.sun_flux[i],
    earthDisc: r.earth_disc_frac[i],
    earthFull: r.earth_disc_frac[i] >= fullDiscThreshold(series),
    horizonElev,
    earthHorizon,
    sunMargin: sunElev - horizonElev,
    earthMargin: earthElev - earthHorizon,
    lit: r.sun_disc_frac[i] > 0,
    earthVisible: r.earth_disc_frac[i] > 0,
  };
}

/* Same rule as maps.site_time_series: a disc counts as full when less than
 * half a sample of its area is cut off. Keep the two in step, or the app and
 * the baked verdict block quote different fractions. */
export function fullDiscThreshold(series) {
  const n = series.meta?.disc_samples || 256;
  return 1 - 0.5 / n;
}

export function summarise(series) {
  const v = series.verdict || {};
  const rows = series.rows;
  let sunMax = -Infinity;
  let earthMax = -Infinity;
  for (let i = 0; i < rows.sun_elev_deg.length; i++) {
    if (rows.sun_elev_deg[i] > sunMax) sunMax = rows.sun_elev_deg[i];
    if (rows.earth_elev_deg[i] > earthMax) earthMax = rows.earth_elev_deg[i];
  }
  return {
    litFrac: v.lit_frac_at_disc ?? 0,
    longestLitH: v.longest_lit_h,
    longestDarkH: v.longest_dark_h,
    earthAnyFrac: v.earth_any_frac ?? 0,
    earthLongestAnyH: v.earth_longest_any_h,
    earthLongestFullH: v.earth_longest_full_h,
    sunMax,
    earthMax,
    samples: rows.et_tdb.length,
  };
}

function solarClass(litFrac) {
  if (litFrac >= 0.9) return ["NEAR-CONTINUOUS SOLAR", "power available almost always"];
  if (litFrac >= 0.5) return ["INTERMITTENT SOLAR", "storage required across dark runs"];
  if (litFrac > 0) return ["BRIEF SOLAR WINDOWS", "storage plus a recharge strategy required"];
  return ["NO DIRECT SUNLIGHT", "surface solar is not viable in this span"];
}

function dteClass(earthAnyFrac) {
  if (earthAnyFrac >= 0.95) return ["DIRECT TO EARTH", "Earth stays above the horizon"];
  if (earthAnyFrac >= 0.2) return ["DTE WINDOWS + RELAY", "direct passes exist, gaps need a relay"];
  if (earthAnyFrac > 0) return ["RELAY REQUIRED", "direct-to-Earth only in rare windows"];
  return ["RELAY REQUIRED", "Earth never clears the local horizon"];
}

/* The W3 verdict: two sentences, each naming the measured quantity. */
export function verdict(series, horizon, index) {
  const now = evaluateAt(series, horizon, index);
  const s = summarise(series);
  const [solarHead, solarNote] = solarClass(s.litFrac);
  const [dteHead, dteNote] = dteClass(s.earthAnyFrac);

  const lines = [
    {
      kind: "headline",
      label: "Solar",
      text: `${solarHead} \u2014 Sun above the measured horizon ${pct(s.litFrac)} of the labelled span.`,
      note: `${solarNote}. Longest continuous dark ${hours(s.longestDarkH)}` +
        (series.runs?.longest_dark?.start_utc
          ? `, starting ${isoShort(series.runs.longest_dark.start_utc)} UTC.` : "."),
    },
    {
      kind: "headline",
      label: "Earth link",
      text: "",
      note: dteNote,
    },
  ];

  // Earth full-disc fraction is not in the verdict block; derive it from rows
  // rather than guessing, because the demo reads this number aloud.
  let full = 0;
  const discs = series.rows.earth_disc_frac;
  const fullAt = fullDiscThreshold(series);
  for (let i = 0; i < discs.length; i++) if (discs[i] >= fullAt) full++;
  const earthFullFrac = discs.length ? full / discs.length : 0;
  lines[1].text =
    `${dteHead} \u2014 Earth any limb ${pct(s.earthAnyFrac)}, ` +
    `full disc ${pct(earthFullFrac)} of the labelled span.`;

  return {
    now, summary: s, earthFullFrac,
    solarHead, dteHead,
    lines,
    spanLabel: series.meta?.span_label ?? "",
    spanDays: series.meta?.span_days ?? null,
    sampleSpanHours: (series.meta?.step_min ?? 0) * s.samples / 60,
  };
}
