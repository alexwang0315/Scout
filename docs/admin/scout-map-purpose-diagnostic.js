/* Existing Dashboard D049: approved vector-comparison and illustrative-map
 * purposes. This module never creates plans or changes the analysis selection. */
(function (global) {
  "use strict";
  const requireValue = (condition, message) => { if (!condition) throw new Error(message); };
  const array = value => Array.isArray(value) ? value : [];
  const sha = value => /^[0-9a-f]{64}$/i.test(String(value || ""));
  const sleep = ms => new Promise(resolve => global.setTimeout(resolve, ms));
  const canonical = value => JSON.stringify(value, function (_key, item) {
    return item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item;
  });
  const ROLES = ["route-context", "permission", "weather", "navigation", "architecture", "pace-fit"];
  const CASES = Object.freeze([
    {key: "permission-preview", route: "outdoor-permission", mapId: "preview", purpose: "vector-comparison"},
    {key: "permission-compare", route: "outdoor-permission", mapId: "compare", purpose: "vector-comparison"},
    ...ROLES.map(role => ({key: `analysis-${role}`, route: `outdoor-${role}`, mapId: "analysis", purpose: "vector-comparison"})),
    {key: "analysis-body-index", route: "outdoor-pace-fit-body-index", mapId: "analysis", purpose: "vector-comparison"},
    {key: "legacy-emergency", route: "emergency", mapId: "desktop", purpose: "illustrative-only"},
  ]);
  const PLANNED_STAGES = ["purpose-and-version", "source-geometry", "controls", "layer-toggles", "anchors", "authority", "reload"];
  const LEGACY_STAGES = ["illustrative-purpose", "layer-toggles", "authority", "reload"];

  function lines(value) {
    if (value?.type === "FeatureCollection") return array(value.features).flatMap(lines);
    if (value?.type === "Feature") return lines(value.geometry);
    if (value?.type === "GeometryCollection") return array(value.geometries).flatMap(lines);
    if (value?.type === "LineString") return [value.coordinates];
    if (value?.type === "MultiLineString") return array(value.coordinates);
    return [];
  }

  function versionBinding(detail, projectId) {
    const manifest = detail?.manifest, preview = detail?.preview;
    requireValue(manifest?.project_id === projectId && preview?.project_id === projectId,
      "Saved Planned version belongs to another workspace or lacks its preview.");
    requireValue(manifest.version_id && sha(manifest.manifest_sha256) && sha(manifest.preview_sha256)
      && sha(manifest.geometry_sha256) && preview.preview_sha256 === manifest.preview_sha256
      && preview.geometry_sha256 === manifest.geometry_sha256 && sha(manifest.files?.["preview.json"]?.sha256),
    "Saved Planned version/preview/geometry hash binding is incomplete.");
    requireValue(detail.candidate_only === true && detail.runtime_safety_truth === false
      && manifest.candidate_only === true && manifest.runtime_safety_truth === false,
    "Saved Planned version claims authority beyond a candidate.");
    requireValue(lines(preview.route_geojson).length > 0 && lines(preview.golden_geojson).length > 0,
      "Saved comparison is missing Golden or Planned source geometry; another version cannot substitute it.");
    return {project: projectId, version: manifest.version_id, manifest_sha256: manifest.manifest_sha256,
      preview_sha256: manifest.preview_sha256, geometry_sha256: manifest.geometry_sha256,
      preview_file_sha256: manifest.files?.["preview.json"]?.sha256 || null,
      source_status: detail.source_status?.status || detail.source_status || "unknown"};
  }

  async function readContext(options) {
    const project = options.projectId, prefix = `/admin/pretrip/projects/${encodeURIComponent(project)}`;
    const context = {projectId: project, readRefs: [], selected: null, comparison: null, subject: null};
    const read = async path => { context.readRefs.push(path); return options.read(path); };
    try {
      const [catalog, selection, subject] = await Promise.all([
        read(`${prefix}/planned-route/versions`), read(`${prefix}/planned-route/analysis-selection`), read(`${prefix}/analysis-subject`),
      ]);
      requireValue(catalog?.project_id === project && Array.isArray(catalog.versions), "Planned version catalog has no matching workspace.");
      requireValue(selection?.project_id === project && selection.subject_kind === "planned_gpx" && selection.version_id,
        "Current workspace has no selected Planned version. Diagnostic will not select or generate one.");
      const saved = await read(`${prefix}/planned-route/versions/${encodeURIComponent(selection.version_id)}`);
      const binding = versionBinding(saved, project);
      requireValue(binding.manifest_sha256 === selection.manifest_sha256 && binding.source_status === "current",
        "Selected Planned manifest or current source binding changed; re-review the real saved version.");
      requireValue(subject?.project_id === project && subject.subject_kind === "planned_gpx"
        && subject.selected_plan_version_id === binding.version && subject.planned_bundle_sha256 === binding.manifest_sha256
        && subject.geometry_fingerprint === binding.geometry_sha256 && sha(subject.analysis_revision),
      "Current analysis subject does not match the selected Saved Planned version.");
      requireValue(subject.candidate_only === true && subject.runtime_safety_truth === false && subject.departure_approval_granted === false,
        "Planned analysis subject claims runtime or departure authority.");
      const previewSource = subject.sources?.planned_comparison_preview;
      requireValue(previewSource?.status === "available" && previewSource.sha256 === binding.preview_file_sha256
        && previewSource.ref?.endsWith(`/versions/${binding.version}/preview.json`),
      "Analysis comparison lacks the selected immutable preview source/hash.");
      requireValue(canonical(subject.planned_route_geojson) === canonical(saved.preview.route_geojson)
        && canonical(subject.golden_route_geojson) === canonical(saved.preview.golden_geojson),
      "Analysis geometry differs from its selected Saved Planned comparison.");
      context.selected = saved; context.binding = binding; context.subject = subject;
      const other = catalog.versions.find(row => row.version_id !== binding.version);
      if (!other) context.compareError = "No second saved Planned version exists; the Compare instance remains unverified.";
      else {
        try {
          context.comparison = await read(`${prefix}/planned-route/versions/${encodeURIComponent(other.version_id)}`);
          context.compareBinding = versionBinding(context.comparison, project);
        } catch (error) { context.compareError = error.message; }
      }
    } catch (error) { context.plannedError = error.message; }
    return context;
  }

  function inspectBinding(descriptor, testCase, context) {
    const root = descriptor.root, data = root.dataset;
    const expected = testCase.mapId === "compare" ? context.compareBinding : context.binding;
    requireValue(root.isConnected && root.ownerDocument === descriptor.doc && data.plannedMap === testCase.mapId,
      "The actual Planned map instance is missing or belongs to another document.");
    requireValue(data.mapPurpose === "vector-comparison" && root.querySelector("[data-planned-map-purpose]")?.textContent.includes("向量比較"),
      "Planned map does not visibly identify its vector-comparison purpose.");
    for (const [name, value] of Object.entries({Project: expected.project, Version: expected.version,
      ManifestSha256: expected.manifest_sha256, GeometrySha256: expected.geometry_sha256})) {
      requireValue(data[`plannedMap${name}`] === value, `Planned ${name} does not match the selected source/version.`);
    }
    if (testCase.mapId === "analysis") {
      const expectedRole = testCase.key === "analysis-body-index" ? "pace_fit" : testCase.route.replace("outdoor-", "").replaceAll("-", "_");
      requireValue(data.plannedMapAnalysisRole === expectedRole, "Analysis map was rendered for another force/entry role.");
      requireValue(data.plannedMapAnalysisRevision === context.subject.analysis_revision,
        "Analysis map revision changed or belongs to another selected version.");
      requireValue(data.plannedMapSourceStatus === context.subject.schedule_status, "Analysis source status differs from the selected subject.");
    } else {
      requireValue(data.plannedMapPreviewSha256 === expected.preview_sha256, "Saved preview hash does not match the rendered map.");
      requireValue(data.plannedMapSourceStatus === expected.source_status, "Saved comparison source freshness is hidden or incorrect.");
    }
    requireValue(root.querySelector('svg[data-planned-bound="true"]'), "Production Planned map event binding did not complete.");
    return {...expected, analysisRevision: data.plannedMapAnalysisRevision || null, entry: testCase.route,
      instance: testCase.mapId, purpose: data.mapPurpose, sourceBasis: descriptor.sourceBasis,
      entryActions: descriptor.entryActions || [], componentReads: descriptor.requestLog || []};
  }

  function geometryEvidence(descriptor, planned, golden) {
    const root = descriptor.root, pairs = [];
    const counts = {};
    for (const [layer, geometry] of [["golden", golden], ["planned", planned]]) {
      const source = lines(geometry), rendered = [...root.querySelectorAll(`path[data-planned-map-layer="${layer}"]`)];
      requireValue(source.length > 0 && rendered.length === source.length, `${layer} source pieces are missing, merged, or invented.`);
      let total = 0;
      source.forEach((coordinates, index) => {
        requireValue(Array.isArray(coordinates) && coordinates.length >= 2, `${layer} contains an incomplete source piece.`);
        const path = rendered[index], d = path.getAttribute("d") || "";
        const commands = [...d.matchAll(/([ML])\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?),\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/gi)];
        requireValue(commands.length === coordinates.length && commands[0]?.[1] === "M"
          && commands.slice(1).every(command => command[1] === "L") && d.replace(/([ML])\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?),\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/gi, "").trim() === "",
        `${layer} point order/count or source gap boundary changed.`);
        coordinates.forEach((coordinate, point) => {
          requireValue(Array.isArray(coordinate) && Number.isFinite(coordinate[0]) && Number.isFinite(coordinate[1]),
            `${layer} has nonnumeric WGS84 source coordinates.`);
          const lon = Number(coordinate?.[0]), lat = Number(coordinate?.[1]);
          requireValue(Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lon) <= 180 && Math.abs(lat) <= 90,
            `${layer} has invalid WGS84 source coordinates.`);
          pairs.push({lon, lat, x: Number(commands[point][2]), y: Number(commands[point][3])});
        });
        total += coordinates.length;
      });
      counts[layer] = {pieces: source.length, points: total};
    }
    // An independent affine check uses all source/rendered points. It catches
    // shortened, reversed, shifted or invented pieces without copying mapHtml.
    for (const [input, output, sign] of [["lon", "x", 1], ["lat", "y", -1]]) {
      const ordered = pairs.slice().sort((a, b) => a[input] - b[input]);
      const first = ordered[0], last = ordered.at(-1), span = last[input] - first[input];
      if (span < 1e-12) requireValue(pairs.every(point => Math.abs(point[output] - first[output]) < .002), "Degenerate source axis was distorted.");
      else {
        const scale = (last[output] - first[output]) / span;
        requireValue(Number.isFinite(scale) && scale * sign > 0, "Source direction or projection scale is invalid.");
        requireValue(pairs.every(point => Math.abs(point[output] - (first[output] + (point[input] - first[input]) * scale)) < .004),
          "Rendered source geometry is not one consistent projection of all input points.");
      }
    }
    requireValue(root.querySelectorAll("image, img, canvas, [data-dashboard-rudy-tile-layer], [data-layer-group='rudy-twmap']").length === 0,
      "Vector comparison unexpectedly includes a raster/native basemap.");
    return {sourcePieces: counts, preservedOrder: true, preservedGaps: true, projection: "all-point-affine-invariant", nativeTileClaim: false};
  }

  const view = root => (root.querySelector("svg").getAttribute("viewBox") || "").trim().split(/\s+/).map(Number);
  const sameView = (a, b) => a.length === 4 && b.length === 4 && a.every((value, index) => Math.abs(value - b[index]) < .001);
  function click(root, selector) {
    const button = root.querySelector(selector);
    requireValue(button && !button.disabled, `Actual map control is unavailable: ${selector}`);
    button.click();
  }
  function pointer(doc, target, type, x, y) {
    const EventClass = doc.defaultView.PointerEvent || doc.defaultView.MouseEvent;
    target.dispatchEvent(new EventClass(type, {clientX: x, clientY: y, pointerId: 19, pointerType: "mouse", isPrimary: true,
      button: 0, buttons: type === "pointerup" ? 0 : 1, bubbles: true, cancelable: true}));
  }
  async function controlEvidence(descriptor) {
    const {root, doc} = descriptor;
    click(root, '[data-planned-action="map-fit"]'); const fitted = view(root);
    click(root, '[data-planned-action="map-in"]'); const zoomIn = view(root);
    requireValue(zoomIn[2] < fitted[2] && zoomIn[3] < fitted[3], "Planned + did not change the map view.");
    click(root, '[data-planned-action="map-out"]'); const zoomOut = view(root);
    requireValue(zoomOut[2] > zoomIn[2] && zoomOut[3] > zoomIn[3], "Planned − did not change the map view.");
    const svg = root.querySelector("svg"), rect = svg.getBoundingClientRect();
    requireValue(rect.width > 0 && rect.height > 0, "Planned viewport has no actual screen extent.");
    const x = rect.left + rect.width * .5, y = rect.top + rect.height * .5;
    pointer(doc, svg, "pointerdown", x, y); pointer(doc, svg, "pointermove", x + 37, y + 21); pointer(doc, svg, "pointerup", x + 37, y + 21);
    const panned = view(root);
    requireValue(!sameView(panned, zoomOut) && Math.abs(panned[2] - zoomOut[2]) < .001, "Planned pointer pan did not move the actual view.");
    click(root, '[data-planned-action="map-fit"]'); const reset = view(root);
    requireValue(sameView(reset, fitted), "Planned Fit did not restore the fitted source view.");
    await sleep(0);
    return {fit: fitted, zoomIn, zoomOut, pointerPan: panned, reset, inputBasis: "isolated-production-DOM-events"};
  }

  function layerEvidence(descriptor, legacy = false) {
    const {root, doc} = descriptor;
    const controls = [...(legacy ? root.closest("section").querySelectorAll("[data-layer-toggle]") : root.querySelectorAll("[data-planned-map-toggle]"))];
    const expected = legacy ? ["rudy-twmap", "imagery", "overpass", "segments", "checkpoints", "route-notes", "terrain"] : ["golden", "planned"];
    const names = controls.map(control => legacy ? control.dataset.layerToggle : control.dataset.plannedMapToggle);
    requireValue(names.length === expected.length && expected.every(name => names.includes(name)), "A production layer toggle is missing, duplicated, or unmapped.");
    const rows = [];
    for (const control of controls) {
      const name = legacy ? control.dataset.layerToggle : control.dataset.plannedMapToggle;
      const groups = [...root.querySelectorAll(legacy ? `[data-layer-group="${name}"]${name === "checkpoints" ? ', [data-layer-group="mcp"]' : ""}` : `[data-planned-map-layer="${name}"]`)];
      requireValue(groups.length > 0 && !control.disabled, `${name} has no rendered source layer or usable control.`);
      const set = enabled => {
        if (legacy) { if ((control.getAttribute("aria-pressed") === "true") !== enabled) control.click(); }
        else { control.checked = enabled; control.dispatchEvent(new doc.defaultView.Event("change", {bubbles: true})); }
      };
      set(false);
      requireValue(groups.every(group => doc.defaultView.getComputedStyle(group).display === "none"), `${name} off left rendered content visible.`);
      set(true);
      requireValue(groups.every(group => doc.defaultView.getComputedStyle(group).display !== "none"), `${name} on did not restore rendered content.`);
      rows.push({layer: name, groups: groups.length, off: true, on: true, purpose: legacy ? "illustrative-only" : "vector-comparison"});
    }
    return rows;
  }

  function anchorEvidence(descriptor, expectedPoints) {
    const {root, doc} = descriptor;
    const available = array(expectedPoints).filter(point => {
      const coordinate = point.coordinates || point.coordinate || (point.lon != null && point.lat != null ? [point.lon, point.lat] : null);
      return coordinate && Number.isFinite(Number(coordinate[0])) && Number.isFinite(Number(coordinate[1]));
    });
    const anchors = [...root.querySelectorAll("[data-planned-map-anchor]")];
    requireValue(anchors.length === available.length && anchors.length > 0, "Source anchors are missing or anchor controls remain unexercised.");
    const sourceId = point => String(point.anchor_id || point.candidate_id || point.checkpoint_id || point.id || point.name || point.label || "");
    requireValue(anchors.every((anchor, index) => sourceId(available[index]) && anchor.dataset.plannedMapAnchor === sourceId(available[index])),
      "Rendered anchor identity/order differs from its source.");
    const receipt = [];
    for (const [index, action] of ["click", "Enter", " "].entries()) {
      const target = anchors[index % anchors.length];
      if (action === "click") target.dispatchEvent(new doc.defaultView.MouseEvent("click", {bubbles: true}));
      else target.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown", {key: action, bubbles: true, cancelable: true}));
      requireValue(target.classList.contains("is-selected") && root.querySelector("[data-planned-map-selection]").textContent.includes(target.dataset.plannedMapAnchor),
        `Planned anchor ${action} did not update the selected source anchor.`);
      receipt.push({action, anchor: target.dataset.plannedMapAnchor});
    }
    return {sourceAnchors: available.length, renderedAnchors: anchors.length, operated: receipt};
  }

  function authorityEvidence(descriptor, legacy = false) {
    if (legacy) {
      const artifact = JSON.parse(descriptor.doc.querySelector('[data-artifact-preview="desktop"]').textContent);
      for (const name of ["external_send_performed", "safety_api_called", "phase1_mutation_requested", "sent"])
        requireValue(artifact[name] === false, `Legacy artifact has an unsafe ${name} claim.`);
      const receipt = descriptor.boundary?.();
      requireValue(receipt?.pendingRefresh === false && receipt.livingConnected === false && receipt.externalSendPerformed === false,
        "Legacy illustration probe has active Living refresh or outbound authority.");
      return {externalSendPerformed: false, runtimeSafetyTruth: false, phase1Mutation: false,
        mapIsWorkspaceRouteEvidence: false, packetRouteId: artifact.route_id, purpose: "illustrative-only"};
    }
    const data = descriptor.root.dataset;
    requireValue(data.candidateOnly === "true" && data.runtimeSafetyTruth === "false" && data.departureApprovalGranted === "false",
      "Planned map claims runtime or departure authority.");
    return {candidateOnly: true, runtimeSafetyTruth: false, departureApprovalGranted: false};
  }

  function illustrationEvidence(descriptor) {
    const {root, doc} = descriptor;
    requireValue(root?.isConnected && root.dataset.mapPurpose === "illustrative-only"
      && root.dataset.mapSource === "static-prototype-geometry" && root.dataset.workspaceRouteEvidence === "false"
      && root.dataset.runtimeSafetyTruth === "false", "Legacy map does not declare its illustrative source/authority boundary.");
    const note = root.closest("section")?.querySelector('[data-legacy-map-purpose="illustrative-only"]');
    requireValue(note?.textContent.includes("固定 SVG") && note.textContent.includes("CSS"), "Legacy map has no visible illustrative-source explanation.");
    requireValue(root.querySelectorAll("img, image, canvas").length === 0, "Legacy illustration unexpectedly loaded raster or live map content.");
    requireValue(root.querySelector("svg path"), "Legacy illustration has no rendered schematic geometry.");
    requireValue(doc.querySelector('[data-dashboard-emergency-mode="desktop-only"]'), "Legacy diagnostic did not load the actual desktop entry.");
    return {purpose: "illustrative-only", source: "static-prototype-geometry", workspaceRouteEvidence: false,
      entry: new URL(doc.URL).pathname, dailyReviewContext: descriptor.dailyReviewContext || null,
      rasterTiles: 0, illustrationPaths: root.querySelectorAll("svg path").length, note: note.textContent};
  }

  async function runCase(testCase, context, options) {
    const legacy = testCase.purpose === "illustrative-only", stages = legacy ? LEGACY_STAGES : PLANNED_STAGES;
    const result = {...testCase, stages: [], status: "running", cleanup: []};
    let probe = null, descriptor = null, activeStage = stages[0];
    const publish = () => options.onProgress?.(result);
    const record = async (stage, action) => { activeStage = stage; result.activeStage = stage; publish();
      const evidence = await action(); result.stages.push({stage, status: "passed", evidence}); publish(); return evidence; };
    const close = async () => {
      const current = probe; probe = null;
      if (!current) return;
      let receipt;
      try { receipt = await current.close(); }
      catch (error) { receipt = {disposed: false, errors: [{phase: "close", errorName: error.name || "Error"}]}; }
      const passed = receipt?.disposed === true && array(receipt.errors).length === 0;
      result.cleanup.push({status: passed ? "passed" : "failed", receipt});
      requireValue(passed, "Purpose probe cleanup is incomplete.");
    };
    try {
      if (!legacy) {
        requireValue(!context.plannedError, context.plannedError);
        requireValue(testCase.mapId !== "compare" || !context.compareError, context.compareError);
      }
      probe = await options.open(testCase, context); descriptor = probe.descriptor;
      if (legacy) {
        await record("illustrative-purpose", () => illustrationEvidence(descriptor));
        const before = JSON.stringify(authorityEvidence(descriptor, true));
        await record("layer-toggles", () => layerEvidence(descriptor, true));
        await record("authority", () => { const after = authorityEvidence(descriptor, true);
          requireValue(JSON.stringify(after) === before, "Map layer toggles changed Legacy approval state."); return after; });
      } else {
        const detail = testCase.mapId === "compare" ? context.comparison : context.selected;
        await record("purpose-and-version", () => inspectBinding(descriptor, testCase, context));
        await record("source-geometry", () => geometryEvidence(descriptor, detail.preview.route_geojson, detail.preview.golden_geojson));
        await record("controls", () => controlEvidence(descriptor));
        await record("layer-toggles", () => layerEvidence(descriptor));
        await record("anchors", () => anchorEvidence(descriptor, descriptor.sourceAnchors));
        await record("authority", () => authorityEvidence(descriptor));
        inspectBinding(descriptor, testCase, context);
      }
      activeStage = "cleanup"; await close(); descriptor = null;
      await record("reload", async () => {
        probe = await options.open(testCase, context); descriptor = probe.descriptor;
        if (legacy) return {purpose: illustrationEvidence(descriptor), layers: layerEvidence(descriptor, true), authority: authorityEvidence(descriptor, true)};
        const detail = testCase.mapId === "compare" ? context.comparison : context.selected;
        return {binding: inspectBinding(descriptor, testCase, context),
          geometry: geometryEvidence(descriptor, detail.preview.route_geojson, detail.preview.golden_geojson),
          controls: await controlEvidence(descriptor), layers: layerEvidence(descriptor),
          anchors: anchorEvidence(descriptor, descriptor.sourceAnchors), authority: authorityEvidence(descriptor)};
      });
    } catch (error) {
      if (error.cleanupReceipt) result.cleanup.push({status: error.cleanupReceipt.disposed === true
        && array(error.cleanupReceipt.errors).length === 0 ? "passed" : "failed", receipt: error.cleanupReceipt});
      result.stages.push({stage: activeStage, status: "failed", detail: error.message,
        observed: descriptor?.root ? {mapId: descriptor.root.dataset.plannedMap || descriptor.root.dataset.mapSurface,
          purpose: descriptor.root.dataset.mapPurpose, version: descriptor.root.dataset.plannedMapVersion || null} : null});
    } finally {
      try { await close(); } catch (_) { /* Cleanup failure is retained below; later instances still run. */ }
      for (const stage of stages) if (!result.stages.some(row => row.stage === stage))
        result.stages.push({stage, status: "not_checked", detail: "Blocked by an earlier failure; not counted as passed."});
      result.status = result.stages.every(row => row.status === "passed") && result.cleanup.length > 0
        && result.cleanup.every(row => row.status === "passed") ? "passed" : "failed";
      publish();
    }
    return result;
  }

  function summarize(rows) {
    const expected = CASES.map(row => row.key), keys = rows.map(row => row.key);
    const complete = keys.length === expected.length && new Set(keys).size === expected.length && expected.every(key => keys.includes(key));
    const passed = rows.filter(row => row.status === "passed").length;
    return {status: complete && passed === expected.length ? "passed" : "failed", plannedRows: expected.length,
      recordedRows: rows.length, passedRows: passed, missingRows: expected.filter(key => !keys.includes(key)),
      detail: `用途矩陣 ${passed}/${expected.length}：Planned 9個向量比較入口與 Legacy 1個示意入口；隔離的正式render/bind，完整Chrome頁面操作另列證據。`};
  }

  async function run(options) {
    const context = await readContext(options), rows = [];
    const report = {schemaVersion: 1, projectId: options.projectId, startedAt: new Date().toISOString(), status: "running",
      scope: "isolated-production-map-purpose", nativeTileAcceptance: false, workspaceWrites: false,
      readRefs: context.readRefs, sourceBinding: context.binding || null, compareBinding: context.compareBinding || null,
      plannedDataError: context.plannedError || null, compareDataError: context.compareError || null, rows};
    for (const testCase of CASES) {
      if (options.currentProjectId() !== options.projectId) {
        report.scopeError = "Workspace changed during the purpose matrix; remaining entries were not opened.";
        rows.push({...testCase, status: "failed", cleanup: [], stages: [{stage: "workspace-binding", status: "failed", detail: report.scopeError}]});
        continue;
      }
      report.activeCase = testCase.key;
      rows.push(await runCase(testCase, context, {...options, onProgress: result => {
        report.activeResult = result; options.onProgress?.(report);
      }}));
    }
    Object.assign(report, summarize(rows), {completedAt: new Date().toISOString()});
    options.onProgress?.(report);
    return report;
  }
  const api = Object.freeze({CASES, versionBinding, readContext, inspectBinding, geometryEvidence, controlEvidence,
    layerEvidence, anchorEvidence, authorityEvidence, illustrationEvidence, runCase, summarize, run});
  global.ScoutMapPurposeDiagnostic = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
