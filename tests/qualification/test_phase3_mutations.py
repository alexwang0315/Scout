from __future__ import annotations

from pathlib import Path

from tests.qualification.phase3_discovery import discover_dashboard_surface
from tests.qualification.phase3_mutations import run_phase3_mutations
from tests.qualification.test_phase3_reporting import _reports


ROOT = Path(__file__).resolve().parents[2]


def test_required_phase3_false_pass_mutants_are_isolated_activated_and_killed(
    tmp_path: Path,
) -> None:
    aggregate, domains = _reports()
    surface = discover_dashboard_surface(ROOT)
    retained = {
        "phase2-mutant-a": (True, "killed", ("PHASE2-EXPECTED-A",)),
        "phase2-mutant-b": (True, "killed", ("PHASE2-EXPECTED-B",)),
    }

    results = run_phase3_mutations(
        repository_root=ROOT,
        execution_root=tmp_path / "mutants",
        surface_manifest=surface.manifest,
        aggregate_report=aggregate,
        domain_reports=domains,
        retained_phase2_mutants=retained,
    )

    assert len(results) == len(retained) + 17
    assert all(item.activated for item in results)
    assert all(item.status == "passed" for item in results)
    assert all(len(item.finding_codes) == 1 for item in results)
    required_ids = {
        "minimum-risk-tier-downgraded",
        "not-applicable-witness-forged",
        "non-route-executable-entrypoint-removed",
        "required-cross-domain-edge-removed",
        "required-conflict-pair-removed",
        "required-shared-yield-removed",
        "confirmation-reused-after-subject-change",
        "admission-reused-after-policy-or-generation-change",
        "workspace-concurrent-mutation-accepted",
        "workspace-unknown-entry-omitted",
        "workspace-path-alias-accepted",
        "stale-foreign-or-mixed-domain-evidence-accepted",
        "privacy-sentinel-propagated",
        "authority-candidate-boundary-bypassed",
        "aggregate-domain-omitted",
        "aggregate-incomplete-evidence-exit-zero",
        "phase2-non-adapter-manifest-drift-accepted",
    }
    assert required_ids <= {
        item.case_id.removeprefix("mutation:") for item in results
    }
