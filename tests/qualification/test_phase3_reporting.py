from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from tests.qualification.contracts import canonical_sha256
from tests.qualification.phase3_catalog import DOMAIN_IDS
from tests.qualification.phase3_contracts import (
    Phase3AggregateReport,
    Phase3CaseResult,
    Phase3DomainReport,
)
from tests.qualification.phase3_reporting import (
    InvalidPhase3Qualification,
    exit_code_for_phase3,
    finalize_phase3_reports,
    validate_aggregate_report,
)


HASH = "a" * 64


def _reports() -> tuple[Phase3AggregateReport, dict[str, Phase3DomainReport]]:
    run_id = "dashboard.phase3.synthetic-run"
    domains = {
        domain_id: Phase3DomainReport(
            schema_version="dashboardQualificationDomainReport.v1",
            run_id=f"{run_id}.{domain_id}",
            aggregate_run_id=run_id,
            domain_id=domain_id,
            source_manifest_sha256=HASH,
            domain_model_sha256=canonical_sha256((domain_id, "model")),
            workspace_snapshot_sha256=None,
            verdict="pass",
            complete=True,
            cases=(
                Phase3CaseResult(
                    case_id=f"case:{domain_id}",
                    category="synthetic",
                    status="passed",
                    activated=True,
                    evidence_ref=canonical_sha256((domain_id, "evidence")),
                ),
            ),
        )
        for domain_id in DOMAIN_IDS
    }
    aggregate = Phase3AggregateReport(
        schema_version="dashboardQualificationAggregateReport.v1",
        run_id=run_id,
        claim="construction",
        design_sha256=HASH,
        phase2_report_sha256=HASH,
        repository_identity=HASH,
        source_manifest_sha256=HASH,
        workspace_snapshot_sha256=None,
        verdict="pass",
        complete=True,
        required_domain_ids=DOMAIN_IDS,
        domain_report_sha256=tuple(
            (domain_id, canonical_sha256(domains[domain_id])) for domain_id in DOMAIN_IDS
        ),
        cases=(
            Phase3CaseResult(
                case_id="aggregate:surface",
                category="aggregate",
                status="passed",
                activated=True,
                evidence_ref=HASH,
            ),
        ),
    )
    return aggregate, domains


def test_phase3_reports_finalize_atomically_with_projection_parity(tmp_path: Path) -> None:
    aggregate, domains = _reports()
    outputs = finalize_phase3_reports(aggregate, domains, tmp_path / "result")

    assert outputs.aggregate_json.is_file()
    assert outputs.aggregate_junit.is_file()
    assert outputs.aggregate_text.is_file()
    assert len(outputs.domain_outputs) == 9
    payload = json.loads(outputs.aggregate_json.read_text(encoding="utf-8"))
    assert payload["content_sha256"] == outputs.content_sha256
    assert exit_code_for_phase3(aggregate, domains, finalized=True) == 0


def test_omitted_domain_cannot_validate_or_exit_zero() -> None:
    aggregate, domains = _reports()
    domains.pop(DOMAIN_IDS[-1])

    with pytest.raises(InvalidPhase3Qualification, match="omitted"):
        validate_aggregate_report(aggregate, domains)
    assert exit_code_for_phase3(aggregate, domains, finalized=True) == 2


def test_foreign_or_mixed_run_domain_report_is_invalid() -> None:
    aggregate, domains = _reports()
    target = DOMAIN_IDS[0]
    domains[target] = dataclasses.replace(domains[target], aggregate_run_id="foreign-run")

    with pytest.raises(InvalidPhase3Qualification, match="foreign-run"):
        validate_aggregate_report(aggregate, domains)
    assert exit_code_for_phase3(aggregate, domains, finalized=True) == 2


def test_release_claim_without_workspace_snapshot_is_invalid() -> None:
    aggregate, domains = _reports()
    release = dataclasses.replace(aggregate, claim="release")

    with pytest.raises(InvalidPhase3Qualification, match="sealed workspace"):
        validate_aggregate_report(release, domains)


def test_incomplete_evidence_cannot_exit_zero() -> None:
    aggregate, domains = _reports()
    incomplete = dataclasses.replace(aggregate, complete=False, verdict="invalid")
    assert exit_code_for_phase3(incomplete, domains, finalized=True) == 2
