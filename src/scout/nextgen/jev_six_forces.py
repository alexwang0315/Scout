"""Bounded Jev preflight contracts for the Six-Forces evaluator.

This adapter is deliberately advisory.  It sends only an allowlisted workspace
projection, deterministic QuestionContract/MSER state, and evidence metadata.
The answer evaluator remains the owner of tool execution, MSER enforcement, and
final verification.
"""

from __future__ import annotations

from typing import Any

from scout.schemas.base import SchemaModel

from .jev_decisions import AnonymizedWorkspaceProjection, JevDecisionRequest
from .jev_decision_service import (
    JevArtifactFamily,
    JevAuthorityClass,
    JevMSERCertificate,
    JevMSERStatus,
    JevQuestionClass,
    JevQuestionContract,
    JevToolFamily,
    _routing_questions,
)


class JevSixForcesPreflightMetadata(SchemaModel):
    """Typed, bounded metadata retained beside one Six-Forces model run."""

    question_contract: dict[str, Any]
    mser_certificate: dict[str, Any]
    allowed_tool_families: tuple[str, ...]
    deterministic_tool_ids: tuple[str, ...]
    candidate_only: bool = True
    runtime_safety_truth: bool = False


def _contract_for_force(force_code: str) -> JevQuestionContract:
    """Map a Six-Forces domain to an advisory bounded contract."""

    normalized = force_code.upper()
    if normalized == "EXP":
        return JevQuestionContract(
            question_class=JevQuestionClass.CROSS_ARTIFACT_JOIN,
            artifact_family=JevArtifactFamily.ROUTE,
            allowed_tool_families=(
                JevToolFamily.WORKSPACE_QUERY,
                JevToolFamily.PRAISONAI_INFORMATION_NEED,
                JevToolFamily.HUMAN_REVIEW,
            ),
            authority_class=JevAuthorityClass.LOW_RISK_CANDIDATE,
            required_domains=("route", "terrain", "weather"),
        )
    if normalized == "RPF":
        return JevQuestionContract(
            question_class=JevQuestionClass.SPATIAL,
            artifact_family=JevArtifactFamily.RISK,
            allowed_tool_families=(
                JevToolFamily.GIS_SPATIAL,
                JevToolFamily.WORKSPACE_QUERY,
                JevToolFamily.HUMAN_REVIEW,
            ),
            authority_class=JevAuthorityClass.SAFETY_SENSITIVE,
            required_domains=("route", "terrain"),
        )
    if normalized == "PER":
        return JevQuestionContract(
            question_class=JevQuestionClass.STATIC_FACT,
            artifact_family=JevArtifactFamily.PERMISSION,
            allowed_tool_families=(
                JevToolFamily.DATABASE_READ,
                JevToolFamily.WORKSPACE_QUERY,
                JevToolFamily.HUMAN_REVIEW,
            ),
            authority_class=JevAuthorityClass.AUTHORITY_BEARING,
            required_domains=("permission", "route"),
        )
    if normalized == "RTE":
        return JevQuestionContract(
            question_class=JevQuestionClass.SPATIAL,
            artifact_family=JevArtifactFamily.ROUTE,
            allowed_tool_families=(
                JevToolFamily.GIS_SPATIAL,
                JevToolFamily.WORKSPACE_QUERY,
                JevToolFamily.HUMAN_REVIEW,
            ),
            authority_class=JevAuthorityClass.SAFETY_SENSITIVE,
            required_domains=("route", "terrain"),
        )
    if normalized == "WTH":
        return JevQuestionContract(
            question_class=JevQuestionClass.CROSS_ARTIFACT_JOIN,
            artifact_family=JevArtifactFamily.WEATHER,
            allowed_tool_families=(
                JevToolFamily.FRESHNESS_REFRESH,
                JevToolFamily.WORKSPACE_QUERY,
                JevToolFamily.HUMAN_REVIEW,
            ),
            authority_class=JevAuthorityClass.SAFETY_SENSITIVE,
            required_domains=("weather", "route"),
        )
    return JevQuestionContract(
        question_class=JevQuestionClass.SPATIAL,
        artifact_family=JevArtifactFamily.MAP,
        allowed_tool_families=(
            JevToolFamily.GIS_SPATIAL,
            JevToolFamily.WORKSPACE_QUERY,
            JevToolFamily.FRESHNESS_REFRESH,
            JevToolFamily.HUMAN_REVIEW,
        ),
        authority_class=JevAuthorityClass.SAFETY_SENSITIVE,
        required_domains=("route", "map"),
    )


def _mser_status(mser_context: dict[str, Any] | None) -> JevMSERStatus:
    raw = str(((mser_context or {}).get("sufficiency") or {}).get("status") or "")
    try:
        return JevMSERStatus(raw)
    except ValueError:
        return JevMSERStatus.AMBIGUOUS


def build_six_forces_jev_request(
    *,
    model_id: str,
    projection: AnonymizedWorkspaceProjection,
    run: dict[str, Any],
    mser_context: dict[str, Any] | None,
    compact_evidence: dict[str, Any],
    deterministic_tool_ids: list[str],
) -> tuple[JevDecisionRequest, JevSixForcesPreflightMetadata]:
    """Build a path-free request with deterministic contract and MSER gate."""

    contract = _contract_for_force(str(run.get("force_code") or "NAV"))
    status = _mser_status(mser_context)
    compact_sufficiency = (mser_context or {}).get("sufficiency") or {}
    certificate = JevMSERCertificate(
        status=status,
        information_need=bool(compact_sufficiency.get("information_needs")),
        synthesis_failed=False,
    )
    evidence_catalog = [
        {
            "tool_id": item.get("tool_id"),
            "status": item.get("status"),
            "answerability": item.get("answerability"),
            "missing_fields": list(item.get("missing_fields") or []),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for item in compact_evidence.get("tools") or []
        if isinstance(item, dict) and item.get("tool_id")
    ]
    state = {
        "task_kind": "six_forces_answer_preflight",
        "language": "zh-tw",
        "user_question": str(run["question_text"]),
        "force_code": str(run.get("force_code") or ""),
        "scenario_id": str(run.get("scenario_id") or ""),
        "variant_id": str(run.get("variant_id") or ""),
        "workspace_projection": projection.model_dump(mode="json"),
        "question_contract": contract.model_dump(mode="json"),
        "mser_certificate": certificate.model_dump(mode="json"),
        "deterministic_tool_ids": list(deterministic_tool_ids),
        "evidence_catalog": evidence_catalog,
        "missing_evidence": list(
            str(item)
            for item in compact_evidence.get("missing_evidence") or []
            if item
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    request = JevDecisionRequest(
        model=model_id,
        state=state,
        questions=_routing_questions(),
    )
    metadata = JevSixForcesPreflightMetadata(
        question_contract=contract.model_dump(mode="json"),
        mser_certificate=certificate.model_dump(mode="json"),
        allowed_tool_families=tuple(
            item.value for item in contract.allowed_tool_families
        ),
        deterministic_tool_ids=tuple(deterministic_tool_ids),
    )
    return request, metadata


__all__ = [
    "JevSixForcesPreflightMetadata",
    "build_six_forces_jev_request",
]
