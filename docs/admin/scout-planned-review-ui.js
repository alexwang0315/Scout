/* Same-version human inputs, explicit terrain assumptions, and grounded intent.
 * GET and rendering never save declarations. Unknowns stay null. A reviewer,
 * review time, source evidence, or personal capability is never synthesized.
 */
(function (global) {
  "use strict";
  const array = value => Array.isArray(value) ? value : [];
  const copy = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const pretty = value => JSON.stringify(value, null, 2);
  const navFields = {
    offline_map_downloaded:"離線地圖已下載", gpx_loaded_on_device:"GPX 已載入裝置",
    contour_skill_confirmed:"等高線判讀能力", terrain_feature_skill_confirmed:"地形特徵判讀能力",
    junction_points_known:"岔路位置已掌握", retreat_direction_understood:"撤退方向已理解",
    backup_positioning_available:"備援定位可用", terrain_risk_layers_understood:"地形風險圖層已理解"
  };
  const readinessFields = {team_slowest_basis_confirmed:"以隊伍最慢者為準", departure_time_confirmed:"出發時間已確認",
    equipment_confirmed:"裝備已確認", remote_contact_confirmed:"留守聯絡已確認"};
  const sections = {
    members:{label:"隊伍成員與腳程聲明", fallback:[], example:[{member_id:"請填成員代號", planned_pace_kmh:null, reserve_minutes:null, experience_level:null, evidence_ids:[]}]},
    equipment:{label:"裝備狀態", fallback:[], example:[{item:"請填裝備名稱", state:"unknown", member_id:null, evidence_ids:[]}]},
    transport:{label:"交通、回程與折返限制", fallback:{}, example:{mode:null, meeting_point:null, outbound_at:null, latest_return_at:null, return_limit_point_index:null, return_constraint:null, turnaround_point_index:null, turnaround_at:null}},
    evidence:{label:"來源檔案與 SHA-256", fallback:[], example:[{evidence_id:"source.example", ref:"請填專案內來源路徑", sha256:"請填完整 SHA-256", source_kind:"human_review", description:"請填來源說明"}]},
    checkpoint_reviews:{label:"CP 水源、營地與撤退審查", fallback:[], example:[{point_index:0, water_available:null, retreat_available:null, signal_expected:null, requires_daylight:null, camp_suitability:"unknown", campsite_legal_use:null, campsite_capacity:null, review:{status:"pending", evidence_ids:[]}}]},
    segment_policies:{label:"路段政策", fallback:[], example:[{from_point_index:0, to_point_index:1, requires_daylight:null, water_available:null, retreat_available:null, signal_expected:null, review:{status:"pending", evidence_ids:[]}}]},
    permission_reviews:{label:"Permission 餘裕與來源審查", fallback:[], example:[{point_index:0, remaining_safety_buffer_minutes:null, next_segment_uncertainty_minutes:null, weather_reserve_minutes:null, daylight_reserve_minutes:null, retreat_reserve_minutes:null, slowest_member_reserve_minutes:null, review:{status:"pending", evidence_ids:[]}, weather_review:{status:"pending", evidence_ids:[]}, daylight_review:{status:"pending", evidence_ids:[]}, retreat_review:{status:"pending", evidence_ids:[]}}]},
    narrative:{label:"Route Context briefing 與敘事審查", fallback:{review:{status:"pending", evidence_ids:[]}}, example:{briefing_evidence_id:null, review:{status:"pending", reviewer_alias:null, reviewed_at:null, conclusion:null, evidence_ids:[]}, notes:null}}
  };
  const timingFields = {
    assumed_flat_speed_kmh:["假設平地腳程 km/h",.1,20], assumed_ascent_m_per_hour:["假設爬升 m/h",1,null],
    assumed_descent_m_per_hour:["假設下降 m/h",1,null], uncertainty_fraction:["耗時區間比例（0–1）",0,.99],
    max_daily_moving_minutes:["每日移動上限（分）",1,null], max_daily_elapsed_minutes:["每日總耗時上限（分）",1,null],
    rest_every_moving_minutes:["每移動多久休息（分）",1,null], rest_duration_minutes:["每次休息（分）",1,null],
    minimum_overnight_minutes:["最少過夜休息（分）",1,null], party_size:["估時隊伍人數",1,null], max_days:["最多天數",1,null],
    daylight_margin_minutes:["日照餘裕（分）",0,null]
  };
  const timingBooleans = {require_daylight:"要求在提供的日照區間內移動", auto_schedule_camps:"從候選營地安排分日",
    require_camp_water:"候選營地必須有現地水源", use_assumptions_for_missing_members:"明示用以上假設補足未知成員係數"};
  let sequence = 0;

  function freshReview() {
    return {target:"", loaded:false, attempted:false, busy:false, dirty:false, confirmed:false, record:null, requestId:0,
      declaredBy:"", declaredAt:"", teamSize:"", goals:"", routeEvidenceIds:"", mapUsers:"", navigation:{}, readiness:{},
      sections:Object.fromEntries(Object.entries(sections).map(([key, spec]) => [key, pretty(spec.fallback)])),
      status:"尚未讀取此版本補件；所有未填條件維持未知。", command:null};
  }
  function freshTiming() {
    return {enabled:false, fields:{uncertainty_fraction:"0.25", daylight_margin_minutes:"0"}, flags:{}, nextDeparture:"",
      assumptionLabel:"人工規劃假設；尚未證明個人實際能力", advanced:pretty({team_members:[], source_refs:[], daylight_windows:[], campsite_candidates:[], surface_time_multipliers:{unspecified:1.0}})};
  }
  function createState() {
    return {review:freshReview(), timing:freshTiming(), intent:{result:null, key:"", status:"尚未解析原文。", busy:false, useModel:false, useDraft:false, draftJson:"", edits:{}, requestId:0}, downloads:{}};
  }
  function workflow(state) { return state.workflow || (state.workflow = createState()); }
  function binding(state) {
    const manifest = state.saved?.manifest || state.saved || {};
    return {project_id:state.projectId, version_id:state.saved?.version_id || manifest.version_id || "",
      manifest_sha256:state.saved?.manifest_sha256 || manifest.manifest_sha256 || "",
      geometry_sha256:manifest.geometry_sha256 || state.saved?.preview?.geometry_sha256 || "",
      itinerary_sha256:manifest.itinerary_sha256 || state.saved?.preview?.itinerary_sha256 || ""};
  }
  function matches(expected, actual) {
    return Boolean(actual) && Object.entries(expected).every(([key, value]) => Boolean(value) && actual[key] === value);
  }
  function sync(state) {
    const work = workflow(state), expected = binding(state), target = Object.values(expected).join(":");
    if (work.review.target !== target) {
      const next = freshReview(); next.target = target; next.requestId = work.review.requestId + 1;
      work.review = next; work.downloads = {};
    }
    return work;
  }
  function contextSha(state) { return sync(state).review.record?.context_sha256 || null; }
  function contextReady(state) { const r = sync(state).review; return r.loaded && !r.busy && !r.dirty; }
  function contextMatchesJob(state, job) {
    const current = sync(state).review.record?.context_sha256 || null;
    const observed = job?.review_context_sha256 ?? job?.binding?.review_context_sha256 ?? null;
    return current === observed && (job?.binding?.review_context_sha256 ?? null) === current;
  }
  function intentKey(state) {
    return JSON.stringify([state.text, state.departure, state.timezone,
      Object.entries(state.nameResolutions || {}).sort(([a],[b]) => a.localeCompare(b)), state.catalog?.source_snapshot_sha256 || null]);
  }
  function invalidateIntent(state) {
    const intent = workflow(state).intent;
    if (intent.key && intent.key !== intentKey(state)) {
      intent.result = null; intent.useDraft = false; intent.draftJson = ""; intent.edits = {}; intent.key = "";
      intent.status = "原文、日期、地名或來源已變更；請重新解析。"; intent.requestId += 1; intent.busy = false;
    }
  }
  function parseJson(raw, expected, label) {
    let result;
    try { result = JSON.parse(raw); } catch (_) { throw new Error(`${label} 必須是有效 JSON。`); }
    if (expected === "array" ? !Array.isArray(result) : !result || typeof result !== "object" || Array.isArray(result)) throw new Error(`${label} 必須是 ${expected === "array" ? "JSON 陣列" : "JSON 物件"}。`);
    return result;
  }
  function numeric(raw, label, integer = false) {
    if (raw === "" || raw == null) return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0 || (integer && !Number.isInteger(value))) throw new Error(`${label} 需要有效${integer ? "整數" : "數值"}。`);
    return value;
  }
  function aware(value, label) {
    if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error(`${label} 需含日期、時間與明確時區。`);
    return value;
  }
  function tri(value) { return value === "true" ? true : value === "false" ? false : null; }
  function triSelect(field, label, value, group) {
    const selected = value === true ? "true" : value === false ? "false" : "unknown";
    return `<label>${esc(label)}<select data-planned-context-${group}="${field}">${[["unknown","未知／尚未確認"],["true","是／已確認"],["false","否／尚未具備"]].map(([key,text]) => `<option value="${key}" ${selected === key ? "selected" : ""}>${text}</option>`).join("")}</select></label>`;
  }
  function buildDeclaration(state) {
    const r = sync(state).review;
    if (!r.declaredBy.trim()) throw new Error("請填寫實際聲明者代號。");
    const declaration = {declared_by:r.declaredBy.trim(), declared_at:aware(r.declaredAt.trim(),"聲明時間"), team_size:numeric(r.teamSize,"隊伍人數",true),
      navigation:Object.fromEntries(Object.keys(navFields).map(key => [key, r.navigation[key] ?? null])),
      readiness:Object.fromEntries(Object.keys(readinessFields).map(key => [key, r.readiness[key] ?? null])),
      goals:r.goals.split(/\r?\n/).map(s => s.trim()).filter(Boolean), route_condition_evidence_ids:r.routeEvidenceIds.split(/[,\n]/).map(s => s.trim()).filter(Boolean)};
    declaration.navigation.team_map_user_count = numeric(r.mapUsers,"地圖使用人數",true);
    for (const [key, spec] of Object.entries(sections)) declaration[key] = parseJson(r.sections[key], Array.isArray(spec.fallback) ? "array" : "object",spec.label);
    return declaration;
  }
  function reviewPayload(state) {
    const r = sync(state).review, expected = binding(state);
    if (!Object.values(expected).every(Boolean) || !r.loaded) throw new Error("請先讀取並核對完整的保存版本與補件。");
    if (!r.confirmed) throw new Error("請明確確認本次同版聲明後再保存。");
    const body = {version_id:expected.version_id, expected_manifest_sha256:expected.manifest_sha256,
      expected_geometry_sha256:expected.geometry_sha256, expected_itinerary_sha256:expected.itinerary_sha256,
      expected_parent_revision_id:r.record?.revision_id || null, declaration:buildDeclaration(state), explicit_confirmation:true};
    const signature = JSON.stringify(body);
    if (!r.command || r.command.signature !== signature) r.command = {signature, key:`planned-context-${global.crypto?.randomUUID?.() || `${Date.now()}-${++sequence}`}`};
    return {...body, idempotency_key:r.command.key};
  }
  function acceptContext(state, record) {
    const r = sync(state).review, expected = binding(state);
    if (record && (!matches(expected,record.subject_binding) || record.version_id !== expected.version_id || record.is_current !== true
      || record.candidate_only !== true || record.runtime_safety_truth !== false || !record.context_sha256)) throw new Error("補件回應未通過目前專案、版本與來源雜湊核對。");
    const declaration = record?.declaration || {};
    r.record = record || null; r.loaded = true; r.dirty = false; r.confirmed = false; r.command = null;
    r.declaredBy = declaration.declared_by || ""; r.declaredAt = declaration.declared_at || "";
    r.teamSize = declaration.team_size == null ? "" : String(declaration.team_size);
    r.goals = array(declaration.goals).join("\n"); r.routeEvidenceIds = array(declaration.route_condition_evidence_ids).join(", ");
    r.navigation = copy(declaration.navigation || {}); r.readiness = copy(declaration.readiness || {});
    r.mapUsers = declaration.navigation?.team_map_user_count == null ? "" : String(declaration.navigation.team_map_user_count);
    r.sections = Object.fromEntries(Object.entries(sections).map(([key,spec]) => [key,pretty(declaration[key] ?? spec.fallback)]));
    r.status = record ? `已讀取 ${record.revision_id} · SHA ${record.context_sha256}；已保存資料與新草稿分開。` : "此版本尚無補件；空白與未知將原樣保存。";
  }
  async function loadContext(state, api, explicit = false) {
    const r = sync(state).review, expected = binding(state), target = r.target;
    if (!expected.version_id || r.busy || (r.loaded && !explicit)) return;
    const id = ++r.requestId;
    r.busy = true; r.attempted = true; r.status = "正在核對此版本補件…"; api.refresh();
    try {
      const response = await api.fetchJson(`versions/${encodeURIComponent(expected.version_id)}/review-context`);
      if (!api.live() || workflow(state).review !== r || r.requestId !== id || r.target !== target) return;
      acceptContext(state, Object.hasOwn(response || {},"context") ? response.context : response);
    } catch (error) { if (api.live() && workflow(state).review === r && r.requestId === id) r.status = `補件讀取失敗：${error.message || error}`; }
    finally { if (api.live() && workflow(state).review === r && r.requestId === id) { r.busy = false; api.refresh(); } }
  }
  async function saveContext(state, api) {
    const r = sync(state).review;
    if (r.busy) return;
    let payload;
    try { payload = reviewPayload(state); } catch (error) { r.status = error.message; api.refresh(); return; }
    const target = r.target, id = ++r.requestId;
    r.busy = true; r.status = "正在保存明示的同版補件…"; api.refresh();
    try {
      const response = await api.postJson("review-context",payload);
      if (!api.live() || workflow(state).review !== r || r.target !== target || r.requestId !== id) return;
      const record = Object.hasOwn(response || {},"context") ? response.context : response;
      acceptContext(state,record);
      r.status = `已保存 ${record.revision_id}；舊六力與綜合報告已過期，請建立使用此補件的新作業。`;
      try { await api.afterContextSaved(record); }
      catch (error) { if (api.live()) r.status += ` 補件已保存；主體重讀失敗：${error.message || error}`; }
    } catch (error) { if (api.live() && workflow(state).review === r && r.requestId === id) r.status = `補件未完成：${error.message || error}。重試同一內容會沿用原請求識別。`; }
    finally { if (api.live() && workflow(state).review === r && r.requestId === id) { r.busy = false; api.refresh(); } }
  }
  function timingRequest(state) {
    const timing = workflow(state).timing;
    if (!timing.enabled) return null;
    const result = parseJson(timing.advanced,"object","地形估時進階欄位");
    for (const key of [...Object.keys(timingFields),...Object.keys(timingBooleans),"next_day_departure_time","assumption_label"]) {
      if (Object.hasOwn(result,key)) throw new Error(`${key} 請在上方估時表單填寫，避免兩份欄位互相覆蓋。`);
    }
    for (const [key,[label,min,max]] of Object.entries(timingFields)) {
      const value = numeric(timing.fields[key],label,["party_size","max_days"].includes(key));
      if (value !== null) {
        if (value < min || (max !== null && value > max)) throw new Error(`${label} 超出欄位範圍。`);
        result[key] = value;
      }
    }
    for (const key of Object.keys(timingBooleans)) result[key] = timing.flags[key] === true;
    if (timing.nextDeparture) result.next_day_departure_time = timing.nextDeparture;
    result.assumption_label = timing.assumptionLabel;
    return result;
  }
  function requestExtras(state) {
    invalidateIntent(state);
    const result = {}, work = workflow(state), timing = timingRequest(state);
    if (timing) result.terrain_timing = timing;
    if (work.intent.useDraft && work.intent.result?.validated_draft && work.intent.key === intentKey(state)) {
      result.intent_draft = parseJson(work.intent.draftJson,"object","解析草稿");
      result.intent_input_sha256 = work.intent.result.input_sha256;
      result.source_snapshot_sha256 = work.intent.result.source_snapshot_sha256;
    }
    return result;
  }
  function restoreRequest(state, request) {
    const work = workflow(state), options = request.terrain_timing;
    work.timing = freshTiming();
    if (options) {
      work.timing.enabled = true;
      const advanced = copy(options);
      for (const key of Object.keys(timingFields)) { work.timing.fields[key] = options[key] == null ? "" : String(options[key]); delete advanced[key]; }
      for (const key of Object.keys(timingBooleans)) { work.timing.flags[key] = options[key] === true; delete advanced[key]; }
      work.timing.nextDeparture = options.next_day_departure_time || ""; delete advanced.next_day_departure_time;
      work.timing.assumptionLabel = options.assumption_label || ""; delete advanced.assumption_label;
      work.timing.advanced = pretty(advanced);
    }
    work.intent = {...createState().intent};
    if (request.intent_draft) {
      work.intent.result = {validated_draft:copy(request.intent_draft), input_sha256:request.intent_input_sha256,
        source_snapshot_sha256:request.source_snapshot_sha256, status:"restored", clauses:[], issues:[]};
      work.intent.key = intentKey(state); work.intent.draftJson = pretty(request.intent_draft); work.intent.useDraft = true;
      work.intent.useDraft = request.source_snapshot_sha256 === state.catalog?.source_snapshot_sha256;
      work.intent.status = work.intent.useDraft ? "已恢復保存版本的已綁定解析草稿；未再呼叫模型。" : "保存草稿的來源已變更；請重新解析原文。";
    }
  }
  async function parseIntent(state, api) {
    const intent = workflow(state).intent;
    if (intent.busy || !state.text.trim() || !state.catalog) return;
    const key = intentKey(state), id = ++intent.requestId;
    intent.busy = true; intent.useDraft = false; intent.status = "正在解析原文、日序與地名…"; api.refresh();
    try {
      const payload = {human_text:state.text, name_resolutions:copy(state.nameResolutions || {}), use_configured_model:intent.useModel === true};
      if (state.departure) payload.departure_at = api.dateTime(state.departure,state.timezone);
      const response = await api.postJson("intent",payload), result = response.intent || response;
      if (!api.live() || id !== intent.requestId || key !== intentKey(state)) return;
      if (!result.input_sha256 || result.source_snapshot_sha256 !== state.catalog.source_snapshot_sha256) throw new Error("解析回應來源與目前目錄不一致。");
      intent.result = result; intent.key = key; intent.draftJson = result.validated_draft ? pretty(result.validated_draft) : ""; intent.edits = {};
      intent.status = `${result.status} · ${array(result.clauses).length} 句 · ${array(result.unresolved_clause_ids).length} 句待釐清 · ${result.mode || "deterministic"}`;
    } catch (error) { if (api.live() && id === intent.requestId) { intent.result = null; intent.key = ""; intent.status = `解析失敗：${error.message || error}`; } }
    finally { if (api.live() && id === intent.requestId) { intent.busy = false; api.refresh(); } }
  }
  function replaceClause(state, clauseId) {
    const intent = workflow(state).intent, clause = array(intent.result?.clauses).find(row => row.clause_id === clauseId);
    if (!clause || intent.key !== intentKey(state)) throw new Error("原文已變更，請先重新解析。");
    const chars = Array.from(state.text), span = clause.source_span;
    if (!span || chars.slice(span.start,span.end).join("") !== clause.source_text) throw new Error("此句來源範圍已變更，未套用修訂。");
    const replacement = intent.edits[clauseId] ?? clause.source_text;
    if (!replacement.trim()) throw new Error("修訂句不能留空；請明確描述希望保留的行程。");
    return [...chars.slice(0,span.start),...Array.from(replacement),...chars.slice(span.end)].join("");
  }
  function jsonSection(key, r) {
    const spec = sections[key];
    return `<details class="planned-context-json"><summary>${esc(spec.label)} · JSON</summary>
      <label>${esc(spec.label)}<textarea data-planned-context-json="${key}" rows="${key === "permission_reviews" ? 10 : 6}" spellcheck="false">${esc(r.sections[key])}</textarea></label>
      <details><summary>查看欄位範例（不會自動填入）</summary><pre>${esc(pretty(spec.example))}</pre></details></details>`;
  }
  function renderSupplement(state) {
    const work = sync(state), r = work.review, expected = binding(state);
    if (!expected.version_id) return "";
    return `<section class="planned-review planned-context" data-planned-review-context="${esc(expected.version_id)}" data-planned-context-sha="${esc(r.record?.context_sha256 || "")}">
      <h3>此 Planned 版本的補件與審查資料</h3><p>保存完整聲明，綁定此版幾何與時程。更新補件後，舊作業結果需重新計算。</p>
      <p><code>${esc(expected.version_id)}</code> · ${r.dirty ? "有未保存編輯" : "使用已讀取版本"}</p>
      <div class="planned-grid"><label>實際聲明者代號<input data-planned-context-field="declaredBy" value="${esc(r.declaredBy)}" autocomplete="off"></label>
      <label>聲明時間（ISO 與時區）<input data-planned-context-field="declaredAt" value="${esc(r.declaredAt)}" placeholder="2026-10-01T06:00:00+08:00"></label>
      <label>隊伍人數<input type="number" min="1" step="1" data-planned-context-field="teamSize" value="${esc(r.teamSize)}"></label>
      <label>會使用地圖的人數<input type="number" min="0" step="1" data-planned-context-field="mapUsers" value="${esc(r.mapUsers)}"></label></div>
      <details open><summary>八項 Navigation 人工確認</summary><div class="planned-grid">${Object.entries(navFields).map(([key,label]) => triSelect(key,label,r.navigation[key],"navigation")).join("")}</div></details>
      <details><summary>共同準備狀態</summary><div class="planned-grid">${Object.entries(readinessFields).map(([key,label]) => triSelect(key,label,r.readiness[key],"readiness")).join("")}</div></details>
      <label>本次目標（每行一項）<textarea data-planned-context-field="goals" rows="3">${esc(r.goals)}</textarea></label>
      <label>路況來源 evidence ID（逗號分隔）<input data-planned-context-field="routeEvidenceIds" value="${esc(r.routeEvidenceIds)}"></label>
      ${Object.keys(sections).map(key => jsonSection(key,r)).join("")}
      <p class="status">review.status 預設 pending。填寫 reviewed／rejected 時須自行提供實際 reviewer_alias、reviewed_at、conclusion 與 evidence_ids；來源 SHA 由伺服器核對。</p>
      <label class="planned-check"><input type="checkbox" data-planned-context-confirm="true" ${r.confirmed ? "checked" : ""} ${r.busy ? "disabled" : ""}>我確認以上是此版本的完整人工聲明，未填項目維持未知</label>
      <div class="permission-authoring-actions"><button type="button" class="permission-button" data-planned-context-action="load" ${r.busy ? "disabled" : ""}>重新讀取補件（取代未保存編輯）</button>
      <button type="button" class="permission-button" data-planned-context-action="save" ${r.busy || !r.loaded || !r.confirmed ? "disabled" : ""}>保存此版補件</button></div>
      <p role="status" data-planned-context-status="true">${esc(r.status)}</p>
      <details><summary>目前版本與補件綁定</summary><pre>${esc(pretty({binding:expected, revision_id:r.record?.revision_id || null, context_sha256:r.record?.context_sha256 || null, source_hashes:r.record?.source_hashes || {}}))}</pre></details>
    </section>`;
  }
  function renderInputs(state) {
    const work = workflow(state), timing = work.timing, intent = work.intent, result = intent.result;
    return `<section class="planned-review planned-intent" data-planned-intent="true"><h4>原文解析與逐句釐清</h4>
      <label class="planned-check"><input type="checkbox" data-planned-intent-model="true" ${intent.useModel ? "checked" : ""}>使用已設定模型協助產生可核對草稿</label>
      <button type="button" class="permission-button" data-planned-intent-action="parse" ${intent.busy || state.busy || !state.catalog || !state.text.trim() ? "disabled" : ""}>解析人工行程</button>
      <p role="status" data-planned-intent-status="true">${esc(intent.status)}</p>
      ${result ? `<div data-planned-intent-result="${esc(result.input_sha256)}"><p>來源 ${esc(result.source_snapshot_sha256)} · ${esc(result.status)}</p>
        ${array(result.clauses).map(clause => `<details class="planned-intent-clause" open data-planned-intent-clause="${esc(clause.clause_id)}"><summary>${esc(clause.clause_id)} · ${esc(clause.status)}</summary>
          <label>原句／修訂句<textarea data-planned-intent-clause-edit="${esc(clause.clause_id)}" rows="2">${esc(intent.edits[clause.clause_id] ?? clause.source_text)}</textarea></label>
          <p>來源字元 ${esc(clause.source_span?.start)}–${esc(clause.source_span?.end)} · 操作 ${esc(array(clause.operation_indices).join(", "))}</p>
          ${array(result.issues).filter(issue => issue.clause_id === clause.clause_id).map(issue => `<div class="planned-issues"><p>${esc(issue.code)} · ${esc(issue.message)}</p>${issue.choices ? `<pre>${esc(pretty(issue.choices))}</pre>` : ""}</div>`).join("")}
          <button type="button" class="permission-button" data-planned-intent-action="replace-clause" data-planned-clause-id="${esc(clause.clause_id)}" ${intent.busy ? "disabled" : ""}>套用此句修訂並重新解析</button></details>`).join("")}
        ${array(result.issues).filter(issue => !issue.clause_id).map(issue => `<p class="planned-issues">${esc(issue.code)} · ${esc(issue.message)}</p>`).join("")}
        <details open><summary>日序、操作與衍生限制</summary><pre>${esc(pretty({operations:result.operations,route_intents:result.route_intents,derived_constraints:result.derived_constraints,pending_conditions:result.pending_conditions,unresolved_clause_ids:result.unresolved_clause_ids}))}</pre></details>
        ${result.validated_draft ? `<label>可核對的模型草稿 JSON<textarea data-planned-intent-draft="true" rows="8" spellcheck="false">${esc(intent.draftJson)}</textarea></label>
          <button type="button" class="permission-button" data-planned-intent-action="apply-draft" ${intent.busy ? "disabled" : ""}>採用此解析草稿供預覽</button><p>${intent.useDraft ? "此草稿將隨原文與來源雜湊送交編譯器再核對。" : "尚未採用模型草稿。"}</p>` : ""}</div>` : ""}
    </section><details class="planned-review planned-terrain" data-planned-terrain-options="true"><summary>地形、隊伍與分日估時</summary>
      <label class="planned-check"><input type="checkbox" data-planned-timing-enabled="true" ${timing.enabled ? "checked" : ""}>啟用此版的地形與隊伍估時</label>
      <p>假設值只供規劃；缺少地形或成員係數時，耗時保留未知。區間為情境範圍，不是統計信賴區間。</p>
      <div class="planned-grid">${Object.entries(timingFields).map(([key,[label,min,max]]) => `<label>${esc(label)}<input type="number" min="${min}" ${max == null ? "" : `max="${max}"`} step="${["party_size","max_days"].includes(key) ? "1" : "any"}" data-planned-timing-field="${key}" value="${esc(timing.fields[key] || "")}" placeholder="未知"></label>`).join("")}
      <label>隔日啟程 HH:MM<input type="time" data-planned-timing-next-departure="true" value="${esc(timing.nextDeparture)}"></label></div>
      ${Object.entries(timingBooleans).map(([key,label]) => `<label class="planned-check"><input type="checkbox" data-planned-timing-flag="${key}" ${timing.flags[key] ? "checked" : ""}>${esc(label)}</label>`).join("")}
      <label>估時假設說明<input data-planned-timing-assumption="true" value="${esc(timing.assumptionLabel)}"></label>
      <label>其他估時欄位 JSON（隊伍係數、日照來源、候選營地、地面倍率）<textarea data-planned-timing-advanced="true" rows="10" spellcheck="false">${esc(timing.advanced)}</textarea></label>
      <p class="status">候選營地須提供 point_index；water_available、capacity_persons、legal_use、overnight_suitable 未知請留 null。日照需 sunrise_at、sunset_at 與 source_ref。TRH 成本不作步行時數。</p>
    </details>`;
  }
  function reportMatches(job, expected, currentContext = null) {
    const entry = job?.pretrip_report, report = entry?.report;
    const context = job?.binding?.review_context_sha256 ?? job?.review_context_sha256 ?? null;
    return Boolean(entry && report && ["completed","completed_with_gaps"].includes(job.status)
      && job.project_id === expected.project_id && job.version_id === expected.version_id && job.manifest_sha256 === expected.manifest_sha256 && matches(expected,job.binding)
      && job.candidate_only === true && job.runtime_safety_truth === false
      && matches(expected,entry.input_binding) && matches(expected,report.input_binding) && context === currentContext
      && (entry.input_binding.review_context_sha256 ?? null) === context && (report.input_binding.review_context_sha256 ?? null) === context
      && (!entry.input_binding.run_id || entry.input_binding.run_id === job.run_id)
      && (!report.input_binding.run_id || report.input_binding.run_id === job.run_id)
      && entry.artifact_ref && entry.artifact_sha256 && entry.candidate_only === true && entry.runtime_safety_truth === false
      && report.candidate_only === true && report.runtime_safety_truth === false);
  }
  function reportHtml(state, job, expected = binding(state), currentContext = contextSha(state)) {
    if (!job?.pretrip_report) return "";
    if (!reportMatches(job,expected,currentContext)) return '<section class="planned-issues" data-planned-pretrip-report-pending="true"><h4>同版行前綜合報告</h4><p>報告與目前路線、時程或補件綁定不同，暫不作本版結果。</p></section>';
    const entry = job.pretrip_report, report = entry.report, outputs = report.required_outputs || {};
    const list = values => array(values).length ? `<ul>${values.map(value => `<li>${esc(typeof value === "string" ? value : pretty(value))}</li>`).join("")}</ul>` : '<p>尚無資料／候選。</p>';
    const output = (key,label) => `<details data-planned-report-output="${key}"><summary>${label}</summary><pre>${esc(pretty(outputs[key] ?? null))}</pre></details>`;
    const download = workflow(state).downloads[`${job.run_id}:${entry.artifact_sha256}`];
    return `<section class="planned-review planned-pretrip-report" data-planned-pretrip-report="${esc(job.run_id)}" data-planned-report-sha="${esc(entry.artifact_sha256)}" data-planned-report-context="${esc(currentContext || "")}">
      <h3>同版行前綜合報告</h3><p data-planned-report-decision="${esc(report.decision)}">候選規劃建議：${esc(report.decision)} · 完整度 ${esc(report.status)}</p>
      <p>${esc(job.version_id)} · ${esc(job.run_id)} · 補件 ${esc(currentContext || "未提供")}</p>
      <h4>前三大風險來源</h4>${list(outputs.top_risk_sources)}<h4>必補條件</h4>${list(outputs.required_conditions)}
      ${output("cp_graph","CP graph 與路段")}${output("latest_turnaround","最晚折返時刻與依據")}
      ${output("suggested_stop_points","建議停留點與時間限制")}${output("not_recommended_stop_points","不建議停留位置／待查限制")}
      <h4>替代方案與短版候選</h4>${list(outputs.alternatives_or_short_routes)}${output("pretrip_checklist","行前 checklist")}
      <h4>剩餘風險</h4>${list(outputs.residual_risk)}
      <details><summary>時程、回程與營地條件</summary><pre>${esc(pretty({planned_timetable:report.planned_timetable,return_constraint:report.return_constraint,camp_candidates:report.camp_candidates,missing_inputs:report.missing_inputs}))}</pre></details>
      <p><code>${esc(entry.artifact_ref)}</code><br>SHA-256：<code>${esc(entry.artifact_sha256)}</code></p>
      <button type="button" class="permission-button" data-planned-report-download="${esc(job.run_id)}" ${download?.busy ? "disabled" : ""}>核對並下載完整行前報告</button>
      <p role="status" data-planned-report-download-status="true">${esc(download?.message || "尚未下載")}</p>
      <p class="status">此報告為候選行前評估；人工補件與報告生成不授予出發許可。runtime safety truth=false。</p></section>`;
  }
  async function downloadReport(state, api, job) {
    const expected = binding(state), currentContext = contextSha(state), entry = job?.pretrip_report;
    if (!reportMatches(job,expected,currentContext)) return;
    const key = `${job.run_id}:${entry.artifact_sha256}`, records = workflow(state).downloads;
    if (records[key]?.busy) return;
    records[key] = {busy:true,message:"正在讀取並核對報告 SHA-256…"}; api.refreshRun();
    let url;
    try {
      const response = await global.fetch(api.url(`analysis-runs/${encodeURIComponent(job.run_id)}/artifact?ref=${encodeURIComponent(entry.artifact_ref)}`),{credentials:"same-origin",cache:"no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = await response.arrayBuffer();
      if (!global.crypto?.subtle) throw new Error("此瀏覽器缺少 SHA-256 核對能力。");
      const digest = Array.from(new Uint8Array(await global.crypto.subtle.digest("SHA-256",bytes))).map(value => value.toString(16).padStart(2,"0")).join("");
      if (digest !== entry.artifact_sha256 || !api.live() || !matches(expected,binding(state)) || contextSha(state) !== currentContext) throw new Error("報告內容或目前版本已變更，下載未套用。");
      url = global.URL.createObjectURL(new global.Blob([bytes],{type:"application/json"}));
      const link = global.document.createElement("a"); link.href = url; link.download = `${job.version_id}.pretrip-report.json`;
      global.document.body.appendChild(link); link.click(); link.remove();
      records[key] = {busy:false,message:`SHA-256 核對通過，已觸發 ${bytes.byteLength} bytes 報告下載。`,sha256:digest,byte_count:bytes.byteLength};
    } catch (error) { records[key] = {busy:false,message:`報告下載未完成：${error.message || error}`}; }
    finally { if (url) global.setTimeout(() => global.URL.revokeObjectURL(url),30000); if (api.live()) api.refreshRun(); }
  }
  function installStyle() {
    if (global.document.getElementById("plannedReviewInputStyle")) return;
    const style = global.document.createElement("style"); style.id = "plannedReviewInputStyle";
    style.textContent = ".planned-context label,.planned-terrain label,.planned-intent label{display:grid;gap:.4rem;margin:.6rem 0}.planned-context textarea,.planned-terrain textarea,.planned-intent textarea{box-sizing:border-box;max-width:100%;width:100%;min-height:4.5rem;padding:.65rem;border:1px solid #8997a5;border-radius:.35rem;background:#fff;color:#102938;font:inherit}.planned-context-json textarea,.planned-terrain [data-planned-timing-advanced],.planned-intent [data-planned-intent-draft]{font-family:ui-monospace,monospace;font-size:.9rem}.planned-context input,.planned-context select,.planned-terrain input{box-sizing:border-box;max-width:100%;min-width:0;padding:.45rem;background:#fff;color:#102938;border:1px solid #8997a5;border-radius:.3rem}.planned-context .planned-check,.planned-terrain .planned-check,.planned-intent .planned-check{display:flex;align-items:flex-start;gap:.6rem}.planned-context .planned-check input,.planned-terrain .planned-check input,.planned-intent .planned-check input{flex:none;margin-top:.25rem}.planned-context pre,.planned-intent pre,.planned-pretrip-report pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:32rem;overflow:auto}.planned-context summary,.planned-terrain summary,.planned-intent summary{cursor:pointer;padding:.5rem 0}.planned-context-json,.planned-intent-clause{border-top:1px solid #748493;padding:.4rem 0}.planned-pretrip-report li{overflow-wrap:anywhere;margin:.4rem 0}.planned-review button:focus-visible,.planned-review input:focus-visible,.planned-review textarea:focus-visible,.planned-review select:focus-visible{outline:3px solid #2e85d3;outline-offset:2px}";
    global.document.head.appendChild(style);
  }
  function updateContextControls(root,r) {
    const save = root.querySelector('[data-planned-context-action="save"]'); if (save) save.disabled = r.busy || !r.loaded || !r.confirmed;
    const check = root.querySelector("[data-planned-context-confirm]"); if (check) check.checked = r.confirmed;
    const status = root.querySelector("[data-planned-context-status]"); if (status) status.textContent = r.status;
  }
  function bind(root,state,api) {
    installStyle(); const work = sync(state), r = work.review;
    const context = root.querySelector("[data-planned-review-context]");
    if (context && context.dataset.plannedContextBound !== "true") {
      context.dataset.plannedContextBound = "true";
      const edited = () => { r.dirty = true; r.confirmed = false; r.status = "有未保存補件；勾選確認後保存完整聲明。"; updateContextControls(context,r); api.updateButtons(); };
      context.querySelectorAll("[data-planned-context-field]").forEach(input => input.addEventListener("input",() => { r[input.dataset.plannedContextField] = input.value; edited(); }));
      context.querySelectorAll("[data-planned-context-json]").forEach(input => input.addEventListener("input",() => { r.sections[input.dataset.plannedContextJson] = input.value; edited(); }));
      for (const group of ["navigation","readiness"]) context.querySelectorAll(`[data-planned-context-${group}]`).forEach(input => input.addEventListener("change",() => { r[group][input.dataset[group === "navigation" ? "plannedContextNavigation" : "plannedContextReadiness"]] = tri(input.value); edited(); }));
      context.querySelector("[data-planned-context-confirm]").addEventListener("change",event => { r.confirmed = event.currentTarget.checked; updateContextControls(context,r); });
      context.querySelectorAll("[data-planned-context-action]").forEach(control => control.addEventListener("click",() => { if (!control.disabled) void (control.dataset.plannedContextAction === "load" ? loadContext(state,api,true) : saveContext(state,api)); }));
      if (r.busy) context.querySelectorAll("input,textarea,select").forEach(input => { input.disabled = true; });
      if (!r.loaded && !r.attempted && !r.busy) void loadContext(state,api);
    }
    const terrain = root.querySelector("[data-planned-terrain-options]");
    if (terrain && terrain.dataset.plannedTimingBound !== "true") {
      terrain.dataset.plannedTimingBound = "true";
      terrain.querySelector("[data-planned-timing-enabled]").addEventListener("change",event => { work.timing.enabled = event.currentTarget.checked; api.changed(false); });
      terrain.querySelectorAll("[data-planned-timing-field]").forEach(input => input.addEventListener("input",() => { work.timing.fields[input.dataset.plannedTimingField] = input.value; api.changed(false); }));
      terrain.querySelectorAll("[data-planned-timing-flag]").forEach(input => input.addEventListener("change",() => { work.timing.flags[input.dataset.plannedTimingFlag] = input.checked; api.changed(false); }));
      for (const [selector,field] of [["[data-planned-timing-next-departure]","nextDeparture"],["[data-planned-timing-assumption]","assumptionLabel"],["[data-planned-timing-advanced]","advanced"]]) terrain.querySelector(selector).addEventListener("input",event => { work.timing[field] = event.currentTarget.value; api.changed(false); });
    }
    const intentPanel = root.querySelector("[data-planned-intent]");
    if (intentPanel && intentPanel.dataset.plannedIntentBound !== "true") {
      intentPanel.dataset.plannedIntentBound = "true";
      intentPanel.querySelector("[data-planned-intent-model]").addEventListener("change",event => { work.intent.useModel = event.currentTarget.checked; });
      intentPanel.querySelectorAll("[data-planned-intent-clause-edit]").forEach(input => input.addEventListener("input",() => { work.intent.edits[input.dataset.plannedIntentClauseEdit] = input.value; }));
      intentPanel.querySelector("[data-planned-intent-draft]")?.addEventListener("input",event => { work.intent.draftJson = event.currentTarget.value; work.intent.useDraft = false; api.changed(false); });
      intentPanel.querySelectorAll("[data-planned-intent-action]").forEach(control => control.addEventListener("click",() => {
        if (control.disabled) return;
        try {
          if (control.dataset.plannedIntentAction === "replace-clause") { state.text = replaceClause(state,control.dataset.plannedClauseId); api.changed(false); void parseIntent(state,api); }
          else if (control.dataset.plannedIntentAction === "apply-draft") { parseJson(work.intent.draftJson,"object","解析草稿"); work.intent.useDraft = true; api.changed(); }
          else void parseIntent(state,api);
        } catch (error) { work.intent.status = error.message; api.refresh(); }
      }));
    }
    root.querySelectorAll("[data-planned-report-download]").forEach(control => {
      if (control.dataset.plannedDownloadBound === "true") return;
      control.dataset.plannedDownloadBound = "true";
      control.addEventListener("click",() => { if (!control.disabled && state.analysisRun?.run_id === control.dataset.plannedReportDownload) void downloadReport(state,api,state.analysisRun); });
    });
  }
  function updateInputControls(root,state) {
    const intent = workflow(state).intent, control = root?.querySelector('[data-planned-intent-action="parse"]');
    if (control) control.disabled = intent.busy || state.busy || !state.catalog || !state.text.trim();
    const status = root?.querySelector("[data-planned-intent-status]"); if (status) status.textContent = intent.status;
    if (!intent.result) root?.querySelector("[data-planned-intent-result]")?.remove();
  }
  global.ScoutPlannedReviewUI = {createState,binding,matches,sync,contextSha,contextReady,contextMatchesJob,invalidateIntent,requestExtras,
    restoreRequest,renderInputs,renderSupplement,reportHtml,bind,updateInputControls,
    // Pure request builders and guards are also used by the focused DOM tests.
    buildDeclaration,reviewPayload,acceptContext,timingRequest,replaceClause,reportMatches};
})(typeof window === "undefined" ? globalThis : window);
