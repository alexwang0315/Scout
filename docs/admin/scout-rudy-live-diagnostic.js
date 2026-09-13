/* Diagnostic 037 only. Approved 2026-09-12: native Rudy cache fills, no forced
 * refresh; all other writes remain blocked by the isolated Dashboard probe. */
(function (global) {
  "use strict";
  const STAGES = Object.freeze(["initial", "reload", "fit", "first-plus", "native-z20", "actual-maximum", "pan-z20", "cache-hit", "cache-miss", "recovery"]);
  const SVG_IDS = ["overview-map", "lbs-map", "permission-map", "emergency-review-map", "architecture-map", "pace-fit-map"];
  const LENSES = ["structure", "pressure", "risk", "retreat", "events"];
  const NAVIGATION_DOMAINS = ["observed", "terrain", "prior"];
  const sleep = ms => new Promise(resolve => global.setTimeout(resolve, ms));
  const number = value => value !== "" && value != null && Number.isFinite(Number(value)) ? Number(value) : null;
  const requireValue = (condition, message) => { if (!condition) throw new Error(message); };
  let lastReport = null;
  let requestSequence = 0;

  function errorEvidence(error, seen = new Set()) {
    if (error == null) return null;
    if (typeof error !== "object" && typeof error !== "function") return {name: typeof error, message: String(error)};
    if (seen.has(error)) return {name: "CircularErrorCause", message: "Cause already recorded."};
    seen.add(error);
    return {name: String(error.name || "Error"), message: String(error.message || error),
      ...(error.code == null ? {} : {code: String(error.code)}),
      ...(error.cause == null ? {} : {cause: errorEvidence(error.cause, seen)})};
  }

  function casesFor(registry, dailyIds) {
    const ids = new Set(registry.map(item => item.id));
    const expected = [...SVG_IDS, "map", "weather-map", "navigation-map", "debug-map", "permission-day-maps"];
    for (const id of expected) {
      requireValue(ids.has(id), `Rudy inventory missing ${id}; coverage cannot be reduced.`);
    }
    for (const id of ids) requireValue(expected.includes(id), `Rudy inventory has unmapped entry ${id}; coverage must be extended.`);
    const cases = [];
    for (const id of ["map", "weather-map", "debug-map"]) {
      for (const renderer of ["maplibre", "svg"]) cases.push({id, renderer, variant: "default"});
    }
    for (const id of SVG_IDS) {
      const variants = id === "architecture-map"
        ? ["structure", "terrain_demand", "slow_passage", "risk_passage", "reversibility", "time_window", "evidence_quality"] : ["default"];
      for (const variant of variants) cases.push({id, renderer: "svg", variant});
    }
    cases.find(item => item.id === "architecture-map").auditArchitectureLenses = true;
    for (const mode of ["2d", "3d"]) {
      for (const lens of LENSES) cases.push({id: "navigation-map", renderer: "maplibre", domain: "observed", variant: `observed:${mode}:${lens}`});
    }
    for (const lens of LENSES) cases.push({id: "navigation-map", renderer: "svg", domain: "observed", variant: `observed:fallback:${lens}`});
    for (const domain of NAVIGATION_DOMAINS) cases.push({id: "navigation-map", renderer: "svg", domain, variant: `${domain}:loading:structure`});
    cases.find(item => item.id === "navigation-map").auditNavigationDomains = true;
    for (const dayId of dailyIds.length ? [...new Set(dailyIds)] : [null]) {
      cases.push({id: "permission-day-maps", renderer: "svg", variant: dayId || "missing-daily-route"});
    }
    return cases.map(item => ({...item, key: `${item.id}/${item.renderer}/${item.variant}`}));
  }

  function validateNavigationCoverage(evidence, cases) {
    requireValue(evidence?.basis === "production-rendered-dom-and-style" && Array.isArray(evidence.domains)
      && Array.isArray(evidence.rows), "Navigation domain source evidence is missing; native coverage is unverified.");
    requireValue(evidence.domains.length === NAVIGATION_DOMAINS.length
      && new Set(evidence.domains).size === NAVIGATION_DOMAINS.length
      && evidence.domains.every(domain => NAVIGATION_DOMAINS.includes(domain)),
    "Navigation domain controls changed; extend the Rudy matrix before passing.");
    const rows = new Map(evidence.rows.map(row => [`${row.domain}:${row.mode}`, row]));
    requireValue(rows.size === NAVIGATION_DOMAINS.length * 4 && rows.size === evidence.rows.length,
      "Navigation domain source evidence has missing, duplicate, or unmapped renderer rows.");
    for (const domain of NAVIGATION_DOMAINS) {
      for (const mode of ["2d", "3d", "fallback", "loading"]) {
        const row = rows.get(`${domain}:${mode}`);
        requireValue(row && row.stateDomain === domain && (mode === "loading" || row.renderedDomain === domain),
          `${domain}:${mode} rendered another evidence domain; source coverage is unverified.`);
        requireValue(typeof row.hasRudy === "boolean" && row.declaredBasemap === (row.hasRudy ? "rudy-twmap" : "none"),
          `${domain}:${mode} actual source and declared basemap disagree.`);
        const matching = cases.filter(item => item.id === "navigation-map" && item.domain === domain
          && item.variant.startsWith(`${domain}:${mode}:`));
        if (row.hasRudy) {
          const lenses = mode === "loading" ? ["structure"] : domain === "observed" ? LENSES : ["structure"];
          requireValue(matching.length === lenses.length && lenses.every(lens => matching.some(item =>
            item.variant === `${domain}:${mode}:${lens}` && item.renderer === (["2d", "3d"].includes(mode) ? "maplibre" : "svg"))),
          `Unmapped Rudy entry ${domain}:${mode}; extend the native matrix before passing.`);
        } else {
          requireValue(matching.length === 0, `${domain}:${mode} native cases have no Rudy source in the current workspace.`);
        }
      }
    }
    return {status: "passed", ...evidence};
  }

  function validateArchitectureCoverage(lenses, cases) {
    const expected = cases.filter(item => item.id === "architecture-map" && item.renderer === "svg").map(item => item.variant);
    requireValue(Array.isArray(lenses) && lenses.length > 0 && lenses.length === expected.length
      && new Set(lenses).size === lenses.length && lenses.every(lens => expected.includes(lens)),
    "Architecture production lens controls differ from the Rudy matrix; extend coverage before passing.");
    return {status: "passed", basis: "production-lens-controls", lenses};
  }

  function nativeComplete(snapshot, expected = null) {
    return snapshot.rendererReady === true && Number.isInteger(snapshot.matrix) && snapshot.matrix >= 0
      && (expected == null || snapshot.matrix === expected) && snapshot.verified === snapshot.matrix
      && Number.isInteger(snapshot.required) && snapshot.required > 0 && snapshot.success === snapshot.required
      && snapshot.pending === 0 && snapshot.errors === 0 && snapshot.unverified === 0
      && ["ready", "available"].includes(snapshot.status) && !snapshot.failure;
  }

  function atViewMaximum(evidence) {
    return Number.isFinite(evidence?.viewZoom) && Number.isFinite(evidence?.maxViewZoom)
      && evidence.maxViewZoom > 0 && Math.abs(evidence.viewZoom - evidence.maxViewZoom) <= .001;
  }

  function maximumComplete(snapshot) {
    const evidence = snapshot.viewLimits;
    if (!nativeComplete(snapshot, 20) || !atViewMaximum(evidence)
      || !Number.isFinite(evidence.nativePixelRatio) || evidence.nativePixelRatio <= 0
      || evidence.nativePixelRatio > 1.001) return false;
    if (snapshot.activeRenderer === "svg") {
      return evidence.pixelScaleBasis === "svg-tile-css-rectangle" && evidence.measuredTileCount === snapshot.required;
    }
    const camera = evidence.nativeCamera;
    return camera?.active === true && camera.layerId === "rudy-twmap" && camera.providerNativeMaxZoom === 20
      && Number.isFinite(camera.cameraZoom) && Math.abs(camera.cameraZoom - evidence.viewZoom) <= .001
      && Number.isFinite(camera.maxCameraZoom) && Math.abs(camera.maxCameraZoom - evidence.maxViewZoom) <= .001
      && ["unpitched-camera-pixel-scale", "camera-world-scale-only"].includes(camera.pixelScaleScope)
      && camera.requestedAboveNativeMax === false && Array.isArray(camera.requestedNativeZooms)
      && camera.requestedNativeZooms.length > 0 && camera.requestedNativeZooms.every(zoom => Number.isInteger(zoom) && zoom <= 20);
  }

  function descriptorFor(config) {
    const {kind, renderer, root, doc} = config;
    const shell = kind === "navigation" ? root.closest("[data-navigation-maplibre-shell]")
      : doc.querySelector(kind === "debug" ? "#runtimeMapRendererShell" : "#mapRendererShell");
    const scope = kind === "dashboard-svg" ? root : kind === "navigation" ? shell : doc;
    const host = renderer === "maplibre" ? root : null;
    const tileGroup = () => root.querySelector('[data-dashboard-rudy-tile-layer="true"], [data-layer-group="rudy-twmap"]');
    const activeImages = () => [...(tileGroup()?.querySelectorAll("image[data-dashboard-rudy-tile], image[data-raster-tile]") || [])]
      .filter(node => !node.closest('[data-tile-generation="pending"], [data-dashboard-rudy-tile-generation="pending"]'));
    const viewLimits = () => {
      const supplied = config.viewLimits?.() || {};
      let nativeCamera = supplied.nativeCamera || null;
      if (!nativeCamera && host?.dataset.maplibreNativeCameraReceipt) {
        try { nativeCamera = JSON.parse(host.dataset.maplibreNativeCameraReceipt); } catch (_) { /* Unknown cannot pass maximum. */ }
      }
      const current = kind === "dashboard-svg" ? root.dashboardMapController?.getState?.() : null;
      const viewZoom = number(supplied.viewZoom) ?? number(config.map?.getZoom?.()) ?? number(nativeCamera?.cameraZoom) ?? number(current?.zoom);
      const maxViewZoom = number(supplied.maxViewZoom) ?? number(config.map?.getMaxZoom?.())
        ?? number(nativeCamera?.maxCameraZoom) ?? number(root.dataset.mapMaxZoom);
      const rectangles = renderer === "svg" ? activeImages().map(image => image.getBoundingClientRect()) : [];
      const measured = rectangles.filter(rect => Number.isFinite(rect.width) && Number.isFinite(rect.height) && rect.width > 0 && rect.height > 0);
      return {viewZoom, maxViewZoom, nativeCamera,
        nativePixelRatio: renderer === "maplibre" ? number(nativeCamera?.worldPixelsPerProviderPixel)
          : measured.length && measured.length === rectangles.length ? Math.max(...measured.flatMap(rect => [rect.width / 256, rect.height / 256])) : null,
        measuredTileCount: measured.length,
        pixelScaleBasis: renderer === "maplibre" ? nativeCamera?.pixelScaleScope || "unknown" : "svg-tile-css-rectangle"};
    };
    const snapshot = () => {
      const data = renderer === "maplibre" ? host.dataset : kind === "dashboard-svg" ? root.dataset : shell?.dataset || {};
      const group = tileGroup();
      const images = activeImages();
      const tiles = images.map(node => ({key: node.getAttribute("data-dashboard-rudy-tile") || node.getAttribute("data-raster-tile"), href: node.getAttribute("href")}));
      let prefix, matrix, verified, status, failure = "";
      if (renderer === "maplibre") {
        prefix = "maplibreRaster"; matrix = number(data.maplibreRasterNativeZoom);
        verified = number(data.maplibreRasterVerifiedNativeZoom); status = data.maplibreRudyState || data.maplibreRasterState;
      } else if (kind === "dashboard-svg") {
        prefix = "dashboardTile"; matrix = number(data.dashboardTileRequestedZoom);
        verified = number(data.dashboardTileVerifiedZoom); status = data.dashboardTileLoadState;
      } else if (kind === "debug") {
        prefix = "debugRudy"; matrix = number(data.debugRudyRequestedZoom);
        verified = number(data.debugRudyVerifiedZoom); status = data.debugRudyState;
      } else {
        const pendingImage = group?.querySelector('[data-tile-generation="pending"] image[data-raster-tile]');
        matrix = number(pendingImage?.getAttribute("data-raster-tile")?.split("/")[0])
          ?? number(group?.dataset.requestedTileZoom) ?? number(tiles[0]?.key?.split("/")[0]);
        verified = number(group?.dataset.displayedTileZoom); status = group?.dataset.tileGenerationState;
        failure = group?.dataset.nativeTileFailure || "";
      }
      const readCount = field => prefix ? number(data[`${prefix}${field}Count`]) : null;
      const currentView = kind === "dashboard-svg" ? root.dashboardMapController?.getState?.()
        : config.map ? {center: config.map.getCenter().toArray(), zoom: config.map.getZoom(), pitch: config.map.getPitch(), bearing: config.map.getBearing?.()}
          : renderer === "maplibre" ? [data.maplibreCenter, data.maplibreZoom] : root.getAttribute("viewBox");
      const activeRenderer = kind === "dashboard-svg" ? "svg" : kind === "navigation" ? "maplibre" : shell?.dataset.mapRendererActive;
      const rendererReady = kind === "dashboard-svg" ? Boolean(root.dashboardMapController)
        : kind === "navigation" ? root.dataset.navigationMaplibreStatus === "ready"
          : shell?.dataset.mapRendererState === "ready" && activeRenderer === renderer;
      const pendingImages = [...(group?.querySelectorAll('[data-tile-generation="pending"] image, [data-dashboard-rudy-tile-generation="pending"] image') || [])];
      const requestedImages = pendingImages.length ? pendingImages : images;
      const pending = pendingImages.filter(node => node.dataset.tileGenerationLoaded !== "true").length;
      const cohort = String(data.maplibreRasterNativeZooms || "").split(",").filter(Boolean).map(Number);
      const verifiedCohort = String(data.maplibreRasterVerifiedNativeZooms || "").split(",").filter(Boolean).map(Number);
      const cohortVerified = !cohort.length || JSON.stringify(cohort) === JSON.stringify(verifiedCohort);
      const transportVerified = renderer !== "maplibre" || data.maplibreRasterTransport === "same-origin-protocol";
      let initializationReceipt = null;
      const receiptValue = data.maplibreInitReceipt || (kind === "pretrip" ? doc.querySelector("#mapLibreEvidenceMap")
        : kind === "debug" ? doc.querySelector("#runtimeMapLibre") : null)?.dataset.maplibreInitReceipt;
      if (receiptValue) {
        try { initializationReceipt = JSON.parse(receiptValue); }
        catch (_) { initializationReceipt = {parseError: true, raw: receiptValue}; }
      }
      const navigationDomain = config.navigationDomain ? {requested: config.navigationDomain,
        state: config.navigationDomainState?.() || null, rendered: root.dataset.navigationEvidenceDomain || null,
        phase: config.navigationPhase, renderedState: root.dataset.navigationEvidenceState || null} : null;
      const domainVerified = !navigationDomain || navigationDomain.state === navigationDomain.requested
        && (navigationDomain.phase === "loading" ? Boolean(navigationDomain.renderedState)
          : navigationDomain.rendered === navigationDomain.requested);
      const observedAt = Date.now();
      const initializationObservation = {observedAt, basis: "current-renderer-dom",
        documentUrl: doc.location?.href || null, documentReadyState: doc.readyState || null,
        documentVisibility: doc.visibilityState || "unknown", documentHidden: typeof doc.hidden === "boolean" ? doc.hidden : null,
        documentHasFocus: typeof doc.hasFocus === "function" ? doc.hasFocus() : null,
        rootId: root.id || null, rootConnected: typeof root.isConnected === "boolean" ? root.isConnected : null,
        requestedRenderer: renderer, activeRenderer: activeRenderer || null,
        rendererState: shell?.dataset.mapRendererState || root.dataset.navigationMaplibreStatus || null,
        rendererReason: shell?.dataset.mapRendererReason || root.dataset.navigationMaplibreReason || null,
        projectLoadState: shell?.dataset.mapProjectLoadState || null,
        initializationReceiptPresent: Boolean(receiptValue), initializationPhase: initializationReceipt?.phase || null,
        adapterAvailable: Boolean(doc.defaultView?.ScoutMapLibreEvidence),
        bridgeAvailable: kind === "pretrip" ? Boolean(doc.defaultView?.scoutPretripMapRendererBridge)
          : kind === "debug" ? Boolean(doc.defaultView?.scoutDebugMapRendererBridge) : null};
      return {observedAt, activeRenderer, rendererReady: rendererReady && cohortVerified && transportVerified && domainVerified, matrix, verified, status: status || "unknown", failure,
        required: prefix ? readCount("Required") : requestedImages.length,
        success: prefix ? readCount("Success") : requestedImages.filter(node => node.dataset.tileGenerationLoaded === "true").length,
        pending: prefix ? readCount("Pending") : pending, errors: prefix ? readCount("Error") : failure ? 1 : 0,
        unverified: prefix ? readCount("Unverified") : images.filter(node => node.dataset.tileGenerationLoaded !== "true").length,
        matrices: cohort.length ? cohort : matrix == null ? [] : [matrix], view: JSON.stringify(currentView),
        scrollTop: Number(root.scrollTop || 0), scrollLeft: Number(root.scrollLeft || 0),
        initializationReceipt, initializationObservation, navigationDomain, rendererState: shell?.dataset.mapRendererState || root.dataset.navigationMaplibreStatus || null,
        viewLimits: viewLimits(),
        rendererReason: shell?.dataset.mapRendererReason || root.dataset.navigationMaplibreReason || null,
        otherRasterState: renderer === "maplibre" ? data.maplibreRasterState || "unknown" : undefined,
        generation: group?.dataset.activeTileGenerationKey || group?.dataset.dashboardRudyTileKey || tiles.map(tile => tile.key).join("|"),
        tiles: renderer === "svg" ? tiles : undefined};
    };
    const tileView = () => {
      const supplied = config.tileView?.();
      if (supplied?.bounds && supplied?.tileTemplate) return supplied;
      requireValue(renderer === "svg", "MapLibre visible native cohort bridge is unavailable.");
      const image = activeImages()[0];
      const key = (image?.getAttribute("data-raster-tile") || "").split("/").map(Number);
      const box = String(root.getAttribute("viewBox") || "").split(/\s+/).map(Number);
      requireValue(key.length === 3 && box.length === 4 && image, "SVG native viewport projection is unavailable.");
      const [z, x, y] = key, n = 2 ** z;
      const ix = Number(image.getAttribute("x")), iy = Number(image.getAttribute("y"));
      const width = Number(image.getAttribute("width")), height = Number(image.getAttribute("height"));
      requireValue(width > 0 && height > 0, "SVG native tile geometry is unavailable.");
      const lon = value => value / n * 360 - 180;
      const lat = value => Math.atan(Math.sinh(Math.PI * (1 - 2 * value / n))) * 180 / Math.PI;
      const url = new URL(image.getAttribute("href"), doc.location.href);
      url.pathname = url.pathname.replace(/\/\d+\/\d+\/\d+\.png$/, "/{z}/{x}/{y}.png");
      return {bounds: {west: lon(x + (box[0] - ix) / width), east: lon(x + (box[0] + box[2] - ix) / width),
        north: lat(y + (box[1] - iy) / height), south: lat(y + (box[1] + box[3] - iy) / height)},
        tileTemplate: url.href.replace(/%7B([zxy])%7D/gi, "{$1}"), minzoom: 5, maxzoom: 20, tileSize: 256};
    };
    const act = action => {
      if (["left", "right", "up", "down"].includes(action)) {
        const target = renderer === "maplibre" ? root.querySelector("canvas") || root : root;
        target.focus?.({preventScroll: true});
        // MapLibre 6.2's public keyboard handler reads keyCode; Shift+Arrow
        // rotates its camera, so only the SVG accelerator uses Shift here.
        const keyCode = {left: 37, up: 38, right: 39, down: 40}[action];
        target.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown", {key: `Arrow${action[0].toUpperCase()}${action.slice(1)}`,
          keyCode, which: keyCode, shiftKey: renderer === "svg", bubbles: true, cancelable: true}));
        return;
      }
      const selector = action === "fit" ? '[data-map-control="reset"], [data-navigation-maplibre-fit], #fitRoute'
        : action === "plus" ? '[data-map-control="zoom-in"], .maplibregl-ctrl-zoom-in, #zoomIn'
          : '[data-map-rudy-updates], #refreshMapTiles';
      const button = scope?.querySelector(selector);
      requireValue(button && !button.disabled, `${kind} ${action}: actual map control is unavailable.`);
      if (action.endsWith("updates")) {
        const expected = action === "start-updates";
        requireValue(["true", "false"].includes(button.getAttribute("aria-pressed")), "Map update control does not expose its policy.");
        if ((button.getAttribute("aria-pressed") === "true") === expected) return;
      }
      button.click();
    };
    const directionTo = tile => {
      if (!config.map?.project) return tile.direction;
      const native = tileView().tiles?.filter(item => item.z === tile.z) || [];
      requireValue(native.length > 0, "Navigation has no current native cohort to guide the cache-miss pan.");
      const point = item => config.map.project([(item.x + .5) / (2 ** item.z) * 360 - 180,
        Math.atan(Math.sinh(Math.PI * (1 - 2 * (item.y + .5) / (2 ** item.z)))) * 180 / Math.PI]);
      const target = point(tile), centers = native.map(point);
      const dx = target.x - centers.reduce((sum, item) => sum + item.x, 0) / centers.length;
      const dy = target.y - centers.reduce((sum, item) => sum + item.y, 0) / centers.length;
      requireValue(Number.isFinite(dx) && Number.isFinite(dy), "Native cache-miss screen projection is unavailable.");
      return Math.abs(dx) >= Math.abs(dy) ? dx >= 0 ? "right" : "left" : dy >= 0 ? "down" : "up";
    };
    return {...config, snapshot, tileView, act, directionTo};
  }

  function tileUrl(value, base, projectId, mode = null) {
    const url = new URL(value, base);
    const prefix = `/admin/tiles/imagery/${encodeURIComponent(projectId)}/`;
    requireValue(url.origin === new URL(base).origin && !url.username && !url.password
      && url.pathname.startsWith(prefix), "Rudy tile escaped the selected workspace/origin.");
    const match = url.pathname.slice(prefix.length).match(/^(imagery|rudy-twmap)\/(\d+)\/(\d+)\/(\d+)\.png$/);
    requireValue(match && url.searchParams.get("source_id") === "happyman_rudy_twmap", "Rudy tile source or XYZ path is invalid.");
    const [z, x, y] = match.slice(2).map(Number);
    requireValue(z <= 20 && x < 2 ** z && y < 2 ** z && url.searchParams.get("exact") === "1"
      && !url.searchParams.has("refresh"), "Rudy diagnostic requires exact native detail without forced refresh.");
    requireValue((url.searchParams.get("native") === "1" && !url.searchParams.has("cache_only"))
      || (url.searchParams.get("cache_only") === "1" && !url.searchParams.has("native")), "Rudy load policy is not explicit.");
    if (mode) {
      url.searchParams.delete("native"); url.searchParams.delete("cache_only");
      url.searchParams.set(mode === "cache" ? "cache_only" : "native", "1");
    }
    return {href: url.href, z, x, y, key: `${z}/${x}/${y}`};
  }

  function tileRange(view, z) {
    const n = 2 ** z, bounds = view?.bounds;
    requireValue(bounds && [bounds.west, bounds.east, bounds.north, bounds.south].every(Number.isFinite), "Visible Rudy bounds are unavailable.");
    const tx = lon => (lon + 180) / 360 * n;
    const ty = lat => (1 - Math.asinh(Math.tan(Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180)) / Math.PI) / 2 * n;
    const range = {xMin: Math.max(0, Math.floor(tx(bounds.west))), xMax: Math.min(n - 1, Math.ceil(tx(bounds.east)) - 1),
      yMin: Math.max(0, Math.floor(ty(bounds.north))), yMax: Math.min(n - 1, Math.ceil(ty(bounds.south)) - 1)};
    if (Array.isArray(view.sourceBounds) && view.sourceBounds.length === 4) {
      const [west, south, east, north] = view.sourceBounds;
      range.xMin = Math.max(range.xMin, Math.floor(tx(west))); range.xMax = Math.min(range.xMax, Math.ceil(tx(east)) - 1);
      range.yMin = Math.max(range.yMin, Math.floor(ty(north))); range.yMax = Math.min(range.yMax, Math.ceil(ty(south)) - 1);
    }
    return range;
  }

  function urlsFor(descriptor, snapshot, projectId) {
    const base = descriptor.doc.location.href;
    let urls = snapshot.tiles?.map(tile => tileUrl(tile.href, base, projectId)) || [];
    if (!urls.length) {
      const view = descriptor.tileView(), z = snapshot.matrix;
      requireValue(view?.tileTemplate && z != null, "Native source template is unavailable.");
      let tiles = view.tiles;
      if (!Array.isArray(tiles)) {
        const range = tileRange(view, z); tiles = [];
        requireValue((range.xMax - range.xMin + 1) * (range.yMax - range.yMin + 1) <= 512, "Visible Rudy request coverage exceeds the diagnostic tile bound.");
        for (let x = range.xMin; x <= range.xMax; x += 1) for (let y = range.yMin; y <= range.yMax; y += 1) tiles.push({z, x, y});
      }
      for (const tile of tiles) {
        urls.push(tileUrl(view.tileTemplate.replaceAll("{z}", tile.z).replaceAll("{x}", tile.x).replaceAll("{y}", tile.y), base, projectId));
      }
    }
    requireValue(urls.length === snapshot.required && new Set(urls.map(url => url.key)).size === urls.length
      && urls.every(url => (snapshot.matrices || [snapshot.matrix]).includes(url.z))
      && Math.max(...urls.map(url => url.z)) === snapshot.matrix, "Displayed native matrix/required coverage disagrees with its exact tile URLs.");
    return urls;
  }

  async function readTile(value, descriptor, projectId, {allowMissing = false, decode = true, mode = "cache", onReceipt = null} = {}) {
    const tile = tileUrl(value.href || value, descriptor.doc.location.href, projectId, mode);
    const controller = new AbortController();
    const receipt = {requestId: ++requestSequence, purpose: "diagnostic-tile-verification", ...tile,
      mode, method: "GET", fetchCache: "no-store", allowMissing, decodeRequested: decode,
      startedAt: Date.now(), deadlineMs: 15000, phase: "fetch", outcome: "pending", httpStatus: null,
      headers: null, blobBytes: null, bitmapWidth: null, bitmapHeight: null, decoded: false,
      deadlineTriggered: false, abort: {aborted: false, reason: null, trigger: null}, events: [], error: null};
    const copyReceipt = () => ({...receipt, headers: receipt.headers ? {...receipt.headers} : null,
      abort: {...receipt.abort}, events: receipt.events.map(event => ({...event}))});
    const publish = event => {
      const observedAt = Date.now();
      receipt.elapsedMs = Math.max(0, observedAt - receipt.startedAt);
      receipt.observedAt = observedAt;
      receipt.abort = {aborted: controller.signal.aborted, reason: errorEvidence(controller.signal.reason),
        trigger: receipt.deadlineTriggered ? "diagnostic-readTile-deadline" : controller.signal.aborted ? "unknown" : null};
      receipt.events.push({event, phase: receipt.phase, observedAt, elapsedMs: receipt.elapsedMs});
      onReceipt?.(copyReceipt());
    };
    const phase = name => { receipt.phase = name; publish("phase"); };
    const complete = outcome => { receipt.outcome = outcome; receipt.completedAt = Date.now(); phase("complete"); };
    const timer = global.setTimeout(() => {
      receipt.deadlineTriggered = true;
      receipt.deadlineTriggeredAt = Date.now();
      controller.abort();
      publish("abort");
    }, 15000);
    try {
      publish("start");
      const response = await global.fetch(tile.href, {method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store", signal: controller.signal});
      receipt.httpStatus = response.status;
      receipt.headers = Object.fromEntries(["X-Scout-Tile-Exact", "X-Scout-Tile-Zoom", "X-Scout-Imagery-Source-Id",
        "X-Scout-Tile-Source", "Content-Type", "Content-Length"].map(name => [name, response.headers?.get?.(name) ?? null]));
      phase("headers");
      if (allowMissing && response.status === 404) {
        complete("missing");
        return {...tile, status: 404, decoded: false, requestReceipt: copyReceipt()};
      }
      requireValue(response.ok, `${tile.key}: HTTP ${response.status}.`);
      const source = response.headers.get("X-Scout-Tile-Source") || "";
      phase("provenance");
      requireValue(response.headers.get("X-Scout-Tile-Exact") === "true"
        && Number(response.headers.get("X-Scout-Tile-Zoom")) === tile.z
        && response.headers.get("X-Scout-Imagery-Source-Id") === "happyman_rudy_twmap"
        && source && !/fallback|parent|transparent|placeholder|upsampl/i.test(source), `${tile.key}: native provenance is not verified.`);
      if (mode === "cache") requireValue(["local_source_cache", "local_cache"].includes(source), `${tile.key}: cache-only GET fetched remote bytes.`);
      if (decode) {
        phase("blob");
        const blob = await response.blob();
        receipt.blobBytes = number(blob.size);
        phase("decode");
        const bitmap = await global.createImageBitmap(blob);
        receipt.bitmapWidth = number(bitmap.width); receipt.bitmapHeight = number(bitmap.height);
        try {
          phase("dimensions");
          requireValue(bitmap.width >= 256 && bitmap.height >= 256, `${tile.key}: tile has no native 256 px detail.`);
          receipt.decoded = true;
        }
        finally { bitmap.close(); }
      }
      complete("verified");
      return {...tile, status: response.status, source, decoded: decode, requestReceipt: copyReceipt()};
    } catch (error) {
      receipt.outcome = "failed"; receipt.completedAt = Date.now(); receipt.error = errorEvidence(error);
      publish("error");
      throw Object.assign(new Error(error.message, {cause: error}), {name: error.name || "Error", requestReceipt: copyReceipt()});
    } finally { global.clearTimeout(timer); }
  }

  async function waitFor(read, timeoutMs = 60000, progress = null) {
    let deadline = Date.now() + timeoutMs, token;
    const evidence = {startedAt: Date.now(), timeoutMs, pollIntervalMs: 150, scheduler: "setTimeout",
      readCount: 0, deadlineResetCount: 0, lastProgressAt: null};
    try {
      do {
        evidence.readCount += 1; evidence.lastReadAt = Date.now();
        const value = read();
        if (value) return value;
        const next = progress?.();
        if (progress && next !== token) {
          token = next; deadline = Date.now() + timeoutMs;
          evidence.deadlineResetCount += 1; evidence.lastProgressAt = Date.now();
        }
        await sleep(150);
      } while (Date.now() < deadline);
      throw new Error("Native tile/view state did not settle before the diagnostic deadline.");
    } catch (error) {
      throw Object.assign(new Error(error.message, {cause: error}), {waitEvidence: {...evidence,
        deadlineAt: deadline, completedAt: Date.now(), elapsedMs: Math.max(0, Date.now() - evidence.startedAt)}});
    }
  }

  async function ready(descriptor, projectId, {expected = null, previousView = null, previousGeneration = null, onSnapshot = null, onRequestReceipt = null} = {}) {
    let key = "", stable = 0, last, bestSuccess = -1, progressToken = 0;
    const initializationObservations = [];
    let initializationKey = "";
    try {
      const snapshot = await waitFor(() => {
        last = descriptor.snapshot();
        const observation = last.initializationObservation || {observedAt: Date.now(), basis: "renderer-snapshot",
          activeRenderer: last.activeRenderer, rendererState: last.rendererState || null,
          rendererReason: last.rendererReason || null, initializationPhase: last.initializationReceipt?.phase || null};
        const nextInitializationKey = JSON.stringify({...observation, observedAt: null});
        if (nextInitializationKey !== initializationKey) {
          initializationKey = nextInitializationKey; initializationObservations.push(observation);
        }
        onSnapshot?.(last);
        requireValue(descriptor.projectId() === projectId, "Workspace changed during Rudy verification.");
        requireValue(last.scrollTop === 0 && last.scrollLeft === 0, "Map viewport scrolled independently of its camera; tile coverage is displaced.");
        // "pending" is the canonical page's legal initialization state. Only
        // another concrete renderer proves fallback; unknown states must wait.
        if (["maplibre", "svg"].includes(last.activeRenderer) && last.activeRenderer !== descriptor.renderer) {
          throw new Error(`Requested ${descriptor.renderer}, received ${last.activeRenderer}.`);
        }
        const nextKey = JSON.stringify([last.activeRenderer, last.rendererReady, last.matrix, last.verified,
          last.required, last.success, last.pending, last.errors, last.unverified, last.status, last.failure,
          last.view, last.generation, last.scrollTop, last.scrollLeft, last.matrices]);
        stable = nextKey === key ? stable + 1 : 0; key = nextKey;
        return last.activeRenderer === descriptor.renderer && nativeComplete(last, expected)
          && stable >= 2 && (!previousView || last.view !== previousView)
          && (!previousGeneration || last.generation !== previousGeneration) ? last : null;
      }, 60000, () => {
        // A large cold cohort can take longer than one minute while decoded
        // native tiles keep arriving. Only new success extends the idle timer.
        if (Number.isFinite(last?.success) && last.success > bestSuccess) {
          bestSuccess = last.success; progressToken += 1;
        }
        return progressToken;
      });
      const urls = urlsFor(descriptor, snapshot, projectId);
      if (descriptor.renderer === "svg") {
        await Promise.all(urls.map(url => readTile(url, descriptor, projectId, {onReceipt: onRequestReceipt})));
        const current = descriptor.snapshot();
        requireValue(current.view === snapshot.view && current.generation === snapshot.generation
          && current.activeRenderer === descriptor.renderer && nativeComplete(current, expected), "SVG active generation changed during HTTP/decode verification.");
      }
      return {...snapshot, requestCount: urls.length};
    } catch (error) {
      throw Object.assign(new Error(`${error.message} Actual Z${last?.matrix ?? "?"}; ${last?.success ?? "?"}/${last?.required ?? "?"}; state=${last?.status || "unknown"}.`, {cause: error}),
        {requestReceipt: error.requestReceipt || null, waitEvidence: error.waitEvidence || null,
          initializationEvidence: {observations: initializationObservations, latestReceipt: last?.initializationReceipt || null}});
    }
  }

  async function act(descriptor, action) {
    await descriptor.act(action);
    await sleep(240);
  }

  async function findCacheMiss(descriptor, snapshot, projectId, {onReceipt = null} = {}) {
    const view = descriptor.tileView(), z = snapshot.matrix;
    const native = view.tiles?.filter(tile => tile.z === z);
    const range = native?.length ? {xMin: Math.min(...native.map(tile => tile.x)), xMax: Math.max(...native.map(tile => tile.x)),
      yMin: Math.min(...native.map(tile => tile.y)), yMax: Math.max(...native.map(tile => tile.y))} : tileRange(view, z);
    const midX = Math.floor((range.xMin + range.xMax) / 2), midY = Math.floor((range.yMin + range.yMax) / 2);
    for (const offset of [1, 2, 4, 8, 16, 32]) {
      for (const [direction, x, y] of [["right", range.xMax + offset, midY], ["left", range.xMin - offset, midY],
        ["down", midX, range.yMax + offset], ["up", midX, range.yMin - offset]]) {
        if (x < 0 || y < 0 || x >= 2 ** z || y >= 2 ** z) continue;
        const href = view.tileTemplate.replaceAll("{z}", z).replaceAll("{x}", x).replaceAll("{y}", y);
        const result = await readTile(href, descriptor, projectId, {allowMissing: true, decode: false, onReceipt});
        if (result.status === 404) return {...result, direction};
      }
    }
    throw new Error("No genuine cache miss found in the bounded adjacent views; caches were not deleted. Miss/recovery remain unverified.");
  }

  function containsTile(view, tile) {
    if (Array.isArray(view.tiles)) return view.tiles.some(item => item.z === tile.z && item.x === tile.x && item.y === tile.y);
    const range = tileRange(view, tile.z);
    return tile.x >= range.xMin && tile.x <= range.xMax && tile.y >= range.yMin && tile.y <= range.yMax;
  }

  function summarize(cases) {
    const required = cases.reduce((sum, item) => sum + item.stages.length, 0);
    const passed = cases.reduce((sum, item) => sum + item.stages.filter(stage => stage.status === "passed").length, 0);
    const cleanupFailures = cases.filter(item => item.cleanupStatus === "warning").length;
    return {status: required > 0 && passed === required && cleanupFailures === 0 ? "passed" : "warning", required, passed, cleanupFailures,
      incomplete: required - passed, detail: `隔離的既有入口 renderer：${passed}/${required} 個適用階段完成；${cases.length} 組地圖/renderer/變體；${cleanupFailures} 組清理未完成。正式 Chrome 頁面操作另列證據。`};
  }

  async function runCase(testCase, options) {
    const result = {...testCase, stages: [], activeStage: "initial", cleanup: []};
    let probe, descriptor, stage = "initial";
    let lastPublishedAt = -Infinity, lastObserved = "";
    let requests = new Map(), finalized = false;
    const publish = key => {
      if (key !== lastObserved && Date.now() - lastPublishedAt >= 500) {
        lastObserved = key; lastPublishedAt = Date.now(); options.onProgress?.(result);
      }
    };
    const start = name => {
      stage = name; result.activeStage = name; requests = new Map(); result.liveRequestReceipts = [];
      options.onProgress?.(result);
    };
    const requestObserver = () => {
      const stageRequests = requests, requestStage = stage;
      return receipt => {
        stageRequests.set(receipt.requestId, receipt);
        if (!finalized && requestStage === stage) {
          result.liveRequestReceipts = [...stageRequests.values()];
          publish(JSON.stringify([stage, "requests", receipt.requestId, receipt.phase, receipt.outcome, receipt.deadlineTriggered]));
        }
      };
    };
    const readRequest = (value, settings = {}) => readTile(value, descriptor, options.projectId,
      {...settings, onReceipt: requestObserver()});
    const requestEvidence = () => ({capturedAt: Date.now(), requests: [...requests.values()],
      inFlightCount: [...requests.values()].filter(receipt => receipt.outcome === "pending").length});
    const observe = snapshot => {
      result.liveSnapshot = snapshot;
      const key = JSON.stringify([stage, snapshot.matrix, snapshot.verified, snapshot.required, snapshot.success,
        snapshot.pending, snapshot.errors, snapshot.status, snapshot.scrollTop, snapshot.scrollLeft,
        snapshot.activeRenderer, snapshot.rendererState, snapshot.rendererReason, snapshot.initializationReceipt?.phase,
        snapshot.initializationObservation?.projectLoadState,
        snapshot.initializationObservation?.documentVisibility, snapshot.initializationObservation?.documentHasFocus]);
      publish(key);
    };
    const settle = settings => ready(descriptor, options.projectId,
      {...settings, onSnapshot: observe, onRequestReceipt: requestObserver()});
    const addCleanup = receipt => {
      const complete = receipt?.disposed === true && receipt.activeMaps === 0 && receipt.pendingInitializations === 0
        && Array.isArray(receipt.errors) && receipt.errors.length === 0;
      result.cleanup.push({stage, status: complete ? "passed" : "warning", receipt: receipt || null});
      return complete;
    };
    const closeProbe = async () => {
      const current = probe; probe = null;
      if (!current) return true;
      try { return addCleanup(await current.close()); }
      catch (error) { return addCleanup({disposed: false, activeMaps: null, pendingInitializations: null,
        errors: [{phase: "probe-close", errorName: error.name || "Error"}]}); }
    };
    const record = (name, snapshot) => {
      result.liveSnapshot = snapshot;
      result.stages.push({stage: name, status: "passed", snapshot, requestEvidence: requestEvidence()});
      options.onProgress?.(result);
    };
    const verifyDomains = () => {
      if (testCase.auditArchitectureLenses) {
        result.architectureLenses = descriptor.architectureLenses || null;
        result.architectureCoverage = validateArchitectureCoverage(result.architectureLenses, options.inventoryCases || []);
      }
      if (!testCase.auditNavigationDomains) return;
      result.navigationDomainEvidence = descriptor.navigationDomainEvidence || null;
      result.navigationCoverage = validateNavigationCoverage(result.navigationDomainEvidence, options.inventoryCases || []);
    };
    try {
      start("initial");
      probe = await options.open(testCase);
      descriptor = probe.descriptor;
      verifyDomains();
      record(stage, await settle());
      start("reload");
      requireValue(await closeProbe(), "Previous map cleanup is incomplete; reload was not accepted.");
      descriptor = null;
      probe = await options.open(testCase); descriptor = probe.descriptor;
      verifyDomains();
      record(stage, await settle());
      start("fit"); await act(descriptor, "fit");
      const fit = await settle(); record(stage, fit);
      start("first-plus"); await act(descriptor, "plus");
      const first = await settle({previousView: fit.view});
      requireValue(first.matrix > fit.matrix, `First + kept native Z${fit.matrix}; repeated + is not a substitute.`);
      record(stage, first);
      start("native-z20");
      let current = first;
      for (let clicks = 0; current.matrix < 20 && !atViewMaximum(current.viewLimits) && clicks < 48; clicks += 1) {
        await act(descriptor, "plus"); current = descriptor.snapshot();
      }
      const high = await settle({expected: 20}); record(stage, high);
      start("actual-maximum");
      current = high;
      for (let clicks = 0; !atViewMaximum(current.viewLimits) && clicks < 64; clicks += 1) {
        requireValue(Number.isFinite(current.viewLimits?.viewZoom) && Number.isFinite(current.viewLimits?.maxViewZoom),
          "Actual zoom/current maximum receipt is unavailable; a disabled + button is not proof.");
        await act(descriptor, "plus"); current = await settle({expected: 20});
      }
      const maximum = await settle({expected: 20});
      requireValue(maximumComplete(maximum), `Actual maximum is not native-pixel verified: zoom ${maximum.viewLimits?.viewZoom ?? "?"}/${maximum.viewLimits?.maxViewZoom ?? "?"}; pixel ratio ${maximum.viewLimits?.nativePixelRatio ?? "?"}; unbounded native selection ${maximum.viewLimits?.nativeCamera?.requestedAboveNativeMax ?? "unknown"}.`);
      record(stage, maximum);
      start("pan-z20");
      for (let index = 0; index < 6; index += 1) await act(descriptor, "right");
      const pan = await settle({expected: 20, previousView: maximum.view,
        previousGeneration: descriptor.renderer === "svg" ? maximum.generation : null});
      record(stage, pan);
      start("cache-hit");
      await act(descriptor, "stop-updates");
      const cached = await settle({expected: 20});
      const hits = await Promise.all(urlsFor(descriptor, cached, options.projectId).map(url => readRequest(url)));
      record(stage, {...cached, cacheHits: hits.length, cachedSource: [...new Set(hits.map(hit => hit.source))]});
      start("cache-miss");
      const missing = await findCacheMiss(descriptor, cached, options.projectId, {onReceipt: requestObserver()});
      for (let steps = 0; !containsTile(descriptor.tileView(), missing) && steps < 256; steps += 1) {
        await act(descriptor, descriptor.directionTo?.(missing) || missing.direction);
      }
      requireValue(containsTile(descriptor.tileView(), missing), "The genuine missing tile did not enter the actual viewport.");
      const unavailable = await waitFor(() => {
        const snapshot = descriptor.snapshot();
        observe(snapshot);
        requireValue(snapshot.scrollTop === 0 && snapshot.scrollLeft === 0, "Stopped map viewport scrolled independently of its camera.");
        return snapshot.view !== cached.view && !nativeComplete(snapshot) && snapshot.pending === 0
          && (snapshot.errors > 0 || /retained|degraded/.test(snapshot.status)) ? snapshot : null;
      });
      requireValue((await readRequest(missing, {allowMissing: true, decode: false})).status === 404,
        "Missing tile was filled while updates were stopped; cache-only behavior failed.");
      record(stage, {...unavailable, genuineCacheMiss: missing.key, cacheHttpStatus: 404, failureDetected: true});
      start("recovery");
      await act(descriptor, "start-updates");
      const recovered = await settle({expected: 20});
      requireValue(recovered.view === unavailable.view && containsTile(descriptor.tileView(), missing), "Recovery reset the camera or left the missing tile outside the viewport.");
      const recoveryTile = await readRequest(missing);
      record(stage, {...recovered, recoveredTile: recoveryTile.key, recoveryHttpStatus: recoveryTile.status});
    } catch (error) {
      if (error.cleanupReceipt) addCleanup(error.cleanupReceipt);
      let snapshot = result.liveSnapshot || null, snapshotError = null;
      try { if (descriptor) snapshot = descriptor.snapshot(); } catch (failure) { snapshotError = failure.message; }
      result.stages.push({stage, status: "warning", detail: error.message, snapshot, snapshotError,
        snapshotSource: descriptor ? "current-renderer" : snapshot ? "last-observed-before-initialization" : "unavailable",
        error: errorEvidence(error), requestReceipt: error.requestReceipt || null, requestEvidence: requestEvidence(),
        waitEvidence: error.waitEvidence || null, initializationEvidence: error.initializationEvidence || null});
    } finally {
      finalized = true;
      await closeProbe();
      for (const name of STAGES) if (!result.stages.some(item => item.stage === name)) {
        result.stages.push({stage: name, status: "not_checked", detail: `Blocked by ${stage}; not counted as passed.`});
      }
      result.cleanupStatus = result.cleanup.some(item => item.status !== "passed") ? "warning" : result.cleanup.length ? "passed" : "not_checked";
      result.status = result.stages.every(item => item.status === "passed") && result.cleanupStatus === "passed" ? "passed" : "warning";
      options.onProgress?.(result);
    }
    return result;
  }

  async function run(options) {
    requireValue(/^[A-Za-z0-9_.-]+$/.test(options.projectId), "Invalid diagnostic workspace.");
    const cases = casesFor(options.registry, options.dailyIds || []);
    const results = [];
    lastReport = {schemaVersion: 1, projectId: options.projectId, scope: "isolated-existing-entry-renderers",
      approval: "2026-09-12 user arbitration A/B and all Rudy coverage", candidateOnly: true, runtimeSafetyTruth: false,
      cacheDeletion: false, forcedRefresh: false, otherWrites: false, dailyEvidence: options.dailyEvidence || null,
      navigationScope: {readyRudyDomains: ["observed"], readyDomainsWithoutRudy: ["terrain", "prior"],
        loadingRudyDomains: NAVIGATION_DOMAINS, sourceBoundaryBasis: "production-rendered-dom-and-style"},
      cases: results, stageNames: STAGES, status: "running", plannedCases: cases.length, plannedStages: cases.length * STAGES.length,
      required: cases.length * STAGES.length, passed: 0, startedAt: new Date().toISOString()};
    for (const testCase of cases) {
      requireValue(options.currentProjectId() === options.projectId, "Workspace changed; diagnostic cannot reuse another project's result.");
      lastReport.activeCase = testCase.key;
      results.push(await runCase(testCase, {...options, inventoryCases: cases, onProgress: result => {
        lastReport.activeResult = result;
        const observed = results.some(item => item.key === result.key) ? results : [...results, result];
        const summary = summarize(observed);
        Object.assign(lastReport, {status: "running", passed: summary.passed, recordedStages: summary.required,
          incomplete: lastReport.plannedStages - summary.passed, cleanupFailures: summary.cleanupFailures});
        options.onProgress?.(result, lastReport);
      }}));
      const completed = summarize(results);
      Object.assign(lastReport, completed, {status: "running", required: lastReport.plannedStages,
        recordedStages: completed.required, incomplete: lastReport.plannedStages - completed.passed});
    }
    Object.assign(lastReport, summarize(results), {completedAt: new Date().toISOString()});
    options.onProgress?.(lastReport.activeResult, lastReport);
    return lastReport;
  }

  const api = Object.freeze({STAGES, casesFor, validateNavigationCoverage, validateArchitectureCoverage, nativeComplete, maximumComplete, descriptorFor, tileUrl, tileRange, urlsFor, readTile,
    findCacheMiss, containsTile, summarize, runCase, run, snapshot: () => lastReport});
  global.ScoutRudyLiveDiagnostic = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
