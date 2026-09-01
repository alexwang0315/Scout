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
    assert 'data-load-living' in html
    assert 'data-bind="livingStatus"' in html
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
    assert 'LIVING_ENDPOINT = "/admin/dashboard/living"' in html
    assert "payloadFromLivingProjection" in html
    assert "loadLivingProjection" in html
    assert "syncLivingDecision" in html
    assert '`${LIVING_ENDPOINT}/approvals`' in html
    assert "confirm_sandbox_action: true" in html
    assert "Simulator receipt recorded. No real transport or delivery occurred." in html
    assert "simulated_delivery_verified" not in html
    assert 'data-bind="pathStateTitle"' in html
    assert '"Shadow Reducer Candidate"' in html
    assert "Transport outcome" in html
    assert "production=false" in html
    assert "Verified delivery" not in html
    assert "max-width: 100vw" in html
    assert ".desktop-console {" in html
    assert "display: none;" in html

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
    assert "Emergency Call Out executor admission v0" in reducer_text
    assert "execute_emergency_call_out()" in reducer_text
    assert "run_emergency_call_out_dry_run()" in reducer_text
    assert "blocked_production_executor_unavailable" in reducer_text
    assert "Production gate residency audit v0" in reducer_text
    assert "build_production_gate_residency_audit()" in reducer_text
    assert "Production emergency approval preflight v0" in reducer_text
    assert "evaluate_production_emergency_approval()" in reducer_text
    assert "Approved transport executor selection preflight v0" in reducer_text
    assert "evaluate_approved_transport_executor_selection()" in reducer_text
    assert "Production transport release and delivery closure v0" in reducer_text
    assert "evaluate_production_transport_release()" in reducer_text
    assert "verify_production_delivery_evidence()" in reducer_text
    assert "evaluate_production_emergency_workflow_completion()" in reducer_text
    assert "Weather/environment live-evidence contract audit v0" in reducer_text
    assert "build_production_live_evidence_contract_audit()" in reducer_text
    assert "Weather/environment live-observation bridge v0" in reducer_text
    assert "build_runtime_safety_gate_events_from_live_observations()" in reducer_text
    assert "Phase 1 runtime promotion readiness gate v0" in reducer_text
    assert "evaluate_phase1_runtime_promotion_readiness()" in reducer_text
    assert "Phase 1 writer invocation guard v0" in reducer_text
    assert "invoke_phase1_runtime_promotion_writer()" in reducer_text
    assert "Production transport invocation guard v0" in reducer_text
    assert "evaluate_production_transport_invocation_guard()" in reducer_text
    assert "Live provider connector request contract v0" in reducer_text
    assert "evaluate_production_live_provider_request_contract()" in reducer_text
    assert "Live connector health executor invocation guard v0" in reducer_text
    assert "evaluate_live_connector_health_executor_invocation_guard()" in reducer_text
    assert "Live connector health executor harness v0" in reducer_text
    assert "execute_live_connector_health_check_with_client()" in reducer_text
    assert "Live provider connector health receipt intake v0" in reducer_text
    assert "build_live_provider_connector_manifest_from_health_receipt()" in reducer_text
    assert "Live provider response receipt intake v0" in reducer_text
    assert "build_live_observation_from_provider_response_receipt()" in reducer_text
    assert "Live field/device validation receipt intake v0" in reducer_text
    assert "build_live_field_device_validation_intake()" in reducer_text
    assert "Live field/device validator invocation guard v0" in reducer_text
    assert "evaluate_live_field_device_validator_invocation_guard()" in reducer_text
    assert "Live field/device validator executor harness v0" in reducer_text
    assert "execute_live_field_device_validation_with_client()" in reducer_text
    assert "Live freshness attestor invocation guard v0" in reducer_text
    assert "evaluate_live_freshness_attestor_invocation_guard()" in reducer_text
    assert "Live freshness attestor executor harness v0" in reducer_text
    assert "execute_live_freshness_attestation_check_with_client()" in reducer_text
    assert "Live freshness attestation receipt intake v0" in reducer_text
    assert "build_live_freshness_attestation_intake()" in reducer_text
    assert "Live provider executor effect-boundary readiness v0" in reducer_text
    assert "evaluate_live_provider_executor_effect_boundary_readiness()" in reducer_text
    assert "Live provider executor invocation guard v0" in reducer_text
    assert "evaluate_live_provider_executor_invocation_guard()" in reducer_text
    assert "Live provider executor harness v0" in reducer_text
    assert "execute_live_provider_request_with_client()" in reducer_text
    assert "Live provider effect receipt intake v0" in reducer_text
    assert "build_provider_response_receipt_from_provider_effect_receipt()" in reducer_text
    assert "Production transport effect receipt intake v0" in reducer_text
    assert "build_delivery_evidence_from_transport_effect_receipt()" in reducer_text
    assert "Production transport executor effect-boundary readiness v0" in reducer_text
    assert (
        "evaluate_production_transport_executor_effect_boundary_readiness()"
        in reducer_text
    )
    assert "Production transport executor harness v0" in reducer_text
    assert "execute_production_transport_with_client()" in reducer_text
    assert "Production cutover qualification audit v0" in reducer_text
    assert "evaluate_production_safety_cutover_readiness()" in reducer_text
    assert "Production cutover qualification artifact writer v0" in reducer_text
    assert "write_production_safety_cutover_readiness_audit()" in reducer_text
    assert "run_production_safety_cutover_readiness_audit()" in reducer_text
    assert "Area-specific qualification bundle admission v0" in reducer_text
    assert "PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS" in reducer_text
    assert "evaluate_production_safety_qualification_bundle()" in reducer_text
    assert "Qualification bundle admission CLI bridge v0" in reducer_text
    assert "run_production_safety_qualification_bundle_admission()" in reducer_text
    assert "write_production_safety_qualification_receipt()" in reducer_text
    assert "Qualification claim freshness/stale-binding gate v0" in reducer_text
    assert "blocked_stale_required_claims" in reducer_text
    assert "evidence_observed_at" in reducer_text
    assert "Qualification evidence source-integrity verifier v0" in reducer_text
    assert "verify_production_safety_qualification_source_integrity()" in reducer_text
    assert "source_integrity_verified" in reducer_text
    assert "Source-integrity-bound qualification admission v0" in reducer_text
    assert "blocked_source_integrity_unverified" in reducer_text
    assert "--source-package" in reducer_text
    assert "Production qualification dossier validator v0" in reducer_text
    assert "run_production_safety_qualification_dossier()" in reducer_text
    assert "dossier_ready_for_production_cutover" in reducer_text
    assert "Qualification threat-coverage audit v0" in reducer_text
    assert (
        "evaluate_production_safety_qualification_threat_coverage()"
        in reducer_text
    )
    assert "blocked_missing_qualification_coverage" in reducer_text
    assert "--threat-coverage" in reducer_text
    assert "Threat-coverage evidence source-integrity v0" in reducer_text
    assert (
        "verify_production_safety_qualification_threat_coverage_source_integrity()"
        in reducer_text
    )
    assert "blocked_source_integrity_unverified" in reducer_text
    assert "--threat-coverage-source-package" in reducer_text
    assert "Production qualification gap plan v0" in reducer_text
    assert "evaluate_production_safety_qualification_gap_plan()" in reducer_text
    assert "blocked_production_qualification_gaps_open" in reducer_text
    assert "--gap-plan" in reducer_text
    assert "Production qualification evidence request pack v0" in reducer_text
    assert (
        "build_production_safety_qualification_evidence_request_pack()"
        in reducer_text
    )
    assert "evidence_request_pack_ready" in reducer_text
    assert "--evidence-request-pack" in reducer_text
    assert (
        "Production qualification evidence request fulfillment intake v0"
        in reducer_text
    )
    assert (
        "evaluate_production_safety_qualification_evidence_fulfillment()"
        in reducer_text
    )
    assert "blocked_missing_requested_evidence" in reducer_text
    assert "--evidence-fulfillment-manifest" in reducer_text
    assert (
        "Production qualification fulfillment source-integrity v0"
        in reducer_text
    )
    assert (
        "verify_production_safety_qualification_evidence_fulfillment_source_integrity()"
        in reducer_text
    )
    assert "blocked_fulfillment_source_integrity_unverified" in reducer_text
    assert "--evidence-fulfillment-source-package" in reducer_text
    assert "Production qualification remediation readiness v0" in reducer_text
    assert (
        "evaluate_production_safety_qualification_remediation_readiness()"
        in reducer_text
    )
    assert "ready_for_dossier_rerun" in reducer_text
    assert "--remediation-gap-plan" in reducer_text
    assert "Production qualification external action packet v0" in reducer_text
    assert (
        "build_production_safety_qualification_external_action_packet()"
        in reducer_text
    )
    assert "external_actions_ready_for_operator_authorization" in reducer_text
    assert "--external-action-remediation" in reducer_text
    assert (
        "Production qualification external authorization intake v0"
        in reducer_text
    )
    assert (
        "evaluate_production_safety_qualification_external_authorization()"
        in reducer_text
    )
    assert "external_authorization_recorded" in reducer_text
    assert "--external-authorization-packet" in reducer_text
    assert "Production qualification external invocation guard v0" in reducer_text
    assert (
        "evaluate_production_safety_qualification_external_invocation()"
        in reducer_text
    )
    assert "external_invocation_handoff_recorded" in reducer_text
    assert "--external-invocation-authorization-report" in reducer_text
    assert (
        "Production qualification external result receipt intake v0"
        in reducer_text
    )
    assert (
        "evaluate_production_safety_qualification_external_result_intake()"
        in reducer_text
    )
    assert "external_results_recorded" in reducer_text
    assert "--external-result-invocation-report" in reducer_text
    assert (
        "Production qualification external result evidence bridge v0"
        in reducer_text
    )
    assert (
        "build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results()"
        in reducer_text
    )
    assert "external_result_bridge_ready" in reducer_text
    assert "--external-result-bridge-request-pack" in reducer_text
    assert (
        "Production qualification external result remediation closure v0"
        in reducer_text
    )
    assert (
        "evaluate_production_safety_qualification_external_result_remediation_closure()"
        in reducer_text
    )
    assert "external_result_remediation_ready_for_dossier_rerun" in reducer_text
    assert "--external-result-closure-gap-plan" in reducer_text
    assert "Phase 1 writer production deployment readiness v0" in reducer_text
    assert "evaluate_phase1_writer_production_deployment_readiness()" in reducer_text
    assert "Cached Rudy+TW tile layer" in reducer_text
    assert "Cached imagery tile layer" in reducer_text
    assert "CP/MCP layer" in reducer_text
    assert "authenticated production approval preflight" in reducer_text
    assert "verified delivery" in reducer_text
    assert "Emergency Mobile Approval UI v0" in workspace_text
    assert "bottom evidence frame tabs" in workspace_text
    assert "/admin/pretrip/projects/{project_id}?compact=1" in workspace_text
    assert "/admin/pretrip/projects/{project_id}/debug-projection" in workspace_text
    assert "/admin/pretrip/projects/{project_id}/admin-projection" in workspace_text
    assert "read-only GET" in workspace_text
