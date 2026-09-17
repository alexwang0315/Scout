#!/usr/bin/env python3
"""Construction tests for screenshot scale and preserved DOM geometry, not UI qualification."""
from pathlib import Path
import ast,base64,copy,html,importlib.util,json,hashlib,unittest
ROOT=Path(__file__).resolve().parent
TREE=ast.parse((ROOT/'build.py').read_text())
FUNCTIONS=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='image_html']
spec=importlib.util.spec_from_file_location('guide_sync',ROOT/'verify_ui_sync.py')
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)
class CaptureScaleTests(unittest.TestCase):
 def setUp(self):
  self.slide=next(s for s in json.loads((ROOT/'slides.json').read_text())['slides'] if s['id']=='saved-select')
  self.shot=next(s for s in json.loads((ROOT/'capture-sources.json').read_text())['shots'] if s['page_id']=='saved-select')
 def render(self,shot=None,slide=None):
  ns={'ROOT':ROOT,'base64':base64,'esc':lambda s:html.escape(str(s),quote=True),'CAPTURES':{'saved-select':shot or self.shot}}
  exec(compile(ast.Module(body=FUNCTIONS,type_ignores=[]),'build.py','exec'),ns)
  return ns['image_html'](slide or self.slide)
 def scaled(self):
  p=ROOT/'assets/ui-saved-select-9099-20260913.png'
  shot=copy.deepcopy(self.shot);slide=copy.deepcopy(self.slide)
  shot.update(asset=p.name,width=2880,height=1368,viewport={'width':1440,'height':684},pixel_ratio=2,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
  slide['image']=p.name
  # Fixture rectangles exercise the new coordinate contract; this is not a current capture receipt.
  for m,t in zip(slide['markers'],shot['targets']):
   css=copy.deepcopy(t['box']);t['css_box']=css;t['box']={k:v*2 for k,v in css.items()}
   m['target']=copy.deepcopy(t['box']);m['x']*=2;m['y']*=2
  return shot,slide
 def check_capture(self,shot,slide):
  v=sync.Verifier(ROOT,ROOT.parents[2],True);v.capture(slide,shot,'test-capture');return v.errors
 def test_existing_scale_stays_unchanged(self):
  result=self.render()
  self.assertEqual(result.count('r="25"'),3);self.assertEqual(result.count('font-size:30px'),3)
 def test_dpr_two_numbers_match_css_size(self):
  shot,slide=self.scaled();result=self.render(shot,slide)
  self.assertEqual(result.count('r="50"'),3);self.assertEqual(result.count('font-size:60px'),3)
  self.assertIn('--capture-scale:2',result)
 def test_valid_dpr_two_capture_preserves_css_rectangles(self):
  shot,slide=self.scaled();self.assertEqual(self.check_capture(shot,slide),[])
 def test_wrong_dpr_is_rejected(self):
  shot,slide=self.scaled();shot['pixel_ratio']=1
  self.assertTrue(any('image dimensions must equal' in x for x in self.check_capture(shot,slide)))
 def test_guessed_target_rectangles_are_rejected(self):
  shot,slide=self.scaled();shot['targets'][0]['box']['x']+=20;slide['markers'][0]['target']['x']+=20
  self.assertTrue(any('original CSS coordinates' in x for x in self.check_capture(shot,slide)))
 def test_missing_original_css_box_is_rejected(self):
  shot,slide=self.scaled();del shot['targets'][0]['css_box']
  self.assertTrue(any('original DOM CSS rectangle' in x for x in self.check_capture(shot,slide)))
 def test_invalid_scaled_viewport_fails_without_exception(self):
  shot,slide=self.scaled();shot['viewport']=[]
  self.assertTrue(any('original CSS viewport' in x for x in self.check_capture(shot,slide)))
 def test_missing_image_dimension_fails_without_exception(self):
  shot,slide=self.scaled();del shot['width']
  self.assertTrue(any('positive integers' in x for x in self.check_capture(shot,slide)))
 def test_invalid_css_box_fails_without_exception(self):
  shot,slide=self.scaled();shot['targets'][0]['css_box']=['invalid']
  self.assertTrue(any('original DOM CSS rectangle' in x for x in self.check_capture(shot,slide)))
if __name__=='__main__': unittest.main(verbosity=2)
