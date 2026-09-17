"""Advanced replays are explicit, scoped, and excluded from normal Diag all."""
from pathlib import Path
import re
from test_dashboard_diagnostic_alignment import function, node

ROOT = Path(__file__).resolve().parents[1]


def test_advanced_cases_do_not_enter_regular_batch_and_are_scope_bound():
    page=(ROOT/'docs/admin/scout-dashboard-v0.1.html').read_text()
    regular=page.split('const DASHBOARD_DIAGNOSTIC_CASES =',1)[1].split('];',1)[0]
    assert len(re.findall(r'id: "DASH-\d+"',regular))==48
    assert 'runDiagnosticAdvanced' not in function('runAllDashboardDiagnostics')
    assert 'data-diagnostic-advanced-run' in function('bindDiagnosticControls')
    assert 'stored?.scopeKey === diagnosticCaseScopeKey' in function('renderDiagnosticAdvanced')
    node(function('runDiagnosticAdvanced')+r'''
const assert=require('node:assert/strict');
const DIAGNOSTIC_ADVANCED_CASES=[{id:'assistant'}];
let busy=false,scope='one',calls=0;
const diagnosticExecutionBusy=()=>busy;
const diagnosticCaseScopeKey=()=>scope;
const state={};const document={querySelector:()=>null};
const updateDiagnosticDom=()=>{},bindDiagnosticControls=()=>{};
const diagnosticRequire=(ok,message)=>{if(!ok)throw Error(message)};
const diagnosticSafeDetail=String;
const diagnosticAdvancedAssistantReplay=async()=>{calls++;return {status:'warning',detail:'cancel unsupported'};};
(async()=>{
 await runDiagnosticAdvanced('unknown');assert.equal(calls,0);
 busy=true;await runDiagnosticAdvanced('assistant');assert.equal(calls,0);
 busy=false;await runDiagnosticAdvanced('assistant');assert.equal(calls,1);
 assert.equal(state.diagnosticAdvancedResults.assistant.status,'warning');
 assert.equal(state.diagnosticAdvancedResults.assistant.scopeKey,'one');
 assert.equal(state.diagnosticAdvancedBusy,false);
})().catch(e=>{console.error(e);process.exitCode=1});
''')


def test_inline_advanced_module_matches_tested_source():
    page=(ROOT/'docs/admin/scout-dashboard-v0.1.html').read_text()
    inline=page.split('// diagnostic-advanced-inline:start\n',1)[1].split('// diagnostic-advanced-inline:end',1)[0]
    assert inline==(ROOT/'docs/admin/scout-diagnostic-advanced.js').read_text()
