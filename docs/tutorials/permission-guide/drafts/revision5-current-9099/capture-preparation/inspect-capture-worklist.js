/* Read-only operation planner for root's connected Chrome. No clicks, scroll,
   fetches, input writes, screenshots, source-hash updates or approval actions.
   Call inspectGuideCaptureWorklist(worklist, {pages:[1,2,3], bindings:{...}}).
   A DOM-ready result still needs original screenshot + visual verification. */
function inspectGuideCaptureWorklist(worklist, options = {}) {
  const requested = options.pages || [];
  const all = [...worklist.pages, ...(worklist.supplements || [])];
  const pages = requested.map(id => all.find(p => p.page === id || p.id === id));
  const issue = (status, extra = {}) => ({status, captured_at:null, image_sha256:null, ...extra});
  if (!pages.length || pages.some(p => !p)) return issue("UNKNOWN_PAGE");
  const group = pages.length > 1 && worklist.capture_groups.find(g => pages.every(p => g.pages.includes(p.page)));
  if (pages.length > 1 && !group) return issue("SEPARATE_CAPTURES_REQUIRED", {
    reason:"這些頁面不在同一候選畫面組；不同頁面/ready/error/frame不能直接共用圖片。"
  });
  const sameEntry = pages.every(p => p.entry.url === pages[0].entry.url && p.entry.frame_selector === pages[0].entry.frame_selector);
  if (!sameEntry) return issue("SEPARATE_CAPTURES_REQUIRED");
  const expected = pages[0].entry;
  const url = new URL(location.href);
  if (url.origin !== worklist.origin || url.pathname !== new URL(expected.url).pathname || url.searchParams.get("projectId") !== worklist.workspace || url.hash !== "#" + expected.route) {
    return issue("NAVIGATION_REQUIRED", {url:expected.url, observed_url:location.href});
  }
  const frame = expected.frame_selector ? document.querySelector(expected.frame_selector) : null;
  if (expected.frame_selector && !frame) return issue("FRAME_MISSING");
  let doc,win;
  try {doc=frame?frame.contentDocument:document;win=doc?.defaultView;}
  catch (_) {return issue("FRAME_NOT_READABLE");}
  if (!doc || !win) return issue("FRAME_NOT_READY");
  let frameUrl;
  try {frameUrl=new URL(win.location.href);}
  catch (_) {return issue("FRAME_NOT_READABLE");}
  if (frame && (frameUrl.origin !== worklist.origin ||
      (frameUrl.searchParams.has("projectId") && frameUrl.searchParams.get("projectId") !== worklist.workspace))) {
    return issue("FRAME_WORKSPACE_OR_ORIGIN_MISMATCH", {frame_url:frameUrl.href,project_expected:worklist.workspace});
  }
  const frameRect=frame?frame.getBoundingClientRect():{x:0,y:0};
  const frameOffset={x:frameRect.x+(frame?.clientLeft||0),y:frameRect.y+(frame?.clientTop||0)};
  const normalize=s=>String(s||"").replace(/\s+/g," ").trim();
  const cssString=s=>String(s).replace(/\\/g,"\\\\").replace(/"/g,'\\"').replace(/[\r\n\f]/g,"\\a ");
  const bindings=options.bindings || {};
  const collectorPages=[], pending=[], targetRows=[], openSummaries=[];
  for(const page of pages) {
    const copy={...page,frame_selector:expected.frame_selector,targets:[]};
    for(const target of page.targets) {
      let selector=target.locator_template || target.locator;
      const missing=[];
      selector=selector.replace(/\{\{([A-Za-z0-9_]+)\}\}/g,(_,name)=>{
        if(bindings[name]==null || String(bindings[name])==="") {missing.push(name);return "";}
        return cssString(bindings[name]);
      });
      const key={page:page.page,id:page.id,step:target.step,locator:selector};
      if(missing.length) {pending.push({...key,status:"REAL_BINDING_REQUIRED",bindings:missing});continue;}
      let matches;
      try {matches=[...doc.querySelectorAll(selector)].filter(el=>
        (!target.text_exact || normalize(el.textContent)===normalize(target.text_exact)) &&
        (!target.text_prefix || normalize(el.textContent).startsWith(normalize(target.text_prefix))));}
      catch(error) {pending.push({...key,status:"INVALID_SELECTOR",message:String(error)});continue;}
      copy.targets.push({...target,locator:selector});
      if(matches.length!==1) {pending.push({...key,status:matches.length?"AMBIGUOUS_TARGET":"TARGET_MISSING",count:matches.length,condition:target.condition || target.dom_requirement?.condition || null});continue;}
      const el=matches[0], rect=el.getBoundingClientRect();
      const closed=[];
      for(let at=el;at;at=at.parentElement) {
        if(at.tagName==="DETAILS"&&!at.open) {
          const summary=at.querySelector(":scope > summary");
          if(summary&&!summary.contains(el)) {
            closed.push({summary_text:normalize(summary.textContent),target_locator:selector,action:"點擊這個實際summary後重跑inspect"});
          }
        }
      }
      if(closed.length) {openSummaries.push(...closed.reverse());pending.push({...key,status:"CLOSED_DETAILS",details:closed});}
      const top={x:rect.x+frameOffset.x,y:rect.y+frameOffset.y,width:rect.width,height:rect.height};
      const fully=rect.width>0&&rect.height>0&&rect.x>=0&&rect.y>=0&&rect.right<=win.innerWidth&&rect.bottom<=win.innerHeight&&top.x>=0&&top.y>=0&&top.x+top.width<=innerWidth&&top.y+top.height<=innerHeight;
      const hidden=(()=>{for(let at=el;at;at=at.parentElement){const style=win.getComputedStyle(at);if(at.hidden||style.display==="none"||style.visibility==="hidden"||Number(style.opacity)===0)return true;}return false;})();
      if(!fully||hidden) pending.push({...key,status:hidden?"HIDDEN_TARGET":"SCROLL_OR_SEPARATE_VIEW_REQUIRED"});
      const centerX=rect.x+rect.width/2,centerY=rect.y+rect.height/2;
      let occluded=null;
      if(fully && typeof doc.elementFromPoint==="function") {
        const hit=doc.elementFromPoint(centerX,centerY);
        occluded=Boolean(hit&&!el.contains(hit)&&!hit.contains(el));
        if(occluded)pending.push({...key,status:"CENTER_OCCLUDED",instruction:"以正常UI關閉遮擋或捲動後重拍，不改DOM。"});
      }
      targetRows.push({...key,text:normalize(el.innerText||el.textContent).slice(0,700),
        disabled:Boolean(el.disabled||el.getAttribute("aria-disabled")==="true"||el.querySelector("input:disabled,button:disabled,select:disabled")),
        value:"value" in el?el.value:null,top_rect_css:top,fully_visible:fully&&!hidden&&!closed.length,center_occluded:occluded});
    }
    collectorPages.push(copy);
  }
  const rects=targetRows.map(t=>t.top_rect_css);
  const union=rects.length?{x:Math.min(...rects.map(r=>r.x)),y:Math.min(...rects.map(r=>r.y)),right:Math.max(...rects.map(r=>r.x+r.width)),bottom:Math.max(...rects.map(r=>r.y+r.height))}:null;
  if(union){union.width=union.right-union.x;union.height=union.bottom-union.y;}
  return issue(pending.length?"TARGETS_REQUIRE_REAL_UI_PREPARATION":"DOM_READY_SCREENSHOT_AND_VISUAL_CHECK_PENDING",{
    observed_at:new Date().toISOString(),top_url:location.href,frame_url:win.location.href,
    project_expected:worklist.workspace,viewport_css:{width:innerWidth,height:innerHeight},dpr:devicePixelRatio,
    requested_pages:requested,shared_image_candidate:pages.length>1,shared_image_confirmed:false,
    target_union_css:union,union_can_fit_without_scaling:union?union.width<=innerWidth&&union.height<=innerHeight:false,
    normal_scroll_suggestion_css:union&&union.height<=innerHeight?{x:scrollX,y:Math.max(0,scrollY+union.y-16)}:null,
    pending,open_summaries:openSummaries,targets:targetRows,collector_pages:collectorPages,
    next:"先依pending以正常UI操作，再逐page把collector_pages交給既有collectGuideTargetRects。最後由root取得原始截图及真實來源/影像receipt。"
  });
}
