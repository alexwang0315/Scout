"""HTTP persistence and a real one-shot subprocess for the no-GPX entrypoint."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import scout_exploration_jobs as exploration_jobs
from scout_exploration_api import create_exploration_router
from scout_exploration_jobs import ExplorationJobManager, _release
from scout_exploration_workspace import prepare_exploration_workspace
from test_scout_exploration_workspace import _map_fetcher, _native_raster, _point, _request


def _client(tmp_path, queue=None, *, real=False):
    app = FastAPI()
    def preparer(root, preparation_id, **kwargs):
        return prepare_exploration_workspace(root, preparation_id, map_fetcher=_map_fetcher(), **kwargs)
    app.include_router(create_exploration_router(workspace_root=tmp_path / "workspaces",
        **({} if real else {"launch": queue.append, "preparer": preparer})), prefix="/admin")
    return TestClient(app)


def _create(client, **updates):
    response = client.post("/admin/pretrip/exploration/projects", json=_request(**updates))
    assert response.status_code == 201, response.text
    receipt = response.json()
    return receipt, f"/admin/pretrip/projects/{receipt['project_id']}/exploration"


def _command(receipt, key="first", **updates):
    return {"expected_intake_sha256": receipt["intake_sha256"], "idempotency_key": key, **updates}


def test_create_is_zero_gpx_and_reads_do_not_start_or_mutate_jobs(tmp_path):
    queue = []
    client = _client(tmp_path, queue)
    receipt, path = _create(client)
    root = Path(receipt["project_root"])
    before = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    assert receipt["golden_source_id"] is None and receipt["reference_gpxs"] == []
    assert receipt["preparation"]["can_prepare"] is True
    for suffix in ("", "/prepare", "/catalog"):
        response = client.get(path + suffix)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert not queue and not list(root.rglob("*.gpx"))
    assert {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()} == before
    bad = client.post("/admin/pretrip/exploration/projects", json=_request(primary_gpx="invented.gpx"))
    assert bad.status_code == 422


def test_explicit_202_prepare_reload_idempotency_and_resume_preserve_attempts(tmp_path):
    queue=[]; client=_client(tmp_path,queue)
    receipt,path=_create(client)
    command=_command(receipt)
    first=client.post(path+"/prepare",json=command)
    assert first.status_code==202 and first.json()["preparation"]["worker_live"] is True
    assert first.json()["preparation"]["status"]=="queued" and len(queue)==1
    duplicate=client.post(path+"/prepare",json=command)
    assert duplicate.status_code==202 and len(queue)==1
    changed=client.post(path+"/prepare",json={**command,"fetch_map":False})
    assert changed.status_code==409 and len(queue)==1
    queue.pop(0)()
    # Build a fresh server/router: no manager or Python-object cache is reused.
    client=_client(tmp_path,queue)
    current=client.get(path).json()
    assert current["preparation"]["status"]=="completed_with_gaps"
    assert current["preparation"]["attempt"]==1 and current["preparation"]["evidence_current"] is True
    assert current["preparation"]["report"]["map"]["source_count"]==2
    old_report=Path(current["project_root"])/current["preparation"]["report_ref"]
    old_sha=hashlib.sha256(old_report.read_bytes()).hexdigest()
    assert client.post(path+"/prepare",json=command).status_code==202 and not queue
    result=client.post(path+"/prepare/resume",json=_command(receipt,"resume-1"))
    assert result.status_code==202 and len(queue)==1
    queue.pop(0)()
    assert client.get(path).json()["preparation"]["attempt"]==2
    assert hashlib.sha256(old_report.read_bytes()).hexdigest()==old_sha
    assert client.get(path+"/catalog").json()["golden_source_id"] is None


def test_ended_worker_lease_is_reported_interrupted_without_get_restarting(tmp_path):
    queue=[]; client=_client(tmp_path,queue)
    receipt,path=_create(client)
    client.post(path+"/prepare",json=_command(receipt))
    pending=queue.pop(0)
    closure=dict(zip(pending.__code__.co_freevars,[cell.cell_contents for cell in pending.__closure__]))
    _release(closure["fd"])
    root=Path(receipt["project_root"])
    before={p.relative_to(root):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    for _ in range(2):
        state=client.get(path).json()["preparation"]
        assert state["status"]=="interrupted" and state["can_resume"] is True and state["worker_live"] is False
    assert not queue
    assert {p.relative_to(root):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}==before
    assert client.post(path+"/prepare/resume",json=_command(receipt,"recover")).status_code==202
    queue.pop(0)()
    assert client.get(path).json()["preparation"]["status"]=="completed_with_gaps"


def test_changed_intake_or_cross_project_commands_are_rejected(tmp_path):
    queue=[]; client=_client(tmp_path,queue)
    receipt,path=_create(client)
    assert client.post(path+"/prepare",json={**_command(receipt),"expected_intake_sha256":"0"*64}).status_code==409
    assert client.post(path.replace("zero_ref","missing")+"/prepare",json=_command(receipt)).status_code==404
    assert not queue
    assert client.post(path+"/trh-request",json={"expected_intake_sha256":receipt["intake_sha256"]}).status_code==409


def test_trh_post_only_saves_bound_requests_and_does_not_dispatch(tmp_path):
    queue=[]; client=_client(tmp_path,queue)
    receipt,path=_create(client,preparation_inputs=_native_raster(tmp_path),start=_point(280240,2659200),
        destination=_point(280700,2658700),limits={"days":1,"fixed_speed_kmh":2})
    client.post(path+"/prepare",json=_command(receipt));queue.pop(0)()
    response=client.post(path+"/trh-request",json={"expected_intake_sha256":receipt["intake_sha256"],"corridor_m":0})
    assert response.status_code==200,response.text
    result=response.json()
    assert result["request_count"]==1 and result["submitted"] is False and result["route_activated"] is False
    assert result["candidate_only"] is True and result["runtime_safety_truth"] is False and not queue
    artifact=Path(receipt["project_root"])/result["artifact_ref"]
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==result["artifact_sha256"]
    assert not list(Path(receipt["project_root"]).rglob("*.gpx"))


def test_real_one_shot_worker_survives_a_new_http_client_and_finishes(tmp_path, monkeypatch):
    pids, exit_codes = [], []
    reaped = threading.Event()
    original_popen = subprocess.Popen

    class ObservedPopen(original_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            pids.append(self.pid)

        def wait(self, *args, **kwargs):
            code = super().wait(*args, **kwargs)
            exit_codes.append(code)
            reaped.set()
            return code

    # Record only primitive values; a test-held Popen would hide lost ownership.
    monkeypatch.setattr(exploration_jobs.subprocess, "Popen", ObservedPopen)
    client=_client(tmp_path,real=True)
    receipt,path=_create(client)
    started=client.post(path+"/prepare",json=_command(receipt,fetch_map=False))
    assert started.status_code==202
    client.close()
    client=_client(tmp_path,real=True)
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        state=client.get(path+"/prepare").json()["preparation"]
        if state["status"] not in {"queued","running"}:
            break
        time.sleep(.05)
    assert state["status"]=="completed_with_gaps",state
    assert state["attempt"]==1 and state["worker_live"] is False
    assert state["report"]["map"]["status"]=="not_requested"
    assert state["report"]["primary_gpx"] is None and state["report"]["reference_gpxs"]==[]
    assert reaped.wait(max(0, deadline - time.monotonic())), "Worker exited but parent did not reap it"
    assert exit_codes == [0] and len(pids) == 1
    with pytest.raises(ChildProcessError):
        os.waitpid(pids[0], os.WNOHANG)
    client.close()


def test_exploration_ui_create_prepare_restore_and_candidate_scope(tmp_path):
    node=shutil.which("node")
    assert node,"Node is required for the actual exploration UI DOM test"
    script=Path(__file__).resolve().parents[1]/"docs/admin/scout-exploration-workflow.js"
    code=r'''
const assert=require("node:assert/strict"),fs=require("node:fs"),{JSDOM}=require("jsdom");
const dom=new JSDOM('<main id="root"></main>',{url:"http://localhost",runScripts:"outside-only"});
const win=dom.window;win.eval(fs.readFileSync(process.argv[1],"utf8"));const ui=win.ScoutExplorationWorkflow;
let project="",receipt=null,calls=[],created=0,queued=0;
const host={apiGet:async path=>{calls.push({method:"GET",path});if(path.endsWith("/catalog"))return {project_id:project,golden_source_id:null,sources:[{source_id:"map.1",label:"Actual source <script>",kind:"overpass",parts:[[{lat:24,lon:121},{lat:24.001,lon:121.001}]],sha256:"a".repeat(64)}],issues:[]};return structuredClone(receipt);},
 apiPost:async(path,body)=>{calls.push({method:"POST",path,body});if(path.endsWith("/projects")){created++;receipt={project_id:body.project_id,intake:body,intake_sha256:"b".repeat(64),preparation_id:"explore.123",golden_source_id:null,reference_gpxs:[],unknowns:[{code:"start_unknown",message:"A/B remains unknown"}],preparation:{status:"queued",attempt:0,can_prepare:true,can_resume:false}};return structuredClone(receipt);}if(path.endsWith("/prepare")){queued++;receipt.preparation={status:"running",attempt:1,stage:"map",worker_live:true,can_prepare:false,can_resume:false};return structuredClone(receipt);}throw Error(path);},
 onProjectCreated:async id=>{project=id;},refresh:()=>{win.document.querySelector("#root").innerHTML=ui.render({projectId:project});ui.bind(win.document,host);}};
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));async function flush(){for(let i=0;i<10;i++)await tick();}
function el(selector){const x=win.document.querySelector(selector);assert.ok(x,selector);return x;}
function fill(key,value){const x=el(`[data-exploration-field="${key}"]`);x.value=value;x.dispatchEvent(new win.Event("input",{bubbles:true}));}
function click(action){el(`[data-exploration-action="${action}"]`).click();}
(async()=>{
 host.refresh();fill("projectId","area_one");fill("intent","從區域開始");fill("west","121");fill("south","24");fill("east","121.01");fill("north","24.01");click("create");await flush();
 assert.equal(created,1);assert.equal(queued,0);const request=calls.find(x=>x.method==="POST").body;assert.equal(request.primary_gpx,undefined);assert.equal(request.start,undefined);assert.equal(request.aoi.crs,"EPSG:4326");
 assert.equal(el('[data-exploration-action="prepare"]').disabled,false);click("prepare");await flush();assert.equal(queued,1);assert.equal(el('[data-exploration-results]').dataset.explorationAttempt,"1");
 const before=calls.filter(x=>x.method==="POST").length;
 // A true fresh script/DOM instance reconstructs from the saved API receipt.
 const second=new JSDOM('<main id="root"></main>',{url:"http://localhost/reloaded",runScripts:"outside-only"});second.window.eval(fs.readFileSync(process.argv[1],"utf8"));
 const reui=second.window.ScoutExplorationWorkflow;const rehost={...host,refresh:()=>{second.window.document.querySelector("#root").innerHTML=reui.render({projectId:project});reui.bind(second.window.document,rehost);}};
 rehost.refresh();await flush();assert.equal(calls.filter(x=>x.method==="POST").length,before);assert.equal(second.window.document.querySelector('[data-exploration-results]').dataset.explorationAttempt,"1");
 second.window.document.querySelector('[data-exploration-action="catalog"]').click();await flush();assert.equal(second.window.document.querySelectorAll('[data-exploration-source]').length,1);assert.ok(second.window.document.querySelector('[data-exploration-catalog]').textContent.includes("Actual source <script>"));assert.equal(second.window.document.querySelectorAll("script").length,0);
 assert.equal(second.window.document.querySelector('[data-exploration-action="trh"]').disabled,true);
 process.stdout.write(JSON.stringify({created,queued,reloaded_without_post:true,source_scope:true}));second.window.close();dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;dom.window.close();});
'''
    result=subprocess.run([node,"-e",code,str(script)],cwd=script.parents[2],text=True,capture_output=True,check=True)
    assert json.loads(result.stdout)=={"created":1,"queued":1,"reloaded_without_post":True,"source_scope":True}
