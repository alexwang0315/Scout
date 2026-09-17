/* Immutable map versions and explicit human candidate review. GET restoration is read-only. */
(function(global) {
  "use strict";
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const arr = value => Array.isArray(value) ? value : [];
  let state = null, host = null, element = null;
  function ensure(projectId) {
    const id = String(projectId || "");
    if (!state || state.projectId !== id) state = {projectId:id, catalog:null, versions:null, inspected:null, packet:null,
      busy:false, loaded:false, images:new Set(), confirmed:false, reviewer:"", note:"", draft:"", bbox:"", status:"讀取地圖來源版本與待審材料。"};
    return state;
  }
  const active = s => state === s;
  const path = (s, suffix="") => `/admin/pretrip/projects/${encodeURIComponent(s.projectId)}/planned-map${suffix}`;
  const title = value => ({topology_ready:"節點拓樸已就緒",vectors_ready_topology_missing:"有向量，缺少節點拓樸",pending_human_review:"待人類審查",human_reviewed:"已完成人工候選審查",stale_or_unavailable:"來源已變更或不可用",available:"可讀取",unavailable:"未就緒"}[value] || value || "未知");
  const button = (action, label, enabled=true, value="") => `<button type="button" class="permission-button" data-planned-map-action="${action}" data-planned-map-value="${esc(value)}" ${enabled ? "" : "disabled"}>${esc(label)}</button>`;
  function redraw() { if (host?.refresh) host.refresh(); else if (element?.parentElement) { const parent=element.parentElement; element.outerHTML=render({projectId:state.projectId}); bind(parent,host); } }
  function artifactUrl(s, kind, id, inspected, ref) { return `${path(s,`/${kind}/${encodeURIComponent(id)}/artifact`)}?ref=${encodeURIComponent(ref)}&expected_manifest_sha256=${encodeURIComponent(inspected.manifest_sha256)}`; }
  function navigationUrl(s) { const url=new URL(global.location.href);url.searchParams.set("projectId",s.projectId);url.hash="outdoor-navigation";return url.href; }
  function tiles(s) { return arr(s.inspected?.trace?.properties?.source_artifacts).filter(row => row.ref?.endsWith(".png")); }
  function fullyVisible(s) { const rows=tiles(s);return rows.length>0 && rows.every(row=>s.images.has(row.ref)); }
  function points(s) {
    return arr(s.inspected?.trace?.features).flatMap(feature => feature.geometry?.type === "LineString" ? [feature.geometry.coordinates] : feature.geometry?.type === "MultiLineString" ? feature.geometry.coordinates : []);
  }
  function tileView(s, tile) {
    const id=s.inspected.manifest.materialization_id;
    const url=artifactUrl(s,"versions",id,s.inspected,tile.ref);
    const lines=points(s).map(part=>part.map(([lon,lat])=>{
      const n=2**tile.z,x=((lon+180)/360*n-tile.x)*256,y=((1-Math.asinh(Math.tan(lat*Math.PI/180))/Math.PI)/2*n-tile.y)*256;
      return `${x.toFixed(3)},${y.toFixed(3)}`;
    }).join(" "));
    return `<figure style="margin:0;display:grid;gap:.4rem" data-planned-map-tile="${esc(tile.ref)}"><figcaption>Rudy+TW z${esc(tile.z)} / ${esc(tile.x)} / ${esc(tile.y)} · 原圖與綠色描線</figcaption>
      <div style="display:flex;flex-wrap:wrap;gap:.6rem"><img src="${esc(url)}" data-planned-map-original="${esc(tile.ref)}" alt="Rudy+TW 原始地圖圖磚 ${esc(tile.z)}/${esc(tile.x)}/${esc(tile.y)}" width="256" height="256" style="image-rendering:auto;max-width:100%">
      <svg viewBox="0 0 256 256" width="384" height="384" role="img" aria-label="原始地圖上顯示待審向量描線" style="max-width:100%;background:#ddd;overflow:hidden"><image href="${esc(url)}" width="256" height="256"/>${lines.map(line=>`<polyline points="${line}" fill="none" stroke="#03cf78" stroke-width="2.2" stroke-dasharray="4 2"/>`).join("")}</svg></div>
      <details><summary>圖磚來源與 SHA</summary><p>${esc(tile.original_ref || tile.ref)}</p><code>${esc(tile.sha256)}</code><p>來源 manifest：${esc(tile.source_manifest_ref)}</p><code>${esc(tile.source_manifest_sha256)}</code></details></figure>`;
  }
  function inspectedView(s) {
    const inspected=s.inspected;if (!inspected) return "";
    const manifest=inspected.manifest,pending=manifest.kind === "rudy_trace" && manifest.source_state === "pending_human_review";
    return `<section data-planned-map-inspected="${esc(manifest.materialization_id)}" data-planned-map-manifest-sha="${esc(inspected.manifest_sha256)}" style="display:grid;gap:.8rem;border:1px solid #738190;padding:1rem;border-radius:.6rem">
      <h4>${esc(title(manifest.source_state))}</h4><p>版本 ${esc(manifest.materialization_id)}</p><p>Manifest SHA：<code>${esc(inspected.manifest_sha256)}</code></p>
      ${manifest.kind === "rudy_trace" ? `<p>${esc(inspected.trace?.features?.[0]?.properties?.name)} · ${points(s).reduce((total,part)=>total+part.length,0)} 個點；描線作者：${esc(inspected.trace?.properties?.trace_author_kind)}；審查者：${esc(inspected.trace?.properties?.reviewer_kind)}。</p><p>${esc(inspected.trace?.properties?.review_note)}</p>${tiles(s).map(tile=>tileView(s,tile)).join("")}
      <details><summary>逐點經緯度</summary><pre style="white-space:pre-wrap">${esc(JSON.stringify(points(s),null,2))}</pre></details>` : `<p>候選 ${esc(manifest.source_counts?.route_candidates)}；原始 way ${esc(manifest.source_counts?.ways)}；具有真實 node ID 的 way ${esc(manifest.source_counts?.ways_with_node_ids)}。</p><p>舊來源狀態：${esc(manifest.legacy_sources?.state)}。重建保留舊檔及其宣告。</p>`}
      ${manifest.kind === "mapsforge_vector" ? `<p data-planned-map-vector>官方 Mapsforge 向量 · ${esc(manifest.source_counts?.vertices)} 點 · ${esc(inspected.vector?.properties?.comment)}。保留原分段、標籤及圖層，沒有補接缺口或轉為人類描線。</p><a href="${esc(artifactUrl(s,"versions",manifest.materialization_id,inspected,manifest.project_binding.ref))}" target="_blank" rel="noopener">檢視完整來源向量 GeoJSON</a>` : ""}
      ${pending ? `<div data-planned-map-human-review style="display:grid;gap:.6rem"><p>此描線仍是候選，沒有現地查證。確認只建立人工審查版本，不代表路線安全或可通行。</p>
        <label>審查人姓名<input data-planned-map-field="reviewer" value="${esc(s.reviewer)}" autocomplete="off" ${s.busy?"disabled":""}></label>
        <label>審查備註<textarea data-planned-map-field="note" rows="3" ${s.busy?"disabled":""}>${esc(s.note)}</textarea></label>
        <label><input type="checkbox" data-planned-map-field="confirmed" ${s.confirmed?"checked":""} ${s.busy || !fullyVisible(s)?"disabled":""}>我已看過本版本原圖、描線及來源，確認此幾何可作為規劃候選；我了解尚未經現地驗證。</label>
        <p data-planned-map-image-status role="status">${fullyVisible(s)?"原圖已載入，可進行審查。":"原圖載入後才可確認；若圖檔讀取失敗，請重新讀取版本。"}</p>
        ${button("human-review","確認此版本的人工候選審查",!s.busy && fullyVisible(s) && s.confirmed && Boolean(s.reviewer.trim()) && Boolean(s.note.trim()))}</div>` : ""}
      <details><summary>完整版本資訊</summary><pre style="white-space:pre-wrap">${esc(JSON.stringify(manifest,null,2))}</pre></details>
    </section>`;
  }
  function packetView(s) {
    const item=s.packet;if (!item) return "";const p=item.packet;
    const svgs=Object.keys(item.manifest.artifacts).filter(ref=>ref.endsWith(".svg"));
    return `<section data-planned-map-packet="${esc(item.packet_id)}" style="display:grid;gap:.6rem;border:1px solid #9c834d;padding:1rem;border-radius:.6rem">
      <h4>R4 日誌與錨點審查材料</h4><p>待人類審查 · Guidance：${esc(p.guidance_id)} · Packet SHA：<code>${esc(item.manifest_sha256)}</code></p>
      ${p.narrative ? `<details open><summary>原始日誌</summary><p style="white-space:pre-wrap">${esc(p.narrative)}</p></details>` : ""}
      ${svgs.map(ref=>`<img src="${esc(artifactUrl(s,"packets",item.packet_id,item,ref))}" alt="R4 真實地形與待確認錨點位置" style="max-width:100%;height:auto">`).join("")}
      <table><thead><tr><th>錨點</th><th>經度 / 緯度</th><th>DEM 高程</th><th>依據與未知項</th></tr></thead><tbody>${arr(p.anchor_proposals).map(row=>`<tr><td>${esc(row.constraint_id)}</td><td>${esc(row.lon)} / ${esc(row.lat)}</td><td>${esc(row.elevation_m)} m</td><td>${esc(row.reason)}</td></tr>`).join("")}</tbody></table>
      <ul>${arr(p.unknowns).map(row=>`<li>${esc(row)}</li>`).join("")}</ul>
      <p><a href="${esc(navigationUrl(s))}" data-planned-map-navigation>開啟此 workspace 的 Navigation，審查 ${esc(p.guidance_id)} 的 ${esc(arr(p.anchor_proposals).map(row=>row.constraint_id).join("、"))}</a></p>
      <p>請在既有 R4 地圖流程明確建立或調整錨點並完成審查。此材料沒有提交 R4 運算；地形點及日誌推論不代表現地路徑。</p>
      <a href="${esc(artifactUrl(s,"packets",item.packet_id,item,item.manifest.packet_ref))}" target="_blank" rel="noopener">開啟已綁定來源的完整審查 JSON</a>
    </section>`;
  }
  function render(options={}) {
    const s=ensure(options.projectId ?? state?.projectId ?? "");
    const versions=arr(s.versions?.source_states),pbf=arr(s.catalog?.pbf_sources).find(row=>row.status === "available"),mapsforge=arr(s.catalog?.mapsforge_sources).find(row=>row.status === "available");
    return `<section data-planned-map-review="${esc(s.projectId)}" style="display:grid;gap:1rem;border:1px solid #66788b;border-radius:.7rem;padding:1rem">
      <h3>地圖來源與候選描線</h3><p>從既有來源建立新版本，再納入 Planned 路段。Rudy 向量可直接選段；缺少節點關係時不作自動圖尋徑。人工描線與 R4 錨點保留各自的審查。</p>
      <div style="display:flex;gap:.6rem;flex-wrap:wrap">${button("refresh","重新讀取地圖來源",!s.busy && Boolean(s.projectId))}${button("rebuild","由已登錄 PBF 重建新來源版本",!s.busy && Boolean(pbf))}${button("mapsforge","讀取已登錄 Rudy 向量山徑",!s.busy && Boolean(mapsforge))}</div>
      ${pbf?`<p>重建來源：${esc(pbf.source_ref)} · ${esc(pbf.size_bytes)} bytes<br>SHA：<code>${esc(pbf.sha256)}</code></p>`:"<p>此 workspace 尚無可重建的 PBF；仍可檢查既有地圖來源及待審材料。</p>"}
      ${mapsforge?`<p>Rudy Mapsforge：${esc(mapsforge.source_ref)} · ${esc(mapsforge.size_bytes)} bytes<br>SHA：<code>${esc(mapsforge.sha256)}</code></p>`:""}
      <details><summary>重建範圍（僅未準備過地圖範圍時需要）</summary><label>WGS84 bbox JSON<textarea rows="2" data-planned-map-field="bbox" placeholder='{"south":23,"west":121,"north":23.1,"east":121.1}'>${esc(s.bbox)}</textarea></label></details>
      <p data-planned-map-status role="status" aria-live="polite">${esc(s.status)}</p>
      <ul data-planned-map-source-states>${arr(s.catalog?.source_states).map(row=>`<li>${esc(row.source_kind)}：${esc(title(row.status))}${row.reason?` · ${esc(row.reason)}`:""}</li>`).join("")}</ul>
      <div data-planned-map-versions>${versions.map(row=>`<p>${esc(row.source_kind)} · ${esc(title(row.status))} · <code>${esc(row.materialization_id?.slice(0,16))}</code> ${button("inspect","檢視此版本",!s.busy && row.status!=="stale_or_unavailable",row.materialization_id)}</p>`).join("")}</div>
      ${arr(s.catalog?.review_packets).map(row=>`<p>R4 ${esc(row.guidance_id)} · ${esc(title(row.status))} ${button("packet","開啟錨點審查材料",!s.busy && row.status!=="stale_or_unavailable",row.packet_id)}</p>`).join("")}
      ${inspectedView(s)}${packetView(s)}
      <details><summary>建立 Rudy 描線草稿</summary><p>貼上包含 label、geometry、map_evidence、created_by、review_note 的草稿 JSON。原圖必須有工作區內的準備 manifest、SHA 與 z/x/y 定位。儲存後仍待人類審查。</p><textarea rows="8" data-planned-map-field="draft" style="width:100%">${esc(s.draft)}</textarea>${button("draft","保存待審描線草稿",!s.busy && Boolean(s.draft.trim()))}</details>
      ${s.catalog?.issues?.length?`<details><summary>來源缺口</summary><ul>${arr(s.catalog.issues).map(row=>`<li>${esc(row.message || row.code)}</li>`).join("")}</ul></details>`:""}
    </section>`;
  }
  async function load(s) {
    const [catalog,versions]=await Promise.all([host.apiGet(path(s,"/catalog")),host.apiGet(path(s,"/versions"))]);
    if (!active(s)) return;
    if (catalog.project_id!==s.projectId || versions.project_id!==s.projectId) throw Error("回覆的 workspace 不一致。");
    s.catalog=catalog;s.versions=versions;s.loaded=true;
  }
  async function inspect(s,id) {
    const result=await host.apiGet(path(s,`/versions/${encodeURIComponent(id)}`));if (!active(s)) return;
    if (result.project_id!==s.projectId || result.manifest?.materialization_id!==id) throw Error("版本回覆與所選來源不一致。");
    s.inspected=result;s.images=new Set();s.confirmed=false;s.reviewer="";s.note="";
  }
  async function act(action,value="") {
    const s=state;if (s.busy) return;s.busy=true;redraw();
    try {
      if (action==="refresh") { await load(s);if(active(s))s.status="已讀回目前來源；尚未執行新的重建或審查。"; }
      else if (action==="inspect") await inspect(s,value);
      else if (action==="packet") { const result=await host.apiGet(path(s,`/packets/${encodeURIComponent(value)}`));if(!active(s))return;if(result.project_id!==s.projectId)throw Error("審查材料 workspace 不一致。");s.packet=result; }
      else if (action==="mapsforge") {
        const source=arr(s.catalog?.mapsforge_sources).find(row=>row.status==="available");if(!source)throw Error("沒有已登錄的 Mapsforge 向量來源。");
        const result=await host.apiPost(path(s,"/rebuild"),{source_kind:"mapsforge_vector",source_ref:source.source_ref,expected_source_sha256:source.sha256,requested_by:"dashboard_explicit_user_action",explicit_rebuild_confirmed:true,bbox_wgs84:s.bbox.trim()?JSON.parse(s.bbox):null});
        if(!active(s))return;await load(s);await inspect(s,result.materialization_id);if(active(s))s.status="Rudy 向量已加入 Planned 選段來源；節點關係與現地通行狀況仍未知。";
        if(active(s))await host.onSourcesReady?.({project_id:s.projectId});
      } else if (action==="rebuild") {
        const pbf=arr(s.catalog?.pbf_sources).find(row=>row.status==="available");if(!pbf)throw Error("沒有可重建的已登錄 PBF。");
        const result=await host.apiPost(path(s,"/rebuild"),{source_kind:"osm_pbf",source_ref:pbf.source_ref,expected_source_sha256:pbf.sha256,requested_by:"dashboard_explicit_user_action",explicit_rebuild_confirmed:true,bbox_wgs84:s.bbox.trim()?JSON.parse(s.bbox):null});
        if(!active(s))return;await load(s);await inspect(s,result.materialization_id);if(active(s))s.status="已由真實 PBF 建立新版本，舊來源保留。";
        if(active(s))await host.onSourcesReady?.({project_id:s.projectId});
      } else if (action==="draft") {
        const request=JSON.parse(s.draft);const result=await host.apiPost(path(s,"/rudy/drafts"),{...request,draft_creation_confirmed:true});
        if(!active(s))return;await load(s);await inspect(s,result.materialization_id);if(active(s))s.status="描線草稿已保存，等待人類檢視原圖與確認。";
      } else if (action==="human-review") {
        if (!fullyVisible(s) || !s.confirmed || !s.reviewer.trim() || !s.note.trim()) throw Error("請先查看原圖、填寫姓名與備註，再明確勾選確認。");
        const version=s.inspected;const result=await host.apiPost(path(s,`/versions/${version.manifest.materialization_id}/human-review`),{expected_manifest_sha256:version.manifest_sha256,reviewer_name:s.reviewer.trim(),review_note:s.note.trim(),candidate_review_confirmed:true,source_geometry_confirmed:true});
        if(!active(s))return;await load(s);await inspect(s,result.materialization_id);if(active(s)){s.status="已建立新的人工候選審查版本；原草稿與來源證據保留。";await host.refreshAnalysis?.();await host.onSourcesReady?.({project_id:s.projectId});}
      }
    } catch(error) { if(active(s))s.status=String(error?.message || error); }
    finally { if(active(s)){s.busy=false;redraw();} }
  }
  function updateControls(s) {
    if (!element || !active(s)) return;
    const check=element.querySelector('[data-planned-map-field="confirmed"]');if(check)check.disabled=s.busy || !fullyVisible(s);
    const submit=element.querySelector('[data-planned-map-action="human-review"]');if(submit)submit.disabled=s.busy || !fullyVisible(s) || !s.confirmed || !s.reviewer.trim() || !s.note.trim();
    const draft=element.querySelector('[data-planned-map-action="draft"]');if(draft)draft.disabled=s.busy || !s.draft.trim();
    const status=element.querySelector('[data-planned-map-image-status]');if(status && fullyVisible(s))status.textContent="原圖已載入，可進行審查。";
  }
  function bind(container,providedHost) {
    host=providedHost || host;element=container.matches?.('[data-planned-map-review]')?container:container.querySelector('[data-planned-map-review]');if(!element)return;
    const s=ensure(element.dataset.plannedMapReview);
    if(element.dataset.bound)return;element.dataset.bound="true";
    element.querySelectorAll('[data-planned-map-action]').forEach(node=>node.addEventListener("click",()=>act(node.dataset.plannedMapAction,node.dataset.plannedMapValue)));
    element.querySelectorAll('[data-planned-map-field]').forEach(node=>node.addEventListener("input",()=>{if(!active(s))return;s[node.dataset.plannedMapField]=node.type==="checkbox"?node.checked:node.value;updateControls(s);}));
    element.querySelectorAll('[data-planned-map-original]').forEach(img=>{const loaded=()=>{if(active(s)&&img.naturalWidth===256&&img.naturalHeight===256){s.images.add(img.dataset.plannedMapOriginal);updateControls(s);}};img.addEventListener("load",loaded);img.addEventListener("error",()=>{if(active(s)){s.images.delete(img.dataset.plannedMapOriginal);s.confirmed=false;updateControls(s);}});if(img.complete)loaded();});
    if(!s.loaded && !s.busy && s.projectId && host?.apiGet) void act("refresh");
  }
  global.ScoutPlannedMapReview={render,bind};
})(window);
