from pathlib import Path

from pretrip_admin_view import build_pretrip_admin_view


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
ASSISTANT_UI_SCRIPT = ROOT / "docs" / "admin" / "scout-assistant-ui.js"


def test_pretrip_admin_page_contains_expected_layout_contract():
    html = PAGE.read_text(encoding="utf-8")

    assert "Scout Phase 4 Pre-Trip Planning" in html
    assert "html { height: 100%; }" in html
    assert "height: 100vh;" in html
    assert "max-width: 100vw;" in html
    assert 'src="/admin/scout-assistant-ui.js"' in html
    assert 'id="readinessStrip"' in html
    assert "map frame" not in html.lower()
    assert 'id="map"' in html
    assert 'id="evidenceTree"' in html
    assert 'id="jsonPane"' in html
    assert 'id="sectionList"' in html
    assert "grid-template-rows: auto minmax(180px, .95fr) minmax(260px, 1.05fr);" in html
    assert "grid-template-columns: minmax(290px, 360px) minmax(640px, 1fr) minmax(340px, 420px);" in html
    assert 'grid-template-areas: "features map detail";' in html
    assert "grid-template-rows: auto minmax(0, 1fr);" in html
    assert "grid-template-rows: auto minmax(240px, 1fr);" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html
    assert "scrollbar-gutter: stable;" in html
    assert "min-height: 0;" in html
    assert "grid-template-columns: 1fr;" in html
    assert '"map"\n          "features"\n          "detail";' in html
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in html
    assert "grid-template-columns: repeat(3, 24px);" in html
    assert "grid-template-rows: repeat(3, 24px);" in html
    assert "#map { min-height: 420px; }" in html
    assert ".detail-body > *," in html
    assert ".tree > *," in html
    assert ".assistant-panel > *" in html
    assert "overflow-wrap: anywhere;" in html
    assert ".assistant-panel" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html
    assert "CP / Segment Frame" in html
    assert "Pre-trip planning" in html
    assert "Post-analysis" in html
    assert "Review , Workspace" in html
    assert "Import GPX" in html
    assert 'id="reviewWorkspacePanel"' in html
    assert 'id="reviewWorkspaceTree"' in html
    assert 'id="importGpxPanel"' in html
    assert "segment-overlay" in html
    assert "reference-track" in html
    assert "gis-perception-cp" in html
    assert "gis-nearby-group" in html
    assert "is-stale" in html
    assert "map-highlight" in html
    assert "mapTargetsFor" in html
    assert "map_target_ids" in html
    assert "selectEvidence" in html
    assert "highlightMapFor" in html
    assert "data-source-id" in html
    assert "data-tree-category" in html
    assert "data-tree-status" in html
    assert ".route-note" in html
    assert "AI GIS CP" in html
    assert "GIS CP Areas" in html
    assert "nearby_group_id" in html
    assert "route_note_freshness" in html
    assert "view.gis_perception_timeline?.checkpoint_candidates" in html


def test_pretrip_admin_page_has_top_level_readiness_strip_boundary_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "readinessStrip",
        "readinessStripStatus",
        "readinessStripBoundary",
        "readinessBlockerCount",
        "readinessWarningCount",
        "readinessFieldReviewCount",
        "readinessReviewedPackageStatus",
        "readinessDepartureGateBoundary",
        "readinessRuntimeHandoffBoundary",
    ):
        assert f'id="{control_id}"' in html

    assert "function updateReadinessStrip" in html
    assert "view.readiness?.status" in html
    assert "view.review_queue?.counts" in html
    assert "view.route_note_reviewed_assumptions?.counts?.field_verification_request_count" in html
    assert "view.departure_bundle?.package?.status" in html
    assert "view.departure_bundle?.boundary" in html
    assert "view.tabs?.post_analysis?.runtime_handoff?.boundary" in html
    assert "Reviewed planning package only; runtime activation remains closed." in html
    assert "Human review required; not departure approval." in html
    assert "Phase 4.5 owns handoff; no /safety calls or runtime writes." in html


