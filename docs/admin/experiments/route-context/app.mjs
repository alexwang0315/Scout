import * as maplibre from "/maplibre/maplibre-gl.mjs";

const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };
const icons = () => window.lucide?.createIcons();
const kinds = {historical: "歷史", cultural: "地方記憶", natural: "自然地景", observation_point: "觀察視角"};
const classes = {
  uncertain: {label: "不確定", color: "#a8b5bd"}, forest: {label: "森林 / 木本植被", color: "#78bf75"},
  grass: {label: "草地 / 低矮植被", color: "#e4ca71"}, bare: {label: "裸露地", color: "#dc989e"},
  water: {label: "可見水體", color: "#7fc4ea"},
};
const state = {data: null, modern: null, historic: null, layer: null, notes: [], selected: null, tab: "stories", profileIndex: 0, ready: false};
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
let feedbackTimer;

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = content;
  if (className) node.className = className;
  return node;
}

function icon(name) {
  const node = element("i"); node.dataset.lucide = name; node.setAttribute("aria-hidden", "true"); return node;
}

function feedback(message) {
  clearTimeout(feedbackTimer); text("app-feedback", message); $("app-feedback").hidden = false;
  feedbackTimer = setTimeout(() => { $("app-feedback").hidden = true; }, 5000);
}

function showEvidence(title, fields, url) {
  text("evidence-title", title); const dl = element("dl");
  for (const [label, value] of fields) {
    dl.append(element("dt", label), element("dd", value ?? "未記錄", label.includes("SHA") ? "hash" : ""));
  }
  $("evidence-body").replaceChildren(dl);
  if (url && /^https?:\/\//.test(url)) {
    const a = element("a", "開啟原始來源"); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
    $("evidence-body").append(a);
  }
  $("evidence-dialog").showModal();
}

function sourceButtons(ids) {
  const row = element("div", undefined, "source-links");
  for (const id of ids || []) {
    const source = state.data.sources.find(item => item.source_id === id);
    if (!source) continue;
    const button = element("button", id); button.type = "button"; button.title = source.title;
    button.append(icon("arrow-up-right"));
    button.addEventListener("click", () => showEvidence(source.title, [
      ["證據編號 / 分級", `${source.source_id} / ${source.tier}`], ["發布時間", source.published_at],
      ["工作區查核時間", source.checked_at], ["本次展示", "使用既有來源記錄；未重新擷取或確認現況"],
      ["來源網址", source.url],
    ], source.url));
    row.append(button);
  }
  return row;
}

function renderStories() {
  const selected = $("story-filter").value; const list = $("story-list"); list.replaceChildren();
  for (const claim of state.data.claims.filter(item => kinds[item.layer] && (selected === "all" || selected === item.layer))) {
    const article = element("article", undefined, "story");
    article.append(element("div", kinds[claim.layer], "story-kind"), element("h3", claim.title), element("p", claim.text), sourceButtons(claim.source_ids));
    list.append(article);
  }
  if (!list.children.length) list.append(element("p", "此主題尚無來源記錄。", "empty"));
  icons();
}

function selectPublic(point) {
  if (!point.position_allowed || !point.coordinates || !state.ready) return;
  state.modern.easeTo({center: point.coordinates, zoom: 13.7, duration: reducedMotion ? 0 : 650});
  highlight(point.coordinates, `${point.label} · 公開候選點，尚未人工確認`);
}

function renderPlaces() {
  const list = $("place-list"); list.replaceChildren();
  const restricted = state.data.points.filter(p => !p.position_allowed).length;
  text("sensitivity-summary", `${restricted} 個地點依原有文化審核政策保留名稱，不提供座標或里程定位。`);
  for (const point of state.data.points) {
    const article = element("article", undefined, "place-row"); const heading = element("div", undefined, "place-heading");
    heading.append(element("h3", point.label));
    if (point.position_allowed) {
      const button = element("button", undefined, "icon-button"); button.title = `定位 ${point.label}`; button.setAttribute("aria-label", button.title);
      button.append(icon("map-pin")); button.addEventListener("click", () => selectPublic(point)); heading.append(button);
    }
    const status = element("div", undefined, "place-state");
    status.append(icon(point.position_allowed ? "circle-help" : "lock-keyhole"), element("span", point.position_allowed ? "公開候選座標 · 待審核" : "文化審核中 · 座標未公開"));
    article.append(heading, element("p", point.aliases.join(" / ") || "原始名稱"), status, element("p", `來源分級 ${point.source_tier} · 工作區地點候選集`, "meta")); list.append(article);
  }
  icons();
}

