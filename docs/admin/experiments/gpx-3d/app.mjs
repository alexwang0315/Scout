import {parseGpx, buildTimeline, samplePlayback} from "./gpx.mjs";
import {createSelection} from "./selection.mjs";
import {meshElevation, VISUAL_RAISE_M, ELEVATION_COLOR_STOPS} from "./terrain.mjs";

const $ = id => document.getElementById(id);
const setText = (id, value) => {$(id).textContent = value;};
const state = {model: null, mesh: null, scene: null, timeline: null, source: null, fraction: 0, playing: false, generation: 0, rawBytes: null};
let frameId = 0, previousFrame = null, sampleGeneration = 0;
let fallbackProject = null;
const selection = createSelection(node => {
  state.scene?.select(node?.id);
  $("map").dataset.selectedNode = node?.id || "";
  for (const circle of $("map").querySelectorAll("circle[data-node-id]")) circle.setAttribute("r", circle.dataset.nodeId === node?.id ? "12" : "8");
  for (const row of $("nodes").querySelectorAll("button")) row.setAttribute("aria-pressed", String(row.dataset.nodeId === node?.id));
  if (node) {
    const row = [...$("nodes").querySelectorAll("button")].find(button => button.dataset.nodeId === node.id);
    if (row) $("nodes").scrollTop = row.offsetTop - $("nodes").offsetTop;
  }
  renderNode(node);
});

