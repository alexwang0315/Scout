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
    assert 'src="/admin/scout-assistant-ui.js"' in html
    assert 'id="readinessStrip"' in html
    assert "map frame" not in html.lower()
    assert 'id="map"' in html
    assert 'id="evidenceTree"' in html
    assert 'id="jsonPane"' in html
    assert 'id="sectionList"' in html
    assert "grid-template-rows: auto minmax(180px, .95fr) minmax(260px, 1.05fr);" in html
    assert ".assistant-panel" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html
    assert "CP / Segment Frame" in html
    assert "Pre-trip planning" in html
    assert "Post-analysis" in html
    assert "segment-overlay" in html
    assert "map-highlight" in html
    assert "mapTargetsFor" in html
    assert "map_target_ids" in html
    assert "selectEvidence" in html
    assert "highlightMapFor" in html
    assert "data-source-id" in html
    assert "data-tree-category" in html
    assert "data-tree-status" in html
    assert ".route-note" in html


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

    assert 'id="featureEdit" class="tool-button" type="button" disabled' in html
    assert 'id="addCheckpoint" class="tool-button" type="button" disabled' in html
    assert 'id="externalDataImport" class="tool-button" type="button" disabled' in html
    assert "summary only" in html
    assert "raw_samples" not in html


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
    assert 'data-layer="route-notes"' in html
    assert 'data-layer="weather-api"' in html
    assert "OSM_TILE_URL_TEMPLATE" in html
    assert "OSM_PUBLIC_TILE_URL_TEMPLATE" in html
    assert "OSM_LOCAL_TILE_URL_TEMPLATE" in html
    assert "const OSM_TARGET_ZOOM = 17" in html
    assert "const OSM_MAX_TILES = 64" in html
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
    assert "function renderWeatherOverlay" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/weather-overlay" in html
    assert "state.weatherOverlay" in html
    assert "Weather API overlay" in html
    assert html.index('data-layer-group": "imagery"') < html.index(
        'data-layer-group": "osm"'
    )
    assert html.index("renderRasterImagery(imageryGroup") < html.index(
        "renderOsmBasemap(osmGroup"
    )
    assert html.index('data-layer-group": "osm"') < html.index(
        'data-layer-group": "terrain"'
    )
    assert html.index('data-layer-group": "terrain"') < html.index(
        'data-layer-group": "weather-api"'
    )


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
    assert 'role="status" aria-live="polite"' in html
    assert 'id="featureEdit" class="tool-button" type="button" disabled' in html
    assert 'id="addCheckpoint" class="tool-button" type="button" disabled' in html
    assert 'id="removeCheckpoint" class="tool-button" type="button" disabled' in html
    assert 'id="addRetreatRoute" class="tool-button" type="button" disabled' in html
    assert 'id="removeRetreatRoute" class="tool-button" type="button" disabled' in html
    assert 'id="externalDataImport" class="tool-button" type="button" disabled' in html


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
    assert html.count('method: "POST"') == 8
    assert shared_script.count('method: "POST"') == 1
    assert html.count("body: JSON.stringify({") == 4
    assert html.count('headers: {"Content-Type": "application/json"}') == 4
    assert shared_script.count('headers: {"Content-Type": "application/json"}') == 1
    assert 'headers: {"Content-Type": "application/json"}' in html
    assert "body: JSON.stringify({" in html
    assert "candidate_ref: item.candidate_ref" in html
    assert 'decision: "accepted"' in html
    assert 'decision: "corrected"' in html
    assert 'decision: "rejected"' in html
    assert "correctionSummaryFor(item)" in html
    assert "correction: {" in html
    assert "field_updates: {}" in html
    assert "replacement_ref_ids: []" in html
    assert "persist_to_workspace: true" in html
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
    assert view["review_queue"]["counts"]["warning_count"] == 9
    assert view["review_queue"]["counts"]["review_count"] == 33
    assert view["departure_bundle"]["package"]["status"] == "reviewed"
    assert view["departure_bundle"]["boundary"]["human_review_required_before_departure"] is True
    assert view["departure_bundle"]["boundary"]["not_departure_approval"] is True
    runtime_boundary = view["tabs"]["post_analysis"]["runtime_handoff"]["boundary"]
    assert runtime_boundary["safety_api_calls_allowed"] is False
    assert runtime_boundary["final_runtime_write_allowed"] is False


def test_pretrip_admin_page_fixture_sections_include_decision_log_and_import_queue():
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)
    planning_sections = view["tabs"]["pre_trip_planning"]["sections"]
    section_ids = {section["id"] for section in planning_sections}
    section_titles = {section["title"] for section in planning_sections}

    assert "review_decision_log" in section_ids
    assert "external_import_queue" in section_ids
    assert "route_note_review_options" in section_ids
    assert "Review Decision Log" in section_titles
    assert "External Import Queue" in section_titles
    assert "Route Note Review Options" in section_titles
