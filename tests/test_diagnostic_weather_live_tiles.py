"""Cache-only weather DOM and request consistency must fail closed."""
from test_dashboard_diagnostic_alignment import function, node


def test_weather_tile_validation_rejects_mixed_project_matrix_or_remote_refresh():
    node(function('diagnosticWeatherValidateTileUrls') + r'''
const assert=require('node:assert/strict');
const diagnosticRequire=(ok,message)=>{if(!ok)throw Error(message)};
const base='http://localhost/admin/pretrip?projectId=one';
const good={matrix:14,tiles:[{key:'14/1/2',href:'/admin/tiles/imagery/one/imagery/14/1/2.png?cache_only=1'}]};
assert.equal(diagnosticWeatherValidateTileUrls(good,base,'one').length,1);
for(const href of [
 '/admin/tiles/imagery/two/imagery/14/1/2.png?cache_only=1',
 '/admin/tiles/imagery/one/imagery/15/1/2.png?cache_only=1',
 '/admin/tiles/imagery/one/imagery/14/1/2.png?native=1',
 '/admin/tiles/imagery/one/imagery/14/1/2.png?cache_only=1&refresh=1',
 'https://external.invalid/admin/tiles/imagery/one/imagery/14/1/2.png?cache_only=1']) {
 assert.throws(()=>diagnosticWeatherValidateTileUrls({matrix:14,tiles:[{key:'14/1/2',href}]},base,'one'));
}
assert.throws(()=>diagnosticWeatherValidateTileUrls({...good,matrix:15},base,'one'));
''')


def test_pending_generation_is_excluded_from_active_tile_evidence():
    node(function('diagnosticWeatherTileSnapshot') + r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const doc=new JSDOM(`<svg><g data-layer-group="rudy-twmap" data-tile-generation-state="loading" data-active-tile-generation-key="old"><image data-raster-tile="14/1/2" href="old.png"/><g data-tile-generation="pending"><image data-raster-tile="15/2/4" href="new.png"/></g></g></svg>`).window.document;
const state=diagnosticWeatherTileSnapshot(doc);
assert.equal(state.tiles.length,1);assert.equal(state.matrix,14);assert.equal(state.generation,'old');assert.equal(state.status,'loading');
''')
