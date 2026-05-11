from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mission_models import (
    CommunicationState,
    EnvironmentState,
    GoNoGoAction,
    GoNoGoDecision,
    ResourceState,
    RouteSegment,
)
from safety_models import SafetyEvent, SafetyEventType, SafetyLevel


@dataclass(frozen=True)
class MissionContext:
    resource_state: ResourceState
    environment_state: EnvironmentState
    communication_state: CommunicationState
    route_context: dict[str, Any]


@dataclass(frozen=True)
class GoNoGoEvaluation:
    decision: GoNoGoDecision
    safety_event: SafetyEvent | None = None


@dataclass(frozen=True)
class GoNoGoConfig:
    daylight_margin_seconds: int = 900
    min_delivery_confidence: float = 0.5
    high_weather_risk: float = 0.7
    concern_weather_risk: float = 0.85
    high_fatigue_score: float = 0.55
    low_pace_trend: float = 0.7


def load_mission_context(path: Path | str) -> MissionContext:
    payload = json.loads(Path(path).read_text())
    return MissionContext(
        resource_state=ResourceState.model_validate(payload["resource_state"]),
        environment_state=EnvironmentState.model_validate(payload["environment_state"]),
        communication_state=CommunicationState.model_validate(payload["communication_state"]),
        route_context=payload.get("route_context", {}),
    )


class GoNoGoEvaluator:
    def __init__(self, config: GoNoGoConfig | None = None):
        self.config = config or GoNoGoConfig()

    def evaluate(
        self,
        segment: RouteSegment,
        context: MissionContext,
        *,
        timestamp: float = 0.0,
    ) -> GoNoGoEvaluation:
        resource = context.resource_state
        environment = context.environment_state
        communication = context.communication_state

        if resource.device_battery < segment.requirement.min_device_battery:
            return self._event_decision(
                action=GoNoGoAction.TURN_BACK,
                reason="device battery is below the next segment requirement",
                event_type=SafetyEventType.RESOURCE_CONSTRAINT,
                level=SafetyLevel.CONCERN,
                timestamp=timestamp,
                confidence=0.9,
                details={
                    "segment_id": segment.segment_id,
                    "device_battery": resource.device_battery,
                    "min_device_battery": segment.requirement.min_device_battery,
                },
            )

        if resource.estimated_human_energy < segment.requirement.min_estimated_human_energy:
            return self._event_decision(
                action=GoNoGoAction.REST,
                reason="estimated human energy is below the next segment requirement",
                event_type=SafetyEventType.RESOURCE_CONSTRAINT,
                level=SafetyLevel.CONCERN,
                timestamp=timestamp,
                confidence=0.86,
                details={
                    "segment_id": segment.segment_id,
                    "estimated_human_energy": resource.estimated_human_energy,
                    "min_estimated_human_energy": segment.requirement.min_estimated_human_energy,
                },
            )

        daylight_remaining = environment.daylight_remaining_seconds
        if segment.requirement.requires_daylight and daylight_remaining is not None:
            required_daylight = segment.requirement.expected_duration_seconds + self.config.daylight_margin_seconds
            if daylight_remaining < required_daylight:
                return self._event_decision(
                    action=GoNoGoAction.HOLD,
                    reason="daylight remaining is below the next segment duration plus safety margin",
                    event_type=SafetyEventType.UNSAFE_CONTINUATION,
                    level=SafetyLevel.CONCERN,
                    timestamp=timestamp,
                    confidence=0.88,
                    details={
                        "segment_id": segment.segment_id,
                        "daylight_remaining_seconds": daylight_remaining,
                        "required_daylight_seconds": required_daylight,
                    },
                )

        best_delivery = communication.best_delivery_confidence
        high_risk_zone = context.route_context.get("control_zone_id") in {
            "zone_steep_descent",
            "zone_ridge_crossing",
            "zone_high_risk",
        }
        if high_risk_zone and best_delivery < self.config.min_delivery_confidence:
            return self._event_decision(
                action=GoNoGoAction.HOLD,
                reason="communication confidence is low inside a high-risk control zone",
                event_type=SafetyEventType.UNSAFE_CONTINUATION,
                level=SafetyLevel.WATCH,
                timestamp=timestamp,
                confidence=0.74,
                details={
                    "segment_id": segment.segment_id,
                    "control_zone_id": context.route_context.get("control_zone_id"),
                    "best_delivery_confidence": best_delivery,
                    "min_delivery_confidence": self.config.min_delivery_confidence,
                },
            )

        if segment.requirement.signal_expected and best_delivery < self.config.min_delivery_confidence:
            return self._event_decision(
                action=GoNoGoAction.HOLD,
                reason="communication confidence is below the next segment expectation",
                event_type=SafetyEventType.UNSAFE_CONTINUATION,
                level=SafetyLevel.WATCH,
                timestamp=timestamp,
                confidence=0.72,
                details={
                    "segment_id": segment.segment_id,
                    "best_delivery_confidence": best_delivery,
                    "min_delivery_confidence": self.config.min_delivery_confidence,
                },
            )

        if environment.weather_risk >= self.config.concern_weather_risk:
            return self._event_decision(
                action=GoNoGoAction.HOLD,
                reason="weather risk is high enough to make continuation unsafe",
                event_type=SafetyEventType.UNSAFE_CONTINUATION,
                level=SafetyLevel.CONCERN,
                timestamp=timestamp,
                confidence=0.84,
                details={
                    "segment_id": segment.segment_id,
                    "weather_risk": environment.weather_risk,
                    "threshold": self.config.concern_weather_risk,
                },
            )

        if environment.weather_risk >= self.config.high_weather_risk:
            return self._event_decision(
                action=GoNoGoAction.HOLD,
                reason="weather risk is deteriorating",
                event_type=SafetyEventType.UNSAFE_CONTINUATION,
                level=SafetyLevel.WATCH,
                timestamp=timestamp,
                confidence=0.7,
                details={
                    "segment_id": segment.segment_id,
                    "weather_risk": environment.weather_risk,
                    "threshold": self.config.high_weather_risk,
                },
            )

        if resource.fatigue_score >= self.config.high_fatigue_score or resource.pace_trend < self.config.low_pace_trend:
            return self._event_decision(
                action=GoNoGoAction.REST,
                reason="fatigue or pace trend suggests resting before continuing",
                event_type=SafetyEventType.RESOURCE_CONSTRAINT,
                level=SafetyLevel.WATCH,
                timestamp=timestamp,
                confidence=0.68,
                details={
                    "segment_id": segment.segment_id,
                    "fatigue_score": resource.fatigue_score,
                    "pace_trend": resource.pace_trend,
                },
            )

        decision = GoNoGoDecision(
            decision=GoNoGoAction.CONTINUE,
            reason="current resource, environment, and communication state meets next segment requirements",
            confidence=0.82,
        )
        return GoNoGoEvaluation(decision=decision)

    def _event_decision(
        self,
        *,
        action: GoNoGoAction,
        reason: str,
        event_type: SafetyEventType,
        level: SafetyLevel,
        timestamp: float,
        confidence: float,
        details: dict[str, Any],
    ) -> GoNoGoEvaluation:
        decision = GoNoGoDecision(
            decision=action,
            reason=reason,
            confidence=confidence,
        )
        event = SafetyEvent(
            event_type=event_type,
            level=level,
            timestamp=timestamp,
            reason=reason,
            confidence=confidence,
            details=details,
        )
        return GoNoGoEvaluation(decision=decision, safety_event=event)
