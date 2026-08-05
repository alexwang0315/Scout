from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tests.qualification.contracts import (
    QualificationRunManifest,
    canonical_sha256,
    file_sha256,
)
from tests.qualification.phase3_catalog import (
    PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256,
    PHASE2_DETERMINISM_ADDENDUM_REV1_CANONICAL_SHA256,
    PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256,
    PHASE2_MANIFEST_SEMANTIC_SHA256,
    PHASE2_REPORT_CANONICAL_SHA256,
    PHASE2_REPORT_SEMANTIC_SHA256,
)
from tests.qualification.phase3_contracts import Phase3Finding


ADDENDUM_REF = (
    "docs/evals/"
    "dashboard-internal-qualification-phase2-determinism-addendum-rev2.json"
)
ADAPTER_PLACEHOLDER = "<adapter-source-bound>"


@dataclass(frozen=True)
class Phase2LineageContract:
    retained_manifest: QualificationRunManifest
    current_manifest: QualificationRunManifest
    retained_manifest_sha256: str
    current_manifest_sha256: str
    retained_report_sha256: str
    current_report_sha256: str
    current_report_serialized_sha256: str
    normalized_manifest_sha256: str
    normalized_report_sha256: str
    addendum_sha256: str


@dataclass(frozen=True)
class Phase2LineageEvidence:
    current_manifest_sha256: str
    normalized_manifest_sha256: str
    normalized_report_sha256: str
    findings: tuple[Phase3Finding, ...]


def _finding(code: str, summary: str, *, evidence: tuple[str, ...] = ()) -> Phase3Finding:
    return Phase3Finding(
        finding_id=f"{code.casefold()}.{canonical_sha256((code, summary))[:12]}",
        code=code,
        severity="blocking",
        summary=summary,
        requirement_refs=("P3D-05",),
        evidence_refs=evidence,
    )


def _manifest_from_mapping(value: Mapping[str, Any]) -> QualificationRunManifest:
    components = value.get("component_sha256")
    if not isinstance(components, list):
        raise ValueError("Phase 2 manifest component_sha256 must be a list")
    pairs = tuple((str(item[0]), str(item[1])) for item in components)
    if len(pairs) != len(set(name for name, _ in pairs)):
        raise ValueError("Phase 2 manifest component names must be unique")
    if sum(name == "adapter" for name, _ in pairs) != 1:
        raise ValueError("Phase 2 manifest must contain exactly one adapter component")
    return QualificationRunManifest(
        run_id=str(value["run_id"]),
        phase1_prerequisite_sha256=str(value["phase1_prerequisite_sha256"]),
        component_sha256=pairs,
        deterministic_clock=str(value["deterministic_clock"]),
        deterministic_seed=int(value["deterministic_seed"]),
    )


def _normalized_manifest_payload(
    manifest: QualificationRunManifest,
) -> dict[str, object]:
    return {
        "run_id": manifest.run_id,
        "phase1_prerequisite_sha256": manifest.phase1_prerequisite_sha256,
        "component_sha256": [
            [name, ADAPTER_PLACEHOLDER if name == "adapter" else digest]
            for name, digest in manifest.component_sha256
        ],
        "deterministic_clock": manifest.deterministic_clock,
        "deterministic_seed": manifest.deterministic_seed,
    }


def normalized_phase2_report_hash(
    artifact: Mapping[str, Any],
    normalized_manifest_sha256: str,
) -> str:
    payload = json.loads(json.dumps(artifact))
    payload.pop("content_sha256", None)
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError("Phase 2 artifact report must be an object")
    components = report.get("run_manifest_component_sha256")
    if not isinstance(components, list):
        raise ValueError("Phase 2 report component manifest must be a list")
    normalized_components: list[list[str]] = []
    adapter_count = 0
    for item in components:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("Phase 2 report component entry must be a pair")
        name, digest = str(item[0]), str(item[1])
        if name == "adapter":
            adapter_count += 1
            digest = ADAPTER_PLACEHOLDER
        normalized_components.append([name, digest])
    if adapter_count != 1:
        raise ValueError("Phase 2 report must contain exactly one adapter component")
    report["run_manifest_sha256"] = normalized_manifest_sha256
    report["run_manifest_component_sha256"] = normalized_components
    return canonical_sha256(payload)


