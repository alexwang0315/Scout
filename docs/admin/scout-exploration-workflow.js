/* AOI-first exploration: every write follows an explicit visible action.
 * Host: apiGet(path), apiPost(path, body), onProjectCreated(projectId, receipt),
 * refresh(). Routes are mounted below /admin. GET restoration never dispatches.
 */
(function (global) {
  "use strict";
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const arr = value => Array.isArray(value) ? value : [];
  const initialForm = () => ({projectId:"", intent:"", crs:"EPSG:4326", west:"", south:"", east:"", north:"",
    startX:"", startY:"", endX:"", endY:"", waypoints:"", days:"", speed:"", dailyHours:"", rest:"",
    departure:"", arrival:"", dtmDirs:"", assumptions:""});
  let current = null, sequence = 0, host = null, elementRoot = null;
  const fresh = id => ({projectId:id, epoch:++sequence, form:initialForm(), receipt:null, catalog:null, trh:null,
    busy:false, restored:false, status:"尚無 Ref. GPX 時，先提供研究區域與目的。起訖點可暫留空白。"});
  function ensure(id) { if (!current || current.projectId !== String(id || "")) current = fresh(String(id || "")); return current; }
  const live = state => current === state;
  function redraw() {
    if (host?.refresh) host.refresh();
    else if (elementRoot) { const parent = elementRoot.parentElement; elementRoot.outerHTML = render({projectId:current.projectId}); if (parent) bind(parent, host); }
  }
  const path = (state, suffix = "") => `/admin/pretrip/projects/${encodeURIComponent(state.projectId)}/exploration${suffix}`;
  const button = (action, text, enabled = true) => `<button type="button" class="permission-button" data-exploration-action="${action}" ${enabled ? "" : "disabled"}>${esc(text)}</button>`;
  const number = (value, label, optional = false) => {
    if (String(value).trim() === "") { if (optional) return undefined; throw Error(`${label}尚未填寫。`); }
    const parsed = Number(value); if (!Number.isFinite(parsed)) throw Error(`${label}必須是有效數字。`); return parsed;
  };
  function field(state, key, label, type = "text", placeholder = "") {
    return `<label style="display:grid;gap:.3rem">${esc(label)}<input type="${type}" data-exploration-field="${key}" value="${esc(state.form[key])}" placeholder="${esc(placeholder)}" ${state.busy ? "disabled" : ""}></label>`;
  }
  function textarea(state, key, label, placeholder = "") {
    return `<label style="display:grid;gap:.3rem">${esc(label)}<textarea rows="3" data-exploration-field="${key}" placeholder="${esc(placeholder)}" ${state.busy ? "disabled" : ""}>${esc(state.form[key])}</textarea></label>`;
  }
  const statusText = value => ({queued:"等待準備",running:"準備中",interrupted:"作業中斷，可明確恢復",failed:"準備失敗，可檢查後恢復",
    completed:"本次準備完成",completed_with_gaps:"已保存證據，仍有未知項",stale:"來源已變動，需建立新輸入",no_trail_candidates:"未找到可用山徑",unavailable:"來源未就緒",partial:"部分覆蓋"}[value] || value || "尚未讀取");
  function results(state) {
    const prep = state.receipt?.preparation, report = prep?.report;
    if (!prep) return "";
    const unknowns = report?.unknowns || state.receipt.unknowns;
    return `<section data-exploration-results data-exploration-project="${esc(state.receipt.project_id)}" data-exploration-intake-sha="${esc(state.receipt.intake_sha256)}" data-exploration-attempt="${esc(prep.attempt)}" style="padding:1rem;border:1px solid currentColor;border-radius:.5rem">
      <h4>探索證據與準備狀態</h4><p><strong>${esc(statusText(prep.status))}</strong> · 第 ${esc(prep.attempt || 0)} 次 · ${esc(prep.stage || "尚未執行")}</p>
      <p>Ref. GPX：0；Golden：無。${prep.worker_live ? "一次性作業仍在 Scout 執行；重載後可讀回進度。" : ""}</p>
      ${report ? `<p>山徑候選：${esc(report.map?.source_count ?? 0)} · 地圖：${esc(statusText(report.map?.status))} · DEM：${esc(statusText(report.terrain?.status))}</p>
      <p>DEM 原始解析度 ${esc(report.terrain?.resolution_m ?? "未知")} m；有效區域格數 ${esc(report.terrain?.finite_cell_count ?? "未知")}；缺值 ${esc(report.terrain?.nodata_cell_count ?? "未知")}。</p>` : ""}
      <p>區域地圖與 DEM 已取得後，仍需選定來源路段，再建立 Planned 與路線六力分析。</p>
      ${unknowns?.length ? `<ul data-exploration-unknowns>${arr(unknowns).map(row => `<li>${esc(row.message || row.code)}${row.label ? ` · ${esc(row.label)}` : ""}${row.missing ? `：${esc(row.missing.join("、"))}` : ""}</li>`).join("")}</ul>` : ""}
      ${prep.error ? `<p role="alert">${esc(prep.error.message)}</p>` : ""}
      <details><summary>來源與作業識別</summary><p>Project：${esc(state.receipt.project_id)}</p><p>準備：${esc(state.receipt.preparation_id)}</p><p>Intake SHA：${esc(state.receipt.intake_sha256)}</p><p>Report SHA：${esc(prep.report_sha256 || "尚未產生")}</p></details>
    </section>`;
  }
  function catalogView(state) {
    if (!state.catalog) return "";
    const sources = arr(state.catalog.sources);
    return `<section data-exploration-catalog><h4>可選來源候選（${sources.length}）</h4>
      <p>這些線段供 Planned 組合與研判；地圖有線或地形可算出路徑，仍不代表目前可通行。</p>
      <table style="width:100%;border-collapse:collapse"><thead><tr><th>來源</th><th>種類</th><th>分段／點數</th><th>來源 SHA</th></tr></thead><tbody>${sources.map(source => `<tr data-exploration-source="${esc(source.source_id)}"><td>${esc(source.label)}</td><td>${esc(source.kind)}</td><td>${arr(source.parts).length} / ${arr(source.parts).reduce((sum, part) => sum + arr(part).length, 0)}</td><td><code>${esc(source.sha256?.slice(0, 16))}</code></td></tr>`).join("")}</tbody></table>
      ${!sources.length ? "<p>目前沒有可用幾何；已取得的區域證據與未知項仍保留。</p>" : ""}
      ${state.catalog.issues?.length ? `<details><summary>來源缺口</summary><ul>${arr(state.catalog.issues).map(row => `<li>${esc(row.message)}</li>`).join("")}</ul></details>` : ""}</section>`;
  }
  function render(options = {}) {
    const state = ensure(options.projectId ?? current?.projectId ?? "");
    const prep = state.receipt?.preparation;
    return `<section data-exploration-workflow="${esc(state.projectId)}" style="display:grid;gap:1rem;padding:1rem;border:1px solid #68798c;border-radius:.7rem">
      <h3>無 Ref. GPX：從分析區域開始</h3>
      <p>先研究區域、地圖與 DEM；A/B 未確認時仍可保存證據。選定候選路段後，再建立 Planned GPX。</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:.8rem">
        ${field(state,"projectId","探索 workspace 名稱","text","例如 exploration_chilai")}
        ${field(state,"intent","探索目的","text","研究古道、路線探索或資料調查")}
        <label style="display:grid;gap:.3rem">座標系統<select data-exploration-field="crs" ${state.busy ? "disabled" : ""}><option value="EPSG:4326" ${state.form.crs === "EPSG:4326" ? "selected" : ""}>WGS84 經緯度（EPSG:4326）</option><option value="EPSG:3826" ${state.form.crs === "EPSG:3826" ? "selected" : ""}>TWD97 公尺（EPSG:3826）</option></select></label>
        ${field(state,"west","AOI 最小 X／西界","number")}${field(state,"south","AOI 最小 Y／南界","number")}
        ${field(state,"east","AOI 最大 X／東界","number")}${field(state,"north","AOI 最大 Y／北界","number")}
        ${field(state,"startX","A 起點 X（可留空）","number")}${field(state,"startY","A 起點 Y（可留空）","number")}
        ${field(state,"endX","B 終點 X（可留空）","number")}${field(state,"endY","B 終點 Y（可留空）","number")}
        ${field(state,"days","預計天數（可留空）","number")}${field(state,"speed","固定腳程 km/h（可留空）","number")}
        ${field(state,"dailyHours","每日行走上限（小時）","number")}${field(state,"rest","固定休息（分鐘）","number")}
        ${field(state,"departure","出發時間（含時區）","text","2026-10-01T06:00:00+08:00")}${field(state,"arrival","最晚到達（含時區）","text","2026-10-01T16:00:00+08:00")}
      </div>
      ${textarea(state,"waypoints","途經點／營地（每行：名稱 | X | Y | 天數 | 途經或營地；未知座標可留空）","古道遺址 | | | 1 | 途經")}
      ${textarea(state,"dtmDirs","Scout 上的原始 DTM 資料夾（每行一個，可先留空）")}
      ${textarea(state,"assumptions","腳程、日照或紮營假設（每行一項）")}
      <div style="display:flex;gap:.5rem;flex-wrap:wrap">${button("create","建立探索 workspace",!state.busy)}${button("open","讀取指定 workspace",!state.busy)}
        ${button("prepare","準備區域地圖與 DEM",!state.busy && Boolean(prep?.can_prepare))}
        ${button("status","讀取作業狀態",!state.busy && Boolean(state.receipt))}${button("resume","恢復／重做這次準備",!state.busy && Boolean(prep?.can_resume))}
        ${button("catalog","讀取來源候選",!state.busy && Boolean(state.receipt))}${button("trh","建立 A/B 地形候選請求",!state.busy && Boolean(prep?.report?.trh_request_available))}</div>
      <p data-exploration-status role="status" aria-live="polite">${esc(state.status)}</p>${results(state)}${catalogView(state)}
      ${state.trh ? `<section data-exploration-trh><h4>A/B 地形候選請求</h4><p>已建立 ${esc(state.trh.request_count)} 段請求，尚未提交地形運算。後續 R1–R3／R4 仍須保留來源、缺口及候選審查。</p><p>未啟用行走路線；未變更安全或任務授權。</p><details><summary>請求產物</summary><code>${esc(state.trh.artifact_ref)}</code><p>${esc(state.trh.artifact_sha256)}</p></details></section>` : ""}
    </section>`;
  }
  function requestFromForm(state) {
    const form = state.form;
    if (!form.projectId.trim() || !form.intent.trim()) throw Error("請填寫 workspace 名稱與探索目的。");
    const point = (x, y, label) => !String(x).trim() && !String(y).trim() ? undefined : {x:number(x,`${label} X`),y:number(y,`${label} Y`),crs:form.crs,label};
    const waypoints = form.waypoints.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map(line => {
      const [label,x="",y="",day="",purpose="途經"] = line.split("|").map(value => value.trim());
      if (!label) throw Error("途經點需要名稱。");
      return {label,point:point(x,y,label),day:number(day,"途經點天數",true),purpose:purpose === "營地" ? "camp_candidate" : "passage"};
    });
    return {project_id:form.projectId.trim(),intent:form.intent.trim(),aoi:{crs:form.crs,bbox:[number(form.west,"AOI 西界"),number(form.south,"AOI 南界"),number(form.east,"AOI 東界"),number(form.north,"AOI 北界")]},
      start:point(form.startX,form.startY,"A"),destination:point(form.endX,form.endY,"B"),waypoints,
      limits:{days:number(form.days,"天數",true),fixed_speed_kmh:number(form.speed,"固定腳程",true),max_daily_walk_hours:number(form.dailyHours,"每日行走上限",true),fixed_rest_minutes:number(form.rest,"固定休息",true),
        departure_at:form.departure.trim() || undefined,latest_arrival_at:form.arrival.trim() || undefined,assumptions:form.assumptions.split(/\r?\n/).map(value=>value.trim()).filter(Boolean)},
      preparation_inputs:{dtm_dirs:form.dtmDirs.split(/\r?\n/).map(value=>value.trim()).filter(Boolean)},requested_by:"dashboard_explicit_user_action"};
  }
  function useReceipt(state, receipt) {
    if (!receipt || receipt.project_id !== state.projectId) throw Error("探索回覆的 workspace 不一致，請重新讀取。");
    state.receipt = receipt; state.restored = true;
    const intake = receipt.intake || {}, form = state.form, bbox = intake.aoi?.bbox;
    Object.assign(form,{projectId:receipt.project_id,intent:intake.intent || "",crs:intake.aoi?.crs || "EPSG:4326",
      startX:intake.start?.x ?? "",startY:intake.start?.y ?? "",endX:intake.destination?.x ?? "",endY:intake.destination?.y ?? "",
      days:intake.limits?.days ?? "",speed:intake.limits?.fixed_speed_kmh ?? "",dailyHours:intake.limits?.max_daily_walk_hours ?? "",rest:intake.limits?.fixed_rest_minutes ?? "",
      departure:intake.limits?.departure_at || "",arrival:intake.limits?.latest_arrival_at || "",assumptions:arr(intake.limits?.assumptions).join("\n"),dtmDirs:arr(intake.preparation_inputs?.dtm_dirs).join("\n"),
      waypoints:arr(intake.waypoints).map(row=>[row.label,row.point?.x ?? "",row.point?.y ?? "",row.day ?? "",row.purpose === "camp_candidate" ? "營地" : "途經"].join(" | ")).join("\n")});
    if (bbox) Object.assign(form,{west:bbox[0],south:bbox[1],east:bbox[2],north:bbox[3]});
  }
  async function read(state) {
    const receipt = await host.apiGet(path(state));
    if (!live(state)) return;
    useReceipt(state,receipt);state.status = `${statusText(receipt.preparation?.status)}；資料與作業已從 Scout 讀回。`;
    const completed = ["completed", "completed_with_gaps"].includes(receipt.preparation?.status);
    const revision = completed ? `${receipt.preparation_id}:${receipt.preparation?.attempt}` : null;
    if (revision && revision !== state.notifiedPreparation) {
      state.notifiedPreparation = revision;
      await host.onSourcesReady?.({project_id: state.projectId});
    }
  }
  async function act(action) {
    const state = current; if (state.busy) return;
    state.busy = true; redraw();
    try {
      if (action === "create") {
        const payload = requestFromForm(state);
        const receipt = await host.apiPost("/admin/pretrip/exploration/projects",payload);
        if (!live(state)) return;
        state.projectId = receipt.project_id; useReceipt(state,receipt);
        state.status = "探索 workspace 已建立。下一步可明確啟動區域地圖與 DEM 準備。";
        await host.onProjectCreated?.(receipt.project_id,receipt);
      } else if (action === "open") {
        const id = state.form.projectId.trim(); if (!id) throw Error("請先填寫 workspace 名稱。");
        state.projectId=id; await read(state); if (live(state)) await host.onProjectCreated?.(id,state.receipt);
      } else if (action === "status") await read(state);
      else if (action === "catalog") {
        const value=await host.apiGet(path(state,"/catalog")); if (!live(state)) return;
        if (value.project_id !== state.projectId || value.golden_source_id !== null) throw Error("來源候選與探索 workspace 不一致。");
        state.catalog=value;state.status=`已讀取 ${arr(value.sources).length} 個來源候選，Golden 保持缺席。`;
        await host.onSourcesReady?.(value);
      } else if (action === "prepare" || action === "resume") {
        const receipt=state.receipt, prep=receipt?.preparation;
        if (!receipt) throw Error("請先讀取探索 workspace。");
        const key=`exploration.${action}.${receipt.preparation_id}.${action === "resume" ? prep.attempt : 0}`;
        const value=await host.apiPost(path(state,action === "resume" ? "/prepare/resume" : "/prepare"),{expected_intake_sha256:receipt.intake_sha256,idempotency_key:key,fetch_map:true});
        if (!live(state)) return; useReceipt(state,value);state.status="準備請求已提交至 Scout。可讀取作業狀態，或重載後繼續查看。";
      } else if (action === "trh") {
        const value=await host.apiPost(path(state,"/trh-request"),{expected_intake_sha256:state.receipt.intake_sha256,corridor_m:500,requested_by:"dashboard_explicit_user_action"});
        if (!live(state)) return;
        if (value.project_id !== state.projectId || value.submitted !== false || value.runtime_safety_truth !== false) throw Error("地形請求未保持候選範圍。");
        state.trh=value;state.status="A/B 候選請求已保存；尚未提交地形運算或啟用路線。";
      }
    } catch (error) { if (live(state)) state.status=error.message || String(error); }
    finally { if (live(state)) { state.busy=false;redraw(); } }
  }
  function bind(root, suppliedHost) {
    host=suppliedHost;const container=root?.matches?.("[data-exploration-workflow]") ? root : root?.querySelector?.("[data-exploration-workflow]");
    if (!container || !host?.apiGet || !host?.apiPost) return;
    elementRoot=container;
    if (!container.dataset.explorationBound) {
      container.dataset.explorationBound="true";
      container.addEventListener("input",event=>{const key=event.target.dataset?.explorationField;if(key && current)current.form[key]=event.target.value;});
      container.addEventListener("change",event=>{const key=event.target.dataset?.explorationField;if(key && current)current.form[key]=event.target.value;});
      container.addEventListener("click",event=>{const button=event.target.closest?.("[data-exploration-action]");if(button && !button.disabled)act(button.dataset.explorationAction);});
    }
    const state=current;
    if (state.projectId && !state.restored && !state.busy) {
      state.restored=true;state.busy=true;
      read(state).catch(error=>{if(live(state))state.status=`可建立新的探索 workspace；目前指定項目未讀取成功：${error.message || error}`;})
        .finally(()=>{if(live(state)){state.busy=false;redraw();}});
    }
  }
  global.ScoutExplorationWorkflow={render,bind};
})(window);
