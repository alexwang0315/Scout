from __future__ import annotations

from typing import Any


def classify_dr_distance_source(
    *,
    source: str | None,
    provider: str | None = None,
) -> dict[str, Any]:
    source_text = _clean(source)
    provider_text = _clean(provider)
    normalized = " ".join(value.lower() for value in (source_text, provider_text) if value)

    if not normalized:
        return _review(
            source=source_text,
            provider=provider_text,
            kind="unknown_dr_distance_source",
            navigation_allowed=False,
            evidence_scope="missing_source_metadata",
            reason="DR distance evidence must disclose its source/provider before it can prove navigation.",
        )

    if any(token in normalized for token in ("operator", "manual", "human_entered", "hand_entered")):
        return _review(
            source=source_text,
            provider=provider_text,
            kind="manual_operator_distance_delta",
            navigation_allowed=False,
            evidence_scope="field_rehearsal_only",
            reason="Operator-entered distance is useful for rehearsal but is not a trusted navigation odometry source.",
        )

    if "route_point_pdr_evidence" in normalized:
        return _review(
            source=source_text,
            provider=provider_text,
            kind="route_fixture_pdr_evidence",
            navigation_allowed=False,
            evidence_scope="fixture_replay_only",
            reason="Route-point PDR evidence is replay/fixture input, not live navigation odometry.",
        )

    if any(token in normalized for token in ("wheel", "encoder", "robot_odometry", "base_odom")):
        return _review(
            source=source_text,
            provider=provider_text,
            kind="wheel_or_encoder_odometry",
            navigation_allowed=True,
            evidence_scope="navigation_odometry_source",
            reason="Wheel/encoder odometry is an explicit DR distance source for navigation evidence.",
        )

    if "sensorlog_pedometer_distance" in normalized or "sensorlog_pedometer_steps" in normalized:
        return _review(
            source=source_text,
            provider=provider_text,
            kind="sensorlog_pedometer_pdr",
            navigation_allowed=True,
            evidence_scope="navigation_pdr_source",
            reason="SensorLog pedometer distance/steps are explicit PDR distance evidence.",
        )

    if "pedometer" in normalized:
        return _review(
            source=source_text,
            provider=provider_text,
            kind="pedometer_pdr",
            navigation_allowed=True,
            evidence_scope="navigation_pdr_source",
            reason="Pedometer-derived distance is explicit PDR evidence.",
        )

    if "odometry" in normalized or "dead_reckoning" in normalized or "dr_delta" in normalized:
        return _review(
            source=source_text,
            provider=provider_text,
            kind="declared_odometry_delta",
            navigation_allowed=True,
            evidence_scope="navigation_odometry_source",
            reason="Declared non-manual odometry/DR delta source is suitable for navigation evidence.",
        )

    return _review(
        source=source_text,
        provider=provider_text,
        kind="unknown_dr_distance_source",
        navigation_allowed=False,
        evidence_scope="unclassified_source_metadata",
        reason="DR distance source/provider is not recognized as navigation odometry or PDR evidence.",
    )


def _review(
    *,
    source: str | None,
    provider: str | None,
    kind: str,
    navigation_allowed: bool,
    evidence_scope: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "provider": provider,
        "kind": kind,
        "navigation_allowed": navigation_allowed,
        "evidence_scope": evidence_scope,
        "reason": reason,
    }


def _clean(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    cleaned = str(value).strip()
    return cleaned or None
