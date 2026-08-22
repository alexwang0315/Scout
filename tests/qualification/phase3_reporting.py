from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from tests.qualification.contracts import canonical_json, canonical_sha256
from tests.qualification.phase3_catalog import DOMAIN_IDS
from tests.qualification.phase3_contracts import (
    Phase3AggregateReport,
    Phase3CaseResult,
    Phase3DomainReport,
    Phase3Finding,
)


class InvalidPhase3Qualification(RuntimeError):
    pass


@dataclass(frozen=True)
class Phase3FinalizedOutputs:
    aggregate_json: Path
    aggregate_junit: Path
    aggregate_text: Path
    domain_outputs: tuple[tuple[str, Path, Path, Path, str], ...]
    content_sha256: str


@dataclass(frozen=True)
class Phase3DomainFinalizedOutputs:
    canonical_json: Path
    junit_xml: Path
    text_report: Path
    content_sha256: str


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def _blocking(findings: Sequence[Phase3Finding]) -> tuple[Phase3Finding, ...]:
    return tuple(
        sorted(
            (item for item in findings if item.severity == "blocking"),
            key=lambda item: item.finding_id,
        )
    )


def _validate_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise InvalidPhase3Qualification(f"{label} is not a canonical SHA-256")


def validate_domain_report(report: Phase3DomainReport) -> None:
    if report.schema_version != "dashboardQualificationDomainReport.v1":
        raise InvalidPhase3Qualification("unknown domain report schema")
    if report.domain_id not in DOMAIN_IDS:
        raise InvalidPhase3Qualification("unknown domain report domain")
    if not report.run_id or not report.aggregate_run_id:
        raise InvalidPhase3Qualification("domain report run identity is incomplete")
    _validate_hash(report.source_manifest_sha256, "source manifest")
    _validate_hash(report.domain_model_sha256, "domain model")
    if report.workspace_snapshot_sha256 is not None:
        _validate_hash(report.workspace_snapshot_sha256, "workspace snapshot")
    case_ids = tuple(item.case_id for item in report.cases)
    if len(case_ids) != len(set(case_ids)):
        raise InvalidPhase3Qualification("domain report has duplicate cases")
    has_bad_case = any(
        not item.activated or item.status not in {"passed", "not_applicable"}
        for item in report.cases
    )
    has_blocking = bool(_blocking(report.findings))
    expected_verdict = "invalid" if not report.complete else (
        "fail" if has_bad_case or has_blocking else "pass"
    )
    if report.verdict != expected_verdict:
        raise InvalidPhase3Qualification(
            f"domain verdict {report.verdict} disagrees with evidence {expected_verdict}"
        )


