from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from phase2_brain_ingest import ingest_brain_node
from phase2_brain_models import SkillRunRecord
from phase2_brain_store import BrainFileStore
from skill_registry import load_skill_registry
from skill_runtime import ActivationDecision, record_mock_skill_run


DEFAULT_SCOUT_SKILL_REGISTRY_DIR = Path(__file__).resolve().parent / "skills" / "scout"


def record_and_ingest_mock_skill_run(
    store: BrainFileStore,
    skill_id: str,
    *,
    input_refs: Sequence[str],
    output_refs: Sequence[str] = (),
    artifact_refs: Sequence[str] = (),
    preflight_results: Mapping[str, object],
    activation_decision: ActivationDecision,
    started_at: str,
    ended_at: str | None = None,
    mission_id: str | None = None,
    run_id: str | None = None,
    registry_dir: Path | str = DEFAULT_SCOUT_SKILL_REGISTRY_DIR,
    automatic: bool = False,
    strict_artifact_refs: bool = False,
) -> SkillRunRecord:
    """Record a mocked Scout skill run and persist the audit record through Brain ingest."""

    manifest = load_skill_registry(registry_dir).get(skill_id)
    record = record_mock_skill_run(
        manifest,
        input_refs=input_refs,
        output_refs=output_refs,
        artifact_refs=artifact_refs,
        preflight_results=preflight_results,
        activation_decision=activation_decision,
        failure_policy=manifest.failure_policy,
        started_at=started_at,
        ended_at=ended_at,
        mission_id=mission_id,
        run_id=run_id,
    )
    ingest_brain_node(
        store,
        record,
        automatic=automatic,
        strict_artifact_refs=strict_artifact_refs,
    )
    return record
