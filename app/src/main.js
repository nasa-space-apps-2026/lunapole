/* LUNAPOLE offline app shell.
 *
 * Data comes from the bake: artifacts/horizon/*.bin (P3), artifacts/maps/*
 * (P4) and data/terrain/*.bin (a nearest-neighbour export of the P1 crops).
 * There are no network calls anywhere in this file or its imports; the only
 * fetches are relative paths inside the bundle.
 */
import { loadAppData, loadHorizon, loadSeries, loadTerrain } from "./artifacts.js";
import { drawPanorama } from "./panorama.js";
import { drawMap } from "./mapview.js";
import { prepare, drawTimeline, legend } from "./timeline.js";
import { evaluateAt, verdict, isoShort, pct, hours, deg } from "./verdict.js";
import { Terrain3D } from "./terrain3d.js";

const $ = (id) => document.getElementById(id);
const els = {
  site: $("siteSelect"), build: $("buildInfo"), footerBuild: $("footerBuild"),
  siteNote: $("siteNote"), banner: $("banner"),
  terrainMeta: $("terrainMeta"), terrainNote: $("terrainNote"),
  map: $("map"), mapSpan: $("mapSpanLabel"), mapNote: $("mapNote"),
  pano: $("pano"), skyMeta: $("skyMeta"), skyNote: $("skyNote"),
  verdictBtn: $("verdictBtn"), verdictOut: $("verdictOut"), verdictSpan: $("verdictSpanLabel"),
  timeline: $("timeline"), timeMeta: $("timeMeta"), timeNote: $("timeNote"),
  scrub: $("scrub"), readout: $("timeReadout"), play: $("playBtn"),
};

const state = {
  appData: null, site: null, horizon: null, series: null, terrain: null,
  timeline: null, index: 0, product: "ILLU", images: {}, view3d: null,
  playing: false, timer: null,
};

function showBanner(text) {
  els.banner.hidden = false;
  els.banner.textContent = text;
}