function switchTab(tab, focus = false) {
  state.tab = tab;
  for (const button of document.querySelectorAll("[data-tab]")) {
    const selected = button.dataset.tab === tab;
    button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
    $(`panel-${button.dataset.tab}`).hidden = !selected;
    if (selected && focus) button.focus();
  }
  if (tab === "research" || tab === "notes") setComparison(0);
  else if (+$("comparison").value === 0) setComparison(52);
  text("map-heading", tab === "notes" || tab === "research" ? "影像觀察" : "古今對照");
  state.modern?.getCanvas().style.setProperty("cursor", tab === "notes" ? "crosshair" : "");
}

function setComparison(value) {
  $("comparison").value = value;
  text("comparison-value", `${value} / ${100 - value}`);
  $("historic-clip").style.clipPath = `inset(0 ${100 - value}% 0 0)`;
  $("comparison-divider").style.left = `${value}%`;
  $("comparison-divider").hidden = value === 0 || value === 100;
  $("historic-caption").hidden = value === 0;
  $("modern-caption").hidden = value === 100;
  $("map-captions")?.classList.toggle("imagery-only", value === 0);
}

function updateLayer() {
  state.layer = state.data.layers.find(layer => layer.id === $("era").value);
  for (const layer of state.data.layers.filter(item => item.year)) {
    state.historic.setLayoutProperty(layer.id, "visibility", layer.id === state.layer.id ? "visible" : "none");
  }
  text("historic-caption", `${state.layer.year} · ${state.layer.title}`);
  text("map-source", `${state.layer.year}：${state.layer.attribution} / 正射：NLSC`);
  text("coverage-status", state.layer.no_coverage_tiles ? "本圖幅含缺圖區；空白不代表地物不存在" : "本機圖磚 · 非即時影像");
  if (+$("comparison").value === 0) setComparison(52);
}

function fitRoute() {
  const b = state.data.route.bounds;
  state.modern.fitBounds([[b[0], b[1]], [b[2], b[3]]], {padding: {top: 62, bottom: 54, left: 35, right: 35}, duration: reducedMotion ? 0 : 500});
}

function highlight(coordinates, label) {
  const feature = {type: "Feature", properties: {}, geometry: {type: "Point", coordinates}};
  for (const map of [state.modern, state.historic]) map?.getSource("selection")?.setData(feature);
  text("selection-caption", label); $("selection-caption").hidden = false;
}

function noteFeatures() {
  return {type: "FeatureCollection", features: state.notes.map(note => ({type: "Feature", geometry: {type: "Point", coordinates: note.coordinates}, properties: {color: classes[note.class_id].color, id: note.id}}))};
}

function createStyle(historical) {
  const sources = {}, layers = [{id: "background", type: "background", paint: {"background-color": historical ? "#d4d5c9" : "#29312d"}}];
  for (const layer of state.data.layers.filter(item => historical ? item.year : !item.year)) {
    sources[layer.id] = {type: "raster", tiles: [location.origin + layer.tile_url], tileSize: 256, minzoom: layer.minzoom, maxzoom: layer.maxzoom, bounds: layer.bounds};
    layers.push({id: layer.id, type: "raster", source: layer.id, layout: {visibility: !historical || layer.id === state.layer.id ? "visible" : "none"}, paint: {"raster-fade-duration": 0}});
  }
  sources.route = {type: "geojson", data: {type: "Feature", properties: {}, geometry: state.data.route.geometry}};
  layers.push({id: "route-outline", type: "line", source: "route", paint: {"line-color": "#16313a", "line-width": 5, "line-opacity": .85}});
  layers.push({id: "route-line", type: "line", source: "route", paint: {"line-color": "#62dce7", "line-width": 2.4}});
  sources.places = {type: "geojson", data: {type: "FeatureCollection", features: state.data.points.filter(p => p.position_allowed).map(p => ({type: "Feature", geometry: {type: "Point", coordinates: p.coordinates}, properties: {id: p.id}}))}};
  layers.push({id: "place-points", type: "circle", source: "places", paint: {"circle-radius": 6, "circle-color": "#efc575", "circle-stroke-color": "#1c262a", "circle-stroke-width": 2}});
  sources.notes = {type: "geojson", data: noteFeatures()};
  layers.push({id: "note-points", type: "circle", source: "notes", paint: {"circle-radius": 6, "circle-color": ["get", "color"], "circle-stroke-color": "#172025", "circle-stroke-width": 2}});
  sources.selection = {type: "geojson", data: {type: "FeatureCollection", features: []}};
  layers.push({id: "selected-point", type: "circle", source: "selection", paint: {"circle-radius": 9, "circle-color": "#ffffff", "circle-opacity": .25, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2}});
  return {version: 8, sources, layers};
}