def validate_aggregate_report(
    report: Phase3AggregateReport,
    domain_reports: Mapping[str, Phase3DomainReport],
) -> None:
    if report.schema_version != "dashboardQualificationAggregateReport.v1":
        raise InvalidPhase3Qualification("unknown aggregate report schema")
    if report.claim not in {"construction", "release"}:
        raise InvalidPhase3Qualification("unknown aggregate claim")
    for label, digest in (
        ("design", report.design_sha256),
        ("phase2", report.phase2_report_sha256),
        ("repository", report.repository_identity),
        ("source manifest", report.source_manifest_sha256),
    ):
        _validate_hash(digest, label)
    if report.claim == "release" and report.workspace_snapshot_sha256 is None:
        raise InvalidPhase3Qualification("release claim requires a sealed workspace snapshot")
    if report.workspace_snapshot_sha256 is not None:
        _validate_hash(report.workspace_snapshot_sha256, "workspace snapshot")
    required = tuple(DOMAIN_IDS)
    if report.required_domain_ids != required:
        raise InvalidPhase3Qualification("aggregate required-domain inventory changed")
    if set(domain_reports) != set(required):
        raise InvalidPhase3Qualification("aggregate omitted or added a domain report")
    bound_hashes = dict(report.domain_report_sha256)
    if set(bound_hashes) != set(required):
        raise InvalidPhase3Qualification("aggregate domain-report hash inventory is incomplete")
    for domain_id in required:
        domain = domain_reports[domain_id]
        validate_domain_report(domain)
        if domain.domain_id != domain_id:
            raise InvalidPhase3Qualification("domain report stored under wrong identity")
        if domain.aggregate_run_id != report.run_id:
            raise InvalidPhase3Qualification("foreign-run domain report")
        if domain.source_manifest_sha256 != report.source_manifest_sha256:
            raise InvalidPhase3Qualification("mixed source-manifest domain evidence")
        if domain.workspace_snapshot_sha256 != report.workspace_snapshot_sha256:
            raise InvalidPhase3Qualification("mixed workspace-snapshot domain evidence")
        if bound_hashes[domain_id] != canonical_sha256(domain):
            raise InvalidPhase3Qualification("stale or mismatched domain report hash")
    case_ids = tuple(item.case_id for item in report.cases)
    if len(case_ids) != len(set(case_ids)):
        raise InvalidPhase3Qualification("aggregate report has duplicate cases")
    has_bad_case = any(
        not item.activated or item.status not in {"passed", "not_applicable"}
        for item in report.cases
    ) or any(domain.verdict != "pass" for domain in domain_reports.values())
    has_blocking = bool(_blocking(report.findings))
    expected_verdict = "invalid" if not report.complete else (
        "fail" if has_bad_case or has_blocking else "pass"
    )
    if report.verdict != expected_verdict:
        raise InvalidPhase3Qualification(
            f"aggregate verdict {report.verdict} disagrees with evidence {expected_verdict}"
        )


def exit_code_for_phase3(
    report: Phase3AggregateReport,
    domain_reports: Mapping[str, Phase3DomainReport],
    *,
    finalized: bool,
) -> int:
    if not finalized:
        return 2
    try:
        validate_aggregate_report(report, domain_reports)
    except InvalidPhase3Qualification:
        return 2
    if not report.complete or report.verdict == "invalid":
        return 2
    if report.verdict == "fail" or _blocking(report.findings):
        return 1
    return 0


def exit_code_for_phase3_domain(
    report: Phase3DomainReport,
    *,
    finalized: bool,
) -> int:
    if not finalized:
        return 2
    try:
        validate_domain_report(report)
    except InvalidPhase3Qualification:
        return 2
    if not report.complete or report.verdict == "invalid":
        return 2
    if report.verdict == "fail" or _blocking(report.findings):
        return 1
    return 0


def _artifact_payload(schema: str, report: object) -> tuple[dict[str, object], str]:
    payload: dict[str, object] = {
        "schema_version": schema,
        "report": json.loads(canonical_json(report)),
    }
    digest = canonical_sha256(payload)
    return {**payload, "content_sha256": digest}, digest


def _case_tuple(item: Phase3CaseResult) -> tuple[str, bool, str]:
    accepted = item.activated and item.status in {"passed", "not_applicable"}
    return item.case_id, accepted, item.status


def _render_junit(
    *,
    name: str,
    run_id: str,
    verdict: str,
    complete: bool,
    cases: Sequence[Phase3CaseResult],
    findings: Sequence[Phase3Finding],
) -> str:
    blocking = _blocking(findings)
    failed_cases = sum(not _case_tuple(item)[1] for item in cases)
    suite = ET.Element(
        "testsuite",
        {
            "name": name,
            "run_id": run_id,
            "verdict": verdict,
            "complete": str(complete).lower(),
            "tests": str(max(1, len(cases) + len(blocking))),
            "failures": str(failed_cases + len(blocking)),
            "errors": "0",
        },
    )
    if not cases and not blocking:
        ET.SubElement(suite, "testcase", {"name": "qualification"})
    for item in cases:
        case = ET.SubElement(
            suite,
            "testcase",
            {"name": item.case_id, "classname": item.category, "status": item.status},
        )
        if not _case_tuple(item)[1]:
            failure = ET.SubElement(case, "failure", {"type": "evidence", "message": item.status})
            failure.text = ",".join(item.finding_codes)
    for item in blocking:
        case = ET.SubElement(
            suite,
            "testcase",
            {"name": f"finding:{item.finding_id}", "classname": item.code, "status": "failed"},
        )
        failure = ET.SubElement(
            case,
            "failure",
            {"type": item.severity, "finding_id": item.finding_id, "message": item.summary},
        )
        failure.text = item.code
    return ET.tostring(suite, encoding="unicode") + "\n"


