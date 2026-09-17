// Display-only GPX parsing. The original bytes, segments and source indices are
// retained separately from rendering geometry. No runtime imports.
export const MERCATOR_LIMIT = 85.0511287798066;

const child = (element, name) => Array.from(element.children).filter(
  item => item.localName === name && item.namespaceURI === element.namespaceURI,
);
const text = (element, name) => child(element, name)[0]?.textContent?.trim() || null;
const number = value => value !== null && String(value).trim() !== "" && Number.isFinite(Number(value)) ? Number(value) : null;

export function timestampMillis(value) {
  // A timezone is required: never interpret an ambiguous GPX time in the
  // operator's browser timezone, or let Date.parse normalize impossible dates.
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(value || "");
  if (!match) return null;
  const [, year, month, day, hour, minute, second, , zone] = match;
  const monthDays = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  if (Number(month) < 1 || Number(month) > 12 || Number(day) < 1 || Number(day) > monthDays
    || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59) return null;
  if (zone !== "Z" && (Number(zone.slice(1, 3)) > 14 || Number(zone.slice(4)) > 59
    || (Number(zone.slice(1, 3)) === 14 && Number(zone.slice(4)) !== 0))) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function point(element, id, sourceRef) {
  const lat = number(element.getAttribute("lat"));
  const lon = number(element.getAttribute("lon"));
  if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  const time = text(element, "time");
  return {
    id, lat, lon, name: text(element, "name"),
    gpx_elevation_m: number(text(element, "ele")),
    dem_elevation_m: null, cp_elevation_m: null,
    gpx_vertical_datum: "unknown", time, time_ms: timestampMillis(time),
    source_ref: sourceRef, display_supported: Math.abs(lat) <= MERCATOR_LIMIT,
  };
}

export function parseGpx(xml, sourceRef, Parser = globalThis.DOMParser) {
  if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error("GPX 不接受 DTD 或外部實體。");
  const document = new Parser().parseFromString(xml, "application/xml");
  const root = document.documentElement;
  if (document.querySelector("parsererror") || root?.localName !== "gpx"
    || ![null, "", "http://www.topografix.com/GPX/1/1", "http://www.topografix.com/GPX/1/0"].includes(root.namespaceURI)) {
    throw new Error("無效 GPX：請選擇 GPX 1.0 / 1.1 XML 檔案。");
  }
  const segments = [];
  const points = [];
  const nodes = [];
  let sourceSegmentCount = 0;
  let sourcePointCount = 0;
  let invalidCoordinateCount = 0;
  let unsupportedCoordinateCount = 0;
  let emptySegmentCount = 0;
  let routeElementCount = 0;
  // Document order is preserved even for multi-track / mixed rte + trk input.
  for (const container of Array.from(root.children)) {
    if (container.namespaceURI !== root.namespaceURI) continue;
    const groups = container.localName === "trk" ? child(container, "trkseg")
      : container.localName === "rte" ? [container] : [];
    if (container.localName === "rte") routeElementCount += 1;
    for (const group of groups) {
      const sourceSegmentId = sourceSegmentCount++;
      const entries = child(group, container.localName === "rte" ? "rtept" : "trkpt");
      if (!entries.length) emptySegmentCount += 1;
      let run = [];
      let part = 0;
      const flush = () => {
        if (run.length) segments.push({id: `${sourceSegmentId}:${part++}`, source_segment_id: sourceSegmentId, points: run});
        run = [];
      };
      for (const entry of entries) {
        const sourceIndex = sourcePointCount++;
        const current = point(entry, `point:${sourceIndex}`, sourceRef);
        if (!current) { invalidCoordinateCount += 1; flush(); continue; }
        current.source_index = sourceIndex;
        current.source_segment_id = sourceSegmentId;
        points.push(current);
        if (!current.display_supported) { unsupportedCoordinateCount += 1; flush(); continue; }
        // Avoid a false line around the world at the antimeridian. Retain the
        // raw coordinates; the display/replay explicitly breaks here for V1.
        if (run.length && Math.abs(current.lon - run.at(-1).lon) > 180) flush();
        run.push(current);
      }
      flush();
    }
  }
  for (const [index, entry] of child(root, "wpt").entries()) {
    const current = point(entry, `waypoint:${index}`, sourceRef);
    if (!current) { invalidCoordinateCount += 1; continue; }
    if (!current.display_supported) unsupportedCoordinateCount += 1;
    nodes.push({...current, kind: "waypoint", name: current.name || `Waypoint ${index + 1}`});
  }
  if (!points.length && !nodes.length) throw new Error("空 GPX：沒有有效軌跡點或 waypoint。無效座標不會以 0 取代。");
  if (points.length) {
    nodes.unshift({...points[0], id: "endpoint:start", kind: "start", name: "起點（來源首個有效軌跡點）"});
    nodes.push({...points.at(-1), id: "endpoint:end", kind: "end", name: "終點（來源最後有效軌跡點）"});
  }
  const warnings = [];
  if (invalidCoordinateCount) warnings.push(`${invalidCoordinateCount} 個無效座標已排除，軌跡在該處中斷。`);
  if (unsupportedCoordinateCount) warnings.push(`${unsupportedCoordinateCount} 個極區座標超出 Web Mercator 範圍；保留來源點、不在地圖繪製。`);
  if (emptySegmentCount) warnings.push(`${emptySegmentCount} 個空 segment。`);
  const missingElevation = points.filter(p => p.gpx_elevation_m === null).length;
  if (missingElevation) warnings.push(`${missingElevation} 個軌跡點缺少有效 GPX 高程。`);
  if (!segments.length) warnings.push("沒有可回放的軌跡區段；仍可查看來源節點。");
  if (segments.length > sourceSegmentCount - emptySegmentCount) warnings.push("座標缺口或跨日期變更線處另行斷開展示，未建立連接路段。");
  const allDisplayed = [...segments.flatMap(s => s.points), ...nodes.filter(n => n.display_supported)];
  let bounds = null;
  for (const p of allDisplayed) {
    if (!bounds) bounds = [[p.lon, p.lat], [p.lon, p.lat]];
    else {
      bounds[0][0] = Math.min(bounds[0][0], p.lon); bounds[0][1] = Math.min(bounds[0][1], p.lat);
      bounds[1][0] = Math.max(bounds[1][0], p.lon); bounds[1][1] = Math.max(bounds[1][1], p.lat);
    }
  }
  return {
    name: text(child(root, "metadata")[0] || root, "name") || text(child(root, "trk")[0] || root, "name") || sourceRef,
    source_ref: sourceRef, data_type: "unknown", horizontal_crs: "WGS84 (GPX); GeoJSON [longitude, latitude]",
    vertical_datum: "unknown", source_segment_count: sourceSegmentCount, source_point_count: sourcePointCount,
    missing_elevation_count: missingElevation, invalid_coordinate_count: invalidCoordinateCount,
    route_element_count: routeElementCount, points, segments, nodes, bounds, warnings,
    simplification: "none; original input retained in browser memory",
  };
}

export function distanceMeters(a, b) {
  const radians = value => value * Math.PI / 180;
  const dLat = radians(b.lat - a.lat), dLon = radians(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}

export function buildTimeline(model) {
  const displayed = model.segments.flatMap(s => s.points);
  const recorded = displayed.length > 1 && displayed.length === model.points.length
    && displayed.every((p, i) => p.time_ms !== null && (!i || p.time_ms > displayed[i - 1].time_ms));
  let accumulated = 0;
  const frames = [];
  for (const segment of model.segments) {
    segment.points.forEach((p, index) => {
      if (index) accumulated += distanceMeters(segment.points[index - 1], p);
      frames.push({point: p, segment_id: segment.id, axis: recorded ? (p.time_ms - displayed[0].time_ms) / 1000 : accumulated});
    });
  }
  return {
    mode: recorded ? "recorded_time" : "uniform_distance_illustration",
    label: recorded ? "依 GPX 記錄時間回放" : "等速示意回放",
    reason: recorded ? "時間完整且嚴格遞增；區段缺口不插值。" : "時間缺漏、無效或不遞增；按區段內幾何距離示意，不代表真實速度。",
    frames, total: frames.at(-1)?.axis || 0,
    display_distance_m: accumulated,
  };
}

export function samplePlayback(timeline, fraction) {
  const {frames, total} = timeline;
  if (!frames.length) return {position: null, gap: false, time: null};
  const target = Math.min(1, Math.max(0, fraction)) * total;
  let low = 0, high = frames.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (frames[mid].axis <= target) low = mid + 1; else high = mid;
  }
  const before = frames[Math.max(0, low - 1)], after = frames[low];
  const time = timeline.mode === "recorded_time" ? new Date(frames[0].point.time_ms + target * 1000).toISOString() : null;
  if (after && before.segment_id !== after.segment_id && target > before.axis) return {position: null, gap: true, time};
  if (!after || before.segment_id !== after.segment_id || after.axis === before.axis) return {position: [before.point.lon, before.point.lat], gap: false, time};
  const ratio = (target - before.axis) / (after.axis - before.axis);
  return {position: [before.point.lon + (after.point.lon - before.point.lon) * ratio, before.point.lat + (after.point.lat - before.point.lat) * ratio], gap: false, time};
}

export function routeGeoJSON(model) {
  return {type: "FeatureCollection", features: model.segments.map(segment => ({
    type: "Feature", properties: {segment_id: segment.id},
    geometry: segment.points.length === 1
      ? {type: "Point", coordinates: [segment.points[0].lon, segment.points[0].lat]}
      : {type: "LineString", coordinates: segment.points.map(p => [p.lon, p.lat])},
  }))};
}

export function withinTerrain(point, terrain) {
  const b = terrain?.bounds_wgs84;
  return terrain?.status === "ready" && b && point.lon >= b.west && point.lon < b.east && point.lat > b.south && point.lat <= b.north;
}
