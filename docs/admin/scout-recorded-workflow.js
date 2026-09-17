/* Recorded intake: original source bytes, explicit member/device roles, immutable review versions. */
(function (global) {
  "use strict";
  const states = new Map();
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const asArray = value => Array.isArray(value) ? value : [];
  const fresh = projectId => ({projectId, files: [], member: "", device: "", origin: "", label: "歸來後復盤", timezone: "Asia/Taipei",
    plan: "", plans: [], versions: [], selected: "", bundle: null, selection: null, run: null, camp: "[]", status: "匯入此行的 GPX，保留每份檔案的隊員與裝置來源。", busy: false, key: null});
  function stateFor(id) { if (!states.has(id)) states.set(id, fresh(id)); return states.get(id); }
  const endpoint = (s, suffix) => `/admin/pretrip/projects/${encodeURIComponent(s.projectId)}/recorded-analysis/${suffix}`;
  const btn = (action, text, disabled = false) => `<button type="button" class="permission-button" data-recorded-action="${action}" ${disabled ? "disabled" : ""}>${text}</button>`;
  const show = obj => `<pre>${esc(JSON.stringify(obj, null, 2))}</pre>`;
  function render({projectId = ""} = {}) {
    const s = stateFor(projectId), m = s.bundle?.manifest, preview = s.bundle?.preview;
    const rows = s.files.map((row, i) => `<tr><td>${esc(row.file_name)}<br>${row.point_count} 點</td>
      <td><input data-recorded-row="${i}" data-recorded-prop="member_id" value="${esc(row.member_id)}" aria-label="${esc(row.file_name)} 隊員"></td>
      <td><input data-recorded-row="${i}" data-recorded-prop="device_id" value="${esc(row.device_id)}" aria-label="${esc(row.file_name)} 裝置"></td>
      <td><select data-recorded-row="${i}" data-recorded-prop="role" aria-label="${esc(row.file_name)} 用途">${["primary","backup","member_context"].map(v => `<option ${row.role === v ? "selected" : ""}>${v}</option>`).join("")}</select></td>
      <td>${esc(row.observation_kind)}<br><code>${esc(row.sha256?.slice(0,16))}</code></td></tr>`).join("");
    return `<details class="planned-workbench" data-recorded-workflow="${esc(projectId)}" ${s.open ? "open" : ""}><summary><strong>歸來後復盤 · Recorded / Golden / Planned</strong></summary>
      <p>以此行記錄重看路線、腳程與停留。Golden 與 Planned 各版本保留，檔案或時間缺口會明確顯示。</p>
      <div class="planned-grid"><label>主要隊員<input data-recorded-field="member" value="${esc(s.member)}" placeholder="隊員代號"></label>
      <label>記錄裝置<input data-recorded-field="device" value="${esc(s.device)}" placeholder="裝置代號"></label>
      <label>資料來源<select data-recorded-field="origin"><option value="">請選擇記錄的性質</option>
      ${[["device_observation","本次實際活動記錄"],["historical_recording","歷史參考活動記錄"],["fixture_replay","測試資料重放"]].map(([v,t])=>`<option value="${v}" ${s.origin===v?"selected":""}>${t}</option>`).join("")}</select></label>
      <label>GPX 檔案<input type="file" accept=".gpx,application/gpx+xml" multiple data-recorded-files></label>
      <label>復盤名稱<input data-recorded-field="label" value="${esc(s.label)}"></label><label>時區<input data-recorded-field="timezone" value="${esc(s.timezone)}"></label></div>
      ${btn("upload","匯入原始 GPX",s.busy)}
      ${s.files.length ? `<div class="planned-table-scroll"><table class="planned-table"><thead><tr><th>來源檔</th><th>隊員</th><th>裝置</th><th>用途</th><th>來源識別</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
      <div class="planned-grid"><label>比較的 Planned 版本<select data-recorded-field="plan"><option value="">僅比較 Golden</option>${s.plans.map(p=>`<option value="${esc(p.version_id)}" ${s.plan===p.version_id?"selected":""}>${esc(p.version_id)}</option>`).join("")}</select></label></div>
      <details><summary>確認實際紮營區間（可選）</summary><p>使用原始檔案的點號與觀察者代號；不能跨過記錄缺口。未確認的靜止區間仍為候選。</p><textarea data-recorded-field="camp" rows="5" aria-label="紮營區間確認 JSON">${esc(s.camp)}</textarea></details>
      <p>${btn("save","建立不可覆寫的 Recorded 版本",s.busy || !s.files.length)} ${btn("reload","讀取已存版本與作業",s.busy)}</p>
      <label>已存復盤版本<select data-recorded-field="selected"><option value="">選擇版本</option>${s.versions.map(v=>`<option value="${esc(v.manifest.version_id)}" ${s.selected===v.manifest.version_id?"selected":""}>${esc(v.label)} · ${esc(v.manifest.version_id)}</option>`).join("")}</select></label>
      <p>${btn("restore","還原版本",s.busy || !s.selected)} ${btn("select","將此 Recorded 作為六力分析主體",s.busy || !m)} ${btn("analyse","準備此記錄並重算六力",s.busy || !m)}
      ${btn("run-refresh","讀取作業結果",s.busy || !m)} ${btn("resume","恢復此作業",s.busy || !s.run?.can_resume)}</p>
      <p role="status" data-recorded-status>${esc(s.status)}</p>
      ${m ? `<section data-recorded-version="${esc(m.version_id)}"><h4>${esc(preview.request?.label)}</h4><p>${esc(m.observation_kind)} · ${esc(m.source_times_role)} · ${preview.route_axis?.length || 0} 原始點</p>
        <details open><summary>Recorded 與原計畫比較</summary>${show({metrics: preview.metrics, comparison: Object.fromEntries(Object.entries(preview.comparison || {}).map(([k,v])=>[k,Object.fromEntries(Object.entries(v).filter(([field])=>!["point_matches","checkpoint_visits","route_axis"].includes(field)))])), gaps: preview.itinerary?.unknowns})}</details>
        <p><a href="${endpoint(s,`export/${encodeURIComponent(m.version_id)}/gpx`)}" download>匯出 Recorded GPX（保留記錄時間）</a> · <a href="${endpoint(s,`export/${encodeURIComponent(m.version_id)}/comparison`)}" download>下載完整比較</a></p></section>` : ""}
      ${s.run ? `<section data-recorded-run="${esc(s.run.run_id)}"><h4>六力作業：${esc(s.run.status)}</h4><p>${esc(s.run.run_id)} · 第 ${esc(s.run.attempt)} 次執行</p>
      ${Object.entries(s.run.projections || {}).map(([role,p])=>`<p data-recorded-role="${esc(role)}">${esc(role)} · ${esc(p.status)} · ${esc(p.summary)}</p>`).join("")}
      ${s.run.error ? show(s.run.error) : ""}</section>` : ""}
      <p>GPS 記錄可證明檔案中的時空資料；缺少當時天候或條件的部分保持未知，復盤不授予出發或執行權限。</p>
    </details>`;
  }
  async function load(s, host) {
    const [result, plans] = await Promise.all([host.apiGet(endpoint(s,"versions")),host.apiGet(`/admin/pretrip/projects/${encodeURIComponent(s.projectId)}/planned-route/versions`)]);
    s.versions = asArray(result.versions); s.selection = result.analysis_selection; s.plans = asArray(plans.versions);
    s.status = `已讀取 ${s.versions.length} 個 Recorded 版本。`;
  }
  async function readRun(s, host) {
    const m=s.bundle?.manifest;if(!m)return;
    const runs=await host.apiGet(endpoint(s,`analysis-runs?version_id=${encodeURIComponent(m.version_id)}`));
    s.run=runs.runs?.[0] ? await host.apiGet(endpoint(s,`analysis-runs/${encodeURIComponent(runs.runs[0].run_id)}`)) : null;
    s.status=s.run ? `作業 ${s.run.status}；可重新讀取以觀測進度。` : "此版本尚無六力作業。";
  }
  function bind(container, host) {
    const root=container.querySelector("[data-recorded-workflow]");if(!root || root.dataset.recordedBound)return;
    root.dataset.recordedBound="true";const s=stateFor(root.dataset.recordedWorkflow);
    root.addEventListener("toggle",()=>{if(root.isConnected)s.open=root.open;});
    const current=()=>container.querySelector("[data-recorded-workflow]")?.dataset.recordedWorkflow===s.projectId;
    const repaint=()=>{if(current())host.refresh();};
    root.querySelectorAll("[data-recorded-field]").forEach(el=>el.addEventListener("input",()=>{
      s[el.dataset.recordedField]=el.value;s.key=null;
      if(el.dataset.recordedField==="selected"){
        const restore=root.querySelector('[data-recorded-action="restore"]');
        if(restore)restore.disabled=s.busy || !s.selected;
      }
    }));
    root.querySelectorAll("[data-recorded-row]").forEach(el=>el.addEventListener("input",()=>{s.files[Number(el.dataset.recordedRow)][el.dataset.recordedProp]=el.value;s.key=null;}));
    root.querySelectorAll("[data-recorded-action]").forEach(el=>el.addEventListener("click",async()=>{
      if(s.busy)return;const action=el.dataset.recordedAction;s.busy=true;root.querySelectorAll("[data-recorded-action]").forEach(button=>{button.disabled=true;});const files=[...(root.querySelector("[data-recorded-files]")?.files || [])];
      try {
        if(action==="upload"){
          if(!files.length || !s.member || !s.device || !s.origin)throw new Error("先選 GPX，並填寫主要隊員、裝置與記錄性質。");
          for(const f of files){const result=await host.apiPost(endpoint(s,"sources"),{file_name:f.name,content:await f.text()});
            if(!s.files.some(v=>v.source_ref===result.source_ref))s.files.push({...result,member_id:s.member,device_id:s.device,role:"primary",observation_kind:s.origin});}
          s.key=null;s.status=`已匯入 ${s.files.length} 份原始檔；請核對隊員／裝置與用途。`;
        } else if(action==="reload") await load(s,host);
        else if(action==="save"){
          s.key ||= global.crypto.randomUUID();
          const request={project_id:s.projectId,primary_member_id:s.member,label:s.label,timezone:s.timezone,
            planned_version_id:s.plan || null,idempotency_key:s.key,camp_confirmations:JSON.parse(s.camp),
            recordings:s.files.map(f=>({source_ref:f.source_ref,expected_sha256:f.sha256,member_id:f.member_id,device_id:f.device_id,role:f.role,observation_kind:f.observation_kind}))};
          s.bundle=await host.apiPost(endpoint(s,"versions"),request);s.selected=s.bundle.manifest.version_id;s.run=null;s.runKey=null;s.resumeKey=null;await load(s,host);s.status="Recorded 版本已保存，可核對比較並切換六力主體。";
        } else if(action==="restore"){
          s.bundle=await host.apiGet(endpoint(s,`versions/${encodeURIComponent(s.selected)}`));s.runKey=null;s.resumeKey=null;await readRun(s,host);
        } else if(action==="select"){
          s.selection=await host.apiGet(`/admin/pretrip/projects/${encodeURIComponent(s.projectId)}/planned-route/analysis-selection`);
          const m=s.bundle.manifest;
          s.selection=await host.apiPost(endpoint(s,"selection"),{subject_kind:"recorded_gpx",version_id:m.version_id,expected_manifest_sha256:m.manifest_sha256,
            expected_selection_sha256:s.selection.selection_sha256,idempotency_key:`recorded-select-${m.version_id}-${s.selection.selection_sha256 || "default"}`,explicit_confirmation:true});
          global.ScoutPlannedRoute?.applyAnalysisSelection?.(s.projectId,s.selection);
          await host.refreshAnalysis?.();s.status="六力主體已切換到此 Recorded；Golden 與 Planned 保留作為比較。";
        } else if(action==="analyse"){
          const m=s.bundle.manifest;s.runKey ||= global.crypto.randomUUID();
          s.run=await host.apiPost(endpoint(s,"analysis-runs"),{version_id:m.version_id,expected_manifest_sha256:m.manifest_sha256,idempotency_key:s.runKey,explicit_confirmation:true});
          s.status=`Recorded 六力作業 ${s.run.status}。`;
        } else if(action==="run-refresh") {await readRun(s,host);await host.refreshAnalysis?.();}
        else if(action==="resume"){
          s.resumeKey ||= global.crypto.randomUUID();
          s.run=await host.apiPost(endpoint(s,`analysis-runs/${encodeURIComponent(s.run.run_id)}/resume`),{expected_manifest_sha256:s.bundle.manifest.manifest_sha256,idempotency_key:s.resumeKey,explicit_confirmation:true});s.status=`已恢復第 ${s.run.attempt} 次執行。`;s.resumeKey=null;
        }
      } catch(error){s.status=String(error?.message || error);}finally{s.busy=false;repaint();}
    }));
  }
  global.ScoutRecordedWorkflow={render,bind};
})(typeof window==="undefined"?globalThis:window);