def _render_text(
    *,
    run_id: str,
    verdict: str,
    complete: bool,
    cases: Sequence[Phase3CaseResult],
    findings: Sequence[Phase3Finding],
) -> str:
    lines = [
        f"run_id\t{run_id}",
        f"verdict\t{verdict}",
        f"complete\t{str(complete).lower()}",
        f"cases\t{len(cases)}",
    ]
    lines.extend(
        f"CASE\t{item.case_id}\t{item.category}\t{item.status}\t{str(item.activated).lower()}"
        for item in cases
    )
    lines.extend(
        f"BLOCKING\t{item.finding_id}\t{item.severity}\t{item.code}\t{item.summary.replace(chr(9), ' ').replace(chr(10), ' ')}"
        for item in _blocking(findings)
    )
    return "\n".join(lines) + "\n"


def _verify_artifact(path: Path, expected_report: object, schema: str) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    digest = str(value.pop("content_sha256", ""))
    if value.get("schema_version") != schema or canonical_sha256(value) != digest:
        raise InvalidPhase3Qualification(f"canonical artifact verification failed: {path.name}")
    if value.get("report") != json.loads(canonical_json(expected_report)):
        raise InvalidPhase3Qualification(f"canonical artifact changed report: {path.name}")
    return digest


def _junit_inventory(path: Path) -> tuple[str, ...]:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    return tuple(sorted(str(item.attrib.get("name", "")) for item in root.findall(".//testcase")))


def _expected_inventory(cases: Sequence[Phase3CaseResult], findings: Sequence[Phase3Finding]) -> tuple[str, ...]:
    inventory = [item.case_id for item in cases]
    inventory.extend(f"finding:{item.finding_id}" for item in _blocking(findings))
    if not inventory:
        inventory.append("qualification")
    return tuple(sorted(inventory))


