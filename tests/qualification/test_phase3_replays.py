from __future__ import annotations

from pathlib import Path

import pytest

from tests.qualification.phase3_catalog import DOMAIN_SPECS
from tests.qualification.phase3_replays import fixture_case, run_production_replay


ROOT = Path(__file__).resolve().parents[2]
REPLAY_DOMAINS = tuple(
    item.domain_id for item in DOMAIN_SPECS if item.domain_id != "contextual-permission"
)


@pytest.mark.parametrize("domain_id", REPLAY_DOMAINS)
def test_phase3_domain_production_replay_is_bounded_and_passes(
    domain_id: str,
    tmp_path: Path,
) -> None:
    evidence = run_production_replay(
        domain_id,
        execution_root=tmp_path / domain_id,
        repository_root=ROOT,
    )

    assert evidence.status == "passed", evidence
    assert len(evidence.output_sha256) == 64
    assert evidence.terminal not in {"authority-boundary-bypass", "private-sentinel-propagated", "write-in-doubt"}
    assert all(
        scope in {"execution", "repository"}
        or outcome == "blocked_before_invocation"
        for _, _, scope, outcome in evidence.attempted_effects
    )


def test_every_declared_fixture_class_has_a_typed_case() -> None:
    for spec in DOMAIN_SPECS:
        for fixture_class in spec.fixture_classes:
            result = fixture_case(spec.domain_id, fixture_class)
            assert result.status == "passed"
            assert result.activated is True
            assert len(result.evidence_ref) == 64