def test_pretrip_admin_page_has_read_only_toolbar_and_summary_raw_sample_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "zoomIn",
        "zoomOut",
        "fitRoute",
        "panUp",
        "panDown",
        "panLeft",
        "panRight",
        "layerControl",
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
        "externalDataImport",
    ):
        assert f'id="{control_id}"' in html

    for enabled_control in (
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
    ):
        assert f'id="{enabled_control}" class="tool-button" type="button" disabled' not in html
        assert f'id="{enabled_control}" class="tool-button" type="button"' in html
    assert 'id="externalDataImport" class="tool-button" type="button" title="Open Import GPX reference route flow" aria-label="Open Import GPX reference route flow">Import GPX</button>' in html
    assert 'id="externalDataImport" class="tool-button" type="button" disabled' not in html
    assert "summary only" in html
    assert "raw_samples" not in html


def test_pretrip_admin_page_groups_dense_controls_and_uses_short_labels():
    html = PAGE.read_text(encoding="utf-8")

    assert "toolbar-grid" in html
    assert "assistant-drawer" in html
    assert '<details class="assistant-drawer" open>' in html
    assert '<summary aria-label="Open read-only assistant panel">Assistant</summary>' in html
    assert 'id="assistantQuestionInput"' in html
    assert 'id="assistantAskButton"' in html
    assert 'id="readinessStripStatus">Loading…</strong>' in html
    assert 'class="sr-only">Reviewed planning is not runtime activation.</small>' in html
    assert 'aria-label="Map view controls"' in html
    assert 'aria-label="Map layer controls"' in html
    assert 'class="layer-menu"' in html
    assert 'id="layerControl" title="Show layer controls" aria-label="Layer controls"' in html
    assert 'id="layerEnabledCount"' in html
    assert "layer-menu-panel" in html
    assert "summary.textContent = `${enabled}/${layerInputs.length}`;" in html
    assert "Workspace edit tools" in html
    assert 'aria-label="Workspace edit tools">Edit</summary>' in html
    assert "Planned edit tools" not in html
    assert "<span>Features</span>" in html
    assert "<span>Review</span>" in html
    assert "<span>Workspace</span>" in html
    assert 'class="action-menu workspace-menu"' in html
    assert "Workspace actions" in html
    assert 'aria-label="Local workspace menu actions"' in html
    assert 'title="Add retreat route to workspace edit log" aria-label="Add retreat route to workspace edit log">Add retreat</button>' in html
    assert 'title="Open Import GPX reference route flow" aria-label="Open Import GPX reference route flow">Import GPX</button>' in html
    assert 'title="Route note layer"><input type="checkbox" data-layer="route-notes" checked> Notes</label>' in html
    assert 'title="Weather API layer"><input type="checkbox" data-layer="weather-api" checked> Weather</label>' in html
    assert 'aria-label="Move to next review item">Next</button>' in html
    assert 'aria-label="Accept selected review">Accept</button>' in html
    assert 'aria-label="Route-note reviewed assumptions">Assumptions</button>' in html
    assert "function assistantQuestionLabel" in html