async function createMaps() {
  maplibre.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
  const bounds = state.data.layers.find(l => l.id === "imagery").bounds;
  const options = {center: [121.1, 23.44], zoom: 10.5, minZoom: 9, maxZoom: 15,
    // Camera bounds need room for fitBounds padding at wide and narrow aspects.
    maxBounds: [[bounds[0] - .4, bounds[1] - .4], [bounds[2] + .4, bounds[3] + .4]],
    attributionControl: false, dragRotate: false, pitchWithRotate: false, touchPitch: false,
    canvasContextAttributes: {preserveDrawingBuffer: true}, renderWorldCopies: false};
  state.modern = new maplibre.Map({...options, container: "modern-map", style: createStyle(false)});
  state.historic = new maplibre.Map({...options, container: "historic-map", style: createStyle(true), interactive: false});
  state.modern.touchZoomRotate.disableRotation();
  state.modern.addControl(new maplibre.NavigationControl({showCompass: false}), "top-right");
  state.modern.addControl(new maplibre.ScaleControl({maxWidth: 72, unit: "metric"}), "bottom-right");
  state.modern.on("move", () => state.historic.jumpTo({center: state.modern.getCenter(), zoom: state.modern.getZoom(), bearing: state.modern.getBearing(), pitch: state.modern.getPitch()}));
  const ready = map => new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("地圖載入逾時，請重新整理；未改動工作區")), 60000);
    map.once("load", () => { clearTimeout(timeout); resolve(); });
    map.on("error", event => { text("coverage-status", "圖磚載入異常 / 無覆蓋"); console.warn("Map evidence unavailable:", event.error?.message); });
  });
  const modernReady = ready(state.modern), historicalReady = ready(state.historic);
  await modernReady; await historicalReady;
  state.ready = true; $("map-frame").dataset.ready = "true"; $("map-loading").hidden = true;
  fitRoute(); updateLayer();
  state.modern.on("click", event => {
    if (state.tab === "notes") { choosePosition(event.lngLat.toArray()); return; }
    const hit = state.modern.queryRenderedFeatures(event.point, {layers: ["place-points"]})[0];
    if (hit) { switchTab("places"); selectPublic(state.data.points.find(p => p.id === hit.properties.id)); }
  });
}

function storageKey() { return `scout.route-context.notes.v1.${state.data.project_id}.${state.data.route.sha256}`; }

function insideBounds(coordinates) {
  if (!Array.isArray(coordinates) || coordinates.length !== 2 || !coordinates.every(Number.isFinite)) return false;
  const [x, y] = coordinates, b = state.data.layers.find(l => l.id === "imagery").bounds;
  return x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];
}

function loadNotes() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey()) || "[]");
    if (!Array.isArray(saved)) throw new Error("觀察格式不符");
    state.notes = saved.filter(n => n && typeof n.id === "string" && Object.hasOwn(classes, n.class_id) && insideBounds(n.coordinates)
      && typeof n.text === "string" && typeof n.created_at === "string" && Number.isFinite(n.chainage_m) && Number.isFinite(n.offset_m));
  } catch { feedback("本機觀察無法讀取；原有資料未覆寫"); }
}

