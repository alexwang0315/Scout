import test from "node:test";
import assert from "node:assert/strict";
import {JSDOM} from "jsdom";
import {parseGpx, buildTimeline, samplePlayback, routeGeoJSON, timestampMillis} from "../docs/admin/experiments/gpx-3d/gpx.mjs";
import {meshElevation, mercator} from "../docs/admin/experiments/gpx-3d/terrain.mjs";
import {createSelection} from "../docs/admin/experiments/gpx-3d/selection.mjs";

const dom = new JSDOM();
globalThis.window = dom.window; globalThis.CustomEvent = dom.window.CustomEvent;
const parse = xml => parseGpx(xml, "synthetic-unit-test.gpx", dom.window.DOMParser);
const pt = (lat, lon, content = "") => `<trkpt lat="${lat}" lon="${lon}">${content}</trkpt>`;
const gpx = content => `<gpx xmlns="http://www.topografix.com/GPX/1/1">${content}</gpx>`;
const segment = content => `<trkseg>${content}</trkseg>`;

test("GPX axis order, source segments, all points and source endpoints survive", () => {
  const model = parse(gpx(`<trk>${segment(pt(23,121)+pt(23.1,121.1))}${segment(pt(24,122)+pt(24.1,122.1))}</trk>`));
  assert.equal(model.source_segment_count, 2);assert.equal(model.segments.length, 2);
  assert.equal(model.points.length, 4);
  assert.deepEqual(routeGeoJSON(model).features[0].geometry.coordinates, [[121,23],[121.1,23.1]]);
  assert.equal(model.nodes[0].lon, 121);assert.equal(model.nodes.at(-1).lat, 24.1);
  assert.equal(model.nodes.length, 2);assert.equal(model.data_type, "unknown");
});

test("invalid coordinates create a break; missing and nonfinite elevation are null", () => {
  const model = parse(gpx(`<trk>${segment(pt(23,121)+pt("NaN",120)+pt(23.1,121.1,"<ele>NaN</ele>")+pt(23.2,121.2,"<ele>0</ele>"))}</trk>`));
  assert.equal(model.invalid_coordinate_count, 1);assert.equal(model.segments.length, 2);
  assert.equal(model.points[0].gpx_elevation_m, null);assert.equal(model.points[1].gpx_elevation_m, null);
  assert.equal(model.points[2].gpx_elevation_m, 0);assert.equal(model.points[1].source_index, 2);
});

test("only source wpt nodes count; rte and unnamespaced documents work", () => {
  const model = parse('<gpx><wpt lat="23" lon="121"><name>Source waypoint</name></wpt><rte><rtept lat="23" lon="121"/><rtept lat="23.1" lon="121.1"/></rte></gpx>');
  assert.equal(model.nodes.length, 3);assert.equal(model.nodes[1].name, "Source waypoint");
  assert.equal(model.route_element_count, 1);assert.equal(model.nodes[1].time, null);
});

test("empty, malformed, DTD and non-GPX sources reject explicitly", () => {
  for (const xml of ['<gpx/>', '<gpx><trk>', '<html/>', '<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///.env">]><gpx/>',gpx(`<trk>${segment(pt(99,200))}</trk>`)]) assert.throws(() => parse(xml));
});

test("recorded time respects unequal intervals and never interpolates across gaps", () => {
  const at = (lon, time) => pt(23,lon,`<time>2026-09-07T00:${time}Z</time>`);
  const model = parse(gpx(`<trk>${segment(at(121,"00:00")+at(121.1,"01:00"))}${segment(at(122,"03:00")+at(122.1,"04:00"))}</trk>`));
  const timeline = buildTimeline(model);assert.equal(timeline.mode, "recorded_time");assert.equal(timeline.total,240);
  assert.equal(samplePlayback(timeline,.5).gap,true);assert.equal(samplePlayback(timeline,.5).position,null);
  assert.deepEqual(samplePlayback(timeline,.125).position,[121.05,23]);
  assert.deepEqual(samplePlayback(timeline,1).position,[122.1,23]);
});

test("missing, ambiguous or reversed times use uniform distance illustration", () => {
  for (const times of [[null,null],["2026-09-07T00:00:00Z",null],["2026-09-07T00:00:00Z","2026-09-06T00:00:00Z"],["2026-09-07T00:00:00","2026-09-07T01:00:00"]]) {
    const model = parse(gpx(`<trk>${segment(times.map((t,i)=>pt(23,121+i*.1,t ? `<time>${t}</time>` : "")).join(""))}</trk>`));
    const timeline = buildTimeline(model);assert.equal(timeline.mode,"uniform_distance_illustration");
    assert.equal(samplePlayback(timeline,.5).time,null);
  }
  assert.equal(timestampMillis("2026-02-30T00:00:00Z"),null);
  assert.equal(timestampMillis("2026-09-07T00:00:00+15:00"),null);
});

test("uniform replay skips segment gaps and never includes their distance", () => {
  const model = parse(gpx(`<trk>${segment(pt(0,0)+pt(0,.1))}${segment(pt(0,10)+pt(0,10.1))}</trk>`));
  const t = buildTimeline(model);assert.ok(t.display_distance_m < 23000);
  const p = samplePlayback(t,.501);assert.ok(p.position[0] >= 10);
});

test("God's Eye View actual selection module shares clicks and survives replay", () => {
  const seen=[];const selection=createSelection(node=>seen.push(node?.id));
  selection.reset([{id:"a",name:"A"},{id:"b",name:"B"}]);
  selection.select("a");assert.equal(selection.current().id,"a");
  const model = parse(gpx(`<trk>${segment(pt(23,121)+pt(23.1,121.1))}</trk>`));
  samplePlayback(buildTimeline(model),.5);
  assert.equal(selection.current().id,"a");selection.select("b");assert.equal(seen.at(-1),"b");
  selection.reset([]);assert.equal(selection.current(),null);selection.dispose();
});

test("long routes are not simplified; antimeridian and unsupported polar points break", () => {
  const xml=gpx(`<trk>${segment(Array.from({length:12000},(_,i)=>pt(23,121+i/100000)).join(""))}</trk>`);
  const model=parse(xml);assert.equal(model.points.length,12000);assert.equal(routeGeoJSON(model).features[0].geometry.coordinates.length,12000);
  const polar=parse(gpx(`<trk>${segment(pt(23,179)+pt(23,-179)+pt(89,0)+pt(24,-179))}</trk>`));
  assert.equal(polar.points.length,4);assert.equal(polar.segments.length,3);
});

test("visual mesh interpolation is separate and never fills outside support", () => {
  const [x,y]=mercator(121,23);
  const mesh={status:"ready",x0:x-5,y0:y+5,step_m:10,width:2,height:2,elevations:[100,200,300,400]};
  assert.ok(Math.abs(meshElevation(mesh,121,23)-250)<1e-6);
  assert.equal(meshElevation(mesh,122,23),null);
  mesh.elevations[0]=null;assert.equal(meshElevation(mesh,121,23),null);
});