function siteTime(i) {
  const t0 = Date.parse(state.series.meta.start_utc);
  const ms = t0 + i * state.series.meta.step_min * 60000;
  return new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

async function selectSite(id) {
  const site = state.appData.sites.find((s) => s.id === id) || state.appData.sites[0];
  if (!site) return;
  state.site = site;
  els.site.value = site.id;
  els.siteNote.hidden = false;
  els.siteNote.textContent =
    `${site.name} \u00b7 ${siteKind(site)} ${fmtLatLon(site)} \u00b7 every ` +
    `number below is measured at this catalogue anchor, which is not a ` +
    `landing site and not the rim peak that published illumination figures ` +
    `usually describe.`;

  try {
    const [horizon, series, terrain] = await Promise.all([
      loadHorizon(site.horizon),
      loadSeries(site.series),
      loadTerrain(site.terrain),
    ]);
    state.horizon = horizon;
    state.series = series;
    state.terrain = terrain;
    state.timeline = prepare(series, horizon);
    state.index = Math.min(state.index, state.timeline.n - 1);
    els.scrub.max = String(state.timeline.n - 1);

    if (state.view3d?.ok) {
      state.view3d.setTerrain(terrain);
      state.view3d.setHorizon(horizon);
    }

    els.terrainMeta.textContent =
      `display ${terrain.n}\u00d7${terrain.n} px \u00b7 ` +
      `${(terrain.gridM / 1000).toFixed(2)} km/px \u00b7 ` +
      `z ${terrain.minM.toFixed(0)}..${terrain.maxM.toFixed(0)} m`;
    els.terrainNote.textContent =
      `Nearest-neighbour export of the verified ${site.id} crop ` +
      `(artifacts/dem/${site.id}.tif) at about 130 m/px for the 3D view; ` +
      `heights \u00d73 for legibility. The horizon panel uses the ` +
      `full-resolution crop. Relief shading only, not a cast-shadow simulation.`;

    els.skyMeta.textContent =
      `${horizon.bins} bins \u00b7 ${horizon.maxDistKm.toFixed(1)} km \u00b7 ` +
      `${horizon.stepM.toFixed(0)} m step \u00b7 far-field ${horizon.farFieldBins}/${horizon.bins}`;
    els.skyNote.textContent =
      `Horizon from artifacts/horizon/${site.id}.bin (P3 max-per-bin march, ` +
      `curvature included). Site elevation ${horizon.siteHM.toFixed(0)} m. ` +
      `Far-field bins are drawn brighter; gaps, if any, are drawn red.`;

    els.timeMeta.textContent =
      `${series.meta.samples} samples \u00b7 ${series.meta.step_min} min \u00b7 ` +
      `${series.meta.span_days} d`;
    els.timeNote.textContent =
      `Yellow: Sun elevation. Grey: the measured horizon at the Sun's azimuth. ` +
      `Blue: Earth elevation. Shaded columns are lit (warm) or dark (cool).`;

    renderVerdictReset();
    render();
  } catch (err) {
    showBanner(`${site.id}: ${err.message}`);
    console.error(err);
  }
}

function render() {
  if (!state.series) return;
  const now = evaluateAt(state.series, state.horizon, state.index);
  drawPanorama(els.pano, state.horizon, now);
  drawTimeline(els.timeline, state.timeline, state.index);

  const map = state.appData.maps.find((m) => m.product === state.product);
  if (map) {
    drawMap(els.map, map, state.images[state.product], state.appData.sites, state.site.id);
    els.mapSpan.textContent = map.span_label;
    els.mapNote.textContent =
      `${map.product === "ILLU" ? "Sun illumination" : "Earth visibility"} \u00b7 ` +
      `${map.width}\u00d7${map.height} px \u00b7 ${map.grid_m.toFixed(0)} m/px \u00b7 ` +
      `${map.az_bins} azimuth bins \u00b7 ${map.step_min} min step \u00b7 ` +
      `${(map.width * map.grid_m / 1000).toFixed(0)} km cap. ` +
      `Grey pixels are outside the measured DEM; deep blue means zero ` +
      `sunlight across the span (Sun map) or no limb at any sample (Earth ` +
      `map); only sites inside the cap are marked. Map pixels are coarser than the ` +
      `${state.horizon.bins}-bin per-site ` +
      `profile the verdict uses; the map is known optimistic on low-horizon pixels.`;
  } else {
    els.mapSpan.textContent = "No baked map in this build.";
    els.mapNote.textContent = "Bake the demo profile to populate artifacts/maps.";
  }

  if (state.view3d?.ok) {
    state.view3d.setSun(now.sunAz, now.sunElev, now.earthAz, now.earthElev);
  }
  els.scrub.value = String(state.index);

  const lg = legend(state.timeline, state.index);
  els.readout.textContent =
    `${siteTime(state.index)}  \u00b7  Sun ${deg(lg.sun)} vs horizon ${deg(lg.horizon)} ` +
    `(${lg.margin >= 0 ? "+" : "\u2212"}${Math.abs(lg.margin).toFixed(2)}\u00b0)  \u00b7  ` +
    `${lg.lit ? "LIT" : "DARK"}  \u00b7  Earth ${deg(now.earthElev)} vs horizon ` +
    `${deg(now.earthHorizon)} (${now.earthMargin >= 0 ? "+" : "\u2212"}` +
    `${Math.abs(now.earthMargin).toFixed(2)}\u00b0)  \u00b7  ` +
    `${now.earthVisible ? "visible" : "not visible"}`;
}

/* Coordinates are always printed with the kind that produced them. A bare
 * "Shackleton, -89.67 129.78" reads to an audience as a landing site; it is
 * the IAU catalogue anchor for the crater, and the app must not imply more. */
function fmtLatLon(site) {
  const ns = site.lat >= 0 ? "+" : "\u2212";
  const ew = site.lon >= 0 ? "+" : "\u2212";
  return `${ns}${Math.abs(site.lat).toFixed(3)}\u00b0, ` +
    `${ew}${Math.abs(site.lon).toFixed(2)}\u00b0`;
}

function siteKind(site) {
  return site?.site_kind || "IAU feature centre";
}

function renderVerdictReset() {
  els.verdictOut.innerHTML =
    '<p class="placeholder">Press <em>Compute verdict</em>. The engine reads the ' +
    "baked rows for this site; nothing is fetched.</p>";
  els.verdictSpan.textContent = "";
}

function computeVerdict() {
  const t0 = performance.now();
  const v = verdict(state.series, state.horizon, state.index);
  const html = [];
  for (const line of v.lines) {
    html.push(`<div class="line"><span class="label">${line.label}</span>` +
      `<div class="head">${line.text}</div>` +
      `<div class="sub">${line.note}</div></div>`);
  }
  const n = v.now;
  html.push(`<div class="now">at ${siteTime(state.index)}
` +
    `Sun ${deg(n.sunElev)} \u00b7 measured horizon ${deg(n.horizonElev)} \u00b7 ` +
    `margin ${deg(n.sunMargin)} \u00b7 disc ${pct(n.sunDisc, 0)}
` +
    `Earth ${deg(n.earthElev)} vs measured horizon ${deg(n.earthHorizon)} \u00b7 ` +
    `visible ${n.earthVisible ? "yes" : "no"} \u00b7 full disc ${n.earthFull ? "yes" : "no"}
` +
    `longest dark run ${hours(v.summary.longestDarkH)} \u00b7 ` +
    `Earth any-limb run ${hours(v.summary.earthLongestAnyH)}</div>`);
  if (state.site) {
    html.push(`<p class="note caveat">Measured at the ${siteKind(state.site)} ` +
      `${fmtLatLon(state.site)}. Published illumination figures usually describe ` +
      `a rim peak or a candidate landing pixel, so they are not directly ` +
      `comparable to a value measured at the feature centre.</p>`);
  }
  els.verdictOut.innerHTML = html.join("");
  els.verdictSpan.textContent = v.spanLabel;

  // Measure through the next paint so the number includes the visible render,
  // not just the arithmetic.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const ms = performance.now() - t0;
    const p = document.createElement("p");
    p.className = "note latency";
    p.textContent =
      `Verdict rendered in ${ms.toFixed(1)} ms from ${v.summary.samples} baked ` +
      `samples; no network request.`;
    els.verdictOut.appendChild(p);
    els.verdictBtn.disabled = false;
  }));
}