function persistNotes(next) {
  try { localStorage.setItem(storageKey(), JSON.stringify(next)); state.notes = next; return true; }
  catch { text("note-feedback", "本機儲存失敗；請確認瀏覽器儲存空間與權限"); return false; }
}

function nearestRoute(coordinates) {
  const location = new maplibre.LngLat(...coordinates); let best = null;
  for (const p of state.data.route.profile) {
    const distance = location.distanceTo(new maplibre.LngLat(p[2], p[3]));
    if (!best || distance < best.offset_m) best = {chainage_m: p[0], offset_m: distance};
  }
  return {chainage_m: Math.round(best.chainage_m), offset_m: Math.round(best.offset_m)};
}

function choosePosition(coordinates) {
  if (!state.ready) return;
  if (!insideBounds(coordinates)) { feedback("選取位置超出本區影像範圍"); return; }
  setComparison(0);
  state.selected = {coordinates: coordinates.map(v => +v.toFixed(7)), ...nearestRoute(coordinates)};
  const p = state.selected;
  text("note-position", `${p.coordinates[1].toFixed(5)}, ${p.coordinates[0].toFixed(5)}\n近 GPX ${(p.chainage_m / 1000).toFixed(2)} km · 離最近軌跡點 ${p.offset_m} m`);
  $("save-note").disabled = false;
  highlight(p.coordinates, "新的影像觀察 · 尚未儲存");
  text("note-feedback", "");
}

function startNote() {
  switchTab("notes", true);
  if (state.ready) choosePosition(state.modern.getCenter().toArray());
  if (matchMedia("(max-width: 780px)").matches) $("context-panel").scrollIntoView({behavior: reducedMotion ? "instant" : "smooth", block: "start"});
}

function saveNote(event) {
  event.preventDefault(); if (!state.selected) return;
  const imagery = state.data.layers.find(l => l.id === "imagery");
  const note = {id: crypto.randomUUID(), created_at: new Date().toISOString(), ...state.selected,
    class_id: $("note-class").value, text: $("note-text").value.trim(),
    source_id: imagery.source_id, imagery_manifest_sha256: imagery.sha256, image_acquired_at: null,
    label_source: "human_visual_rgb", review_state: "unreviewed", independent_ground_truth: false,
    zoom: +state.modern.getZoom().toFixed(2), candidate_only: true, runtime_safety_truth: false};
  if (!persistNotes([...state.notes, note])) return;
  renderNotes(); $("note-text").value = ""; state.selected = null; $("save-note").disabled = true;
  text("note-position", "尚未選取下一個位置"); text("note-feedback", "已儲存本機草稿；工作區與模型資料未變更");
  highlight(note.coordinates, `${classes[note.class_id].label} · 人工 RGB 觀察，未審核`);
}

function renderNotes() {
  text("note-count", state.notes.length); text("saved-count", state.notes.length); $("export-notes").disabled = !state.notes.length;
  const list = $("note-list"); list.replaceChildren();
  if (!state.notes.length) list.append(element("p", "尚無本機觀察。", "empty"));
  for (const note of [...state.notes].reverse()) {
    const article = element("article", undefined, "note-row"); const h = element("h3", classes[note.class_id].label); h.style.color = classes[note.class_id].color;
    article.append(h, element("p", note.text || "無文字記錄"), element("p", `近 GPX ${(note.chainage_m / 1000).toFixed(2)} km · 離最近軌跡點 ${note.offset_m} m`, "meta"));
    const actions = element("div", undefined, "note-actions"); actions.append(element("span", "本機草稿 · 未審核"));
    for (const [name, title, action] of [["map-pin", "定位觀察", () => { state.modern.easeTo({center: note.coordinates, zoom: 14, duration: reducedMotion ? 0 : 500}); highlight(note.coordinates, `${classes[note.class_id].label} · 本機草稿`); }],
      ["trash-2", "刪除此觀察", () => { if (persistNotes(state.notes.filter(n => n.id !== note.id))) { renderNotes(); feedback("已刪除此本機觀察"); } }]]) {
      const b = element("button", undefined, "icon-button"); b.title = title; b.setAttribute("aria-label", title); b.append(icon(name)); b.addEventListener("click", action); actions.append(b);
    }
    article.append(actions); list.append(article);
  }
  const distribution = $("label-distribution"); distribution.replaceChildren();
  for (const [key, value] of Object.entries(classes)) {
    const count = state.notes.filter(n => n.class_id === key).length;
    const row = element("div", undefined, "distribution-row"), swatch = element("i"); swatch.style.background = value.color;
    row.append(swatch, element("span", value.label), element("b", `${count} 筆`)); distribution.append(row);
  }
  for (const map of [state.modern, state.historic]) map?.getSource("notes")?.setData(noteFeatures());
  icons();
}