def test_pretrip_admin_page_has_import_gpx_reference_route_panel():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "importGpxTab",
        "importGpxPanel",
        "importGpxForm",
        "importGoldenRouteGpxPath",
        "importReferenceDirectory",
        "importWorkspaceRoot",
        "importTemplateRoot",
        "importCheckpointSpacingM",
        "importMaxReferenceDisplayPoints",
        "importOverwriteWorkspace",
        "importGpxPreview",
        "importGpxRun",
        "importGpxStatus",
        "importGpxResult",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "importGpxInputValue",
        "optionalImportGpxInputValue",
        "importGpxPositiveNumber",
        "importGpxPayload",
        "importGpxValidationErrors",
        "setImportGpxStatus",
        "setImportGpxBusy",
        "setImportGpxResult",
        "previewImportGpx",
        "runImportGpx",
        "prepareLayersPayload",
        "prepareLayersValidationErrors",
        "setPrepareLayersStatus",
        "setPrepareLayersBusy",
        "setPrepareLayersResult",
        "previewPrepareLayers",
        "runPrepareLayers",
    ):
        assert f"function {function_name}" in html

    assert "Golden route GPX is a pre-trip reference route, not an actual walked user track." in html
    assert "Actual walked track belongs to post-analysis after return." in html
    assert "Golden route GPX path" in html
    assert "Reference GPX directory" in html
    assert "Workspace root" in html
    assert "Optional when the admin runtime already has SCOUT_PRETRIP_WORKSPACE_ROOT." in html
    assert "Template project root" in html
    assert "Checkpoint spacing (m)" in html
    assert "Max reference display points" in html
    assert "Overwrite existing project workspace" in html
    assert "Prepare Layers" in html
    assert "LayerPreparationJob（圖層準備工作）" in html
    assert "Layer ids" in html
    assert "Route corridor (m)" in html
    assert "Allow explicit network fetch" in html
    assert "golden_route_gpx: importGpxInputValue" in html
    assert "reference_dir: optionalImportGpxInputValue" in html
    assert "workspace_root: optionalImportGpxInputValue" in html
    assert "template_project_root: optionalImportGpxInputValue" in html
    assert "checkpoint_spacing_m: importGpxPositiveNumber" in html
    assert "max_reference_display_points: importGpxPositiveNumber" in html
    assert "overwrite: document.getElementById(\"importOverwriteWorkspace\").checked" in html
    assert "confirm_import: true" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/import-gpx-preview" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/import-gpx" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/prepare-layers-preview" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/prepare-layers" in html
    assert "confirm_prepare: true" in html
    assert "const DETAIL_TAB_IDS = new Set" in html
    assert 'state.activeTab: initialActiveTab()' not in html
    assert "activeTab: initialActiveTab()" in html
    assert "function initialActiveTab" in html
    assert 'params.get("tab")' in html
    assert 'DETAIL_TAB_IDS.has(requested)' in html
    assert "function syncActiveTabChrome" in html
    assert "function syncActiveTabPanels" in html
    assert 'document.getElementById("externalDataImport").addEventListener("click", () => setActiveTab("import_gpx"))' in html
    assert 'document.getElementById("importGpxPreview").addEventListener("click", previewImportGpx)' in html
    assert 'document.getElementById("importGpxRun").addEventListener("click", runImportGpx)' in html
    assert 'document.getElementById("prepareLayersPreview").addEventListener("click", previewPrepareLayers)' in html
    assert 'document.getElementById("prepareLayersRun").addEventListener("click", runPrepareLayers)' in html
    assert 'document.getElementById("importGpxPanel").classList.toggle("is-active", tab === "import_gpx")' in html
    assert "golden_route_role: \"pretrip reference route\"" in html
    assert "actual_walked_track_surface: \"post-analysis\"" in html
    assert "phase1_runtime_mutation_allowed: false" in html
    assert "final MissionGraph" in html


def test_pretrip_admin_page_fetches_fixture_backed_read_only_project_api():
    html = PAGE.read_text(encoding="utf-8")

    assert 'const PROJECT_ID = "chilai_nanhua_day1"' in html
    assert "/admin/pretrip/projects/${PROJECT_ID}" in html
    assert "apiBase()" in html
    assert 'data-layer="imagery"' in html
    assert 'data-layer="osm"' in html
    assert 'data-layer="terrain"' in html
    assert 'data-layer="corridors"' in html
    assert 'data-layer="route"' in html
    assert 'data-layer="segments"' in html
    assert 'data-layer="retreat"' in html
    assert 'data-layer="hazards"' in html
    assert 'data-layer="overpass"' in html
    assert 'data-layer="route-notes"' in html
    assert 'data-layer="weather-api"' in html
    assert "OSM_TILE_URL_TEMPLATE" in html
    assert "OSM_PUBLIC_TILE_URL_TEMPLATE" in html
    assert "OSM_LOCAL_TILE_URL_TEMPLATE" in html
    assert "const OSM_TARGET_ZOOM = 17" in html
    assert "const OSM_MAX_TILES = 64" in html
    assert "const MAP_VISUAL_PADDING = 56" in html
    assert "RASTER_LOCAL_TILE_URL_TEMPLATE" in html
    assert "/admin/tiles/osm/{z}/{x}/{y}.png" in html
    assert "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png" in html
    assert "function osmTileTemplate" in html
    assert "function tileRangeForZoom" in html
    assert "function tileCountForZoom" in html
    assert "tileCountForZoom(bounds, zoom) > maxTiles" in html
    assert "function rasterTileTemplate" in html
    assert 'params.get("tileSource")' in html
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in html
    assert "function renderRasterImagery" in html
    assert "function rasterTileCoverage" in html
    assert "class: \"raster-tile\"" in html
    assert "data-raster-tile" in html
    assert "local_raster_tile_url_template" in html
    assert "function renderOsmBasemap" in html
    assert "function osmTileCoverage" in html
    assert 'el("image"' in html
    assert "class: \"osm-tile\"" in html
    assert "function renderTerrainMetadata" in html
    assert "segmentTerrainMetadata(view)" in html
    assert "function renderWeatherOverlay" in html
    assert "function weatherOverlayLabel" in html
    assert "weatherOverlayLabel(cards[0]?.summary || \"Weather evidence pending.\")" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/weather-overlay" in html
    assert "state.weatherOverlay" in html
    assert "Weather API overlay" in html
    assert html.index('data-layer-group": "osm"') < html.index(
        'data-layer-group": "imagery"'
    )
    assert html.index("renderOsmBasemap(osmGroup") < html.index(
        "renderRasterImagery(imageryGroup"
    )
    assert html.index('data-layer-group": "imagery"') < html.index(
        'data-layer-group": "terrain"'
    )
    assert html.index('data-layer-group": "terrain"') < html.index(
        'data-layer-group": "overpass"'
    )
    assert html.index('data-layer-group": "overpass"') < html.index(
        'data-layer-group": "weather-api"'
    )


