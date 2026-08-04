from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from scout_contextual_permission_workbench import build_reference_workbench_seed


PROJECT_ID = "permission_api_fixture"
NOW = datetime(2026, 8, 2, 6, 0, tzinfo=timezone.utc)


def _client(
    tmp_path: Path, *, rich_reference: bool = False
) -> tuple[TestClient, Path]:
    workspace_root = tmp_path / "workspace"
    project_root = workspace_root / PROJECT_ID
    seed_path = project_root / "outputs" / "contextual_permission" / "workbench_seed.json"
    seed_path.parent.mkdir(parents=True)
    rules_ref = "candidates/contextual_permission_rules.json"
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "compiled_mission_graph_reviewed_ref": (
                    "outputs/compiled_mission_graph.reviewed.json"
                ),
                "planned_eta_ref": "outputs/planned_eta.json",
                "contextual_permission_rules_ref": rules_ref,
            }
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps({"mission_id": f"mission.{PROJECT_ID}.v1"}),
        encoding="utf-8",
    )
    (project_root / "outputs" / "planned_eta.json").write_text(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "plan_id": f"eta.{PROJECT_ID}.v1",
                "assumption": {
                    "day1_target_node_name": "Reviewed camp",
                    "turn_back_checkpoint_node_name": "Reviewed junction",
                },
                "estimates": [],
            }
        ),
        encoding="utf-8",
    )
    seed = build_reference_workbench_seed(PROJECT_ID)
    seed_path.write_text(seed.model_dump_json(indent=2), encoding="utf-8")
    rules_path = project_root / rules_ref
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_contextual_permission_rules",
                "schema_version": "contextual_permission_rules.v2",
                "project_id": PROJECT_ID,
                "reviewed_baseline_ref": seed.baseline.reviewed_receipt_ref,
                "reviewed_baseline_sha256": seed.baseline.baseline_sha256,
                "reviewed_by_human": True,
                "review_receipt_ref": "reviewed://contextual-permission/rules-v1",
                "review_receipt_sha256": "a" * 64,
                "plan_node_policies": [
                    {
                        "node_id": node.node_id,
                        "mission_day_id": node.mission_day_id,
                        "adjustment_policy": node.adjustment_policy,
                        "minimum_duration_minutes": node.minimum_duration_minutes,
                        "policy_ref": node.source_rule_ref,
                        "policy_sha256": node.source_rule_sha256,
                        "reviewed": True,
                    }
                    for node in seed.remaining_plan
                ],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
        encoding="utf-8",
    )
    if rich_reference:
        project_path = project_root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project.update(
            {
                "reference_segment_timing_ref": "outputs/reference_segment_timing.json",
                "retreat_routes_ref": "candidates/retreat_routes.json",
            }
        )
        project_path.write_text(json.dumps(project), encoding="utf-8")
        labels = ["Start", "Camp One", "CP 020", "Camp Two", "Finish"]
        match_quality = {
            f"node.{index}": {
                "label": label,
                "source_id": "cp.start" if index == 0 else "cp.finish" if index == 4 else f"cp.{index:03d}",
                "source_kind": "checkpoint",
                "route_distance_m": distance,
            }
            for index, (label, distance) in enumerate(
                zip(labels, (0.0, 20_000.0, 40_000.0, 60_000.0, 90_000.0), strict=True)
            )
        }
        segments = [
            {
                "segment_id": f"segment.{index + 1:03d}",
                "from_node_name": labels[index],
                "to_node_name": labels[index + 1],
                "duration_minutes": {
                    "p50": None if index == 1 else 180.0,
                    "p75": None if index == 1 else 240.0,
                },
            }
            for index in range(4)
        ]
        (project_root / "outputs" / "reference_segment_timing.json").write_text(
            json.dumps(
                {
                    "artifact_kind": "reference_segment_timing",
                    "segments": segments,
                    "checkpoint_match_quality": match_quality,
                }
            ),
            encoding="utf-8",
        )
        (project_root / "candidates" / "retreat_routes.json").write_text(
            json.dumps(
                [
                    {
                        "candidate_id": "retreat.reverse-primary",
                        "label": "Return along reversed primary route",
                        "confidence": "medium",
                    }
                ]
            ),
            encoding="utf-8",
        )
    store_root = tmp_path / "permission_store"
    app = create_admin_app(
        pretrip_workspace_root=workspace_root,
        contextual_permission_store_root=store_root,
        now_factory=lambda: NOW,
    )
    return TestClient(app), store_root


