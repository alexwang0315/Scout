/* Read-only DOM receipt helper. Root only; run in an already-authorized live Chrome tab.
   Does not click, fill, scroll, fetch, save, approve, capture images or change application state.
   The caller supplies one page object from capture-queue.json. */
function collectGuideTargetRects(page) {
  const frame = page.frame_selector ? document.querySelector(page.frame_selector) : null;
  if (page.frame_selector && !frame) return {page: page.page, status: "FRAME_MISSING"};
  let doc;
  try { doc = frame ? frame.contentDocument : document; }
  catch (error) { return {page: page.page, status: "FRAME_NOT_READABLE", error: String(error)}; }
  if (!doc) return {page: page.page, status: "FRAME_NOT_READY"};
  const win = doc.defaultView;
  const frameRect = frame ? frame.getBoundingClientRect() : {x: 0, y: 0};
  const offset = {x: frameRect.x + (frame?.clientLeft || 0), y: frameRect.y + (frame?.clientTop || 0)};
  const rect = r => ({x: r.x, y: r.y, width: r.width, height: r.height});
  const normalize = s => String(s || "").replace(/\s+/g, " ").trim();
  const targets = page.targets.map(target => {
    let found;
    try {
      found = [...doc.querySelectorAll(target.locator)].filter(el =>
        (!target.text_exact || normalize(el.textContent) === normalize(target.text_exact)) &&
        (!target.text_prefix || normalize(el.textContent).startsWith(normalize(target.text_prefix))));
    } catch (error) {
      return {step: target.step, selector: target.locator, status: "INVALID_SELECTOR", error: String(error)};
    }
    if (found.length !== 1) return {step: target.step, selector: target.locator, count: found.length, status: "NOT_UNIQUE_OR_MISSING"};
    const el = found[0], r = el.getBoundingClientRect(), style = win.getComputedStyle(el);
    const top = {x: r.x + offset.x, y: r.y + offset.y, width: r.width, height: r.height};
    const ancestors = [];
    for (let at = el; at; at = at.parentElement) ancestors.push(at);
    const hidden = ancestors.some(at => {
      const css = win.getComputedStyle(at);
      return at.hidden || css.display === "none" || css.visibility === "hidden" || Number(css.opacity) === 0 ||
        (at.tagName === "DETAILS" && !at.open && !at.querySelector(":scope > summary")?.contains(el));
    });
    const fullyVisible = !hidden && r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0 &&
      r.right <= win.innerWidth && r.bottom <= win.innerHeight &&
      top.x >= 0 && top.y >= 0 && top.x + top.width <= innerWidth && top.y + top.height <= innerHeight;
    return {step: target.step, selector: target.locator, count: 1,
      status: fullyVisible ? "DOM_RECT_READY_FOR_VISUAL_CHECK" : "NOT_FULLY_VISIBLE",
      text: normalize(el.innerText || el.textContent).slice(0, 700),
      value: "value" in el ? el.value : null,
      disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true" || el.querySelector("input:disabled,button:disabled,select:disabled")),
      aria_pressed: el.getAttribute("aria-pressed"), frame_rect_css: rect(r), top_rect_css: top,
      fully_visible: fullyVisible, image_rect_assumption: "Apply actual image DPR/viewport only after real screenshot receipt; visual occlusion still needs inspection."};
  });
  return {page: page.page, id: page.id, collected_at: new Date().toISOString(),
    top_url: location.href, frame_url: win.location.href,
    viewport_css: {width: innerWidth, height: innerHeight}, frame_viewport_css: {width: win.innerWidth, height: win.innerHeight},
    dpr: devicePixelRatio, scroll_css: {x: scrollX, y: scrollY},
    frame_scroll_css: {x: win.scrollX, y: win.scrollY},
    source_status: "Supply verified served-source SHA separately; this helper does not fetch source.",
    captured_at: null, image_sha256: null, targets,
    status: targets.every(x => x.status === "DOM_RECT_READY_FOR_VISUAL_CHECK") ? "DOM_RECEIPT_ONLY_SCREENSHOT_PENDING" : "TARGETS_REQUIRE_ATTENTION"};
}
