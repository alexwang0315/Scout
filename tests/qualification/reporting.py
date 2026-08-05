from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from tests.qualification.contracts import (
    ConcurrencyScheduleResult,
    Counterexample,
    EffectClassAuditResult,
    FaultResult,
    Finding,
    InvariantResult,
    MutationResult,
    ObligationResult,
    ProductionReplayResult,
    QualificationReport,
    canonical_json,
    canonical_sha256,
)


class InvalidQualificationRun(RuntimeError):
    """Raised when qualification evidence cannot be finalized safely."""


@dataclass(frozen=True)
class FinalizedOutputs:
    canonical_json: Path
    junit_xml: Path
    text_report: Path
    content_sha256: str


def _finding(value: dict[str, object]) -> Finding:
    return Finding(
        finding_id=str(value["finding_id"]),
        code=str(value["code"]),
        severity=str(value["severity"]),  # type: ignore[arg-type]
        summary=str(value["summary"]),
        requirement_refs=tuple(str(item) for item in value["requirement_refs"]),
        evidence_refs=tuple(str(item) for item in value["evidence_refs"]),
    )


def _report_from_mapping(value: dict[str, object]) -> QualificationReport:
    return QualificationReport(
        schema_version=str(value["schema_version"]),
        run_id=str(value["run_id"]),
        run_manifest_sha256=str(value["run_manifest_sha256"]),
        verdict=str(value["verdict"]),  # type: ignore[arg-type]
        complete=bool(value["complete"]),
        phase1_prerequisite_sha256=str(value["phase1_prerequisite_sha256"]),
        run_manifest_component_sha256=tuple(
            (str(item[0]), str(item[1]))
            for item in value["run_manifest_component_sha256"]  # type: ignore[union-attr]
        ),
        findings=tuple(_finding(item) for item in value["findings"]),  # type: ignore[arg-type]
        obligation_results=tuple(
            ObligationResult(
                obligation_id=str(item["obligation_id"]),
                status=str(item["status"]),  # type: ignore[arg-type]
                evidence_id=str(item["evidence_id"]),
                finding_ids=tuple(str(ref) for ref in item["finding_ids"]),
            )
            for item in value["obligation_results"]  # type: ignore[union-attr]
        ),
        replay_results=tuple(
            ProductionReplayResult(
                replay_id=str(item["replay_id"]),
                status=str(item["status"]),  # type: ignore[arg-type]
                observed_terminal_id=(
                    None
                    if item["observed_terminal_id"] is None
                    else str(item["observed_terminal_id"])
                ),
                covered_obligation_ids=tuple(
                    str(ref) for ref in item["covered_obligation_ids"]
                ),
                detail=str(item["detail"]),
            )
            for item in value["replay_results"]  # type: ignore[union-attr]
        ),
        effect_class_results=tuple(
            EffectClassAuditResult(
                effect_class=str(item["effect_class"]),
                static_status=str(item["static_status"]),  # type: ignore[arg-type]
                runtime_status=str(item["runtime_status"]),  # type: ignore[arg-type]
                canary_id=(
                    None if item["canary_id"] is None else str(item["canary_id"])
                ),
                observed_operation=(
                    None
                    if item["observed_operation"] is None
                    else str(item["observed_operation"])
                ),
                detail=str(item["detail"]),
            )
            for item in value["effect_class_results"]  # type: ignore[union-attr]
        ),
        fault_results=tuple(
            FaultResult(
                fault_id=str(item["fault_id"]),
                status=str(item["status"]),  # type: ignore[arg-type]
                observed_terminal_kind=str(item["observed_terminal_kind"]),
                detail=str(item["detail"]),
                activated=bool(item["activated"]),
                execution_identity=str(item["execution_identity"]),
            )
            for item in value["fault_results"]  # type: ignore[union-attr]
        ),
        concurrency_results=tuple(
            ConcurrencyScheduleResult(
                schedule_id=str(item["schedule_id"]),
                status=str(item["status"]),  # type: ignore[arg-type]
                observed_result=str(item["observed_result"]),
                detail=str(item["detail"]),
                activated=bool(item["activated"]),
                execution_identity=str(item["execution_identity"]),
            )
            for item in value["concurrency_results"]  # type: ignore[union-attr]
        ),
        mutation_results=tuple(
            MutationResult(
                mutant_id=str(item["mutant_id"]),
                activated=bool(item["activated"]),
                status=str(item["status"]),  # type: ignore[arg-type]
                observed_finding_codes=tuple(
                    str(code) for code in item["observed_finding_codes"]
                ),
                detail=str(item["detail"]),
            )
            for item in value["mutation_results"]  # type: ignore[union-attr]
        ),
        counterexamples=tuple(
            Counterexample(
                counterexample_id=str(item["counterexample_id"]),
                start_state_id=str(item["start_state_id"]),
                transition_ids=tuple(str(ref) for ref in item["transition_ids"]),
                state_ids=tuple(str(ref) for ref in item["state_ids"]),
                finding_code=str(item["finding_code"]),
            )
            for item in value["counterexamples"]  # type: ignore[union-attr]
        ),
        invariant_results=tuple(
            InvariantResult(
                invariant_id=str(item["invariant_id"]),
                status=str(item["status"]),  # type: ignore[arg-type]
                evidence_id=str(item["evidence_id"]),
                finding_ids=tuple(str(ref) for ref in item["finding_ids"]),
            )
            for item in value["invariant_results"]  # type: ignore[union-attr]
        ),
        unresolved_state_ids=tuple(
            str(item) for item in value["unresolved_state_ids"]  # type: ignore[union-attr]
        ),
        coverage_inventory=tuple(
            (str(item[0]), str(item[1]))
            for item in value["coverage_inventory"]  # type: ignore[union-attr]
        ),
        telemetry=tuple(
            (str(item[0]), int(item[1]))
            for item in value["telemetry"]  # type: ignore[union-attr]
        ),
    )


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _blocking_findings(report: QualificationReport) -> tuple[Finding, ...]:
    return tuple(
        sorted(
            (item for item in report.findings if item.severity == "blocking"),
            key=lambda item: item.finding_id,
        )
    )


