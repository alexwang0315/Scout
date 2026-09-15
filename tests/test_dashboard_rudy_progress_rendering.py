"""D037's report observer must not block the timed work it observes."""
import re

from test_dashboard_rudy_live_diagnostic import BASE, PAGE, function, node


def test_live_receipts_are_not_traversed_or_serialized_and_final_evidence_is_lossless():
    # The fallback lets this regression run against the previous publisher: it
    # must fail on the deep copy, rather than merely on a missing new helper.
    helper = (function("diagnosticUpdateRudyProgress")
              if re.search(r"function diagnosticUpdateRudyProgress\(", PAGE.read_text()) else "")
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<main id="mount"></main>',{url:base});
const document=dom.window.document,projectId=()=>project,asArray=value=>Array.isArray(value)?value:[];
const escapeHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
let stored={},fullUpdates=0,receiptReads=0;
const diagnosticResult=()=>stored,diagnosticSetResult=(id,patch)=>{assert.equal(id,'DASH-037');stored={...stored,...patch}};
const updateDiagnosticDom=()=>{fullUpdates++;document.querySelector('#mount').innerHTML=renderDiagnosticRudyResults(stored.rudyNativeReport)};
""" + function("renderDiagnosticRudyResults") + helper + function("diagnosticPublishRudyReport") + r"""
// A getter is a deterministic witness of traversing a large request archive.
// Its size matches the order of the actual 9.53 MB failed run, without storing
// private request coordinates or a large fixture in the repository.
const archive={};Object.defineProperty(archive,'receipts',{enumerable:true,configurable:true,get(){receiptReads++;return 'x'.repeat(9530000)}});
const row={key:'map/svg/default',status:'running',activeStage:'initial',stages:[],requestEvidence:archive,
 liveSnapshot:{matrix:20,success:0,required:20,pending:20,errors:0,status:'loading'}};
const report={projectId:project,status:'running',phase:'native-matrix',plannedStages:450,plannedCases:45,
 stageNames:api.STAGES,cases:[],activeResult:row};
diagnosticPublishRudyReport(report,'begin',{live:true});
assert.equal(receiptReads,0,'The progress observer must not copy request archives');
assert.ok(document.querySelector('[data-diagnostic-rudy-json-pending]'));
assert.equal(document.querySelector('[data-diagnostic-rudy-json]'),null);
diagnosticPublishRudyReport(report,'first receipt',{live:true});
const stableRoot=document.querySelector('[data-diagnostic-rudy-report]');
const details=document.querySelector('[data-diagnostic-rudy-cases-details]');details.open=true;
for(let i=1;i<=20;i++){
 row.liveSnapshot.success=i;row.liveSnapshot.pending=20-i;
 diagnosticPublishRudyReport(report,'headers/provenance/blob '+i,{live:true});
 assert.equal(document.querySelector('[data-diagnostic-rudy-report]'),stableRoot,'Per-request updates must not replace the report DOM');
}
assert.equal(fullUpdates,1);assert.equal(receiptReads,0);assert.equal(details.open,true);
assert.match(document.querySelector('[data-diagnostic-rudy-live-state]').textContent,/20\/20.*0 載入中/);
const failure={stage:'initial',status:'warning',detail:'HTTP 503 retained',requestEvidence:archive};
row.stages.push(failure);row.status='warning';row.cleanupStatus='passed';
diagnosticPublishRudyReport(report,'failed initial',{live:true});
assert.equal(receiptReads,0,'Stage summaries must not serialize the raw receipts either');
assert.match(document.querySelector('[data-diagnostic-rudy-first-failure]').textContent,/HTTP 503 retained/);
assert.equal(document.querySelector('[data-diagnostic-rudy-cases-details]').open,true);
diagnosticPublishRudyReport({...report,projectId:'other_trip'},'wrong scope',{live:true});
assert.equal(stored.detail,'failed initial');
diagnosticPublishRudyReport({...report,status:'warning',phase:'complete'},'finished');
const rendered=JSON.parse(document.querySelector('[data-diagnostic-rudy-json]').textContent);
assert.equal(rendered.activeResult.requestEvidence.receipts.length,9530000);
assert.equal(rendered.activeResult.stages[0].requestEvidence.receipts.length,9530000);
assert.equal(rendered.activeResult.stages[0].detail,'HTTP 503 retained');
row.stages[0].detail='late mutation';
assert.equal(stored.rudyNativeReport.activeResult.stages[0].detail,'HTTP 503 retained','Sealed evidence must be independent of the producer');
dom.window.close();
""")


def test_terminal_runner_failure_exposes_full_evidence_even_if_report_was_running():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<main></main>',{url:base}),document=dom.window.document;
const projectId=()=>project,asArray=value=>Array.isArray(value)?value:[],escapeHtml=value=>String(value);
""" + function("renderDiagnosticRudyResults") + r"""
const report={projectId:project,status:'running',cases:[],activeResult:null,retained:{cause:'unexpected exception'}};
document.querySelector('main').innerHTML=renderDiagnosticRudyResults(report,{status:'failed',detail:'runner stopped'});
const evidence=JSON.parse(document.querySelector('[data-diagnostic-rudy-json]').textContent);
assert.equal(evidence.retained.cause,'unexpected exception');assert.equal(evidence.diagnosticResult.status,'failed');
dom.window.close();
""")