function setProduct(product) {
  state.product = product;
  for (const b of document.querySelectorAll(".tab")) {
    b.classList.toggle("is-on", b.dataset.product === product);
  }
  render();
}

function step(delta) {
  if (!state.timeline) return;
  state.index = Math.max(0, Math.min(state.timeline.n - 1, state.index + delta));
  renderVerdictReset();
  render();
}

function togglePlay() {
  state.playing = !state.playing;
  els.play.textContent = state.playing ? "Pause" : "Play";
  if (state.timer) { clearInterval(state.timer); state.timer = null; }
  if (state.playing) {
    state.timer = setInterval(() => {
      if (!state.timeline) return;
      if (state.index >= state.timeline.n - 1) {
        state.playing = false;
        els.play.textContent = "Play";
        clearInterval(state.timer);
        state.timer = null;
        return;
      }
      state.index += 3;
      render();
    }, 40);
  }
}

async function boot() {
  try {
    state.appData = await loadAppData();
  } catch (err) {
    showBanner(`app-data.json: ${err.message}. The bundle must be served over ` +
      `HTTP, e.g. python scripts/build_app.py --serve.`);
    return;
  }
  const b = state.appData.build || {};
  els.build.textContent = b.manifest_sha256
    ? `manifest ${b.manifest_sha256.slice(0, 12)}` : "no manifest";
  els.footerBuild.textContent = b.built_utc ? `build ${b.built_utc}` : "";
  if (!b.manifest_sha256) {
    showBanner("This bundle was built without a manifest. Re-run scripts/build_app.py.");
  }

  const sites = state.appData.sites || [];
  if (!sites.length) {
    showBanner("No site artifacts in this bundle. Bake the demo profile first.");
    return;
  }
  for (const s of sites) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name;
    els.site.appendChild(opt);
  }

  state.images = {};
  await Promise.all((state.appData.maps || []).map(async (m) => {
    state.images[m.product] = await loadImage(m.png);
  }));

  try {
    state.view3d = new Terrain3D($("terrain3d"));
    if (!state.view3d.ok) {
      showBanner(`3D view unavailable (${state.view3d.error}); the other panels still work.`);
    }
  } catch (err) {
    state.view3d = { ok: false, error: String(err) };
    showBanner(`3D view unavailable (${err}); the other panels still work.`);
  }

  els.site.addEventListener("change", () => selectSite(els.site.value));
  els.scrub.addEventListener("input", () => {
    state.index = Number(els.scrub.value);
    renderVerdictReset();
    render();
  });
  els.verdictBtn.addEventListener("click", () => {
    els.verdictBtn.disabled = true;
    computeVerdict();
  });
  els.play.addEventListener("click", togglePlay);
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => setProduct(tab.dataset.product));
  }
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT") return;
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
  });

  const hash = new URLSearchParams(location.hash.slice(1));
  const wanted = hash.get("site") || sites[0].id;
  await selectSite(wanted);
  if (hash.has("i")) {
    state.index = Math.max(0, Math.min(state.timeline.n - 1, Number(hash.get("i")) | 0));
    render();
  }
}

boot();