def test_pretrip_admin_page_renders_overpass_evidence_layer_and_tree():
    html = PAGE.read_text(encoding="utf-8")
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)

    assert view["overpass_evidence"]["counts"]["candidates"] == 219
    assert view["overpass_evidence"]["counts"]["skipped"] == 0
    assert view["overpass_evidence"]["boundary"]["runtime_truth"] is False
    assert view["overpass_evidence"]["boundary"]["live_network_required"] is False
    assert "Overpass Vector Evidence" in {
        section["title"]
        for section in view["tabs"]["pre_trip_planning"]["sections"]
    }
    assert "overpass-corridor" in html
    assert "overpass-hazard" in html
    assert "overpass-poi" in html
    assert "view.overpass_evidence?.corridor_candidates" in html
    assert "view.overpass_evidence?.hazard_candidates" in html
    assert "view.overpass_evidence?.poi_candidates" in html
    assert 'treeGroup("Reference GPX"' in html
    assert "candidate.corridor.coordinates" in html
    assert "candidate.hazard.polygon" in html
    assert "candidate.poi.coordinate" in html
    assert "view.overpass_evidence?.counts?.candidates" in html
    assert "fetch(`${apiBase()}/safety" not in html


def test_pretrip_admin_page_has_round1_map_interaction_contract():
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "mapViewBox",
        "applyMapViewport",
        "clampMapPan",
        "panMap",
        "zoomMap",
        "resetMapView",
    ):
        assert f"function {function_name}" in html

    assert "pointerdown" in html
    assert "pointermove" in html
    assert "pointerup" in html
    assert "setPointerCapture" in html
    assert "is-panning" in html
    assert "highlightMapFor(state.selected)" in html
    assert "highlightTreeNode(state.selected)" in html


def test_pretrip_admin_page_has_round1_cp_segment_panel_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "cpSegmentSearch",
        "featureCategoryFilter",
        "featureStatusFilter",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "statusFor",
        "itemSearchText",
        "updateStatusFilterOptions",
        "applyTreeFilters",
    ):
        assert f"function {function_name}" in html

    assert "badge badge-status" in html
    assert "badge badge-category" in html
    assert "tree-label" in html
    assert "data-filter-empty" in html
    assert "scrollIntoView" in html


def test_pretrip_admin_page_has_review_queue_navigation_and_filter_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "reviewCategoryFilter",
        "reviewSeverityFilter",
        "reviewBlockerQuick",
        "reviewWarningQuick",
        "reviewReviewQuick",
        "reviewBlockerCount",
        "reviewWarningCount",
        "reviewReviewCount",
        "reviewNextItem",
        "routeNoteDraftDisposition",
        "routeNoteDraftPreview",
        "routeNoteDraftSave",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "reviewCategoryFor",
        "reviewSeverityFor",
        "updateReviewCategoryFilterOptions",
        "updateReviewQueueControls",
        "updateReviewQuickButtons",
        "setReviewSeverityFilter",
        "decidedCandidateRefs",
        "isCandidateRefDecided",
        "reviewDecisionStateFor",
        "findEvidenceBySourceId",
        "routeNoteReviewOptionFor",
        "selectedRouteNoteDraftOption",
        "saveRouteNoteDraftDispositionToWorkspace",
        "visibleReviewButtons",
        "jumpToNextReviewItem",
        "previewRouteNoteDraftDisposition",
    ):
        assert f"function {function_name}" in html

    assert 'data-review-severity="blocker"' in html
    assert 'data-review-severity="warning"' in html
    assert 'data-review-severity="review"' in html
    assert 'data-review-category' in html
    assert 'data-review-decision-state' in html
    assert 'data-candidate-ref' in html
    assert "view?.review_decision_log?.decisions" in html
    assert "decision?.candidate_ref" in html
    assert "const selectedSourceId = evidenceSourceId(state.selected)" in html
    assert "findEvidenceBySourceId(view, selectedSourceId) || view.summary" in html
    assert 'button.dataset.reviewDecisionState === "undecided"' in html
    assert "return undecidedButtons.length ? undecidedButtons : buttons;" in html
    assert 'data-map-target-ids' in html
    assert "state.reviewQueueCursor" in html
    assert "state.routeNoteDraftDisposition" in html
    assert 'value="promote_hint"' in html
    assert 'value="promote_warning"' in html
    assert 'value="ignore"' in html
    assert 'value="field_verify"' in html
    assert "draft_preview_only" in html


