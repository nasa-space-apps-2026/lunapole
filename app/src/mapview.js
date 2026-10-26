/* Panel B: the baked pole-cap map, drawn from the artifact itself.
 *
 * The PNG next to each .bin is produced by the same bake that produced the
 * planes, so the picture cannot drift from the numbers. The span label is
 * rendered verbatim from the map header via app-data.json.
 */
const R_MOON_M = 1_737_400;

export function latLonToStereo(latDeg, lonDeg) {
  const r = 2 * R_MOON_M * Math.tan(Math.PI / 4 + (latDeg * Math.PI / 180) / 2);
  const lo = (lonDeg * Math.PI) / 180;
  return { x: r * Math.sin(lo), y: -r * Math.cos(lo) };
}

export function drawMap(canvas, map, image, sites, selectedId) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = canvas.clientWidth || 420;
  const cssH = canvas.clientHeight || 420;
  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.fillStyle = "#070a12";
  g.fillRect(0, 0, cssW, cssH);
  if (!image || !image.complete || !image.naturalWidth) return;

  const side = Math.min(cssW, cssH);
  const ox = (cssW - side) / 2;
  const oy = (cssH - side) / 2;
  g.imageSmoothingEnabled = true;
  g.drawImage(image, ox, oy, side, side);

  const { width, height, grid_m: gridM, center } = map;
  const px = side / width;
  const py = side / height;

  for (const s of sites) {
    const p = latLonToStereo(s.lat, s.lon);
    const col = Math.round((p.x - center[0]) / gridM + (width - 1) / 2);
    const row = Math.round((height - 1) / 2 - (p.y - center[1]) / gridM);
    if (col < 0 || row < 0 || col >= width || row >= height) continue;
    const x = ox + col * px;
    const y = oy + row * py;
    const active = s.id === selectedId;
    g.beginPath();
    g.arc(x, y, active ? 6 : 4, 0, Math.PI * 2);
    g.fillStyle = active ? "#ffd166" : "rgba(255,255,255,0.85)";
    g.fill();
    g.strokeStyle = "rgba(0,0,0,0.75)";
    g.lineWidth = 1.5;
    g.stroke();
    g.font = `${active ? "600 " : ""}12px system-ui, -apple-system, Segoe UI, sans-serif`;
    g.fillStyle = active ? "#ffe6a8" : "#dfe8f5";
    g.textAlign = "left";
    g.textBaseline = "middle";
    g.fillText(s.name, x + 9, y);
  }

  // north-up crosshair at the pole (the region centre)
  const cx = ox + ((width - 1) / 2) * px;
  const cy = oy + ((height - 1) / 2) * py;
  g.strokeStyle = "rgba(255,255,255,0.35)";
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(cx - 6, cy); g.lineTo(cx + 6, cy);
  g.moveTo(cx, cy - 6); g.lineTo(cx, cy + 6);
  g.stroke();
}