function download(name, value) {
  const blob = new Blob([JSON.stringify(value, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob), a = element("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportNotes() {
  download(`${state.data.project_id}.observations.json`, {
    schema_version: "route_context_visual_observations.v1", project_id: state.data.project_id,
    route_sha256: state.data.route.sha256, created_at: new Date().toISOString(),
    candidate_only: true, runtime_safety_truth: false, independent_ground_truth: false,
    model_inference_executed: false, evaluation_eligible: false, image_pairing: null,
    coordinate_system: "EPSG:4326", chainage_method: "nearest primary GPX vertex; not snapped", observations: state.notes,
  });
  feedback("觀察 JSON 已送交瀏覽器下載；不含模型結果");
}

function drawProfile() {
  if (!state.data) return;
  const canvas = $("elevation-profile"), ctx = canvas.getContext("2d"), w = canvas.clientWidth, h = 104, dpr = devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); ctx.scale(dpr, dpr);
  const route = state.data.route, profile = route.profile, max = route.elevation_max_m || 1;
  const x = p => 36 + (p[0] / route.distance_m) * (w - 44), y = p => h - 8 - ((p[1] ?? 0) / (max * 1.08)) * (h - 18);
  ctx.font = "10px monospace";
  for (const elevation of [1000, 2000, 3000]) {
    const yy = y([0, elevation]); ctx.strokeStyle = "#33404a"; ctx.lineWidth = .6; ctx.beginPath(); ctx.moveTo(33, yy); ctx.lineTo(w, yy); ctx.stroke(); ctx.fillStyle = "#a8b5bd"; ctx.fillText(String(elevation), 0, yy + 3);
  }
  ctx.strokeStyle = "#62b5c4"; ctx.lineWidth = 1.7; ctx.beginPath(); let previous;
  for (const p of profile) {
    if (p[1] === null) { previous = null; continue; }
    if (previous && previous[4] === p[4]) ctx.lineTo(x(p), y(p)); else ctx.moveTo(x(p), y(p)); previous = p;
  }
  ctx.stroke(); const selected = profile[state.profileIndex];
  ctx.strokeStyle = "#bba15e"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x(selected), 4); ctx.lineTo(x(selected), h); ctx.stroke();
  if (selected[1] !== null) { ctx.fillStyle = "#efd591"; ctx.beginPath(); ctx.arc(x(selected), y(selected), 3.5, 0, Math.PI * 2); ctx.fill(); }
}

function setProfilePosition() {
  const target = +$("route-position").value / 1000 * state.data.route.distance_m;
  let index = state.data.route.profile.findIndex(p => p[0] >= target); if (index < 0) index = state.data.route.profile.length - 1;
  state.profileIndex = index; const p = state.data.route.profile[index];
  const label = `${(p[0] / 1000).toFixed(2)} km · ${p[1] === null ? "高程未知" : `${Math.round(p[1])} m`}`;
  text("profile-position", label); highlight([p[2], p[3]], `GPX 記錄位置 · ${label}`); drawProfile();
}

function bindControls() {
  for (const button of document.querySelectorAll("[data-tab]")) {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
    button.addEventListener("keydown", event => {
      const buttons = [...document.querySelectorAll("[data-tab]")], index = buttons.indexOf(button);
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        switchTab(buttons[next].dataset.tab, true);
      }
    });
  }
  $("story-filter").addEventListener("change", renderStories);
  $("comparison").addEventListener("input", () => setComparison(+$("comparison").value));
  $("era").addEventListener("change", updateLayer);
  $("fit-route").addEventListener("click", () => { if (state.ready) fitRoute(); });
  $("focus-public").addEventListener("click", () => { const p = state.data.points.find(p => p.position_allowed); if (p) { switchTab("places"); selectPublic(p); } });
  $("route-toggle").addEventListener("change", () => {
    if (!state.ready) return; const visibility = $("route-toggle").checked ? "visible" : "none";
    for (const map of [state.modern, state.historic]) for (const id of ["route-line", "route-outline"]) map.setLayoutProperty(id, "visibility", visibility);
  });
  $("map-evidence").addEventListener("click", () => showEvidence(`${state.layer.year} ${state.layer.title}`, [
    ["來源", state.layer.attribution], ["圖幅年代", state.layer.year], ["快取記錄時間（非拍攝時間）", state.layer.cached_at],
    ["缺圖數（來源 manifest）", state.layer.no_coverage_tiles], ["來源檔案", state.layer.source_ref],
    ["Manifest SHA-256", state.layer.sha256], ["判讀限制", "歷史地圖可能有測繪及配準誤差；GPX 為現代記錄，不是已確認的古道路線。"],
  ]));
  $("start-note").addEventListener("click", startNote); $("research-add").addEventListener("click", startNote);
  $("pick-position").addEventListener("click", () => { if (state.ready) choosePosition(state.modern.getCenter().toArray()); });
  $("note-form").addEventListener("submit", saveNote); $("export-notes").addEventListener("click", exportNotes);
  $("export-evidence").addEventListener("click", () => download(`${state.data.project_id}.evidence-index.json`, {
    schema_version: "route_context_demo_evidence.v1", project_id: state.data.project_id, boundary: state.data.boundary,
    provenance: state.data.provenance, route: {source_ref: state.data.route.source_ref, sha256: state.data.route.sha256},
    sources: state.data.sources, layers: state.data.layers, research: state.data.research,
  }));
  $("close-evidence").addEventListener("click", () => $("evidence-dialog").close());
  $("route-position").addEventListener("input", setProfilePosition);
  new ResizeObserver(drawProfile).observe($("elevation-profile"));
}