def test_pretrip_admin_page_review_items_stay_map_target_backed_and_read_only():
    html = PAGE.read_text(encoding="utf-8")

    assert 'treeGroup("Review Queue"' in html
    assert 'data-tree-category="review"' in html
    assert "mapTargetsFor(item)" in html
    assert "item?.map_target_ids" in html
    assert "view?.route_notes?.candidates || []" in html
    assert 'el("g", {"data-layer-group": "route-notes"})' in html
    assert 'class: "route-note"' in html
    assert "button.addEventListener(\"click\", () => selectEvidence(item))" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}`)" in html
    assert "fetch(`${apiBase()}/safety" not in html


def test_pretrip_admin_page_has_local_workspace_write_controls_and_status():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "localWorkspaceCreate",
        "workspaceAcceptReview",
        "workspaceRejectReview",
        "workspaceRefreshApplyPlan",
        "routeNoteReviewedAssumptions",
        "expertContributionApplyResult",
        "workspaceWriteStatus",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "setWorkspaceStatus",
        "isSelectedReviewQueueItem",
        "parseWriteResponse",
        "createLocalWorkspace",
        "acceptSelectedReviewToWorkspace",
        "rejectSelectedReviewToWorkspace",
        "refreshWorkspaceApplyPlan",
        "generateRouteNoteReviewedAssumptionsForWorkspace",
        "applyExpertContributionWorkspaceResult",
        "reloadProjectView",
    ):
        assert f"function {function_name}" in html

    assert "Workspace-only controls are closed to final handoff and runtime writes." in html
    assert '<details class="action-menu workspace-menu">' in html
    assert '<summary aria-label="Open local workspace action menu">Workspace actions</summary>' in html
    assert 'role="status" aria-live="polite"' in html
    for enabled_control in (
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
    ):
        assert f'id="{enabled_control}" class="tool-button" type="button" disabled' not in html
    assert 'id="externalDataImport" class="tool-button" type="button" title="Open Import GPX reference route flow" aria-label="Open Import GPX reference route flow">Import GPX</button>' in html


def test_pretrip_admin_page_has_enabled_workspace_edit_tools():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
    ):
        assert f'id="{control_id}" class="tool-button" type="button" disabled' not in html
        assert f'document.getElementById("{control_id}").addEventListener("click",' in html

    for function_name in (
        "coordinateFromMapPointerEvent",
        "setSelectedMapCoordinate",
        "selectedOrPromptCoordinate",
        "promptRectangleSelection",
        "workspaceEditPayload",
        "postWorkspaceEditLogOperation",
        "addCheckpointToWorkspace",
        "removeSelectedCheckpointFromWorkspace",
        "addRetreatRouteToWorkspace",
        "removeSelectedRetreatRouteFromWorkspace",
        "featureEditToWorkspace",
    ):
        assert f"function {function_name}" in html

    assert "selectedMapCoordinate" in html
    assert "Add CP coordinate as lat, lon. Uses selected map coordinate when available." in html
    assert "Select a checkpoint before Remove CP." in html
    assert "Select a checkpoint before Add retreat." in html
    assert "finishCheckpointCandidate" in html
    assert "Select a retreat route before Remove retreat." in html
    assert "select_trail_generate_waypoint" in html
    assert "rectangle_group_selection" in html
    assert "manualCandidateId" in html
    assert "selectedTargetRefs" in html
    assert "persist_to_workspace: true" in html
    assert "operation," in html
    assert "candidate_id: manualCandidateId" in html
    assert "target_ref: checkpoint.candidate_id" in html
    assert "target_ref: retreat.candidate_id" in html
    assert "bbox_wgs84" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace-edits`, {" in html
    assert "fetch(`${apiBase()}/safety" not in html


