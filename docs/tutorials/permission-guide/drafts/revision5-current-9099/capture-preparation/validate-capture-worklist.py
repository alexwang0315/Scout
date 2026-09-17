#!/usr/bin/env python3
"""Validate capture planning metadata, never generate capture attestations."""
import argparse,copy,hashlib,json
from pathlib import Path
from urllib.parse import urlparse,parse_qs
ROOT=Path(__file__).resolve().parent
GUIDE=ROOT.parents[2]
QUEUE=json.loads((GUIDE/'drafts/revision5-current-9099/capture-queue.json').read_text())
DRAFT=json.loads((GUIDE/'drafts/revision5-current-9099/slides.draft.json').read_text())
WORKSPACE='dongqing_batongguan_historic_trail_newImport'
ORIGIN='http://127.0.0.1:9099'
def validate(w,draft=None):
 if draft is None:draft=DRAFT
 errors=[]
 def need(ok,message):
  if not ok:errors.append(message)
 pages=w.get('pages',[])
 need(len(pages)==38,'Expected all 38 pages')
 need([p.get('page') for p in pages]==list(range(1,39)),'Pages must remain ordered 1..38')
 need(sum(len(p.get('targets',[])) for p in pages)==113,'Expected all 113 targets')
 need(w.get('current_capture_count')==0,'Planning cannot attest current captures')
 need(w.get('status')=='BLOCKED_AWAITING_UI_FREEZE_AND_ACTUAL_9099_CHROME_CAPTURES','Current captures still require the final UI freeze and actual Chrome')
 readiness=w.get('integration_readiness',{})
 need(readiness.get('status')=='BLOCKED' and readiness.get('ui_source_frozen') is False,'Planning cannot claim that the UI is frozen')
 need(readiness.get('final_ui_source_hashes') is None,'Final current UI source hashes must remain unassigned')
 need(readiness.get('capture_receipts')==[] and readiness.get('actual_current_capture_count')==0,'Planning cannot forge capture receipts')

 need(w.get('source_evidence',{}).get('inventory_from_queue_unchanged')==QUEUE['source_inventory'],'Capture source inventory must not be rewritten')
 need(w.get('authorized_text',{}).get('user_four_day_text')==QUEUE['user_four_day_text'],'Authorized four-day text must remain exact')
 for p,q in zip(pages,QUEUE['pages']):
  need(p.get('id')==q['id'],'Page identity drift: '+str(p.get('page')))
  need(p.get('frame_selector')==q.get('frame_selector'),'Frame drift: '+str(p.get('page')))
  need(len(p.get('targets',[]))==len(q['targets']),'Target count drift: '+str(p.get('page')))
  for target,original in zip(p.get('targets',[]),q['targets']):
   for k,v in original.items():
    need(target.get(k)==v,'Original target changed: page '+str(p.get('page'))+' step '+str(original['step'])+' '+k)
   need(bool(target.get('source_anchors')),'No source planning anchor')
   action=target.get('user_action',{})
   if action.get('kind') in ['human_review_then_check','review_bound_commit_or_subject_selection','execute_when_real_prerequisites_satisfied']:
    need(action.get('execute_during_capture_preparation') is False,'Capture must not fabricate a review/save/adoption')
  need(p.get('capture_status')=='PENDING_CURRENT_UI_CAPTURE','Page has invented capture status')
  need(bool(p.get('prepare_actions')),'Page lacks preparation operations')
 for p in pages+w.get('supplements',[]):
  e=p['entry'];url=urlparse(e['url'])
  need(url.scheme+'://'+url.netloc==ORIGIN,'Wrong dashboard service origin')
  need(url.path=='/admin/dashboard','Wrong dashboard service path')
  need(parse_qs(url.query).get('projectId')==[WORKSPACE],'Wrong requested workspace')
  need(e.get('workspace')==WORKSPACE,'Wrong workspace metadata')
  need(url.fragment==e['route'],'Route/entry mismatch')
  need([t['step'] for t in p['targets']]==list(range(1,len(p['targets'])+1)),'Step sequence changed')
  for action in p.get('prepare_actions',[]):
   need(action.get('op') not in ['check_human_review','create_fake_recorded','forge_capture','fill_review_signature'],'Disallowed capture action')
 groups=w.get('capture_groups',[])
 member_ids=[i for g in groups for i in g['pages']]
 need(sorted(member_ids)==list(range(1,39)),'Groups must cover every page exactly once')
 for g in groups:
  need(g.get('same_image_confirmed') is False,'Same-image reuse is not yet verified')
  members=[p for p in pages if p['page'] in g['pages']]
  need(len(set((p['entry']['url'],p['entry']['frame_selector']) for p in members))<=1,'Cross-entry image reuse')
  for p in members:need(p['capture_group']==g['id'],'Page/group mismatch')
  if any(i in [35,36,37,38] for i in g['pages']):need(len(g['pages'])==1,'Map or ready/error screenshots cannot be combined')
 supplements=w.get('supplements',[])
 need(len(supplements)==1 and len(supplements[0]['targets'])==4,'Expected Completed GPX four-step supplement')
 if supplements:
  need(supplements[0]['entry']['route']=='timeline','Completed GPX must open Timeline Evidence')
  need(supplements[0].get('buildable') is False,'Supplement has no screenshots yet')
 for name,value in w.get('bindings',{}).items():
  if name!='binding_rule':need(value is None,'Planning must not invent real binding '+name)
 need(all(s['image'] is None and not s['markers'] for s in draft['slides']),'Draft must remain pending real images/markers')
 need(all(s.get('capture_status') in [None,'PENDING_CURRENT_UI_CAPTURE'] for s in draft['slides']),
  'Draft cannot mark missing current images as captured')
 need(draft['buildable'] is False,'Draft cannot be buildable without captures')
 return errors
