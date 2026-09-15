import * as THREE from "./vendor/three/three.module.js";
import {OrbitControls} from "./vendor/three/addons/controls/OrbitControls.js";
import {Line2} from "./vendor/three/addons/lines/Line2.js";
import {LineGeometry} from "./vendor/three/addons/lines/LineGeometry.js";
import {LineMaterial} from "./vendor/three/addons/lines/LineMaterial.js";
import {mercator, meshElevation, VISUAL_RAISE_M, ELEVATION_COLOR_STOPS} from "./terrain.mjs";

export class TerrainScene {
  constructor(host, {onSelect, onFailure, onCamera, pixelRatio = Math.min(window.devicePixelRatio, 2), drawGrid = true, shading = true}) {
    this.host = host;
    this.onSelect = onSelect;
    this.onCamera = onCamera;
    this.drawGrid = drawGrid;
    this.shading = shading;
    this.scene = new THREE.Scene();
    const css = getComputedStyle(document.documentElement);
    this.color = name => css.getPropertyValue(`--${name}`).trim();
    this.scene.background = new THREE.Color(this.color("bg"));
    this.camera = new THREE.PerspectiveCamera(42, 1, 1, 1e8);
    this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, preserveDrawingBuffer: true});
    this.renderer.setPixelRatio(pixelRatio);
    this.renderer.setSize(host.clientWidth, host.clientHeight);
    const canvas = this.renderer.domElement;
    canvas.tabIndex = 0;
    canvas.setAttribute("aria-label", "3D 軌跡；方向鍵旋轉，+ / - 縮放，F 全程定位");
    canvas.setAttribute("role", "application");
    canvas.style.cssText = "width:100%;height:100%;display:block;touch-action:none";
    host.replaceChildren(canvas);
    canvas.addEventListener("webglcontextlost", event => {event.preventDefault(); onFailure("WebGL context lost");});
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = false;
    this.controls.maxPolarAngle = Math.PI / 2 - .015;
    this.controls.minPolarAngle = .01;
    this.controls.screenSpacePanning = true;
    this.controls.addEventListener("change", () => this.draw());
    this.scene.add(new THREE.AmbientLight(this.color("terrain-light"), .15));
    const light = new THREE.DirectionalLight(this.color("terrain-light"), 3);
    light.position.set(-1, Math.SQRT2, -1);
    this.scene.add(light);
    this.world = new THREE.Group();
    this.scene.add(this.world);
    this.nodes = new Map();
    this.lineMaterials = [];
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
    let down = null;
    canvas.addEventListener("pointerdown", event => { down = [event.clientX, event.clientY]; });
    canvas.addEventListener("pointerup", event => {
      if (event.button !== 0 || !down || Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 5) return;
      const rect = canvas.getBoundingClientRect();
      const ray = new THREE.Raycaster();
      ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), this.camera);
      const intersections = ray.intersectObjects([...this.nodes.values()]);
      if (intersections.length) onSelect(intersections[0].object.userData.node.id);
    });
    canvas.addEventListener("keydown", event => {
      const handlers = {ArrowLeft: () => this.rotate(-15), ArrowRight: () => this.rotate(15),
        ArrowUp: () => this.tilt(8), ArrowDown: () => this.tilt(-8), "+": () => this.zoom(.8), "=": () => this.zoom(.8), "-": () => this.zoom(1.25), f: () => this.fit()};
      if (handlers[event.key]) {event.preventDefault(); handlers[event.key]();}
    });
  }

  clear() {
    this.world.traverse(object => {
      object.geometry?.dispose();
      if (object.material) {
        object.material.map?.dispose();
        object.material.dispose();
      }
    });
    this.world.clear();
    this.nodes.clear();
    this.lineMaterials = [];
  }

  setData(model, mesh) {
    this.clear();
    this.model = model;
    this.mesh = mesh;
    const bounds = model.bounds || [[-1, -1], [1, 1]];
    const centerLat = (bounds[0][1] + bounds[1][1]) / 2;
    this.origin = mercator((bounds[0][0] + bounds[1][0]) / 2, centerLat);
    this.scale = Math.cos(centerLat * Math.PI / 180);
    this.base = mesh?.status === "ready" ? mesh.minimum_elevation_m - 100 : null;
    this.routeBox = new THREE.Box3();
    for (const point of [...model.segments.flatMap(s => s.points), ...model.nodes.filter(n => n.display_supported !== false)]) {
      this.routeBox.expandByPoint(this.position(point.lon, point.lat));
    }
    if (this.routeBox.isEmpty()) this.routeBox.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(1000, 100, 1000));
    const size = this.routeBox.getSize(new THREE.Vector3());
    const gridSize = Math.max(size.x, size.z, 1000) * 1.8;
    // The grid is a schematic coordinate plane, not missing DEM filled at 0 m.
    if (this.drawGrid) {
      const grid = new THREE.GridHelper(gridSize, 24, this.color("line-strong"), this.color("line"));
      grid.material.transparent = true; grid.material.opacity = .35;
      grid.position.y = -10;
      this.world.add(grid);
    }
    if (mesh?.status === "ready") this.addTerrain(mesh);
    this.displayLineCount = 0;
    for (const segment of model.segments) this.addRoute(segment);
    for (const node of model.nodes) {
      if (node.display_supported === false) continue;
      const color = this.color(node.kind === "start" ? "ok" : node.kind === "end" ? "warn" : "accent");
      const sprite = this.sprite(color);
      sprite.position.copy(this.position(node.lon, node.lat));
      sprite.userData.node = node;
      this.nodes.set(node.id, sprite);
      this.world.add(sprite);
    }
    this.cursor = this.sprite(this.color("candidate"), true);
    this.cursor.visible = false;
    this.world.add(this.cursor);
    this.fit();
    this.host.dataset.renderer = "three";
    this.host.dataset.segmentCount = String(model.segments.length);
  }

  position(lon, lat) {
    const [x, y] = mercator(lon, lat);
    const height = meshElevation(this.mesh, lon, lat);
    return new THREE.Vector3((x - this.origin[0]) * this.scale,
      height === null ? 0 : height - this.base + VISUAL_RAISE_M,
      (this.origin[1] - y) * this.scale);
  }

  addTerrain(mesh) {
    const vertices = new Float32Array(mesh.width * mesh.height * 3);
    const colors = new Float32Array(vertices.length);
    const indices = [];
    // Interpolate reference-ramp RGB values first, then store linear values
    // for Three.js lighting. The unshaded legend uses the same sRGB ramp.
    const stops = ELEVATION_COLOR_STOPS.map(stop => ({...stop, color: new THREE.Color(this.color(stop.token)).convertLinearToSRGB()}));
    const color = new THREE.Color();
    const range = mesh.maximum_elevation_m - mesh.minimum_elevation_m;
    for (let row = 0; row < mesh.height; row++) {
      for (let column = 0; column < mesh.width; column++) {
        const i = row * mesh.width + column;
        vertices[i * 3] = (mesh.x0 + column * mesh.step_m - this.origin[0]) * this.scale;
        vertices[i * 3 + 1] = mesh.elevations[i] - this.base;
        vertices[i * 3 + 2] = (this.origin[1] - mesh.y0 + row * mesh.step_m) * this.scale;
        const fraction = range > 0 ? Math.max(0, Math.min(1, (mesh.elevations[i] - mesh.minimum_elevation_m) / range)) : 0;
        const upper = stops.findIndex((stop, index) => index > 0 && fraction <= stop.fraction);
        const low = stops[upper - 1], high = stops[upper];
        color.lerpColors(low.color, high.color, (fraction - low.fraction) / (high.fraction - low.fraction));
        color.convertSRGBToLinear();
        color.toArray(colors, i * 3);
        if (row < mesh.height - 1 && column < mesh.width - 1) {
          indices.push(i, i + mesh.width + 1, i + 1, i, i + mesh.width, i + mesh.width + 1);
        }
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(vertices, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.setIndex(indices);
    if (this.shading) geometry.computeVertexNormals();
    const Material = this.shading ? THREE.MeshLambertMaterial : THREE.MeshBasicMaterial;
    const terrain = new THREE.Mesh(geometry, new Material({vertexColors: true, side: THREE.DoubleSide}));
    this.world.add(terrain);
    this.host.dataset.terrainVertices = String(mesh.width * mesh.height);
  }

  addRoute(segment) {
    let points = [], supported = null;
    const flush = () => {
      if (points.length >= 6) {
        const geometry = new LineGeometry(); geometry.setPositions(points);
        const material = new LineMaterial({color: this.color(supported ? "accent" : "accent-2"), linewidth: 3, dashed: !supported, dashSize: 80, gapSize: 60});
        material.resolution.set(this.host.clientWidth, this.host.clientHeight);
        this.lineMaterials.push(material);
        const line = new Line2(geometry, material); line.computeLineDistances();
        line.userData.source_segment_id = segment.source_segment_id;
        this.world.add(line); this.displayLineCount += 1;
      } else if (points.length === 3) {
        const geometry = new THREE.BufferGeometry(); geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
        this.world.add(new THREE.Points(geometry, new THREE.PointsMaterial({color: this.color("accent"), size: 4, sizeAttenuation: false})));
      }
      points = [];
    };
    const append = (lon, lat) => {
      const next = meshElevation(this.mesh, lon, lat) !== null;
      if (supported !== null && next !== supported) flush();
      supported = next;
      this.position(lon, lat).toArray(points, points.length);
    };
    segment.points.forEach((point, i) => {
      if (i && this.mesh?.status === "ready") {
        const before = segment.points[i - 1];
        const a = mercator(before.lon, before.lat), b = mercator(point.lon, point.lat);
        const steps = Math.ceil(Math.hypot(a[0] - b[0], a[1] - b[1]) / this.mesh.step_m);
        // Display drape subdivision only; no source point or official metric changes.
        for (let step = 1; step < steps; step++) append(before.lon + (point.lon - before.lon) * step / steps, before.lat + (point.lat - before.lat) * step / steps);
      }
      append(point.lon, point.lat);
    });
    flush();
  }

  sprite(color, diamond = false) {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 64;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = color; ctx.strokeStyle = this.color("bg"); ctx.lineWidth = 6;
    ctx.beginPath();
    if (diamond) {ctx.moveTo(32, 4);ctx.lineTo(60, 32);ctx.lineTo(32, 60);ctx.lineTo(4, 32);ctx.closePath();}
    else ctx.arc(32, 32, 22, 0, Math.PI * 2);
    ctx.fill();ctx.stroke();
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(canvas), depthTest: false, sizeAttenuation: false}));
    sprite.scale.set(.020, .020, 1); sprite.renderOrder = 4;
    return sprite;
  }

  select(id) {
    for (const [key, sprite] of this.nodes) {
      sprite.scale.setScalar(key === id ? .030 : .020);
      sprite.material.rotation = key === id ? Math.PI / 4 : 0;
    }
    this.host.dataset.selectedNode = id || "";
    this.draw();
  }

  playback(position) {
    this.cursor.visible = Boolean(position);
    if (position) this.cursor.position.copy(this.position(...position));
    this.draw();
  }

  fit() {
    if (!this.routeBox) return;
    const center = this.routeBox.getCenter(new THREE.Vector3());
    const radius = Math.max(this.routeBox.getSize(new THREE.Vector3()).length() / 2, 250);
    const vertical = this.camera.fov * Math.PI / 180;
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * this.camera.aspect);
    const distance = radius / Math.sin(Math.min(vertical, horizontal) / 2) * 1.12;
    this.controls.target.copy(center);
    const direction = this.mesh?.status === "ready" ? new THREE.Vector3(.18, .9, 1) : new THREE.Vector3(0, 1, .001);
    this.camera.position.copy(center).add(direction.normalize().multiplyScalar(distance));
    this.camera.near = Math.max(1, radius / 2000); this.camera.far = distance * 100;
    this.camera.updateProjectionMatrix(); this.controls.minDistance = 40; this.controls.maxDistance = distance * 5;
    this.controls.update(); this.draw();
  }

  zoom(factor) {this.camera.position.sub(this.controls.target).multiplyScalar(factor).add(this.controls.target);this.controls.update();this.draw();}
  rotate(degrees) {this.camera.position.sub(this.controls.target).applyAxisAngle(new THREE.Vector3(0, 1, 0), degrees * Math.PI / 180).add(this.controls.target);this.controls.update();this.draw();}
  tilt(degrees = null) {
    const offset = this.camera.position.clone().sub(this.controls.target), spherical = new THREE.Spherical().setFromVector3(offset);
    spherical.phi = degrees === null ? (spherical.phi < .15 ? .85 : .01) : Math.max(.01, Math.min(Math.PI / 2 - .02, spherical.phi + degrees * Math.PI / 180));
    this.camera.position.copy(this.controls.target).add(new THREE.Vector3().setFromSpherical(spherical));this.controls.update();this.draw();
  }

  resize() {
    const width = this.host.clientWidth, height = this.host.clientHeight;
    if (!width || !height) return;
    this.camera.aspect = width / height; this.camera.updateProjectionMatrix();this.renderer.setSize(width, height);
    this.lineMaterials.forEach(m => m.resolution.set(width, height));this.draw();
  }

  draw() {
    this.renderer.render(this.scene, this.camera);
    const spherical = new THREE.Spherical().setFromVector3(this.camera.position.clone().sub(this.controls.target));
    this.onCamera?.({bearing: spherical.theta * 180 / Math.PI, pitch: spherical.phi * 180 / Math.PI, distance: spherical.radius});
  }

  screenPosition(id) {
    const node = this.nodes.get(id); if (!node) return null;
    const point = node.position.clone().project(this.camera);
    return {x: (point.x + 1) / 2 * this.host.clientWidth, y: (1 - point.y) / 2 * this.host.clientHeight, visible: Math.abs(point.x) <= 1 && Math.abs(point.y) <= 1 && Math.abs(point.z) <= 1};
  }

  dispose() {this.resizeObserver.disconnect();this.controls.dispose();this.clear();this.renderer.dispose();}
}