def test_pretrip_admin_page_posts_only_local_workspace_routes():
    html = PAGE.read_text(encoding="utf-8")
    shared_script = ASSISTANT_UI_SCRIPT.read_text(encoding="utf-8")

    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decisions`, {" in html
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/route-note-dispositions`, {"
        in html
    )
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decision-apply-plan`, {"
        in html
    )
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/route-note-reviewed-assumptions`, {"
        in html
    )
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/expert-contribution-workspace-apply-result`, {"
        in html
    )
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace-edits`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/import-gpx-preview`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/import-gpx`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/prepare-layers-preview`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/prepare-layers`, {" in html
    assert html.count('method: "POST"') == 13
    assert shared_script.count('method: "POST"') == 1
    assert html.count("body: JSON.stringify({") == 6
    assert html.count("body: JSON.stringify(payload)") == 3
    assert html.count("body: JSON.stringify({...payload, confirm_import: true})") == 1
    assert html.count("body: JSON.stringify({...payload, confirm_prepare: true})") == 1
    assert html.count("body: JSON.stringify(") == 9
    assert html.count('headers: {"Content-Type": "application/json"}') == 9
    assert shared_script.count('headers: {"Content-Type": "application/json"}') == 1
    assert 'headers: {"Content-Type": "application/json"}' in html
    assert "body: JSON.stringify({" in html
    assert "body: JSON.stringify(payload)" in html
    assert "candidate_ref: item.candidate_ref" in html
    assert 'decision: "accepted"' in html
    assert 'decision: "corrected"' in html
    assert 'decision: "rejected"' in html
    assert "correctionSummaryFor(item)" in html
    assert "correction: {" in html
    assert "field_updates: {}" in html
    assert "replacement_ref_ids: []" in html
    assert "persist_to_workspace: true" in html
    assert "persist_to_workspace: true" in html
    assert "operation," in html
    assert "route_note_ref: option.source_route_note_candidate_id" in html
    assert "disposition: state.routeNoteDraftDisposition" in html
    assert "Select a route-note review item before saving a draft option." in html
    assert "Select a route-note draft disposition before saving." in html
    assert "Saved route-note draft option" in html
    assert "Route-note reviewed assumptions written to local workspace only." in html
    assert "Runtime and final handoff remain closed." in html
    assert "Expert contribution workspace apply result written locally." in html
    assert "No final package, MissionGraph, runtime, or Brain writeback was opened." in html
    assert "Corrected from Phase 4 admin local workspace" in html
    assert "Rejected from Phase 4 admin local workspace" in html
    assert "Select a review queue item with candidate_ref before accepting to workspace." in html
    assert "Select a review queue item with candidate_ref before correcting to workspace." in html
    assert "Select a review queue item with candidate_ref before rejecting to workspace." in html
    assert "isCandidateRefDecided(item.candidate_ref)" in html
    assert (
        "already has a decision. Select an undecided review queue item before accepting to workspace."
        in html
    )
    assert (
        "already has a decision. Select an undecided review queue item before correcting to workspace."
        in html
    )
    assert (
        "already has a decision. Select an undecided review queue item before rejecting to workspace."
        in html
    )
    assert "Correct selected review canceled: correction summary is required." in html
    assert (
        'document.getElementById("workspaceCorrectReview").addEventListener("click", correctSelectedReviewToWorkspace)'
        in html
    )
    assert (
        'document.getElementById("workspaceRejectReview").addEventListener("click", rejectSelectedReviewToWorkspace)'
        in html
    )
    assert (
        'document.getElementById("routeNoteDraftSave").addEventListener("click", saveRouteNoteDraftDispositionToWorkspace)'
        in html
    )
    assert (
        'document.getElementById("routeNoteReviewedAssumptions").addEventListener("click", generateRouteNoteReviewedAssumptionsForWorkspace)'
        in html
    )
    assert (
        'document.getElementById("expertContributionApplyResult").addEventListener("click", applyExpertContributionWorkspaceResult)'
        in html
    )
    assert "evidenceCategory(state.selected) === \"review\"" in html
    assert 'method: "PUT"' not in html
    assert 'method: "PATCH"' not in html
    assert 'method: "DELETE"' not in html
    assert "fetch(`${apiBase()}/safety" not in html
    assert "Boolean(state.selected?.candidate_ref)" in html
    assert "await reloadProjectView();" in html
    assert html.count("await reloadProjectView();") >= 5
    assert "fetch(`${apiBase()}/safety" not in html
    assert "PUT" not in html
    assert "PATCH" not in html
    assert "DELETE" not in html


def test_pretrip_admin_page_renders_active_tab_sections_as_read_only_navigation():
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "sectionCountSummary",
        "sectionBoundarySummary",
        "setSectionDetail",
        "activeTabLabel",
        "activeTabSource",
        "tabOverviewPayload",
        "setActiveTabDetail",
        "highlightSectionCard",
        "renderSectionList",
    ):
        assert f"function {function_name}" in html

    assert 'id="sectionList" class="section-list" aria-label="Active tab sections"' in html
    assert "view.tabs[state.activeTab]" in html
    assert "tab?.sections || []" in html
    assert 'button.setAttribute("data-section-id", section.id)' in html
    assert "section.title" in html
    assert "section.status || \"traceable\"" in html
    assert "section.source_path || \"no source path\"" in html
    assert "sectionCountSummary(section)" in html
    assert "sectionBoundarySummary(section)" in html
    assert "section-boundary" in html
    assert 'button.addEventListener("click", () => setSectionDetail(section))' in html
    assert "JSON.stringify(section || {}, null, 2)" in html
    assert 'document.getElementById("detailTitle").textContent = `${activeTabLabel()} overview`;' in html
    assert "pre_trip_planning | fixture-backed planning workspace" in html
    assert "post_analysis | read-only post-planning artifacts" in html
    assert "active_tab: tabId" in html
    assert "section_count: sections.length" in html
    assert "sections.map(section => ({" in html
    assert "setActiveTabDetail(state.view)" in html


