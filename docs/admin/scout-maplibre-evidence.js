(function installScoutMapLibreEvidence(global) {
  "use strict";

  const MAPLIBRE_VERSION = "6.2.0";
  const DEFAULT_MODULE_URL = "/admin/vendor/maplibre-gl/6.2.0/maplibre-gl.mjs";
  const RENDERER_PREFERENCES = new Set(["auto", "maplibre", "svg"]);
  const EVIDENCE_SOURCE_ID = "scout-evidence";
  const EVIDENCE_LAYER_IDS = Object.freeze({
    background: "scout-evidence-background",
    osmFill: "scout-evidence-osm-fill",
    osmLineCasing: "scout-evidence-osm-line-casing",
    osmLine: "scout-evidence-osm-line",
    osmPoint: "scout-evidence-osm-point",
    fill: "scout-evidence-fill",
    line: "scout-evidence-line",
    point: "scout-evidence-point",
    overlayFill: "scout-evidence-overlay-fill",
  });
  const RASTER_NETWORK_SCOPES = new Set(["same_origin", "explicit_remote"]);
  const RASTER_RENDER_POSITIONS = new Set(["base", "overlay"]);
  const RASTER_LAYER_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{0,79}$/;
  const MAX_RASTER_TILE_TEMPLATES = 4;
  let mapLibreModulePromise = null;
  let rasterProtocolSequence = 0;

  function normalizeRendererPreference(value) {
    const normalized = String(value || "auto").trim().toLowerCase();
    return RENDERER_PREFERENCES.has(normalized) ? normalized : "auto";
  }

  function webglAvailable(documentRef = global.document) {
    try {
      if (!documentRef?.createElement) return false;
      const canvas = documentRef.createElement("canvas");
      return Boolean(
        global.WebGL2RenderingContext && canvas.getContext("webgl2")
        || global.WebGLRenderingContext && (
          canvas.getContext("webgl") || canvas.getContext("experimental-webgl")
        )
      );
    } catch (_error) {
      return false;
    }
  }

  function resolveRenderer({requested = "auto", webglAvailable: hasWebGl = false} = {}) {
    const normalized = normalizeRendererPreference(requested);
    if (normalized === "svg") {
      return {
        requested: normalized,
        active: "svg",
        state: "ready",
        reason: "forced_svg",
      };
    }
    if (!hasWebGl) {
      return {
        requested: normalized,
        active: "svg",
        state: "degraded",
        reason: "webgl_unavailable",
      };
    }
    return {
      requested: normalized,
      active: "maplibre",
      state: "loading",
      reason: "maplibre_selected",
    };
  }

  function firstIdentifier(...values) {
    for (const value of values) {
      if (value === null || value === undefined) continue;
      const normalized = String(value).trim();
      if (normalized) return normalized;
    }
    return null;
  }

  function normalizeEvidenceIdentity(item = {}, {layerId = "", ordinal = 0} = {}) {
    const sourceId = firstIdentifier(
      item.source_id,
      item.sourceId,
      item.evidence_id,
      item.event_id,
      item.checkpoint_id,
      item.segment_id,
    );
    const artifactId = firstIdentifier(
      item.artifact_id,
      item.artifactId,
      item.artifact_ref,
    );
    const candidateId = firstIdentifier(
      item.candidate_id,
      item.candidateId,
      item.candidate_ref,
      item.review_candidate_id,
    );
    const normalizedLayerId = firstIdentifier(layerId, item.layer_id) || "unclassified";
    const explicitFeatureId = firstIdentifier(
      item.feature_id,
      item.featureId,
      item.map_feature_id,
    );
    const sourceBoundFeatureId = firstIdentifier(
      explicitFeatureId,
      candidateId,
      artifactId,
      sourceId,
    );
    const featureId = sourceBoundFeatureId
      || `renderer-local:${normalizedLayerId}:${Math.max(0, Number(ordinal) || 0)}`;
    const candidateOnly = item.candidate_only !== false;
    const runtimeSafetyTruth = item.runtime_safety_truth === true;
    const operational = item.operational === true;
    if (candidateOnly && runtimeSafetyTruth) {
      throw new Error("candidate_runtime_truth_conflict");
    }
    if (candidateOnly && operational) {
      throw new Error("candidate_operational_conflict");
    }
    const selectedEvidence = item.selected_evidence === true;
    return Object.freeze({
      source_id: sourceId,
      artifact_id: artifactId,
      candidate_id: candidateId,
      layer_id: normalizedLayerId,
      feature_id: featureId,
      identity_key: `${normalizedLayerId}:${featureId}`,
      identity_status: sourceBoundFeatureId ? "source_bound" : "renderer_local",
      geometry_ref: firstIdentifier(item.geometry_ref, item.geometryRef),
      candidate_only: candidateOnly,
      runtime_safety_truth: runtimeSafetyTruth,
      operational,
      selected_evidence: selectedEvidence,
      highlight_state: firstIdentifier(item.highlight_state)
        || (selectedEvidence ? "selected" : "default"),
    });
  }

  function normalizeRasterTileUrl(value, networkScope) {
    const template = String(value || "").trim();
    if (!template || template.length > 2048) {
      throw new Error("invalid_raster_tile_template");
    }
    if (!["{z}", "{x}", "{y}"].every(token => template.includes(token))) {
      throw new Error("invalid_raster_tile_template");
    }
    if (template.startsWith("/")) return template;
    if (!/^https?:\/\//i.test(template)) {
      throw new Error("unsupported_raster_tile_url");
    }
    if (networkScope === "explicit_remote") return template;
    const pageOrigin = String(global.location?.origin || "").trim();
    if (!pageOrigin || new URL(template).origin !== pageOrigin) {
      throw new Error("remote_raster_requires_explicit_scope");
    }
    return template;
  }

  function normalizeRasterImageUrl(value, networkScope) {
    const url = String(value || "").trim();
    if (!url || url.length > 2048) throw new Error("invalid_raster_image_url");
    if (url.startsWith("/")) return url;
    if (!/^https?:\/\//i.test(url)) throw new Error("unsupported_raster_image_url");
    if (networkScope === "explicit_remote") return url;
    const pageOrigin = String(global.location?.origin || "").trim();
    if (!pageOrigin || new URL(url).origin !== pageOrigin) {
      throw new Error("remote_raster_requires_explicit_scope");
    }
    return url;
  }

  function normalizeImageCoordinates(value) {
    if (!Array.isArray(value) || value.length !== 4) {
      throw new Error("invalid_raster_image_coordinates");
    }
    return Object.freeze(value.map(pair => {
      if (!Array.isArray(pair) || pair.length < 2) {
        throw new Error("invalid_raster_image_coordinates");
      }
      const lon = Number(pair[0]);
      const lat = Number(pair[1]);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)
        || lon < -180 || lon > 180 || lat < -90 || lat > 90) {
        throw new Error("invalid_raster_image_coordinates");
      }
      return Object.freeze([lon, lat]);
    }));
  }

  function normalizeRasterLayer(definition = {}, ordinal = 0) {
    const layerId = String(definition.layer_id || definition.layerId || "").trim();
    if (!RASTER_LAYER_ID_PATTERN.test(layerId)) {
      throw new Error("invalid_raster_layer_id");
    }
    const networkScope = String(
      definition.network_scope || definition.networkScope || "same_origin",
    ).trim();
    if (!RASTER_NETWORK_SCOPES.has(networkScope)) {
      throw new Error("invalid_raster_network_scope");
    }
    const candidateOnly = definition.candidate_only !== false;
    const runtimeSafetyTruth = definition.runtime_safety_truth === true;
    const operational = definition.operational === true;
    if (candidateOnly && runtimeSafetyTruth) {
      throw new Error("candidate_runtime_truth_conflict");
    }
    if (candidateOnly && operational) {
      throw new Error("candidate_operational_conflict");
    }
    if (runtimeSafetyTruth) throw new Error("raster_runtime_truth_forbidden");
    if (operational) throw new Error("raster_operational_forbidden");
    const sourceType = String(definition.source_type || definition.sourceType || "raster").trim();
    if (!["raster", "image"].includes(sourceType)) {
      throw new Error("invalid_raster_source_type");
    }
    const controlLayerId = String(
      definition.control_layer_id || definition.controlLayerId || layerId,
    ).trim();
    if (!RASTER_LAYER_ID_PATTERN.test(controlLayerId)) {
      throw new Error("invalid_raster_control_layer_id");
    }
    const rawTiles = sourceType === "raster" && Array.isArray(definition.tiles)
      ? definition.tiles
      : [];
    if (sourceType === "raster"
      && (!rawTiles.length || rawTiles.length > MAX_RASTER_TILE_TEMPLATES)) {
      throw new Error("invalid_raster_tile_count");
    }
    const imageUrl = sourceType === "image"
      ? normalizeRasterImageUrl(
        definition.image_url || definition.imageUrl || definition.url,
        networkScope,
      )
      : null;
    const imageCoordinates = sourceType === "image"
      ? normalizeImageCoordinates(definition.image_coordinates || definition.imageCoordinates)
      : null;
    const minzoom = Math.max(0, Math.min(24, Number(definition.minzoom) || 0));
    const maxzoom = Math.max(
      minzoom,
      Math.min(24, Number(definition.maxzoom) || 22),
    );
    const tileSize = Number(definition.tile_size || definition.tileSize) === 512 ? 512 : 256;
    const opacity = Math.max(0, Math.min(1, Number(definition.opacity ?? 1)));
    const renderPosition = String(
      definition.render_position || definition.renderPosition || "base",
    ).trim();
    if (!RASTER_RENDER_POSITIONS.has(renderPosition)) {
      throw new Error("invalid_raster_render_position");
    }
    return Object.freeze({
      layer_id: layerId,
      control_layer_id: controlLayerId,
      source_id: firstIdentifier(definition.source_id, definition.sourceId),
      map_source_id: `scout-raster-${layerId}`,
      map_layer_id: `scout-raster-layer-${layerId}`,
      source_type: sourceType,
      tiles: Object.freeze(rawTiles.map(value => normalizeRasterTileUrl(value, networkScope))),
      image_url: imageUrl,
      image_coordinates: imageCoordinates,
      tile_size: tileSize,
      minzoom,
      maxzoom,
      bounds: Array.isArray(definition.bounds) && definition.bounds.length === 4
        ? Object.freeze(definition.bounds.map(Number))
        : null,
      attribution: String(definition.attribution || "").slice(0, 500),
      opacity,
      visible: definition.visible !== false,
      render_position: renderPosition,
      network_scope: networkScope,
      candidate_only: candidateOnly,
      runtime_safety_truth: false,
      operational: false,
      visualization_only: true,
      adds_source_resolution: false,
      source_resolution: firstIdentifier(
        definition.source_resolution,
        definition.sourceResolution,
        definition.cell_resolution_m,
      ),
      artifact_hash: firstIdentifier(definition.artifact_hash, definition.sha256),
      ordinal: Math.max(0, Number(ordinal) || 0),
    });
  }

  function normalizeRasterLayers(definitions = []) {
    const seen = new Set();
    return Object.freeze((Array.isArray(definitions) ? definitions : []).map((definition, ordinal) => {
      const normalized = normalizeRasterLayer(definition, ordinal);
      if (seen.has(normalized.layer_id)) throw new Error("duplicate_raster_layer_id");
      seen.add(normalized.layer_id);
      return normalized;
    }));
  }

  function rasterSourceDefinition(layer) {
    return layer.source_type === "image"
      ? {
        type: "image",
        url: layer.image_url,
        coordinates: layer.image_coordinates.map(pair => [...pair]),
      }
      : {
        type: "raster",
        tiles: [...layer.tiles],
        tileSize: layer.tile_size,
        minzoom: layer.minzoom,
        maxzoom: layer.maxzoom,
        ...(layer.bounds ? {bounds: [...layer.bounds]} : {}),
        ...(layer.attribution ? {attribution: layer.attribution} : {}),
      };
  }

  function rasterStyleLayerDefinition(layer) {
    return {
      id: layer.map_layer_id,
      type: "raster",
      source: layer.map_source_id,
      layout: {visibility: layer.visible ? "visible" : "none"},
      paint: {
        "raster-opacity": layer.opacity,
        ...(layer.source_type === "image" ? {"raster-resampling": "nearest"} : {}),
      },
      metadata: {
        "scout:layer_id": layer.layer_id,
        "scout:control_layer_id": layer.control_layer_id,
        "scout:source_type": layer.source_type,
        "scout:render_position": layer.render_position,
        "scout:candidate_only": layer.candidate_only,
        "scout:runtime_safety_truth": false,
        "scout:visualization_only": true,
        "scout:adds_source_resolution": false,
        "scout:source_resolution": layer.source_resolution,
        "scout:artifact_hash": layer.artifact_hash,
      },
    };
  }

  function rasterLayersSignature(layers) {
    return JSON.stringify(layers.map(layer => ({
      layer_id: layer.layer_id,
      control_layer_id: layer.control_layer_id,
      source_id: layer.source_id,
      source_type: layer.source_type,
      tiles: [...layer.tiles],
      image_url: layer.image_url,
      image_coordinates: layer.image_coordinates,
      tile_size: layer.tile_size,
      minzoom: layer.minzoom,
      maxzoom: layer.maxzoom,
      bounds: layer.bounds,
      attribution: layer.attribution,
      opacity: layer.opacity,
      visible: layer.visible,
      render_position: layer.render_position,
      network_scope: layer.network_scope,
      source_resolution: layer.source_resolution,
      artifact_hash: layer.artifact_hash,
    })));
  }

  function rasterLayerEventPatch(current = {}, eventKind = "") {
    if (current?.visible !== true) return null;
    if (eventKind === "source_loaded") {
      // A settled source can still contain failed tiles. Retry/reconfiguration
      // clears errors; a later source event must not hide a missing detail tile.
      if (Number(current.error_count || 0) > 0) return null;
      return Object.freeze({state: "available", reason: "source_loaded"});
    }
    if (eventKind === "tile_error") {
      return Object.freeze({
        state: "degraded",
        reason: "tile_load_failed",
        error_count: Number(current?.error_count || 0) + 1,
      });
    }
    return null;
  }

  function createLayerOrderResult(renderer, layers, violations = [], gaps = []) {
    const groupedViolations = new Map();
    violations.forEach(violation => {
      const key = JSON.stringify([violation.code, violation.detail]);
      const previous = groupedViolations.get(key);
      groupedViolations.set(key, {...violation, occurrences: (previous?.occurrences || 0) + 1});
    });
    const uniqueViolations = [...groupedViolations.values()];
    const failed = uniqueViolations.some(violation => !String(violation?.code || "").startsWith("empty_"));
    return {
      status: failed ? "failed" : gaps.length || violations.length ? "warning" : "passed",
      renderer,
      layers,
      violations: uniqueViolations,
      gaps: [...new Set(gaps)],
    };
  }

  function layerOrderVisibleFromDom(node) {
    if (!node) return false;
    let current = node;
    while (current && String(current.tagName || "").toLowerCase() !== "svg") {
      const currentStyle = current.getAttribute?.("style") || "";
      if (current.hidden
        || current.dataset?.layerHidden === "true"
        || svgClassIncludes(current, "is-hidden")
        || /(^|;)\s*display\s*:\s*none\b/i.test(currentStyle)
        || /(^|;)\s*visibility\s*:\s*hidden\b/i.test(currentStyle)
        || /(^|;)\s*opacity\s*:\s*0(?:\.0+)?\s*(?:!important\s*)?(?:;|$)/i.test(currentStyle)) {
        return false;
      }
      current = current.parentElement;
    }
    const style = node.getAttribute?.("style") || "";
    return !/(^|;)\s*display\s*:\s*none\b/i.test(style)
      && !/(^|;)\s*visibility\s*:\s*hidden\b/i.test(style)
      && !/(^|;)\s*opacity\s*:\s*0(?:\.0+)?\s*(?:!important\s*)?(?:;|$)/i.test(style);
  }

  function svgElementHasPaintContent(node) {
    if (!node) return false;
    const tag = String(node.tagName || "").toLowerCase();
    if (["defs", "clipPath", "mask", "pattern", "metadata", "title", "desc"].includes(tag)) return false;
    if (tag === "image") {
      return Boolean(firstIdentifier(
        node.getAttribute?.("href"),
        node.getAttribute?.("xlink:href"),
      ));
    }
    if (tag === "path") return Boolean(String(node.getAttribute?.("d") || "").trim());
    if (["line", "polyline", "polygon", "circle", "ellipse", "rect"].includes(tag)) return true;
    if (tag === "text") return Boolean(String(node.textContent || "").trim());
    return false;
  }

  function svgDescendantHasPaintContent(node) {
    if (!node || !node.querySelectorAll) return svgElementHasPaintContent(node);
    if (svgElementHasPaintContent(node)) return true;
    return [...node.querySelectorAll("*")].some(svgElementHasPaintContent);
  }

  function svgDescendantHasVisiblePaintContent(node) {
    if (!node || !node.querySelectorAll) return svgElementHasPaintContent(node) && layerOrderVisibleFromDom(node);
    if (svgElementHasPaintContent(node) && layerOrderVisibleFromDom(node)) return true;
    return [...node.querySelectorAll("*")]
      .some(child => svgElementHasPaintContent(child) && layerOrderVisibleFromDom(child));
  }

  function svgClassIncludes(node, token) {
    const classes = String(node?.getAttribute?.("class") || "").split(/\s+/);
    return classes.includes(token);
  }

  function svgRoleOverride(node) {
    const role = String(node?.dataset?.mapOrderRole || "").trim().toLowerCase();
    return role || null;
  }

  function semanticDatasetValue(node, key, fallback) {
    if (!Object.prototype.hasOwnProperty.call(node?.dataset || {}, key)) return null;
    const value = String(node?.dataset?.[key] || "").trim();
    return value && value !== "true" ? value : fallback;
  }

  function svgSemanticLayerId(node) {
    return firstIdentifier(
      node?.dataset?.layerGroup,
      node?.dataset?.layer,
      node?.dataset?.mapLayer,
      node?.dataset?.mapTileSource,
      node?.dataset?.dashboardMapHintSource,
      semanticDatasetValue(node, "dashboardContextPoints", "dashboard-context-points"),
      node?.dataset?.paceCheckpointId,
      node?.dataset?.permissionMapAnchor,
      node?.dataset?.architectureNodeId,
      node?.dataset?.navigationNodeId,
      node?.dataset?.mapRenderKind,
      node?.getAttribute?.("id"),
      String(node?.tagName || "").toLowerCase(),
    );
  }

  function svgLayerRole(layerId, node) {
    const roleOverride = svgRoleOverride(node);
    if (roleOverride) return roleOverride;
    const id = String(layerId || "").toLowerCase();
    const tag = String(node?.tagName || "").toLowerCase();
    const kind = String(node?.dataset?.mapRenderKind || node?.dataset?.layerKind || "").toLowerCase();
    const hintSource = String(node?.dataset?.dashboardMapHintSource || "").toLowerCase();
    if (node?.hasAttribute?.("data-navigation-route-path")
      || node?.hasAttribute?.("data-navigation-route-halo")
      || node?.hasAttribute?.("data-navigation-terrain-3d-route")
      || id === "route-structure") return "route";
    if (hintSource.endsWith("-route-evidence")) return "route";
    if (node?.dataset?.dashboardContextPoints !== undefined
      || node?.dataset?.paceCheckpointId
      || node?.dataset?.permissionMapAnchor) {
      return "checkpoint";
    }
    if (svgClassIncludes(node, "route-structure")
      || svgClassIncludes(node, "navigation-route")
      || svgClassIncludes(node, "terrain-route")
      || svgClassIncludes(node, "terrain-route-reference")
      || svgClassIncludes(node, "terrain-retreat-arrow")
      || svgClassIncludes(node, "route-line")
      || svgClassIncludes(node, "retreat-line")
      || svgClassIncludes(node, "segment-overlay")) {
      return "route";
    }
    if (["route", "completed-track", "reference-tracks"].includes(id)) return "route";
    if (id === "segments") return "segment";
    if (["checkpoints", "mcp", "boss-points"].includes(id)) return "checkpoint";
    if (["pois", "hazards", "route-notes", "events"].includes(id)) return "evidence";
    if (tag === "image" || ["tile", "raster", "image"].includes(kind)
      || ["imagery", "rudy", "rudy-twmap", "relief", "geology", "topo-5k", "forest", "osm"].includes(id)) {
      return "background";
    }
    if (["terrain", "risk-heatmap", "risk-delta", "soil-moisture", "antecedent-rain", "cwa-qpf", "cwa-weather", "weather-api"].includes(id)) {
      // Classify painted geometry, never exempt an entire mixed group.
      if (tag === "path" && ["risk-heatmap", "risk-delta"].includes(id)
        && svgClassIncludes(node, id)
        && node?.getAttribute?.("data-risk-layer") === (id === "risk-heatmap" ? "calibrated" : "delta")) {
        return "evidence";
      }
      if (tag === "circle" && ["soil-moisture", "antecedent-rain", "cwa-qpf", "cwa-weather"].includes(id)
        && svgClassIncludes(node, `${id}-point`)) return "evidence";
      return "thematic-background";
    }
    if (["corridors", "overpass", "retreat", "risk-ribbon", "risk-score"].includes(id)) return "evidence";
    return "unknown";
  }

  function mergeLayerSummary(left, right) {
    return {
      id: left.id,
      role: left.role,
      visible: left.visible || right.visible,
      hasContent: left.hasContent || right.hasContent,
    };
  }

  function compactSvgOrderLayers(svg, paintLayers, exceptionIndexes = new Set()) {
    const topLevelGroups = svg?.querySelectorAll
      ? [...svg.querySelectorAll(":scope > [data-layer-group]")]
      : [];
    if (topLevelGroups.length) {
      const representedIds = new Set();
      const compact = topLevelGroups.map(node => {
        const id = node.dataset.layerGroup;
        representedIds.add(id);
        return {
          id,
          role: svgLayerRole(id, node),
          visible: svgDescendantHasVisiblePaintContent(node),
          hasContent: svgDescendantHasPaintContent(node),
        };
      });
      [...exceptionIndexes].forEach(index => {
        const layer = paintLayers[index];
        if (layer && !representedIds.has(layer.id)) compact.push({...layer});
      });
      return compact;
    }
    return paintLayers.reduce((compact, layer) => {
      const previous = compact[compact.length - 1];
      if (previous && previous.id === layer.id && previous.role === layer.role) {
        compact[compact.length - 1] = mergeLayerSummary(previous, layer);
      } else {
        compact.push({...layer});
      }
      return compact;
    }, []);
  }

  function collectSvgPaintLayers(svg) {
    const layers = [];
    const walk = node => {
      if (!node || ["defs", "clippath", "mask", "pattern"].includes(String(node.tagName || "").toLowerCase())) return;
      if (node !== svg && svgElementHasPaintContent(node)) {
        let id = svgSemanticLayerId(node);
        let role = svgLayerRole(id, node);
        const marker = node.closest?.("[data-dashboard-context-points], [data-pace-checkpoint-id], [data-permission-map-anchor], [data-navigation-terrain-3d-saddle], [data-terrain-feature]");
        const group = node.closest?.("[data-layer-group]");
        if (role === "unknown" && marker) {
          id = svgSemanticLayerId(marker);
          role = "checkpoint";
        } else if (role === "unknown" && group) {
          id = group.dataset.layerGroup;
          role = svgLayerRole(id, node);
        } else if (group && id === String(node.tagName || "").toLowerCase()) {
          id = `${group.dataset.layerGroup}:${id}`;
        }
        layers.push({
          id,
          role,
          visible: layerOrderVisibleFromDom(node),
          hasContent: true,
        });
      }
      [...(node.children || [])].forEach(walk);
    };
    walk(svg);
    return layers;
  }

  function normalizeExpectedLayerOrder(expectedLayerOrder) {
    return expectedLayerOrder
      .map(entry => Array.isArray(entry) ? entry.map(String) : [String(entry)])
      .filter(group => group.some(Boolean));
  }

  function expectedLayerRankMap(expectedLayerOrder) {
    const rankMap = new Map();
    normalizeExpectedLayerOrder(expectedLayerOrder).forEach((group, rank) => {
      group.forEach(layerId => rankMap.set(layerId, rank));
    });
    return rankMap;
  }

  function inspectExpectedSvgGroupOrder(svg, expectedLayerOrder, violations) {
    if (!expectedLayerOrder.length || !svg?.querySelectorAll) return;
    const groupOrder = [...svg.querySelectorAll(":scope > [data-layer-group]")]
      .map(node => node.dataset.layerGroup);
    const rankMap = expectedLayerRankMap(expectedLayerOrder);
    groupOrder.forEach((layerId, observedIndex) => {
      const leftRank = rankMap.get(layerId);
      if (!Number.isInteger(leftRank)) return;
      groupOrder.slice(observedIndex + 1).forEach(laterId => {
        const rightRank = rankMap.get(laterId);
        if (!Number.isInteger(rightRank) || leftRank <= rightRank) return;
        violations.push({
          code: "expected_layer_order_inversion",
          detail: `${layerId} is painted below ${laterId}, but the layer contract requires it above.`,
        });
      });
    });
  }

  function inspectSvgLayerOrder(svg, options = {}) {
    const requiredLayerIds = Array.isArray(options.requiredLayerIds) ? options.requiredLayerIds.map(String) : [];
    const expectedLayerOrder = Array.isArray(options.expectedLayerOrder) ? options.expectedLayerOrder : [];
    const requireRoute = options.requireRoute !== false;
    const violations = [];
    const gaps = [];
    if (!svg || String(svg.tagName || "").toLowerCase() !== "svg") {
      return createLayerOrderResult("svg", [], [], ["no SVG element supplied"]);
    }
    const paintLayers = collectSvgPaintLayers(svg);
    if (!paintLayers.length) gaps.push("SVG contains no painted layer content");
    if (!requireRoute && ![...svg.querySelectorAll("path,polyline,polygon,line,circle,ellipse")]
      .some(node => !node.closest("defs,clipPath,mask,pattern") && svgElementHasPaintContent(node))) {
      gaps.push("SVG contains no route, terrain, or point geometry to verify");
    }
    const topLevelGroups = svg.querySelectorAll
      ? [...svg.querySelectorAll(":scope > [data-layer-group]")]
      : [];
    const groupIds = topLevelGroups.map(node => node.dataset.layerGroup);
    topLevelGroups.filter(node => layerOrderVisibleFromDom(node) && !svgDescendantHasVisiblePaintContent(node))
      .forEach(node => gaps.push(`${node.dataset.layerGroup} has no rendered content`));
    requiredLayerIds.forEach(layerId => {
      if (!groupIds.includes(layerId)) {
        violations.push({code: "missing_required_layer", detail: `${layerId} is missing.`});
      }
    });
    [...new Set(groupIds)].forEach(layerId => {
      if (groupIds.filter(id => id === layerId).length > 1) {
        violations.push({code: "duplicate_layer_group", detail: `${layerId} appears more than once.`});
      }
    });
    inspectExpectedSvgGroupOrder(svg, expectedLayerOrder, violations);
    paintLayers.filter(layer => layer.visible && !layer.hasContent).forEach(layer => {
      gaps.push(`${layer.id} has no rendered content`);
    });
    const routeIndexes = paintLayers
      .map((layer, index) => ["route", "segment"].includes(layer.role) ? index : -1)
      .filter(index => index >= 0);
    if (requireRoute && !routeIndexes.length) gaps.push("route or segment layer is missing or empty");
    const checkpointIndexes = paintLayers
      .map((layer, index) => layer.role === "checkpoint" ? index : -1)
      .filter(index => index >= 0);
    const backgroundIndexes = paintLayers
      .map((layer, index) => ["background", "thematic-background"].includes(layer.role) ? index : -1)
      .filter(index => index >= 0);
    const exceptionIndexes = new Set();
    if (routeIndexes.length) {
      const firstRoute = Math.min(...routeIndexes);
      backgroundIndexes
        .filter(index => index > firstRoute)
        .forEach(index => {
          exceptionIndexes.add(index);
          violations.push({
            code: "background_over_route",
            detail: `${paintLayers[index].id} is painted above a route or segment layer.`,
          });
        });
    }
    if (routeIndexes.length && checkpointIndexes.length) {
      const lastRoute = Math.max(...routeIndexes);
      checkpointIndexes
        .filter(index => index < lastRoute)
        .forEach(index => {
          exceptionIndexes.add(index);
          violations.push({
            code: "route_over_checkpoint_anchor",
            detail: `${paintLayers[index].id} is painted below a later route or segment layer.`,
          });
        });
    }
    const layers = compactSvgOrderLayers(svg, paintLayers, exceptionIndexes);
    return createLayerOrderResult("svg", layers, violations, gaps);
  }

  function mapLibreStyleFromMapOrStyle(mapOrStyle) {
    if (mapOrStyle?.getStyle && typeof mapOrStyle.getStyle === "function") {
      try {
        return mapOrStyle.getStyle();
      } catch (error) {
        return {__scoutOrderInspectorGap: `getStyle failed: ${String(error?.message || error || "unknown error")}`};
      }
    }
    return mapOrStyle && typeof mapOrStyle === "object" ? mapOrStyle : null;
  }

  function mapLibreLayerRole(layer) {
    const id = String(layer?.id || "").toLowerCase();
    const source = String(layer?.source || "").toLowerCase();
    const type = String(layer?.type || "").toLowerCase();
    if (layer?.type === "raster" || layer?.type === "hillshade" || id.includes("raster") || id.includes("hillshade")) {
      return "background";
    }
    if (id === EVIDENCE_LAYER_IDS.osmLine || id === EVIDENCE_LAYER_IDS.osmLineCasing) return "osm-basemap";
    if (type === "line" && (id === EVIDENCE_LAYER_IDS.line || /(^|[-_])(route|track|segment)([-_]|$)/.test(id))) return "route";
    if (["circle", "symbol"].includes(type)
      && (id === EVIDENCE_LAYER_IDS.point || /(^|[-_])(checkpoint|cp|anchor|poi|hazard|boss|mcp|event)([-_]|$)/.test(id))) {
      return "checkpoint";
    }
    if (source === EVIDENCE_SOURCE_ID) return "evidence";
    return "unknown";
  }

  function mapLibreLayerVisible(layer) {
    return layer?.layout?.visibility !== "none";
  }

  function mapLibreSourceHasGeometry(style, sourceId, role) {
    const source = style?.sources?.[sourceId];
    const data = source?.data;
    const features = Array.isArray(data?.features) ? data.features : [];
    if (!features.length) return false;
    if (role === "route") {
      return features.some(feature => ["LineString", "MultiLineString"].includes(feature?.geometry?.type)
        && String(feature?.properties?.layer_id || "").toLowerCase() !== "osm");
    }
    if (role === "checkpoint") {
      return features.some(feature => feature?.geometry?.type === "Point"
        && String(feature?.properties?.layer_id || "").toLowerCase() !== "osm");
    }
    return true;
  }

  function inspectMapLibreLayerOrder(mapOrStyle, options = {}) {
    const requireRoute = options.requireRoute !== false;
    const style = mapLibreStyleFromMapOrStyle(mapOrStyle);
    const violations = [];
    const gaps = [];
    if (style?.__scoutOrderInspectorGap) {
      return createLayerOrderResult("maplibre", [], [], [style.__scoutOrderInspectorGap]);
    }
    if (!style || !Array.isArray(style.layers)) {
      return createLayerOrderResult("maplibre", [], [], ["empty or missing MapLibre style"]);
    }
    style.layers
      .map(layer => String(layer?.id || ""))
      .filter(Boolean)
      .filter((id, index, ids) => ids.indexOf(id) !== index)
      .filter((id, index, ids) => ids.indexOf(id) === index)
      .forEach(id => violations.push({
        code: "duplicate_style_layer_id",
        detail: `${id} appears more than once.`,
      }));
    const layers = style.layers.map(layer => {
      const role = mapLibreLayerRole(layer);
      return {
        id: String(layer?.id || ""),
        role,
        visible: mapLibreLayerVisible(layer),
        hasContent: role === "background"
          ? Boolean(style.sources?.[layer.source])
          : mapLibreSourceHasGeometry(style, layer.source, role),
      };
    });
    if (!layers.length) gaps.push("MapLibre style contains no layers");
    const routeIndexes = layers
      .map((layer, index) => layer.role === "route" ? index : -1)
      .filter(index => index >= 0);
    const checkpointIndexes = layers
      .map((layer, index) => layer.role === "checkpoint" ? index : -1)
      .filter(index => index >= 0);
    const backgroundIndexes = layers
      .map((layer, index) => layer.role === "background" ? index : -1)
      .filter(index => index >= 0);
    if (requireRoute && !routeIndexes.length) gaps.push("route layer is missing");
    if (requireRoute && routeIndexes.length && !routeIndexes.some(index => layers[index].hasContent)) {
      gaps.push("route layer has no non-OSM source geometry");
    }
    layers.filter(layer => layer.visible && !layer.hasContent && layer.role !== "unknown" && layer.role !== "osm-basemap")
      .forEach(layer => gaps.push(`${layer.id} has no source geometry or raster source`));
    if (routeIndexes.length) {
      const firstRoute = Math.min(...routeIndexes);
      backgroundIndexes
        .filter(index => index > firstRoute)
        .forEach(index => violations.push({
          code: "background_over_route",
          detail: `${layers[index].id} is above a protected route layer.`,
        }));
    }
    if (routeIndexes.length && checkpointIndexes.length) {
      const lastRoute = Math.max(...routeIndexes);
      checkpointIndexes
        .filter(index => index < lastRoute)
        .forEach(index => violations.push({
          code: "route_over_checkpoint_anchor",
          detail: `${layers[index].id} is below a later protected route layer.`,
        }));
    }
    return createLayerOrderResult("maplibre", layers, violations, gaps);
  }

  function buildEvidenceIndex(features = []) {
    const featureById = new Map();
    const featureIdsByRef = new Map();
    function indexRef(value, featureId) {
      const ref = firstIdentifier(value);
      if (!ref) return;
      const existing = featureIdsByRef.get(ref) || new Set();
      existing.add(featureId);
      featureIdsByRef.set(ref, existing);
    }
    for (const feature of Array.isArray(features) ? features : []) {
      const properties = feature?.properties || {};
      const featureId = firstIdentifier(feature?.id, properties.feature_id);
      if (!featureId || featureById.has(featureId)) continue;
      featureById.set(featureId, feature);
      [
        featureId,
        properties.identity_key,
        properties.source_id,
        properties.artifact_id,
        properties.candidate_id,
        properties.event_id,
        properties.checkpoint_id,
        properties.segment_id,
        properties.mcp_id,
        properties.boss_point_id,
        properties.nearby_group_id,
        properties.map_refs,
        properties.map_target_ids,
        properties.target_ids,
      ].flatMap(value => Array.isArray(value) ? value : [value]).forEach(ref => (
        indexRef(ref, featureId)
      ));
    }
    return Object.freeze({
      size: featureById.size,
      resolve(ref) {
        return [...(featureIdsByRef.get(String(ref || "")) || [])];
      },
      feature(featureId) {
        return featureById.get(String(featureId || "")) || null;
      },
    });
  }

  function geometryCoordinatePairs(value, pairs = []) {
    if (!Array.isArray(value)) return pairs;
    if (
      value.length >= 2
      && Number.isFinite(Number(value[0]))
      && Number.isFinite(Number(value[1]))
    ) {
      const lon = Number(value[0]);
      const lat = Number(value[1]);
      if (lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90) {
        pairs.push([lon, lat]);
      }
      return pairs;
    }
    value.forEach(child => geometryCoordinatePairs(child, pairs));
    return pairs;
  }

  function normalizeGeometry(geometry) {
    const supportedTypes = new Set([
      "Point",
      "MultiPoint",
      "LineString",
      "MultiLineString",
      "Polygon",
      "MultiPolygon",
    ]);
    const geometryType = String(geometry?.type || "Unknown");
    if (!supportedTypes.has(geometryType)) {
      throw new Error(`unsupported_geometry_type:${geometryType}`);
    }
    const pairs = geometryCoordinatePairs(geometry.coordinates);
    if (!pairs.length) throw new Error("invalid_geometry_coordinates");
    return Object.freeze({
      type: geometryType,
      coordinates: JSON.parse(JSON.stringify(geometry.coordinates)),
    });
  }

  function geometryBounds(geometry) {
    const pairs = geometryCoordinatePairs(geometry?.coordinates);
    if (!pairs.length) return null;
    const longitudes = pairs.map(pair => pair[0]);
    const latitudes = pairs.map(pair => pair[1]);
    return Object.freeze([
      Math.min(...longitudes),
      Math.min(...latitudes),
      Math.max(...longitudes),
      Math.max(...latitudes),
    ]);
  }

  function createEvidenceFeature(
    item = {},
    {layerId = "", ordinal = 0, geometry = null, properties = {}} = {},
  ) {
    const identity = normalizeEvidenceIdentity(item, {layerId, ordinal});
    const normalizedGeometry = normalizeGeometry(geometry);
    const bbox = geometryBounds(normalizedGeometry);
    return Object.freeze({
      type: "Feature",
      id: identity.identity_key,
      bbox,
      geometry: normalizedGeometry,
      properties: Object.freeze({
        ...properties,
        ...identity,
        bbox_wgs84: bbox,
        _scout_visible: true,
      }),
    });
  }

  function createEvidenceFeatureCollection(features = []) {
    const normalizedFeatures = (Array.isArray(features) ? features : []).filter(feature => (
      feature?.type === "Feature"
      && feature?.geometry
      && firstIdentifier(feature?.id, feature?.properties?.feature_id)
    ));
    return Object.freeze({
      type: "FeatureCollection",
      features: Object.freeze([...normalizedFeatures]),
    });
  }

  function evidenceLayerColorExpression() {
    return [
      "match",
      ["get", "layer_id"],
      "route", "#146b7a",
      "reference-tracks", "#8b6914",
      "retreat", "#76513a",
      "segments", "#cf7b18",
      "risk-ribbon", "#c23b32",
      "risk-heatmap", "#d24f35",
      "risk-delta", "#9b3f72",
      "hazards", "#a83232",
      "checkpoints", "#ad2f45",
      "mcp", "#146c57",
      "boss-points", "#684b9a",
      "qgis-candidate", "#66589a",
      "qgis-route", "#e00067",
      "qgis-slope", "#247d78",
      "qgis-ridge-lines", "#ffb000",
      "qgis-valley-lines", "#38a7c7",
      "qgis-stream-network", "#1769aa",
      "#3e6077",
    ];
  }

  function osmFillColorExpression() {
    return [
      "match",
      ["get", "osm_style_category"],
      "forest", "#add19e",
      "park", "#c8facc",
      "grass", "#cdebb0",
      "farmland", "#eef0d5",
      "residential", "#e0dfdf",
      "building", "#d9d0c9",
      "water", "#aad3df",
      "glacier", "#ddecec",
      "terrain", "#e7dfd2",
      "#eeeece",
    ];
  }

  function osmFillOutlineColorExpression() {
    return [
      "match",
      ["get", "osm_style_category"],
      "building", "#b8ada6",
      "water", "#4d80b3",
      "rgba(110,114,102,0.46)",
    ];
  }

  function osmLineCasingColorExpression() {
    return [
      "match",
      ["get", "osm_style_category"],
      "path", "#ffffff",
      "footway", "#ffffff",
      "steps", "#ffffff",
      "track", "#8d6f38",
      "motorway", "#dc2a67",
      "waterway", "rgba(255,255,255,0.86)",
      "terrain", "rgba(255,255,255,0.76)",
      "infrastructure", "rgba(255,255,255,0.82)",
      "#b9a16f",
    ];
  }

  function osmLineCoreColorExpression() {
    return [
      "match",
      ["get", "osm_style_category"],
      "path", "#b47d46",
      "footway", "#cf5f70",
      "steps", "#9e7048",
      "track", "#996600",
      "service", "#ffffff",
      "motorway", "#e892a2",
      "trunk", "#f9b29c",
      "primary", "#fcd6a4",
      "secondary", "#f7fabf",
      "tertiary", "#ffffff",
      "unclassified", "#ffffff",
      "residential", "#ffffff",
      "road", "#ffffff",
      "route", "#7b8f2a",
      "waterway", "#4d80b3",
      "terrain", "#9c8d78",
      "infrastructure", "#8a8f99",
      "#a36b2c",
    ];
  }

  function osmLineCasingWidthExpression() {
    return [
      "match",
      ["get", "osm_style_category"],
      "motorway", 6.6,
      "trunk", 6.2,
      "primary", 5.9,
      "secondary", 5.5,
      "tertiary", 5.1,
      "unclassified", 5.1,
      "residential", 5.1,
      "road", 5.3,
      "track", 4.8,
      "service", 4.5,
      "path", 3.8,
      "footway", 3.8,
      "steps", 3.8,
      2.8,
    ];
  }

  function osmLineCoreWidthExpression() {
    return [
      "match",
      ["get", "osm_style_category"],
      "motorway", 4.1,
      "trunk", 3.8,
      "primary", 3.5,
      "secondary", 3.2,
      "tertiary", 3,
      "unclassified", 3,
      "residential", 3,
      "road", 3.1,
      "track", 2.5,
      "service", 2.5,
      "path", 1.55,
      "footway", 1.45,
      "steps", 1.55,
      "route", 1.55,
      "waterway", 1.35,
      1.15,
    ];
  }

  function osmPointColorExpression() {
    return [
      "match",
      ["get", "osm_style_category"],
      "milestone", "#8c6a21",
      "mobile", "#0077b6",
      "peak", "#a46020",
      "shelter", "#6d5e3a",
      "parking", "#3f78b5",
      "water", "#2f90c8",
      "#5a5f63",
    ];
  }

  function createEvidenceStyle(
    featureCollection = createEvidenceFeatureCollection(),
    {rasterLayers = []} = {},
  ) {
    const data = featureCollection?.type === "FeatureCollection"
      ? featureCollection
      : createEvidenceFeatureCollection();
    const normalizedRasterLayers = normalizeRasterLayers(rasterLayers);
    const rasterSources = Object.fromEntries(normalizedRasterLayers.map(layer => [
      layer.map_source_id,
      rasterSourceDefinition(layer),
    ]));
    const baseRasterStyleLayers = normalizedRasterLayers
      .filter(layer => layer.render_position === "base")
      .map(rasterStyleLayerDefinition);
    const overlayRasterStyleLayers = normalizedRasterLayers
      .filter(layer => layer.render_position === "overlay")
      .map(rasterStyleLayerDefinition);
    const visibleFilter = ["==", ["get", "_scout_visible"], true];
    const osmVisibleFilter = [
      "all",
      visibleFilter,
      ["==", ["get", "layer_id"], "osm"],
    ];
    const evidenceVisibleFilter = [
      "all",
      visibleFilter,
      ["!=", ["get", "layer_id"], "osm"],
    ];
    return {
      version: 8,
      sources: {
        ...rasterSources,
        [EVIDENCE_SOURCE_ID]: {
          type: "geojson",
          data,
        },
      },
      layers: [
        {
          id: EVIDENCE_LAYER_IDS.background,
          type: "background",
          paint: {"background-color": "#e8eef2"},
        },
        ...baseRasterStyleLayers,
        {
          id: EVIDENCE_LAYER_IDS.osmFill,
          type: "fill",
          source: EVIDENCE_SOURCE_ID,
          filter: ["all", osmVisibleFilter, ["==", ["geometry-type"], "Polygon"]],
          paint: {
            "fill-color": osmFillColorExpression(),
            "fill-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.82, 0.68],
            "fill-outline-color": osmFillOutlineColorExpression(),
          },
        },
        {
          id: EVIDENCE_LAYER_IDS.osmLineCasing,
          type: "line",
          source: EVIDENCE_SOURCE_ID,
          filter: ["all", osmVisibleFilter, ["==", ["geometry-type"], "LineString"]],
          layout: {"line-cap": "round", "line-join": "round"},
          paint: {
            "line-color": osmLineCasingColorExpression(),
            "line-width": osmLineCasingWidthExpression(),
            "line-opacity": 0.92,
          },
        },
        {
          id: EVIDENCE_LAYER_IDS.osmLine,
          type: "line",
          source: EVIDENCE_SOURCE_ID,
          filter: ["all", osmVisibleFilter, ["==", ["geometry-type"], "LineString"]],
          layout: {"line-cap": "round", "line-join": "round"},
          paint: {
            "line-color": osmLineCoreColorExpression(),
            "line-width": osmLineCoreWidthExpression(),
            "line-opacity": 0.96,
          },
        },
        {
          id: EVIDENCE_LAYER_IDS.osmPoint,
          type: "circle",
          source: EVIDENCE_SOURCE_ID,
          filter: ["all", osmVisibleFilter, ["==", ["geometry-type"], "Point"]],
          paint: {
            "circle-color": osmPointColorExpression(),
            "circle-radius": ["case", ["boolean", ["feature-state", "selected"], false], 7, 3.2],
            "circle-stroke-color": "rgba(255,255,255,0.94)",
            "circle-stroke-width": 1,
            "circle-opacity": 0.86,
          },
        },
        {
          id: EVIDENCE_LAYER_IDS.fill,
          type: "fill",
          source: EVIDENCE_SOURCE_ID,
          filter: [
            "all",
            evidenceVisibleFilter,
            ["==", ["geometry-type"], "Polygon"],
            ["!=", ["get", "render_position"], "overlay"],
          ],
          paint: {
            "fill-color": evidenceLayerColorExpression(),
            "fill-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.5, 0.24],
            "fill-outline-color": "#263746",
          },
        },
        ...overlayRasterStyleLayers,
        {
          id: EVIDENCE_LAYER_IDS.line,
          type: "line",
          source: EVIDENCE_SOURCE_ID,
          filter: ["all", evidenceVisibleFilter, ["==", ["geometry-type"], "LineString"]],
          layout: {"line-cap": "round", "line-join": "round"},
          paint: {
            "line-color": evidenceLayerColorExpression(),
            "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 8, 4],
            "line-opacity": 0.94,
          },
        },
        {
          id: EVIDENCE_LAYER_IDS.point,
          type: "circle",
          source: EVIDENCE_SOURCE_ID,
          filter: ["all", evidenceVisibleFilter, ["==", ["geometry-type"], "Point"]],
          paint: {
            "circle-color": evidenceLayerColorExpression(),
            "circle-radius": ["case", ["boolean", ["feature-state", "selected"], false], 10, 6],
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": ["case", ["boolean", ["feature-state", "selected"], false], 3, 1.5],
            "circle-opacity": 0.95,
          },
        },
        {
          id: EVIDENCE_LAYER_IDS.overlayFill,
          type: "fill",
          source: EVIDENCE_SOURCE_ID,
          filter: [
            "all",
            evidenceVisibleFilter,
            ["==", ["geometry-type"], "Polygon"],
            ["==", ["get", "render_position"], "overlay"],
          ],
          paint: {
            "fill-color": ["coalesce", ["get", "render_color"], "#00a8f3"],
            "fill-opacity": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              0.72,
              ["coalesce", ["get", "render_opacity"], 0.5],
            ],
            "fill-outline-color": "rgba(255,255,255,0.48)",
          },
        },
      ],
    };
  }

  function featureCollectionBounds(featureCollection) {
    const bounds = (featureCollection?.features || [])
      .map(feature => feature?.bbox || geometryBounds(feature?.geometry))
      .filter(candidate => Array.isArray(candidate) && candidate.length === 4);
    if (!bounds.length) return null;
    return Object.freeze([
      Math.min(...bounds.map(candidate => Number(candidate[0]))),
      Math.min(...bounds.map(candidate => Number(candidate[1]))),
      Math.max(...bounds.map(candidate => Number(candidate[2]))),
      Math.max(...bounds.map(candidate => Number(candidate[3]))),
    ]);
  }

  function waitForMapLoad(map, timeoutMs = 15000) {
    if (map.loaded?.()) return Promise.resolve();
    return new Promise((resolve, reject) => {
      let settled = false;
      let timer = null;
      const finish = callback => value => {
        if (settled) return;
        settled = true;
        global.clearTimeout(timer);
        callback(value);
      };
      const complete = finish(resolve);
      const fail = finish(reject);
      timer = global.setTimeout(
        () => fail(new Error("maplibre_initialization_timeout")),
        Math.max(1000, Number(timeoutMs) || 15000),
      );
      map.once("load", complete);
    });
  }

  function rasterTileCoverage(layer, map) {
    const bounds = map?.getBounds?.();
    const zoom = Number(map?.getZoom?.());
    if (!bounds || !Number.isFinite(zoom)) return null;
    // RasterTileSource.roundZoom is true in MapLibre 6.2; its map tile size is 512.
    const z = Math.max(Math.ceil(layer.minzoom), Math.min(Math.floor(layer.maxzoom),
      Math.round(zoom + Math.log2(512 / layer.tile_size))));
    const size = 2 ** z;
    const rangeFor = ([west, south, east, north]) => {
      if (![west, south, east, north].every(Number.isFinite) || south > north) return null;
      if (east < west) east += 360;
      const y = latitude => {
        const radians = Math.max(-85.05112878, Math.min(85.05112878, latitude)) * Math.PI / 180;
        return size * (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2;
      };
      const xMin = Math.floor(size * (west + 180) / 360);
      const xMax = Math.max(xMin, Math.ceil(size * (east + 180) / 360) - 1);
      const wrap = value => ((value % size) + size) % size;
      const xs = xMax - xMin + 1 >= size ? [[0, size - 1]]
        : wrap(xMin) <= wrap(xMax) ? [[wrap(xMin), wrap(xMax)]]
          : [[0, wrap(xMax)], [wrap(xMin), size - 1]];
      return {xs, yMin: Math.max(0, Math.floor(y(north))),
        yMax: Math.min(size - 1, Math.max(Math.floor(y(north)), Math.ceil(y(south)) - 1))};
    };
    let range = rangeFor([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]);
    if (!range) return null;
    if (layer.bounds) {
      const source = rangeFor(layer.bounds);
      if (!source) return null;
      range = {
        xs: range.xs.flatMap(viewX => source.xs.map(sourceX => [
          Math.max(viewX[0], sourceX[0]), Math.min(viewX[1], sourceX[1]),
        ]).filter(([min, max]) => min <= max)),
        yMin: Math.max(range.yMin, source.yMin), yMax: Math.min(range.yMax, source.yMax),
      };
    }
    const count = range.xs.reduce((sum, [min, max]) => sum + max - min + 1, 0)
      * Math.max(0, range.yMax - range.yMin + 1);
    return {z, count, key: JSON.stringify([z, range.xs, range.yMin, range.yMax]),
      contains: tile => tile.z === z && tile.y >= range.yMin && tile.y <= range.yMax
        && range.xs.some(([min, max]) => tile.x >= min && tile.x <= max)};
  }

  class RasterTileTransport {
    constructor({maplibregl, getMap, onState, container}) {
      this.maplibregl = maplibregl;
      this.getMap = getMap;
      this.onState = onState;
      this.container = container;
      this.protocol = `scout-raster-${++rasterProtocolSequence}`;
      this.revision = 0;
      this.requestSequence = 0;
      this.layers = new Map();
      this.records = new Map();
      this.controllers = new Set();
      this.viewErrors = new Map();
      this.destroyed = false;
      this.enabled = typeof maplibregl.addProtocol === "function"
        && typeof maplibregl.removeProtocol === "function" && typeof global.fetch === "function";
      if (this.enabled) maplibregl.addProtocol(this.protocol, (request, controller) => this.load(request, controller));
      container.dataset.maplibreRasterTransport = this.enabled ? "same-origin-protocol" : "event-only";
    }

    configure(layers) {
      this.revision += 1;
      this.controllers.forEach(controller => controller.abort());
      this.controllers.clear();
      this.records.clear();
      this.viewErrors.clear();
      this.layers.clear();
      const origin = String(global.location?.origin || "");
      layers.forEach(layer => {
        if (layer.source_type !== "raster" || !origin) return;
        try {
          const templates = layer.tiles.map(template => new URL(template, origin));
          if (!templates.every(url => url.origin === origin && !url.username && !url.password
            && !/\{(?!z\}|x\}|y\})/.test(decodeURI(url.href)))) return;
          this.layers.set(layer.layer_id, {layer, visible: layer.visible,
            templates: layer.tiles.map(template => new URL(template, origin).href
              .replace(/%7B([zxy])%7D/gi, "{$1}"))});
        } catch (_error) { /* Unsupported sources retain their existing public loader. */ }
      });
    }

    sourceDefinition(layer) {
      const source = rasterSourceDefinition(layer);
      if (!this.enabled || !this.layers.has(layer.layer_id)) return source;
      source.tiles = layer.tiles.map((_template, index) => (
        `${this.protocol}://${this.revision}/${layer.layer_id}/${index}/{z}/{x}/{y}`
      ));
      return source;
    }

    handles(layerId) {
      return !this.destroyed && this.layers.has(layerId);
    }

    publish(layerId) {
      const entry = this.layers.get(layerId);
      if (this.destroyed || !entry) return;
      const coverage = rasterTileCoverage(entry.layer, this.getMap());
      const records = [...this.records.values()].filter(record => record.layerId === layerId && coverage?.contains(record));
      const errors = records.filter(record => record.state === "error");
      const pending = records.filter(record => record.state === "pending").length;
      const successes = records.filter(record => record.state === "success").length;
      const viewError = this.viewErrors.get(layerId)?.key === coverage?.key;
      const missing = Math.max(0, Number(coverage?.count || 0) - successes - pending - errors.length);
      let settled = false;
      try { settled = this.getMap()?.isSourceLoaded?.(entry.layer.map_source_id) === true; } catch (_error) { /* Source removal. */ }
      const state = !entry.visible ? "hidden" : !this.enabled || errors.length || viewError ? "degraded"
        : !coverage ? "loading" : !coverage.count ? "configured"
          : settled && !pending ? missing ? "degraded" : "available" : "loading";
      const reason = !entry.visible ? "layer_hidden" : !this.enabled ? "tile_transport_unavailable"
        : errors.length ? "native_tile_http_error" : viewError ? "tile_decode_failed"
          : !coverage ? "viewport_pending" : !coverage.count ? "outside_source_bounds"
            : state === "available" ? "native_tiles_loaded" : state === "degraded" ? "native_tiles_unverified" : "tiles_loading";
      this.onState(layerId, {state, reason, visible: entry.visible, error_count: errors.length + Number(viewError),
        pending_count: pending, success_count: successes, unverified_count: missing,
        required_count: coverage?.count || 0, required_tile_count: coverage?.count || 0,
        native_zoom: coverage?.z ?? null, verified_native_zoom: state === "available" ? coverage.z : null,
        last_http_status: errors.at(-1)?.status || null, transport_revision: this.revision,
        transport: this.enabled ? "same-origin-protocol" : "unavailable"});
    }

    publishAll() {
      this.layers.forEach((_entry, layerId) => this.publish(layerId));
    }

    setVisibility(layerId, visible) {
      const entry = this.layers.get(layerId);
      if (!entry) return;
      entry.visible = Boolean(visible);
      this.publish(layerId);
    }

    recordMapError(layerId) {
      const entry = this.layers.get(layerId);
      if (!entry) return;
      const coverage = rasterTileCoverage(entry.layer, this.getMap());
      this.viewErrors.set(layerId, {key: coverage?.key});
      this.publish(layerId);
    }

    async load(request, controller) {
      const abortError = () => Object.assign(new Error("Raster request cancelled"), {name: "AbortError"});
      const match = String(request.url).match(new RegExp(`^${this.protocol}://(\\d+)/([a-z0-9._-]+)/(\\d+)/(\\d+)/(\\d+)/(\\d+)$`));
      const entry = match && this.layers.get(match[2]);
      if (this.destroyed || !entry || Number(match[1]) !== this.revision || controller.signal.aborted) throw abortError();
      const [index, z, x, y] = match.slice(3).map(Number);
      const template = entry.templates[index];
      if (!template || z < Math.floor(entry.layer.minzoom) || z > Math.ceil(entry.layer.maxzoom)
        || x >= 2 ** z || y >= 2 ** z) throw new Error("invalid_raster_protocol_tile");
      const url = new URL(template.replaceAll("{z}", String(z)).replaceAll("{x}", String(x)).replaceAll("{y}", String(y)));
      if (url.origin !== global.location.origin || url.username || url.password) throw new Error("invalid_raster_protocol_origin");
      const revision = this.revision;
      const key = `${match[2]}:${z}/${x}/${y}`;
      const previous = this.records.get(key);
      const record = {layerId: match[2], z, x, y, state: "pending", status: null, attempt: ++this.requestSequence};
      const current = () => !this.destroyed && revision === this.revision && this.records.get(key) === record;
      this.records.set(key, record);
      this.viewErrors.delete(record.layerId);
      this.controllers.add(controller);
      this.publish(record.layerId);
      try {
        const response = await global.fetch(url.href, {signal: controller.signal, credentials: "same-origin",
          redirect: "error", headers: {Accept: "image/webp,*/*"}});
        if (controller.signal.aborted) throw abortError();
        record.status = response.status;
        if (!response.ok) throw Object.assign(new Error(`Raster tile HTTP ${response.status}`), {status: response.status});
        const data = await response.arrayBuffer();
        if (controller.signal.aborted) throw abortError();
        if (current()) record.state = "success";
        return {data, cacheControl: response.headers.get("Cache-Control"), expires: response.headers.get("Expires")};
      } catch (error) {
        if (current()) {
          if (controller.signal.aborted || error?.name === "AbortError") {
            if (previous && previous.state !== "pending") this.records.set(key, previous);
            else this.records.delete(key);
          } else record.state = "error";
        }
        // MapLibre may suppress HTTP 404 events; HTTP status is already recorded above.
        throw Object.assign(new Error(error?.message || "Raster transport failed"), {
          name: controller.signal.aborted ? "AbortError" : error?.name || "Error",
          status: error?.status, scoutRasterTransport: true,
        });
      } finally {
        this.controllers.delete(controller);
        if (!this.destroyed && revision === this.revision) this.publish(record.layerId);
      }
    }

    destroy() {
      this.destroyed = true;
      this.controllers.forEach(controller => controller.abort());
      this.controllers.clear();
      if (this.enabled) this.maplibregl.removeProtocol(this.protocol);
      this.layers.clear();
      this.records.clear();
      this.viewErrors.clear();
      this.container.dataset.maplibreRasterTransport = "destroyed";
    }
  }

  class MapLibreEvidenceRenderer {
    constructor({
      maplibregl,
      container,
      onFeatureSelect = null,
      onFeatureHover = null,
      onFeatureLeave = null,
      onStatus = null,
      onRasterStatus = null,
      onViewState = null,
      rasterLayers = [],
      timeoutMs = 15000,
    } = {}) {
      if (typeof maplibregl?.Map !== "function") throw new Error("maplibre_map_unavailable");
      if (!container) throw new Error("maplibre_container_unavailable");
      this.maplibregl = maplibregl;
      this.container = container;
      this.onFeatureSelect = typeof onFeatureSelect === "function" ? onFeatureSelect : null;
      this.onFeatureHover = typeof onFeatureHover === "function" ? onFeatureHover : null;
      this.onFeatureLeave = typeof onFeatureLeave === "function" ? onFeatureLeave : null;
      this.onStatus = typeof onStatus === "function" ? onStatus : null;
      this.onRasterStatus = typeof onRasterStatus === "function" ? onRasterStatus : null;
      this.onViewState = typeof onViewState === "function" ? onViewState : null;
      this.rasterLayers = normalizeRasterLayers(rasterLayers);
      this.rasterLayerSignature = rasterLayersSignature(this.rasterLayers);
      this.rasterLayerStates = new Map(this.rasterLayers.map(layer => [
        layer.layer_id,
        Object.freeze({
          layer_id: layer.layer_id,
          source_id: layer.source_id,
          state: layer.visible ? "configured" : "hidden",
          reason: layer.visible ? "source_configured" : "layer_hidden",
          visible: layer.visible,
          error_count: 0,
        }),
      ]));
      this.timeoutMs = timeoutMs;
      this.map = null;
      this.destroyed = false;
      this.rasterTransport = new RasterTileTransport({maplibregl, container,
        getMap: () => this.map, onState: (layerId, patch) => this.updateRasterLayerState(layerId, patch)});
      this.rasterTransport.configure(this.rasterLayers);
      this.featureCollection = createEvidenceFeatureCollection();
      this.index = buildEvidenceIndex();
      this.hiddenLayerIds = new Set();
      this.selectedFeatureIds = [];
      this.interactionMode = "pan";
      this.rectangleZoomSelection = null;
      this.rectangleZoomOverlay = null;
      this.selectionLabel = null;
      this.suppressFeatureClickUntil = 0;
      this.interactionSurface = null;
      this.interactionCapture = null;
      this.boundRectangleZoomStart = event => this.beginRectangleZoom(event);
      this.boundRectangleZoomMove = event => this.updateRectangleZoom(event);
      this.boundRectangleZoomEnd = event => this.finishRectangleZoom(event);
      this.boundRectangleZoomCancel = () => this.cancelRectangleZoom();
      this.status = Object.freeze({state: "idle", reason: "not_initialized"});
    }

    updateRasterLayerState(layerId, patch = {}) {
      if (this.destroyed) return null;
      const key = String(layerId || "");
      const current = this.rasterLayerStates.get(key);
      if (!current) return null;
      const next = Object.freeze({...current, ...patch, layer_id: key});
      const states = new Map(this.rasterLayerStates);
      states.set(key, next);
      this.rasterLayerStates = states;
      const values = [...states.values()];
      const aggregate = values.some(state => state.state === "degraded")
        ? "degraded"
        : values.some(state => state.state === "loading")
          ? "loading"
          : values.some(state => state.state === "available")
            ? "available"
            : values.length
              ? "configured"
              : "not_configured";
      this.container.dataset.maplibreRasterState = aggregate;
      const native = values.find(value => value.layer_id === "rudy-twmap" && value.visible);
      this.container.dataset.maplibreRasterNativeZoom = native?.native_zoom == null ? "" : String(native.native_zoom);
      this.container.dataset.maplibreRasterVerifiedNativeZoom = native?.verified_native_zoom == null
        ? "" : String(native.verified_native_zoom);
      ["required_count", "success_count", "pending_count", "error_count", "unverified_count"].forEach((field, index) => {
        const key = ["RequiredCount", "SuccessCount", "PendingCount", "ErrorCount", "UnverifiedCount"][index];
        this.container.dataset[`maplibreRaster${key}`] = String(native?.[field] || 0);
      });
      if (this.onRasterStatus) this.onRasterStatus(next, values);
      return next;
    }

    rasterLayerForSource(sourceId) {
      return this.rasterLayers.find(layer => layer.map_source_id === String(sourceId || "")) || null;
    }

    bindRasterStatus() {
      this.rasterLayers.forEach(layer => {
        if (layer.visible) {
          this.updateRasterLayerState(layer.layer_id, {
            state: "loading",
            reason: "tiles_loading",
          });
        }
      });
      ["move", "moveend", "idle"].forEach(event => {
        this.map.on(event, () => this.rasterTransport.publishAll());
      });
      this.map.on("sourcedata", event => {
        const layer = this.rasterLayerForSource(event?.sourceId);
        if (!layer || event?.isSourceLoaded !== true) return;
        if (this.rasterTransport.handles(layer.layer_id)) {
          this.rasterTransport.publish(layer.layer_id);
          return;
        }
        const patch = rasterLayerEventPatch(
          this.rasterLayerStates.get(layer.layer_id),
          "source_loaded",
        );
        if (patch) this.updateRasterLayerState(layer.layer_id, patch);
      });
      this.map.on("error", event => {
        const layer = this.rasterLayerForSource(event?.sourceId);
        if (!layer) return;
        if (event.error?.name === "AbortError" || event.error?.scoutRasterTransport) return;
        if (this.rasterTransport.handles(layer.layer_id)) {
          this.rasterTransport.recordMapError(layer.layer_id);
          return;
        }
        const current = this.rasterLayerStates.get(layer.layer_id);
        const patch = rasterLayerEventPatch(current, "tile_error");
        if (patch) this.updateRasterLayerState(layer.layer_id, patch);
      });
    }

    setRasterLayers(definitions = []) {
      const nextLayers = normalizeRasterLayers(definitions);
      const nextSignature = rasterLayersSignature(nextLayers);
      if (nextSignature === this.rasterLayerSignature) return false;

      const previousLayers = this.rasterLayers;
      this.rasterTransport.configure(nextLayers);
      if (this.map) {
        [...previousLayers].reverse().forEach(layer => {
          if (this.map.getLayer(layer.map_layer_id)) this.map.removeLayer(layer.map_layer_id);
        });
        previousLayers.forEach(layer => {
          if (this.map.getSource(layer.map_source_id)) this.map.removeSource(layer.map_source_id);
        });
      }

      this.rasterLayers = nextLayers;
      this.rasterLayerSignature = nextSignature;
      this.rasterLayerStates = new Map(nextLayers.map(layer => [
        layer.layer_id,
        Object.freeze({
          layer_id: layer.layer_id,
          source_id: layer.source_id,
          state: layer.visible ? "loading" : "hidden",
          reason: layer.visible ? "tiles_loading" : "layer_hidden",
          visible: layer.visible,
          error_count: 0,
        }),
      ]));

      if (this.map) {
        nextLayers.forEach(layer => {
          this.map.addSource(layer.map_source_id, this.rasterTransport.sourceDefinition(layer));
        });
        nextLayers.filter(layer => layer.render_position === "base").forEach(layer => {
          this.map.addLayer(
            rasterStyleLayerDefinition(layer),
            this.map.getLayer(EVIDENCE_LAYER_IDS.fill) ? EVIDENCE_LAYER_IDS.fill : undefined,
          );
        });
        const overlayBeforeLayerId = this.map.getLayer(EVIDENCE_LAYER_IDS.line)
          ? EVIDENCE_LAYER_IDS.line
          : this.map.getLayer(EVIDENCE_LAYER_IDS.point)
            ? EVIDENCE_LAYER_IDS.point
            : undefined;
        nextLayers.filter(layer => layer.render_position === "overlay").forEach(layer => {
          this.map.addLayer(rasterStyleLayerDefinition(layer), overlayBeforeLayerId);
        });
      }

      const states = [...this.rasterLayerStates.values()];
      const aggregate = states.some(state => state.state === "loading")
        ? "loading"
        : states.length
          ? "configured"
          : "not_configured";
      this.container.dataset.maplibreRasterState = aggregate;
      if (this.onRasterStatus) this.onRasterStatus(null, states);
      return true;
    }

    emitStatus(state, reason, detail = "") {
      this.status = Object.freeze({state, reason, detail});
      this.container.dataset.maplibreState = state;
      this.container.dataset.maplibreReason = reason;
      if (this.onStatus) this.onStatus(this.status);
      return this.status;
    }

    visibleFeatureCollection() {
      return createEvidenceFeatureCollection(this.featureCollection.features.map(feature => ({
        ...feature,
        properties: {
          ...feature.properties,
          _scout_visible: !this.hiddenLayerIds.has(feature.properties?.layer_id),
        },
      })));
    }

    async initialize(featureCollection = createEvidenceFeatureCollection()) {
      this.emitStatus("loading", "map_initializing");
      this.featureCollection = createEvidenceFeatureCollection(featureCollection.features || []);
      this.index = buildEvidenceIndex(this.featureCollection.features);
      const style = createEvidenceStyle(this.visibleFeatureCollection(), {rasterLayers: this.rasterLayers});
      this.rasterLayers.forEach(layer => {
        style.sources[layer.map_source_id] = this.rasterTransport.sourceDefinition(layer);
      });
      this.map = new this.maplibregl.Map({
        container: this.container,
        style,
        center: [0, 0],
        zoom: 1,
        attributionControl: true,
        dragRotate: false,
        pitchWithRotate: false,
        boxZoom: false,
      });
      this.bindRasterStatus();
      if (typeof this.maplibregl.NavigationControl === "function") {
        this.map.addControl(new this.maplibregl.NavigationControl({showCompass: false}), "top-right");
      }
      await waitForMapLoad(this.map, this.timeoutMs);
      this.bindFeatureInteractions();
      this.bindRectangleZoomInteractions();
      this.bindViewState();
      this.setInteractionMode(this.interactionMode);
      this.setFeatureCollection(this.featureCollection);
      this.fitAll({duration: 0});
      this.container.dataset.maplibreFeatureCount = String(this.featureCollection.features.length);
      this.emitStatus("ready", "evidence_rendered");
      return this;
    }

    bindFeatureInteractions() {
      [
        EVIDENCE_LAYER_IDS.osmFill,
        EVIDENCE_LAYER_IDS.osmLine,
        EVIDENCE_LAYER_IDS.osmPoint,
        EVIDENCE_LAYER_IDS.fill,
        EVIDENCE_LAYER_IDS.line,
        EVIDENCE_LAYER_IDS.point,
        EVIDENCE_LAYER_IDS.overlayFill,
      ].forEach(layerId => {
        this.map.on("click", layerId, event => {
          if (Date.now() < this.suppressFeatureClickUntil) return;
          const renderedFeature = event?.features?.[0];
          const featureId = firstIdentifier(renderedFeature?.id, renderedFeature?.properties?.identity_key);
          if (!featureId) return;
          const feature = this.index.feature(featureId) || renderedFeature;
          const result = this.focus(featureId, {fit: false});
          if (this.onFeatureSelect) this.onFeatureSelect(feature, result);
        });
        this.map.on("mouseenter", layerId, event => {
          this.syncCursor(true);
          const renderedFeature = event?.features?.[0];
          if (renderedFeature && this.onFeatureHover) {
            const featureId = firstIdentifier(
              renderedFeature.id,
              renderedFeature.properties?.identity_key,
            );
            this.onFeatureHover(this.index.feature(featureId) || renderedFeature, event);
          }
        });
        this.map.on("mousemove", layerId, event => {
          const renderedFeature = event?.features?.[0];
          if (!renderedFeature || !this.onFeatureHover) return;
          const featureId = firstIdentifier(
            renderedFeature.id,
            renderedFeature.properties?.identity_key,
          );
          this.onFeatureHover(this.index.feature(featureId) || renderedFeature, event);
        });
        this.map.on("mouseleave", layerId, () => {
          this.syncCursor(false);
          if (this.onFeatureLeave) this.onFeatureLeave();
        });
      });
    }

    syncCursor(featureHover = false) {
      const canvas = this.map?.getCanvas?.();
      if (!canvas) return;
      canvas.style.cursor = this.interactionMode === "box"
        ? "crosshair"
        : featureHover ? "pointer" : "";
    }

    bindViewState() {
      if (!this.map) return;
      const sync = () => {
        const center = this.map?.getCenter?.();
        const zoom = Number(this.map?.getZoom?.());
        if (Number.isFinite(zoom)) this.container.dataset.maplibreZoom = zoom.toFixed(6);
        if (center && Number.isFinite(Number(center.lng)) && Number.isFinite(Number(center.lat))) {
          this.container.dataset.maplibreCenter = `${Number(center.lng).toFixed(7)},${Number(center.lat).toFixed(7)}`;
        }
        if (this.onViewState && Number.isFinite(zoom)) {
          this.onViewState({zoom, minZoom: this.map.getMinZoom?.(), maxZoom: this.map.getMaxZoom?.()});
        }
        this.syncSelectionLabel();
      };
      this.map.on("move", sync);
      this.map.on("moveend", sync);
      sync();
    }

    bindRectangleZoomInteractions() {
      const canvasSurface = this.map?.getCanvasContainer?.() || this.map?.getCanvas?.();
      let surface = canvasSurface;
      const capture = global.document?.createElement?.("div");
      if (capture && canvasSurface?.appendChild) {
        capture.className = "scout-maplibre-box-capture";
        capture.setAttribute("aria-hidden", "true");
        Object.assign(capture.style, {
          position: "absolute",
          inset: "0",
          zIndex: "4",
          background: "transparent",
          pointerEvents: "none",
          touchAction: "none",
          cursor: "crosshair",
        });
        canvasSurface.appendChild(capture);
        this.interactionCapture = capture;
        surface = capture;
      }
      if (!surface?.addEventListener) return;
      this.interactionSurface = surface;
      surface.addEventListener("pointerdown", this.boundRectangleZoomStart, true);
      surface.addEventListener("pointermove", this.boundRectangleZoomMove, true);
      surface.addEventListener("pointerup", this.boundRectangleZoomEnd, true);
      surface.addEventListener("pointercancel", this.boundRectangleZoomCancel, true);
      this.container.dataset.maplibreBoxZoomBound = "true";
    }

    setInteractionMode(mode) {
      const nextMode = mode === "box" ? "box" : "pan";
      this.interactionMode = nextMode;
      this.cancelRectangleZoom();
      if (nextMode === "box") this.map?.dragPan?.disable?.();
      else this.map?.dragPan?.enable?.();
      this.map?.boxZoom?.disable?.();
      if (this.interactionCapture) {
        this.interactionCapture.style.pointerEvents = nextMode === "box" ? "auto" : "none";
      }
      this.container.dataset.maplibreInteractionMode = nextMode;
      this.syncCursor(false);
      return nextMode;
    }

    rectanglePoint(event) {
      const rect = this.interactionSurface?.getBoundingClientRect?.();
      if (!rect?.width || !rect?.height) return null;
      return Object.freeze({
        x: Math.max(0, Math.min(rect.width, Number(event.clientX) - rect.left)),
        y: Math.max(0, Math.min(rect.height, Number(event.clientY) - rect.top)),
      });
    }

    ensureRectangleZoomOverlay() {
      if (this.rectangleZoomOverlay?.isConnected) return this.rectangleZoomOverlay;
      const overlay = global.document?.createElement?.("div");
      if (!overlay) return null;
      overlay.className = "scout-maplibre-box-selection";
      Object.assign(overlay.style, {
        position: "absolute",
        zIndex: "8",
        border: "2px solid #f7c948",
        background: "rgba(247, 201, 72, 0.16)",
        boxShadow: "0 0 0 1px rgba(17, 24, 39, 0.75)",
        pointerEvents: "none",
        display: "none",
      });
      this.container.appendChild(overlay);
      this.rectangleZoomOverlay = overlay;
      return overlay;
    }

    updateRectangleZoomOverlay(start, current) {
      const overlay = this.ensureRectangleZoomOverlay();
      if (!overlay) return;
      overlay.style.left = `${Math.min(start.x, current.x).toFixed(1)}px`;
      overlay.style.top = `${Math.min(start.y, current.y).toFixed(1)}px`;
      overlay.style.width = `${Math.abs(start.x - current.x).toFixed(1)}px`;
      overlay.style.height = `${Math.abs(start.y - current.y).toFixed(1)}px`;
      overlay.style.display = "block";
      this.container.dataset.maplibreBoxSelecting = "true";
    }

    clearRectangleZoomOverlay() {
      if (this.rectangleZoomOverlay) {
        this.rectangleZoomOverlay.style.display = "none";
        this.rectangleZoomOverlay.removeAttribute("data-active");
      }
      this.container.dataset.maplibreBoxSelecting = "false";
    }

    beginRectangleZoom(event) {
      if (this.interactionMode !== "box" || Number(event.button) !== 0) return;
      const start = this.rectanglePoint(event);
      if (!start) return;
      this.rectangleZoomSelection = {
        pointerId: event.pointerId,
        start,
        current: start,
        moved: false,
      };
      this.interactionSurface?.setPointerCapture?.(event.pointerId);
      event.preventDefault();
      event.stopPropagation();
    }

    updateRectangleZoom(event) {
      const selection = this.rectangleZoomSelection;
      if (!selection || selection.pointerId !== event.pointerId) return;
      const current = this.rectanglePoint(event);
      if (!current) return;
      selection.current = current;
      selection.moved = selection.moved
        || Math.abs(current.x - selection.start.x) > 8
        || Math.abs(current.y - selection.start.y) > 8;
      if (selection.moved) this.updateRectangleZoomOverlay(selection.start, current);
      event.preventDefault();
      event.stopPropagation();
    }

    finishRectangleZoom(event) {
      const selection = this.rectangleZoomSelection;
      if (!selection || selection.pointerId !== event.pointerId) return false;
      this.rectangleZoomSelection = null;
      try {
        this.interactionSurface?.releasePointerCapture?.(event.pointerId);
      } catch (_error) {
        // Pointer capture may already have been released by the browser.
      }
      this.clearRectangleZoomOverlay();
      if (selection.moved) {
        const left = Math.min(selection.start.x, selection.current.x);
        const right = Math.max(selection.start.x, selection.current.x);
        const top = Math.min(selection.start.y, selection.current.y);
        const bottom = Math.max(selection.start.y, selection.current.y);
        const northWest = this.map?.unproject?.([left, top]);
        const southEast = this.map?.unproject?.([right, bottom]);
        if (northWest && southEast) {
          const west = Math.min(Number(northWest.lng), Number(southEast.lng));
          const east = Math.max(Number(northWest.lng), Number(southEast.lng));
          const south = Math.min(Number(northWest.lat), Number(southEast.lat));
          const north = Math.max(Number(northWest.lat), Number(southEast.lat));
          const maxZoom = Math.min(Number(this.map?.getZoom?.() || 0) + 2, 18);
          this.map.fitBounds([[west, south], [east, north]], {
            padding: 24,
            maxZoom,
            duration: 280,
          });
          this.container.dataset.maplibreLastBoxBounds = [west, south, east, north]
            .map(value => value.toFixed(7)).join(",");
        }
        this.suppressFeatureClickUntil = Date.now() + 350;
      } else {
        const center = this.map?.unproject?.([selection.start.x, selection.start.y]);
        this.map?.easeTo?.({
          center,
          zoom: Math.min(Number(this.map?.getZoom?.() || 0) + 1, 18),
          duration: 220,
        });
      }
      event.preventDefault();
      event.stopPropagation();
      return true;
    }

    cancelRectangleZoom() {
      const pointerId = this.rectangleZoomSelection?.pointerId;
      this.rectangleZoomSelection = null;
      if (pointerId !== undefined) {
        try {
          this.interactionSurface?.releasePointerCapture?.(pointerId);
        } catch (_error) {
          // Pointer capture may already have been released by the browser.
        }
      }
      this.clearRectangleZoomOverlay();
    }

    ensureSelectionLabel() {
      if (this.selectionLabel?.isConnected) return this.selectionLabel;
      const label = global.document?.createElement?.("div");
      if (!label) return null;
      label.className = "scout-maplibre-selection-label";
      label.setAttribute("role", "status");
      Object.assign(label.style, {
        position: "absolute",
        zIndex: "7",
        maxWidth: "min(280px, calc(100% - 24px))",
        padding: "5px 8px",
        border: "1px solid rgba(255,255,255,0.86)",
        borderRadius: "4px",
        background: "rgba(15, 34, 42, 0.92)",
        color: "#f4fbfc",
        font: "600 12px/1.25 system-ui, sans-serif",
        pointerEvents: "none",
        transform: "translate(10px, -50%)",
        display: "none",
      });
      this.container.appendChild(label);
      this.selectionLabel = label;
      return label;
    }

    syncSelectionLabel() {
      const label = this.ensureSelectionLabel();
      const feature = this.selectedFeatureIds.length
        ? this.index.feature(this.selectedFeatureIds[0])
        : null;
      const pairs = geometryCoordinatePairs(feature?.geometry?.coordinates);
      if (!label || !feature || !pairs.length || !this.map?.project) {
        if (label) label.style.display = "none";
        return;
      }
      const coordinate = pairs[Math.floor(pairs.length / 2)];
      const point = this.map.project(coordinate);
      label.textContent = firstIdentifier(
        feature.properties?.display_label,
        feature.properties?.label,
        feature.properties?.identity_key,
      ) || "selected evidence";
      label.style.left = `${Number(point.x).toFixed(1)}px`;
      label.style.top = `${Number(point.y).toFixed(1)}px`;
      label.style.display = "block";
    }

    setFeatureCollection(featureCollection) {
      this.featureCollection = createEvidenceFeatureCollection(featureCollection?.features || []);
      this.index = buildEvidenceIndex(this.featureCollection.features);
      const visible = this.visibleFeatureCollection();
      const source = this.map?.getSource(EVIDENCE_SOURCE_ID);
      if (typeof source?.setData === "function") source.setData(visible);
      this.container.dataset.maplibreFeatureCount = String(this.featureCollection.features.length);
      this.selectedFeatureIds = this.selectedFeatureIds.filter(featureId => this.index.feature(featureId));
      this.syncSelectionLabel();
      return this.featureCollection;
    }

    setLayerVisibility(layerId, visible) {
      const requestedLayerId = String(layerId);
      const nextHiddenLayerIds = new Set(this.hiddenLayerIds);
      if (visible) nextHiddenLayerIds.delete(requestedLayerId);
      else nextHiddenLayerIds.add(requestedLayerId);
      this.hiddenLayerIds = nextHiddenLayerIds;
      const rasterLayers = this.rasterLayers.filter(layer => (
        layer.layer_id === requestedLayerId
        || layer.control_layer_id === requestedLayerId
      ));
      rasterLayers.forEach(rasterLayer => {
        if (!this.map?.getLayer(rasterLayer.map_layer_id)) return;
        const currentRasterState = this.rasterLayerStates.get(rasterLayer.layer_id);
        const retainedState = visible
          && currentRasterState?.visible === true
          && ["available", "degraded"].includes(currentRasterState?.state)
          ? currentRasterState.state
          : null;
        this.map.setLayoutProperty(
          rasterLayer.map_layer_id,
          "visibility",
          visible ? "visible" : "none",
        );
        this.updateRasterLayerState(rasterLayer.layer_id, {
          visible: Boolean(visible),
          state: visible ? retainedState || "loading" : "hidden",
          reason: visible
            ? retainedState
              ? currentRasterState.reason
              : "tiles_loading"
            : "layer_hidden",
        });
        this.rasterTransport.setVisibility(rasterLayer.layer_id, visible);
      });
      const source = this.map?.getSource(EVIDENCE_SOURCE_ID);
      if (typeof source?.setData === "function") source.setData(this.visibleFeatureCollection());
      this.container.dataset.maplibreHiddenLayers = [...this.hiddenLayerIds].sort().join(",");
      return !this.hiddenLayerIds.has(requestedLayerId);
    }

    clearSelection() {
      this.selectedFeatureIds.forEach(featureId => {
        try {
          this.map?.setFeatureState(
            {source: EVIDENCE_SOURCE_ID, id: featureId},
            {selected: false},
          );
        } catch (_error) {
          // The source may have been replaced during a projection refresh.
        }
      });
      this.selectedFeatureIds = [];
      this.syncSelectionLabel();
    }

    fitFeatureIds(featureIds, options = {}) {
      const features = featureIds.map(featureId => this.index.feature(featureId)).filter(Boolean);
      const bounds = featureCollectionBounds(createEvidenceFeatureCollection(features));
      if (!bounds || !this.map) return false;
      const [west, south, east, north] = bounds;
      if (west === east && south === north) {
        this.map.easeTo({
          center: [west, south],
          zoom: Math.min(Number(options.maxZoom) || 16, 16),
          duration: Number(options.duration) || 280,
        });
      } else {
        this.map.fitBounds([[west, south], [east, north]], {
          padding: Number(options.padding) || 72,
          maxZoom: Number(options.maxZoom) || 16,
          duration: options.duration === 0 ? 0 : Number(options.duration) || 320,
        });
      }
      return true;
    }

    centerFeatureIds(featureIds, options = {}) {
      const features = featureIds.map(featureId => this.index.feature(featureId)).filter(Boolean);
      const bounds = featureCollectionBounds(createEvidenceFeatureCollection(features));
      if (!bounds || !this.map) return false;
      const [west, south, east, north] = bounds;
      this.map.easeTo({
        center: [(west + east) / 2, (south + north) / 2],
        zoom: this.map.getZoom(),
        duration: Number(options.duration) || 260,
      });
      return true;
    }

    focus(reference, options = {}) {
      const featureIds = this.index.resolve(reference);
      if (!featureIds.length) {
        return Object.freeze({focused: false, feature_ids: [], reason: "feature_not_found"});
      }
      this.clearSelection();
      featureIds.forEach(featureId => {
        this.map?.setFeatureState(
          {source: EVIDENCE_SOURCE_ID, id: featureId},
          {selected: true},
        );
      });
      this.selectedFeatureIds = [...featureIds];
      this.syncSelectionLabel();
      const fitted = options.fit === false
        ? true
        : options.preserveZoom === true
          ? this.centerFeatureIds(featureIds, options)
          : this.fitFeatureIds(featureIds, options);
      return Object.freeze({
        focused: fitted,
        feature_ids: [...featureIds],
        reason: fitted ? "feature_selected" : "feature_bounds_unavailable",
      });
    }

    fitAll(options = {}) {
      if (!this.featureCollection.features.length || !this.map) return false;
      return this.fitFeatureIds(
        this.featureCollection.features.map(feature => String(feature.id)),
        options,
      );
    }

    fitLayer(layerId, options = {}) {
      const featureIds = this.featureCollection.features
        .filter(feature => feature.properties?.layer_id === String(layerId || ""))
        .map(feature => String(feature.id));
      return featureIds.length ? this.fitFeatureIds(featureIds, options) : false;
    }

    zoomBy(direction) {
      if (!this.map) return false;
      if (Number(direction) > 0) this.map.zoomIn({duration: 180});
      else this.map.zoomOut({duration: 180});
      return true;
    }

    panBy([x, y]) {
      if (!this.map) return false;
      this.map.panBy([Number(x) || 0, Number(y) || 0], {duration: 180});
      return true;
    }

    screenPoint(reference) {
      const featureId = this.index.resolve(reference)[0];
      const feature = featureId ? this.index.feature(featureId) : null;
      const pairs = geometryCoordinatePairs(feature?.geometry?.coordinates);
      if (!feature || !pairs.length || !this.map?.project) return null;
      const coordinate = pairs[Math.floor(pairs.length / 2)];
      const point = this.map.project(coordinate);
      return Object.freeze({
        x: Number(point.x),
        y: Number(point.y),
        feature_id: featureId,
        identity_key: feature.properties?.identity_key || featureId,
      });
    }

    resize() {
      this.map?.resize();
    }

    snapshot() {
      const layerFeatureCounts = {};
      const firstFeatureRefs = {};
      this.featureCollection.features.forEach(feature => {
        const layerId = String(feature.properties?.layer_id || "unclassified");
        layerFeatureCounts[layerId] = (layerFeatureCounts[layerId] || 0) + 1;
        if (!firstFeatureRefs[layerId]) firstFeatureRefs[layerId] = String(feature.id);
      });
      return Object.freeze({
        ...this.status,
        feature_count: this.featureCollection.features.length,
        selected_feature_ids: [...this.selectedFeatureIds],
        hidden_layer_ids: [...this.hiddenLayerIds],
        interaction_mode: this.interactionMode,
        box_zoom_active: Boolean(this.rectangleZoomSelection),
        layer_feature_counts: Object.freeze(layerFeatureCounts),
        first_feature_refs: Object.freeze(firstFeatureRefs),
        raster_layer_states: Object.freeze(Object.fromEntries(
          [...this.rasterLayerStates.entries()].map(([layerId, state]) => [layerId, state]),
        )),
        raster_layer_order: Object.freeze(this.rasterLayers.map(layer => Object.freeze({
          layer_id: layer.layer_id,
          control_layer_id: layer.control_layer_id,
          render_position: layer.render_position,
        }))),
        zoom: this.map?.getZoom?.() ?? null,
        center: this.map?.getCenter?.()?.toArray?.() ?? null,
      });
    }

    destroy() {
      this.destroyed = true;
      this.rasterTransport.destroy();
      this.cancelRectangleZoom();
      if (this.interactionSurface?.removeEventListener) {
        this.interactionSurface.removeEventListener("pointerdown", this.boundRectangleZoomStart, true);
        this.interactionSurface.removeEventListener("pointermove", this.boundRectangleZoomMove, true);
        this.interactionSurface.removeEventListener("pointerup", this.boundRectangleZoomEnd, true);
        this.interactionSurface.removeEventListener("pointercancel", this.boundRectangleZoomCancel, true);
      }
      this.rectangleZoomOverlay?.remove?.();
      this.interactionCapture?.remove?.();
      this.selectionLabel?.remove?.();
      if (this.onFeatureLeave) this.onFeatureLeave();
      this.map?.remove();
      this.map = null;
      this.emitStatus("disabled", "renderer_destroyed");
    }
  }

  async function createRenderer(options, featureCollection = createEvidenceFeatureCollection()) {
    const renderer = new MapLibreEvidenceRenderer(options);
    try {
      return await renderer.initialize(featureCollection);
    } catch (error) {
      renderer.destroy();
      throw error;
    }
  }

  async function loadMapLibre(moduleUrl = DEFAULT_MODULE_URL) {
    if (!mapLibreModulePromise) {
      mapLibreModulePromise = import(moduleUrl).then(module => module.default || module);
    }
    return mapLibreModulePromise;
  }

  async function loadRenderer({requested = "auto", moduleUrl = DEFAULT_MODULE_URL} = {}) {
    const resolution = resolveRenderer({
      requested,
      webglAvailable: webglAvailable(),
    });
    if (resolution.active === "svg") {
      return Object.freeze({...resolution, maplibregl: null, error: ""});
    }
    try {
      const maplibregl = await loadMapLibre(moduleUrl);
      if (typeof maplibregl?.Map !== "function") {
        throw new Error("MapLibre module does not expose Map");
      }
      return Object.freeze({
        ...resolution,
        state: "ready",
        reason: "maplibre_loaded",
        maplibregl,
        error: "",
      });
    } catch (error) {
      return Object.freeze({
        requested: resolution.requested,
        active: "svg",
        state: "degraded",
        reason: "maplibre_load_failed",
        maplibregl: null,
        error: String(error?.message || error || "MapLibre load failed"),
      });
    }
  }

  window.ScoutMapLibreEvidence = Object.freeze({
    version: "0.1.0",
    mapLibreVersion: MAPLIBRE_VERSION,
    moduleUrl: DEFAULT_MODULE_URL,
    normalizeRendererPreference,
    resolveRenderer,
    normalizeEvidenceIdentity,
    normalizeRasterLayer,
    normalizeRasterLayers,
    rasterLayerEventPatch,
    buildEvidenceIndex,
    geometryBounds,
    createEvidenceFeature,
    createEvidenceFeatureCollection,
    createEvidenceStyle,
    featureCollectionBounds,
    inspectSvgLayerOrder,
    inspectMapLibreLayerOrder,
    createRenderer,
    sourceId: EVIDENCE_SOURCE_ID,
    layerIds: EVIDENCE_LAYER_IDS,
    webglAvailable,
    loadMapLibre,
    loadRenderer,
  });
})(window);