def main():
 parser=argparse.ArgumentParser();parser.add_argument('worklist',nargs='?',default=str(ROOT/'capture-worklist.json'));parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
 w=json.loads(Path(args.worklist).read_text());errors=validate(w)
 result={'status':'PASS' if not errors else 'FAIL','scope':'capture-worklist metadata only; not live UI or workflow acceptance','errors':errors,'pages':len(w['pages']),'targets':sum(len(p['targets']) for p in w['pages']),'candidate_groups':len(w['capture_groups']),'captured_images':0}
 if args.self_test:
  rows=[]
  changes=[
   ('missing target',lambda d:d['pages'][0]['targets'].pop()),
   ('wrong workspace',lambda d:d['pages'][0]['entry'].update(url=d['pages'][0]['entry']['url'].replace(WORKSPACE,'other'))),
   ('map/weather shared group',lambda d:d['capture_groups'][-4]['pages'].append(37)),
   ('review auto-check',lambda d:d['pages'][5]['targets'][0]['user_action'].update(execute_during_capture_preparation=True)),
   ('invented captures',lambda d:d.update(current_capture_count=38)),
   ('invented recorded ID',lambda d:d['bindings'].update(recorded_version_id='fake')),
   ('changed source SHA',lambda d:d['source_evidence']['inventory_from_queue_unchanged']['docs/admin/scout-maplibre-evidence.js'].update(sha256='0'*64)),
   ('claimed UI freeze',lambda d:d['integration_readiness'].update(ui_source_frozen=True)),
   ('invented final source SHA',lambda d:d['integration_readiness'].update(final_ui_source_hashes={'docs/admin/scout-dashboard-v0.1.html':'0'*64})),
   ('forged capture receipt',lambda d:d['integration_readiness'].update(capture_receipts=[{'image':'fake.png'}])),

  ]
  for label,change in changes:
   d=copy.deepcopy(w);change(d);caught=validate(d);rows.append({'case':label,'status':'PASS' if caught else 'FAIL','caught':caught})
  draft=copy.deepcopy(DRAFT);draft['slides'][34]['capture_status']='captured';caught=validate(w,draft)
  rows.append({'case':'draft falsely marked captured','status':'PASS' if caught else 'FAIL','caught':caught})
  result['negative_mutations']=rows
  if any(x['status']=='FAIL' for x in rows):result['status']='FAIL'
 print(json.dumps(result,ensure_ascii=False,indent=2))
 return int(result['status']!='PASS')
if __name__=='__main__':raise SystemExit(main())