def test_pretrip_admin_page_section_click_handler_does_not_add_write_calls():
    html = PAGE.read_text(encoding="utf-8")

    assert "setSectionDetail(section)" in html
    assert "state.selectedSectionId = section?.id || \"\"" in html
    assert "renderSectionList(state.view)" in html
    assert ".section-card.is-selected" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}`)" in html
    assert "fetch(`${apiBase()}/safety" not in html
    assert "PUT" not in html
    assert "PATCH" not in html
    assert "DELETE" not in html


def test_pretrip_admin_view_exposes_fixture_fields_used_by_readiness_strip():
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)

    assert view["readiness"]["status"] == "ready"
    assert view["review_queue"]["counts"]["blocker_count"] == 0
    assert view["review_queue"]["counts"]["warning_count"] == 10
    assert view["review_queue"]["counts"]["review_count"] == 43
    assert view["departure_bundle"]["package"]["status"] == "reviewed"
    assert view["departure_bundle"]["boundary"]["human_review_required_before_departure"] is True
    assert view["departure_bundle"]["boundary"]["not_departure_approval"] is True
    runtime_boundary = view["tabs"]["post_analysis"]["runtime_handoff"]["boundary"]
    assert runtime_boundary["safety_api_calls_allowed"] is False
    assert runtime_boundary["final_runtime_write_allowed"] is False


def test_pretrip_admin_page_fixture_sections_include_decision_log_and_import_queue():
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)
    planning_sections = view["tabs"]["pre_trip_planning"]["sections"]
    review_sections = view["tabs"]["review_workspace"]["sections"]
    section_ids = {section["id"] for section in planning_sections}
    section_titles = {section["title"] for section in planning_sections}
    review_section_ids = {section["id"] for section in review_sections}
    review_section_titles = {section["title"] for section in review_sections}

    assert "review_decision_log" in review_section_ids
    assert "external_import_queue" in review_section_ids
    assert "overpass_evidence" in section_ids
    assert "route_note_review_options" in review_section_ids
    assert "Review Decision Log" in review_section_titles
    assert "External Import Queue" in review_section_titles
    assert "Overpass Vector Evidence" in section_titles
    assert "Route Note Review Options" in review_section_titles
