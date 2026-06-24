from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "docs" / "emergency" / "scout-emergency-mobile-approval-v0.html"
REDUCER_SPEC = ROOT / "docs" / "specs" / "scout-runtime-multi-gate-safety-reducer.md"
PHYSIOLOGIC_SPEC = ROOT / "docs" / "specs" / "scout-runtime-physiologic-gate.md"
WORKSPACE_SPEC = ROOT / "docs" / "specs" / "scout-workspace-layout.md"


def test_emergency_mobile_approval_ui_v0_contract() -> None:
    html = UI_PATH.read_text(encoding="utf-8")

    assert 'data-emergency-ui-version="v0"' in html
    assert 'data-emergency-surface="mobile"' in html
    assert 'data-emergency-surface="desktop"' in html
    assert 'data-map-surface="mobile"' in html
    assert 'data-map-surface="desktop"' in html
    assert 'data-file-input' in html
    assert 'data-project-input' in html
    assert 'data-load-workspace' in html
    assert 'data-artifact-preview="mobile"' in html
    assert 'data-artifact-preview="desktop"' in html
    assert 'data-evidence-frame="mobile"' in html
    assert 'data-evidence-frame="desktop"' in html
    assert 'data-evidence-tab="approval"' in html
    assert 'data-evidence-tab="packet"' in html
    assert 'data-evidence-tab="workspace"' in html
    assert 'data-evidence-panel="approval"' in html
    assert 'data-evidence-panel="packet"' in html
    assert 'data-evidence-panel="workspace"' in html
    assert "selectEvidenceTab" in html
    assert "selectAdjacentEvidenceTab" in html
    assert "Emergency Package Draft" in html
    assert "Workspace Resources" in html
    assert html.index("Production Path State") < html.index("Workspace Resources")
    assert html.index("Offline Map") < html.index("Workspace Resources")
    assert "WORKSPACE_LAYOUT_VERSION" in html
    assert "scout.workspace.v1" in html
    assert "workspaceResourcePaths" in html
    assert "fetchWorkspaceJson" in html
    assert "/admin/pretrip/projects/" in html
    assert "admin-projection" in html
    assert "debug-projection" in html
    assert "debug-projection-events" in html
    assert "workspace_source_refs" in html
    assert "workspace_endpoint_refs" in html
    assert "scout.adminApiBase" in html
    assert "scout.emergencyProjectId" in html
    assert "Production Path State" in html
    assert "Quick Decision" in html
    assert "Decision Controls" in html
    assert "Offline Map" in html
    assert "Emergency Call Out" in html
    assert "Cached Rudy+TW" in html
    assert "Cached Imagery" in html
    assert "sent=false" in html
    assert "scout_emergency_approval_action" in html
    assert "external_send_performed: false" in html
    assert "safety_api_called: false" in html
    assert "phase1_mutation_requested: false" in html
    assert "raw_health_payload_shared: false" in html
    assert "precise_coordinates_shared: false" in html
    assert "grid-template-columns: 420px minmax(620px, 1fr)" in html
    assert 'data-gate="physiologic_gate"' in html
    assert 'class="physio-icon"' in html
    assert 'data-state="danger"' in html
    assert 'data-callout="message"' in html
    assert 'data-callout="voice"' in html
    assert "message_draft" in html
    assert "voice_call_script" in html
    assert "activeLayers" in html
    assert "layerAliases" in html

    for decision in (
        "approve_send",
        "deny_send",
        "review_5",
        "review_10",
        "downgrade_request",
        "call_now",
        "copy_packet",
        "retreat_camp",
    ):
        assert f'data-decision="{decision}"' in html

    for layer_toggle in (
        "rudy-twmap",
        "imagery",
        "overpass",
        "segments",
        "checkpoints",
        "route-notes",
        "terrain",
    ):
        assert f'data-layer-toggle="{layer_toggle}"' in html

    for layer_group in (
        "imagery",
        "rudy-twmap",
        "terrain",
        "overpass",
        "segments",
        "checkpoints",
        "mcp",
        "route-notes",
    ):
        assert f'data-layer-group="{layer_group}"' in html

    forbidden_runtime_paths = (
        "/safety/",
        "XMLHttpRequest",
        "WebSocket",
        "sendBeacon",
        "method:",
        "POST",
        "Date.now",
        "new Date",
    )
    for forbidden in forbidden_runtime_paths:
        assert forbidden not in html


def test_emergency_mobile_approval_ui_v0_is_documented_in_specs() -> None:
    reducer_text = REDUCER_SPEC.read_text(encoding="utf-8")
    physiologic_text = PHYSIOLOGIC_SPEC.read_text(encoding="utf-8")
    workspace_text = WORKSPACE_SPEC.read_text(encoding="utf-8")

    for text in (reducer_text, physiologic_text):
        assert "docs/emergency/scout-emergency-mobile-approval-v0.html" in text
        assert "mobile and desktop" in text
        assert "offline-map preview" in text
        assert "sent=false" in text
        assert "does not call `/safety/*`" in text or "does not call transport" in text

    assert "Emergency approval UI v0" in physiologic_text
    assert "iconized physiologic gate status" in physiologic_text
    assert "message / voice callout artifact preview" in physiologic_text
    assert "cached layer toggles" in physiologic_text
    assert "Emergency Mobile Approval UI v0" in reducer_text
    assert "icon-first production path status" in reducer_text
    assert "bottom evidence frame tabs" in reducer_text
    assert "Emergency Call Out" in reducer_text
    assert "Cached Rudy+TW tile layer" in reducer_text
    assert "Cached imagery tile layer" in reducer_text
    assert "CP/MCP layer" in reducer_text
    assert "authenticated production workflow" in reducer_text
    assert "verified delivery" in reducer_text
    assert "Emergency Mobile Approval UI v0" in workspace_text
    assert "bottom evidence frame tabs" in workspace_text
    assert "/admin/pretrip/projects/{project_id}?compact=1" in workspace_text
    assert "/admin/pretrip/projects/{project_id}/debug-projection" in workspace_text
    assert "/admin/pretrip/projects/{project_id}/admin-projection" in workspace_text
    assert "read-only GET" in workspace_text