def test_dashboard_projection_get_is_project_scoped_and_read_only(tmp_path: Path) -> None:
    client, store_root = _client(tmp_path)

    response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard?lens=replay"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "contextual_permission_dashboard_projection"
    assert payload["project_id"] == PROJECT_ID
    assert payload["current_decision"]["authorized_duration_minutes"] == 6
    assert payload["current_decision"]["observed_duration_minutes"] == 16
    assert payload["risk_budget"]["time_debt_minutes"] == 10
    assert payload["authority"] == {
        "runtime_authorization_performed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_action_performed": False,
        "outbound_transport_invoked": False,
        "external_send_performed": False,
        "hardware_control_performed": False,
    }
    assert not store_root.exists()


def test_candidate_simulation_post_is_explicit_and_no_write(tmp_path: Path) -> None:
    client, store_root = _client(tmp_path)

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/simulations",
        json={
            "action_id": "rest",
            "authorized_duration_minutes": 6,
            "observed_duration_minutes": 36,
            "causes": [
                {
                    "cause_id": "weather.heavy-rain",
                    "source_kind": "weather_fact",
                    "source_ref": "evidence://weather/heavy-rain",
                    "source_sha256": "a" * 64,
                    "verified": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["writes_performed"] is False
    assert payload["replaces_current_decision"] is False
    assert payload["projection"]["inspection_state"] == "SIMULATION_READY"
    assert payload["projection"]["risk_budget"]["unabsorbed_debt_minutes"] == 20
    assert not store_root.exists()


def test_baseline_preview_keeps_human_and_reference_modes_no_write(tmp_path: Path) -> None:
    client, store_root = _client(tmp_path)
    endpoint = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline/preview"

    human = client.post(
        endpoint,
        json={
            "mode": "human_text",
            "human_text": "D0: city - trailhead C0\nD1: C0 - junction - camp C1",
        },
    )
    reference = client.post(
        endpoint,
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )

    assert human.status_code == 200
    assert reference.status_code == 200
    assert human.json()["schema_version"] == reference.json()["schema_version"]
    assert human.json()["source_mode"] == "human_text"
    assert reference.json()["source_mode"] == "reference_gpx"
    assert human.json()["writes_performed"] is False
    assert reference.json()["writes_performed"] is False
    assert not store_root.exists()


def test_reference_gpx_generate_draft_returns_auto_proposal_for_compact_review(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path, rich_reference=True)

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["proposal_profile"] == "ref_gpx_proposal_v1"
    assert payload["proposal_summary"]["day_count"] >= 2
    assert payload["proposal_summary"]["missing_p75_segment_count"] == 1
    assert all(
        day["primary_day_end_proposal"] is not None
        for day in payload["days"]
        if day["day_kind"] == "on_trail"
    )
    assert payload["review_requirements"]["safety_handoff_required"] is True
    assert payload["writes_performed"] is False
    assert not store_root.exists()


def test_safety_emergency_review_uses_one_packet_and_append_only_receipt(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path)
    day_endpoint = (
        f"/admin/pretrip/projects/{PROJECT_ID}/safety-emergency/mission-days/"
        "D1.instance.001/night-review"
    )
    session = client.get(day_endpoint)
    assert session.status_code == 200
    packet = session.json()["alternatives"][0]
    aggregate = session.json()["aggregate"]

    request = {
        "command_context": {
            "session_id": aggregate["session_id"],
            "group_id": aggregate["group_id"],
            "mission_day_instance_id": aggregate["mission_day_instance_id"],
            "membership_revision": aggregate["membership_revision"],
            "expected_baseline_sha256": aggregate["baseline_sha256"],
            "expected_aggregate_sha256": aggregate["aggregate_sha256"],
            "expected_sequence": aggregate["through_sequence"],
            "idempotency_key": "api-review-001",
        },
        "packet_id": packet["packet_id"],
        "packet_sha256": packet["sha256"],
        "mission_day_instance_id": "D1.instance.001",
        "review_generation": 1,
        "reviewed_sequence": 12,
        "decision": "reject_night_travel",
        "reviewer_alias": "leader-01",
        "idempotency_key": "api-review-001",
        "explicit_confirmation": True,
    }
    first = client.post(
        f"{day_endpoint}/{packet['packet_id']}/decisions",
        json=request,
    )
    second = client.post(
        f"{day_endpoint}/{packet['packet_id']}/decisions",
        json=request,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["receipt_sha256"] == second.json()["receipt_sha256"]
    assert first.json()["runtime_authorization_performed"] is False
    assert first.json()["outbound_action_performed"] is False
    event_files = list(store_root.rglob("*.json"))
    recorded = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in event_files
        if "events" in path.parts
    ]
    assert [event["idempotency_key"] for event in recorded] == ["api-review-001"]
    assert recorded[0]["event_kind"] == "night_review_decision_recorded"
    projection = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard?lens=replay"
    ).json()
    assert projection["daily_review"]["state"] == "reviewed"
    assert projection["daily_review"]["selected_alternative_state"] == "rejected"


def test_review_rejects_first_tap_stale_hash_and_packet_path_mismatch(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    day_endpoint = (
        f"/admin/pretrip/projects/{PROJECT_ID}/safety-emergency/mission-days/"
        "D1.instance.001/night-review"
    )
    packet = client.get(day_endpoint).json()["alternatives"][0]
    base = {
        "packet_id": packet["packet_id"],
        "packet_sha256": packet["sha256"],
        "mission_day_instance_id": "D1.instance.001",
        "review_generation": 1,
        "reviewed_sequence": 12,
        "decision": "select_hold_or_bivy",
        "reviewer_alias": "leader-01",
        "idempotency_key": "api-review-rejected",
    }

    first_tap = client.post(
        f"{day_endpoint}/{packet['packet_id']}/decisions",
        json={**base, "explicit_confirmation": False},
    )
    stale = client.post(
        f"{day_endpoint}/{packet['packet_id']}/decisions",
        json={**base, "packet_sha256": "0" * 64, "explicit_confirmation": True},
    )
    mismatch = client.post(
        f"{day_endpoint}/different.packet/decisions",
        json={**base, "explicit_confirmation": True},
    )

    assert first_tap.status_code == 409
    assert first_tap.json()["detail"]["code"] == "explicit_confirmation_required"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "packet_replaced"
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "packet_path_mismatch"


def test_offline_sync_rejects_approval_but_accepts_conservative_intent(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    day_endpoint = (
        f"/admin/pretrip/projects/{PROJECT_ID}/safety-emergency/mission-days/"
        "D1.instance.001/night-review"
    )
    packet = client.get(day_endpoint).json()["alternatives"][0]
    sync_endpoint = f"{day_endpoint}/offline-intents/sync"
    base = {
        "intent_id": "offline-api-001",
        "idempotency_key": "offline-api-001",
        "packet_id": packet["packet_id"],
        "packet_sha256": packet["sha256"],
        "mission_day_instance_id": "D1.instance.001",
        "review_generation": 1,
        "reviewed_sequence": 12,
        "reviewer_alias": "leader-01",
        "device_instance_id": "field-device-01",
        "pending_sync": True,
    }

    approval = client.post(
        sync_endpoint,
        json={**base, "decision": "approve_for_runtime_consideration"},
    )
    refreshed_packet = client.get(day_endpoint).json()["alternatives"][0]
    hold = client.post(
        sync_endpoint,
        json={
            **base,
            "intent_id": "offline-api-002",
            "idempotency_key": "offline-api-002",
            "packet_sha256": refreshed_packet["sha256"],
            "reviewed_sequence": refreshed_packet["reviewed_sequence"],
            "decision": "select_hold_or_bivy",
            "supersedes_intent_id": "offline-api-001",
        },
    )

    assert approval.status_code == 200
    assert approval.json()["status"] == "rejected_sync_audit"
    assert approval.json()["reasons"] == ["offline_approval_forbidden"]
    assert hold.status_code == 200
    assert hold.json()["status"] == "receipt_appended"
    assert hold.json()["runtime_authorization_performed"] is False


def test_missing_seed_is_bounded_blocked_projection_not_server_error(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    project_root = workspace_root / PROJECT_ID
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "compiled_mission_graph_reviewed_ref": (
                    "outputs/compiled_mission_graph.reviewed.json"
                ),
                "planned_eta_ref": "outputs/planned_eta.json",
            }
        ),
        encoding="utf-8",
    )
    for name in ("compiled_mission_graph.reviewed.json", "planned_eta.json"):
        (project_root / "outputs" / name).write_text("{}", encoding="utf-8")
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            contextual_permission_store_root=tmp_path / "store",
        )
    )

    response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["error"]["code"] == "contextual_permission_seed_missing"
    assert response.json()["candidate_only"] is True
    assert response.json()["runtime_safety_truth"] is False


