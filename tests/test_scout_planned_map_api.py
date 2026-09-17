"""Map HTTP boundaries and actual DOM actions; human decisions here are fixtures."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scout_planned_map_api import create_planned_map_router, register_planned_map_review_packet
from scout_planned_map_materialization import materialize_rudy_trace
from scout_planned_route_sources import load_map_route_sources
from test_scout_planned_map_materialization import _project, _rudy, _write


def _client(root):
    app = FastAPI()
    app.include_router(create_planned_map_router(project_root_for=lambda project_id: root if project_id == _project(root)["project_id"] else None), prefix="/admin")
    return TestClient(app)


def _snapshot(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}


def _pbf(root):
    import osmium
    ref = "map/source.osm.pbf"
    _write(root, "project.json", {"project_id": "map-api-test", "osm_pbf_route_extract_ref": ref})
    path = root / ref; path.parent.mkdir(parents=True, exist_ok=True)
    with osmium.SimpleWriter(str(path)) as writer:
        writer.add_node(osmium.osm.mutable.Node(id=10, location=(121,23)))
        writer.add_node(osmium.osm.mutable.Node(id=11, location=(121.001,23)))
        writer.add_way(osmium.osm.mutable.Way(id=42, nodes=[10,11], tags={"highway":"path"}))
    return {"source_kind":"osm_pbf", "source_ref":ref, "expected_source_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "bbox_wgs84":{"south":22.9,"west":120.9,"north":23.1,"east":121.1},
        "requested_by":"test_explicit_action", "explicit_rebuild_confirmed":True}


def test_get_restoration_is_read_only_and_rebuild_uses_registered_real_pbf(tmp_path):
    command=_pbf(tmp_path);client=_client(tmp_path);base="/admin/pretrip/projects/map-api-test/planned-map"
    before=_snapshot(tmp_path)
    for suffix in ("/catalog","/versions"):
        response=client.get(base+suffix)
        assert response.status_code==200 and response.headers["Cache-Control"]=="no-store"
    assert _snapshot(tmp_path)==before
    assert client.post(base+"/rebuild",json={**command,"explicit_rebuild_confirmed":False}).status_code==422
    response=client.post(base+"/rebuild",json=command)
    assert response.status_code==201,response.text
    receipt=response.json();assert receipt["source_state"]=="topology_ready"
    assert {ref:_snapshot(tmp_path)[ref] for ref in before}==before
    sources=load_map_route_sources(tmp_path,_project(tmp_path))["sources"]
    assert [point["osm_node_id"] for point in sources[0]["parts"][0]]==[10,11]
    exact=client.get(base+"/versions/"+receipt["materialization_id"])
    assert exact.status_code==200 and exact.json()["manifest_sha256"]==receipt["manifest_sha256"]
    assert "requested_at" in exact.json()["manifest"]["request"]
    assert client.post(base+"/rebuild",json={**command,"requested_at":"2099-01-01T00:00:00Z"}).status_code==422
    assert client.post(base+"/rebuild",json={**command,"source_ref":"project.json"}).status_code==409
    assert client.post(base+"/rebuild",json={**command,"expected_source_sha256":"0"*64}).status_code==409
    assert client.get(base.replace("map-api-test","missing")+"/catalog").status_code==404


def _draft(client, request):
    payload={key:request[key] for key in ("label","geometry","map_evidence","review_note")}
    payload.update(created_by="fixture_software",draft_creation_confirmed=True)
    result=client.post("/admin/pretrip/projects/rudy-review/planned-map/rudy/drafts",json=payload)
    assert result.status_code==201,result.text
    return result.json(),payload


def _human_command(receipt):
    return {"expected_manifest_sha256":receipt["manifest_sha256"],"reviewer_name":"Fixture human, not real approval",
        "review_note":"Test fixture only: preserve exact software trace", "candidate_review_confirmed":True,"source_geometry_confirmed":True}


def test_human_review_is_new_exact_version_and_preserves_software_authorship(tmp_path):
    request=_rudy(tmp_path);client=_client(tmp_path);receipt,payload=_draft(client,request)
    base="/admin/pretrip/projects/rudy-review/planned-map/versions/"+receipt["materialization_id"]
    before=_snapshot(tmp_path);command=_human_command(receipt)
    assert not load_map_route_sources(tmp_path,_project(tmp_path))["sources"]
    for invalid in ({"candidate_review_confirmed":False},{"source_geometry_confirmed":False},{"reviewer_name":" "},{"geometry":request["geometry"]},{"reviewer_kind":"software"}):
        assert client.post(base+"/human-review",json={**command,**invalid}).status_code==422
    assert client.post(base+"/human-review",json={**command,"expected_manifest_sha256":"0"*64}).status_code==409
    assert _snapshot(tmp_path)==before
    result=client.post(base+"/human-review",json=command)
    assert result.status_code==201,result.text
    reviewed=result.json();assert reviewed["materialization_id"]!=receipt["materialization_id"]
    exact=client.get("/admin/pretrip/projects/rudy-review/planned-map/versions/"+reviewed["materialization_id"]).json()
    props=exact["trace"]["properties"]
    assert props["human_reviewed"] is True and props["field_verified"] is False
    assert props["trace_author_kind"]=="software" and props["reviewer_kind"]=="human"
    assert exact["manifest"]["request"]["geometry"]==request["geometry"]
    assert exact["manifest"]["request"]["reviewed_draft_sha256"]==receipt["manifest_sha256"]
    assert receipt["manifest_ref"] in exact["manifest"]["input_source_hashes"]
    assert all(_snapshot(tmp_path)[ref]==sha for ref,sha in before.items() if not ref.endswith("catalog.json"))
    assert client.get(base).json()["manifest"]["source_state"]=="pending_human_review"
    assert len(load_map_route_sources(tmp_path,_project(tmp_path))["sources"])==1


def test_only_current_bound_registered_artifacts_can_be_served(tmp_path):
    request=_rudy(tmp_path);client=_client(tmp_path);receipt,_=_draft(client,request)
    base="/admin/pretrip/projects/rudy-review/planned-map/versions/"+receipt["materialization_id"]
    exact=client.get(base).json();ref=next(ref for ref in exact["manifest"]["artifacts"] if ref.endswith(".png"))
    params={"ref":ref,"expected_manifest_sha256":receipt["manifest_sha256"]}
    response=client.get(base+"/artifact",params=params)
    assert response.status_code==200 and response.content.startswith(b"\x89PNG")
    assert response.headers["x-content-type-options"]=="nosniff" and "sandbox" in response.headers["content-security-policy"]
    for forbidden in ("project.json","map/rudy.png","../secret","/etc/passwd"):
        assert client.get(base+"/artifact",params={**params,"ref":forbidden}).status_code==409
    assert client.get(base+"/artifact",params={**params,"expected_manifest_sha256":"0"*64}).status_code==409
    (tmp_path/"map/rudy.png").write_bytes(b"changed")
    assert client.get(base+"/artifact",params=params).status_code==409
    assert client.post(base+"/human-review",json=_human_command(receipt)).status_code==409
    states=client.get("/admin/pretrip/projects/rudy-review/planned-map/versions").json()["source_states"]
    assert states[0]["status"]=="stale_or_unavailable"


def test_registered_r4_packet_is_read_only_bound_to_sources_and_links_no_fake_execution(tmp_path):
    request=_rudy(tmp_path);client=_client(tmp_path)
    packet={"project_id":"rudy-review","guidance_id":"guidance-fixture","narrative":"Fixture narrative <script>",
        "anchor_proposals":[],"candidate_only":True,"runtime_safety_truth":False,"actual_R4_worker_submitted":False}
    receipt=register_planned_map_review_packet(tmp_path,packet=packet,source_hashes={"map/rudy.png":request["map_evidence"][0]["sha256"]},attachments={"overview.svg":b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'})
    base="/admin/pretrip/projects/rudy-review/planned-map";before=_snapshot(tmp_path)
    assert client.get(base+"/catalog").json()["review_packets"][0]["packet_id"]==receipt["packet_id"]
    result=client.get(base+"/packets/"+receipt["packet_id"])
    assert result.status_code==200 and result.json()["packet"]["actual_R4_worker_submitted"] is False
    endpoint=base+"/packets/"+receipt["packet_id"]+"/artifact"
    assert client.get(endpoint,params={"ref":receipt["packet_ref"],"expected_manifest_sha256":receipt["manifest_sha256"]}).status_code==200
    assert _snapshot(tmp_path)==before
    (tmp_path/"map/rudy.png").write_bytes(b"changed")
    assert client.get(base+"/packets/"+receipt["packet_id"]).status_code==409


def test_dashboard_map_review_only_posts_after_explicit_action(tmp_path):
    node=shutil.which("node");assert node,"Node is required for the map-review DOM proof"
    script=Path(__file__).resolve().parents[1]/"docs/admin/scout-planned-map-review.js"
    code=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<main id="root"></main>',{url:'http://localhost/dashboard?projectId=demo',runScripts:'outside-only'}),win=dom.window;
win.eval(fs.readFileSync(process.argv[1],'utf8'));const ui=win.ScoutPlannedMapReview;let calls=[],reviewed=false;
const id='a'.repeat(64),sha='b'.repeat(64),ref=`outputs/${id}/tile.png`;
const packet={project_id:'demo',manifest_sha256:sha,manifest:{materialization_id:id,kind:'rudy_trace',source_state:'pending_human_review'},trace:{properties:{trace_author_kind:'software',reviewer_kind:'software',review_note:'Pending <script> review',source_artifacts:[{ref,sha256:'c'.repeat(64),z:0,x:0,y:0}]},features:[{properties:{name:'Map <script>'},geometry:{type:'LineString',coordinates:[[121,23],[121.001,23.001]]}}]}};
const host={apiGet:async path=>{calls.push({method:'GET',path});if(path.endsWith('/catalog'))return {project_id:'demo',source_states:[],pbf_sources:[]};if(path.endsWith('/versions'))return {project_id:'demo',source_states:[{source_kind:'rudy_trace',materialization_id:id,status:'pending_human_review'}]};return structuredClone(packet);},
 apiPost:async(path,body)=>{calls.push({method:'POST',path,body});assert.ok(path.endsWith('/human-review'));assert.equal(body.expected_manifest_sha256,sha);assert.equal(body.source_geometry_confirmed,true);assert.equal(body.geometry,undefined);reviewed=true;packet.manifest.source_state='human_reviewed';return {materialization_id:id};},refresh:()=>{win.document.querySelector('#root').innerHTML=ui.render({projectId:'demo'});ui.bind(win.document,host);}};
const tick=()=>new Promise(r=>setTimeout(r,0));async function flush(){for(let i=0;i<12;i++)await tick();}
const el=s=>{const n=win.document.querySelector(s);assert.ok(n,s);return n;};
function fill(key,value){const n=el(`[data-planned-map-field="${key}"]`);if(n.type==='checkbox')n.checked=value;else n.value=value;n.dispatchEvent(new win.Event('input',{bubbles:true}));}
(async()=>{host.refresh();await flush();assert.equal(calls.filter(c=>c.method==='POST').length,0);el('[data-planned-map-action="inspect"]').click();await flush();
 assert.equal(el('[data-planned-map-field="confirmed"]').disabled,true);assert.equal(el('[data-planned-map-action="human-review"]').disabled,true);
 assert.ok(el('[data-planned-map-inspected]').textContent.includes('Map <script>'));assert.equal(win.document.querySelectorAll('script').length,0);
 const image=el('[data-planned-map-original]');Object.defineProperty(image,'naturalWidth',{value:256});Object.defineProperty(image,'naturalHeight',{value:256});image.dispatchEvent(new win.Event('load'));
 assert.equal(el('[data-planned-map-field="confirmed"]').disabled,false);fill('reviewer','Fixture human');fill('note','Fixture exact trace only');assert.equal(el('[data-planned-map-action="human-review"]').disabled,true);fill('confirmed',true);assert.equal(el('[data-planned-map-action="human-review"]').disabled,false);
 el('[data-planned-map-action="human-review"]').click();await flush();assert.equal(reviewed,true);assert.equal(calls.filter(c=>c.method==='POST').length,1);
 host.refresh();await flush();assert.equal(calls.filter(c=>c.method==='POST').length,1);
 process.stdout.write(JSON.stringify({restored_without_post:true,image_gate:true,explicit_exact_review:true,escaped_source_text:true}));dom.window.close();})().catch(error=>{console.error(error);process.exitCode=1;dom.window.close();});
'''
    result=subprocess.run([node,"-e",code,str(script)],text=True,capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)=={"restored_without_post":True,"image_gate":True,"explicit_exact_review":True,"escaped_source_text":True}
