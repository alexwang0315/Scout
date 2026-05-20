import json
from pathlib import Path

from pretrip_implementation_status import (
    build_pretrip_implementation_status_manifest,
    load_pretrip_implementation_status_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
STATUS_FIXTURE = ROOT / "tests" / "fixtures" / "pretrip" / "implementation_status.json"


def test_builds_deterministic_implementation_status_manifest():
    first = build_pretrip_implementation_status_manifest()
    second = build_pretrip_implementation_status_manifest()

    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")
    assert first.to_dict() == load_pretrip_implementation_status_fixture(STATUS_FIXTURE)


def test_manifest_maps_phase4_milestones_and_marks_ui_not_started():
    manifest = build_pretrip_implementation_status_manifest().to_dict()
    milestones = {entry["milestone"]: entry for entry in manifest["milestones"]}

    assert list(milestones) == [
        "0",
        "1",
        "2",
        "2A",
        "3",
        "4",
        "5",
        "6",
        "6A",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "4.5",
        "4.5A",
        "4.5B",
        "4.5C",
        "4.5D",
        "4.5E",
        "4.5F",
        "4.5G",
        "4.5H",
        "4.5I",
        "4.5J",
        "4.5K",
        "4.5L",
        "4.5M",
        "4.5N",
        "4.5O",
        "4.5P",
        "4.5Q",
        "4.5R",
        "4.5S",
        "4.5T",
        "4.5U",
        "4.5V",
        "4.5W",
        "4.5X",
        "4.5Y",
        "4.5Z",
        "4.5AA",
        "4.5AB",
        "4.5AC",
        "4.5AD",
        "4.5AE",
        "4.5AF",
        "4.5AG",
        "4.5AH",
        "4.5AI",
        "4.5AJ",
        "4.5AK",
        "4.5AL",
        "4.5AM",
        "4.5AN",
        "4.5AO",
        "4.5AP",
    ]
    for milestone_id in [
        "0",
        "1",
        "2",
        "2A",
        "3",
        "4",
        "5",
        "6",
        "6A",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "4.5",
        "4.5A",
        "4.5B",
        "4.5C",
        "4.5D",
        "4.5E",
        "4.5F",
        "4.5G",
        "4.5H",
        "4.5I",
        "4.5J",
        "4.5K",
        "4.5L",
        "4.5M",
        "4.5N",
        "4.5O",
        "4.5P",
        "4.5Q",
        "4.5R",
        "4.5S",
        "4.5T",
        "4.5U",
        "4.5V",
        "4.5W",
        "4.5X",
        "4.5Y",
        "4.5Z",
        "4.5AA",
        "4.5AB",
        "4.5AC",
        "4.5AD",
        "4.5AE",
        "4.5AF",
        "4.5AG",
        "4.5AH",
        "4.5AI",
        "4.5AJ",
        "4.5AK",
        "4.5AL",
        "4.5AM",
        "4.5AN",
        "4.5AO",
        "4.5AP",
    ]:
        milestone = milestones[milestone_id]
        assert milestone["implementation_status"] == "implemented"
        assert milestone["modules"]
        assert milestone["tests"]
        assert milestone["fixture_refs"]
        assert milestone["release_check_coverage"]["covered"] is True
        assert milestone["release_check_coverage"]["commands"] == [
            "phase4_focused_suite",
            "phase4_release_check",
        ]

    ui = milestones["7"]
    assert ui["title"] == "Minimal Admin UI"
    assert ui["implementation_status"] == "implemented"
    assert ui["modules"] == [
        "pretrip_admin_view.py",
        "pretrip_review_draft.py",
        "pretrip_review_draft_fixture.py",
        "admin_api.py",
        "docs/admin/phase4-pretrip-planning.html",
    ]
    assert ui["tests"] == [
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_admin_page.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_pretrip_review_draft.py",
        "tests/test_pretrip_review_draft_fixture.py",
    ]
    assert ui["fixture_refs"] == [
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/reviews/review_draft_log.json",
    ]
    assert ui["release_check_coverage"]["check_names"] == [
        "pretrip_admin_ui",
        "review_draft_log",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_8 = milestones["8"]
    assert milestone_8["title"] == (
        "Fixture-Only Review Decisions and External Import Requests"
    )
    assert milestone_8["modules"] == [
        "pretrip_review_decision_log.py",
        "pretrip_external_import_queue.py",
    ]
    assert milestone_8["tests"] == [
        "tests/test_pretrip_review_decision_log.py",
        "tests/test_pretrip_external_import_queue.py",
    ]
    assert milestone_8["release_check_coverage"]["check_names"] == [
        "review_decision_log",
        "external_import_queue",
    ]

    milestone_9 = milestones["9"]
    assert milestone_9["title"] == "Fixture-Backed Admin Decision Write Contract"
    assert milestone_9["modules"] == [
        "admin_api.py",
        "pretrip_review_decision_apply.py",
    ]
    assert milestone_9["tests"] == [
        "tests/test_pretrip_admin_api.py",
        "tests/test_pretrip_review_decision_apply.py",
    ]
    assert milestone_9["release_check_coverage"]["check_names"] == [
        "review_decision_apply_plan",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_10 = milestones["10"]
    assert milestone_10["title"] == "Append-Only Local Review Decision Store"
    assert milestone_10["modules"] == ["pretrip_review_decision_store.py"]
    assert milestone_10["tests"] == ["tests/test_pretrip_review_decision_store.py"]
    assert milestone_10["release_check_coverage"]["check_names"] == [
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_11 = milestones["11"]
    assert milestone_11["title"] == "Optional Local Workspace Decision Persistence"
    assert milestone_11["modules"] == [
        "admin_api.py",
        "pretrip_review_decision_apply.py",
    ]
    assert milestone_11["tests"] == [
        "tests/test_pretrip_admin_api.py",
        "tests/test_pretrip_review_decision_apply.py",
    ]
    assert milestone_11["release_check_coverage"]["check_names"] == [
        "review_decision_apply_plan",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_12 = milestones["12"]
    assert milestone_12["title"] == "Workspace Review Decision Apply-Plan Writer"
    assert milestone_12["modules"] == [
        "pretrip_review_decision_apply_store.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_12["tests"] == [
        "tests/test_pretrip_review_decision_apply_store.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_12["release_check_coverage"]["check_names"] == [
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_13 = milestones["13"]
    assert milestone_13["title"] == "Local Workspace Project and Apply-Plan Admin Endpoint"
    assert milestone_13["modules"] == [
        "pretrip_workspace_project.py",
        "admin_api.py",
    ]
    assert milestone_13["tests"] == [
        "tests/test_pretrip_workspace_project.py",
        "tests/test_pretrip_admin_api.py",
    ]
    assert milestone_13["release_check_coverage"]["check_names"] == [
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_14 = milestones["14"]
    assert milestone_14["title"] == "Admin-Created Metadata Workspace"
    assert milestone_14["modules"] == [
        "admin_api.py",
        "pretrip_workspace_project.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_14["tests"] == [
        "tests/test_pretrip_admin_api.py",
        "tests/test_pretrip_workspace_project.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_14["release_check_coverage"]["check_names"] == [
        "admin_workspace_project_creation_contract",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_15 = milestones["15"]
    assert milestone_15["title"] == "Local Workspace Admin Write Controls"
    assert milestone_15["modules"] == [
        "docs/admin/phase4-pretrip-planning.html",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_15["tests"] == [
        "tests/test_pretrip_admin_page.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_15["release_check_coverage"]["check_names"] == [
        "admin_ui_local_workspace_write_controls",
        "admin_workspace_project_creation_contract",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_16 = milestones["16"]
    assert milestone_16["title"] == "Local Workspace Reject Review Control"
    assert milestone_16["modules"] == [
        "docs/admin/phase4-pretrip-planning.html",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_16["tests"] == [
        "tests/test_pretrip_admin_page.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_16["release_check_coverage"]["check_names"] == [
        "admin_ui_local_workspace_write_controls",
        "admin_workspace_project_creation_contract",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_17 = milestones["17"]
    assert milestone_17["title"] == "Review Decision Duplicate Candidate Guard"
    assert milestone_17["modules"] == ["pretrip_review_decision_store.py"]
    assert milestone_17["tests"] == [
        "tests/test_pretrip_review_decision_store.py",
        "tests/test_pretrip_admin_api.py",
    ]
    assert milestone_17["release_check_coverage"]["check_names"] == [
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_18 = milestones["18"]
    assert milestone_18["title"] == "Local Workspace Corrected Review Control"
    assert milestone_18["modules"] == [
        "docs/admin/phase4-pretrip-planning.html",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_18["tests"] == [
        "tests/test_pretrip_admin_page.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_18["release_check_coverage"]["check_names"] == [
        "admin_ui_local_workspace_write_controls",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_19 = milestones["19"]
    assert milestone_19["title"] == "Workspace-Aware Admin View Overlay"
    assert milestone_19["modules"] == [
        "pretrip_admin_view.py",
        "admin_api.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_19["tests"] == [
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_19["release_check_coverage"]["check_names"] == [
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_20 = milestones["20"]
    assert milestone_20["title"] == "Review Decision Correction Detail Exposure"
    assert milestone_20["modules"] == ["pretrip_admin_view.py"]
    assert milestone_20["tests"] == ["tests/test_pretrip_admin_view.py"]
    assert milestone_20["release_check_coverage"]["check_names"] == [
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_21 = milestones["21"]
    assert milestone_21["title"] == "Expert Contribution Memory Seed Candidates"
    assert milestone_21["modules"] == [
        "pretrip_expert_contribution.py",
        "pretrip_admin_view.py",
        "pretrip_artifact_manifest.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_21["tests"] == [
        "tests/test_pretrip_expert_contribution.py",
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_artifact_manifest.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_21["release_check_coverage"]["check_names"] == [
        "expert_contribution_log",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_22 = milestones["22"]
    assert milestone_22["title"] == "GPX Waypoint Route Note Candidates"
    assert milestone_22["modules"] == [
        "pretrip_route_note_candidates.py",
        "pretrip_admin_view.py",
        "pretrip_artifact_manifest.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_22["tests"] == [
        "tests/test_pretrip_route_note_candidates.py",
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_artifact_manifest.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_22["release_check_coverage"]["check_names"] == [
        "route_note_candidates",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_23 = milestones["23"]
    assert milestone_23["title"] == "Route Note Ln Proposal Candidates"
    assert milestone_23["modules"] == [
        "pretrip_route_note_ln_proposals.py",
        "pretrip_review_queue.py",
        "pretrip_admin_view.py",
        "pretrip_artifact_manifest.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_23["tests"] == [
        "tests/test_pretrip_route_note_ln_proposals.py",
        "tests/test_pretrip_review_queue.py",
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_artifact_manifest.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_23["release_check_coverage"]["check_names"] == [
        "route_note_ln_proposals",
        "review_queue_manifest",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_24 = milestones["24"]
    assert milestone_24["title"] == "Route Note Review Options"
    assert milestone_24["modules"] == [
        "pretrip_route_note_review_options.py",
        "pretrip_admin_view.py",
        "pretrip_artifact_manifest.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_24["tests"] == [
        "tests/test_pretrip_route_note_review_options.py",
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_artifact_manifest.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_24["release_check_coverage"]["check_names"] == [
        "route_note_review_options",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_25 = milestones["25"]
    assert milestone_25["title"] == "Expert Contribution Workspace Apply Plan"
    assert milestone_25["modules"] == [
        "pretrip_expert_contribution_apply_plan.py",
        "pretrip_fixture_hygiene.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_25["tests"] == [
        "tests/test_pretrip_expert_contribution_apply_plan.py",
        "tests/test_pretrip_fixture_hygiene.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_25["release_check_coverage"]["check_names"] == [
        "workspace_only_artifact_boundaries",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_26 = milestones["26"]
    assert milestone_26["title"] == "Route Note Reviewed Workspace Assumptions"
    assert milestone_26["modules"] == [
        "pretrip_route_note_reviewed_assumptions.py",
        "pretrip_fixture_hygiene.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_26["tests"] == [
        "tests/test_pretrip_route_note_reviewed_assumptions.py",
        "tests/test_pretrip_fixture_hygiene.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_26["release_check_coverage"]["check_names"] == [
        "workspace_only_artifact_boundaries",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45 = milestones["4.5"]
    assert milestone_45["title"] == "Departure Gate and Runtime Handoff Boundary"
    assert milestone_45["modules"] == [
        "pretrip_review_profiles.py",
        "pretrip_departure_gate.py",
        "pretrip_runtime_handoff.py",
    ]
    assert milestone_45["tests"] == [
        "tests/test_pretrip_review_profiles.py",
        "tests/test_pretrip_departure_gate.py",
        "tests/test_pretrip_runtime_handoff.py",
    ]
    assert milestone_45["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45a = milestones["4.5A"]
    assert milestone_45a["title"] == "Departure Gate Resolution Path"
    assert milestone_45a["modules"] == [
        "pretrip_departure_gate_resolution.py",
        "pretrip_departure_gate.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45a["tests"] == [
        "tests/test_pretrip_departure_gate_resolution.py",
        "tests/test_pretrip_departure_gate.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45a["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45b = milestones["4.5B"]
    assert milestone_45b["title"] == "Final MissionGraph Generation Gate"
    assert milestone_45b["modules"] == [
        "pretrip_final_mission_graph.py",
        "pretrip_departure_gate_resolution.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45b["tests"] == [
        "tests/test_pretrip_final_mission_graph.py",
        "tests/test_pretrip_departure_gate_resolution.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45b["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45c = milestones["4.5C"]
    assert milestone_45c["title"] == "Final MissionGraph Runtime Handoff Link"
    assert milestone_45c["modules"] == [
        "pretrip_runtime_handoff.py",
        "pretrip_final_mission_graph.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45c["tests"] == [
        "tests/test_pretrip_runtime_handoff.py",
        "tests/test_pretrip_final_mission_graph.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45c["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45d = milestones["4.5D"]
    assert milestone_45d["title"] == "Runtime Export Bundle Write Path"
    assert milestone_45d["modules"] == [
        "pretrip_runtime_export.py",
        "pretrip_runtime_handoff.py",
        "pretrip_final_mission_graph.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45d["tests"] == [
        "tests/test_pretrip_runtime_export.py",
        "tests/test_pretrip_runtime_handoff.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45d["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45e = milestones["4.5E"]
    assert milestone_45e["title"] == "Runtime Artifact Resolution Manifest"
    assert milestone_45e["modules"] == [
        "runtime_artifact_resolution.py",
        "pretrip_runtime_artifact_resolution.py",
        "pretrip_runtime_export.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45e["tests"] == [
        "tests/test_pretrip_runtime_artifact_resolution.py",
        "tests/test_pretrip_runtime_export.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45e["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45f = milestones["4.5F"]
    assert milestone_45f["title"] == "Runtime Activation Preflight"
    assert milestone_45f["modules"] == [
        "pretrip_runtime_activation_preflight.py",
        "pretrip_runtime_artifact_resolution.py",
        "runtime_artifact_resolution.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45f["tests"] == [
        "tests/test_pretrip_runtime_activation_preflight.py",
        "tests/test_pretrip_runtime_artifact_resolution.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45f["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45g = milestones["4.5G"]
    assert milestone_45g["title"] == "Runtime Activation Request"
    assert milestone_45g["modules"] == [
        "pretrip_runtime_activation_request.py",
        "pretrip_runtime_activation_preflight.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45g["tests"] == [
        "tests/test_pretrip_runtime_activation_request.py",
        "tests/test_pretrip_runtime_activation_preflight.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45g["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45h = milestones["4.5H"]
    assert milestone_45h["title"] == "Runtime Load Dry Run"
    assert milestone_45h["modules"] == [
        "runtime_load_dry_run.py",
        "runtime_artifact_resolution.py",
        "pretrip_runtime_activation_request.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45h["tests"] == [
        "tests/test_runtime_load_dry_run.py",
        "tests/test_pretrip_runtime_activation_request.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45h["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45i = milestones["4.5I"]
    assert milestone_45i["title"] == "Actual Runtime Activation Loader"
    assert milestone_45i["modules"] == [
        "runtime_activation_loader.py",
        "runtime_load_dry_run.py",
        "safety_runtime_session.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45i["tests"] == [
        "tests/test_runtime_activation_loader.py",
        "tests/test_runtime_load_dry_run.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45i["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45j = milestones["4.5J"]
    assert milestone_45j["title"] == "Runtime Observing Start"
    assert milestone_45j["modules"] == [
        "runtime_activation_loader.py",
        "safety_runtime_session.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45j["tests"] == [
        "tests/test_runtime_activation_loader.py",
        "tests/test_safety_runtime_session.py",
        "tests/test_phase4_pretrip_release_check.py",
    ]
    assert milestone_45j["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45k = milestones["4.5K"]
    assert milestone_45k["title"] == "Runtime Lifecycle Controls"
    assert milestone_45k["modules"] == [
        "runtime_activation_loader.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45k["tests"] == [
        "tests/test_runtime_activation_loader.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45k["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45l = milestones["4.5L"]
    assert milestone_45l["title"] == "Runtime Observation Batch"
    assert milestone_45l["modules"] == [
        "runtime_activation_loader.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45l["tests"] == [
        "tests/test_runtime_activation_loader.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45l["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45m = milestones["4.5M"]
    assert milestone_45m["title"] == "Runtime Stream Guard"
    assert milestone_45m["modules"] == [
        "runtime_activation_loader.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45m["tests"] == [
        "tests/test_runtime_activation_loader.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45m["release_check_coverage"]["check_names"] == [
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45n = milestones["4.5N"]
    assert milestone_45n["title"] == "Runtime Stream Policy"
    assert milestone_45n["modules"] == [
        "runtime_stream_policy.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45n["tests"] == [
        "tests/test_runtime_stream_policy.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45n["release_check_coverage"]["check_names"] == [
        "runtime_stream_policy",
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45o = milestones["4.5O"]
    assert milestone_45o["title"] == "Runtime Observation Envelope"
    assert milestone_45o["modules"] == [
        "runtime_observation_envelope.py",
        "runtime_stream_policy.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45o["tests"] == [
        "tests/test_runtime_observation_envelope.py",
        "tests/test_runtime_stream_policy.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45o["release_check_coverage"]["check_names"] == [
        "runtime_observation_envelope",
        "runtime_stream_policy",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45p = milestones["4.5P"]
    assert milestone_45p["title"] == "Runtime Input Admission"
    assert milestone_45p["modules"] == [
        "runtime_input_admission.py",
        "runtime_observation_envelope.py",
        "runtime_stream_policy.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45p["tests"] == [
        "tests/test_runtime_input_admission.py",
        "tests/test_runtime_observation_envelope.py",
        "tests/test_runtime_stream_policy.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45p["release_check_coverage"]["check_names"] == [
        "runtime_input_admission",
        "runtime_observation_envelope",
        "runtime_stream_policy",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45q = milestones["4.5Q"]
    assert milestone_45q["title"] == "Safety Observation Admission API"
    assert milestone_45q["modules"] == [
        "safety_api.py",
        "runtime_input_admission.py",
        "runtime_observation_envelope.py",
        "runtime_stream_policy.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45q["tests"] == [
        "tests/test_safety_observation_admission_api.py",
        "tests/test_safety_api.py",
        "tests/test_runtime_input_admission.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45q["release_check_coverage"]["check_names"] == [
        "safety_observation_admission_api",
        "runtime_input_admission",
        "runtime_observation_envelope",
        "runtime_stream_policy",
        "focused_phase4_tests",
    ]

    milestone_45r = milestones["4.5R"]
    assert milestone_45r["title"] == "Runtime Incident Bridge Opt-In Guard"
    assert milestone_45r["modules"] == [
        "runtime_incident_bridge_opt_in.py",
        "runtime_stream_policy.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45r["tests"] == [
        "tests/test_runtime_incident_bridge_opt_in.py",
        "tests/test_runtime_stream_policy.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45r["release_check_coverage"]["check_names"] == [
        "runtime_incident_bridge_opt_in",
        "runtime_stream_policy",
        "core_phase4_modules",
        "focused_phase4_tests",
    ]

    milestone_45s = milestones["4.5S"]
    assert milestone_45s["title"] == "Server Safety Admission Config"
    assert milestone_45s["modules"] == [
        "server.py",
        "server_safety_observation_admission_config.py",
        "safety_api.py",
        "runtime_input_admission.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45s["tests"] == [
        "tests/test_server_safety_observation_admission_config.py",
        "tests/test_safety_observation_admission_api.py",
        "tests/test_server_safety_flow.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45s["release_check_coverage"]["check_names"] == [
        "server_safety_observation_admission_config",
        "safety_observation_admission_api",
        "focused_phase4_tests",
    ]

    milestone_45t = milestones["4.5T"]
    assert milestone_45t["title"] == "Runtime Stream Transport API"
    assert milestone_45t["modules"] == [
        "runtime_stream_transport_api.py",
        "server.py",
        "safety_api.py",
        "runtime_observation_envelope.py",
        "runtime_input_admission.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45t["tests"] == [
        "tests/test_runtime_stream_transport_api.py",
        "tests/test_server_safety_observation_admission_config.py",
        "tests/test_safety_observation_admission_api.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45t["release_check_coverage"]["check_names"] == [
        "runtime_stream_transport_api",
        "server_safety_observation_admission_config",
        "safety_observation_admission_api",
        "focused_phase4_tests",
    ]

    milestone_45u = milestones["4.5U"]
    assert milestone_45u["title"] == "Runtime Stream Telemetry"
    assert milestone_45u["modules"] == [
        "runtime_stream_telemetry.py",
        "runtime_stream_transport_api.py",
        "runtime_input_admission.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45u["tests"] == [
        "tests/test_runtime_stream_telemetry.py",
        "tests/test_runtime_stream_transport_api.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45u["release_check_coverage"]["check_names"] == [
        "runtime_stream_telemetry",
        "runtime_stream_transport_api",
        "focused_phase4_tests",
    ]

    milestone_45v = milestones["4.5V"]
    assert milestone_45v["title"] == "Runtime Stream Operator Controls"
    assert milestone_45v["modules"] == [
        "runtime_stream_controls.py",
        "runtime_stream_transport_api.py",
        "runtime_stream_telemetry.py",
        "runtime_input_admission.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45v["tests"] == [
        "tests/test_runtime_stream_controls.py",
        "tests/test_runtime_stream_transport_api.py",
        "tests/test_runtime_stream_telemetry.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45v["release_check_coverage"]["check_names"] == [
        "runtime_stream_controls",
        "runtime_stream_transport_api",
        "runtime_stream_telemetry",
        "focused_phase4_tests",
    ]

    milestone_45w = milestones["4.5W"]
    assert milestone_45w["title"] == "Runtime Incident Bridge Enablement Dry Run"
    assert milestone_45w["modules"] == [
        "runtime_incident_bridge_enablement.py",
        "runtime_incident_bridge_opt_in.py",
        "mock_outbound_transport.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45w["tests"] == [
        "tests/test_runtime_incident_bridge_enablement.py",
        "tests/test_runtime_incident_bridge_opt_in.py",
        "tests/test_mock_outbound_transport.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45w["release_check_coverage"]["check_names"] == [
        "runtime_incident_bridge_enablement",
        "runtime_incident_bridge_opt_in",
        "focused_phase4_tests",
    ]

    milestone_45x = milestones["4.5X"]
    assert milestone_45x["title"] == "Mock Delivery Acknowledgment and Withdrawal"
    assert milestone_45x["modules"] == [
        "runtime_incident_bridge_delivery_ack.py",
        "runtime_incident_bridge_enablement.py",
        "mock_outbound_transport.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45x["tests"] == [
        "tests/test_runtime_incident_bridge_delivery_ack.py",
        "tests/test_runtime_incident_bridge_enablement.py",
        "tests/test_mock_outbound_transport.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45x["release_check_coverage"]["check_names"] == [
        "runtime_incident_bridge_delivery_ack",
        "runtime_incident_bridge_enablement",
        "focused_phase4_tests",
    ]

    milestone_45y = milestones["4.5Y"]
    assert milestone_45y["title"] == "Webhook Remote Provider Policy Contract"
    assert milestone_45y["modules"] == [
        "runtime_remote_provider_policy.py",
        "runtime_incident_bridge_delivery_ack.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45y["tests"] == [
        "tests/test_runtime_remote_provider_policy.py",
        "tests/test_runtime_incident_bridge_delivery_ack.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45y["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_policy",
        "runtime_incident_bridge_delivery_ack",
        "focused_phase4_tests",
    ]

    milestone_45z = milestones["4.5Z"]
    assert milestone_45z["title"] == "Remote Provider Config Preflight"
    assert milestone_45z["modules"] == [
        "runtime_remote_provider_config_preflight.py",
        "runtime_remote_provider_policy.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45z["tests"] == [
        "tests/test_runtime_remote_provider_config_preflight.py",
        "tests/test_runtime_remote_provider_policy.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45z["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_config_preflight",
        "runtime_remote_provider_policy",
        "focused_phase4_tests",
    ]

    milestone_45aa = milestones["4.5AA"]
    assert milestone_45aa["title"] == "Remote Provider Payload Composer"
    assert milestone_45aa["modules"] == [
        "runtime_remote_provider_payload_composer.py",
        "runtime_remote_provider_config_preflight.py",
        "runtime_remote_provider_policy.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45aa["tests"] == [
        "tests/test_runtime_remote_provider_payload_composer.py",
        "tests/test_runtime_remote_provider_config_preflight.py",
        "tests/test_runtime_remote_provider_policy.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45aa["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_payload_composer",
        "runtime_remote_provider_config_preflight",
        "runtime_remote_provider_policy",
        "focused_phase4_tests",
    ]

    milestone_45ab = milestones["4.5AB"]
    assert milestone_45ab["title"] == "Remote Provider Send Intent Queue"
    assert milestone_45ab["modules"] == [
        "runtime_remote_provider_send_queue.py",
        "runtime_remote_provider_payload_composer.py",
        "runtime_remote_provider_config_preflight.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ab["tests"] == [
        "tests/test_runtime_remote_provider_send_queue.py",
        "tests/test_runtime_remote_provider_payload_composer.py",
        "tests/test_runtime_remote_provider_config_preflight.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ab["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_send_queue",
        "runtime_remote_provider_payload_composer",
        "runtime_remote_provider_config_preflight",
        "focused_phase4_tests",
    ]

    milestone_45ac = milestones["4.5AC"]
    assert milestone_45ac["title"] == "Webhook Live Provider Adapter"
    assert milestone_45ac["modules"] == [
        "runtime_remote_provider_live_adapter.py",
        "runtime_remote_provider_send_queue.py",
        "runtime_remote_provider_config_preflight.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ac["tests"] == [
        "tests/test_runtime_remote_provider_live_adapter.py",
        "tests/test_runtime_remote_provider_send_queue.py",
        "tests/test_runtime_remote_provider_config_preflight.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ac["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_live_adapter",
        "runtime_remote_provider_send_queue",
        "runtime_remote_provider_config_preflight",
        "focused_phase4_tests",
    ]

    milestone_45ad = milestones["4.5AD"]
    assert milestone_45ad["title"] == "Webhook Live Send Operator CLI"
    assert milestone_45ad["modules"] == [
        "runtime_remote_provider_live_send_cli.py",
        "runtime_remote_provider_live_adapter.py",
        "runtime_remote_provider_send_queue.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ad["tests"] == [
        "tests/test_runtime_remote_provider_live_send_cli.py",
        "tests/test_runtime_remote_provider_live_adapter.py",
        "tests/test_runtime_remote_provider_send_queue.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ad["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_live_send_cli",
        "runtime_remote_provider_live_adapter",
        "runtime_remote_provider_send_queue",
        "focused_phase4_tests",
    ]

    milestone_45ae = milestones["4.5AE"]
    assert milestone_45ae["title"] == "Shared Admin Map Layer Stack"
    assert milestone_45ae["modules"] == [
        "admin_map_layers.py",
        "pretrip_admin_view.py",
        "admin_after_action.py",
        "docs/admin/phase4-pretrip-planning.html",
        "docs/admin/phase1-after-action.html",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ae["tests"] == [
        "tests/test_admin_map_layers.py",
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_admin_page.py",
        "tests/test_admin_after_action.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ae["release_check_coverage"]["check_names"] == [
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ]

    milestone_45af = milestones["4.5AF"]
    assert milestone_45af["title"] == "Real OSM Basemap Renderer"
    assert milestone_45af["modules"] == [
        "admin_basemap_tiles.py",
        "admin_map_layers.py",
        "docs/admin/phase4-pretrip-planning.html",
        "docs/admin/phase1-after-action.html",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45af["tests"] == [
        "tests/test_admin_basemap_tiles.py",
        "tests/test_admin_map_layers.py",
        "tests/test_pretrip_admin_page.py",
        "tests/test_admin_after_action.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45af["release_check_coverage"]["check_names"] == [
        "admin_basemap_renderer",
        "admin_map_layer_stack",
        "focused_phase4_tests",
    ]

    milestone_45ag = milestones["4.5AG"]
    assert milestone_45ag["title"] == "Local Webhook Demo Harness"
    assert milestone_45ag["modules"] == [
        "runtime_remote_provider_demo_harness.py",
        "runtime_remote_provider_live_send_cli.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ag["tests"] == [
        "tests/test_runtime_remote_provider_demo_harness.py",
        "tests/test_runtime_remote_provider_live_send_cli.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ag["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_demo_harness",
        "runtime_remote_provider_live_send_cli",
        "focused_phase4_tests",
    ]

    milestone_45ah = milestones["4.5AH"]
    assert milestone_45ah["title"] == "Local Webhook Demo Bundle Builder"
    assert milestone_45ah["modules"] == [
        "runtime_remote_provider_demo_bundle.py",
        "runtime_remote_provider_demo_harness.py",
        "runtime_remote_provider_live_send_cli.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ah["tests"] == [
        "tests/test_runtime_remote_provider_demo_bundle.py",
        "tests/test_runtime_remote_provider_demo_harness.py",
        "tests/test_runtime_remote_provider_live_send_cli.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ah["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_demo_bundle",
        "runtime_remote_provider_demo_harness",
        "runtime_remote_provider_live_send_cli",
        "focused_phase4_tests",
    ]

    milestone_45ai = milestones["4.5AI"]
    assert milestone_45ai["title"] == "Local OSM Tile Cache Proxy"
    assert milestone_45ai["modules"] == [
        "admin_tile_proxy.py",
        "admin_map_layers.py",
        "admin_api.py",
        "docs/admin/phase4-pretrip-planning.html",
        "docs/admin/phase1-after-action.html",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ai["tests"] == [
        "tests/test_admin_tile_proxy.py",
        "tests/test_admin_map_layers.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_pretrip_admin_page.py",
        "tests/test_admin_after_action.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ai["release_check_coverage"]["check_names"] == [
        "admin_tile_proxy",
        "admin_map_layer_stack",
        "focused_phase4_tests",
    ]

    milestone_45aj = milestones["4.5AJ"]
    assert milestone_45aj["title"] == "Weather API Overlay Renderer"
    assert milestone_45aj["modules"] == [
        "admin_weather_overlay.py",
        "admin_map_layers.py",
        "admin_api.py",
        "docs/admin/phase4-pretrip-planning.html",
        "docs/admin/phase1-after-action.html",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45aj["tests"] == [
        "tests/test_admin_weather_overlay.py",
        "tests/test_admin_map_layers.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_pretrip_admin_page.py",
        "tests/test_admin_after_action.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45aj["release_check_coverage"]["check_names"] == [
        "admin_weather_overlay",
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ]

    milestone_45ak = milestones["4.5AK"]
    assert milestone_45ak["title"] == "External Webhook Demo Bundle"
    assert milestone_45ak["modules"] == [
        "runtime_remote_provider_demo_bundle.py",
        "runtime_remote_provider_config_preflight.py",
        "runtime_remote_provider_live_send_cli.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ak["tests"] == [
        "tests/test_runtime_remote_provider_external_demo_bundle.py",
        "tests/test_runtime_remote_provider_demo_bundle.py",
        "tests/test_runtime_remote_provider_live_send_cli.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ak["release_check_coverage"]["check_names"] == [
        "runtime_remote_provider_external_demo_bundle",
        "runtime_remote_provider_demo_bundle",
        "focused_phase4_tests",
    ]

    milestone_45al = milestones["4.5AL"]
    assert milestone_45al["title"] == "Hardware Tile Cache Plan Builder"
    assert milestone_45al["modules"] == [
        "admin_tile_cache_builder.py",
        "admin_tile_proxy.py",
        "admin_basemap_tiles.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45al["tests"] == [
        "tests/test_admin_tile_cache_builder.py",
        "tests/test_admin_tile_proxy.py",
        "tests/test_admin_basemap_tiles.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45al["release_check_coverage"]["check_names"] == [
        "admin_tile_cache_builder",
        "admin_tile_proxy",
        "focused_phase4_tests",
    ]

    milestone_45am = milestones["4.5AM"]
    assert milestone_45am["title"] == "Local GeoTIFF Raster Source Manifest"
    assert milestone_45am["modules"] == [
        "admin_local_raster_source.py",
        "admin_map_layers.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45am["tests"] == [
        "tests/test_admin_local_raster_source.py",
        "tests/test_admin_map_layers.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45am["release_check_coverage"]["check_names"] == [
        "admin_local_raster_source",
        "admin_map_layer_stack",
        "focused_phase4_tests",
    ]

    milestone_45an = milestones["4.5AN"]
    assert milestone_45an["title"] == "Local GeoTIFF Raster Tile Pyramid"
    assert milestone_45an["modules"] == [
        "admin_local_raster_tiles.py",
        "admin_local_raster_source.py",
        "admin_api.py",
        "admin_map_layers.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45an["tests"] == [
        "tests/test_admin_local_raster_tiles.py",
        "tests/test_admin_local_raster_source.py",
        "tests/test_admin_map_layers.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45an["release_check_coverage"]["check_names"] == [
        "admin_local_raster_tiles",
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ]

    milestone_45ao = milestones["4.5AO"]
    assert milestone_45ao["title"] == "Pretrip Raster Imagery Renderer"
    assert milestone_45ao["modules"] == [
        "docs/admin/phase4-pretrip-planning.html",
        "admin_map_layers.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ao["tests"] == [
        "tests/test_pretrip_admin_page.py",
        "tests/test_pretrip_admin_view.py",
        "tests/test_admin_map_layers.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ao["release_check_coverage"]["check_names"] == [
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ]

    milestone_45ap = milestones["4.5AP"]
    assert milestone_45ap["title"] == "After-Action Raster Imagery Renderer"
    assert milestone_45ap["modules"] == [
        "docs/admin/phase1-after-action.html",
        "admin_map_layers.py",
        "phase4_pretrip_release_check.py",
    ]
    assert milestone_45ap["tests"] == [
        "tests/test_admin_after_action.py",
        "tests/test_admin_map_layers.py",
        "tests/test_phase4_pretrip_release_check.py",
        "tests/test_pretrip_implementation_status.py",
    ]
    assert milestone_45ap["release_check_coverage"]["check_names"] == [
        "admin_map_layer_stack",
        "focused_phase4_tests",
    ]


def test_manifest_is_metadata_only_and_names_expected_validation_commands():
    manifest = build_pretrip_implementation_status_manifest().to_dict()

    assert manifest["boundary"]["metadata_only"] is True
    assert manifest["boundary"]["runtime_mutation_allowed"] is False
    assert manifest["boundary"]["runtime_export_write_allowed"] is True
    assert manifest["boundary"]["phase1_live_runtime_touched"] is False
    assert manifest["boundary"]["phase2_bridge_touched"] is False
    assert manifest["boundary"]["ui_scope_included"] is True
    assert manifest["boundary"]["ui_scope"] == "fixture_backed_read_only_admin_preview"

    commands = manifest["validation_commands"]
    assert commands["phase4_focused_suite"].startswith(
        "/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest "
    )
    assert "tests/test_pretrip_implementation_status.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_decision_register.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_fixture_hygiene.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_map_layers.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_local_raster_source.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_local_raster_tiles.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_admin_view.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_admin_page.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_admin_api.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_after_action.py" in commands["phase4_focused_suite"]
    assert "tests/test_safety_observation_admission_api.py" in commands["phase4_focused_suite"]
    assert "tests/test_server_safety_observation_admission_config.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_stream_transport_api.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_stream_telemetry.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_stream_controls.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_incident_bridge_opt_in.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_incident_bridge_enablement.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_incident_bridge_delivery_ack.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_policy.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_config_preflight.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_payload_composer.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_send_queue.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_live_adapter.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_live_send_cli.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_demo_harness.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_demo_bundle.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_remote_provider_external_demo_bundle.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_basemap_tiles.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_tile_cache_builder.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_tile_proxy.py" in commands["phase4_focused_suite"]
    assert "tests/test_admin_weather_overlay.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_review_draft.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_review_draft_fixture.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_review_decision_log.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_review_decision_apply.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_review_decision_apply_store.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_workspace_project.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_review_decision_store.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_external_import_queue.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_expert_contribution.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_expert_contribution_apply_plan.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_route_note_ln_proposals.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_route_note_review_options.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_route_note_reviewed_assumptions.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_review_profiles.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_departure_gate.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_departure_gate_resolution.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_final_mission_graph.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_runtime_handoff.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_runtime_export.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_runtime_artifact_resolution.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_runtime_activation_preflight.py" in commands["phase4_focused_suite"]
    assert "tests/test_pretrip_runtime_activation_request.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_load_dry_run.py" in commands["phase4_focused_suite"]
    assert "tests/test_runtime_activation_loader.py" in commands["phase4_focused_suite"]
    assert commands["phase4_release_check"] == (
        "/Users/alexwang0315/scout-fusion/venv/bin/python phase4_pretrip_release_check.py"
    )

    serialized = json.dumps(manifest, sort_keys=True)
    for forbidden in [
        '"runtime_mutation_allowed": true',
        '"phase1_live_runtime_touched": true',
        '"phase2_bridge_touched": true',
        "/safety/",
        "PdrSample",
        "sensor_records",
        "imu_records",
    ]:
        assert forbidden not in serialized