def finalize_phase3_reports(
    report: Phase3AggregateReport,
    domain_reports: Mapping[str, Phase3DomainReport],
    result_root: Path,
) -> Phase3FinalizedOutputs:
    validate_aggregate_report(report, domain_reports)
    root = Path(result_root)
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise InvalidPhase3Qualification("result root already exists") from error
    domains_root = root / "domains"
    domains_root.mkdir()
    domain_outputs: list[tuple[str, Path, Path, Path, str]] = []
    for domain_id in DOMAIN_IDS:
        domain = domain_reports[domain_id]
        domain_root = domains_root / domain_id
        domain_root.mkdir()
        canonical_path = domain_root / "qualification-report.json"
        junit_path = domain_root / "qualification-report.junit.xml"
        text_path = domain_root / "qualification-report.txt"
        payload, expected_digest = _artifact_payload(
            "dashboardQualificationDomainArtifact.v1", domain
        )
        _atomic_write(canonical_path, canonical_json(payload) + "\n")
        digest = _verify_artifact(
            canonical_path, domain, "dashboardQualificationDomainArtifact.v1"
        )
        if digest != expected_digest:
            raise InvalidPhase3Qualification("domain artifact digest changed")
        _atomic_write(
            junit_path,
            _render_junit(
                name=f"dashboard-qualification-{domain_id}",
                run_id=domain.run_id,
                verdict=domain.verdict,
                complete=domain.complete,
                cases=domain.cases,
                findings=domain.findings,
            ),
        )
        _atomic_write(
            text_path,
            _render_text(
                run_id=domain.run_id,
                verdict=domain.verdict,
                complete=domain.complete,
                cases=domain.cases,
                findings=domain.findings,
            ),
        )
        if _junit_inventory(junit_path) != _expected_inventory(domain.cases, domain.findings):
            raise InvalidPhase3Qualification("domain JUnit projection lost evidence")
        domain_outputs.append((domain_id, canonical_path, junit_path, text_path, digest))

    canonical_path = root / "qualification-report.json"
    junit_path = root / "qualification-report.junit.xml"
    text_path = root / "qualification-report.txt"
    payload, expected_digest = _artifact_payload(
        "dashboardQualificationAggregateArtifact.v1", report
    )
    _atomic_write(canonical_path, canonical_json(payload) + "\n")
    digest = _verify_artifact(
        canonical_path, report, "dashboardQualificationAggregateArtifact.v1"
    )
    if digest != expected_digest:
        raise InvalidPhase3Qualification("aggregate artifact digest changed")
    _atomic_write(
        junit_path,
        _render_junit(
            name="dashboard-internal-qualification-phase3",
            run_id=report.run_id,
            verdict=report.verdict,
            complete=report.complete,
            cases=report.cases,
            findings=report.findings,
        ),
    )
    _atomic_write(
        text_path,
        _render_text(
            run_id=report.run_id,
            verdict=report.verdict,
            complete=report.complete,
            cases=report.cases,
            findings=report.findings,
        ),
    )
    if _junit_inventory(junit_path) != _expected_inventory(report.cases, report.findings):
        raise InvalidPhase3Qualification("aggregate JUnit projection lost evidence")
    return Phase3FinalizedOutputs(
        aggregate_json=canonical_path,
        aggregate_junit=junit_path,
        aggregate_text=text_path,
        domain_outputs=tuple(domain_outputs),
        content_sha256=digest,
    )


def finalize_phase3_domain_report(
    report: Phase3DomainReport,
    result_root: Path,
) -> Phase3DomainFinalizedOutputs:
    validate_domain_report(report)
    root = Path(result_root)
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise InvalidPhase3Qualification("result root already exists") from error
    canonical_path = root / "qualification-report.json"
    junit_path = root / "qualification-report.junit.xml"
    text_path = root / "qualification-report.txt"
    payload, expected_digest = _artifact_payload(
        "dashboardQualificationDomainArtifact.v1", report
    )
    _atomic_write(canonical_path, canonical_json(payload) + "\n")
    digest = _verify_artifact(
        canonical_path, report, "dashboardQualificationDomainArtifact.v1"
    )
    if digest != expected_digest:
        raise InvalidPhase3Qualification("domain artifact digest changed")
    _atomic_write(
        junit_path,
        _render_junit(
            name=f"dashboard-qualification-{report.domain_id}",
            run_id=report.run_id,
            verdict=report.verdict,
            complete=report.complete,
            cases=report.cases,
            findings=report.findings,
        ),
    )
    _atomic_write(
        text_path,
        _render_text(
            run_id=report.run_id,
            verdict=report.verdict,
            complete=report.complete,
            cases=report.cases,
            findings=report.findings,
        ),
    )
    if _junit_inventory(junit_path) != _expected_inventory(report.cases, report.findings):
        raise InvalidPhase3Qualification("domain JUnit projection lost evidence")
    return Phase3DomainFinalizedOutputs(
        canonical_json=canonical_path,
        junit_xml=junit_path,
        text_report=text_path,
        content_sha256=digest,
    )


__all__ = [
    "InvalidPhase3Qualification",
    "Phase3DomainFinalizedOutputs",
    "Phase3FinalizedOutputs",
    "exit_code_for_phase3",
    "exit_code_for_phase3_domain",
    "finalize_phase3_domain_report",
    "finalize_phase3_reports",
    "validate_aggregate_report",
    "validate_domain_report",
]
