/* Panel C: the sky at the site - measured horizon, Sun and Earth.
 *
 * The horizon profile is the P3 artifact, unmodified: 720 bins, max-per-bin
 * far-field march, curvature included. Rays that left the crop are drawn in a
 * different colour instead of being hidden.
 */
const FONT = "12px system-ui, -apple-system, Segoe UI, sans-serif";
const C = {
  bg: "#070a12", grid: "#1b2436", text: "#c9d4e6", dim: "#7f90a8",
  terrainFill: "#2a3550", terrainLine: "#8fa6c8",
  far: "#6f8fbf", gap: "#c2415a", sun: "#ffd166", earth: "#5cb8ff",
};

export function drawPanorama(canvas, horizon, now, opts = {}) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = canvas.clientWidth || 640;
  const cssH = canvas.clientHeight || 260;
  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, cssW, cssH);
  g.fillStyle = C.bg;
  g.fillRect(0, 0, cssW, cssH);

  const pad = { l: 44, r: 74, t: 14, b: 30 };
  const w = cssW - pad.l - pad.r;
  const h = cssH - pad.t - pad.b;

  const marks = [now.sunElev, now.earthElev].filter(Number.isFinite);
  let lo = Math.min(-2, ...horizon.elevDeg, ...marks) - 2;
  let hi = Math.max(2, ...horizon.elevDeg, ...marks) + 2;
  // Keep the aspect readable: at least an 8-degree window.
  if (hi - lo < 8) { const mid = (hi + lo) / 2; lo = mid - 4; hi = mid + 4; }

  const X = (az) => pad.l + (az / 360) * w;
  const Y = (el) => pad.t + (1 - (el - lo) / (hi - lo)) * h;

  g.font = FONT;
  g.textBaseline = "middle";

  // grid: elevation every ~5 degrees, azimuth every 45
  const stepEl = niceStep((hi - lo) / 6);
  g.strokeStyle = C.grid;
  g.lineWidth = 1;
  g.fillStyle = C.dim;
  g.textAlign = "right";
  for (let el = Math.ceil(lo / stepEl) * stepEl; el <= hi; el += stepEl) {
    const y = Y(el);
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(pad.l + w, y); g.stroke();
    g.fillText(`${el.toFixed(0)}\u00b0`, pad.l - 8, y);
  }
  const compass = ["N", "E", "S", "W"];
  g.textAlign = "center";
  for (let a = 0; a <= 360; a += 45) {
    const x = X(a);
    g.fillStyle = C.dim;
    g.fillText(`${compass[(a / 90) % 4]} ${a}\u00b0`, Math.min(pad.l + w, Math.max(pad.l, x)), cssH - 12);
  }

  // terrain silhouette (bin centres, close the ring at both ends)
  g.beginPath();
  g.moveTo(X(0), Y(lo));
  for (let i = 0; i < horizon.bins; i++) {
    const az = horizon.azDeg[i];
    g.lineTo(X(az), Y(horizon.elevDeg[i]));
  }
  g.lineTo(X(360), Y(lo));
  g.closePath();
  const grad = g.createLinearGradient(0, pad.t, 0, pad.t + h);
  grad.addColorStop(0, C.terrainFill);
  grad.addColorStop(1, "#0d1420");
  g.fillStyle = grad;
  g.fill();

  g.lineWidth = 1.4;
  for (let i = 0; i < horizon.bins; i++) {
    const a = horizon.azDeg[i];
    const b = i + 1 < horizon.bins ? horizon.azDeg[i + 1] : 360 + horizon.azDeg[0];
    g.strokeStyle = horizon.provenance[i] === 2 ? C.gap
      : (horizon.flags[i] & 1) ? C.far : C.terrainLine;
    g.beginPath();
    g.moveTo(X(a), Y(horizon.elevDeg[i]));
    g.lineTo(X(b), Y(i + 1 < horizon.bins ? horizon.elevDeg[i + 1] : horizon.elevDeg[0]));
    g.stroke();
  }

  // Sun and Earth markers, connected to the horizon elevation at that azimuth
  const marker = (az, el, colour, label) => {
    if (!Number.isFinite(el)) return;
    const x = X(((az % 360) + 360) % 360), y = Y(el);
    if (el >= lo && el <= hi) {
      g.fillStyle = colour;
      g.beginPath(); g.arc(x, y, 5, 0, Math.PI * 2); g.fill();
      g.save();
      g.shadowColor = colour; g.shadowBlur = 12;
      g.beginPath(); g.arc(x, y, 5, 0, Math.PI * 2); g.fill();
      g.restore();
      g.textAlign = x > pad.l + w - 70 ? "right" : "left";
      g.fillStyle = colour;
      g.fillText(`${label} ${el >= 0 ? "+" : "\u2212"}${Math.abs(el).toFixed(2)}\u00b0`,
        x + (x > pad.l + w - 70 ? -9 : 9), y - 10);
    } else {
      g.fillStyle = colour;
      g.textAlign = x > pad.l + w - 70 ? "right" : "left";
      g.fillText(`${label} ${el >= 0 ? "+" : "\u2212"}${Math.abs(el).toFixed(1)}\u00b0 ${el < lo ? "(below)" : "(above)"}`,
        Math.min(pad.l + w, Math.max(pad.l, x)) + (x > pad.l + w - 70 ? -9 : 9),
        el < lo ? cssH - 26 : pad.t + 6);
    }
  };
  marker(now.earthAz, now.earthElev, C.earth, "Earth");
  marker(now.sunAz, now.sunElev, C.sun, "Sun");

  // the Sun's own azimuth column, so the margin vs the horizon is unambiguous
  const sx = X(((now.sunAz % 360) + 360) % 360);
  g.strokeStyle = "rgba(255,209,102,0.35)";
  g.setLineDash([3, 4]);
  g.beginPath();
  g.moveTo(sx, Y(now.horizonElev));
  g.lineTo(sx, Y(now.sunElev));
  g.stroke();
  g.setLineDash([]);
  g.fillStyle = C.sun;
  g.beginPath(); g.arc(sx, Y(now.horizonElev), 3, 0, Math.PI * 2); g.fill();

  g.fillStyle = C.dim;
  g.textAlign = "left";
  g.fillText(`horizon ${opts.horizonNote ?? ""}`, pad.l + 2, pad.t - 2);
}

function niceStep(raw) {
  const pow = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-6))));
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * pow) return m * pow;
  return 10 * pow;
}
