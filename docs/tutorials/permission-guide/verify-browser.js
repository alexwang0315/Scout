const fs=require('fs'),assert=require('assert'),vm=require('vm'),{chromium}=require('playwright');
const dir=__dirname,out=process.argv[2],writePdf=!process.argv.includes('--no-pdf');
const slides=JSON.parse(fs.readFileSync(dir+'/slides.json','utf8')).slides;
function requiredSlideIndex(id) {
 const matches=slides.flatMap((slide,index)=>slide.id===id?[index]:[]);
 assert.equal(matches.length,1,'Expected exactly one teaching chapter: '+id);
 return matches[0];
}
const slideCount=slides.length,plannedPage=requiredSlideIndex('planned-input')+1,reviewIndex=requiredSlideIndex('planned-review');
assert(plannedPage>0&&reviewIndex>=0);
if(!out)throw Error('Supply a Scout output directory as the first argument');
fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({executablePath:process.env.SCOUT_BROWSER_EXECUTABLE||undefined,headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1920,height:1080},reducedMotion:'reduce'});const errors=[],requests=[],blockedRequests=[];
await page.route(/^https?:/,route=>{blockedRequests.push(route.request().url());return route.abort('blockedbyclient')});
page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(!r.url().startsWith('data:'))requests.push(r.url())});
try{
const source=fs.readFileSync(dir+'/index.html','utf8');new vm.Script(source.match(/<script>([\s\S]*?)<\/script>/)[1]);await page.goto('file://'+dir+'/index.html');await page.evaluate(()=>document.fonts.ready);await page.locator('.slide img').evaluateAll(imgs=>Promise.all(imgs.map(i=>i.decode())));assert.equal(await page.locator('.slide').count(),slideCount);
const results=[];
for(const [width,height] of [[1920,1080],[1440,900],[1280,720],[1024,768],[768,1024],[375,667],[414,896],[667,375],[896,414]]){
 await page.setViewportSize({width,height});await page.waitForTimeout(200);
 for(let i=0;i<slideCount;i++){await page.evaluate(i=>window.presentation.go(i,false),i);await page.waitForTimeout(45);
  const check=await page.evaluate(()=>{const s=document.querySelector('.slide[aria-current]'),box=s.getBoundingClientRect(),footer=document.querySelector('.nav').getBoundingClientRect().top,limit=footer-14;const bad=[];
  for(const el of s.querySelectorAll('.header,.step,.guide-card,.status-row,.takeaway,.example-box,.screen-figure')){const r=el.getBoundingClientRect();if(r.width<1||r.height<1)continue;if(r.left<-.5||r.right>innerWidth+.5||r.top<-1||r.bottom>limit+.5)bad.push({selector:el.className,text:el.innerText?.slice(0,90),x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom,limit});}
  for(const el of s.querySelectorAll('.step h3,.step p,.guide-card h3,.guide-card p,.status-row h3,.status-row p'))if(el.scrollWidth>el.clientWidth+1)bad.push({selector:el.className,text:el.innerText?.slice(0,60),horizontal_text_overflow:true});
  const image=s.querySelector('.shot-stage img'),overlay=s.querySelector('.shot-overlay'),markers=[...s.querySelectorAll('.shot-marker')],steps=[...s.querySelectorAll('.step')];
  if(!image||!overlay||!markers.length||markers.length!==steps.length)bad.push({marker_count:markers.length,steps:steps.length});
  if(image&&overlay){const a=image.getBoundingClientRect(),b=overlay.getBoundingClientRect();for(const key of ['x','y','width','height'])if(Math.abs(a[key]-b[key])>1)bad.push({overlay_misaligned:key,image:a[key],overlay:b[key]});for(const m of markers){const t=m.querySelector('.target-box').getBoundingClientRect(),c=m.querySelector('.marker-disc').getBoundingClientRect();if(t.x<a.x-1||t.y<a.y-1||t.right>a.right+1||t.bottom>a.bottom+1||c.x<a.x-1||c.y<a.y-1||c.right>a.right+1||c.bottom>a.bottom+1)bad.push({marker_outside_image:m.dataset.markerStep});}}
  const circles=markers.map(m=>({step:m.dataset.markerStep,rect:m.querySelector('.marker-disc').getBoundingClientRect()}));
  for(let i=0;i<circles.length;i++)for(let j=i+1;j<circles.length;j++){const a=circles[i].rect,b=circles[j].rect,dist=Math.hypot(a.x+a.width/2-b.x-b.width/2,a.y+a.height/2-b.y-b.height/2);if(dist<(a.width+b.width)/2)bad.push({marker_overlap:[circles[i].step,circles[j].step]});}
  return {slide:Number(s.id.replace('slide-','')),bad,bodyHorizontal:document.documentElement.scrollWidth>innerWidth+1,images:[...s.querySelectorAll('img')].every(im=>im.complete&&im.naturalWidth>0)};});
  results.push({width,height,...check});if(width===1920)await page.screenshot({path:out+'/slide-'+String(i+1).padStart(2,'0')+'.png'});
  if(width===375&&[1,6,7,8,9,10,13,17,20,23,26].includes(i))await page.screenshot({path:out+'/mobile-'+String(i+1).padStart(2,'0')+'.png'});
 }
 console.log('viewport '+width+'x'+height+' checked');
}
fs.writeFileSync(out+'/layout.json',JSON.stringify(results,null,2));const failed=results.filter(x=>x.bad.length||x.bodyHorizontal||!x.images);
console.log(JSON.stringify({layout_cases:results.length,failed:failed.length,examples:failed.slice(0,6)}));
await page.setViewportSize({width:1280,height:720});await page.waitForTimeout(200);await page.evaluate(()=>presentation.go(0,false));await page.keyboard.press('ArrowRight');await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>presentation.current),1);
await page.locator('#chapter').selectOption(String(plannedPage-1));await page.waitForTimeout(120);assert.equal(await page.evaluate(()=>presentation.current),plannedPage-1);
await page.locator('#chapter').selectOption(String(reviewIndex));assert.equal(await page.evaluate(()=>presentation.current),reviewIndex);
await page.locator('#slide-'+(reviewIndex+1)+' [data-zoom]').click();assert(await page.locator('#zoom-dialog').isVisible());
assert.equal(await page.locator('#zoom-dialog .shot-marker').count(),slides[reviewIndex].steps.length);
assert.equal(await page.locator('#zoom-dialog img').getAttribute('src'),await page.locator('#slide-'+(reviewIndex+1)+' img').getAttribute('src'));await page.keyboard.press('Escape');assert(!await page.locator('#zoom-dialog').isVisible());
await page.evaluate(()=>presentation.go(0,false));await page.locator('#play').click();await page.waitForTimeout(12300);assert.equal(await page.evaluate(()=>presentation.current),1);await page.locator('#play').click();assert(!await page.evaluate(()=>presentation.playing));
await page.keyboard.press('End');assert.equal(await page.evaluate(()=>presentation.current),slideCount-1);assert(await page.locator('#next').isDisabled());await page.keyboard.press('Home');assert.equal(await page.evaluate(()=>presentation.current),0);
await page.reload();assert.equal(await page.evaluate(()=>presentation.current),0);
const remote=requests.filter(x=>/^https?:/.test(x));assert.deepEqual(remote,[]);assert.deepEqual(blockedRequests,[]);assert.deepEqual(errors,[]);
if(writePdf){await page.setViewportSize({width:1600,height:900});await page.waitForTimeout(200);await page.evaluate(()=>presentation.go(0,false));await page.emulateMedia({media:'print'});await page.pdf({path:dir+'/permission-guide.pdf',printBackground:true,preferCSSPageSize:true});}
const summary={status:failed.length?'NEEDS_LAYOUT_FIX':'PASS',slide_count:slideCount,layout_cases:results.length,failures:failed,checks:['all pages have screenshot and one marker per step','SVG overlays aligned at every viewport','zoom preserves numbered overlays','all images decoded','inline JavaScript parse','offline without HTTP dependencies','keyboard arrows/Home/End','chapter select','long-distance chapter jump','screenshot dialog and Escape','actual first-slide autoplay at 12 seconds','pause','reload',...(writePdf?['PDF generated']:[])],scope:'offline guide layout and navigation only; not live Dashboard qualification',pdf_generated:writePdf,pageerrors:errors,blocked_http_requests:blockedRequests,pdf_bytes:writePdf?fs.statSync(dir+'/permission-guide.pdf').size:null};fs.writeFileSync(out+'/summary.json',JSON.stringify(summary,null,2));console.log(JSON.stringify({status:summary.status,pdf_bytes:summary.pdf_bytes}));if(failed.length)process.exitCode=1;
}catch(e){fs.writeFileSync(out+'/error.json',JSON.stringify({error:String(e),stack:e.stack,errors},null,2));console.log(e.stack);process.exitCode=1;}finally{await browser.close();}
})().catch(e=>{fs.writeFileSync(out+'/error.json',JSON.stringify({status:'FAIL',stage:'browser-launch-or-setup',error:String(e),stack:e.stack,scope:'offline guide only'},null,2));console.error(e.stack);process.exitCode=1;});
