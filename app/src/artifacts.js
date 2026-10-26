/* Binary artifact readers.
 *
 * Every reader parses the exact header the Python bakers write and refuses
 * anything with the wrong magic. A silently mis-parsed artifact is the worst
 * possible failure here: it would render convincing, wrong terrain.
 *
 * Format sources:
 *   horizon  build/lunapole/horizon.py   '<8sH16sI5f'  + '<fffBB' * bins
 *   terrain  scripts/export_terrain.py   '<8sH16sIddd'  + int16 * n*n
 *   series   build/lunapole/maps.py      JSON (site_time_series)
 */
const text = new TextDecoder("utf-8");
const NUL = /\0+$/;

async function bytes(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url} -> HTTP ${r.status}`);
  return r.arrayBuffer();
}

function cstr(u8, at, len) {
  return text.decode(u8.subarray(at, at + len)).replace(NUL, "");
}

export async function loadAppData() {
  const buf = await bytes("app-data.json");
  return JSON.parse(text.decode(buf));
}

export async function loadHorizon(url) {
  const buf = await bytes(url);
  const u8 = new Uint8Array(buf);
  const dv = new DataView(buf);
  const magic = cstr(u8, 0, 8);
  if (magic !== "LUNAHOR") throw new Error(`${url}: bad magic ${JSON.stringify(magic)}`);
  const version = dv.getUint16(8, true);
  if (version !== 1) throw new Error(`${url}: unsupported horizon version ${version}`);

  const siteId = cstr(u8, 10, 16);
  const bins = dv.getUint32(26, true);
  const stepM = dv.getFloat32(30, true);
  const maxDistKm = dv.getFloat32(34, true);
  const lat = dv.getFloat32(38, true);
  const lon = dv.getFloat32(42, true);
  const siteHM = dv.getFloat32(46, true);

  const HDR = 50, REC = 14;
  if (buf.byteLength !== HDR + REC * bins) {
    throw new Error(`${url}: ${buf.byteLength} B is not ${HDR}+${REC}*${bins}`);
  }
  const elevDeg = new Float32Array(bins);
  const shadowDistKm = new Float32Array(bins);
  const obstacleHM = new Float32Array(bins);
  const flags = new Uint8Array(bins);
  const provenance = new Uint8Array(bins);
  for (let i = 0, off = HDR; i < bins; i++, off += REC) {
    elevDeg[i] = dv.getFloat32(off, true);
    shadowDistKm[i] = dv.getFloat32(off + 4, true);
    obstacleHM[i] = dv.getFloat32(off + 8, true);
    flags[i] = dv.getUint8(off + 12);
    provenance[i] = dv.getUint8(off + 13);
  }
  const azDeg = new Float32Array(bins);
  for (let i = 0; i < bins; i++) azDeg[i] = (i + 0.5) * (360 / bins);

  return {
    siteId, bins, stepM, maxDistKm, lat, lon, siteHM,
    elevDeg, shadowDistKm, obstacleHM, flags, provenance, azDeg,
    farFieldBins: flags.reduce((n, f) => n + ((f & 1) ? 1 : 0), 0),
    gaps: provenance.reduce((n, p) => n + (p === 2 ? 1 : 0), 0),
  };
}

/* Port of horizon.horizon_at(): circular linear interpolation between bin
 * centres. Must match the Python verdict or the app and the JSON disagree. */
export function horizonAt(h, azDeg) {
  const step = 360 / h.bins;
  const x = (((azDeg % 360) + 360) % 360) / step - 0.5;
  const i0 = Math.floor(x);
  const frac = x - i0;
  const a = ((i0 % h.bins) + h.bins) % h.bins;
  const b = (a + 1) % h.bins;
  return h.elevDeg[a] * (1 - frac) + h.elevDeg[b] * frac;
}

export async function loadTerrain(url) {
  const buf = await bytes(url);
  const u8 = new Uint8Array(buf);
  const dv = new DataView(buf);
  const magic = cstr(u8, 0, 8);
  if (magic !== "LUNATRN") throw new Error(`${url}: bad magic ${JSON.stringify(magic)}`);
  const version = dv.getUint16(8, true);
  if (version !== 1) throw new Error(`${url}: unsupported terrain version ${version}`);
  const siteId = cstr(u8, 10, 16);
  const n = dv.getUint32(26, true);
  const gridM = dv.getFloat64(30, true);
  const cxM = dv.getFloat64(38, true);
  const cyM = dv.getFloat64(46, true);
  const HDR = 54;
  if (buf.byteLength !== HDR + n * n * 2) {
    throw new Error(`${url}: ${buf.byteLength} B is not ${HDR}+2*${n}*${n}`);
  }
  const z = new Int16Array(n * n);
  for (let i = 0, off = HDR; i < z.length; i++, off += 2) {
    z[i] = dv.getInt16(off, true);
  }
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < z.length; i++) {
    if (z[i] < lo) lo = z[i];
    if (z[i] > hi) hi = z[i];
  }
  return { siteId, n, gridM, cxM, cyM, z, minM: lo, maxM: hi,
           sideM: (n - 1) * gridM };
}

export async function loadSeries(url) {
  const buf = await bytes(url);
  return JSON.parse(text.decode(buf));
}
