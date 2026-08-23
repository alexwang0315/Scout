from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from scout.nextgen.intelligence_gateway import (
    CapabilityBroker,
    IntelligenceRequest,
    IntelligenceTaskType,
    WorkspaceBinding,
)
from scout.nextgen.model_qualification import ModelRuntimeQualificationCase
from scout.nextgen.praison_service import EvidenceCatalog
from scout.nextgen.workspace_snapshot import (
    WorkspaceContextCompiler,
    build_workspace_benchmark_cases,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the experimental Scout WorkspaceSnapshot v0 benchmark."
    )
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--evidence-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--context-budget-tokens", type=int, default=4096)
    parser.add_argument("--stale-after-seconds", type=int, default=3600)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    as_of = _parse_timestamp(args.as_of)
    case = ModelRuntimeQualificationCase.from_json_file(args.case)
    catalog = EvidenceCatalog.from_json_file(args.evidence_catalog)
    normalized_catalog = catalog.model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"generated_at": as_of})
                for item in catalog.items
            )
        }
    )
    request = _build_request(case=case, catalog=normalized_catalog, as_of=as_of)
    compiler = WorkspaceContextCompiler(
        context_budget_tokens=args.context_budget_tokens,
        stale_after_seconds=args.stale_after_seconds,
    )
    cases = build_workspace_benchmark_cases(
        request=request,
        evidence_catalog=normalized_catalog,
        compiler=compiler,
        now=as_of,
    )
    artifact = {
        "schema_version": "scout.workspace_snapshot_benchmark.v0",
        "generated_at": as_of.isoformat(),
        "source_case": str(args.case),
        "source_case_sha256": _file_hash(args.case),
        "source_evidence_catalog": str(args.evidence_catalog),
        "source_evidence_catalog_sha256": _file_hash(args.evidence_catalog),
        "normalization": "fixture timestamps normalized to generated_at",
        "case_count": len(cases),
        "modes": [case.mode.value for case in cases],
        "expected_behaviors": [
            case.expected_behavior.value for case in cases
        ],
        "cases": [case.model_dump(mode="json") for case in cases],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    artifact["artifact_hash"] = _canonical_hash(artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(args.output)
    print(
        json.dumps(
            {
                "status": "passed",
                "case_count": len(cases),
                "artifact_hash": artifact["artifact_hash"],
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    return 0


def _build_request(
    *,
    case: ModelRuntimeQualificationCase,
    catalog: EvidenceCatalog,
    as_of: datetime,
) -> IntelligenceRequest:
    request_id = uuid5(
        NAMESPACE_URL,
        f"scout.workspace_snapshot.v0:{case.case_id}:{as_of.isoformat()}",
    )
    input_hash = _canonical_hash(
        {
            "case": case.model_dump(mode="json"),
            "catalog": catalog.model_dump(mode="json"),
        }
    )
    binding = WorkspaceBinding(
        workspace_id=case.workspace_id,
        workspace_revision=case.workspace_revision,
        mission_id=case.mission_id,
        mission_version=case.mission_version,
        route_id=case.route_id,
        route_version=case.route_version,
        input_hash=input_hash,
        generated_at=as_of,
    )
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id=case.mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=case.allowed_capabilities,
        evidence_refs_allowed=case.evidence_refs,
        ttl_seconds=case.max_runtime_seconds + 60,
        max_runtime_seconds=case.max_runtime_seconds,
        max_model_requests=case.max_model_requests,
        max_tool_calls=10,
        provenance_ref="scout.workspace_snapshot_benchmark.v0",
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id=case.mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question=case.question,
        workspace_binding=binding,
        capability_grant=grant,
        geographic_scope=case.geographic_scope,
        evidence_refs=case.evidence_refs,
        max_runtime_seconds=case.max_runtime_seconds,
        max_model_requests=case.max_model_requests,
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--as-of must include a timezone")
    return parsed.astimezone(UTC)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
