from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scout_runtime_safety_production_qualification import (
    evaluate_production_safety_qualification_threat_coverage,
    verify_production_safety_qualification_threat_coverage_source_integrity,
)
from scout_runtime_safety_threat_coverage_evidence import (
    MODE_TEST_SELECTORS,
    THREAT_TEST_SELECTORS,
    write_threat_mode_coverage_evidence,
)


def _junit(names: set[str]) -> str:
    cases = "".join(
        f"<testcase classname='tests.safety' name='{name}' />"
        for name in sorted(names)
    )
    return f"<testsuite tests='{len(names)}' failures='0'>{cases}</testsuite>\n"


def _reviewed_after(path) -> datetime:
    observed_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return observed_at + timedelta(seconds=1)


def test_threat_mode_evidence_builds_source_verified_complete_coverage(
    tmp_path,
) -> None:
    names = {
        selector
        for selectors in [
            *THREAT_TEST_SELECTORS.values(),
            *MODE_TEST_SELECTORS.values(),
        ]
        for selector in selectors
    }
    junit = tmp_path / "threat-mode.junit.xml"
    junit.write_text(_junit(names), encoding="utf-8")
    manifest, package, manifest_path, package_path = (
        write_threat_mode_coverage_evidence(
            junit_path=junit,
            output_root=tmp_path,
            qualification_root_ref="prod://qualification/run-001",
            reviewer_ref="operator://qualification/scout-owner/threat-review",
            reviewed_at=_reviewed_after(junit),
        )
    )
    integrity = verify_production_safety_qualification_threat_coverage_source_integrity(
        manifest,
        package,
        root_path=tmp_path,
        source_path="prod://qualification/run-001/threat-coverage/source-integrity",
    )
    audit = evaluate_production_safety_qualification_threat_coverage(
        manifest,
        source_integrity_report=integrity,
        source_path="prod://qualification/run-001/threat-coverage/audit",
    )

    assert manifest_path.is_file()
    assert package_path.is_file()
    assert len(manifest.threat_cases) == 8
    assert len(manifest.qualification_modes) == 15
    assert len(package.artifacts) == 23
    assert integrity.status == "source_integrity_verified"
    assert audit.status == "qualification_threat_coverage_passed"


def test_threat_mode_evidence_keeps_missing_selector_failed(tmp_path) -> None:
    names = {
        selector
        for selectors in [
            *THREAT_TEST_SELECTORS.values(),
            *MODE_TEST_SELECTORS.values(),
        ]
        for selector in selectors
    }
    names.remove("test_prompt_injection_cannot_loosen_assistant_boundary")
    junit = tmp_path / "threat-mode.junit.xml"
    junit.write_text(_junit(names), encoding="utf-8")
    manifest, package, _, _ = write_threat_mode_coverage_evidence(
        junit_path=junit,
        output_root=tmp_path,
        qualification_root_ref="prod://qualification/run-001",
        reviewer_ref="operator://qualification/scout-owner/threat-review",
        reviewed_at=_reviewed_after(junit),
    )
    injection = next(
        case for case in manifest.threat_cases if case.threat_id == "prompt_injection"
    )
    evidence = json.loads(
        (
            tmp_path
            / "threat-coverage/evidence/threats/prompt_injection.json"
        ).read_text(encoding="utf-8")
    )

    assert injection.mitigated is False
    assert evidence["all_required_tests_passed"] is False
    assert package.credential_material_embedded is False