def _junit_evidence_cases(
    report: QualificationReport,
) -> tuple[tuple[str, str, str, bool, str], ...]:
    cases: list[tuple[str, str, str, bool, str]] = []
    cases.extend(
        (
            f"obligation:{item.obligation_id}",
            "qualification.obligation",
            item.status,
            item.status == "passed",
            item.evidence_id,
        )
        for item in report.obligation_results
    )
    cases.extend(
        (
            f"invariant:{item.invariant_id}",
            "qualification.invariant",
            item.status,
            item.status == "passed",
            item.evidence_id,
        )
        for item in report.invariant_results
    )
    cases.extend(
        (
            f"replay:{item.replay_id}",
            "qualification.replay",
            item.status,
            item.status in {"passed", "infeasible"},
            item.detail,
        )
        for item in report.replay_results
    )
    cases.extend(
        (
            f"effect-class:{item.effect_class}",
            "qualification.effect-class",
            f"static={item.static_status},runtime={item.runtime_status}",
            item.static_status == "passed" and item.runtime_status == "passed",
            item.detail,
        )
        for item in report.effect_class_results
    )
    cases.extend(
        (
            f"fault:{item.fault_id}",
            "qualification.fault",
            item.status,
            item.status == "passed",
            item.detail,
        )
        for item in report.fault_results
    )
    cases.extend(
        (
            f"concurrency:{item.schedule_id}",
            "qualification.concurrency",
            item.status,
            item.status == "passed",
            item.detail,
        )
        for item in report.concurrency_results
    )
    cases.extend(
        (
            f"mutation:{item.mutant_id}",
            "qualification.mutation",
            item.status,
            item.activated and item.status == "killed",
            item.detail,
        )
        for item in report.mutation_results
    )
    return tuple(cases)


