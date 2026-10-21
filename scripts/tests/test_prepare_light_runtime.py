import base64, importlib.util, pathlib, subprocess, tempfile, unittest
HERE=pathlib.Path(__file__).resolve().parent
impl=HERE.parent/'prepare-light-runtime.py'
spec=importlib.util.spec_from_file_location('light_runtime',impl)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
def fixture():
 return '<html><head><style>.w0{width:400px;}.h0{height:600px;}.h1{height:601px;}.w1{width:500px;}.h2{height:700px;}</style></head><body><div id="page-container"><div id="pf1" class="pf w0 h0" data-page-no="1"><div class="pc w0 h1"><div class="t ff0">Hello <span class="_"> </span>world</div></div><div class="pi" data-data=\'{"ctm":[1,0,0,1,0,0]}\'></div></div><div id="pf2" class="pf w1 h2" data-page-no="2"><div class="pc w1 h2"><div class="t">Mixed sizes</div></div><div class="pi" data-data=\'{"ctm":[0,1,-1,0,700,0]}\'></div></div></div></body></html>'
class RuntimeTests(unittest.TestCase):
 def test_declared_dimensions_and_text_paint_unchanged(self):
  source=fixture();text,fonts,count=module.prepare(source,'/test/fonts/')
  self.assertEqual(count,2);self.assertEqual(fonts,{})
  self.assertIn('data-pdf2html-page-size="400,600,601"',text)
  self.assertIn('data-pdf2html-page-size="500,700,700"',text)
  self.assertIn('<div class="t ff0">Hello <span class="_"> </span>world</div>',text)
  self.assertIn('data-pdf2html-declared-page-geometry="v1"',text)
 def test_invalid_page_falls_back_without_partial_metadata(self):
  for source in [fixture().replace('.w1{width:500px;}',''),fixture().replace('[1,0,0,1,0,0]','[0,0,0,0,0,0]'),fixture().replace('class="pc w0 h1"','class="pc w0 h1" style="height:999px"'),fixture().replace('data-page-no="2"','data-page-no="1"')]:
   text,fonts,count=module.prepare(source,'/test/fonts/')
   self.assertEqual(count,0);self.assertEqual(text,source)
 def test_font_bytes_deduplicated_other_data_uris_untouched(self):
  data=b'wOFF'+b'same binary font bytes'
  uri='data:application/font-woff;base64,'+base64.b64encode(data).decode()
  source=fixture().replace('</style>',f'@font-face{{font-family:f0;src:url("{uri}") format("woff");}}@font-face{{font-family:f1;src:url("{uri}") format("woff");}}</style>',1)+'<img src="data:image/png;base64,YQ==">'
  text,fonts,count=module.prepare(source,'/test/fonts/')
  self.assertEqual(list(fonts.values()),[data]);name=next(iter(fonts))
  self.assertEqual(text.count('/test/fonts/'+name),2)
  self.assertIn('font-family:f0;',text);self.assertIn('format("woff")',text)
  self.assertIn('data:image/png;base64,YQ==',text)
 def test_unknown_or_external_fonts_preserved(self):
  source=fixture().replace('</style>','@font-face{font-family:f;src:url("existing.woff")}@font-face{font-family:g;src:url("data:font/woff;base64,YQ==")}</style>',1)
  text,fonts,_=module.prepare(source,'/fonts/')
  self.assertEqual(fonts,{});self.assertIn('existing.woff',text);self.assertIn('data:font/woff;base64,YQ==',text)
 def test_idempotent(self):
  a,_,_=module.prepare(fixture(),'/fonts/')
  b,_,_=module.prepare(a,'/fonts/')
  self.assertEqual(a,b)
 def test_cli_refuses_canonical_input(self):
  with tempfile.TemporaryDirectory()as root:
   p=pathlib.Path(root)/'book.html';p.write_text(fixture())
   result=subprocess.run(['/usr/bin/python3','-I','-B',str(impl),str(p),'--font-dir',str(pathlib.Path(root)/'fonts'),'--font-url-prefix','/fonts/'],capture_output=True,text=True)
   self.assertNotEqual(result.returncode,0);self.assertEqual(p.read_text(),fixture())
if __name__=='__main__':unittest.main()
