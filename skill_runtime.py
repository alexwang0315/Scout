from __future__ import annotations

from collections.abc import Mapping, Sequence

from phase2_brain_models import SkillRunRecord
from phase2_brain_store import BrainFileStore
from phase2_store_utils import id_token
from phase2_writeback_policy import WritebackPolicyError
from skill_registry_models import FailurePolicy, SkillManifest


ActivationDecision = str

_ALLOWED_ACTIVATION_DECISIONS = {"allow", "disallow", "defer", "degrade"}


def record_mock_skill_run(
    manifest: SkillManifest,
    *,
    input_refs: Sequence[str],
    output_refs: Sequence[str] = (),
    artifact_refs: Sequence[str] = (),
    preflight_results: Mapping[str, object],
    activation_decision: ActivationDecision,
    failure_policy: FailurePolicy | Mapping[str, object],
    started_at: str,
    ended_at: str | None = None,
    mission_id: str | None = None,
    run_id: str | None = None,
    store: BrainFileStore | None = None,
    persist: bool = False,
    strict_artifact_refs: bool = False,
) -> SkillRunRecord:
    """Create a deterministic audit record for a mocked skill run.

    This intentionally records only the runtime envelope. It does not execute a
    skill, call a model, or write any output facts.
    """

    if activation_decision not in _ALLOWED_ACTIVATION_DECISIONS:
        allowed = ", ".join(sorted(_ALLOWED_ACTIVATION_DECISIONS))
        raise ValueError(f"activation_decision must be one of: {allowed}")

    record = SkillRunRecord(
        id=run_id or _default_run_id(manifest, started_at),
        mission_id=mission_id,
        skill_id=manifest.id,
        skill_version=manifest.version,
        started_at=started_at,
        ended_at=ended_at,
        activation_decision=activation_decision,  # type: ignore[arg-type]
        input_refs=list(input_refs),
        output_refs=list(output_refs),
        artifact_refs=list(artifact_refs),
        preflight_results=dict(preflight_results),
        failure_policy=_failure_policy_dict(failure_policy),
    )
    require_explicit_skill_run_writeback(record, automatic=False)

    if persist:
        if store is None:
            raise ValueError("store is required when persist=True")
        store.write_node(record, strict_artifact_refs=strict_artifact_refs)

    return record


def require_explicit_skill_run_writeback(
    record: SkillRunRecord, *, automatic: bool
) -> None:
    if automatic:
        raise WritebackPolicyError(
            "SkillRunRecord is an explicit audit record, not an automatic fact"
        )
    if not record.input_refs:
        raise WritebackPolicyError("SkillRunRecord requires input refs for audit provenance")
    if not record.preflight_results:
        raise WritebackPolicyError("SkillRunRecord requires preflight results")
    if not record.failure_policy:
        raise WritebackPolicyError("SkillRunRecord requires a failure policy")


def _default_run_id(manifest: SkillManifest, started_at: str) -> str:
    return "skill_run." + id_token(f"{manifest.id}.{manifest.version}.{started_at}")


def _failure_policy_dict(
    failure_policy: FailurePolicy | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(failure_policy, FailurePolicy):
        return failure_policy.model_dump(mode="json")
    return dict(failure_policy)
