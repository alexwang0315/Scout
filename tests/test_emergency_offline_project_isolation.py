"""Project-scoped offline overlays, late reads, and save-time identity."""
from test_dashboard_diagnostic_alignment import function, node


def test_project_filter_and_late_success_or_error_cannot_replace_current_overlay():
    node(function('refreshEmergencyOfflineIntentCount') + r'''
const assert=require('node:assert/strict');
let selected='A';const resolvedPretripProjectId=()=>selected,asArray=x=>Array.isArray(x)?x:[];
const state={emergencyOfflineFieldOverlay:{}};
let waiting=[];const listEmergencyOfflineRecords=()=>new Promise((resolve,reject)=>waiting.push({resolve,reject}));
const record=(project,id)=>({project_id:project,intent_id:id,intent_type:'field_conflict',group_id:'same',row_id:'row'});
(async()=>{
 const first=refreshEmergencyOfflineIntentCount();waiting.shift().resolve([record('A','a'),record('B','b'),record(undefined,'legacy')]);await first;
 assert.equal(state.emergencyOfflineIntentCount,1);assert.equal(state.emergencyOfflineFieldOverlay.same.conflict_rows.row.intent_id,'a');
 const late=refreshEmergencyOfflineIntentCount(),old=waiting.shift();
 selected='B';const current=refreshEmergencyOfflineIntentCount(),fresh=waiting.shift();
 assert.equal(state.emergencyOfflineIntentCount,0);assert.deepEqual(state.emergencyOfflineFieldOverlay,{});
 fresh.resolve([record('A','a'),record('B','b')]);await current;
 old.resolve([record('A','late')]);await late;
 assert.equal(state.emergencyOfflineFieldOverlay.same.conflict_rows.row.intent_id,'b');
 const oldError=refreshEmergencyOfflineIntentCount(),failed=waiting.shift();
 selected='A';const next=refreshEmergencyOfflineIntentCount();waiting.shift().resolve([record('A','new')]);await next;
 failed.reject(Error('old read failed'));await oldError;
 assert.equal(state.emergencyOfflineFieldOverlay.same.conflict_rows.row.intent_id,'new');
 // Same-project refresh ordering must also reject a superseded read.
 const slower=refreshEmergencyOfflineIntentCount(),slow=waiting.shift();
 const faster=refreshEmergencyOfflineIntentCount();waiting.shift().resolve([record('A','latest')]);await faster;
 slow.resolve([record('A','superseded')]);await slower;
 assert.equal(state.emergencyOfflineFieldOverlay.same.conflict_rows.row.intent_id,'latest');
})().catch(e=>{console.error(e);process.exitCode=1});
''')


def test_save_is_bound_before_async_key_lookup_and_metadata_cannot_override_project():
    node(function('storeEncryptedEmergencyIntent') + r'''
const assert=require('node:assert/strict');
let selected='A',release;const resolvedPretripProjectId=()=>selected;
const stored=[];const database={transaction:()=>({objectStore:()=>({add:value=>stored.push(value)})}),close:()=>{}};
const openEmergencyOfflineDb=()=>new Promise(resolve=>{release=()=>resolve(database)});
const emergencyOfflineEncryptionKey=async()=>({});
const window={crypto:{getRandomValues:x=>x,subtle:{encrypt:async()=>new ArrayBuffer(8)}}};
const emergencyOfflineTransaction=async()=>{},refreshEmergencyOfflineIntentCount=async()=>{};
(async()=>{
 const pending=storeEncryptedEmergencyIntent({intent_id:'one',mission_day_instance_id:'day'},{project_id:'malformed_metadata'});
 selected='B';release();await pending;
 assert.equal(stored.length,1);assert.equal(stored[0].project_id,'A');
})().catch(e=>{console.error(e);process.exitCode=1});
''')


def test_late_field_saves_do_not_paint_into_another_project():
    node(function('saveEmergencyOfflineFieldCompletion')+'\n'+function('saveEmergencyOfflineFieldConflict') + r'''
const assert=require('node:assert/strict');
let selected='A',release;
const resolvedPretripProjectId=()=>selected,asArray=x=>Array.isArray(x)?x:[];
const state={emergencyOfflineFieldOverlay:{}};
const emergencyCommandContext=groupId=>({group_id:groupId});
const storeEncryptedEmergencyIntent=()=>new Promise(resolve=>{release=resolve});
const group={group_id:'same',mission_day_instance_id:'day',day_end:{state:'planned',planned_target_ref:'target',planned_target_sha256:'hash',planned_target_label:'Camp'},departure_checklist:{checklist_id:'check',rows:[{row_id:'row',evidence_ref:'ref',evidence_sha256:'sha'}]}};
const pending={rowId:'row',idempotencyKey:'id'};
(async()=>{
 for(const run of [()=>saveEmergencyOfflineFieldCompletion(group,pending),()=>saveEmergencyOfflineFieldConflict(group,pending,'field_condition_differs')]){
  selected='A';state.emergencyOfflineFieldOverlay={};
  const save=run();selected='B';state.emergencyOfflineFieldOverlay={B:{marker:true}};release();await save;
  assert.deepEqual(state.emergencyOfflineFieldOverlay,{B:{marker:true}});
  selected='A';state.emergencyOfflineFieldOverlay={};const current=run();release();await current;
  assert(state.emergencyOfflineFieldOverlay.same);
 }
})().catch(e=>{console.error(e);process.exitCode=1});
''')
