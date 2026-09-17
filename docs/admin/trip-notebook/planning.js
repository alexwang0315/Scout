import {esc, minutes, taipeiTime} from './core.js';

const params=new URLSearchParams(location.search);
if(params.get('view')==='records' || params.has('cpId')) {
  await import('./app.js');
} else {
  await startPlanning();
}

async function startPlanning() {
  const projectId=params.get('projectId') || '';
  const overview=params.get('view')==='permission';
  const api=`./planning/${encodeURIComponent(projectId)}`;
  const dashboard=hash=>`/admin/dashboard?projectId=${encodeURIComponent(projectId)}#${hash}`;
  let db, base=null, adjustments={}, projection=null, pending=null, revision=0, busy=false, acknowledged=false;
  let reviewer='',role='leader',message='',offline=!navigator.onLine,saveError=false;
  let persistQueue=Promise.resolve();
  document.title=overview?'Scout Permission · 計畫':'Planning Fine-tune Panel';
  document.body.innerHTML=`<a class="skip" href="#content">跳至計畫內容</a><header><div class="heading"><div><span class="eyebrow">SCOUT · PERMISSION</span><h1>${overview?'目前計畫':'Planning Fine-tune Panel'}</h1></div><a target="_top" href="${dashboard('outdoor-permission')}">回 Permission</a></div><p>${overview?'查看 Scout 的安排，可直接 Accept，或先微調。':'在 Permission 的大計畫下調整本輪細則，Accept 後更新到同一份計畫。'}</p><p class="source">${esc(projectId)}</p><p class="boundary">Accept 採用計畫版本；現地執行狀態仍由既有 Permission／Safety 流程處理。</p><p id="planning-save-state" class="meta" role="status" aria-live="polite"></p><div class="toolbar"><button id="reload-plan">載入目前採用計畫</button><button id="arrange-plan">由 Scout 提出安排</button><button id="cache-plan">保存離線面板</button><a target="_blank" rel="noopener" href="./?projectId=${encodeURIComponent(projectId)}&view=records">路線資料與活動紀錄</a></div></header><main id="content" tabindex="-1"></main><footer>途中可原樣採用或再微調。離線修改只保存於本機，恢復連線不會自動 Accept 或同步。</footer>`;
  const main=document.querySelector('main');
  const capture=()=>({key:projectId,revision,base,adjustments,pending,reviewer,role,updated_at:new Date().toISOString()});
  const hasEdits=()=>Object.keys(adjustments).length>0;
  async function persist() {
    const value=structuredClone(capture());
    persistQueue=persistQueue.then(()=>new Promise((resolve,reject)=>{
      if(!db){reject(new Error('本機保存尚未就緒'));return;}
      const tx=db.transaction('plans','readwrite'), store=tx.objectStore('plans');
      const request=store.get(projectId);let conflict=false;
      request.onsuccess=()=>{if((request.result?.revision||0)!==revision){conflict=true;tx.abort();return;}store.put({...value,revision:revision+1});};
      tx.oncomplete=()=>{revision++;saveError=false;resolve();};
      tx.onabort=()=>reject(new Error(conflict?'另一分頁已保存新一輪。請保留目前內容，載入比較後再操作。':'本機保存失敗，請保留頁面並重試。'));
      tx.onerror=()=>{};
    })).catch(error=>{saveError=true;message=error.message;});
    await persistQueue;
    const status=document.querySelector("#planning-save-state");
    if(status)status.textContent=saveError?`尚未保存：${message}`:"本輪已保存於目前瀏覽器；尚未 Accept 的修改不改變 Permission。";
    return !saveError;
  }
  async function archive() {
    if(!base)return;
    await new Promise((resolve,reject)=>{const tx=db.transaction('plans','readwrite');tx.objectStore('plans').put({...capture(),key:`archive.${projectId}.${crypto.randomUUID()}`});tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error);});
  }
  async function call(path, payload) {
    if(!navigator.onLine)throw new Error('目前離線，可保存微調；連線後由你按 Accept，不會自動重送。');
    const response=await fetch(api+path,{method:payload===undefined?'GET':'POST',headers:payload===undefined?{}:{'Content-Type':'application/json'},body:payload===undefined?undefined:JSON.stringify(payload),cache:'no-store',signal:AbortSignal.timeout(90000)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail?.message || (typeof data.detail==='string'?data.detail:`計畫操作未完成（${response.status}）`));
    if(data.project_id!==projectId || data.schema_version!=='planningFineTune.v1')throw new Error('計畫身份不符，未採用回應。');
    offline=false;return data;
  }
  const payload=()=>({draft:base.draft,draft_sha256:base.draft_sha256,expected_plan_sha256:base.selected_plan_sha256,adjustments});
  const timeInput=value=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)).replace(' ','T'):'';
  function render() {
    const current=projection||base;
    const days=current?.draft?.days?.filter(day=>day.day_kind==='on_trail') || [];
    const requirements=current?.draft?.review_requirements;
    main.innerHTML=`<div class="actions"><span id="planning-phase" class="chip ${base?.status==='accepted'&&!hasEdits()?'ok':''}">${offline?'離線快照':hasEdits()?'本輪微調 · 尚未 Accept':base?.status==='accepted'?'Permission 已採用':'Scout 安排 · 待 Accept'}</span><span class="meta">${base?.version_id?esc(base.version_id):'尚未採用版本'}</span></div><p id="planning-status" class="callout" role="status" aria-live="polite">${esc(message || base?.reason || '計畫 → 選用微調 → Accept → 更新 Permission → 下一輪')}</p>
      ${!days.length?`<section class="empty"><h2>尚無可編輯的目前計畫</h2><p>${esc(base?.reason || '由 Scout 依目前工作區的參考路線提出安排，再由領隊或嚮導決定是否採用。')}</p></section>`:`
      <div class="planning-days">${days.map(day=>{
        const tune=adjustments[day.mission_day_id] || day.fine_tune || {};
        const timing=current.schedules?.[day.mission_day_id] || {};
        const historical=day.eta_proposal||{};
        return `<article class="section planning-day" data-day="${esc(day.mission_day_id)}"><span class="eyebrow">${esc(day.mission_day_id)}</span><h2>${esc(day.start_anchor?.display_label || '起點')} → ${esc(day.primary_day_end_proposal?.target?.display_label || '終點未定')}</h2>
        <div class="summary"><div><span>${hasEdits()||base.status!=="accepted"?"本輪路程估時":"採用路程估時"}</span><strong>${minutes(timing.duration_minutes)}</strong><small>${timing.basis==='human_estimate'?'領隊／嚮導估計':timing.basis==='historical_elapsed'?'歷史經過時間，可能含停留':'保留未知'}</small></div><div><span>額外停留</span><strong>${minutes(timing.extra_stop_minutes)}</strong></div><div><span>含額外停留</span><strong>${minutes(timing.total_minutes)}</strong></div><div><span>抵達時刻（台灣）</span><strong>${esc(taipeiTime(timing.arrival_at))}</strong></div></div>
        ${overview?`<p>${esc(tune.note || '沿用目前安排；可視現場情況開啟下一輪微調。')}</p>`:`<div class="fields"><label>預計出發（選填，台灣時間）<input data-adjust="departure_at" type="datetime-local" value="${esc(timeInput(tune.departure_at))}"></label><label>本輪路程估時（分鐘，選填）<input data-adjust="duration_minutes" type="number" min="1" max="5760" step="0.1" value="${esc(tune.duration_minutes ?? '')}" placeholder="沿用參考／保留未知"></label><label>額外停留（分鐘）<input data-adjust="extra_stop_minutes" type="number" min="0" max="1440" step="1" value="${esc(tune.extra_stop_minutes ?? 0)}"></label></div><label class="planning-note">安排備註（選填）<textarea data-adjust="note" maxlength="2000" placeholder="例如：岔路集合、午餐或依現場情況調整">${esc(tune.note || '')}</textarea></label>`}
        <details><summary>原安排與估時依據</summary><p>歷史 p50 ${minutes(historical.segment_p50_sum_minutes)}／p75 ${minutes(historical.segment_p75_sum_minutes)}。缺段保持未知；手動估時不改寫歷史統計，也不作為安全期限。</p><p class="source">${esc(day.segment_ids.join(' · '))}</p></details></article>`;
      }).join('')}</div>
      <section class="section"><div class="actions">${overview?`<a class="planning-primary" target="_top" href="${dashboard('trip-notebook')}">Planning Fine-tune Panel · 選用微調</a>`:'<button id="preview-plan">預覽微調對大計畫的影響</button>'}<span class="meta">${hasEdits()&&!projection?'目前輸入尚未預覽；Accept 會重新驗證同一份修改。':'可以原樣採用這份安排。'}</span></div></section>
      <section class="section" aria-label="Accept 計畫"><h2>採用這輪計畫</h2><p>Accept 會採用上列 ${days.length} 天的起終點及本輪細則，更新 Permission 的計畫版本。</p><details><summary>本輪仍保留的不確定性與待處理事項</summary>${[...(current.draft.uncertainties||[]),...(current.acceptance_uncertainties||[])].map(item=>`<p>${esc(item.summary)}</p>`).join('') || '<p>此安排沒有列出的不確定項目；仍需依現場情況判斷。</p>'}<p>Safety / Emergency 待處理項目 ${requirements?.pending_safety_handoff_item_ids?.length||0} 項；此處的採用不替代其判斷。</p></details><div class="fields"><label>操作身份<select id="planning-role"><option value="leader" ${role==='leader'?'selected':''}>領隊</option><option value="guide" ${role==='guide'?'selected':''}>嚮導</option></select></label><label>記錄名稱<input id="planning-reviewer" value="${esc(reviewer)}" maxlength="70" autocomplete="off" placeholder="領隊或嚮導姓名／代稱"></label></div><label class="checkline"><input type="checkbox" id="planning-ack" ${acknowledged?'checked':''}>我已查看這份安排與未定事項，Accept 採用目前版本（可完全不微調）。</label><div class="actions"><button class="planning-primary" id="accept-plan" ${busy||offline||!acknowledged||!reviewer.trim()?'disabled':''}>${busy?'核對與更新中…':pending?'重試同一輪 Accept':'Accept · 更新到 Permission'}</button>${base.status==='accepted'?`<a target="_top" href="${dashboard('outdoor-permission')}">查看更新後的 Permission</a><a target="_top" href="${dashboard('outdoor-pace-fit')}">查看行進與 CP</a>`:''}</div><p class="meta">${pending?'上次回應尚未確認，重試會使用同一個操作識別。':'微調是選用步驟；Accept 後可從更新的計畫再次微調。'}</p></section>`}`;
    main.insertAdjacentHTML('beforeend','<details><summary>本機各輪草稿</summary><div id="planning-history">讀取中…</div></details>');
    void history();
    document.querySelectorAll('header button').forEach(button=>button.disabled=busy);
    document.querySelector('#preview-plan')?.addEventListener('click',()=>run(async()=>{projection=await call('/preview',payload());message='已預覽本輪影響，Permission 仍保留原採用版本。';}));
    document.querySelector('#planning-reviewer')?.addEventListener('input',event=>{reviewer=event.target.value;pending=null;void persist();updateAccept();});
    document.querySelector('#planning-role')?.addEventListener('change',event=>{role=event.target.value;pending=null;acknowledged=false;render();void persist();});
    document.querySelector('#planning-ack')?.addEventListener('change',event=>{acknowledged=event.target.checked;updateAccept();});
    document.querySelector('#accept-plan')?.addEventListener('click',()=>run(async()=>{
      if(!acknowledged||!reviewer.trim())throw new Error('請先填入記錄名稱並勾選 Accept。');
      if(!pending)pending={...structuredClone(payload()),reviewer_alias:reviewer.trim(),reviewer_role:role,explicit_confirmation:true,acknowledged_acceptance_uncertainty_ids:(base.acceptance_uncertainties||[]).map(item=>item.uncertainty_id),idempotency_key:`panel.${crypto.randomUUID()}`};
      if(!await persist())throw new Error(message);
      const result=await call('/accept',pending);
      if(result.status==='accepted_superseded')throw new Error('這輪已曾採用，但 Permission 隨後有新版本。請載入目前計畫；未重複更新。');
      if(result.status!=='accepted' || !result.accept_receipt?.reviewed_baseline_sha256)throw new Error('尚未收到可核對的採用回執，保留本輪以供重試。');
      await archive();base=result;adjustments={};projection=null;pending=null;acknowledged=false;
      const saved=await persist();message=`已 Accept，Permission 採用 ${result.version_id}。${saved ? "下一輪會從此版本開始。" : "本機副本未保存成功，請保留回執並重新載入。"}`;
    }));
    main.querySelectorAll('[data-adjust]').forEach(input=>input.addEventListener('input',event=>{
      const id=input.closest('[data-day]').dataset.day,field=input.dataset.adjust;
      const original=base.draft.days.find(day=>day.mission_day_id===id).fine_tune || {};
      const value=field==='departure_at'?(input.value?`${input.value}:00+08:00`:null):field==='note'?input.value:field==='duration_minutes'?(input.value===''?null:Number(input.value)):Number(input.value);
      adjustments[id]={departure_at:null,duration_minutes:null,extra_stop_minutes:0,note:'',...original,...adjustments[id],[field]:value};
      projection=null;pending=null;acknowledged=false;
      document.querySelector('#planning-ack').checked=false;document.querySelector('#planning-phase').textContent='本輪微調 · 尚未 Accept';updateAccept();
      document.querySelector('#planning-status').textContent='本輪細則已修改，尚未 Accept。可預覽影響，或勾選 Accept 後採用。';
      void persist();
    }));
  }
  async function history() {
    if(!db)return;
    const rows=await new Promise((resolve,reject)=>{const r=db.transaction('plans').objectStore('plans').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);}).catch(()=>[]);
    const archived=rows.filter(row=>row.key.startsWith(`archive.${projectId}.`)).sort((a,b)=>b.updated_at.localeCompare(a.updated_at)).slice(0,20);
    const target=document.querySelector('#planning-history');if(!target)return;
    target.innerHTML=archived.length?archived.map(row=>`<button class="planning-history-item" data-history="${esc(row.key)}">${esc(taipeiTime(row.updated_at))} · ${esc(row.base?.version_id || '未採用安排')} · 開啟這輪草稿</button>`).join(''):'<p class="muted">尚無另存的舊輪次。</p>';
    target.querySelectorAll('[data-history]').forEach(button=>button.onclick=()=>run(async()=>{
      const row=archived.find(item=>item.key===button.dataset.history);
      if(!row||row.base?.project_id!==projectId)throw new Error('這份草稿不屬於目前工作區。');
      await archive();base=row.base;adjustments=row.adjustments||{};pending=row.pending||null;reviewer=row.reviewer||'';role=row.role||'leader';projection=null;acknowledged=false;
      await persist();message='已開啟舊輪次供檢視。Permission 目前採用版本不變；若版本已有變化，需先比較再採用。';
    }));
  }
  function updateAccept(){const button=document.querySelector('#accept-plan');if(button)button.disabled=busy||offline||!acknowledged||!reviewer.trim();}
  async function run(action){if(busy)return;busy=true;updateAccept();try{await action();}catch(error){message=error.message;}finally{busy=false;render();}}
  document.querySelector('#reload-plan').onclick=()=>run(async()=>{const next=await call('');await archive();base=next;adjustments={};projection=null;pending=null;acknowledged=false;await persist();message='已載入 Permission 目前採用的計畫；原本這輪已另存於本機。';});
  document.querySelector('#arrange-plan').onclick=()=>run(async()=>{const next=await call('/arrange',{});await archive();base=next;adjustments={};projection=null;pending=null;acknowledged=false;await persist();message='Scout 已依工作區參考路線提出安排。可直接 Accept，也可先微調。';});
  document.querySelector('#cache-plan').onclick=()=>run(async()=>{
    if(!isSecureContext||!navigator.serviceWorker)throw new Error('請使用 HTTPS 或 localhost 保存離線介面。');
    if(!await persist())throw new Error(message);
    await navigator.serviceWorker.register('./sw.js',{scope:'./'});await navigator.serviceWorker.ready;
    message='離線面板與目前這輪已保存。離線可繼續微調，Accept 需連回 Scout；不自動重送。';
  });
  addEventListener('offline',()=>{offline=true;message='目前離線。保留計畫版本與微調，連線後可手動預覽及 Accept。';render();});
  addEventListener('online',()=>{offline=false;message='已恢復連線；沒有自動更新計畫。可先預覽確認目前版本。';render();});
  try {
    if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(projectId))throw new Error('請由 Permission 選擇工作區後開啟。');
    db=await new Promise((resolve,reject)=>{const r=indexedDB.open('scout-permission-planning-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('plans',{keyPath:'key'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    const cached=await new Promise((resolve,reject)=>{const r=db.transaction('plans').objectStore('plans').get(projectId);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    if(cached){({base,adjustments,pending,revision,reviewer,role}=cached);message='已恢復上次這輪計畫與微調。';}
    if(!base || (base.status==='accepted'&&!hasEdits()&&!pending)) {try{base=await call('');await persist();}catch(error){offline=true;message=base?`目前顯示已保存版本。${error.message}`:error.message;}}
    render();
  }catch(error){message=error.message;render();}
}
