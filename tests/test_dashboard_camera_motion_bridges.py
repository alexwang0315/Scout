"""Read-only motion bridges report the actual current renderer or unknown."""
import re

import pytest

from test_dashboard_rudy_live_diagnostic import BASE, ROOT, node


@pytest.mark.parametrize("page,helper,state_name", [
    ("phase4-pretrip-planning.html", "pretripCameraMotion", "state"),
    ("phase-3-5-runtime-debug.html", "debugCameraMotion", "debugPageState"),
])
def test_motion_bridge_tracks_live_renderer_and_does_not_certify_missing_map(page, helper, state_name):
    source = (ROOT / "docs/admin" / page).read_text()
    function = re.search(rf"(?ms)^    function {helper}\(.*?^    }}", source).group()
    assert f"getCameraMotion: {helper}," in source
    node(BASE + f"\nconst {state_name}={{mapLibreRenderer:null}};\n" + function + r"""
const missing=HELPER();assert.equal(missing.available,false);assert.equal(missing.moving,null);assert.equal(missing.easing,null);
let moving=true,easing=true,reads=0;
STATE.mapLibreRenderer={map:{isMoving(){reads++;return moving},isEasing(){reads++;return easing}}};
const active=HELPER();assert.equal(active.available,true);assert.equal(active.moving,true);assert.equal(active.easing,true);
assert.equal(active.basis,'maplibre-public-api');assert.ok(Number.isFinite(active.observedAt));
moving=false;easing=false;
assert.equal(HELPER().moving,false);assert.equal(HELPER().easing,false);assert.equal(reads,6);
for (const [m,e] of [[true,true],[true,false],[false,true],[false,false]]) {
 moving=m;easing=e;const value=HELPER();assert.equal(value.available,true);assert.equal(value.moving,m);assert.equal(value.easing,e);
}
STATE.mapLibreRenderer={map:{isMoving:()=>false}};
const publicMap=HELPER();assert.equal(publicMap.available,true);assert.equal(publicMap.moving,false);assert.equal(publicMap.easing,null);
STATE.mapLibreRenderer={map:{isEasing:()=>false}};
const incomplete=HELPER();assert.equal(incomplete.available,false);assert.equal(incomplete.moving,null);assert.equal(incomplete.easing,null);
STATE.mapLibreRenderer={map:{isMoving:()=>undefined,isEasing:()=>false}};assert.equal(HELPER().available,false);
STATE.mapLibreRenderer={map:{isMoving(){throw new TypeError('map removed')},isEasing:()=>false}};
const failed=HELPER();assert.equal(failed.available,false);assert.equal(failed.moving,null);assert.equal(failed.errorName,'TypeError');
STATE.mapLibreRenderer=null;assert.equal(HELPER().available,false,'Do not retain a disposed renderer');
""".replace("HELPER", helper).replace("STATE", state_name))
