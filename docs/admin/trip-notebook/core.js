export const SCHEMA = 'trip-notebook-draft.v1';
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const minutes = value => value === null || value === undefined || !Number.isFinite(Number(value)) ? '未定' : `${Number(value).toFixed(1).replace(/\.0$/, '')} 分`;
export function taipeiTime(value) {
  if (!value || !Number.isFinite(new Date(value).valueOf())) return '未定';
  return new Intl.DateTimeFormat('zh-TW', {timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
}
export function newDraft(snapshot) {
  return {schema_version:SCHEMA, id:crypto.randomUUID(), project_id:snapshot.project_id,
    route_version:snapshot.version, revision:0, created_at:new Date().toISOString(), updated_at:null,
    title:'未命名行程', status:'planning', origin:null, step:0,
    plan:{date:'',start_time:'06:00',start_id:snapshot.planning_node_ids[0] || '',end_id:'',direction:'forward',scale:1,legs:{},stops:{}},
    points:[], raw_gpx:null, track_name:null, track_hash:null, notes:'', resources:'', checkins:[], analysis:null};
}
export function plannedRows(snapshot, plan) {
  const ordered = [...snapshot.planning_node_ids];
  if (plan.direction === 'reverse') ordered.reverse();
  const start = ordered.indexOf(plan.start_id), end = ordered.indexOf(plan.end_id);
  const errors = [];
  if (start < 0 || end <= start) errors.push('請依行走方向選擇起點與每日終點。');
  const dateTime = `${plan.date}T${plan.start_time}:00+08:00`;
  let clock = /^\d{4}-\d{2}-\d{2}$/.test(plan.date) && /^\d{2}:\d{2}$/.test(plan.start_time) ? Date.parse(dateTime) : NaN;
  if (!Number.isFinite(clock)) {clock = null; errors.push('請填入日期與起登時間（台灣時間）。');}
  const scale = Number(plan.scale);
  if (!Number.isFinite(scale) || scale < 0.25 || scale > 4) {errors.push('耗時倍率需介於 0.25 與 4。');clock=null;}
  if (start < 0 || end <= start) return {rows:[],errors,known_minutes:0,incomplete:true,start_at:clock,end_at:null};
  const startAt = clock;
  const rows = [];
  let known = 0, incomplete = errors.length > 0;
  for (let i=start; i<end; i++) {
    const from = ordered[i], to = ordered[i+1], id = `${from}>${to}`;
    const leg = plan.legs[id];
    const duration = leg?.minutes !== '' && leg?.minutes !== null && leg?.minutes !== undefined ? Number(leg.minutes) * scale : null;
    const validDuration = duration !== null && Number.isFinite(duration) && duration > 0 && duration <= 5760;
    const rawRest = plan.stops[to] ?? 0;
    const rest = Number(rawRest);
    const validRest = rawRest !== '' && Number.isFinite(rest) && rest >= 0 && rest <= 1440;
    if (!validDuration || !validRest) incomplete = true;
    if (validDuration) known += duration;
    // Once a segment is unknown, later wall-clock times stay unknown.
    const departure = clock;
    const arrival = clock !== null && validDuration ? clock + duration * 60000 : null;
    clock = arrival !== null && validRest ? arrival + rest * 60000 : null;
    const source = snapshot.segments.find(s => s.from_id === from && s.to_id === to);
    rows.push({id,from_id:from,to_id:to,departure,arrival,leave_at:clock,
      duration:validDuration ? duration : null,rest:validRest ? rest : null,basis:leg?.basis || 'unset',reference:source || null});
    if (i < end-1 && validRest) known += rest;
  }
  return {rows,errors,known_minutes:known,incomplete,start_at:startAt,end_at:rows.at(-1)?.arrival ?? null};
}
export function useHistoricalTimes(snapshot, plan) {
  const result = structuredClone(plan);
  for (const row of plannedRows(snapshot, plan).rows) {
    const p50 = row.reference?.duration_minutes?.p50;
    if (Number.isFinite(p50) && p50 > 0) result.legs[row.id] = {minutes:p50,basis:'historical_elapsed'};
  }
  return result;
}
export function parseTrack(xml) {
  if (xml.length > 8*1024*1024 || /<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error('GPX 過大或含不支援的 XML 宣告。');
  const doc = new DOMParser().parseFromString(xml,'application/xml');
  if (doc.querySelector('parsererror') || doc.documentElement.localName !== 'gpx') throw new Error('無法讀取 GPX。');
  const points = [];
  [...doc.getElementsByTagNameNS('*','trkseg')].forEach((segment,part) => {
    for (const node of segment.getElementsByTagNameNS('*','trkpt')) {
      const time = node.getElementsByTagNameNS('*','time')[0]?.textContent;
      const ele = node.getElementsByTagNameNS('*','ele')[0]?.textContent;
      const lat = Number(node.getAttribute('lat')), lon = Number(node.getAttribute('lon'));
      if (!node.hasAttribute('lat') || !node.hasAttribute('lon') || !node.getAttribute('lat').trim() || !node.getAttribute('lon').trim() || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat)>90 || Math.abs(lon)>180) throw new Error('軌跡座標無效。');
      if (!time || !/(Z|[+-]\d\d:\d\d)$/.test(time) || !Number.isFinite(Date.parse(time))) throw new Error('每個軌跡點需有含時區的時間；不會猜測缺少的時間。');
      if (points.length && Date.parse(time) <= Date.parse(points.at(-1).timestamp)) throw new Error('軌跡時間未遞增，請檢查原始紀錄。');
      const elevation = ele === undefined ? null : Number(ele);
      if (elevation !== null && !Number.isFinite(elevation)) throw new Error('高程資料無效。');
      points.push({lat,lon,elevation_m:elevation,timestamp:new Date(time).toISOString(),part});
      if (points.length > 20000) throw new Error('此版支援最多 20,000 個軌跡點。');
    }
  });
  if (points.length < 2) throw new Error('紀錄至少需要兩個帶時間的軌跡點。');
  return points;
}
export async function digest(value) {
  const bytes = value instanceof ArrayBuffer ? new Uint8Array(value) : new TextEncoder().encode(typeof value === 'string' ? value : JSON.stringify(value));
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
}
export function validateBackup(value, projectId) {
  const d = value?.draft, s = value?.snapshot;
  if (value?.schema_version !== 'trip-notebook-backup.v1' || d?.schema_version !== SCHEMA || s?.schema_version !== 'trip-notebook.v1' || d.project_id !== projectId || s.project_id !== projectId || d.route_version !== s.version || !Array.isArray(s.points) || !Array.isArray(s.geometry) || !Array.isArray(s.planning_node_ids) || !Array.isArray(s.segments) || !Array.isArray(d.points) || d.points.length>20000 || !Array.isArray(d.checkins) || !d.plan?.legs || !d.plan?.stops || !/^[A-Za-z0-9._-]{1,100}$/.test(d.id)) throw new Error('備份格式、路線或版本不符；未覆寫任何資料。');
  if (!/^[a-f0-9]{64}$/.test(s.version) || s.geometry.length>20000 || s.points.length>5000 || d.checkins.length>5000 || !s.weather || !Array.isArray(s.weather.forecasts) || !s.diagnostics || !Array.isArray(s.sources) || !Array.isArray(s.source_resolution) || !Array.isArray(s.issues)) throw new Error('備份資料結構不完整。');
  const finite=n=>typeof n==='number' && Number.isFinite(n);
  if(s.geometry.some(p=>!Array.isArray(p) || !finite(p[0]) || !finite(p[1]) || Math.abs(p[0])>180 || Math.abs(p[1])>90) || s.points.some(p=>typeof p.id!=='string' || !finite(p.lat) || !finite(p.lon) || Math.abs(p.lat)>90 || Math.abs(p.lon)>180)) throw new Error('備份的路徑或地點座標無效。');
  let previous=-Infinity;
  for(const p of d.points) {
    const time=Date.parse(p.timestamp);
    if(!finite(p.lat) || !finite(p.lon) || Math.abs(p.lat)>90 || Math.abs(p.lon)>180 || !Number.isFinite(time) || time<=previous || !/(Z|[+-]\d\d:\d\d)$/.test(p.timestamp)) throw new Error('備份軌跡的座標或時間無效。');
    previous=time;
  }
  if(!['planning','recording','draft','completed'].includes(d.status) || ![null,'simulation','user_import'].includes(d.origin) || typeof d.notes!=='string' || typeof d.resources!=='string' || typeof d.title!=='string' || !['forward','reverse'].includes(d.plan.direction)) throw new Error('備份紀錄狀態不符。');
  if(d.origin==='user_import' && s.sources.some(ref=>ref.sha256===d.track_hash)) throw new Error('參考來源不能還原為本人紀錄。');
  s.boundary={candidate_only:true,runtime_safety_truth:false,phase1_runtime_mutation_allowed:false,workspace_write_allowed:false,outbound_sync_allowed:false,departure_approval_granted:false};
  // Preserve a validated analysis snapshot, labelled as restored evidence.
  if(d.analysis) {
    const a=d.analysis, policy=a.rest_policy;
    if(a.schema_version!=='trip-notebook-analysis.v1' || a.draft_id!==d.id || !policy || !/^[a-f0-9]{64}$/.test(a.receipt_id) || ['elapsed_s','rest_s','moving_s','unclassified_gap_s','distance_m','ascent_m','descent_m'].some(k=>!finite(a[k]) || a[k]<0) || ['rest_speed_threshold_kmh','rest_radius_m','min_rest_duration_s'].some(k=>!finite(policy[k]) || policy[k]<0)) throw new Error('備份中的分析回執不完整。');
    d.analysis={...a,restored_from_backup:true,boundary:s.boundary,saved_to_workspace:false,sent:false};
  }
  return value;
}
