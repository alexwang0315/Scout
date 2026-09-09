/* Permission Human Design: versioned candidate geometry and planned itinerary.
 * All geometry is returned by the deterministic compiler. This view never fills
 * gaps or writes a route, review, or analysis selection without a visible action.
 */
(function (global) {
  "use strict";
  const array = value => Array.isArray(value) ? value : [];
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const compact = value => typeof value === "string" ? value : JSON.stringify(value ?? "");
  const copy = value => JSON.parse(JSON.stringify(value));
  const number = (value, unit = "") => value == null || !Number.isFinite(Number(value)) ? "未知" : `${Number(value).toFixed(1)}${unit}`;
  const hash = value => String(value || "").slice(0, 16) || "未提供";
  const button = (action, label, enabled = true, extra = "") => `<button type="button" class="permission-button" data-planned-action="${action}" ${enabled ? "" : "disabled"} ${extra}>${label}</button>`;
  let host = null;
  let epoch = 0;
  let current = freshState("");

  function freshState(projectId) {
    return {projectId, epoch: ++epoch, inputRevision: 0, catalogStatus: "idle", catalog: null,
      versions: [], headVersionId: null, selection: null, versionId: "", saved: null, compareId: "", compare: null,
      preview: null, previewRevision: -1, request: null, previewStatus: "尚未預覽",
      status: "選擇來源與行程差異，先預覽幾何與節奏。", busy: false,
      text: "", departure: "", timezone: "+08:00", speed: "", paceMode: "source_preferred", operations: [], selections: [],
      nameResolutions: {}, reviewChecks: {}, reviewIssues: {}, keys: {}, focusAnchor: "",
      anchorScope: "route", anchorQuery: "", anchorPage: 0, pages: {}, tableViews: new Map(), exportResults: {},
      bbox: {south: "", west: "", north: "", east: ""},
      editor: {kind: "stop", at: "", to: "", visit: "", toVisit: "", duration: "40", departure: "",
        sourceId: "", partIndex: "0", sourceFrom: "", sourceTo: "", roundTrip: true, label: "", sourceText: "",
        trailSearch: false, trailFrom: "", trailTo: "", trailVia: []}};
  }

  function ensureProject(projectId) {
    if (String(projectId || "") !== current.projectId) current = freshState(String(projectId || ""));
    return current;
  }

  function live(state, inputRevision = null) {
    return current === state && state.epoch === epoch && (!host || host.projectId() === state.projectId)
      && (inputRevision === null || inputRevision === state.inputRevision);
  }

  function refresh() { if (host) host.render(); }
  function path(state, suffix) { return `/admin/pretrip/projects/${encodeURIComponent(state.projectId)}/planned-route/${suffix}`; }
  function key(state, kind, binding) {
    const id = `${kind}:${binding}`;
    // Reuse a command identity after a timeout or an uncertain HTTP response.
    if (!state.keys[id]) state.keys[id] = `planned-${kind}-${binding}`;
    return state.keys[id];
  }
  function changed(state, renderNow = true) {
    state.inputRevision += 1;
    state.previewStatus = "輸入已變更：前次預覽與審查已過期，請重新預覽。";
    state.reviewChecks = {};
    state.reviewIssues = {};
    if (renderNow) refresh();
    else updateButtons(state);
  }
  function validPreview(state) { return Boolean(state.preview && state.previewRevision === state.inputRevision); }
  function reviewIssues(preview) {
    return array(preview?.review_required_issue_ids || preview?.required_issue_ids || preview?.review_requirements?.required_issue_ids);
  }
  function manifest(state) { return state.saved?.manifest || state.saved || {}; }
  function manifestSha(state) { return state.saved?.manifest_sha256 || manifest(state).manifest_sha256 || ""; }
  function version(state) { return state.saved?.version_id || manifest(state).version_id || ""; }
  function sourceCurrent(state) { return !["stale", "changed", "invalid"].includes(state.saved?.source_status?.status || state.saved?.source_status); }
  function savedMatches(state) {
    const savedPreview = state.saved?.preview || {};
    return validPreview(state) && version(state) && manifestSha(state)
      && (!savedPreview.preview_sha256 || savedPreview.preview_sha256 === state.preview.preview_sha256) && sourceCurrent(state);
  }
  function reviewed(state) {
    const review = state.saved?.review;
    return savedMatches(state) && Boolean(review && (review.status === "reviewed" || review.status === "accepted"
      || review.status === "reviewed_planning_candidate" || review.review_status === "reviewed" || review.accepted === true || review.review_sha256));
  }
  function canReview(state) {
    return savedMatches(state) && ["sources", "geometry", "timing", "uncertainty"].every(name => state.reviewChecks[name] === true)
      && reviewIssues(state.preview).every(id => state.reviewIssues[id] === true);
  }
  function canSave(state) {
    return validPreview(state) && Boolean(state.preview.preview_sha256)
      && (!state.saved || state.saved?.preview?.preview_sha256 !== state.preview.preview_sha256 || sourceCurrent(state))
      && state.preview.save_allowed !== false && state.preview.valid !== false
      && !["blocked", "invalid", "unresolved"].includes(state.preview.status);
  }
  function updateButtons(state) {
    const container = global.document?.querySelector("[data-planned-workbench]");
    if (!container) return;
    const enabled = {preview: Boolean(state.catalog), save: canSave(state), review: canReview(state),
      select: reviewed(state), restore: Boolean(state.versionId), compare: Boolean(state.compareId),
      refresh: true, golden: true, overpass: Boolean(state.catalog), "add-operation": Boolean(state.catalog), "append-segment": Boolean(state.catalog)};
    container.querySelectorAll("[data-planned-action]").forEach(element => {
      if (Object.hasOwn(enabled, element.dataset.plannedAction)) element.disabled = state.busy || !enabled[element.dataset.plannedAction];
    });
    container.querySelectorAll("[data-planned-export]").forEach(element => {
      element.disabled = state.busy || !version(state) || !manifestSha(state);
    });
    container.querySelectorAll("[data-planned-review-check], [data-planned-review-issue], [data-planned-review-all-issues]").forEach(element => {
      element.disabled = state.busy || !savedMatches(state);
      if (element.dataset.plannedReviewCheck) element.checked = Boolean(state.reviewChecks[element.dataset.plannedReviewCheck]);
      if (element.dataset.plannedReviewIssue) element.checked = Boolean(state.reviewIssues[element.dataset.plannedReviewIssue]);
      if (element.hasAttribute("data-planned-review-all-issues")) element.checked = reviewIssues(state.preview).every(id => state.reviewIssues[id] === true);
    });
    const reviewCount = container.querySelector("[data-planned-review-issue-count]");
    if (reviewCount) reviewCount.textContent = `已確認 ${reviewIssues(state.preview).filter(id => state.reviewIssues[id] === true).length} / ${reviewIssues(state.preview).length} 筆版本限制`;
    const status = container.querySelector("[data-planned-preview-status]");
    if (status) status.textContent = state.previewStatus;
  }

  function catalogSources(state) { return array(state.catalog?.sources); }
  function anchors(state) { return array(state.catalog?.anchors); }
  function anchorId(anchor) { return String(anchor.anchor_id || anchor.candidate_id || anchor.checkpoint_id || anchor.id || anchor.name || anchor.label || ""); }
  function anchorLabel(anchor) { return String(anchor.label || anchor.name || anchor.display_label || anchorId(anchor)); }
  function visibleAnchors(state) {
    const selectedSources = new Set([state.catalog?.golden_source_id || "golden",
      ...state.operations.map(operation => operation.selection?.source_id),
      ...state.selections.map(selection => selection.source_id)]);
    const query = state.anchorQuery.trim().toLocaleLowerCase();
    const matches = anchors(state).filter(anchor => (state.anchorScope === "all"
      || (state.anchorScope === "route" ? selectedSources.has(anchor.source_id) : anchor.source_id === state.anchorScope))
      && (!query || `${anchorLabel(anchor)} ${anchorId(anchor)} ${array(anchor.aliases).join(" ")}`.toLocaleLowerCase().includes(query)));
    const lastPage = Math.max(0, Math.ceil(matches.length / 100) - 1);
    state.anchorPage = Math.min(lastPage, Math.max(0, state.anchorPage));
    return {all: matches, page: matches.slice(state.anchorPage * 100, (state.anchorPage + 1) * 100), lastPage};
  }
  function anchorOptions(state, selected, empty = "請選擇") {
    const visible = visibleAnchors(state).page;
    const selectedAnchor = anchors(state).find(anchor => anchorId(anchor) === selected);
    const items = selectedAnchor && !visible.some(anchor => anchorId(anchor) === selected) ? [selectedAnchor, ...visible] : visible;
    return options(items, selected, anchorId, anchor => `${anchorLabel(anchor)} · ${anchor.source_id || ""}`, empty);
  }
  function options(items, selected, value, label, empty = "請選擇") {
    return `<option value="">${escape(empty)}</option>` + items.map(item => `<option value="${escape(value(item))}" ${String(value(item)) === String(selected) ? "selected" : ""}>${escape(label(item))}</option>`).join("");
  }
  function sourceParts(source) {
    return array(source?.parts || source?.segments).map((part, index) => Array.isArray(part)
      ? {part_index: index, point_count: part.length, points: part} : part);
  }
  function sourceId(source) { return String(source.source_id || source.id || ""); }
  function editorSource(state) { return catalogSources(state).find(item => sourceId(item) === state.editor.sourceId); }
  function editorPart(state) { return sourceParts(editorSource(state)).find((part, index) => Number(part.part_index ?? index) === Number(state.editor.partIndex)); }
  function sourceAnchors(state) {
    const source = editorSource(state);
    const part = editorPart(state);
    const own = array(part?.anchors).length ? part.anchors : array(source?.anchors).length ? source.anchors : anchors(state);
    const mapped = own.flatMap(anchor => {
      const locations = array(anchor.locations || anchor.source_locations);
      if (locations.length) return locations.filter(location => location.source_id === state.editor.sourceId
        && Number(location.part_index) === Number(state.editor.partIndex)).map(location => ({...anchor, ...location}));
      if (anchor.source_id && anchor.source_id !== state.editor.sourceId) return [];
      if (anchor.part_index != null && Number(anchor.part_index) !== Number(state.editor.partIndex)) return [];
      return anchor.point_index != null ? [anchor] : [];
    });
    // A source part's actual first and last points are also usable endpoints;
    // the operator chooses an endpoint label, never types arbitrary coordinates.
    const points = array(part?.points);
    [0, points.length - 1].filter((index, i, list) => index >= 0 && list.indexOf(index) === i).forEach(index => {
      if (mapped.some(anchor => Number(anchor.point_index) === index)) return;
      mapped.push({anchor_id: `source-endpoint:${state.editor.sourceId}:${state.editor.partIndex}:${index}`,
        label: index === 0 ? "此來源段起點" : "此來源段終點", source_id: state.editor.sourceId,
        part_index: Number(state.editor.partIndex), point_index: index, ...points[index]});
    });
    return mapped.sort((a, b) => Number(a.point_index) - Number(b.point_index));
  }
  function selectionFromEditor(state) {
    const editor = state.editor;
    if (editor.trailSearch) {
      if (!editor.trailFrom || !editor.trailTo) throw new Error("請選擇山徑搜尋的起點與終點。");
      return {source_id: editor.sourceId || "", round_trip: Boolean(editor.roundTrip),
        trail_search: {start_anchor_id: editor.trailFrom, end_anchor_id: editor.trailTo, via_anchor_ids: editor.trailVia}};
    }
    const endpoints = sourceAnchors(state);
    const from = endpoints.find(item => `${anchorId(item)}:${item.point_index}` === editor.sourceFrom);
    const to = endpoints.find(item => `${anchorId(item)}:${item.point_index}` === editor.sourceTo);
    if (!editor.sourceId || !from || !to) throw new Error("請選擇來源、來源段，以及該段可定位的起點與終點。");
    return {source_id: editor.sourceId, part_index: Number(editor.partIndex), start_index: Number(from.point_index),
      end_index: Number(to.point_index), round_trip: Boolean(editor.roundTrip)};
  }
  function dateTime(value, offset) {
    if (!value) return null;
    if (!/^[+-]\d{2}:\d{2}$/.test(offset)) throw new Error("請提供明確時區，例如 +08:00。");
    return `${value.length === 16 ? `${value}:00` : value}${offset}`;
  }
  function buildRequest(state) {
    const result = {human_text: state.text, source_snapshot_sha256: state.catalog?.source_snapshot_sha256,
      operations: copy(state.operations), route_selections: copy(state.selections), pace_mode: state.paceMode};
    if (state.departure) result.departure_at = dateTime(state.departure, state.timezone);
    if (state.speed !== "") result.default_speed_kmh = Number(state.speed);
    if (version(state) || state.headVersionId) result.parent_version_id = version(state) || state.headVersionId;
    if (Object.keys(state.nameResolutions).length) result.name_resolutions = copy(state.nameResolutions);
    return result;
  }
  function addOperation(state, selectionOnly = false) {
    const editor = state.editor;
    if (selectionOnly) { state.selections.push(selectionFromEditor(state)); changed(state); return; }
    const operation = {kind: editor.kind};
    if (editor.at) operation.at = editor.at;
    if (editor.to) operation.to = editor.to;
    if (editor.visit !== "") operation.visit = Number(editor.visit);
    if (editor.toVisit !== "") operation.to_visit = Number(editor.toVisit);
    if (editor.label) operation.label = editor.label;
    if (editor.sourceText.trim()) operation.source_text = editor.sourceText.trim();
    if (["branch", "replace"].includes(editor.kind)) operation.selection = selectionFromEditor(state);
    if (["stop", "camp"].includes(editor.kind) && editor.duration !== "") operation.duration_minutes = Number(editor.duration);
    if (["depart", "camp"].includes(editor.kind) && editor.departure) operation.departure_at = dateTime(editor.departure, state.timezone);
    if (editor.kind === "deadline" && editor.departure) operation.latest_arrival_at = dateTime(editor.departure, state.timezone);
    state.operations.push(operation);
    changed(state);
  }

  function geoLines(value) {
    if (!value) return [];
    if (value.type === "FeatureCollection") return array(value.features).flatMap(geoLines);
    if (value.type === "Feature") return geoLines(value.geometry).map(line => ({...line, properties: value.properties || {}}));
    if (value.type === "LineString") return [{coordinates: array(value.coordinates), properties: {}}];
    if (value.type === "MultiLineString") return array(value.coordinates).map(coordinates => ({coordinates, properties: {}}));
    if (value.type === "GeometryCollection") return array(value.geometries).flatMap(geoLines);
    return [];
  }
  function geometry(preview) { return preview?.geojson || preview?.route_geojson || preview?.planned_geojson || preview?.geometry?.geojson; }
  function goldenGeometry(preview, catalog) { return preview?.golden_geojson || catalog?.golden_geojson || catalog?.golden_route_geojson; }
  function mapAnchors(state, preview) {
    const ids = new Set([state.focusAnchor, ...Object.values(state.nameResolutions),
      ...state.operations.flatMap(operation => [operation.at, operation.to])].filter(Boolean));
    return [...array(preview?.checkpoints), ...anchors(state).filter(anchor => ids.has(anchorId(anchor)))];
  }
  function mapHtml(planned, golden, points = [], mapId = "preview") {
    const layers = [...geoLines(golden).map(line => ({...line, layer: "golden"})), ...geoLines(planned).map(line => ({...line, layer: "planned"}))];
    const coordinates = layers.flatMap(line => line.coordinates).filter(coord => Array.isArray(coord) && Number.isFinite(Number(coord[0])) && Number.isFinite(Number(coord[1])));
    if (!coordinates.length) return `<p class="status" data-planned-map-empty="true">尚無可顯示的來源幾何；缺口不補直線。</p>`;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    coordinates.forEach(coord => { minX = Math.min(minX, Number(coord[0])); maxX = Math.max(maxX, Number(coord[0])); minY = Math.min(minY, Number(coord[1])); maxY = Math.max(maxY, Number(coord[1])); });
    const middleLat = (minY + maxY) / 2;
    const xScale = Math.cos(middleLat * Math.PI / 180);
    const width = Math.max((maxX - minX) * xScale, 0.00001), height = Math.max(maxY - minY, 0.00001);
    const scale = Math.min(820 / width, 350 / height);
    const xy = coord => [450 + (Number(coord[0]) - (minX + maxX) / 2) * xScale * scale, 210 - (Number(coord[1]) - middleLat) * scale];
    const paths = layers.map((line, index) => {
      // Each compiler LineString remains a separate SVG path. No cross-trkseg join.
      const d = line.coordinates.map((coord, pointIndex) => `${pointIndex ? "L" : "M"}${xy(coord).map(v => v.toFixed(3)).join(",")}`).join(" ");
      return `<path d="${d}" class="planned-map-${line.layer}" data-planned-map-layer="${line.layer}" data-planned-map-piece="${index}" vector-effect="non-scaling-stroke"><title>${escape(`${line.layer}: ${compact(line.properties)}`)}</title></path>`;
    }).join("");
    const markers = array(points).map(point => {
      const coordinate = point.coordinates || point.coordinate || (point.lon != null && point.lat != null ? [point.lon, point.lat] : null);
      if (!Array.isArray(coordinate) || !Number.isFinite(Number(coordinate[0])) || !Number.isFinite(Number(coordinate[1]))) return "";
      const [x, y] = xy(coordinate);
      const id = anchorId(point);
      return `<circle cx="${x.toFixed(3)}" cy="${y.toFixed(3)}" r="4" class="planned-map-anchor${current.focusAnchor === id ? " is-selected" : ""}" data-planned-map-anchor="${escape(id)}" tabindex="0"><title>${escape(anchorLabel(point))}</title></circle>`;
    }).join("");
    return `<div class="planned-map" data-planned-map="${escape(mapId)}"><div class="planned-map-tools">
      <label><input type="checkbox" data-planned-map-toggle="golden" checked> Golden</label>
      <label><input type="checkbox" data-planned-map-toggle="planned" checked> Planned</label>
      ${button("map-in", "+", true, 'aria-label="放大 Planned 地圖"')}${button("map-out", "−", true, 'aria-label="縮小 Planned 地圖"')}${button("map-fit", "Fit")}
      <span>拖曳平移 · 點選錨點查核</span></div>
      <svg viewBox="0 0 900 420" role="img" aria-label="Golden 與 Planned 完整來源幾何疊圖" data-planned-map-svg="true">${paths}${markers}</svg>
      <p class="status" data-planned-map-selection="true">${layers.filter(line => line.layer === "planned").length} 個 Planned 幾何段；每個來源缺口均保留。</p></div>`;
  }
  function itinerary(preview) { return preview?.itinerary || preview?.planned_itinerary || {}; }
  function dayRows(preview) { return array(itinerary(preview).days || preview?.days || preview?.mission_day_estimates); }
  function tableHtml(headers, rows, attribute = "") {
    return `<div class="planned-table-scroll"><table class="planned-table" ${attribute}><thead><tr>${headers.map(value => `<th>${escape(value)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.map(row => `<tr>${row.map(value => `<td>${value}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}">尚無可計算資料</td></tr>`}</tbody></table></div>`;
  }
  function pagedTable(headers, records, row, viewId) {
    const pageSize = 100;
    const lastPage = Math.max(0, Math.ceil(records.length / pageSize) - 1);
    const page = Math.min(lastPage, Math.max(0, current.pages[viewId] || 0));
    current.pages[viewId] = page;
    current.tableViews.set(viewId, {headers, records, row});
    const start = page * pageSize;
    return `<section data-planned-table="${escape(viewId)}" data-planned-total-rows="${records.length}" data-planned-table-page="${page}">
      <div class="planned-map-tools"><span>完整 ${records.length} 筆 · 顯示 ${records.length ? start + 1 : 0}–${Math.min(records.length, start + pageSize)}</span>
      ${[["first", "第一頁", page > 0], ["previous", "上一頁", page > 0], ["next", "下一頁", page < lastPage], ["last", "最後頁", page < lastPage]].map(([action, label, enabled]) => `<button type="button" class="permission-button" data-planned-table-action="${action}" ${enabled ? "" : "disabled"}>${label}</button>`).join("")}</div>
      ${tableHtml(headers, records.slice(start, start + pageSize).map(row))}</section>`;
  }
  function movementSummary(events) {
    const summary = [];
    events.forEach((event, index) => {
      const previous = summary[summary.length - 1];
      const method = event.timing_method || event.method || event.time_role;
      const merge = event.kind === "move" && previous?.kind === "move"
        && (previous.timing_method || previous.method || previous.time_role) === method
        && previous.point_index === event.from_point_index
        && (previous.duration_minutes == null) === (event.duration_minutes == null)
        && previous.mission_day_id === event.mission_day_id;
      if (merge) {
        previous.point_index = event.point_index;
        previous.end_at = event.end_at;
        previous.arrival_at = event.arrival_at;
        if (previous.duration_minutes != null) previous.duration_minutes += event.duration_minutes;
        previous.raw_end_index = index;
        previous.raw_count += 1;
      } else summary.push({...event, raw_start_index: index, raw_end_index: index, raw_count: 1});
    });
    return summary;
  }
  function itineraryHtml(preview, viewId = "preview") {
    const plan = itinerary(preview);
    const days = dayRows(preview);
    const events = array(plan.events || plan.timeline || preview?.timetable);
    const binding = `${viewId}:${preview?.preview_sha256 || preview?.analysis_revision || preview?.itinerary_sha256 || "timeline"}`;
    const eventRow = event => [
      escape(`${event.kind || event.type || "event"} · ${event.label || event.anchor_id || event.at || event.segment_id || `p${event.from_point_index ?? event.point_index ?? "?"} → p${event.point_index ?? "?"}`}${event.raw_count > 1 ? ` · ${event.raw_count} 原始移動紀錄` : ""}`),
      `${escape(event.start_at || (event.kind === "camp" ? event.arrival_at : event.departure_at) || "未知")}<br>→ ${escape(event.end_at || (event.kind === "camp" ? event.departure_at : event.arrival_at) || "未知")}`,
      `${number(event.duration_minutes, " 分")}<br>${escape(event.timing_method || event.method || event.time_role || "")}`,
    ];
    const summary = movementSummary(events);
    return `<section data-planned-itinerary="true"><h4>Planned 分日、移動與停留</h4>
      ${tableHtml(["日", "啟程 → 到達", "移動", "停留／營地", "距離／限制"], days.map(day => [
        escape(day.day_id || day.mission_day_id || day.date || "日"),
        `${escape(day.departure_at || day.start_at || "未知")}<br>→ ${escape(day.arrival_at || day.end_at || "未知")}`,
        number(day.moving_minutes ?? day.movement_minutes, " 分"),
        `${number(day.stop_minutes ?? day.rest_minutes, " 分")}<br>${escape(compact(day.camp || day.camp_anchor || day.stays || ""))}`,
        `${number(day.distance_m == null ? day.distance_km : day.distance_m / 1000, " km")}<br>${escape(compact(day.issues || day.conflicts || []))}`,
      ]))}
      ${events.length ? `<details open><summary>時間軸：移動、固定停留、離營與未知 · ${events.length} 原始紀錄</summary>
      <p class="status">相鄰且估計方法相同的移動合併顯示；固定停留、紮營、已知／未知切換各自保留。原始時間軸可逐頁核對與完整匯出。</p>
      ${pagedTable(["事件／位置", "開始 → 結束", "分鐘／方法"], summary, eventRow, `${binding}:summary`)}
      <details data-planned-raw-timeline="true"><summary>完整原始時間軸 · ${events.length} 筆</summary>${pagedTable(["事件／位置", "開始 → 結束", "分鐘／方法"], events, eventRow, `${binding}:raw`)}</details></details>` : ""}
      <p class="status">${escape(plan.time_role || plan.timing_role || "planned estimates")} · ${escape(plan.timezone || "+08:00")}；未知耗時維持未知，規劃時間不作 Recorded。</p>
    </section>`;
  }
  function issueList(preview) {
    return [...array(preview?.issues), ...array(preview?.unresolved_items), ...array(preview?.ambiguities), ...array(preview?.gaps), ...array(preview?.conflicts), ...array(itinerary(preview).conflicts)];
  }
  function issuesHtml(issues, viewId) {
    return pagedTable(["問題／限制", "來源與細節"], issues, issue => typeof issue === "string"
      ? [escape(issue), ""] : [escape(`${issue.code || issue.issue_id || "issue"} · ${issue.message || ""}`), `<details><summary>完整證據欄位</summary><pre>${escape(JSON.stringify(issue, null, 2))}</pre></details>`], viewId);
  }
  function previewHtml(state, preview = state.preview, prefix = "") {
    if (!preview) return "";
    const summary = preview.summary || {};
    const pieces = array(preview.route_segments || preview.source_segments || preview.pieces || preview.segment_selections).length
      ? array(preview.route_segments || preview.source_segments || preview.pieces || preview.segment_selections)
      : array(geometry(preview)?.features).map(feature => feature.properties || {});
    const issues = issueList(preview);
    const unresolvedNames = array(preview.unresolved_names || preview.intent?.unresolved_names).length
      ? array(preview.unresolved_names || preview.intent?.unresolved_names)
      : issues.filter(issue => issue.name || issue.unresolved_name || issue.anchor_name).map(issue => issue.name || issue.unresolved_name || issue.anchor_name);
    return `<section data-planned-preview="${escape(preview.preview_sha256 || "unbound")}">
      <h3>${escape(prefix)} Golden / Planned 差異</h3>
      <p>${escape(preview.status || "candidate")} · ${escape(hash(preview.preview_sha256))} · ${number(preview.comparison?.planned_length_m == null ? summary.distance_m == null ? summary.distance_km : summary.distance_m / 1000 : preview.comparison.planned_length_m / 1000, " km")}</p>
      ${mapHtml(geometry(preview), goldenGeometry(preview, state.catalog), mapAnchors(state, preview), prefix ? "compare" : "preview")}
      ${preview.comparison ? `<details open data-planned-comparison="true"><summary>原 Golden 與此 Planned 的差異</summary><pre>${escape(JSON.stringify(preview.comparison, null, 2))}</pre></details>` : ""}
      ${itineraryHtml(preview, prefix ? "compare" : "preview")}
      <details open><summary>來源段、方向與點範圍 · ${pieces.length}</summary>
      ${tableHtml(["來源／種類", "Track／trkseg／點範圍", "方向／長度／時間"], pieces.map(piece => [
        `${escape(piece.source_id || "")}<br>${escape(piece.source_kind || piece.kind || "")}<br>${escape(hash(piece.source_sha256))}`,
        `${escape(piece.track_index ?? "")} / ${escape(piece.part_index ?? piece.trkseg_index ?? "")}<br>${escape(piece.source_start_index ?? piece.start_index ?? "")} → ${escape(piece.source_end_index ?? piece.end_index ?? "")}`,
        `${escape(piece.direction || "")} · ${number(piece.length_m ?? piece.distance_m, " m")}<br>↑ ${number(piece.ascent_m, " m")} / ↓ ${number(piece.descent_m, " m")}`,
      ]))}</details>
      ${issues.length ? `<section class="planned-issues" data-planned-issues="true"><h4>待定位、缺口與限制 · ${issues.length}</h4>${issuesHtml(issues, `${prefix || "preview"}:${preview.preview_sha256}:issues`)}</section>` : `<p data-planned-issues="none">編譯器未回報未解項。</p>`}
      ${unresolvedNames.length ? `<div data-planned-resolutions="true"><h4>將文字地名定位到來源錨點</h4>${unresolvedNames.map(item => {
        const name = typeof item === "string" ? item : item.name || item.text || item.label;
        return `<label>${escape(name)}<select data-planned-resolve-name="${escape(name)}">${anchorOptions(state, state.nameResolutions[name], "請確認對應位置")}</select></label>`;
      }).join("")}</div>` : ""}
      <p class="status">候選路線與人工審查不代表可通行、出發許可或即時安全判定。</p>
    </section>`;
  }

  function editorHtml(state) {
    const editor = state.editor;
    const routeOperation = ["branch", "replace"].includes(editor.kind);
    const endpointOptions = options(sourceAnchors(state), editor.sourceFrom, item => `${anchorId(item)}:${item.point_index}`, item => `${anchorLabel(item)} · p${item.point_index}`);
    const toOptions = options(sourceAnchors(state), editor.sourceTo, item => `${anchorId(item)}:${item.point_index}`, item => `${anchorLabel(item)} · p${item.point_index}`);
    const visible = visibleAnchors(state);
    return `<details class="planned-editor" open><summary>明確行程差異與來源選段</summary>
      <div class="planned-grid"><label>錨點來源範圍<select data-planned-anchor-scope="true"><option value="route" ${state.anchorScope === "route" ? "selected" : ""}>Golden 與已加入路段</option><option value="all" ${state.anchorScope === "all" ? "selected" : ""}>全部來源</option>${catalogSources(state).map(source => `<option value="${escape(sourceId(source))}" ${state.anchorScope === sourceId(source) ? "selected" : ""}>${escape(source.label || sourceId(source))}</option>`).join("")}</select></label>
      <label>依名稱／CP／別名搜尋<input data-planned-anchor-search="true" value="${escape(state.anchorQuery)}" placeholder="輸入後按套用搜尋"></label></div>
      <div class="planned-map-tools">${button("filter-anchors", "套用搜尋", !state.busy)}${button("anchor-previous", "上一頁錨點", state.anchorPage > 0 && !state.busy)}${button("anchor-next", "下一頁錨點", state.anchorPage < visible.lastPage && !state.busy)}<span data-planned-anchor-count="true">符合 ${visible.all.length} 個錨點 · 顯示 ${visible.all.length ? state.anchorPage * 100 + 1 : 0}–${Math.min(visible.all.length, (state.anchorPage + 1) * 100)}；已選位置另保留。</span></div>
      <div class="planned-grid">
      <label>操作<select data-planned-editor="kind">${options([
        ["stop", "固定停留"], ["camp", "紮營／離營"], ["depart", "啟程"], ["deadline", "最晚到達"],
        ["branch", "支線往返"], ["replace", "取代主線路段"], ["trim", "剪裁路線端點"],
      ], editor.kind, item => item[0], item => item[1], "選擇操作")}</select></label>
      <label>位置／起點<select data-planned-editor="at">${anchorOptions(state, editor.at)}</select></label>
      ${["replace", "trim"].includes(editor.kind) ? `<label>終點<select data-planned-editor="to">${anchorOptions(state, editor.to)}</select></label>` : ""}
      <label>第幾次經過此點（可留空）<input type="number" min="1" step="1" data-planned-editor="visit" value="${escape(editor.visit)}"></label>
      ${["replace", "trim"].includes(editor.kind) ? `<label>第幾次經過終點（可留空）<input type="number" min="1" step="1" data-planned-editor="toVisit" value="${escape(editor.toVisit)}"></label>` : ""}
      ${["stop", "camp"].includes(editor.kind) ? `<label>停留／紮營分鐘<input type="number" min="0" step="1" data-planned-editor="duration" value="${escape(editor.duration)}"></label>` : ""}
      ${["camp", "depart", "deadline"].includes(editor.kind) ? `<label>${editor.kind === "deadline" ? "最晚到達" : "啟程／離營"}<input type="datetime-local" data-planned-editor="departure" value="${escape(editor.departure)}"></label>` : ""}
      <label>顯示名稱（可留空）<input data-planned-editor="label" value="${escape(editor.label)}"></label>
      <label>此操作對應的原文句子（可留空）<input data-planned-editor="sourceText" value="${escape(editor.sourceText)}" placeholder="貼入待解句子；以此明確操作表達該句"></label></div>
      <details ${routeOperation ? "open" : ""}><summary>Ref.／地圖／TRH 候選來源段</summary><div class="planned-grid">
        <label>來源<select data-planned-editor="sourceId">${options(catalogSources(state), editor.sourceId, sourceId, source => `${source.label || source.name || sourceId(source)} · ${source.source_kind || source.kind || "source"}`)}</select></label>
        <label>不跨缺口的來源段<select data-planned-editor="partIndex">${options(sourceParts(editorSource(state)), editor.partIndex, (part) => part.part_index ?? sourceParts(editorSource(state)).indexOf(part), (part) => `trkseg ${part.part_index ?? sourceParts(editorSource(state)).indexOf(part)} · ${part.point_count ?? "?"} points`, "選擇來源段")}</select></label>
        <label>來源起點<select data-planned-editor="sourceFrom">${endpointOptions}</select></label>
        <label>來源終點<select data-planned-editor="sourceTo">${toOptions}</select></label>
        <label class="planned-check"><input type="checkbox" data-planned-editor="roundTrip" ${editor.roundTrip ? "checked" : ""}>從終點沿同一來源段返回</label>
        <label class="planned-check"><input type="checkbox" data-planned-editor="trailSearch" ${editor.trailSearch ? "checked" : ""}>改用既有向量山徑連通搜尋</label>
        ${editor.trailSearch ? `<label>尋徑起點<select data-planned-editor="trailFrom">${anchorOptions(state, editor.trailFrom)}</select></label>
        <label>尋徑終點<select data-planned-editor="trailTo">${anchorOptions(state, editor.trailTo)}</select></label>
        <label>途經點（可多選）<select multiple data-planned-editor="trailVia">${[...visible.page, ...anchors(state).filter(anchor => editor.trailVia.includes(anchorId(anchor)) && !visible.page.some(item => anchorId(item) === anchorId(anchor)))].map(anchor => `<option value="${escape(anchorId(anchor))}" ${editor.trailVia.includes(anchorId(anchor)) ? "selected" : ""}>${escape(anchorLabel(anchor))}</option>`).join("")}</select></label>` : ""}
      </div><p class="status">按來源順序選端點；反向由點範圍決定。每段保留完整 source hash 與 trkseg。</p>
      ${button("append-segment", "以此段建立自訂主路線", Boolean(state.catalog) && !state.busy)}
      <p class="status">自訂主路線按加入順序組合；有缺口時會保留未連通結果。</p></details>
      ${button("add-operation", "加入行程差異", Boolean(state.catalog) && !state.busy)}
      </details>`;
  }
  function sourceQueryHtml(state) {
    return `<details><summary>補充既有山徑來源（Overpass）</summary><p>從公開山徑向量查詢指定範圍，保存可回查的候選來源。新來源會使舊預覽過期。</p>
      <div class="planned-grid">${[["south", "南界緯度"], ["west", "西界經度"], ["north", "北界緯度"], ["east", "東界經度"]].map(([name, label]) => `<label>${label}<input type="number" step="0.00001" data-planned-bbox="${name}" value="${escape(state.bbox[name])}"></label>`).join("")}</div>
      ${button("overpass", "查詢並加入 Overpass 山徑候選", Boolean(state.catalog) && !state.busy)}
      <p class="status">Rudy+TWMap 線索、已核對向量與 R1–R4 由 workspace 來源目錄讀入；未定位或未完成審查的來源保持缺口。</p>
      ${array(state.catalog?.issues).length ? issuesHtml(state.catalog.issues, `catalog:${state.catalog.source_snapshot_sha256}:issues`) : ""}</details>`;
  }
  function reviewHtml(state) {
    if (!version(state)) return "";
    return `<section class="planned-review" data-planned-review-version="${escape(version(state))}" data-planned-review-manifest="${escape(manifestSha(state))}">
      <h4>審查此 Planned 版本</h4><p>${escape(version(state))} · ${escape(hash(manifestSha(state)))} · ${escape(state.saved?.review?.status || "未審查")}</p>
      ${[["sources", "來源與選段範圍"], ["geometry", "幾何順序、往返與缺口"], ["timing", "分日、腳程與固定停留"], ["uncertainty", "不確定性與候選來源限制"]].map(([name, label]) => `<label class="planned-check"><input type="checkbox" data-planned-review-check="${name}" ${state.reviewChecks[name] ? "checked" : ""} ${savedMatches(state) && !state.busy ? "" : "disabled"}>已檢視 ${label}</label>`).join("")}
      ${reviewIssues(state.preview).length ? `<p data-planned-review-issue-count="true">已確認 ${reviewIssues(state.preview).filter(id => state.reviewIssues[id] === true).length} / ${reviewIssues(state.preview).length} 筆版本限制</p>
      <label class="planned-check"><input type="checkbox" data-planned-review-all-issues="true" ${reviewIssues(state.preview).every(id => state.reviewIssues[id] === true) ? "checked" : ""} ${savedMatches(state) && !state.busy ? "" : "disabled"}>我已檢視以上完整 ${reviewIssues(state.preview).length} 筆限制，將全部綁定此版本確認</label>
      <details><summary>逐筆確認／撤回版本限制</summary>${pagedTable(["限制 ID", "人工確認"], reviewIssues(state.preview), id => [escape(id), `<label class="planned-check"><input type="checkbox" data-planned-review-issue="${escape(id)}" ${state.reviewIssues[id] ? "checked" : ""} ${savedMatches(state) && !state.busy ? "" : "disabled"}>確認限制</label>`], `review:${manifestSha(state)}:issues`)}</details>` : ""}
      <div class="permission-authoring-actions">${button("review", "記錄此版本審查", !state.busy && canReview(state))}${button("select", "以此 Planned 分析六力", !state.busy && reviewed(state))}</div>
      <p class="status">${savedMatches(state) ? "審查綁定以上 immutable manifest。" : "草稿或來源已變更，舊版審查不能套用到新的輸入。"}</p>
      <p class="status">匯出以下保存版本：${escape(version(state))}。伺服器會重新核對版本與來源；未保存的草稿不會混入匯出。</p>
      <div class="permission-authoring-actions">${["gpx", "manifest", "bundle"].map(kind => `<button type="button" class="permission-button" data-planned-export="${kind}" data-planned-export-url="${escape((host?.apiBase?.() || "") + path(state, `export/${encodeURIComponent(version(state))}/${kind}`))}" ${state.busy ? "disabled" : ""}>匯出 ${kind === "gpx" ? "Planned GPX" : kind === "manifest" ? "行程 Manifest" : "完整 Bundle"}</button>`).join("")}</div>
      <div aria-live="polite" data-planned-export-results="true">${Object.entries(state.exportResults).filter(([, result]) => result.version_id === version(state) && result.manifest_sha256 === manifestSha(state)).map(([kind, result]) => `<p role="status" data-planned-export-result="${kind}" data-planned-export-status="${escape(result.status)}" data-planned-export-version="${escape(result.version_id)}" data-planned-export-bytes="${result.byte_count ?? ""}" data-planned-export-sha256="${escape(result.sha256 || "")}">${escape(result.message)}</p>`).join("")}</div>
    </section>`;
  }
  function render(context) {
    const state = ensureProject(context.projectId);
    return `<section class="planned-workbench" data-planned-workbench="${escape(state.projectId)}" data-planned-input-revision="${state.inputRevision}">
      <div class="permission-card-head"><div><h3>Human Design → Planned GPX</h3><p>依 Golden 編排行程差異，從 Ref. 或地圖候選取得實際路段，建立自己的路線與節奏版本。</p></div><span class="chip info">Planned candidate</span></div>
      <p data-planned-catalog-status="${escape(state.catalogStatus)}">${escape(state.catalogStatus)} · ${catalogSources(state).length} 來源 · ${anchors(state).length} 錨點 · 來源 ${escape(hash(state.catalog?.source_snapshot_sha256))}</p>
      <label class="planned-text">人工行程<textarea data-planned-human-text="true" rows="4" placeholder="例如：在觀景點停留 40 分鐘；從岔路單攻山頭後返回。無法確定的地名會列出待定位。">${escape(state.text)}</textarea></label>
      <div class="planned-grid"><label>計畫啟程<input type="datetime-local" data-planned-field="departure" value="${escape(state.departure)}"></label>
      <label>時區<input data-planned-field="timezone" value="${escape(state.timezone)}" placeholder="+08:00" pattern="[+-][0-9]{2}:[0-9]{2}"></label>
      <label>腳程估計<select data-planned-field="paceMode"><option value="source_preferred" ${state.paceMode === "source_preferred" ? "selected" : ""}>可用來源節奏優先</option><option value="fixed_speed" ${state.paceMode === "fixed_speed" ? "selected" : ""}>全程使用固定腳程</option></select></label>
      <label>腳程 km/h（可留空）<input type="number" min="0.1" max="20" step="0.1" data-planned-field="speed" value="${escape(state.speed)}" placeholder="來源不足時維持未知"></label></div>
      ${editorHtml(state)}${sourceQueryHtml(state)}
      ${state.operations.length || state.selections.length ? `<section><h4>已加入的差異／路段</h4>${[...state.operations.map((operation, index) => ({type: "operation", index, value: operation})), ...state.selections.map((selection, index) => ({type: "selection", index, value: selection}))].map(item => `<div class="planned-operation"><code>${escape(compact(item.value))}</code>${button("remove", "移除", !state.busy, `data-planned-remove-type="${item.type}" data-planned-remove-index="${item.index}"`)}</div>`).join("")}</section>` : ""}
      <div class="permission-authoring-actions">${button("preview", "預覽 Planned 幾何與節奏", Boolean(state.catalog) && !state.busy)}${button("save", "Save Planned Version", canSave(state) && !state.busy)}${button("refresh", "重新讀取來源與版本", !state.busy)}</div>
      <p class="status" aria-live="polite" data-planned-preview-status="true">${escape(state.previewStatus)}</p><p role="status" data-planned-status="true">${escape(state.status)}</p>
      ${previewHtml(state)}${reviewHtml(state)}
      <section class="planned-versions"><h4>保存版本與分析主體</h4><div class="planned-grid">
      <label>Planned 版本<select data-planned-version="true">${options(state.versions, state.versionId, item => item.version_id, item => `${item.version_id} · ${item.review_status || item.status || "saved"}`)}</select></label>
      <label>比較另一版本<select data-planned-compare-version="true">${options(state.versions, state.compareId, item => item.version_id, item => item.version_id)}</select></label></div>
      <div class="permission-authoring-actions">${button("restore", "Restore Planned Version", Boolean(state.versionId) && !state.busy)}${button("compare", "比較版本", Boolean(state.compareId) && !state.busy)}${button("golden", "切回 Golden 分析", !state.busy)}</div>
      <p data-planned-analysis-selection="true">目前選擇：${escape(state.selection?.subject_kind || context.subject?.subject_kind || "golden_gpx")} ${escape(state.selection?.version_id || "")}</p>
      ${state.compare ? previewHtml(state, state.compare.preview, "比較版") : ""}</section>
    </section>`;
  }

  async function loadCatalog(state, explicit = false) {
    if (!host || state.busy) return;
    state.busy = true; state.catalogStatus = "loading"; refresh();
    try {
      const results = await Promise.allSettled([host.fetchJson(path(state, "catalog")), host.fetchJson(path(state, "versions")), host.fetchJson(path(state, "analysis-selection"))]);
      if (!live(state)) return;
      const errors = results.filter(result => result.status === "rejected").map(result => String(result.reason?.message || result.reason));
      if (results[0].status === "fulfilled") {
        const next = results[0].value;
        if (state.catalog && state.catalog.source_snapshot_sha256 !== next.source_snapshot_sha256) changed(state, false);
        state.catalog = next; state.catalogStatus = "ready";
        if (!state.bbox.south) {
          const golden = array(next.sources).find(source => sourceId(source) === next.golden_source_id);
          const points = sourceParts(golden).flatMap(part => array(part.points));
          if (points.length) {
            const latitudes = points.map(point => Number(point.lat)), longitudes = points.map(point => Number(point.lon));
            // Compute by reduction so a large full-resolution GPX cannot exceed
            // the JavaScript argument limit through Math.min(...points).
            state.bbox = {south: (latitudes.reduce((a, b) => Math.min(a, b), Infinity) - 0.005).toFixed(5),
              north: (latitudes.reduce((a, b) => Math.max(a, b), -Infinity) + 0.005).toFixed(5),
              west: (longitudes.reduce((a, b) => Math.min(a, b), Infinity) - 0.005).toFixed(5),
              east: (longitudes.reduce((a, b) => Math.max(a, b), -Infinity) + 0.005).toFixed(5)};
          }
        }
      } else state.catalogStatus = "unavailable";
      if (results[1].status === "fulfilled") { state.versions = array(results[1].value.versions); state.headVersionId = results[1].value.head_version_id || null; }
      if (results[2].status === "fulfilled") state.selection = results[2].value.selection || results[2].value;
      state.status = errors.length ? errors.join(" · ") : explicit ? "來源與保存版本已重新讀取。" : "來源目錄已就緒；預覽不寫入 workspace。";
    } finally { if (live(state)) { state.busy = false; refresh(); } }
  }
  async function exportVersion(state, kind) {
    if (!host || state.busy || !["gpx", "manifest", "bundle"].includes(kind)) return;
    const selectedVersion = version(state), selectedManifest = manifestSha(state);
    if (!selectedVersion || !selectedManifest) return;
    const inputRevision = state.inputRevision;
    const formats = {gpx: {mime: "application/gpx+xml", suffix: ".planned.gpx"},
      manifest: {mime: "application/json", suffix: ".manifest.json"},
      bundle: {mime: "application/zip", suffix: ".planned-bundle.zip"}};
    const format = formats[kind];
    const expectedFilename = selectedVersion + format.suffix;
    const bound = () => live(state, inputRevision) && version(state) === selectedVersion && manifestSha(state) === selectedManifest;
    const receipt = {status: "loading", version_id: selectedVersion, manifest_sha256: selectedManifest, format: kind,
      byte_count: null, file_written_confirmed: false, message: `正在核對並準備匯出：${selectedVersion} · ${kind}`};
    state.exportResults[kind] = receipt;
    state.busy = true; refresh();
    try {
      // This fixed project/version endpoint is the same endpoint as the visible
      // control. A regular fetch exposes HTTP conflicts and response bytes even
      // when an embedded browser does not surface native download events.
      const response = await global.fetch((host.apiBase?.() || "") + path(state, `export/${encodeURIComponent(selectedVersion)}/${kind}`), {
        method: "GET", headers: {Accept: format.mime}, cache: "no-store", credentials: "same-origin", redirect: "error",
      });
      if (!bound()) return;
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        const detail = error.detail || error;
        const message = typeof detail === "string" ? detail : detail.message || JSON.stringify(detail);
        throw new Error(`HTTP ${response.status}${detail.code ? ` ${detail.code}` : ""}: ${message}`);
      }
      const disposition = response.headers.get("Content-Disposition") || "";
      const filenameMatch = disposition.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
      const filename = (filenameMatch?.[1] || filenameMatch?.[2] || "").trim();
      if (!/^\s*attachment(?:;|$)/i.test(disposition) || filename !== expectedFilename) {
        throw new Error(`Content-Disposition 與保存版本／格式不符；預期 ${expectedFilename}。`);
      }
      if (response.headers.get("X-Scout-Track-Role") !== "planned-candidate"
          || response.headers.get("X-Scout-Runtime-Safety-Truth") !== "false") {
        throw new Error("匯出回應未保留 planned-candidate / runtime safety truth=false，已停止下載。");
      }
      const mime = (response.headers.get("Content-Type") || "").split(";", 1)[0].trim().toLowerCase();
      if (mime !== format.mime) throw new Error(`匯出 Content-Type 不符：${mime || "未提供"}。`);
      // Preserve the response bytes. Never decode/re-encode GPX or ZIP text.
      const bytes = await response.arrayBuffer();
      if (!bound()) return;
      if (!bytes.byteLength) throw new Error("匯出回應為空，未啟動下載。");
      let sha256 = null;
      if (global.crypto?.subtle) {
        const digest = await global.crypto.subtle.digest("SHA-256", bytes);
        if (!bound()) return;
        sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      }
      Object.assign(receipt, {status: "ready", byte_count: bytes.byteLength, sha256, filename,
        media_type: mime, track_role: "planned-candidate", runtime_safety_truth: false,
        message: `匯出產物已準備：${selectedVersion} · ${kind} · ${bytes.byteLength} bytes · ${filename}。尚未確認寫入使用者磁碟。`});
      let objectUrl = null;
      try {
        if (typeof global.URL.createObjectURL !== "function") throw new Error("此瀏覽器沒有 Blob 下載能力");
        objectUrl = global.URL.createObjectURL(new global.Blob([bytes], {type: mime}));
        const link = global.document.createElement("a");
        link.href = objectUrl; link.download = filename; link.hidden = true;
        global.document.body.appendChild(link);
        try { link.click(); receipt.download_requested = true; }
        finally { link.remove(); }
      } catch (error) {
        receipt.status = "prepared_download_unavailable";
        receipt.message += ` 瀏覽器下載動作未完成：${String(error?.message || error)}。`;
      } finally {
        // Delay revocation until the browser has had a chance to consume it;
        // this does not claim that a native file was created.
        if (objectUrl) global.setTimeout(() => global.URL.revokeObjectURL(objectUrl), 30000);
      }
    } catch (error) {
      if (bound()) Object.assign(receipt, {status: "failed", message: `匯出失敗：${selectedVersion} · ${kind} · ${String(error?.message || error)}；未啟動下載。`});
    } finally {
      if (live(state)) {
        if (!bound()) Object.assign(receipt, {status: "stale", message: `已忽略過期匯出回應：${selectedVersion} · ${kind}；專案、保存版本或草稿已變更。`});
        state.busy = false; refresh();
      }
    }
  }

  async function action(state, name) {
    if (!host || state.busy) return;
    const inputRevision = state.inputRevision;
    state.busy = true; refresh();
    try {
      if (name === "overpass") {
        const bbox = Object.fromEntries(Object.entries(state.bbox).map(([name, value]) => [name, Number(value)]));
        if (Object.values(state.bbox).some(value => value === "") || Object.values(bbox).some(value => !Number.isFinite(value)) || bbox.south >= bbox.north || bbox.west >= bbox.east) throw new Error("請提供有效的 WGS84 範圍。");
        const result = await host.postJson(path(state, "sources/overpass"), {bbox, idempotency_key: key(state, "overpass", Object.values(bbox).join(":")), explicit_confirmation: true});
        if (!live(state)) return;
        if (result.catalog) { state.catalog = result.catalog; state.catalogStatus = "ready"; }
        changed(state, false);
        state.status = `山徑候選來源已保存：${result.status} · ${result.receipt_ref || ""}。請重新預覽。`;
      } else if (name === "preview") {
        const request = buildRequest(state);
        const result = await host.postJson(path(state, "preview"), request);
        if (!live(state, inputRevision)) return;
        state.preview = result; state.request = copy(result.request || request); state.previewRevision = inputRevision;
        state.previewStatus = `預覽完成：${result.status || "candidate"} · ${hash(result.preview_sha256)}`;
        state.status = "已編譯實際幾何與計画時間。檢視後可明確 Save。";
      } else if (name === "save") {
        if (!canSave(state)) return;
        const saved = await host.postJson(path(state, "versions"), {request: state.request,
          expected_preview_sha256: state.preview.preview_sha256,
          idempotency_key: key(state, "save", state.preview.preview_sha256), explicit_confirmation: true});
        if (!live(state, inputRevision)) return;
        const id = saved.version_id || saved.manifest?.version_id;
        const detail = await host.fetchJson(path(state, `versions/${encodeURIComponent(id)}`));
        if (!live(state, inputRevision)) return;
        state.saved = {...saved, ...detail}; state.versionId = id;
        state.reviewChecks = {}; state.reviewIssues = {};
        const versions = await host.fetchJson(path(state, "versions"));
        if (!live(state, inputRevision)) return;
        state.versions = array(versions.versions); state.headVersionId = versions.head_version_id || null;
        state.status = `已保存 ${id}，原 Golden 保留。審查尚未自動接受。`;
      } else if (name === "restore" || name === "compare") {
        const id = name === "restore" ? state.versionId : state.compareId;
        if (!id) return;
        const detail = await host.fetchJson(path(state, `versions/${encodeURIComponent(id)}`));
        if (!live(state, inputRevision)) return;
        if (name === "compare") { state.compare = detail; state.status = `比較 ${id}；目前草稿未變更。`; }
        else {
          const request = copy(detail.manifest?.request || detail.preview?.request || detail.request || detail.manifest?.intent || {});
          state.text = request.human_text || ""; state.operations = copy(array(request.operations));
          state.selections = copy(array(request.route_selections)); state.nameResolutions = copy(request.name_resolutions || {});
          state.speed = request.default_speed_kmh == null ? "" : String(request.default_speed_kmh);
          state.paceMode = request.pace_mode || "source_preferred";
          const departure = request.departure_at || "";
          state.departure = departure ? departure.slice(0, 16) : "";
          state.timezone = departure.match(/([+-]\d{2}:\d{2})$/)?.[1] || "+08:00";
          state.inputRevision += 1; state.saved = detail; state.preview = detail.preview;
          state.request = request; state.previewRevision = state.inputRevision;
          state.reviewChecks = {}; state.reviewIssues = {};
          state.previewStatus = `已恢復 ${id} · ${sourceCurrent(state) ? "來源核對通過" : "來源已變更，舊版只供比較"}`;
          state.status = "已恢復保存版本；未完成的人工審查仍未接受。";
        }
      } else if (name === "review") {
        if (!canReview(state)) return;
        const result = await host.postJson(path(state, "review"), {version_id: version(state), expected_manifest_sha256: manifestSha(state),
          reviewer_alias: "dashboard_operator", accepted_dimensions: ["sources", "geometry", "timing", "uncertainty"],
          acknowledged_issue_ids: reviewIssues(state.preview), idempotency_key: key(state, "review", manifestSha(state)), explicit_confirmation: true});
        if (!live(state, inputRevision)) return;
        state.saved.review = result.review || result;
        state.status = `已記錄 ${version(state)} 的人工審查；可選為六力分析主體。`;
      } else if (name === "select" || name === "golden") {
        if (name === "select" && !reviewed(state)) return;
        const selectionHash = state.selection?.selection_sha256 || null;
        const payload = {subject_kind: name === "golden" ? "golden_gpx" : "planned_gpx", expected_selection_sha256: selectionHash,
          idempotency_key: key(state, "select", `${name}:${manifestSha(state)}:${selectionHash}`), explicit_confirmation: true};
        if (name === "select") { payload.version_id = version(state); payload.expected_manifest_sha256 = manifestSha(state); }
        const result = await host.postJson(path(state, "analysis-selection"), payload);
        if (!live(state, inputRevision)) return;
        state.selection = result.selection || result;
        await host.refreshAnalysis();
        if (!live(state)) return;
        state.status = `六力分析主體已切為 ${payload.subject_kind}；各力新版結果或待重算狀態分別顯示。`;
      }
    } catch (error) {
      if (live(state)) { state.status = `${name} 未完成：${String(error?.message || error)}`; if (name === "preview") state.previewStatus = state.status; }
    } finally { if (live(state)) { state.busy = false; refresh(); } }
  }

  function bindTables(root) {
    root.querySelectorAll("[data-planned-table]").forEach(table => {
      if (table.dataset.plannedTableBound === "true") return;
      table.dataset.plannedTableBound = "true";
      const state = current;
      table.querySelectorAll("[data-planned-table-action]").forEach(control => control.addEventListener("click", () => {
        if (control.disabled || current !== state) return;
        const id = table.dataset.plannedTable;
        const view = state.tableViews.get(id);
        if (!view) return;
        const lastPage = Math.max(0, Math.ceil(view.records.length / 100) - 1);
        const action = control.dataset.plannedTableAction;
        state.pages[id] = action === "first" ? 0 : action === "last" ? lastPage
          : (state.pages[id] || 0) + (action === "next" ? 1 : -1);
        // Only this page of rows changes. No whole Dashboard/map reconstruction.
        const container = table.parentElement;
        table.outerHTML = pagedTable(view.headers, view.records, view.row, id);
        bindTables(container);
        bindReviewChecks(container, state);
      }));
    });
  }
  function bindMaps(root) {
    root.querySelectorAll("[data-planned-map]").forEach(map => {
      const svg = map.querySelector("svg");
      if (!svg || svg.dataset.plannedBound === "true") return;
      svg.dataset.plannedBound = "true";
      const fitted = [0, 0, 900, 420]; let view = [...fitted]; let drag = null;
      const apply = () => svg.setAttribute("viewBox", view.join(" "));
      map.querySelectorAll("[data-planned-map-toggle]").forEach(control => control.addEventListener("change", () => {
        map.querySelectorAll(`[data-planned-map-layer="${control.dataset.plannedMapToggle}"]`).forEach(pathElement => { pathElement.style.display = control.checked ? "" : "none"; });
      }));
      map.querySelectorAll("[data-planned-action]").forEach(control => control.addEventListener("click", () => {
        const name = control.dataset.plannedAction;
        if (name === "map-fit") view = [...fitted];
        else { const factor = name === "map-in" ? 0.7 : 1 / 0.7; const width = view[2] * factor, height = view[3] * factor; view = [view[0] + (view[2] - width) / 2, view[1] + (view[3] - height) / 2, width, height]; }
        apply();
      }));
      svg.addEventListener("pointerdown", event => { drag = {x: event.clientX, y: event.clientY, view: [...view]}; svg.setPointerCapture?.(event.pointerId); });
      svg.addEventListener("pointermove", event => {
        if (!drag) return;
        const rect = svg.getBoundingClientRect();
        view = [drag.view[0] - (event.clientX - drag.x) / Math.max(rect.width, 1) * drag.view[2], drag.view[1] - (event.clientY - drag.y) / Math.max(rect.height, 1) * drag.view[3], view[2], view[3]]; apply();
      });
      svg.addEventListener("pointerup", () => { drag = null; });
      svg.addEventListener("pointercancel", () => { drag = null; });
      map.querySelectorAll("[data-planned-map-anchor]").forEach(anchor => {
        const select = () => {
          map.querySelectorAll(".is-selected").forEach(item => item.classList.remove("is-selected"));
          anchor.classList.add("is-selected");
          const output = map.querySelector("[data-planned-map-selection]");
          if (output) output.textContent = `${anchor.dataset.plannedMapAnchor} · ${anchor.querySelector("title")?.textContent || ""}`;
        };
        anchor.addEventListener("click", select);
        anchor.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(); } });
      });
    });
  }
  function bindReviewChecks(root, state) {
    root.querySelectorAll("[data-planned-review-check], [data-planned-review-issue], [data-planned-review-all-issues]").forEach(input => {
      if (input.dataset.plannedReviewBound === "true") return;
      input.dataset.plannedReviewBound = "true";
      input.addEventListener("change", event => {
        if (!live(state) || !savedMatches(state)) return;
        const control = event.currentTarget;
        if (control.hasAttribute("data-planned-review-all-issues")) {
          state.reviewIssues = Object.fromEntries(reviewIssues(state.preview).map(id => [id, control.checked]));
        } else if (control.dataset.plannedReviewCheck) state.reviewChecks[control.dataset.plannedReviewCheck] = control.checked;
        else state.reviewIssues[control.dataset.plannedReviewIssue] = control.checked;
        updateButtons(state);
      });
    });
  }
  function installStyle() {
    if (global.document.getElementById("plannedRouteStyle")) return;
    const style = global.document.createElement("style"); style.id = "plannedRouteStyle";
    style.textContent = `.planned-workbench{border:1px solid #9eb7ad;border-radius:12px;margin:16px 0;padding:14px;background:#f8fcfa;color:#203a30}.planned-workbench h3,.planned-workbench h4{color:#183e2c}.planned-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:12px 0}.planned-grid label,.planned-text{display:flex;flex-direction:column;gap:5px;font-size:13px}.planned-grid input,.planned-grid select,.planned-text textarea,.planned-workbench select{max-width:100%;min-width:0;padding:8px;border:1px solid #a8bab1;border-radius:5px;background:white;color:#163526}.planned-text textarea{width:100%;box-sizing:border-box}.planned-check{display:flex;gap:8px;align-items:center;margin:8px 0}.planned-grid .planned-check{flex-direction:row}.planned-editor,.planned-review,.planned-versions{border-top:1px solid #ccd9d2;margin-top:16px;padding-top:14px}.planned-operation{display:flex;align-items:center;gap:12px;margin:8px 0}.planned-operation code{white-space:pre-wrap;overflow-wrap:anywhere;flex:1}.planned-table-scroll{overflow:auto;max-height:420px}.planned-table{border-collapse:collapse;width:100%;font-size:12px;text-align:left}.planned-table th,.planned-table td{padding:8px;border-bottom:1px solid #d1dbd5;vertical-align:top;white-space:normal;min-width:110px}.planned-table th{background:#ecf4ee;position:sticky;top:0}.planned-workbench pre,.planned-subject pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto}.planned-issues{border-left:4px solid #b07816;padding:4px 12px;background:#fff8e8}.planned-issues li{overflow-wrap:anywhere;margin:8px 0}.planned-map{border:1px solid #a5b9ad;border-radius:8px;overflow:hidden;margin:12px 0;background:#f2f5ef}.planned-map-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px;background:white;font-size:12px}.planned-map svg{display:block;width:100%;height:420px;touch-action:none;cursor:grab}.planned-map path{fill:none;stroke-linejoin:round;stroke-linecap:round}.planned-map-golden{stroke:#687f99;stroke-width:5;opacity:.65}.planned-map-planned{stroke:#d35424;stroke-width:2.5}.planned-map-anchor{fill:#fff;stroke:#214e3a;stroke-width:1;cursor:pointer}.planned-map-anchor.is-selected{fill:#edc34d;r:7}.planned-map .status{padding:0 10px}.planned-subject{border:2px solid #cc6c37}.planned-legacy-golden{border:1px dashed #999;padding:12px;margin:16px 0}.planned-legacy-golden>summary{font-weight:600;color:#75542e;cursor:pointer}.planned-legacy-golden[open]>summary{margin-bottom:16px}@media(max-width:600px){.planned-map svg{height:300px}.planned-grid{grid-template-columns:1fr}.planned-workbench{padding:10px}.planned-operation{align-items:flex-start}}`;
    global.document.head.appendChild(style);
  }
  function bind(context) {
    host = context; const state = ensureProject(context.projectId());
    installStyle();
    bindTables(global.document);
    bindMaps(global.document);
    const root = global.document.querySelector("[data-planned-workbench]");
    if (!root || root.dataset.plannedBound === "true") return;
    root.dataset.plannedBound = "true";
    if (state.busy) root.querySelectorAll("input, textarea, select").forEach(input => { input.disabled = true; });
    root.querySelector("[data-planned-human-text]")?.addEventListener("input", event => { state.text = event.currentTarget.value; changed(state, false); });
    root.querySelectorAll("[data-planned-field]").forEach(input => input.addEventListener("input", event => { state[event.currentTarget.dataset.plannedField] = event.currentTarget.value; changed(state, false); }));
    root.querySelectorAll("[data-planned-bbox]").forEach(input => input.addEventListener("input", event => { state.bbox[event.currentTarget.dataset.plannedBbox] = event.currentTarget.value; }));
    root.querySelector("[data-planned-anchor-search]")?.addEventListener("input", event => { state.anchorQuery = event.currentTarget.value; });
    root.querySelector("[data-planned-anchor-scope]")?.addEventListener("change", event => { state.anchorScope = event.currentTarget.value; state.anchorPage = 0; refresh(); });
    root.querySelectorAll("[data-planned-editor]").forEach(input => input.addEventListener(input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input", event => {
      const field = event.currentTarget.dataset.plannedEditor;
      state.editor[field] = field === "trailVia" ? [...event.currentTarget.selectedOptions].map(option => option.value)
        : event.currentTarget.type === "checkbox" ? event.currentTarget.checked : event.currentTarget.value;
      if (["sourceId", "partIndex"].includes(field)) { state.editor.sourceFrom = ""; state.editor.sourceTo = ""; if (field === "sourceId") state.editor.partIndex = String(sourceParts(editorSource(state))[0]?.part_index ?? 0); }
      if (["kind", "sourceId", "partIndex", "trailSearch"].includes(field)) refresh();
    }));
    root.querySelectorAll("[data-planned-resolve-name]").forEach(input => input.addEventListener("change", event => {
      const name = event.currentTarget.dataset.plannedResolveName;
      if (event.currentTarget.value) state.nameResolutions[name] = event.currentTarget.value; else delete state.nameResolutions[name];
      state.focusAnchor = event.currentTarget.value;
      changed(state);
    }));
    root.querySelector("[data-planned-version]")?.addEventListener("change", event => { state.versionId = event.currentTarget.value; updateButtons(state); });
    root.querySelector("[data-planned-compare-version]")?.addEventListener("change", event => { state.compareId = event.currentTarget.value; updateButtons(state); });
    bindReviewChecks(root, state);
    root.querySelectorAll("[data-planned-export]").forEach(control => control.addEventListener("click", () => {
      if (!control.disabled) void exportVersion(state, control.dataset.plannedExport);
    }));
    root.querySelectorAll("[data-planned-action]").forEach(control => control.addEventListener("click", () => {
      const name = control.dataset.plannedAction;
      if (control.disabled || name.startsWith("map-")) return;
      try {
        if (name === "filter-anchors") { state.anchorPage = 0; refresh(); return; }
        if (name === "anchor-previous" || name === "anchor-next") { state.anchorPage += name === "anchor-next" ? 1 : -1; refresh(); return; }
        if (name === "refresh") { void loadCatalog(state, true); return; }
        if (name === "add-operation" || name === "append-segment") { addOperation(state, name === "append-segment"); return; }
        if (name === "remove") { const collection = control.dataset.plannedRemoveType === "operation" ? state.operations : state.selections; collection.splice(Number(control.dataset.plannedRemoveIndex), 1); changed(state); return; }
        void action(state, name);
      } catch (error) { state.status = String(error?.message || error); refresh(); }
    }));
    if (state.catalogStatus === "idle") void loadCatalog(state);
  }

  function renderSubject(subject, route) {
    ensureProject(subject.project_id);
    const role = route.replace("outdoor-", "").replaceAll("-", "_");
    const dependency = subject.dependencies?.[role] || {};
    const routeGeojson = subject.planned_route_geojson || subject.route_geojson || subject.route_axis?.geojson;
    const checkpoints = array(subject.checkpoints || subject.route_axis?.checkpoints);
    const segments = array(subject.segments || subject.route_axis?.segments);
    const preview = {analysis_revision: subject.analysis_revision, itinerary: subject.itinerary || subject.planned_itinerary, days: subject.mission_day_estimates, timetable: subject.timetable};
    return `<section class="panel planned-subject" data-analysis-subject="${escape(subject.subject_id)}" data-analysis-project="${escape(subject.project_id)}" data-analysis-revision="${escape(subject.analysis_revision)}" data-analysis-dependency="${escape(dependency.status || "needs_reanalysis")}" data-planned-analysis-subject="true">
      <h3>${subject.subject_kind === "unresolved_selection" ? "Planned 分析選擇待恢復" : "共同分析主體：Planned GPX"}</h3><p>${escape(subject.selected_plan_version_id || subject.version_id || subject.planned_version_id || subject.subject_id)} · ${escape(hash(subject.analysis_revision))}</p>
      <div class="metric-line"><div class="metric-row"><span>新路線 / CP / Segment</span><strong>${escape(hash(subject.geometry_fingerprint))} · ${checkpoints.length} CP · ${segments.length} segments</strong></div>
      <div class="metric-row"><span>本頁新版分析</span><strong>${escape(dependency.status || "needs_reanalysis")}</strong></div></div>
      <p class="status">${escape(dependency.reason || "各力依此版 route axis 與時間計畫重算；尚未重算的內容保留明確狀態。")}</p>
      ${mapHtml(routeGeojson, subject.golden_route_geojson, checkpoints, "analysis")}${itineraryHtml(preview, `analysis:${role}`)}
      <details><summary>此 Planned 的 CP、路段與版次</summary>${tableHtml(["CP", "序列／距離", "時刻"], checkpoints.map(cp => [escape(cp.label || cp.checkpoint_id || cp.anchor_id), escape(cp.route_order_m ?? cp.distance_m ?? cp.point_index ?? "未知"), escape(cp.arrival_at || cp.planned_at || "未知")]))}
      ${tableHtml(["Segment", "端點", "距離／來源"], segments.map(segment => [escape(segment.segment_id || segment.id), `${escape(segment.from_checkpoint_id || segment.start_anchor_id || segment.start_point_index || "")} → ${escape(segment.to_checkpoint_id || segment.end_anchor_id || segment.end_point_index || "")}`, `${number(segment.length_m ?? segment.distance_m, " m")}<br>${escape(segment.source_id || "")}`]))}
      <pre>${escape(JSON.stringify({sources: subject.sources, dependencies: subject.dependencies, subject_guard: subject.subject_guard}, null, 2))}</pre>
      ${array(subject.issues).length ? issuesHtml(subject.issues, `analysis:${subject.analysis_revision}:issues`) : ""}</details>
      <p class="status">Planned 為候選分析；舊 Golden 地圖／報表尚未因此變成新版結果。歷史天候未知與目前預報分開，runtime safety truth=false。</p>
    </section>`;
  }
  function wrapHistorical(content, header, route, subject) {
    if (!["planned_gpx", "unresolved_selection"].includes(subject?.subject_kind) || route === "outdoor-permission" || route === "outdoor-pace-fit-body-index") return content;
    return `${header}<details class="planned-legacy-golden" data-planned-legacy-golden="${escape(route)}"><summary>Golden 歷史資料與既有工具 · 此區尚未重算為 Planned ${escape(subject.selected_plan_version_id || subject.version_id || subject.subject_id)}</summary>${content.replace(header, "")}</details>`;
  }
  global.ScoutPlannedRoute = {render, bind, renderSubject, wrapHistorical};
})(typeof window === "undefined" ? globalThis : window);