function addField(list, label, value) {
  const dt = document.createElement("dt"), dd = document.createElement("dd");
  dt.textContent = label; dd.textContent = value ?? "unknown";
  list.append(dt, dd); return dd;
}
const altitude = value => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)} m` : "缺漏 / unknown";

async function json(url) {
  const response = await fetch(url, {cache: "no-store"});
  if (!response.ok) throw new Error(`${url.split("?")[0]} · HTTP ${response.status}`);
  return response.json();
}

function renderNode(node) {
  const generation = ++sampleGeneration;
  const detail = $("node-detail"); detail.replaceChildren();
  const heading = document.createElement("h2"); heading.textContent = node?.name || "選取節點"; detail.append(heading);
  if (!node) {
    const p = document.createElement("p");p.textContent = "點選地圖或清單，查看相同的來源記錄。";p.className = "muted";detail.append(p);return;
  }
  const dl = document.createElement("dl");detail.append(dl);
  addField(dl, "座標 · WGS84", `經度 ${node.lon.toFixed(7)} / 緯度 ${node.lat.toFixed(7)}`);
  addField(dl, "GPX 原始高程 · 垂直基準 unknown", altitude(node.gpx_elevation_m));
  if (node.kind === "checkpoint") {
    addField(dl, "既有 CP 記載高程 · 基準 unknown", altitude(node.cp_elevation_m));
    addField(dl, "CP 原有審查狀態", node.review_state);
  }
  const demCell = addField(dl, "DEM 取樣 · prepared Terrain RGB", state.mesh?.status === "ready" ? "正在讀取原瓦片像素…" : "不可用");
  const visual = fallbackProject ? null : meshElevation(state.mesh, node.lon, node.lat);
  addField(dl, "純視覺貼地 / 抬升", visual === null
    ? "無 DEM 支援；僅平面位置示意，高程 unknown"
    : `展示網格 ${altitude(visual)} + ${VISUAL_RAISE_M} m 視覺抬升；不修改來源高程`);
  addField(dl, "時間 · 來源原文", node.time || "缺漏 / unknown");
  addField(dl, "資料來源", node.source_ref);
  addField(dl, "SHA-256", node.source_sha256 || state.source?.sha256);
  if (node.kind === "checkpoint") addField(dl, "CP 關聯依據", "來源 URI 或速度篩選報告的輸出雜湊；不是按距離猜測");
  if (state.mesh?.status === "ready") {
    json(`/api/elevation?lon=${encodeURIComponent(node.lon)}&lat=${encodeURIComponent(node.lat)}`)
      .then(sample => {
        if (generation !== sampleGeneration) return;
        demCell.textContent = sample.elevation_m === null ? "超出已準備範圍 / unknown"
          : `${altitude(sample.elevation_m)} · ${sample.vertical_datum} · 獨立讀取原瓦片像素（0.1 m 編碼，不代表精度）`;
        if (sample.source_ref) addField(dl, "DEM 取樣來源", `${sample.source_ref} · SHA-256 ${sample.sha256}`);
      }).catch(error => {
        if (generation === sampleGeneration) demCell.textContent = `取樣失敗 / unknown · ${error.message}`;
      });
  }
}

function renderNodes() {
  const query = $("node-filter").value.trim().toLowerCase();
  const fragment = document.createDocumentFragment();
  const nodes = state.model?.nodes || [];
  for (const node of nodes.filter(n => n.name.toLowerCase().includes(query))) {
    const row = document.createElement("button"); row.className = "node-row";
    row.dataset.nodeId = node.id; row.dataset.kind = node.kind;
    row.setAttribute("aria-pressed", String(selection.current()?.id === node.id));
    const dot = document.createElement("span");dot.className = "dot";dot.setAttribute("aria-hidden", "true");
    const title = document.createElement("span");title.className = "node-name";
    title.textContent = `${node.name}${node.kind === "checkpoint" ? " · 既有 CP 候選" : ""}`;
    row.append(dot, title);row.addEventListener("click", () => selection.select(node.id));fragment.append(row);
  }
  $("nodes").replaceChildren(fragment);
  setText("node-count", `${nodes.length} 個`);
}

function renderSource() {
  const model = state.model, source = state.source, mesh = state.mesh;
  const dl = $("source-detail"); dl.replaceChildren();
  addField(dl, "GPX 識別", source.source_ref);
  addField(dl, "SHA-256", source.sha256);
  addField(dl, "來源身份依據", source.identity_basis || "使用者本機選檔；瀏覽器計算 SHA-256");
  addField(dl, "Workspace 用途", source.workspace_role || "unknown");
  addField(dl, "資料類型", $("source-type").selectedOptions[0].textContent);
  addField(dl, "水平座標", "GPX WGS84 → EPSG:3857 → 路線中心緯度尺度校正的本機展示座標");
  addField(dl, "GPX 垂直基準", "unknown；未與 DEM 高程進行基準換算或差值計算");
  addField(dl, "地形來源", mesh?.status === "ready"
    ? `Scout 已準備 Terrain RGB · 原 DEM ${mesh.source.source_cell_resolution_m} m · ${mesh.source.tile_count} 瓦片`
    : "不可用；目前僅平面位置示意");
  if (mesh?.status === "ready") {
    addField(dl, "DEM 基準 / 取樣", `${mesh.vertical_datum}（coverage metadata）· 原瓦片 bilinear elevation / 0.1 m encoding`);
    addField(dl, "展示網格", `每 ${mesh.sampling.stride_pixels} 像素取 1 點；${mesh.width} × ${mesh.height} 頂點；不增加解析度`);
    addField(dl, "地形準備時間", mesh.source.prepared_at);
    addField(dl, "地形來源指紋", mesh.source.source_fingerprint);
  }
  addField(dl, "視覺高程", `垂直誇張 1×；貼地後抬升 ${VISUAL_RAISE_M} m，只用於看清線條。虛線為無 DEM 的平面位置。`);
  addField(dl, "軌跡處理", "原始有效點全數保留；只增加貼地用顯示頂點。未重新計算或寫回正式指標。");
  addField(dl, "外部底圖", "未啟用；沒有瓦片供應商連線");
  const items = model.warnings.map(warning => {const li = document.createElement("li");li.textContent = warning;return li;});
  $("warnings").replaceChildren(...items);
}

function renderTerrainLegend(mesh) {
  const legend = $("elevation-legend");
  legend.hidden = true;
  $("elevation-stops").replaceChildren();
  if (mesh?.status !== "ready" || ![mesh.minimum_elevation_m, mesh.maximum_elevation_m].every(Number.isFinite) || mesh.minimum_elevation_m > mesh.maximum_elevation_m) return;
  const low = mesh.minimum_elevation_m, high = mesh.maximum_elevation_m;
  const format = height => `${height.toLocaleString("zh-TW", {minimumFractionDigits: 1, maximumFractionDigits: 1})} m`;
  setText("elevation-low", format(low));
  setText("elevation-middle", low === high ? "均一高程" : format((low + high) / 2));
  setText("elevation-high", format(high));
  setText("elevation-datum", `DEM · 垂直基準 ${mesh.vertical_datum || "unknown"}`);
  const stops = ELEVATION_COLOR_STOPS.map(stop => `var(--${low === high ? ELEVATION_COLOR_STOPS[0].token : stop.token}) ${stop.fraction * 100}%`).join(", ");
  const gradient = `linear-gradient(to right in srgb, ${stops})`;
  // Match the reference's RGB interpolation and the renderer's color anchors.
  $("elevation-ramp").style.backgroundImage = CSS.supports("background-image", gradient) ? gradient : `linear-gradient(to right, ${stops})`;
  for (const stop of low === high ? ELEVATION_COLOR_STOPS.slice(0, 1) : ELEVATION_COLOR_STOPS) {
    const row = document.createElement("li"), swatch = document.createElement("i"), label = document.createElement("span"), height = document.createElement("span");
    row.dataset.fraction = String(stop.fraction);
    row.dataset.elevationM = String(low + stop.fraction * (high - low));
    swatch.style.backgroundColor = `var(--${stop.token})`;swatch.setAttribute("aria-hidden", "true");
    label.textContent = `${stop.label} · ${low === high ? "均一高程" : `${Math.round(stop.fraction * 100)}%`}`;
    height.className = "mono";height.textContent = format(Number(row.dataset.elevationM));
    row.append(swatch, label, height);$("elevation-stops").append(row);
  }
  legend.hidden = false;
}

function terrainStatus(mesh, error = null) {
  const host = $("terrain-status");
  if (mesh?.status === "ready" && !error) {
    const points = state.model.points;
    const supported = points.filter(p => meshElevation(mesh, p.lon, p.lat) !== null).length;
    host.dataset.state = "ready";
    host.textContent = `本機 DEM 衍生 3D · 覆蓋 ${supported} / ${points.length} 軌跡點 · 未覆蓋部分以虛線平面定位 · 無外部底圖`;
  } else {
    host.dataset.state = error ? "failed" : "unavailable";
    host.textContent = `地形不可用：${error || mesh?.summary || "未準備"} · 已降級為平面位置示意，無高程、無底圖`;
  }
}

function drawFallback(error) {
  renderTerrainLegend(null);
  state.scene?.dispose();state.scene = null;
  const host = $("map"); host.replaceChildren();host.dataset.renderer = "svg-fallback";
  setText("render-status", "2D 降級");
  terrainStatus(null, error);
  for (const button of document.querySelectorAll(".map-controls button")) button.disabled = true;
  if (!state.model?.bounds) return;
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 1000 600");svg.classList.add("fallback");svg.setAttribute("aria-label", "WebGL 失敗後的平面軌跡示意");
  const bounds = state.model.bounds;
  const scale = Math.min(900 / Math.max(.00001, bounds[1][0] - bounds[0][0]), 450 / Math.max(.00001, bounds[1][1] - bounds[0][1]));
  const xy = p => [500 + (p.lon - (bounds[0][0] + bounds[1][0]) / 2) * scale, 300 - (p.lat - (bounds[0][1] + bounds[1][1]) / 2) * scale];
  fallbackProject = xy;
  for (const segment of state.model.segments) {
    const path = document.createElementNS(ns, "polyline");path.setAttribute("points", segment.points.map(p => xy(p).join(",")).join(" "));
    path.setAttribute("stroke", "var(--accent-2)");path.setAttribute("stroke-width", "3");svg.append(path);
  }
  for (const node of state.model.nodes.filter(n => n.display_supported !== false)) {
    const circle = document.createElementNS(ns, "circle");const [x, y] = xy(node);
    circle.dataset.nodeId = node.id;
    circle.setAttribute("cx", x);circle.setAttribute("cy", y);circle.setAttribute("r", "8");circle.setAttribute("fill", "var(--accent)");circle.setAttribute("tabindex", "0");circle.setAttribute("role", "button");circle.setAttribute("aria-label", node.name);
    circle.addEventListener("click", () => selection.select(node.id));circle.addEventListener("keydown", event => {if (["Enter", " "].includes(event.key)) selection.select(node.id);});svg.append(circle);
  }
  const cursor = document.createElementNS(ns, "circle");cursor.dataset.playbackCursor = "true";
  cursor.setAttribute("r", "7");cursor.setAttribute("fill", "var(--candidate)");cursor.setAttribute("pointer-events", "none");cursor.setAttribute("visibility", "hidden");svg.append(cursor);
  host.append(svg);
}

function pause() {state.playing = false;cancelAnimationFrame(frameId);previousFrame = null;setText("play", "播放");}
function updatePlayback() {
  if (!state.timeline) return;
  const sample = samplePlayback(state.timeline, state.fraction);
  state.scene?.playback(sample.position);
  const cursor = $("map").querySelector("[data-playback-cursor]");
  if (cursor && fallbackProject) {
    cursor.setAttribute("visibility", sample.position ? "visible" : "hidden");
    if (sample.position) {const [x,y] = fallbackProject({lon:sample.position[0],lat:sample.position[1]});cursor.setAttribute("cx",x);cursor.setAttribute("cy",y);}
  }
  $("progress").value = String(Math.round(state.fraction * 10000));
  setText("progress-label", `${(state.fraction * 100).toFixed(1)}%`);
  setText("playback-time", sample.gap ? `區段缺口 · 不插值 · ${sample.time || ""}` : sample.time || "示意進度；不代表真實速度 / ETA");
}
function animate(time) {
  if (!state.playing) return;
  if (previousFrame !== null) {
    const seconds = (time - previousFrame) / 1000;
    const speed = Number($("speed").value);
    const duration = state.timeline.mode === "recorded_time" ? state.timeline.total / speed : speed;
    state.fraction = Math.min(1, state.fraction + seconds / duration);
  }
  previousFrame = time;updatePlayback();
  if (state.fraction >= 1) pause(); else frameId = requestAnimationFrame(animate);
}

async function openSource(source, readBytes, sourceId = null) {
  const generation = ++state.generation;
  renderTerrainLegend(null);
  pause();selection.reset([]);state.model = null;state.timeline = null;state.fraction = 0;
  state.rawBytes = null;state.mesh = null;state.source = null;fallbackProject = null;
  state.scene?.dispose();state.scene = null;$("map").replaceChildren();$("empty-state").hidden = false;
  $("map").dataset.renderer = "";setText("node-count", "0 個");setText("nodes", "正在讀取來源…");
  setText("playback-mode", "讀取軌跡");setText("playback-time", "等待來源");setText("progress-label", "0.0%");$("progress").value = "0";
  setText("cp-status", "");$("warnings").replaceChildren();
  setText("route-stats", "正在讀取來源…");setText("source-detail", "正在確認來源…");
  setText("terrain-status", "正在讀取本機地形…");$("terrain-status").dataset.state = "loading";
  $("source-error").hidden = true;$("node-filter").value = "";setText("render-status", "讀取來源");
  for (const id of ["play", "restart", "progress", "speed", "source-type", "node-filter", "fit", "zoom-in", "zoom-out", "rotate-left", "rotate-right", "tilt"]) $(id).disabled = true;
  try {
    const bytes = await readBytes(); if (generation !== state.generation) return;
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2, "0")).join("");
    if (source.sha256 && source.sha256 !== hash) throw new Error("GPX 與目錄雜湊不同，請重新整理來源。");
    const model = parseGpx(new TextDecoder("utf-8", {fatal: true}).decode(bytes), source.source_ref);
    state.rawBytes = bytes;
    const [meshResult, cpResult] = await Promise.allSettled([
      json("/api/terrain-mesh"), sourceId ? json(`/api/checkpoints/${sourceId}`) : Promise.resolve({nodes: [], summary: "本機選檔未自動關聯 Workspace CP。"}),
    ]);
    if (generation !== state.generation) return;
    const mesh = meshResult.status === "fulfilled" ? meshResult.value : {status: "unavailable", summary: meshResult.reason.message};
    const cps = cpResult.status === "fulfilled" ? cpResult.value : {nodes: [], summary: `CP 讀取失敗：${cpResult.reason.message}`};
    model.nodes.push(...cps.nodes.map(node => ({...node, display_supported: Math.abs(node.lat) <= 85.0511287798066})));
    state.model = model;state.mesh = mesh;state.source = {...source, sha256: hash};state.timeline = buildTimeline(model);
    $("source-type").value = "unknown";$("source-type").disabled = false;$("node-filter").disabled = false;
    setText("type-basis", "來源類型 unknown；Workspace 用途與原始記錄類型分開呈現。");
    setText("route-name", model.name);setText("cp-status", cps.summary);setText("playback-mode", state.timeline.label);setText("playback-reason", state.timeline.reason);
    const recorded = state.timeline.mode === "recorded_time";
    setText("speed-label", recorded ? "時間壓縮倍率" : "示意全程時間");
    $("speed").replaceChildren(...(recorded ? [[1,"1×"],[60,"60×"],[600,"600×"],[3600,"3600×"]] : [[30,"30 秒"],[60,"60 秒"],[120,"120 秒"]]).map(([value, label]) => new Option(label, value)));
    $("speed").value = recorded ? "600" : "60";
    const canPlay = state.timeline.frames.length > 1 && state.timeline.total > 0;
    for (const id of ["play", "restart", "progress", "speed"]) $(id).disabled = !canPlay;
    setText("route-stats", `${model.points.length.toLocaleString()} 個有效來源點　·　${model.source_segment_count} 個原始 segment / ${model.segments.length} 個展示區段　·　${model.nodes.length} 個來源節點　·　GPX 高程缺漏 ${model.missing_elevation_count}`);
    selection.reset(model.nodes);renderNodes();renderSource();terrainStatus(mesh, meshResult.status === "rejected" ? meshResult.reason.message : null);
    $("empty-state").hidden = true;
    try {
      const {TerrainScene} = await import("./renderer.mjs");
      if (generation !== state.generation) return;
      state.scene = new TerrainScene($("map"), {
        onSelect: id => selection.select(id), onFailure: error => drawFallback(error),
        onCamera: camera => setText("camera-readout", `方位 ${camera.bearing.toFixed(0)}° · 傾角 ${camera.pitch.toFixed(0)}°`),
      });
      state.scene.setData(model, mesh);
      renderTerrainLegend(mesh);
      for (const button of document.querySelectorAll(".map-controls button")) button.disabled = false;
      $("tilt").disabled = mesh.status !== "ready";
      setText("render-status", mesh.status === "ready" ? "3D · 本機地形" : "平面示意 · 無 DEM");
    } catch (error) { drawFallback(error.message); }
    updatePlayback();
  } catch (error) {
    if (generation !== state.generation) return;
    state.rawBytes = null;setText("source-error", error.message);$("source-error").hidden = false;
    setText("terrain-status", "沒有有效 GPX；未顯示地形或上一份路線。");$("terrain-status").dataset.state = "unavailable";
    setText("playback-mode", "沒有可回放軌跡");setText("route-stats", "沒有有效軌跡資料");
    setText("render-status", "來源無法讀取");setText("route-name", "請重新選擇 GPX");
    setText("nodes", "沒有可用來源節點。");setText("source-detail", "來源讀取失敗；未呈現上一份軌跡。");
  }
}

let catalog;
$("source-picker").addEventListener("change", () => {
  const source = catalog?.sources.find(s => s.id === $("source-picker").value);
  if (!source) return;
  $("file-picker").value = "";
  openSource(source, async () => {
    const response = await fetch(`/api/gpx/${source.id}`, {cache:"no-store"});
    if (!response.ok) throw new Error(`GPX 讀取失敗 · HTTP ${response.status}`);
    return response.arrayBuffer();
  }, source.id);
});
$("file-picker").addEventListener("change", () => {
  const file = $("file-picker").files[0];if (!file) return;
  $("source-picker").value = "";
  openSource({source_ref: file.name, workspace_role: "local_file", identity_basis:"使用者本機選檔；沒有上傳"}, () => file.arrayBuffer());
});
$("source-type").addEventListener("change", () => {setText("type-basis", $("source-type").value === "unknown" ? "來源類型尚未確認。" : "此類型是使用者本次聲明；沒有寫回來源或成為安全依據。");renderSource();});
$("node-filter").addEventListener("input", renderNodes);
$("play").addEventListener("click", () => {if (state.playing) pause();else {if (state.fraction >= 1) state.fraction = 0;state.playing = true;setText("play", "暫停");frameId = requestAnimationFrame(animate);}});
$("restart").addEventListener("click", () => {pause();state.fraction = 0;updatePlayback();});
$("progress").addEventListener("input", () => {pause();state.fraction = Number($("progress").value) / 10000;updatePlayback();});
$("fit").addEventListener("click", () => state.scene?.fit());
$("zoom-in").addEventListener("click", () => state.scene?.zoom(.8));$("zoom-out").addEventListener("click", () => state.scene?.zoom(1.25));
$("rotate-left").addEventListener("click", () => state.scene?.rotate(-30));$("rotate-right").addEventListener("click", () => state.scene?.rotate(30));$("tilt").addEventListener("click", () => state.scene?.tilt());
document.addEventListener("visibilitychange", () => {if (document.hidden) pause();});
window.addEventListener("pagehide", () => {pause();selection.dispose();state.scene?.dispose();});

// Read-only diagnostics for focused browser proof; this cannot reach runtime APIs.
window.scoutGpx3d = Object.freeze({snapshot: () => ({
  source: state.source, pointCount: state.model?.points.length, sourceSegmentCount: state.model?.source_segment_count,
  segmentCount: state.model?.segments.length, selectedId: selection.current()?.id || null,
  replayMode: state.timeline?.mode, fraction: state.fraction, playing: state.playing,
  terrainStatus: state.mesh?.status, displayLineCount: state.scene?.displayLineCount,
  start: state.model?.points[0], end: state.model?.points.at(-1),
  nodeScreens: state.scene ? [...state.scene.nodes.keys()].map(id => ({id, ...state.scene.screenPosition(id)})) : [],
})});

try {
  catalog = await json("/api/catalog");setText("project-name", catalog.project_id);setText("catalog-status", catalog.summary);
  for (const source of catalog.sources) $("source-picker").add(new Option(`${source.workspace_role === "golden_route_reference" ? "Workspace 主 GPX · " : ""}${source.source_ref}`, source.id));
  // A URL can name an explicit existing source, but cannot supply a path/URL.
  // Otherwise stay at the chooser; do not arbitrarily pick a private trip.
  const requested = new URLSearchParams(location.search).get("gpx");
  if (requested && catalog.sources.some(s => s.id === requested)) {
    $("source-picker").value = requested;$("source-picker").dispatchEvent(new Event("change"));
  }
} catch (error) {setText("catalog-status", `Workspace 目錄不可用：${error.message}。仍可開啟本機 GPX。`);}