def load_phase2_lineage_contract(repository_root: Path) -> Phase2LineageContract:
    path = Path(repository_root).resolve() / ADDENDUM_REF
    payload = json.loads(path.read_text(encoding="utf-8"))
    embedded = str(payload.pop("content_sha256"))
    if (
        embedded != PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256
        or canonical_sha256(payload) != embedded
    ):
        raise ValueError("Phase 2 determinism addendum identity changed")
    predecessor = payload["predecessor"]
    if predecessor["canonical_sha256"] != (
        PHASE2_DETERMINISM_ADDENDUM_REV1_CANONICAL_SHA256
    ):
        raise ValueError("Phase 2 determinism addendum predecessor changed")
    retained = payload["retained_joint_baseline"]
    current = payload["current_deterministic_baseline"]
    retained_manifest = _manifest_from_mapping(retained["manifest_payload"])
    current_manifest = _manifest_from_mapping(current["manifest_payload"])
    retained_manifest_sha256 = str(retained["manifest_canonical_sha256"])
    current_manifest_sha256 = str(current["manifest_canonical_sha256"])
    if canonical_sha256(retained_manifest) != retained_manifest_sha256:
        raise ValueError("retained Phase 2 full manifest identity changed")
    if canonical_sha256(current_manifest) != current_manifest_sha256:
        raise ValueError("current Phase 2 full manifest identity changed")
    normalized_retained = _normalized_manifest_payload(retained_manifest)
    normalized_current = _normalized_manifest_payload(current_manifest)
    if normalized_retained != normalized_current:
        raise ValueError("Phase 2 manifests differ outside the adapter digest")
    normalized_manifest_sha256 = canonical_sha256(normalized_current)
    equivalence = payload["field_level_equivalence"]
    if (
        normalized_manifest_sha256 != PHASE2_MANIFEST_SEMANTIC_SHA256
        or equivalence["normalized_manifest_sha256"]
        != normalized_manifest_sha256
        or equivalence["normalized_report_sha256"]
        != PHASE2_REPORT_SEMANTIC_SHA256
    ):
        raise ValueError("Phase 2 normalized manifest/report identity changed")
    if retained["report_canonical_sha256"] != (
        PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256
    ):
        raise ValueError("retained Phase 2 report identity changed")
    if current["report_canonical_sha256"] != PHASE2_REPORT_CANONICAL_SHA256:
        raise ValueError("current Phase 2 report identity changed")
    return Phase2LineageContract(
        retained_manifest=retained_manifest,
        current_manifest=current_manifest,
        retained_manifest_sha256=retained_manifest_sha256,
        current_manifest_sha256=current_manifest_sha256,
        retained_report_sha256=str(retained["report_canonical_sha256"]),
        current_report_sha256=str(current["report_canonical_sha256"]),
        current_report_serialized_sha256=str(current["report_serialized_sha256"]),
        normalized_manifest_sha256=normalized_manifest_sha256,
        normalized_report_sha256=str(equivalence["normalized_report_sha256"]),
        addendum_sha256=embedded,
    )


def phase2_manifest_findings(
    contract: Phase2LineageContract,
    current_manifest: QualificationRunManifest,
) -> tuple[Phase3Finding, ...]:
    if (
        current_manifest.phase1_prerequisite_sha256
        != contract.current_manifest.phase1_prerequisite_sha256
    ):
        return (
            _finding(
                "PHASE1-REGRESSION",
                "Current Phase 2 manifest changed the retained Phase 1 prerequisite.",
            ),
        )
    current_sha256 = canonical_sha256(current_manifest)
    normalized_sha256 = canonical_sha256(_normalized_manifest_payload(current_manifest))
    if (
        current_sha256 != contract.current_manifest_sha256
        or current_manifest != contract.current_manifest
        or normalized_sha256 != contract.normalized_manifest_sha256
    ):
        return (
            _finding(
                "PHASE2-REGRESSION",
                "Current Phase 2 full manifest differs outside the reviewed deterministic adapter lineage.",
            ),
        )
    return ()


def exit_code_for_phase2_lineage(
    findings: tuple[Phase3Finding, ...],
) -> int:
    return 2 if findings else 0


def validate_phase2_lineage(
    contract: Phase2LineageContract,
    current_manifest: QualificationRunManifest,
    current_artifact_path: Path,
) -> Phase2LineageEvidence:
    findings = list(phase2_manifest_findings(contract, current_manifest))
    artifact_path = Path(current_artifact_path)
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        embedded = str(artifact["content_sha256"])
        artifact_without_hash = dict(artifact)
        artifact_without_hash.pop("content_sha256", None)
        report = artifact["report"]
        report_manifest_sha256 = str(report["run_manifest_sha256"])
        report_components = tuple(
            (str(item[0]), str(item[1]))
            for item in report["run_manifest_component_sha256"]
        )
        normalized_report_sha256 = normalized_phase2_report_hash(
            artifact,
            contract.normalized_manifest_sha256,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        findings.append(
            _finding(
                "PHASE2-REGRESSION",
                f"Current Phase 2 artifact cannot prove full manifest lineage: {type(error).__name__}.",
            )
        )
        return Phase2LineageEvidence(
            current_manifest_sha256=canonical_sha256(current_manifest),
            normalized_manifest_sha256=canonical_sha256(
                _normalized_manifest_payload(current_manifest)
            ),
            normalized_report_sha256="invalid",
            findings=tuple(findings),
        )
    if (
        embedded != contract.current_report_sha256
        or canonical_sha256(artifact_without_hash) != embedded
        or file_sha256(artifact_path) != contract.current_report_serialized_sha256
        or report_manifest_sha256 != canonical_sha256(current_manifest)
        or report_components != current_manifest.component_sha256
        or normalized_report_sha256 != contract.normalized_report_sha256
    ):
        findings.append(
            _finding(
                "PHASE2-REGRESSION",
                "Current Phase 2 report or its full manifest binding differs from the reviewed lineage.",
            )
        )
    return Phase2LineageEvidence(
        current_manifest_sha256=canonical_sha256(current_manifest),
        normalized_manifest_sha256=canonical_sha256(
            _normalized_manifest_payload(current_manifest)
        ),
        normalized_report_sha256=normalized_report_sha256,
        findings=tuple(findings),
    )


__all__ = [
    "Phase2LineageContract",
    "Phase2LineageEvidence",
    "load_phase2_lineage_contract",
    "normalized_phase2_report_hash",
    "phase2_manifest_findings",
    "exit_code_for_phase2_lineage",
    "validate_phase2_lineage",
]
