// Run inside a real browser on the isolated notebook origin. No network writes.
(async () => {
  const c=await import('/admin/trip-notebook/core.js');
  const storage=await import('/admin/trip-notebook/store.js');
  const results=[];
  function check(name,condition){if(!condition)throw new Error(name);results.push(name);}
  const snapshot={schema_version:'trip-notebook.v1',project_id:'unit-browser-isolated',version:'a'.repeat(64),planning_node_ids:['a','b','c'],points:[],segments:[{from_id:'a',to_id:'b',duration_minutes:{p50:60}}]};
  const plan={date:'2026-09-13',start_time:'23:00',start_id:'a',end_id:'c',direction:'forward',scale:1,legs:{'a>b':{minutes:60},'b>c':{minutes:50}},stops:{b:10}};
  let result=c.plannedRows(snapshot,plan);
  check('跨日抵達採台灣時區',new Date(result.end_at).toISOString()==='2026-09-13T17:00:00.000Z');
  check('途中停留與路段耗時相加',result.known_minutes===120);
  check('終點停留不改變抵達',c.plannedRows(snapshot,{...plan,stops:{b:10,c:20}}).end_at===result.end_at);
  check('缺值不當零並傳遞至後段',c.plannedRows(snapshot,{...plan,legs:{'b>c':{minutes:50}}}).end_at===null);
  check('倍率不能超出輸入界線',c.plannedRows(snapshot,{...plan,scale:5}).end_at===null);
  check('起終點未定不能形成時程',c.plannedRows(snapshot,{...plan,end_id:''}).rows.length===0);
  check('反向不沿用順向時間',c.plannedRows(snapshot,{...plan,start_id:'c',end_id:'a',direction:'reverse'}).rows.every(r=>r.reference===null && r.duration===null));
  check('帶入 p50 不補未知路段',Object.keys(c.useHistoricalTimes(snapshot,{...plan,legs:{}}).legs).length===1);
  check('參考時間仍標經過時間',c.useHistoricalTimes(snapshot,plan).legs['a>b'].basis==='historical_elapsed');
  check('文字輸入會跳脫標籤',c.esc('<img onerror="x">').includes('&lt;img'));
  check('GPX 檔案身份採原始位元組',await c.digest('abc')===await c.digest(new TextEncoder().encode('abc').buffer));
  const xml='<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="23" lon="121"><time>2026-01-01T00:00:00Z</time></trkpt></trkseg><trkseg><trkpt lat="23.01" lon="121"><time>2026-01-01T00:20:00Z</time></trkpt></trkseg></trk></gpx>';
  check('GPX 的跨段身份保留',c.parseTrack(xml).at(-1).part===1);
  for(const [name,value] of [['拒絕外部實體','<!DOCTYPE gpx SYSTEM "file:///etc/passwd">'+xml],['拒絕倒置時間',xml.replace('00:20:00','00:00:00')],['拒絕無時區',xml.replaceAll('00Z','00')],['空白座標不轉成零',xml.replace('lat="23"','lat=""')]]) {
    let rejected=false;try{c.parseTrack(value);}catch{rejected=true;}check(name,rejected);
  }
  const db=await storage.openStore();
  const d=c.newDraft(snapshot);
  const saved=await storage.saveDraft(db,snapshot,d);
  check('保存回執包含遞增版本',saved.revision===1 && Boolean(saved.updated_at));
  let conflict=false;try{await storage.saveDraft(db,snapshot,d);}catch{conflict=true;}
  check('舊分頁不得覆蓋較新版本',conflict);
  check('衝突後已存內容保留',(await storage.all(db,'drafts')).find(x=>x.id===d.id).revision===1);
  // Cleanup only this test's random browser draft and synthetic package.
  await new Promise((resolve,reject)=>{const tx=db.transaction(['drafts','packages'],'readwrite');tx.objectStore('drafts').delete(d.id);tx.objectStore('packages').delete(`${snapshot.project_id}:${snapshot.version}`);tx.oncomplete=resolve;tx.onabort=reject;});
  db.close();
  return {status:'passed',checks:results};
})()