def _render_junit(report: QualificationReport) -> str:
    blocking = _blocking_findings(report)
    evidence_cases = _junit_evidence_cases(report)
    failed_evidence = tuple(item for item in evidence_cases if not item[3])
    case_count = len(evidence_cases) + len(blocking)
    suite = ET.Element(
        "testsuite",
        {
            "name": "dashboard-internal-qualification",
            "run_id": report.run_id,
            "verdict": report.verdict,
            "complete": str(report.complete).lower(),
            "tests": str(max(1, case_count)),
            "failures": str(len(failed_evidence) + len(blocking)),
            "errors": "0",
        },
    )
    if not evidence_cases and not blocking:
        ET.SubElement(
            suite,
            "testcase",
            {"name": "qualification", "classname": report.run_id},
        )
    for name, classname, status, accepted, detail in evidence_cases:
        case = ET.SubElement(
            suite,
            "testcase",
            {"name": name, "classname": classname, "status": status},
        )
        if not accepted:
            failure = ET.SubElement(
                case,
                "failure",
                {
                    "type": "evidence",
                    "message": detail or f"{name} has status {status}",
                },
            )
            failure.text = status
    for item in blocking:
        case = ET.SubElement(
            suite,
            "testcase",
            {
                "name": f"finding:{item.finding_id}",
                "classname": item.code,
                "status": "failed",
            },
        )
        failure = ET.SubElement(
            case,
            "failure",
            {
                "type": item.severity,
                "message": item.summary,
                "finding_id": item.finding_id,
            },
        )
        failure.text = item.code
    return ET.tostring(suite, encoding="unicode") + "\n"


def _render_text(report: QualificationReport) -> str:
    surviving_mutants = tuple(
        item
        for item in report.mutation_results
        if not item.activated or item.status != "killed"
    )
    reproduction_domain = report.run_id.split(".phase", 1)[0]
    lines = [
        f"run_id\t{report.run_id}",
        f"verdict\t{report.verdict}",
        f"complete\t{str(report.complete).lower()}",
        f"obligations\t{len(report.obligation_results)}",
        f"invariants\t{len(report.invariant_results)}",
        f"replays\t{len(report.replay_results)}",
        f"effect_classes\t{len(report.effect_class_results)}",
        f"faults\t{len(report.fault_results)}",
        f"concurrency_schedules\t{len(report.concurrency_results)}",
        f"mutants\t{len(report.mutation_results)}",
        (
            "reproduce\tpython3 tools/verify_dashboard_internal_qualification.py "
            f"--domain {reproduction_domain} --execution-dir <unique-empty-dir> "
            "--output-dir <new-result-dir>"
        ),
    ]
    lines.extend(
        "\t".join(
            (
                "BLOCKING",
                item.finding_id,
                item.severity,
                item.code,
                item.summary.replace("\t", " ").replace("\n", " "),
            )
        )
        for item in _blocking_findings(report)
    )
    lines.extend(f"UNCOVERED_STATE\t{item}" for item in report.unresolved_state_ids)
    lines.extend(
        "\t".join(
            (
                "COUNTEREXAMPLE",
                item.counterexample_id,
                item.finding_code,
                ",".join(item.transition_ids),
            )
        )
        for item in report.counterexamples
    )
    lines.extend(
        "\t".join(
            (
                "SURVIVED_MUTANT",
                item.mutant_id,
                item.status,
                str(item.activated).lower(),
            )
        )
        for item in surviving_mutants
    )
    return "\n".join(lines) + "\n"


def load_finalized_report(path: Path) -> QualificationReport:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
        expected = value.pop("content_sha256")
        if canonical_sha256(value) != expected:
            raise InvalidQualificationRun("canonical report hash mismatch")
        if value.get("schema_version") != "dashboardQualificationArtifact.v1":
            raise InvalidQualificationRun("unknown canonical artifact schema")
        report_value = value["report"]
        if not isinstance(report_value, dict):
            raise TypeError("report must be an object")
        report = _report_from_mapping(report_value)
        if (
            report.schema_version != "dashboardQualificationReport.v2"
            or report.verdict not in {"pass", "fail", "invalid"}
            or not report.run_id
            or len(report.run_manifest_sha256) != 64
            or len(report.phase1_prerequisite_sha256) != 64
            or any(
                len(digest) != 64
                for _, digest in report.run_manifest_component_sha256
            )
        ):
            raise InvalidQualificationRun("canonical report schema validation failed")
        return report
    except InvalidQualificationRun:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise InvalidQualificationRun(f"invalid canonical report: {error}") from error


