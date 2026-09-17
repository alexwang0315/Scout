from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_model_config import load_assistant_model_config  # noqa: E402
from scout.nextgen.assistant_promotion import (  # noqa: E402
    AssistantModelProductionPromotionManifest,
    AssistantProductionSmokeReport,
    PromotionEvidenceRef,
    file_sha256,
    promotion_manifest_hash,
)
from scout.nextgen.model_qualification import (  # noqa: E402
    ModelQualificationDisposition,
    ModelRuntimeQualificationReport,
)
from scout.nextgen.workspace_model_benchmark import (  # noqa: E402
    WorkspaceModelBenchmarkDisposition,
    WorkspaceModelBenchmarkReport,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a fail-closed read-only Assistant model promotion manifest."
    )
    parser.add_argument("--promotion-id", required=True)
    parser.add_argument("--candidate-config", type=Path, required=True)
    parser.add_argument("--model-runtime-report", type=Path, required=True)
    parser.add_argument("--workspace-benchmark-report", type=Path, required=True)
    parser.add_argument("--assistant-route-smoke", type=Path, required=True)
    parser.add_argument("--assistant-workspace-smoke", type=Path, required=True)
    parser.add_argument("--rollback-model", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_assistant_model_config(args.candidate_config)
    model_report = ModelRuntimeQualificationReport.model_validate_json(
        args.model_runtime_report.read_bytes()
    )
    workspace_report = WorkspaceModelBenchmarkReport.model_validate_json(
        args.workspace_benchmark_report.read_bytes()
    )
    assistant_smoke = AssistantProductionSmokeReport.model_validate_json(
        args.assistant_workspace_smoke.read_bytes()
    )
    route_smoke = _load_route_smoke(args.assistant_route_smoke)
    _validate_qualification_set(
        config_model=config.cloud_model.model_name,
        model_report=model_report,
        workspace_report=workspace_report,
        assistant_smoke=assistant_smoke,
        route_smoke=route_smoke,
    )

    evidence = (
        PromotionEvidenceRef(
            evidence_type="model_runtime_qualification",
            path=str(args.model_runtime_report),
            file_sha256=file_sha256(args.model_runtime_report),
            report_hash=model_report.report_hash,
        ),
        PromotionEvidenceRef(
            evidence_type="workspace_five_mode_benchmark",
            path=str(args.workspace_benchmark_report),
            file_sha256=file_sha256(args.workspace_benchmark_report),
            report_hash=workspace_report.report_hash,
        ),
        PromotionEvidenceRef(
            evidence_type="assistant_route_smoke",
            path=str(args.assistant_route_smoke),
            file_sha256=file_sha256(args.assistant_route_smoke),
        ),
        PromotionEvidenceRef(
            evidence_type="assistant_workspace_api_smoke",
            path=str(args.assistant_workspace_smoke),
            file_sha256=file_sha256(args.assistant_workspace_smoke),
            report_hash=assistant_smoke.report_hash,
        ),
    )
    provisional = AssistantModelProductionPromotionManifest.model_construct(
        promotion_id=args.promotion_id,
        generated_at=_parse_timestamp(args.generated_at),
        scope="read_only_workspace_assistant",
        promoted_model_name=config.cloud_model.model_name,
        observed_model_id=assistant_smoke.observed_model_id,
        rollback_model_name=args.rollback_model,
        local_fallback_model_name=config.local_model.model_name,
        evidence=evidence,
        model_runtime_qualification_passed=True,
        workspace_five_mode_benchmark_passed=True,
        assistant_route_smoke_passed=True,
        assistant_workspace_api_smoke_passed=True,
        authority_boundary_passed=True,
        local_fallback_preserved=True,
        behavior_probe_promoted=False,
        production_promotion_allowed=True,
        candidate_only=True,
        runtime_safety_truth=False,
        manifest_hash="0" * 64,
    )
    payload = provisional.model_dump(mode="json")
    payload["manifest_hash"] = promotion_manifest_hash(provisional)
    manifest = AssistantModelProductionPromotionManifest.model_validate(payload)
    _write_json(args.output, manifest.model_dump_json(indent=2) + "\n")
    print(
        f"passed model={manifest.promoted_model_name} "
        f"rollback={manifest.rollback_model_name} "
        f"manifest_hash={manifest.manifest_hash} output={args.output}"
    )
    return 0


def _validate_qualification_set(
    *,
    config_model: str,
    model_report: ModelRuntimeQualificationReport,
    workspace_report: WorkspaceModelBenchmarkReport,
    assistant_smoke: AssistantProductionSmokeReport,
    route_smoke: list[dict[str, object]],
) -> None:
    if model_report.disposition is not ModelQualificationDisposition.PASSED:
        raise ValueError("model runtime qualification did not pass")
    if workspace_report.disposition is not WorkspaceModelBenchmarkDisposition.PASSED:
        raise ValueError("Workspace five-mode benchmark did not pass")
    if (
        workspace_report.metrics.total_cases != 5
        or workspace_report.metrics.passed_cases != 5
        or workspace_report.metrics.workspace_dependency_score != 1.0
    ):
        raise ValueError("Workspace benchmark is not a 5/5 dependency qualification")
    expected_model_id = config_model.removeprefix("openrouter:")
    if {
        model_report.requested_model_id,
        workspace_report.model_id,
        assistant_smoke.observed_model_id,
    } != {expected_model_id}:
        raise ValueError("promotion evidence model binding mismatch")
    if assistant_smoke.model_name != config_model:
        raise ValueError("assistant smoke config model binding mismatch")
    samples = [item for item in route_smoke if isinstance(item.get("iteration"), int)]
    summaries = [item for item in route_smoke if item not in samples]
    if len(samples) < 3 or any(item.get("ok") is not True for item in samples):
        raise ValueError("assistant route smoke requires at least three passing runs")
    if len(summaries) != 1:
        raise ValueError("assistant route smoke requires one summary record")
    summary = summaries[0]
    boundary = summary.get("safety_boundary")
    if (
        summary.get("status") != "ok"
        or summary.get("success_count") != len(samples)
        or summary.get("failure_count") != 0
        or not isinstance(boundary, dict)
        or boundary.get("mutates_scout_safety_state") is not False
        or boundary.get("secret_values_serialized") is not False
        or boundary.get("sends_operator_alerts") is not False
    ):
        raise ValueError("assistant route smoke summary violates promotion gates")
    output_hashes = {str(item.get("output_sha256") or "") for item in samples}
    if len(output_hashes) != 1 or "" in output_hashes:
        raise ValueError("assistant route smoke output is not deterministic")


def _load_route_smoke(path: Path) -> list[dict[str, object]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("assistant route smoke JSONL is invalid")
    return records


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include a timezone")
    return parsed.astimezone(UTC)


def _write_json(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