def test_bundled_fixture_has_deterministic_reference_replay() -> None:
    client = TestClient(create_admin_app(now_factory=lambda: NOW))

    response = client.get(
        "/admin/pretrip/projects/chilai_nanhua_day1/contextual-permission-dashboard?lens=replay"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["risk_budget"]["time_debt_minutes"] == 10
    assert payload["lens"] == "replay"


def _command_context_from_aggregate(
    aggregate: dict[str, object], idempotency_key: str
) -> dict[str, object]:
    return {
        "session_id": aggregate["session_id"],
        "group_id": aggregate["group_id"],
        "mission_day_instance_id": aggregate["mission_day_instance_id"],
        "membership_revision": aggregate["membership_revision"],
        "expected_baseline_sha256": aggregate["baseline_sha256"],
        "expected_aggregate_sha256": aggregate["aggregate_sha256"],
        "expected_sequence": aggregate["through_sequence"],
        "idempotency_key": idempotency_key,
    }


def test_cross_page_arrival_command_reduces_the_same_group_aggregate(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    projection_url = (
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard?lens=replay"
    )
    first = client.get(projection_url).json()
    ridge = first["movement_groups"][0]
    aggregate = first["primary_aggregate"]
    endpoint = (
        f"/admin/pretrip/projects/{PROJECT_ID}/safety-emergency/movement-groups/"
        "group.ridge/arrival-dwell"
    )
    payload = {
        "command_context": _command_context_from_aggregate(aggregate, "api-arrival-599"),
        "target_ref": ridge["day_end"]["planned_target_ref"],
        "target_sha256": ridge["day_end"]["planned_target_sha256"],
        "elapsed_seconds": 599,
        "target_match": True,
        "route_progress_match": True,
        "gnss_confidence": "high",
        "zone_exit": False,
        "continued_route_travel": False,
        "unexpected_separation": False,
    }
    observed = client.post(endpoint, json=payload)
    assert observed.status_code == 200
    assert observed.json()["event_kind"] == "arrival_dwell_observed"

    at_599 = client.get(projection_url).json()
    assert at_599["movement_groups"][0]["arrival_dwell"]["elapsed_seconds"] == 599
    current = at_599["primary_aggregate"]
    completed = client.post(
        endpoint,
        json={
            **payload,
            "command_context": _command_context_from_aggregate(
                current, "api-arrival-600"
            ),
            "elapsed_seconds": 600,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["event_kind"] == "day_end_closed"
    closed = client.get(projection_url).json()["movement_groups"][0]
    assert closed["day_end"]["completion"] == "planned_closed"
    assert closed["shelter_hold"]["state"] == "active"
    assert closed["pending_next_day"] == "D2"


def test_baseline_accept_marks_permission_projection_stale_without_runtime_rebind(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    draft_response = client.post(
        f"{prefix}/preview",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()
    saved_response = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "api-save-baseline-001",
            "explicit_confirmation": True,
        },
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    accepted = client.post(
        f"{prefix}/reviews/accept",
        json={
            "candidate_ref": saved["version_ref"],
            "candidate_sha256": saved["version_sha256"],
            "reviewer_alias": "leader-01",
            "idempotency_key": "api-accept-baseline-001",
            "explicit_confirmation": True,
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["active_runtime_session_updated"] is False
    blocked = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["error"]["code"] == "contextual_permission_projection_stale"
    assert blocked.json()["rebuild"]["eligible"] is False

    authoring_remains_available = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )
    assert authoring_remains_available.status_code == 200
    assert authoring_remains_available.json()["writes_performed"] is False

    (tmp_path / "workspace" / PROJECT_ID / "candidates" / "contextual_permission_rules.json").unlink()
    authoring_survives_missing_derived_rules = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )
    assert authoring_survives_missing_derived_rules.status_code == 200
    assert authoring_survives_missing_derived_rules.json()["writes_performed"] is False


def test_explicit_rebuild_binds_reviewed_proposal_without_runtime_authority(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, rich_reference=True)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    generated = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )
    assert generated.status_code == 200
    draft = generated.json()
    requirements = draft["review_requirements"]
    saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "api-rebuild-save-001",
            "explicit_confirmation": True,
        },
    )
    assert saved.status_code == 200
    candidate = saved.json()
    accepted = client.post(
        f"{prefix}/reviews/accept",
        json={
            "candidate_ref": candidate["version_ref"],
            "candidate_sha256": candidate["version_sha256"],
            "reviewer_alias": "leader-01",
            "idempotency_key": "api-rebuild-accept-001",
            "reviewed_day_ids": requirements["required_reviewed_day_ids"],
            "acknowledged_uncertainty_ids": requirements[
                "required_acknowledgment_uncertainty_ids"
            ],
            "safety_handoff_acknowledged": requirements[
                "safety_handoff_required"
            ],
            "explicit_confirmation": True,
        },
    )
    assert accepted.status_code == 200
    reviewed = accepted.json()

    blocked = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["rebuild"]["required"] is True
    assert blocked.json()["rebuild"]["eligible"] is True
    assert blocked.json()["rebuild"]["reviewed_baseline_sha256"] == reviewed[
        "reviewed_baseline_sha256"
    ]

    rebuilt = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
        json={
            "expected_reviewed_baseline_sha256": reviewed[
                "reviewed_baseline_sha256"
            ],
            "idempotency_key": "api-permission-rebuild-001",
            "explicit_confirmation": True,
        },
    )
    assert rebuilt.status_code == 200
    receipt = rebuilt.json()
    assert receipt["reviewed_baseline_sha256"] == reviewed[
        "reviewed_baseline_sha256"
    ]
    assert receipt["rule_review_state"] == "pending_review_only"
    assert receipt["active_runtime_session_updated"] is False
    assert receipt["runtime_safety_truth"] is False
    assert receipt["departure_approval_granted"] is False
    assert receipt["safety_api_called"] is False
    assert receipt["outbound_action_performed"] is False

    rebuilt_again = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
        json={
            "expected_reviewed_baseline_sha256": reviewed[
                "reviewed_baseline_sha256"
            ],
            "idempotency_key": "api-permission-rebuild-001",
            "explicit_confirmation": True,
        },
    )
    assert rebuilt_again.status_code == 200
    assert rebuilt_again.json()["rebuild_sha256"] == receipt["rebuild_sha256"]

    projection = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert projection.status_code == 200
    payload = projection.json()
    assert payload["status"] == "degraded"
    assert payload["baseline"]["baseline_sha256"] == reviewed[
        "reviewed_baseline_sha256"
    ]
    assert payload["baseline"]["accepted_by_human"] is True
    assert payload["baseline"][
        "contextual_permission_rules_reviewed_by_human"
    ] is False
    assert payload["current_decision"]["decision"] == "ESCALATE"
    assert payload["authority"]["runtime_authorization_performed"] is False


