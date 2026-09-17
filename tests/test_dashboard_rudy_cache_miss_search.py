"""Finite search/model regressions only; not real Dashboard cache-miss qualification."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_dashboard_rudy_live_diagnostic import BASE, MODULE, ROOT, WORKFLOW, node

SEARCH = r"""
const view={tiles:[{z:20,x:850000,y:450000}],tileTemplate:href().replace('/20/850000/450000.png','/{z}/{x}/{y}.png')};
const descriptor={renderer:'svg',doc:{location:{href:base}},tileView:()=>view};
const response=status=>({ok:status===200,status,headers:headers(),blob:async()=>new Blob(['controlled fixture'])});
"""


def test_candidate_domain_is_complete_finite_unique_and_reproducible():
    node(BASE + SEARCH + r"""
const first=api.cacheMissCandidates(view,20),second=api.cacheMissCandidates(view,20);
assert.deepEqual(first,second);assert.equal(first.radius,32);
assert.equal(first.candidates.length,65*65-1);
assert.equal(new Set(first.candidates.map(item=>item.key)).size,first.candidates.length);
for(let x=850000-32;x<=850000+32;x++)for(let y=450000-32;y<=450000+32;y++){
 if(x===850000&&y===450000)continue;
 assert.ok(first.candidates.some(item=>item.x===x&&item.y===y));
}
assert.equal(first.candidates[0].key,'20/850001/450000');
""")


@pytest.mark.parametrize("x,y", [(0, 0), (2**20 - 1, 2**20 - 1)])
def test_world_bounds_never_emit_invalid_xyz(x, y):
    node(BASE + SEARCH + f"\nview.tiles=[{{z:20,x:{x},y:{y}}}];\n" + r"""
const plan=api.cacheMissCandidates(view,20);
assert.equal(plan.candidates.length,33*33-1);
assert.ok(plan.candidates.every(t=>t.x>=0&&t.y>=0&&t.x<2**20&&t.y<2**20));
""")


def test_source_bounds_can_exhaust_domain_without_fabricating_miss():
    node(BASE + SEARCH + r"""
