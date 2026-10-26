/* Panel A: real terrain in 3D, lit by the real Sun direction.
 *
 * Three.js is vendored (app/vendor/three, MIT) so the bundle has no CDN. The
 * mesh is a nearest-neighbour decimation of the verified crop - the exporter
 * never interpolates, so every vertex height is a measured LOLA pixel.
 *
 * This is relief *shading*, not a cast-shadow simulation: no shadow map is
 * rendered, which the panel says out loud. The horizon ring is the P3
 * artifact at its own occlusion distances.
 */
import * as THREE from "../vendor/three/three.module.js";

const EXAGGERATION = 3;

export class Terrain3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.ok = false;
    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas, antialias: true, alpha: false,
      });
    } catch (err) {
      this.error = String(err);
      return;
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x070a12);
    this.scene.fog = new THREE.Fog(0x070a12, 140, 420);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.5, 2000);
    this.ambient = new THREE.AmbientLight(0x93a7c4, 0.55);
    this.scene.add(this.ambient);
    this.sun = new THREE.DirectionalLight(0xffe3a3, 2.1);
    this.scene.add(this.sun);
    this.sunMarker = new THREE.Mesh(
      new THREE.SphereGeometry(1.6, 20, 14),
      new THREE.MeshBasicMaterial({ color: 0xffd166 }),
    );
    this.earthMarker = new THREE.Mesh(
      new THREE.SphereGeometry(1.3, 20, 14),
      new THREE.MeshBasicMaterial({ color: 0x5cb8ff }),
    );
    this.scene.add(this.sunMarker, this.earthMarker);

    this.orbit = { az: 0.6, el: 0.62, dist: 210 };
    this._bindPointer();
    this._resize();
    this._raf = null;
    this.ok = true;
  }

  setTerrain(terrain) {
    if (!this.ok) return;
    if (this.mesh) {
      this.scene.remove(this.mesh);
      this.mesh.geometry.dispose();
      this.mesh.material.dispose();
    }
    if (this.ring) {
      this.scene.remove(this.ring);
      this.ring.geometry.dispose();
      this.ring.material.dispose();
      this.ring = null;
    }
    const n = terrain.n;
    const gridKm = terrain.gridM / 1000;
    const half = ((n - 1) / 2) * gridKm;
    const pos = new Float32Array(n * n * 3);
    const col = new Float32Array(n * n * 3);
    const lo = terrain.minM, hi = terrain.maxM;
    const span = Math.max(1, hi - lo);
    const c = new THREE.Color();
    for (let row = 0; row < n; row++) {
      for (let colI = 0; colI < n; colI++) {
        const k = row * n + colI;
        const x = colI * gridKm - half;
        const z = row * gridKm - half;          // row 0 = north
        const h = (terrain.z[k] - lo) / span;
        pos[k * 3] = x;
        pos[k * 3 + 1] = (terrain.z[k] / 1000) * EXAGGERATION;
        pos[k * 3 + 2] = z;
        c.setHSL(0.60 - 0.16 * h, 0.16 + 0.22 * h, 0.22 + 0.42 * h);
        col[k * 3] = c.r; col[k * 3 + 1] = c.g; col[k * 3 + 2] = c.b;
      }
    }
    const idx = [];
    for (let row = 0; row < n - 1; row++) {
      for (let colI = 0; colI < n - 1; colI++) {
        const a = row * n + colI, b = a + 1, d = a + n, e = d + 1;
        idx.push(a, d, b, b, d, e);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 0.94, metalness: 0.02, flatShading: false,
    });
    this.mesh = new THREE.Mesh(geo, mat);
    this.scene.add(this.mesh);
    this.orbit.dist = half * 3.1;
    this.terrain = terrain;
    this._aim();
  }

  setHorizon(horizon) {
    if (!this.ok || !this.terrain) return;
    if (this.ring) {
      this.scene.remove(this.ring);
      this.ring.geometry.dispose();
      this.ring.material.dispose();
      this.ring = null;
    }
    const n = horizon.bins;
    const pts = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const az = (horizon.azDeg[i] * Math.PI) / 180;
      const distKm = Math.min(horizon.maxDistKm, Math.max(1, horizon.shadowDistKm[i]));
      const hKm = (horizon.siteHM + distKm * 1000 * Math.tan(horizon.elevDeg[i] * Math.PI / 180)) / 1000;
      // +x east at azimuth 90, -z north at azimuth 0
      pts[i * 3] = distKm * Math.sin(az);
      pts[i * 3 + 1] = hKm * EXAGGERATION;
      pts[i * 3 + 2] = -distKm * Math.cos(az);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pts, 3));
    const mat = new THREE.LineBasicMaterial({ color: 0xffb703, transparent: true, opacity: 0.75 });
    this.ring = new THREE.LineLoop(geo, mat);
    this.scene.add(this.ring);
  }

  setSun(sunAzDeg, sunElevDeg, earthAzDeg, earthElevDeg) {
    if (!this.ok) return;
    const d = 0.5;
    const az = (sunAzDeg * Math.PI) / 180;
    const el = (sunElevDeg * Math.PI) / 180;
    const dir = new THREE.Vector3(
      Math.cos(el) * Math.sin(az), Math.sin(el), -Math.cos(el) * Math.cos(az),
    );
    const r = this.orbit.dist * d;
    this.sun.position.copy(dir.clone().multiplyScalar(r));
    this.sunMarker.position.copy(this.sun.position);
    this.sunMarker.visible = sunElevDeg > -3;
    // Shading is only meaningful while the Sun is up; below the horizon the
    // panel dims rather than lying about illumination.
    this.sun.intensity = sunElevDeg > 0 ? 2.1 : 0.15;
    this.ambient.intensity = sunElevDeg > 0 ? 0.55 : 0.18;

    if (Number.isFinite(earthAzDeg) && Number.isFinite(earthElevDeg)) {
      const eaz = (earthAzDeg * Math.PI) / 180;
      const eel = (earthElevDeg * Math.PI) / 180;
      this.earthMarker.position.set(
        Math.cos(eel) * Math.sin(eaz) * r, Math.sin(eel) * r, -Math.cos(eel) * Math.cos(eaz) * r,
      );
      this.earthMarker.visible = earthElevDeg > 0;
    } else {
      this.earthMarker.visible = false;
    }
    this._draw();
  }

  _aim() {
    const o = this.orbit;
    const x = Math.sin(o.az) * Math.cos(o.el) * o.dist;
    const y = Math.sin(o.el) * o.dist;
    const z = Math.cos(o.az) * Math.cos(o.el) * o.dist;
    this.camera.position.set(x, y, z);
    this.camera.lookAt(0, (this.terrain ? (this.terrain.maxM - this.terrain.minM) * 0.5 : 0) / 1000 * EXAGGERATION * 0.35, 0);
  }

  _draw() {
    if (!this.ok) return;
    this._aim();
    this.renderer.render(this.scene, this.camera);
  }

  _resize() {
    const w = this.canvas.clientWidth || 640;
    const h = this.canvas.clientHeight || 360;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this._draw();
  }

  _bindPointer() {
    let drag = null;
    this.canvas.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY };
      this.canvas.setPointerCapture(e.pointerId);
    });
    this.canvas.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.orbit.az -= (e.clientX - drag.x) * 0.008;
      this.orbit.el = Math.max(0.08, Math.min(1.45, this.orbit.el + (e.clientY - drag.y) * 0.006));
      drag = { x: e.clientX, y: e.clientY };
      this._draw();
    });
    this.canvas.addEventListener("pointerup", () => { drag = null; });
    this.canvas.addEventListener("pointercancel", () => { drag = null; });
    this.canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.orbit.dist = Math.max(20, Math.min(900, this.orbit.dist * (1 + e.deltaY * 0.0012)));
      this._draw();
    }, { passive: false });
    new ResizeObserver(() => this._resize()).observe(this.canvas);
  }
}