def test_baseline_generate_and_patch_endpoints_are_explicit_and_versioned(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    generated = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )
    assert generated.status_code == 200
    draft = generated.json()
    assert draft["writes_performed"] is False
    saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "api-patch-parent-001",
            "explicit_confirmation": True,
        },
    )
    assert saved.status_code == 200
    base = saved.json()
    preview = client.post(
        f"{prefix}/patches/preview",
        json={
            "base_candidate_ref": base["version_ref"],
            "base_candidate_sha256": base["version_sha256"],
            "operations": [
                {
                    "operation": "add_assumption",
                    "assumption": "Review the water fallback before departure.",
                }
            ],
            "conversation_refs": ["conversation://baseline/api-001"],
            "conversation_hashes": ["c" * 64],
        },
    )
    assert preview.status_code == 200
    assert preview.json()["writes_performed"] is False
    child = client.post(
        f"{prefix}/candidates/from-patch",
        json={
            "patch": preview.json(),
            "expected_base_candidate_sha256": base["version_sha256"],
            "idempotency_key": "api-patch-child-002",
            "explicit_confirmation": True,
        },
    )
    assert child.status_code == 200
    assert child.json()["version_id"] != base["version_id"]


def test_daily_review_invalidation_is_generation_bound_and_fail_closed(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    day_endpoint = (
        f"/admin/pretrip/projects/{PROJECT_ID}/safety-emergency/mission-days/"
        "D1.instance.001/night-review"
    )
    first = client.get(day_endpoint).json()
    packet = first["alternatives"][0]
    aggregate = first["aggregate"]
    decision = client.post(
        f"{day_endpoint}/{packet['packet_id']}/decisions",
        json={
            "command_context": _command_context_from_aggregate(
                aggregate, "api-generation-review-001"
            ),
            "packet_id": packet["packet_id"],
            "packet_sha256": packet["sha256"],
            "mission_day_instance_id": packet["mission_day_instance_id"],
            "review_generation": packet["review_generation"],
            "reviewed_sequence": packet["reviewed_sequence"],
            "decision": "reject_night_travel",
            "reviewer_alias": "leader-01",
            "explicit_confirmation": True,
        },
    )
    assert decision.status_code == 200
    current = client.get(day_endpoint).json()["aggregate"]
    invalidated = client.post(
        f"{day_endpoint}/invalidations",
        json={
            "command_context": _command_context_from_aggregate(
                current, "api-generation-invalidate-002"
            ),
            "reason_kind": "team_condition_outside_envelope",
            "source_refs": ["evidence://team/outside-envelope"],
            "source_hashes": ["d" * 64],
            "reviewed_envelope_crossed": True,
            "explicit_confirmation": False,
        },
    )
    assert invalidated.status_code == 200
    renewed = client.get(day_endpoint).json()
    assert renewed["review_generation"] == 2
    assert renewed["state"] == "re_review_required"
    assert renewed["receipts"] == []


def test_offline_field_day_end_sync_uses_typed_server_result(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    projection_url = (
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard?lens=replay"
    )
    projection = client.get(projection_url).json()
    ridge = projection["movement_groups"][0]
    aggregate = projection["primary_aggregate"]
    endpoint = (
        f"/admin/pretrip/projects/{PROJECT_ID}/safety-emergency/movement-groups/"
        "group.ridge/day-end/offline-intents/sync"
    )
    response = client.post(
        endpoint,
        json={
            "intent_id": "offline-api-day-end-001",
            "idempotency_key": "offline-api-day-end-001",
            "command_context": _command_context_from_aggregate(
                aggregate, "offline-api-day-end-001"
            ),
            "target_ref": ridge["day_end"]["planned_target_ref"],
            "target_sha256": ridge["day_end"]["planned_target_sha256"],
            "target_label": ridge["day_end"]["planned_target_label"],
            "target_kind": "planned_day_end",
            "confirmation_kind": "arrived",
            "authorized_on_site_participant": True,
            "participant_alias": "participant-01",
            "uncertainty_acknowledgement": True,
            "explicit_confirmation": True,
            "pending_sync": True,
            "device_local_encrypted": True,
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "receipt_appended"
    assert result["outbound_transport_invoked"] is False
    assert result["external_send_performed"] is False


def test_communication_projection_rollup_and_contact_loss_review_are_bounded(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    base = f"/admin/pretrip/projects/{PROJECT_ID}/safety-emergency"
    projection_url = (
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard?lens=replay"
    )
    projection = client.get(projection_url).json()
    ridge = projection["movement_groups"][0]
    communication = ridge["communication"]
    overdue = client.post(
        f"{base}/movement-groups/group.ridge/communication-events",
        json={
            "command_context": _command_context_from_aggregate(
                projection["primary_aggregate"], "api-contact-overdue-001"
            ),
            "event_kind": "deadline_elapsed",
            "communication_policy_id": communication["policy_id"],
            "communication_policy_sha256": communication["policy_sha256"],
            "route_scope_match": True,
            "acknowledged_receipt_ref": None,
            "compound_evidence_refs": [],
            "retroactive": False,
        },
    )
    assert overdue.status_code == 200
    current_projection = client.get(projection_url).json()
    current = current_projection["movement_groups"][0]
    communication_view = client.get(
        f"{base}/movement-groups/group.ridge/communication"
    )
    assert communication_view.status_code == 200
    assert communication_view.json()["communication"]["state"] == "contact_overdue"
    assert communication_view.json()["authority"]["external_send_performed"] is False

    review = client.post(
        f"{base}/movement-groups/group.ridge/contact-loss-reviews",
        json={
            "command_context": _command_context_from_aggregate(
                current_projection["primary_aggregate"], "api-contact-review-001"
            ),
            "communication_policy_id": current["communication"]["policy_id"],
            "communication_policy_sha256": current["communication"]["policy_sha256"],
            "decision": "continue_monitoring",
            "overdue_fact_refs": [
                "automatic://communication/contact-overdue/group.ridge"
            ],
            "overdue_fact_hashes": ["a" * 64],
            "compound_evidence_refs": [],
            "compound_evidence_hashes": [],
            "safety_emergency_trigger_refs": [],
            "safety_emergency_trigger_hashes": [],
            "reviewer_alias": "leader-01",
            "explicit_confirmation": True,
        },
    )
    assert review.status_code == 200
    assert review.json()["authority"]["outbound_transport_invoked"] is False
    rollup = client.get(f"{base}/communication/roll-up")
    assert rollup.status_code == 200
    assert rollup.json()["authority"]["external_send_performed"] is False
    ridge_rollup = next(
        item
        for item in rollup.json()["groups"]
        if item["movement_group_id"] == "group.ridge"
    )
    assert ridge_rollup["state"] == "contact_loss_review_required"
    assert ridge_rollup["emergency_declared"] is False
