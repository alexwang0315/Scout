import {esc,minutes,taipeiTime,newDraft,plannedRows,useHistoricalTimes,parseTrack,digest,validateBackup} from './core.js';
import {openStore,all,saveDraft,savePackage} from './store.js';

const params = new URLSearchParams(location.search);
const projectId = params.get('projectId') || '';
const main = document.querySelector('main');
let db, snapshot, latestSnapshot, draft, draftList=[], selectedPoint=params.get('cpId'), tab=params.get('tab') || 'plan';
let saveQueue=Promise.resolve(), pending=0, saveError=false, blocked=false, localOnly=false;
const labels={planning:'規劃草稿',recording:'模擬紀錄中',draft:'未完成紀錄',completed:'已完成紀錄'};
const point=id=>snapshot?.points.find(p=>p.id===id);
const pointName=id=>point(id)?.label || id;
const toast=message=>{document.querySelector('#notice').textContent=message;};
const shortHash=value=>String(value || '').slice(0,12);
const clone=value=>structuredClone(value);

function markConnection() {
  const el=document.querySelector('#connection');
  el.textContent=localOnly || !navigator.onLine ? '使用已保存資料' : '本機 Scout 資料';
  el.classList.toggle('warn',localOnly || !navigator.onLine);
}
function save() {
  if (!db || !draft || blocked) return Promise.resolve(false);
  pending++;
  document.querySelector('#save-status').textContent='保存中，請等候回執';
  saveQueue=saveQueue.then(async()=>{
    const id=draft.id;
    try {
      const result=await saveDraft(db,snapshot,clone(draft));
      if (draft.id===id) {draft.revision=result.revision;draft.updated_at=result.updated_at;}
      draftList=[...draftList.filter(d=>d.id!==id),result];
      const list=document.querySelector('#record-list');
      if(list)list.innerHTML=recordButtons();
      saveError=false;
      document.querySelector('#save-status').textContent=`已存本機 ${taipeiTime(result.updated_at)} · 版本 ${result.revision} · 未同步`;
      return true;
    } catch(error) {
      blocked=true;saveError=true;
      document.querySelector('#save-status').textContent='未保存成功';
      toast(`${error.message} 可在下山紀錄匯出備份或另存新草稿。`);
      return false;
    } finally {pending--;}
  });
  return saveQueue;
}
function options(ids,value,empty='') {
  return (empty ? `<option value="">${esc(empty)}</option>` : '')+ids.map(id=>`<option value="${esc(id)}" ${id===value?'selected':''}>${esc(pointName(id))}</option>`).join('');
}
function field(name,label,type,value,extra='') {
  return `<label>${esc(label)}<input data-field="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
}
function render() {
  if (!snapshot || !draft) return;
  if (!['plan','points','record','sources'].includes(tab)) tab='plan';
  document.querySelectorAll('[data-tab]').forEach(el=>el.setAttribute('aria-current',el.dataset.tab===tab?'page':'false'));
  document.querySelector('#route-name').textContent=snapshot.route_name || projectId;
  document.querySelector('#save').disabled=!db;
  document.querySelector('#offline').disabled=!db;
  main.innerHTML=tab==='plan'?renderPlan():tab==='points'?renderPoints():tab==='record'?renderRecord():renderSources();
  if(tab==='sources' && latestSnapshot && latestSnapshot.version!==draft.route_version) main.insertAdjacentHTML('afterbegin','<p class="callout">Scout 有新資料版本；原草稿繼續綁定舊版。</p><button data-action="new-latest">依目前 Scout 新資料另建草稿</button>');
  markConnection();
}
function planSummary() {
  const schedule=plannedRows(snapshot,draft.plan);
  return `<div class="summary"><div><span>每日終點抵達 · 台灣時間</span><strong>${esc(taipeiTime(schedule.end_at))}</strong></div><div><span>${schedule.incomplete?'已填部分（非完整總程）':'路段＋途中額外停留'}</span><strong>${minutes(schedule.known_minutes)}</strong></div><div><span>路線資料版本</span><strong class="number">${shortHash(draft.route_version)}</strong></div></div>${schedule.errors.map(e=>`<p class="warn">${esc(e)}</p>`).join('')}`;
}
function planTable() {
  const schedule=plannedRows(snapshot,draft.plan);
  if (!schedule.rows.length) return '<p class="empty">先選擇每日起點、終點與日期，再逐段填入時間。不同方向保留獨立估時。</p>';
  return `<div class="table-scroll"><table><caption class="muted">點地名可開啟同一個 CP；空白路段不補成 0 分鐘。</caption><thead><tr><th>路段／目的地</th><th>路段耗時<br>分鐘</th><th>抵達後額外停留<br>分鐘</th><th>計畫抵達／離開</th><th>歷史依據</th></tr></thead><tbody>${schedule.rows.map(row=>{
    const leg=draft.plan.legs[row.id];
    return `<tr><td><small>${esc(pointName(row.from_id))} →</small><br><button data-select-point="${esc(row.to_id)}">${esc(pointName(row.to_id))}</button></td><td><input type="number" min="1" max="1440" step="0.1" data-leg="${esc(row.id)}" value="${esc(leg?.minutes ?? '')}" aria-label="${esc(pointName(row.to_id))} 路段耗時"><br><small>${leg?.basis==='historical_elapsed'?'歷史經過時間':'自行估計行進時間'}</small></td><td><input type="number" min="0" max="1440" data-rest="${esc(row.to_id)}" value="${esc(draft.plan.stops[row.to_id] ?? 0)}" aria-label="${esc(pointName(row.to_id))} 額外停留"></td><td class="number" data-clock="${esc(row.id)}">${esc(taipeiTime(row.arrival))}<br>${esc(taipeiTime(row.leave_at))}</td><td>${row.reference?.sample_count?`p50 ${minutes(row.reference.duration_minutes.p50)}<br><small>${row.reference.source_count} 個不同內容來源</small>`:'<span class="warn">此方向缺少統計</span>'}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}
function renderPlan() {
  const ids=snapshot.planning_node_ids;
  return `<section class="section"><h2>每日時程</h2><p class="muted">選定今天要走的一段。路段耗時、抵達時刻與額外停留分開保存；此處不啟用舊安全基準。</p><div class="fields">
    ${field('plan.date','行程日期','date',draft.plan.date)}${field('plan.start_time','起登時間（台灣）','time',draft.plan.start_time)}
    <label>方向<select data-field="plan.direction"><option value="forward" ${draft.plan.direction==='forward'?'selected':''}>依參考路線順向</option><option value="reverse" ${draft.plan.direction==='reverse'?'selected':''}>同一路徑反向</option></select></label>
    ${field('plan.scale','自行設定耗時倍率','number',draft.plan.scale,'min="0.25" max="4" step="0.05"')}
    <label>每日起點<select data-field="plan.start_id">${options(ids,draft.plan.start_id)}</select></label>
    <label>每日終點<select data-field="plan.end_id">${options(ids,draft.plan.end_id,'請選擇終點')}</select></label>
    </div><div id="plan-summary">${planSummary()}</div><button data-action="use-history">帶入所選路段的同方向歷史 p50</button><p class="meta muted">歷史 p50 是經過時間，可能已含停留。另填的休息是「額外增加」，不可解讀為已分離的純行進時間或安全期限。反向不沿用順向統計。</p></section>
    <section id="plan-table">${planTable()}</section><p class="meta muted">此版調整已保存路徑上的每日範圍；尚不建立新的岔路幾何，也不自動判斷日落、封閉或隊伍安全。</p>`;
}
function projection() {
  const coords=snapshot.geometry;
  const lons=coords.map(p=>p[0]),lats=coords.map(p=>p[1]);
  const west=Math.min(...lons),east=Math.max(...lons),south=Math.min(...lats),north=Math.max(...lats);
  const scale=Math.min(736/Math.max(east-west,0.001),416/Math.max(north-south,0.001));
  return (lon,lat)=>[32+(lon-west)*scale,448-(lat-south)*scale];
}
function mapMarkup(record=false) {
  if (!snapshot.geometry.length) return '<p class="empty">路徑幾何未通過讀取／雜湊檢查。</p>';
  const xy=projection();
  const line=snapshot.geometry.map(p=>xy(p[0],p[1]).join(',')).join(' ');
  const nodes=snapshot.points.filter(p=>snapshot.planning_node_ids.includes(p.id) || p.id===selectedPoint);
  return `<svg class="point-map" viewBox="0 0 800 480" role="group" aria-label="已保存路徑示意圖，可選地點；不是即時導航或地形圖"><polyline class="route-line" points="${line}"/>${record&&draft.points.length?`<polyline class="record-line" points="${draft.points.map(p=>xy(p.lon,p.lat).join(',')).join(' ')}"/>`:''}${nodes.map(p=>{
    const [x,y]=xy(p.lon,p.lat);return `<circle class="map-point ${p.id===selectedPoint?'selected':''}" cx="${x}" cy="${y}" r="7" role="button" tabindex="0" data-select-point="${esc(p.id)}" aria-label="${esc(p.label)}"><title>${esc(p.label)}</title></circle>`;
  }).join('')}</svg><p class="meta muted">青色：保存路徑；黃色：${record?'匯入／模擬紀錄':'所選地點'}。無底圖、地形或即時定位。</p>`;
}
function selectedFacts() {
  const p=point(selectedPoint) || snapshot.points[0];
  if (!p) return '<p class="empty">此工作區尚無可讀地點。</p>';
  selectedPoint=p.id;
  const schedule=plannedRows(snapshot,draft.plan);
  const row=schedule.rows.find(r=>r.to_id===p.id);
  const next=snapshot.segments.find(s=>s.from_id===p.id);
  const check=draft.checkins.filter(c=>c.point_id===p.id).at(-1);
  const delay=check?.arrived_at && row?.arrival ? (Date.parse(check.arrived_at)-row.arrival)/60000 : null;
  const revisedEnd=delay!==null && schedule.end_at!==null ? schedule.end_at+delay*60000 : null;
  const weather=snapshot.weather;
  const validUntil=Date.parse(weather.valid_until);
  const stale=!Number.isFinite(validUntil) || validUntil<Date.now();
  const forecasts=[...weather.forecasts].sort((a,b)=>(Number(a.lat)-p.lat)**2+(Number(a.lon)-p.lon)**2-((Number(b.lat)-p.lat)**2+(Number(b.lon)-p.lon)**2));
  const forecast=forecasts[0];
  return `<h2>${esc(p.label)}</h2><span class="chip">${esc(p.kind.toUpperCase())} · ${esc(p.id)}</span>
    <dl class="facts"><div><dt>參考路徑位置</dt><dd>${p.route_distance_m===null?'無法對齊':`${(p.route_distance_m/1000).toFixed(2)} km`} · ${p.elevation_m===null?'高程未定':`${Math.round(p.elevation_m)} m`}</dd></div><div><dt>計畫抵達／離開</dt><dd>${esc(taipeiTime(row?.arrival))}<br>${esc(taipeiTime(row?.leave_at))}</dd></div><div><dt>本機手動記錄抵達</dt><dd>${esc(taipeiTime(check?.arrived_at))}<br><small>非即時隊伍訊號${check?` · ${esc(check.origin)}`:''}</small></dd></div><div><dt>與計畫時刻差</dt><dd>${delay===null?'缺少同一 CP 的計畫或抵達紀錄':`${Math.abs(delay).toFixed(1)} 分鐘${delay>=0?'落後':'提前'}（不等於危險界線）`}</dd></div></dl>
    ${p.position_mismatch?`<p class="callout">原資料里程 ${(Number(p.declared_distance_m)/1000).toFixed(2)} km 與座標投影不一致。本頁依所選參考 GPX 最近點排序；原始資料保留，尚待核對。</p>`:''}
    <section class="section"><h3>下一段與停留</h3><p>${next?`${esc(pointName(next.to_id))} · ${(next.distance_m/1000).toFixed(2)} km<br>順向歷史 p50 ${minutes(next.duration_minutes.p50)}／p75 ${minutes(next.duration_minutes.p75)} · ${next.source_count} 個不同內容來源`:'此點未建獨立歷史分段；請查看相鄰主要節點。'}</p><small class="muted">歷史經過時間可能含停留；樣本不是今天的可用時間。今日額外停留 ${minutes(draft.plan.stops[p.id] ?? 0)}。</small>${revisedEnd?`<p class="callout">若後續各段耗時與停留照原計畫，依這次手動抵達紀錄平移後，終點估計 ${esc(taipeiTime(revisedEnd))}。這只是情境重算，未納入新的疲勞、天候或日落限制。</p>`:''}</section>
    <section class="section"><h3>資源與資料新鮮度</h3><p>${p.classes.includes('camp_hut_structure')?'營地／山屋候選：水量、住宿容量與可用狀態尚未核實。':'此點尚無已核實的水源／住宿現況。'}</p><p>天氣快照：${esc(taipeiTime(weather.fetched_at))} · <span class="${stale?'warn':''}">${stale?'已過期或有效期不明':'仍在保存的預報期間'}</span></p>${forecast?`<p class="meta">最近有座標的預報點：${esc(forecast.label || forecast.areaName || forecast.source)}，${esc(forecast.tempC ?? '—')} °C，降雨 ${esc(forecast.rainProbability ?? '—')}%。這是附近預報快照，不是此 CP 的觀測。</p>`:'<p class="meta muted">沒有可明確對應此點的溫度／雨量數值；不套用縣市預報。</p>'}<details><summary>地點與天氣來源</summary><p class="source">${esc(p.source_ref)}<br>${esc(weather.source_ref)}</p><p class="meta">地點更新時間未提供；手冊下載時間不可代替來源更新時間。</p></details></section>
    <section class="section"><h3>手動記錄抵達</h3><label>抵達時間（台灣）<input type="datetime-local" id="arrival-time"></label><button data-action="arrival">保存此 CP 抵達紀錄</button><p class="meta muted">僅保存至這份本機草稿，可在下山紀錄補寫；不修改隊伍狀態。</p></section>`;
}
function renderPoints() {
  if (!selectedPoint || !point(selectedPoint)) selectedPoint=snapshot.points[0]?.id;
  return `<div class="point-layout"><section><h2>路線地點</h2><label>尋找地點／CP<input id="point-search" type="search" placeholder="地名或 CP 編號"></label><div class="point-list" id="point-list">${pointButtons('')}</div>${mapMarkup()}</section><article class="point-detail">${selectedFacts()}</article></div>`;
}
function pointButtons(query) {
  const found=snapshot.points.filter(p=>`${p.label} ${p.id}`.toLowerCase().includes(query.toLowerCase()));
  return found.length ? found.slice(0,80).map(p=>`<button class="${p.id===selectedPoint?'selected':''}" data-select-point="${esc(p.id)}">${esc(p.label)}</button>`).join('')+(found.length>80?'<p class="meta muted">顯示前 80 點，可輸入名稱縮小範圍。</p>':'') : '<p class="empty">沒有符合的地點。</p>';
}
function recordSteps() {
  const step=Number(draft.step)||0;
  if (step===0) return `<h3>1 · 基本資料</h3><div class="fields">${field('title','紀錄名稱','text',draft.title,'maxlength="200"')}<div><span class="muted">來源</span><p>${draft.origin==='simulation'?'模擬紀錄，不是本人實走':draft.origin==='user_import'?'使用者選取的 GPX':'尚未加入軌跡'}</p></div></div><p class="source">${esc(draft.track_name || '沒有軌跡檔')} ${shortHash(draft.track_hash)}</p>`;
  if (step===1) {
    const elapsed=draft.points.length?(Date.parse(draft.points.at(-1).timestamp)-Date.parse(draft.points[0].timestamp))/60000:null;
    const a=draft.analysis;
    return `<h3>2 · 本次總覽</h3><div class="summary"><div><span>原始紀錄點</span><strong>${draft.points.length}</strong></div><div><span>經過時間</span><strong>${minutes(elapsed)}</strong></div>${a?`<div><span>偵測行進／休息</span><strong>${minutes(a.moving_s/60)}／${minutes(a.rest_s/60)}</strong></div><div><span>缺樣／跨段未分類</span><strong>${minutes(a.unclassified_gap_s/60)}</strong></div>`:''}</div>${mapMarkup(true)}<button data-action="analyze" ${draft.points.length<2?'disabled':''}>以目前 Scout 分析軌跡</button><p class="meta muted">手動將這份軌跡送至目前 Scout 的本機分析接口，不寫入 workspace。離線時可先保留原始紀錄，連線後再按分析；不會自動重送。</p>${a?`<p class="meta muted">${a.restored_from_backup?'備份中的分析結果，尚未在此重新計算。':'本機分析結果'}</p><p class="source">${esc(a.algorithm)}<br>回執 ${esc(a.receipt_id)} · 未同步</p><p class="meta muted">休息以速度 ≤ ${a.rest_policy.rest_speed_threshold_kmh} km/h、半徑 ${a.rest_policy.rest_radius_m} m、持續 ${a.rest_policy.min_rest_duration_s} 秒推估；缺樣不當成休息。</p>`:'<p class="muted">尚未分析；不以經過時間冒充行進時間。</p>'}`;
  }
  if (step===2) return `<h3>3 · 沿途資源</h3><label>水源、住宿與現場觀察<textarea data-field="resources" maxlength="10000">${esc(draft.resources)}</textarea></label><p class="meta muted">只屬於本次紀錄，尚未發布為地點現況。</p>`;
  if (step===3) return `<h3>4 · 心得</h3><label>稍後可以繼續補寫<textarea data-field="notes" maxlength="20000">${esc(draft.notes)}</textarea></label>`;
  return `<h3>5 · 打卡與存檔</h3>${draft.checkins.length?draft.checkins.map((c,i)=>`<section class="section"><strong>${esc(pointName(c.point_id))}</strong><p>${esc(taipeiTime(c.arrived_at))} · 手動記錄</p><label>打卡備註<input data-checkin-note="${i}" value="${esc(c.note || '')}" maxlength="2000"></label></section>`).join(''):'<p class="empty">尚無打卡。可至地點頁手動填入抵達時間。</p>'}<button data-action="complete" ${draft.points.length<2 || draft.status==='recording'?'disabled':''}>${draft.origin==='simulation'?'保存為已完成的模擬紀錄':'保存為已完成紀錄'}</button><p class="meta muted">參考 GPX 不會自動成為本人活動。未完成可以直接離開，稍後繼續。</p>`;
}
function renderRecord() {
  return `<section class="section"><div class="actions"><h2>下山紀錄</h2><span class="chip">${esc(labels[draft.status] || '草稿')} · ${draft.origin==='simulation'?'模擬':'本機'} · 未同步</span></div><div class="actions"><button data-action="new">新增空白行程</button><button data-action="simulate" ${draft.points.length?'disabled':''}>加入模擬軌跡</button><button data-action="stop" ${draft.status!=='recording'?'disabled':''}>停止模擬並整理</button></div><label>選取自己的 GPX（先保存至瀏覽器）<input type="file" id="import-gpx" accept=".gpx,application/gpx+xml" ${draft.points.length?'disabled':''}></label><p class="meta muted">已有軌跡時請另建草稿，保留原紀錄與分析版本。此版不啟用 GPS 背景錄製。</p><nav class="step-nav" aria-label="紀錄步驟">${['基本資料','本次總覽','沿途資源','心得','打卡與存檔'].map((name,i)=>`<button data-step="${i}" aria-current="${i===Number(draft.step)?'page':'false'}">${i+1} ${name}</button>`).join('')}</nav>${recordSteps()}</section>
    <section class="section"><h3>保存與恢復</h3><div class="actions"><button data-action="backup">匯出這份手冊與紀錄備份</button><button data-action="branch">另存新草稿</button><button data-action="reload">重新讀取本機版本</button></div><label>還原備份<input id="import-backup" type="file" accept=".json,application/json"></label><p class="meta muted">備份包含所選路線、來源、原始 GPX、心得與本機紀錄。請保存於自己的裝置；本頁不外送。</p><h3>此工作區的本機紀錄</h3><div id="record-list" class="record-list">${draftList.filter(d=>d.project_id===projectId).map(d=>`<button data-open-draft="${esc(d.id)}">${esc(d.title)} · ${esc(labels[d.status] || d.status)}${d.origin==='simulation'?' · 模擬':''} · ${esc(taipeiTime(d.updated_at))}</button>`).join('') || '<span class="muted">第一次保存後即可在此恢復。</span>'}</div></section>`;
}

function recordButtons() {
  return draftList.filter(d=>d.project_id===projectId).map(d=>`<button data-open-draft="${esc(d.id)}">${esc(d.title)} · ${esc(labels[d.status] || d.status)}${d.origin==='simulation'?' · 模擬':''} · ${esc(taipeiTime(d.updated_at))}</button>`).join('') || '<span class="muted">第一次保存後即可在此恢復。</span>';
}
function renderSources() {
  const counts=snapshot.timing_counts;
  return `<section class="section"><h2>資料與版本</h2><p class="source">${esc(projectId)}<br>資料版本 ${esc(snapshot.version)}<br>目前草稿綁定 ${esc(draft.route_version)}</p><p class="muted">抓取時間 ${esc(taipeiTime(snapshot.captured_at))}；來源的新鮮度須各別查看。移動資料目錄不應改變內容版本。</p><div class="summary"><div><span>索引來源</span><strong>${counts.source_file_count ?? 0}</strong></div><div><span>不同內容可讀 GPX</span><strong>${counts.unique_content_source_count ?? 0}</strong></div><div><span>已排除重複內容</span><strong>${counts.duplicate_content_source_count ?? 0}</strong></div><div><span>可比歷史分段</span><strong>${counts.usable_segment_count ?? 0} / ${snapshot.segments.length}</strong></div></div><p class="meta muted">檔案數不是人數；p50/p75 沒有個人安全意義。方向、距離與時間品質沿用分段檢查，季節分層尚未建立。</p><div class="table-scroll"><table><thead><tr><th>GPX 來源</th><th>可攜解析結果</th><th>內容身份</th></tr></thead><tbody>${snapshot.source_resolution.map(s=>`<tr><td class="source">${esc(s.source_id)}</td><td>${esc(({resolved:'已讀取',duplicate_content:'重複內容，排除計數',missing:'本機找不到',hash_mismatch:'雜湊不符，未採用',unsafe_workspace_ref:'來源超出工作區，未採用'})[s.status] || s.status)}<br><span class="source">${esc(s.workspace_ref || '')}</span></td><td class="source">${esc(shortHash(s.sha256))}${s.duplicate_of?`<br>同 ${esc(s.duplicate_of)}`:''}</td></tr>`).join('')}</tbody></table></div></section>
    <section class="section"><h3>保留的資料缺口</h3><p>地點原里程與本次 GPX 投影相差超過 1 km：${snapshot.position_mismatch_count} 個；未回寫原資料。</p><p>舊 ETA：${esc(snapshot.diagnostics.saved_eta_status)}，${esc(taipeiTime(snapshot.diagnostics.saved_eta_generated_at))}。</p>${snapshot.diagnostics.saved_eta_gaps.map(g=>`<p class="meta muted">${esc(g)}</p>`).join('')}<p>${esc(snapshot.diagnostics.terrain_note)}</p><p class="meta muted">舊 reviewed baseline 是否符合現行契約，仍由原 Permission 頁處理。手冊的每日時程是新的本機候選草稿，不繼承其批准狀態。</p>${snapshot.issues.map(i=>`<p class="warn source">${esc(i.ref)}：${esc(i.message)}</p>`).join('')}</section><section class="section"><h3>來源收據</h3>${snapshot.sources.map(s=>`<details><summary>${esc(s.ref)}</summary><p class="source">${esc(s.sha256 || s.reason)} · ${esc(s.status)}</p></details>`).join('')}</section>`;
}

async function loadSaved(id) {
  const records=await all(db,'drafts');
  draftList=records;
  const found=id?records.find(d=>d.id===id && d.project_id===projectId):records.filter(d=>d.project_id===projectId).sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at)))[0];
  if (!found) return false;
  const pkg=(await all(db,'packages')).find(p=>p.key===`${projectId}:${found.route_version}`);
  if (!pkg) throw new Error('草稿的路線版本未保存完整；請還原備份，避免混用另一版本。');
  draft=found;snapshot=pkg.snapshot;blocked=false;saveError=false;
  document.querySelector('#save-status').textContent=`已恢復本機草稿 · 版本 ${draft.revision} · 未同步`;
  return true;
}
async function action(name) {
  if (name==='new-latest') {if(!latestSnapshot || !await save())return;snapshot=latestSnapshot;draft=newDraft(snapshot);await save();render();toast('已依目前 Scout 資料建立新草稿，原版本紀錄保留。');}
  if (name==='use-history') {draft.plan=useHistoricalTimes(snapshot,draft.plan);await save();render();}
  if (name==='arrival') {
    const value=document.querySelector('#arrival-time').value;
    if (!value) throw new Error('請填入抵達時間。');
    const arrived=new Date(`${value}:00+08:00`);
    if (!Number.isFinite(arrived.valueOf())) throw new Error('抵達時間無效。');
    draft.checkins.push({id:crypto.randomUUID(),point_id:selectedPoint,arrived_at:arrived.toISOString(),origin:draft.origin==='simulation'?'simulation':'manual',note:''});
    await save();render();
  }
  if (name==='new') {if (!await save()) return;draft=newDraft(snapshot);blocked=false;await save();render();}
  if (name==='simulate') {
    if (draft.points.length) return;
    const coords=snapshot.geometry.slice(0,20);
    if (coords.length<2) throw new Error('沒有可用的路徑幾何。');
    const start=Date.parse(`${draft.plan.date || '2026-01-01'}T${draft.plan.start_time || '06:00'}:00+08:00`);
    draft.points=coords.map((p,i)=>({lat:p[1],lon:p[0],elevation_m:p[3],timestamp:new Date(start+i*60000).toISOString(),part:0}));
    const last=draft.points.at(-1);
    for(let i=1;i<=5;i++) draft.points.push({...last,timestamp:new Date(Date.parse(last.timestamp)+i*60000).toISOString()});
    draft.origin='simulation';draft.status='recording';draft.title=`模擬紀錄－${snapshot.route_name}`;draft.track_name='本機生成的模擬軌跡';draft.track_hash=await digest(draft.points);draft.analysis=null;
    await save();render();
  }
  if (name==='stop') {if(draft.status!=='recording')return;draft.status='draft';draft.step=0;await save();render();}
  if (name==='complete') {
    if(draft.points.length<2 || !['simulation','user_import'].includes(draft.origin) || draft.status==='recording') throw new Error('先停止模擬或匯入自己的紀錄，再完成存檔。');
    const previous=draft.status;draft.status='completed';if(!await save())draft.status=previous;draftList=await all(db,'drafts');render();
  }
  if (name==='analyze') {
    if (!navigator.onLine) throw new Error('目前離線，軌跡仍保存在本機。連線到 Scout 後可再按分析。');
    const trackHash=draft.track_hash,id=draft.id;
    toast('正在使用目前 Scout 的休息偵測分析，不寫入 workspace。');
    const response=await fetch('./analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({draft_id:id,origin:draft.origin,points:draft.points}),signal:AbortSignal.timeout(30000)});
    const result=await response.json();
    if (!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'分析輸入不符，請檢查軌跡。');
    if(draft.id!==id || draft.track_hash!==trackHash) throw new Error('分析期間草稿已切換，未套用回執。');
    draft.analysis=result;if(await save())toast('分析完成，結果已存於這份本機紀錄。');render();
  }
  if (name==='backup') {
    await saveQueue;
    const blob=new Blob([JSON.stringify({schema_version:'trip-notebook-backup.v1',snapshot,draft},null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`scout-notebook-${draft.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    toast('已請求下載備份，請確認檔案存在。包含位置與私人紀錄，請自行保管。');
  }
  if (name==='branch') {await saveQueue;draft={...clone(draft),id:crypto.randomUUID(),revision:0,status:draft.points.length?'draft':'planning',created_at:new Date().toISOString(),analysis:null};blocked=false;await save();render();}
  if (name==='reload') {await saveQueue;if(!await loadSaved(draft.id))throw new Error('沒有已保存的版本。');render();toast('已重新讀取本機版本。');}
}

main.addEventListener('click',async event=>{
  const el=event.target.closest('[data-select-point],[data-action],[data-step],[data-open-draft]');
  if (!el) return;
  try {
    if (el.dataset.selectPoint) {selectedPoint=el.dataset.selectPoint;tab='points';render();main.focus({preventScroll:true});}
    if (el.dataset.step!==undefined) {draft.step=Number(el.dataset.step);await save();render();}
    if (el.dataset.openDraft) {if(!await save())return;await loadSaved(el.dataset.openDraft);render();}
    if (el.dataset.action) {el.disabled=true;try {await action(el.dataset.action);}finally{if(el.isConnected)el.disabled=false;}}
  } catch(error) {toast(error.message);}
});
main.addEventListener('keydown',event=>{
  if(event.target.matches('circle[data-select-point]') && ['Enter',' '].includes(event.key)){event.preventDefault();selectedPoint=event.target.dataset.selectPoint;tab='points';render();}
});
main.addEventListener('input',event=>{
  const el=event.target;
  if (el.id==='point-search') {document.querySelector('#point-list').innerHTML=pointButtons(el.value);return;}
  let changed=false;
  if(el.dataset.field) {
    const [parent,key]=el.dataset.field.split('.');
    if(key) draft[parent][key]=el.value;else draft[parent]=el.value;
    changed=true;
  }
  if(el.dataset.leg) {draft.plan.legs[el.dataset.leg]={minutes:el.value,basis:'manual_moving'};el.parentElement.querySelector('small').textContent='自行估計行進時間';changed=true;}
  if(el.dataset.rest) {draft.plan.stops[el.dataset.rest]=el.value;changed=true;}
  if(el.dataset.checkinNote!==undefined) {draft.checkins[Number(el.dataset.checkinNote)].note=el.value;changed=true;}
  if(changed) {
    if(draft.status==='completed')draft.status='draft';
    void save();
    if(tab==='plan') {
      document.querySelector('#plan-summary').innerHTML=planSummary();
      if(el.dataset.field?.startsWith('plan.'))document.querySelector('#plan-table').innerHTML=planTable();
      else for(const row of plannedRows(snapshot,draft.plan).rows) {
        const cell=[...document.querySelectorAll('[data-clock]')].find(n=>n.dataset.clock===row.id);
        if(cell)cell.innerHTML=`${esc(taipeiTime(row.arrival))}<br>${esc(taipeiTime(row.leave_at))}`;
      }
    }
  }
});
main.addEventListener('change',async event=>{
  const el=event.target;
  if(!['import-gpx','import-backup'].includes(el.id) || !el.files?.length)return;
  try {
    const file=el.files[0];
    if(file.size>20*1024*1024)throw new Error('檔案超過此版 20 MB 的本機還原範圍。');
    const text=await file.text();
    if(el.id==='import-gpx') {
      if(draft.points.length)throw new Error('請先新增空白草稿，保留既有軌跡。');
      const hash=await digest(await file.arrayBuffer());
      if(snapshot.sources.some(s=>s.sha256===hash)) throw new Error('這是工作區參考來源，不能作為自己的完成紀錄。請選本人軌跡，或使用明示的模擬紀錄。');
      const points=parseTrack(text);
      draft.points=points;draft.raw_gpx=text;draft.track_name=file.name;draft.track_hash=hash;
      draft.origin='user_import';draft.status='draft';draft.analysis=null;draft.title=file.name.replace(/\.gpx$/i,'');draft.step=0;
      await save();render();
    } else {
      const backup=validateBackup(JSON.parse(text),projectId);
      const found=(await all(db,'drafts')).find(d=>d.id===backup.draft.id);
      if(found) {
        const content=d=>{const {revision,updated_at,analysis,...rest}=d;return rest;};
        if(await digest(content(found))!==await digest(content(backup.draft))) throw new Error('本機已有同一份草稿的不同版本。未覆寫；可另存目前草稿，或在其他瀏覽器還原此備份。');
        await loadSaved(found.id);render();toast('這份備份已存在，未建立重複紀錄。');return;
      }
      if(draft && !await save())return;
      snapshot=backup.snapshot;draft={...backup.draft,revision:0};blocked=false;
      await save();render();toast('已恢復備份中的路線版本與紀錄，未同步。');
    }
  }catch(error){toast(error.message);el.value='';}
});
document.querySelectorAll('[data-tab]').forEach(el=>el.addEventListener('click',async()=>{
  if(!draft)return;tab=el.dataset.tab;if(tab==='record')draftList=await all(db,'drafts');render();
}));
document.querySelector('#save').addEventListener('click',()=>void save());
document.querySelector('#offline').addEventListener('click',async event=>{
  const el=event.currentTarget;el.disabled=true;
  try {
    if(!isSecureContext || !('serviceWorker' in navigator))throw new Error('此網址不支援離線啟動。請以 HTTPS 或本機 localhost 開啟；仍可匯出備份。');
    if(!await save())return;
    const registration=await navigator.serviceWorker.register('./sw.js',{scope:'./'});
    const worker=registration.installing || registration.waiting;
    if(worker && worker.state!=='activated')await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('離線介面安裝尚未完成，請重試。')),20000);
      worker.addEventListener('statechange',()=>{if(worker.state==='activated'){clearTimeout(timer);resolve();}if(worker.state==='redundant'){clearTimeout(timer);reject(new Error('離線介面保存失敗。'));}});
    });
    await savePackage(db,snapshot);
    const persistent=await navigator.storage?.persist?.();
    toast(`離線手冊已保存：路徑、CP、歷史時間、資料來源與本機草稿。請收藏「離線入口」。${persistent?'瀏覽器已允許持久保存。':'瀏覽器未保證永久保存，請另匯出備份。'} 不包含整個 Dashboard、底圖或新的天氣。`);
  }catch(error){toast(error.message);}finally{el.disabled=false;}
});
addEventListener('offline',()=>{localOnly=true;markConnection();});
addEventListener('online',()=>{markConnection();toast('網路已恢復；本機草稿仍未同步。需要分析時請自行按「以目前 Scout 分析軌跡」。');});
addEventListener('beforeunload',event=>{if(pending || saveError){event.preventDefault();event.returnValue='';}});
async function boot() {
  document.title="Scout 路線資料與活動紀錄";
  document.querySelector(".eyebrow").textContent="SCOUT · 路線資料與活動紀錄";
  document.querySelector(".boundary").textContent="本頁保存路線資料、獨立估時試算與活動紀錄。計畫微調及 Accept 請回 Permission。";
  document.querySelector("[data-tab=plan]").textContent="獨立估時試算";
  document.querySelector('#dashboard-link').href=`/admin/dashboard?projectId=${encodeURIComponent(projectId)}#trip-notebook`;
  const standalone=new URL('./',location.href);standalone.searchParams.set('projectId',projectId);
  document.querySelector('#standalone').href=standalone.href;
  if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(projectId))throw new Error('未選擇有效工作區。請由 Dashboard 的行程手冊入口開啟。');
  db=await openStore();
  const restored=await loadSaved(params.get('draftId'));
  if(restored){render();toast('已恢復上次保存的路線版本與草稿；正在檢查目前資料版本。');}
  try {
    if(!navigator.onLine)throw new Error('offline');
    const response=await fetch(`./snapshot/${encodeURIComponent(projectId)}`,{cache:'no-store',signal:AbortSignal.timeout(90000)});
    if(!response.ok)throw new Error(`Scout 讀取失敗（${response.status}）`);
    const incoming=await response.json();
    if(incoming.project_id!==projectId || incoming.schema_version!=='trip-notebook.v1')throw new Error('資料身份不符。');
    latestSnapshot=incoming;
    if(!restored){snapshot=incoming;draft=newDraft(snapshot);}
    else if(incoming.version!==draft.route_version) toast('Scout 資料已有不同版本。這份草稿保留原版本；可至「資料與版本」另建使用新資料的草稿。');
    else toast('目前 Scout 與本機草稿使用相同路線版本。');
  }catch(error){
    localOnly=true;
    if(!restored){
      const packages=(await all(db,'packages')).filter(p=>p.snapshot.project_id===projectId).sort((a,b)=>b.snapshot.captured_at.localeCompare(a.snapshot.captured_at));
      if(!packages.length)throw new Error('目前無法連到 Scout，也尚未保存此路線。請先連線保存離線手冊。');
      snapshot=packages[0].snapshot;draft=newDraft(snapshot);
    }
    toast('使用已保存的手冊與草稿。資料日期與缺口保留，沒有更新天氣或同步。');
  }
  render();
}
boot().catch(error=>{main.innerHTML=`<h2>手冊尚無法開啟</h2><p class="callout">${esc(error.message)}</p><button id="retry">重新讀取</button>${db?'<label>從手冊備份恢復<input id="import-backup" type="file" accept=".json"></label>':''}`;document.querySelector('#retry').onclick=()=>location.reload();});