async function init() {
  icons();
  try {
    const response = await fetch("/api/context", {cache: "no-store"}); if (!response.ok) throw new Error(`證據讀取失敗 HTTP ${response.status}`);
    state.data = await response.json();
    const data = state.data, route = data.route, histories = data.layers.filter(l => l.year);
    if (!histories.length || !data.layers.some(l => l.id === "imagery")) throw new Error("工作區缺少歷史圖幅或正射影像快取");
    state.layer = histories.find(l => l.year === "1916") || histories[0];
    text("route-direction", data.identity.direction); text("workspace-id", data.project_id);
    text("route-distance", `${(route.distance_m / 1000).toFixed(2)} km`);
    text("route-elevation", route.elevation_min_m === null ? "未記錄" : `${Math.round(route.elevation_min_m)}–${Math.round(route.elevation_max_m)} m`);
    const localDate = value => value ? new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date(value)) : "未知";
    text("route-period", `${localDate(route.started_at)} → ${localDate(route.ended_at)}`);
    text("closure-status", `${data.status_snapshot.label || "工作區未記錄開放狀態"}；本次未重新查核`);
    text("identity-summary", data.identity.explanation); $("identity-sources").replaceChildren(sourceButtons(data.identity.source_ids));
    text("gee-feature-count", `${data.research.raw_feature_count} 筆`);
    text("gee-status", `工作區 GEE：${data.research.gee_status} · 原始特徵 ${data.research.raw_feature_count} 筆；本次未發出 GEE 請求。`);
    $("era").replaceChildren(...histories.map(layer => { const option = element("option", `${layer.year} · ${layer.title}`); option.value = layer.id; return option; }));
    $("era").value = state.layer.id;
    loadNotes(); renderStories(); renderPlaces(); renderNotes(); bindControls(); drawProfile(); icons();
    await createMaps(); $("era").disabled = false;
  } catch (error) {
    console.error(error); text("map-loading", error.message || "展示載入失敗"); $("map-loading").hidden = false;
  }
}

await init();
