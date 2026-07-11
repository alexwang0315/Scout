"""Deterministic evaluation for Scout outbound standing grants."""

from __future__ import annotations

from datetime import UTC, datetime

from scout.schemas.outbound import (
    OutboundActionIntent,
    OutboundDecisionStatus,
    OutboundGrantDecision,
    OutboundStandingGrant,
    is_safety_message_class,
)


def evaluate_outbound_standing_grant(
    intent: OutboundActionIntent,
    *,
    grant: OutboundStandingGrant | None,
    now: datetime | None = None,
    prior_send_count: int = 0,
) -> OutboundGrantDecision:
    """Decide whether a summarized outbound intent may execute automatically."""

    if prior_send_count < 0:
        raise ValueError("prior_send_count cannot be negative")
    evaluation_time = now or datetime.now(UTC)
    if evaluation_time.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    hard_blockers = _hard_blockers(intent)
    if hard_blockers:
        return _decision(
            intent,
            grant=grant,
            status=OutboundDecisionStatus.BLOCKED,
            blockers=hard_blockers,
        )

    if grant is None:
        return _decision(
            intent,
            grant=None,
            status=OutboundDecisionStatus.NEEDS_APPROVAL,
            blockers=["standing_grant_missing"],
        )

    approval_blockers = _grant_scope_blockers(
        intent,
        grant=grant,
        now=evaluation_time,
        prior_send_count=prior_send_count,
    )
    if approval_blockers:
        return _decision(
            intent,
            grant=grant,
            status=OutboundDecisionStatus.NEEDS_APPROVAL,
            blockers=approval_blockers,
        )

    return _decision(
        intent,
        grant=grant,
        status=OutboundDecisionStatus.ALLOWED,
        blockers=[],
    )


def _hard_blockers(intent: OutboundActionIntent) -> list[str]:
    blockers: list[str] = []
    if intent.safety_related:
        blockers.append("safety_related_outbound_blocked")
    if intent.safety_mutation_requested:
        blockers.append("safety_mutation_outbound_blocked")
    if intent.phase1_l0_l4_state_mutation_requested:
        blockers.append("phase1_l0_l4_mutation_outbound_blocked")
    if is_safety_message_class(intent.message_class):
        blockers.append("safety_message_class_blocked")
    if intent.contains_secret_material:
        blockers.append("secret_material_outbound_blocked")
    return list(dict.fromkeys(blockers))


def _grant_scope_blockers(
    intent: OutboundActionIntent,
    *,
    grant: OutboundStandingGrant,
    now: datetime,
    prior_send_count: int,
) -> list[str]:
    blockers: list[str] = []
    if not grant.active:
        blockers.append("standing_grant_inactive")
    if now < grant.issued_at:
        blockers.append("standing_grant_not_yet_valid")
    if now >= grant.expires_at:
        blockers.append("standing_grant_expired")
    if intent.scope_ref != grant.scope_ref:
        blockers.append("scope_ref_not_granted")
    if intent.provider_ref not in grant.allowed_provider_refs:
        blockers.append("provider_ref_not_granted")
    if intent.recipient_ref not in grant.allowed_recipient_refs:
        blockers.append("recipient_ref_not_granted")
    if intent.message_class not in grant.allowed_message_classes:
        blockers.append("message_class_not_granted")
    if intent.topic_ref is not None and intent.topic_ref not in grant.allowed_topic_refs:
        blockers.append("topic_ref_not_granted")
    if any(item not in grant.allowed_data_classes for item in intent.data_classes):
        blockers.append("data_class_not_granted")
    if intent.priority not in grant.allowed_priorities:
        blockers.append("priority_not_granted")
    if prior_send_count >= grant.max_send_count:
        blockers.append("standing_grant_send_limit_reached")
    return blockers


def _decision(
    intent: OutboundActionIntent,
    *,
    grant: OutboundStandingGrant | None,
    status: OutboundDecisionStatus,
    blockers: list[str],
) -> OutboundGrantDecision:
    return OutboundGrantDecision(
        status=status,
        intent_id=intent.intent_id,
        grant_id=grant.grant_id if grant is not None else None,
        auto_execute_allowed=status is OutboundDecisionStatus.ALLOWED,
        requires_user_approval=status is OutboundDecisionStatus.NEEDS_APPROVAL,
        blocker_reasons=blockers,
    )


__all__ = ["evaluate_outbound_standing_grant"]
