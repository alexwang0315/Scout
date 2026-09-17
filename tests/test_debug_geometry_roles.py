"""Mixed Debug groups must retain background violations after evidence classification."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_debug_mixed_geometry_roles_do_not_exempt_raster_or_extent():
    probe = r'''
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<body></body>');global.window=dom.window;global.document=dom.window.document;
require('./docs/admin/scout-maplibre-evidence.js');
function inspect(id, content, hidden=false){
 document.body.innerHTML=`<svg><g data-layer-group="route"><path class="route-line" d="M0 0 L10 10"/></g><g data-layer-group="${id}" ${hidden?'data-layer-hidden="true"':''}>${content}</g></svg>`;
 return window.ScoutMapLibreEvidence.inspectSvgLayerOrder(document.querySelector('svg'));
}
const cases=[];
for(const [id,kind] of [['risk-heatmap','calibrated'],['risk-delta','delta']]){
 const path=`<path class="${id}" data-risk-layer="${kind}" d="M0 0 L10 10"/>`;
 assert.equal(inspect(id,path).violations.length,0);
 assert(inspect(id,path.replace(`data-risk-layer="${kind}"`, '')).violations.some(v=>v.code==='background_over_route'));
 assert(inspect(id,path+'<image href="tile.png" width="10" height="10"/>').violations.some(v=>v.code==='background_over_route'));
 cases.push({id,evidencePathAllowed:true,untypedPathRejected:true,rasterStillRejected:true});
}
for(const id of ['soil-moisture','antecedent-rain','cwa-qpf','cwa-weather']){
 const point=`<circle class="${id}-point" r="5"/>`;
 assert.equal(inspect(id,point).violations.length,0);
 for(const hidden of [false,true]){
  const result=inspect(id,point+`<rect class="environment-extent ${id}" width="10" height="10"/>`,hidden);
  assert(result.violations.some(v=>v.code==='background_over_route'));
 }
 assert(inspect(id,point+'<image href="tile.png" width="10" height="10"/>').violations.some(v=>v.code==='background_over_route'));
 cases.push({id,pointAllowed:true,visibleExtentRejected:true,hiddenExtentRejected:true,rasterRejected:true});
}
console.log(JSON.stringify({evidenceKind:'synthetic_geometry_contract_replay',cases},null,2));
'''
    result = subprocess.run(['node', '-e', probe], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    print(result.stdout)
