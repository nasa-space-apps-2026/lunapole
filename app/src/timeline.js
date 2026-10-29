/* Timeline panel: Sun elevation vs the measured horizon over the labelled span.
 *
 * A full year at hourly resolution is 8 766 samples; drawing one point per
 * sample would be a 10-pixel-wide smear. Each screen column therefore draws
 * the min/max envelope of the samples it covers, and the "lit" shading uses
 * the per-sample comparison, not the smoothed line.
 */
import { horizonAt } from "./artifacts.js";

const C = {
  bg: "#070a12", grid: "#1b2436", text: "#c9d4e6", dim: "#7f90a8",
  sun: "#ffd166", hor: "#8fa6c8", earth: "#5cb8ff",
  lit: "rgba(255,209,102,0.16)", dark: "rgba(60,80,120,0.22)",
};

// Narrow canvases get every second or third month so labels never overlap.
export function monthStepFor(cssWidth, padL = 44, padR = 12) {
  const w = cssWidth - padL - padR;
  return w < 420 ? 3 : w < 700 ? 2 : 1;
}

export function prepare(series, horizon) {
  const r = series.rows;
  const n = r.et_tdb.length;
  const sun = new Float32Array(n);
  const hor = new Float32Array(n);
  const earth = new Float32Array(n);
  const lit = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    sun[i] = r.sun_elev_deg[i];
    earth[i] = r.earth_elev_deg[i];
    hor[i] = horizonAt(horizon, r.sun_az_deg[i]);
    lit[i] = r.sun_disc_frac[i] > 0 ? 1 : 0;
  }
  return { n, sun, hor, earth, lit, stepMin: series.meta.step_min,
           startUtc: series.meta.start_utc, endUtc: series.meta.end_utc };
}

export function drawTimeline(canvas, tl, index) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = canvas.clientWidth || 800;
  const cssH = canvas.clientHeight || 180;
  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, cssW, cssH);
  g.fillStyle = C.bg;
  g.fillRect(0, 0, cssW, cssH);

  const pad = { l: 44, r: 12, t: 10, b: 24 };
  const w = cssW - pad.l - pad.r;
  const h = cssH - pad.t - pad.b;
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < tl.n; i++) {
    lo = Math.min(lo, tl.sun[i], tl.hor[i], tl.earth[i]);
    hi = Math.max(hi, tl.sun[i], tl.hor[i], tl.earth[i]);
  }
  lo = Math.max(-90, lo - 1);
  hi = Math.min(90, hi + 1);
  if (hi - lo < 4) { hi += 2; lo -= 2; }
  const Y = (el) => pad.t + (1 - (el - lo) / (hi - lo)) * h;
  const X = (i) => pad.l + (i / Math.max(1, tl.n - 1)) * w;

  g.font = "12px system-ui, -apple-system, Segoe UI, sans-serif";
  g.textBaseline = "middle";
  g.strokeStyle = C.grid;
  g.lineWidth = 1;
  g.fillStyle = C.dim;
  g.textAlign = "right";
  for (let el = Math.ceil(lo / 10) * 10; el <= hi; el += 10) {
    const y = Y(el);
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(pad.l + w, y); g.stroke();
    g.fillText(`${el.toFixed(0)}\u00b0`, pad.l - 8, y);
  }
  if (lo < 0 && hi > 0) {
    g.strokeStyle = "rgba(201,212,230,0.28)";
    g.beginPath(); g.moveTo(pad.l, Y(0)); g.lineTo(pad.l + w, Y(0)); g.stroke();
  }

  // per-column envelopes + lit shading
  const cols = Math.max(1, Math.floor(w));
  for (let c = 0; c < cols; c++) {
    const i0 = Math.floor((c / cols) * tl.n);
    const i1 = Math.max(i0 + 1, Math.floor(((c + 1) / cols) * tl.n));
    let sLo = Infinity, sHi = -Infinity, hLo = Infinity, hHi = -Infinity;
    let lLo = Infinity, lHi = -Infinity, eLo = Infinity, eHi = -Infinity;
    let litCount = 0;
    for (let i = i0; i < i1; i++) {
      sLo = Math.min(sLo, tl.sun[i]); sHi = Math.max(sHi, tl.sun[i]);
      hLo = Math.min(hLo, tl.hor[i]); hHi = Math.max(hHi, tl.hor[i]);
      eLo = Math.min(eLo, tl.earth[i]); eHi = Math.max(eHi, tl.earth[i]);
      if (tl.lit[i]) litCount++;
      void lLo; void lHi;
    }
    const x = pad.l + c;
    // shade the column: warm when any sample is lit, cool when none is
    g.fillStyle = litCount ? C.lit : C.dark;
    g.fillRect(x, pad.t, 1, h);
    g.fillStyle = C.hor;
    g.fillRect(x, Y(hHi), 1, Math.max(1, Y(hLo) - Y(hHi)));
    g.fillStyle = C.sun;
    g.fillRect(x, Y(sHi), 1, Math.max(1, Y(sLo) - Y(sHi)));
    g.fillStyle = C.earth;
    g.fillRect(x, Y(eHi), 1, Math.max(1, Y(eLo) - Y(eHi)));
  }

  // month ticks from the real start/end, not from an assumed calendar.
  // Thin the labels on narrow canvases so they do not overlap.
  const t0 = Date.parse(tl.startUtc), t1 = Date.parse(tl.endUtc);
  g.textAlign = "center";
  const start = new Date(t0);
  const monthStep = monthStepFor(cssW, pad.l, pad.r);
  for (let m = 0; m < 13; m += monthStep) {
    const d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + m, 1));
    const frac = (d.getTime() - t0) / (t1 - t0);
    if (frac < 0 || frac > 1) continue;
    const x = pad.l + frac * w;
    g.strokeStyle = "rgba(27,36,54,0.9)";
    g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, pad.t + h); g.stroke();
    g.fillStyle = C.dim;
    g.fillText(d.toLocaleString("en", { month: "short", timeZone: "UTC" }), x, cssH - 10);
  }

  const cx = X(index);
  g.strokeStyle = "rgba(255,255,255,0.85)";
  g.lineWidth = 1.2;
  g.beginPath(); g.moveTo(cx, pad.t); g.lineTo(cx, pad.t + h); g.stroke();
  g.fillStyle = C.sun;
  g.beginPath(); g.arc(cx, Y(tl.sun[index]), 3.5, 0, Math.PI * 2); g.fill();
  g.fillStyle = C.earth;
  g.beginPath(); g.arc(cx, Y(tl.earth[index]), 3.5, 0, Math.PI * 2); g.fill();
  g.fillStyle = C.hor;
  g.beginPath(); g.arc(cx, Y(tl.hor[index]), 3.5, 0, Math.PI * 2); g.fill();
}

export function legend(tl, index) {
  const lit = tl.lit[index] === 1;
  return {
    sun: tl.sun[index], horizon: tl.hor[index], earth: tl.earth[index], lit,
    margin: tl.sun[index] - tl.hor[index],
  };
}