def finalize_report(
    report: QualificationReport,
    result_root: Path,
) -> FinalizedOutputs:
    root = Path(result_root)
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise InvalidQualificationRun(
            f"result root already exists and could contain stale evidence: {root}"
        ) from error

    canonical_path = root / "qualification-report.json"
    junit_path = root / "qualification-report.junit.xml"
    text_path = root / "qualification-report.txt"
    payload = {
        "schema_version": "dashboardQualificationArtifact.v1",
        "report": json.loads(canonical_json(report)),
    }
    content_sha256 = canonical_sha256(payload)
    finalized_payload = {**payload, "content_sha256": content_sha256}
    try:
        _atomic_write(canonical_path, canonical_json(finalized_payload) + "\n")
        authoritative = load_finalized_report(canonical_path)
        if authoritative != report:
            raise InvalidQualificationRun("canonical report round trip changed content")
        _atomic_write(junit_path, _render_junit(authoritative))
        _atomic_write(text_path, _render_text(authoritative))
        expected_inventory = tuple(
            (item.finding_id, item.severity)
            for item in _blocking_findings(authoritative)
        )
        if projection_blocking_inventory(junit_path) != expected_inventory:
            raise InvalidQualificationRun(
                "JUnit projection changed the blocking inventory"
            )
        if projection_blocking_inventory(text_path) != expected_inventory:
            raise InvalidQualificationRun(
                "text projection changed the blocking inventory"
            )
        expected_junit_cases = {
            *(item[0] for item in _junit_evidence_cases(authoritative)),
            *(f"finding:{item.finding_id}" for item in _blocking_findings(authoritative)),
        }
        if not expected_junit_cases:
            expected_junit_cases = {"qualification"}
        if junit_case_inventory(junit_path) != tuple(sorted(expected_junit_cases)):
            raise InvalidQualificationRun(
                "JUnit projection changed the evidence-case inventory"
            )
        if _projection_verdict(junit_path) != (
            authoritative.verdict,
            authoritative.complete,
        ):
            raise InvalidQualificationRun("JUnit projection changed the verdict")
        if _projection_verdict(text_path) != (
            authoritative.verdict,
            authoritative.complete,
        ):
            raise InvalidQualificationRun("text projection changed the verdict")
    except Exception as error:
        if isinstance(error, InvalidQualificationRun):
            raise
        raise InvalidQualificationRun(f"report finalization failed: {error}") from error
    return FinalizedOutputs(
        canonical_json=canonical_path,
        junit_xml=junit_path,
        text_report=text_path,
        content_sha256=content_sha256,
    )


def projection_blocking_inventory(path: Path) -> tuple[tuple[str, str], ...]:
    source = Path(path)
    if source.suffix == ".xml":
        root = ET.fromstring(source.read_text(encoding="utf-8"))
        inventory = {
            (str(item.attrib["finding_id"]), str(item.attrib["type"]))
            for item in root.findall(".//failure")
            if "finding_id" in item.attrib and "type" in item.attrib
        }
    else:
        inventory = {
            (parts[1], parts[2])
            for line in source.read_text(encoding="utf-8").splitlines()
            if (parts := line.split("\t", 4))[0] == "BLOCKING"
            and len(parts) >= 3
        }
    return tuple(sorted(inventory))


def junit_case_inventory(path: Path) -> tuple[str, ...]:
    root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    return tuple(
        sorted(str(item.attrib["name"]) for item in root.findall(".//testcase"))
    )


def _projection_verdict(path: Path) -> tuple[str, bool]:
    source = Path(path)
    if source.suffix == ".xml":
        root = ET.fromstring(source.read_text(encoding="utf-8"))
        return (
            str(root.attrib.get("verdict", "")),
            root.attrib.get("complete") == "true",
        )
    values = {
        parts[0]: parts[1]
        for line in source.read_text(encoding="utf-8").splitlines()
        if len(parts := line.split("\t", 1)) == 2
        and parts[0] in {"verdict", "complete"}
    }
    return values.get("verdict", ""), values.get("complete") == "true"


def exit_code_for(report: QualificationReport, *, finalized: bool) -> int:
    if not finalized or report.verdict == "invalid" or not report.complete:
        return 2
    if report.verdict == "fail" or _blocking_findings(report):
        return 1
    return 0


__all__ = [
    "FinalizedOutputs",
    "InvalidQualificationRun",
    "exit_code_for",
    "finalize_report",
    "junit_case_inventory",
    "load_finalized_report",
    "projection_blocking_inventory",
]