const lon=x=>x/(2**20)*360-180,lat=y=>Math.atan(Math.sinh(Math.PI*(1-2*y/(2**20))))*180/Math.PI;
view.sourceBounds=[lon(850000+.1),lat(450000+.9),lon(850000+.9),lat(450000+.1)];
let calls=0;global.fetch=async()=>{calls++;return response(404)};
(async()=>{await assert.rejects(api.findCacheMiss(descriptor,{matrix:20},project),error=>{
 assert.match(error.message,/No genuine cache miss/);assert.equal(error.cacheMissSearchEvidence.eligibleCount,0);return true});
 assert.equal(calls,0);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_old_24_probe_hits_do_not_hide_a_missing_diagonal_tile():
    node(BASE + SEARCH + r"""
const calls=[];global.fetch=async url=>{calls.push(url);return response(new URL(url).pathname.includes('/20/850001/450001.png')?404:200)};
(async()=>{const result=await api.findCacheMiss(descriptor,{matrix:20},project);
 assert.equal(result.key,'20/850001/450001');assert.equal(result.status,404);
 assert.ok(calls.every(url=>new URL(url).searchParams.get('cache_only')==='1'&&!new URL(url).searchParams.has('native')));
 assert.equal(result.requestReceipt.mode,'cache');assert.equal(result.requestReceipt.outcome,'missing');
 assert.equal(result.cacheMissSearchEvidence.selected.requestId,result.requestReceipt.requestId);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_exhausted_neighborhood_remains_unverified_with_full_prior_hit_evidence():
    node(BASE + SEARCH + r"""
let calls=0;global.fetch=async()=>{calls++;return response(200)};
const state={knownHits:new Map()};
(async()=>{let first,second;
 await assert.rejects(api.findCacheMiss(descriptor,{matrix:20},project,{searchState:state,caseKey:'one'}),error=>{first=error.cacheMissSearchEvidence;return /No genuine cache miss/.test(error.message)});
 await assert.rejects(api.findCacheMiss(descriptor,{matrix:20},project,{searchState:state,caseKey:'two'}),error=>{second=error.cacheMissSearchEvidence;return /No genuine cache miss/.test(error.message)});
 assert.equal(calls,65*65-1);assert.equal(first.examined.length,calls);assert.equal(first.status,'unverified');
 assert.equal(second.examined.length,0);assert.equal(second.priorHits.length,calls);assert.equal(second.status,'unverified');
 assert.ok(second.priorHits.every(row=>row.httpStatus===200&&row.caseKey==='one'&&Number.isFinite(row.requestId)));
 assert.equal(second.selected,null);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_non404_network_failure_is_not_bypassed_to_find_a_convenient_miss():
    node(BASE + SEARCH + r"""
let calls=0;global.fetch=async()=>{calls++;return response(calls===1?503:404)};
(async()=>{await assert.rejects(api.findCacheMiss(descriptor,{matrix:20},project),error=>{
 assert.match(error.message,/HTTP 503/);assert.equal(error.requestReceipt.httpStatus,503);
 assert.equal(error.cacheMissSearchEvidence.status,'unverified');return true});assert.equal(calls,1)
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_off_axis_navigation_recomputes_direction_from_current_view():
    node(BASE + SEARCH + r"""
const target={z:20,x:850002,y:450002,direction:'right'};
assert.equal(api.cacheMissDirection(view,target),'right');
view.tiles=[{z:20,x:850002,y:450000}];assert.equal(api.cacheMissDirection(view,target),'down');
view.tiles=[{z:20,x:850002,y:450003}];assert.equal(api.cacheMissDirection(view,target),'up');
view.tiles=[{z:20,x:850003,y:450002}];assert.equal(api.cacheMissDirection(view,target),'left');
""")


def test_45_modeled_cases_share_cache_and_keep_all_450_stage_requirements():
    program = WORKFLOW.replace("BEHAVIOR", json.dumps("normal")).split("(async()=>{\nconst result=await api.runCase")[0]
    program = program.replace("snapshot:()=>{const available=", """directionTo(tile){const current=this.tileView().tiles[0];
 return tile.x>current.x?'right':tile.x<current.x?'left':tile.y>current.y?'down':'up'},
  snapshot:()=>{const available=""")
    program += r"""
(async()=>{
 const results=[],cacheMissSearchState={knownHits:new Map()};
 for(let index=0;index<45;index++)results.push(await api.runCase(
  {id:'map',renderer:'svg',variant:'modeled-'+index,key:'map/svg/modeled-'+index},
  {projectId:project,open,cacheMissSearchState}));
 const summary=api.summarize(results);
 console.log(JSON.stringify({scope:'controlled one-tile renderer model, not Dashboard UI/native qualification',
  summary,opened,closed,cases:results.map(r=>({key:r.key,status:r.status,
   stages:r.stages.map(s=>({stage:s.stage,status:s.status,detail:s.detail,snapshot:s.snapshot})),
   search:r.cacheMissSearchEvidence}))}));
 assert.equal(summary.status,'passed');assert.equal(summary.required,450);assert.equal(summary.passed,450);
 assert.equal(opened,90);assert.equal(closed,90);
 const consumed=new Set();
 for(const result of results){
  const miss=result.stages.find(s=>s.stage==='cache-miss').snapshot,recovery=result.stages.find(s=>s.stage==='recovery').snapshot;
  assert.equal(miss.cacheHttpStatus,404);assert.equal(recovery.recoveryHttpStatus,200);
  assert.equal(miss.view,recovery.view);assert.equal(miss.genuineCacheMiss,recovery.recoveredTile);
  assert.ok(!consumed.has(miss.genuineCacheMiss));consumed.add(miss.genuineCacheMiss);
  assert.deepEqual(result.stages.map(s=>s.stage),api.STAGES);
 }
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run([shutil.which("node"), "-", str(MODULE)], input=program,
                            capture_output=True, text=True, cwd=ROOT, timeout=45)
    evidence = os.environ.get("SCOUT_CACHE_SEARCH_EVIDENCE")
    if evidence:
        destination = Path(evidence)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "45-modeled-cases.json").write_text(result.stdout)
        (destination / "45-modeled-cases.stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stderr
