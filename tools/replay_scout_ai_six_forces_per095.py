from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from assistant_models import (  # noqa: E402
    AssistantRuntimePreference,
    AssistantSurface,
    ScoutAssistantQuery,
)
from scout_ai_six_forces_scenarios import (  # noqa: E402
    ScenarioContext,
    ScenarioDecisionBatch,
    ScenarioDecisionOutput,
    SixForcesCase,
    verify_scenario_decision,
)
from tools.scout_ai_aihat2_fallback_eval import (  # noqa: E402
    _compact_total_info,
    build_total_info,
    run_tools,
)


DEFAULT_WORKSPACE = Path(
    "/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI"
)
NAVIGATION_TOOL_ID = "scout.ai.live_navigation_state.assess.v0"
EVIDENCE_TOOL_IDS = [
    NAVIGATION_TOOL_ID,
    "scout.ai.energy_vitals.assess.v0",
    "scout.ai.equipment_resource.assess.v0",
]
LOCATION_FIELDS = (
    "lat",
    "lon",
    "elevation_m",
    "nearest_route_distance_m",
    "route_progress_m",
    "nearest_cp_id",
    "heading_deg",
    "course_deg",
    "travel_direction",
    "distance_to_boss_along_route_m",
    "boss_point_id",
    "boss_rank",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _query_snapshot(
    scenario: ScenarioContext,
    condition_overlay: dict[str, Any],
) -> dict[str, Any]:
    snapshot = scenario.to_live_navigation_snapshot()
    if condition_overlay.get("location_status") == "stale_unknown":
        snapshot = {
            key: value
            for key, value in snapshot.items()
            if key not in LOCATION_FIELDS
        }
        snapshot.update(
            {
                "fix_quality": "stale_unknown",
                "snapshot_status": "synthetic_fixture_stale_unknown",
                "horizontal_accuracy_m": 9999.0,
                "uncertainty_m": 9999.0,
            }
        )
    return snapshot


def _selected_total_info_flags(total_info: dict[str, Any] | None) -> dict[str, Any]:
    location = (total_info or {}).get("location_context") or {}
    return {
        "query_snapshot_available": location.get("query_snapshot_available"),
        "route_match_available": location.get("route_match_available"),
        "source": location.get("source"),
    }


def _compact_model_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    records = []
    for record in result.get("records") or []:
        records.append(
            {
                key: record.get(key)
                for key in (
                    "answerability",
                    "candidate_only",
                    "confidence",
                    "decision",
                    "decision_summary",
                    "main_reasons",
                    "next_action",
                    "runtime_safety_truth",
                )
                if record.get(key) is not None
            }
        )
    return {
        key: value
        for key, value in {
            "tool_id": result.get("tool_id"),
            "status": result.get("status"),
            "missing_fields": result.get("missing_fields") or [],
            "warnings": result.get("warnings") or [],
            "errors": result.get("errors") or [],
            "scenario_context": result.get("scenario_context"),
            "provided_fields": result.get("provided_fields"),
            "resource_state": result.get("resource_state"),
            "records": records,
            "source_report": result.get("source_report") or [],
        }.items()
        if value not in (None, [], {})
    }


def prepare_replay_evidence(
    *,
    workspace: Path,
    scenario_artifact_path: Path,
) -> dict[str, Any]:
    artifact = _read_json(scenario_artifact_path)
    case = SixForcesCase.model_validate(
        next(item for item in artifact["cases"] if item["question_id"] == "PER-095")
    )
    replay_inputs: list[dict[str, Any]] = []
    for item in artifact["supplemental_per095_replays"]:
        scenario = ScenarioContext.model_validate(item["scenario"])
        overlay = dict(item["condition_overlay"])
        snapshot = _query_snapshot(scenario, overlay)
        query = ScoutAssistantQuery(
            surface=AssistantSurface.PRETRIP,
            question=case.question_text,
            project_id=scenario.project_id,
            runtime_preference=AssistantRuntimePreference.CLOUD,
            live_navigation_snapshot=snapshot,
        )
        total_info = build_total_info(
            workspace,
            query,
            reference_time=scenario.observed_at,
        )
        tool_results, missing_tools, missing_evidence = run_tools(
            query=query,
            project_root=workspace,
            tool_ids=EVIDENCE_TOOL_IDS,
            max_tools=len(EVIDENCE_TOOL_IDS),
            synthetic_field_context=True,
            live_navigation_snapshot=snapshot,
        )
        replay_inputs.append(
            {
                "scenario_id": scenario.scenario_id,
                "question_id": case.question_id,
                "question_text": case.question_text,
                "expected_evidence_contract": case.expected_evidence_contract.model_dump(
                    mode="json"
                ),
                "expected_decision_boundary": case.expected_decision_boundary.model_dump(
                    mode="json"
                ),
                "scenario_candidate_context": {
                    "risk_terrain_candidate": scenario.risk_terrain_candidate,
                    "source_refs": [
                        source.model_dump(mode="json") for source in scenario.source_refs
                    ],
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                "condition_overlay": overlay,
                "query_snapshot": snapshot,
                "total_info": _compact_total_info(total_info),
                "total_info_flags": _selected_total_info_flags(total_info),
                "selected_tool_results": [
                    _compact_model_tool_result(result) for result in tool_results
                ],
                "missing_tools": missing_tools,
                "missing_evidence": missing_evidence,
            }
        )
    return {
        "artifact_kind": "scout_ai_per095_model_input_evidence",
        "artifact_version": "scout_ai_per095_model_input_evidence.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_artifact_ref": str(scenario_artifact_path),
        "scenario_artifact_sha256": _sha256(scenario_artifact_path),
        "model_instruction": (
            "Return one structured decision per scenario using only the supplied evidence. "
            "Keep candidate terrain unconfirmed; if location is stale/unknown, do not claim "
            "to know what 'here' is. Include decisive and opposing evidence, gaps, change "
            "conditions, and source refs. Do not infer missing facts."
        ),
        "deterministic_reference_included": False,
        "model_answer_included": False,
        "replay_inputs": replay_inputs,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "live_safety_api_calls_allowed": False,
            "outbound_send_allowed": False,
            "hardware_control_allowed": False,
        },
    }


def _context_sync_check(replay_input: dict[str, Any]) -> dict[str, Any]:
    snapshot = replay_input["query_snapshot"]
    scenario_id = snapshot["scenario_id"]
    total_info_location = replay_input["total_info"]["location"]
    tool_envelopes = [
        result.get("scenario_context")
        for result in replay_input["selected_tool_results"]
        if isinstance(result.get("scenario_context"), dict)
    ]
    mismatches: list[str] = []
    for key in ("scenario_id", "lat", "lon", "route_progress_m"):
        expected = snapshot.get(key)
        if total_info_location.get(key) != expected:
            mismatches.append(f"total_info:{key}")
        for index, envelope in enumerate(tool_envelopes):
            if envelope.get(key) != expected:
                mismatches.append(f"tool_{index}:{key}")
    return {
        "status": "pass" if not mismatches else "fail",
        "scenario_id": scenario_id,
        "mismatches": mismatches,
        "query_snapshot_available": replay_input["total_info_flags"].get(
            "query_snapshot_available"
        ),
        "route_match_available": replay_input["total_info_flags"].get(
            "route_match_available"
        ),
    }


def finalize_replay(
    *,
    evidence_path: Path,
    scenario_artifact_path: Path,
    model_output_path: Path,
) -> dict[str, Any]:
    evidence = _read_json(evidence_path)
    artifact = _read_json(scenario_artifact_path)
    batch = ScenarioDecisionBatch.model_validate(_read_json(model_output_path))
    outputs_by_id = {output.scenario_id: output for output in batch.outputs}
    if len(outputs_by_id) != len(evidence["replay_inputs"]):
        raise ValueError("model output must contain one unique output for every replay input")
    case = SixForcesCase.model_validate(
        next(item for item in artifact["cases"] if item["question_id"] == "PER-095")
    )
    references = {
        item["scenario"]["scenario_id"]: item["deterministic_reference"]
        for item in artifact["supplemental_per095_replays"]
    }
    results: list[dict[str, Any]] = []
    for replay_input in evidence["replay_inputs"]:
        scenario_id = replay_input["scenario_id"]
        scenario_source = next(
            item["scenario"]
            for item in artifact["supplemental_per095_replays"]
            if item["scenario"]["scenario_id"] == scenario_id
        )
        scenario = ScenarioContext.model_validate(scenario_source)
        output: ScenarioDecisionOutput = outputs_by_id[scenario_id]
        verifier = verify_scenario_decision(output, scenario=scenario, case=case)
        context_sync = _context_sync_check(replay_input)
        reference_decision = references[scenario_id]["decision"]
        results.append(
            {
                "scenario_id": scenario_id,
                "variant_id": replay_input["condition_overlay"]["variant_id"],
                "model_output": output.model_dump(mode="json"),
                "deterministic_reference_decision": reference_decision,
                "reference_match": output.decision == reference_decision,
                "verifier": verifier,
                "context_sync": context_sync,
            }
        )
    passed = all(
        result["reference_match"]
        and result["verifier"]["status"] == "pass"
        and result["context_sync"]["status"] == "pass"
        for result in results
    )
    return {
        "artifact_kind": "scout_ai_per095_faithful_model_replay",
        "artifact_version": "scout_ai_per095_faithful_model_replay.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if passed else "fail",
        "model_provider": batch.model_provider,
        "evidence_ref": str(evidence_path),
        "evidence_sha256": _sha256(evidence_path),
        "model_output_ref": str(model_output_path),
        "model_output_sha256": _sha256(model_output_path),
        "deterministic_reference_excluded_from_model_input": True,
        "results": results,
        "boundary": evidence["boundary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or finalize the PER-095 faithful model replay."
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--stage", choices=("prepare", "finalize"), required=True)
    parser.add_argument("--scenario-artifact", type=Path, default=None)
    parser.add_argument("--evidence-output", type=Path, default=None)
    parser.add_argument("--schema-output", type=Path, default=None)
    parser.add_argument("--model-output", type=Path, default=None)
    parser.add_argument("--replay-output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    scenario_artifact = (
        args.scenario_artifact
        or workspace / "outputs/evals/scout_ai_six_forces_600_scenarios.json"
    ).expanduser().resolve()
    evidence_output = (
        args.evidence_output
        or workspace / "outputs/evals/scout_ai_per095_replay_evidence.json"
    ).expanduser().resolve()
    if args.stage == "prepare":
        schema_output = (
            args.schema_output
            or workspace / "outputs/evals/scout_ai_per095_model_output.schema.json"
        ).expanduser().resolve()
        _write_json(
            evidence_output,
            prepare_replay_evidence(
                workspace=workspace,
                scenario_artifact_path=scenario_artifact,
            ),
        )
        _write_json(schema_output, ScenarioDecisionBatch.model_json_schema())
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "evidence_output": str(evidence_output),
                    "schema_output": str(schema_output),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.model_output is None:
        raise ValueError("--model-output is required for finalize")
    replay_output = (
        args.replay_output
        or workspace / "outputs/evals/scout_ai_per095_faithful_replay.json"
    ).expanduser().resolve()
    _write_json(
        replay_output,
        finalize_replay(
            evidence_path=evidence_output,
            scenario_artifact_path=scenario_artifact,
            model_output_path=args.model_output.expanduser().resolve(),
        ),
    )
    print(json.dumps({"status": "finalized", "output": str(replay_output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
