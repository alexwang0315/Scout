"""Deterministic MSER classification, reduction, and planning prototype."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

from scout.schemas.mser import (
    CompactDimension,
    CompactSignal,
    DecisionCompactProfile,
    DecisionCriticality,
    DecisionIntent,
    DecisionType,
    DimensionCoverage,
    DimensionRequirement,
    EnvironmentalRepresentation,
    GapKind,
    InformationNeed,
    KnowledgeCandidate,
    MSERDecisionPacket,
    MSERStage,
    MemoryEvent,
    MinimalSufficientContext,
    MinimalToolPlan,
    PlannedCompactTool,
    ReducedKnowledge,
    ReducedMemory,
    SignalAvailability,
    SufficiencyCertificate,
    SufficiencyStatus,
    ToolCapability,
)


def _requirement(
    dimension: CompactDimension,
    reason: str,
    *,
    confidence: float = 0.55,
    max_age_seconds: int | None = None,
) -> DimensionRequirement:
    return DimensionRequirement(
        dimension=dimension,
        reason=reason,
        minimum_confidence=confidence,
        max_age_seconds=max_age_seconds,
    )


_LIVE = 300
_NEAR_LIVE = 900
_FORECAST = 10_800
_PRETRIP = 86_400


def _profile(
    decision_type: DecisionType,
    criticality: DecisionCriticality,
    *requirements: DimensionRequirement,
    risk_preservation_threshold: float = 0.7,
) -> DecisionCompactProfile:
    return DecisionCompactProfile(
        profile_id=f"scout.mser.profile.{decision_type.value}.v0",
        decision_type=decision_type,
        requirements=requirements,
        criticality=criticality,
        risk_preservation_threshold=risk_preservation_threshold,
    )


DECISION_PROFILES: dict[DecisionType, DecisionCompactProfile] = {
    DecisionType.NAVIGATION: _profile(
        DecisionType.NAVIGATION,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.GPS_CONFIDENCE,
            "Position confidence is required before comparing movement to the route.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ROUTE_ALIGNMENT,
            "The decision needs current alignment with the intended route.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.TERRAIN_COMPLEXITY,
            "Complex terrain changes the consequence of navigation uncertainty.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.VISIBILITY,
            "Visibility controls whether visual navigation cues remain usable.",
            max_age_seconds=_NEAR_LIVE,
        ),
    ),
    DecisionType.HAZARD: _profile(
        DecisionType.HAZARD,
        DecisionCriticality.CRITICAL,
        _requirement(
            CompactDimension.CURRENT_HAZARD,
            "A hazard decision needs the currently observed or projected hazard.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.EXPOSURE_RISK,
            "Exposure determines the consequence of a slip or loss of control.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.SLIP_RISK,
            "Surface instability is a primary local hazard variable.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.ROCKFALL_RISK,
            "Rockfall evidence must be retained when assessing terrain hazard.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.WEATHER_TREND,
            "Changing weather can rapidly invalidate a static terrain estimate.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.TERRAIN_CONFIDENCE,
            "Scout must know how reliable the terrain abstraction is.",
            confidence=0.6,
            max_age_seconds=_PRETRIP,
        ),
        risk_preservation_threshold=0.55,
    ),
    DecisionType.PHOTOGRAPHY: _profile(
        DecisionType.PHOTOGRAPHY,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.EXPOSURE_RISK,
            "Stopping and attention diversion are unsafe in exposed terrain.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.WEATHER_STABILITY,
            "The available stopping window depends on near-term weather stability.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.TEAM_DISTANCE,
            "A stop must not create an unobserved team separation.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.REMAINING_DAYLIGHT,
            "A discretionary stop consumes the remaining daylight margin.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ESCAPE_COST,
            "A stop is less tolerable where retreat is slow or difficult.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.GPS_CONFIDENCE,
            "Position confidence binds the decision to the correct route segment.",
            confidence=0.6,
            max_age_seconds=_LIVE,
        ),
    ),
    DecisionType.REST: _profile(
        DecisionType.REST,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.EXPOSURE_RISK,
            "Rest duration depends on whether the current location is exposed.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.WEATHER_STABILITY,
            "Weather stability bounds how long remaining stationary is reasonable.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.TEAM_DISTANCE,
            "Rest must not produce an unsafe team gap.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.REMAINING_DAYLIGHT,
            "Rest consumes route schedule and daylight margin.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.FATIGUE_INDEX,
            "The benefit and urgency of rest depend on current fatigue.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ENERGY_RESERVE,
            "Energy reserve determines whether a short rest is sufficient.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.ESCAPE_COST,
            "Rest cannot consume the margin needed to exit a costly segment.",
            max_age_seconds=_PRETRIP,
        ),
    ),
    DecisionType.SUMMIT: _profile(
        DecisionType.SUMMIT,
        DecisionCriticality.CRITICAL,
        _requirement(
            CompactDimension.ROUTE_PROGRESS,
            "Summit feasibility depends on current progress, not planned progress.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.REMAINING_DAYLIGHT,
            "The summit and return must fit inside the usable daylight window.",
            confidence=0.7,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.WEATHER_STABILITY,
            "A summit commitment requires a stable enough weather window.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.WEATHER_TREND,
            "The trend matters more than the current snapshot near a summit.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.DANGER_WINDOW,
            "The route timeline must be compared with the next danger window.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.FORECAST_CONFIDENCE,
            "Forecast uncertainty limits how strongly weather can support go/no-go.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.ENERGY_RESERVE,
            "The team needs reserve for the return, not only ascent.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.SAFETY_MARGIN,
            "Summit decisions consume multiple independent safety margins.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ESCAPE_COST,
            "Commitment is constrained by the cost of retreat from later terrain.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.EMERGENCY_REACHABILITY,
            "Emergency reachability affects the consequence of committing onward.",
            max_age_seconds=_NEAR_LIVE,
        ),
        risk_preservation_threshold=0.5,
    ),
    DecisionType.RETREAT: _profile(
        DecisionType.RETREAT,
        DecisionCriticality.CRITICAL,
        _requirement(
            CompactDimension.CURRENT_HAZARD,
            "Retreat reasoning starts from the current hazard state.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ESCAPE_COST,
            "Scout must compare the costs of continuing, waiting, and retreating.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.ROUTE_ALIGNMENT,
            "Retreat direction is unsafe when route alignment is unknown.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.GPS_CONFIDENCE,
            "Location uncertainty must remain visible in a retreat decision.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.WEATHER_TREND,
            "Worsening conditions may close an otherwise available retreat route.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.DANGER_WINDOW,
            "Retreat must be compared with the next weather or daylight threshold.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.ENERGY_RESERVE,
            "The selected exit must fit current human capacity.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.COGNITIVE_CONFIDENCE,
            "Decision quality may be degraded by fatigue, cold, or distress.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.EMERGENCY_REACHABILITY,
            "Failure to complete retreat may require communication or rescue.",
            max_age_seconds=_NEAR_LIVE,
        ),
        risk_preservation_threshold=0.45,
    ),
    DecisionType.CAMP: _profile(
        DecisionType.CAMP,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.CAMP_VIABILITY,
            "Camp selection needs a compact assessment of the site itself.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.EXPOSURE_RISK,
            "Exposure can make an otherwise flat site unsuitable.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.WEATHER_TREND,
            "Overnight weather trend changes shelter and drainage requirements.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.WATER_MARGIN,
            "Overnight viability depends on usable water reserve or access.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.COMMUNICATION_RELIABILITY,
            "Camp changes the next expected communication opportunity.",
            max_age_seconds=_NEAR_LIVE,
        ),
    ),
    DecisionType.MEDICAL: _profile(
        DecisionType.MEDICAL,
        DecisionCriticality.CRITICAL,
        _requirement(
            CompactDimension.MEDICAL_URGENCY,
            "Medical action depends on symptom severity and progression.",
            confidence=0.7,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.COGNITIVE_CONFIDENCE,
            "Cognition is both a symptom and a decision reliability factor.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ENERGY_RESERVE,
            "Self-evacuation feasibility depends on remaining capacity.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.GPS_CONFIDENCE,
            "A medical handoff requires a reliable location.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.EMERGENCY_REACHABILITY,
            "Scout must know whether an escalation can reach an external party.",
            max_age_seconds=_LIVE,
        ),
        risk_preservation_threshold=0.4,
    ),
    DecisionType.COMMUNICATION: _profile(
        DecisionType.COMMUNICATION,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.COMMUNICATION_RELIABILITY,
            "The active bearer mix must be reduced to current reliability.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.COVERAGE_CONFIDENCE,
            "A prior coverage map is not equivalent to current reachability.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.EMERGENCY_REACHABILITY,
            "Emergency communication has stricter sufficiency requirements.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.GPS_CONFIDENCE,
            "Position is part of a useful communication or rescue handoff.",
            max_age_seconds=_LIVE,
        ),
    ),
    DecisionType.WEATHER: _profile(
        DecisionType.WEATHER,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.WEATHER_STABILITY,
            "Current stability summarizes the immediate operating window.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.WEATHER_TREND,
            "Trend prevents a current benign snapshot from hiding deterioration.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.DANGER_WINDOW,
            "The answer needs a route-relevant danger interval.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.FORECAST_CONFIDENCE,
            "Mountain forecast uncertainty must remain explicit.",
            max_age_seconds=_FORECAST,
        ),
    ),
    DecisionType.WATER: _profile(
        DecisionType.WATER,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.WATER_MARGIN,
            "Water decisions require current reserve plus expected consumption.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.ROUTE_PROGRESS,
            "The next reliable source must be measured from current progress.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.WEATHER_TREND,
            "Heat, rain, and cold alter consumption and source reliability.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.ENERGY_RESERVE,
            "Hydration and energy capacity are coupled during movement.",
            max_age_seconds=_NEAR_LIVE,
        ),
    ),
    DecisionType.WILDLIFE: _profile(
        DecisionType.WILDLIFE,
        DecisionCriticality.MODERATE,
        _requirement(
            CompactDimension.WILDLIFE_PRESSURE,
            "The decision needs observed signs and route-specific wildlife context.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.TEAM_DISTANCE,
            "Team spacing affects response options during an encounter.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ESCAPE_COST,
            "Terrain limits safe separation and avoidance options.",
            max_age_seconds=_PRETRIP,
        ),
    ),
    DecisionType.HISTORY: _profile(
        DecisionType.HISTORY,
        DecisionCriticality.LOW,
        _requirement(
            CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
            "Historical knowledge should be bound to the current route context.",
            confidence=0.45,
            max_age_seconds=None,
        ),
        _requirement(
            CompactDimension.ROUTE_PROGRESS,
            "Current route position selects the locally relevant historical layer.",
            confidence=0.5,
            max_age_seconds=_LIVE,
        ),
        risk_preservation_threshold=0.85,
    ),
    DecisionType.ROUTE_PLANNING: _profile(
        DecisionType.ROUTE_PLANNING,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.ROUTE_FEASIBILITY,
            "Planning needs a route-level feasibility abstraction.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.TERRAIN_COMPLEXITY,
            "Terrain complexity controls pace and route tolerance.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.ESCAPE_COST,
            "A route plan must retain retreat and bailout cost.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.WEATHER_STABILITY,
            "The selected time window must fit forecast stability.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.MISSION_MARGIN,
            "The route must fit time, energy, team, and equipment margins.",
            max_age_seconds=_NEAR_LIVE,
        ),
    ),
    DecisionType.READINESS_PACE: _profile(
        DecisionType.READINESS_PACE,
        DecisionCriticality.HIGH,
        _requirement(
            CompactDimension.ROUTE_FEASIBILITY,
            "Pace fit must be evaluated against the actual route workload.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.ROUTE_PROGRESS,
            "Current or historical progress anchors pace to the route timeline.",
            confidence=0.6,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.FATIGUE_INDEX,
            "Observed fatigue changes sustainable pace and decision quality.",
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ENERGY_RESERVE,
            "Route completion requires reserve beyond the next checkpoint.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.MISSION_MARGIN,
            "Schedule slack must absorb slower members, stops, and terrain delay.",
            max_age_seconds=_NEAR_LIVE,
        ),
        _requirement(
            CompactDimension.TERRAIN_COMPLEXITY,
            "Technical terrain changes the meaning of flat-ground pace.",
            max_age_seconds=_PRETRIP,
        ),
        _requirement(
            CompactDimension.REMAINING_DAYLIGHT,
            "Remaining daylight bounds whether the observed pace is acceptable.",
            confidence=0.6,
            max_age_seconds=_LIVE,
        ),
    ),
    DecisionType.GENERAL: _profile(
        DecisionType.GENERAL,
        DecisionCriticality.MODERATE,
        _requirement(
            CompactDimension.MISSION_MARGIN,
            "General operational questions need the current mission margin.",
            max_age_seconds=_NEAR_LIVE,
        ),
    ),
}

_MODIFIER_REQUIREMENTS: dict[DecisionType, tuple[DimensionRequirement, ...]] = {
    DecisionType.HAZARD: (
        _requirement(
            CompactDimension.CURRENT_HAZARD,
            "A hazard modifier adds the current hazard state without importing the full hazard profile.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.TERRAIN_CONFIDENCE,
            "A hazard modifier must preserve uncertainty in the terrain abstraction.",
            max_age_seconds=_PRETRIP,
        ),
    ),
    DecisionType.WEATHER: (
        _requirement(
            CompactDimension.WEATHER_TREND,
            "A weather modifier adds deterioration or improvement direction.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.DANGER_WINDOW,
            "A weather modifier adds the next route-relevant danger interval.",
            max_age_seconds=_FORECAST,
        ),
        _requirement(
            CompactDimension.FORECAST_CONFIDENCE,
            "A weather modifier preserves forecast uncertainty.",
            max_age_seconds=_FORECAST,
        ),
    ),
    DecisionType.NAVIGATION: (
        _requirement(
            CompactDimension.GPS_CONFIDENCE,
            "A navigation modifier binds the decision to a reliable current location.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.ROUTE_ALIGNMENT,
            "A navigation modifier preserves current route alignment.",
            confidence=0.65,
            max_age_seconds=_LIVE,
        ),
    ),
    DecisionType.MEDICAL: (
        _requirement(
            CompactDimension.MEDICAL_URGENCY,
            "A medical modifier preserves symptom urgency.",
            confidence=0.7,
            max_age_seconds=_LIVE,
        ),
        _requirement(
            CompactDimension.COGNITIVE_CONFIDENCE,
            "A medical modifier preserves decision-making capacity.",
            max_age_seconds=_LIVE,
        ),
    ),
    DecisionType.COMMUNICATION: (
        _requirement(
            CompactDimension.EMERGENCY_REACHABILITY,
            "A communication modifier preserves escalation reachability.",
            max_age_seconds=_LIVE,
        ),
    ),
}


class DecisionTypeClassifier:
    """Deterministic baseline; a model classifier may propose, never bypass validation."""

    _RULES: tuple[tuple[DecisionType, tuple[str, ...]], ...] = (
        (
            DecisionType.MEDICAL,
            (
                "受傷",
                "流血",
                "骨折",
                "失溫",
                "頭痛",
                "想吐",
                "喘",
                "medical",
                "injury",
            ),
        ),
        (
            DecisionType.RETREAT,
            (
                "撤退",
                "下撤",
                "折返",
                "回頭",
                "停止推進",
                "否決",
                "retreat",
                "turn back",
            ),
        ),
        (
            DecisionType.SUMMIT,
            (
                "攻頂",
                "登頂",
                "山頂",
                "主峰",
                "副峰",
                "前峰",
                "繼續上升",
                "summit",
            ),
        ),
        (
            DecisionType.PHOTOGRAPHY,
            (
                "拍照",
                "攝影",
                "拍攝",
                "錄影",
                "取景",
                "架腳架",
                "拍雲海",
                "拍一小段影片",
                "等光線",
                "觀察點",
                "找角度",
                "photo",
                "photography",
            ),
        ),
        (
            DecisionType.REST,
            (
                "休息",
                "停多久",
                "停十分鐘",
                "停10分鐘",
                "停二十分鐘",
                "停20分鐘",
                "停一下",
                "停下來",
                "短休",
                "吃午餐",
                "午餐",
                "吃東西",
                "補水",
                "脫外套",
                "整理裝備",
                "原地等候",
                "等隊友",
                "等全員",
                "等十分鐘",
                "停三分鐘",
                "rest",
                "break",
            ),
        ),
        (
            DecisionType.CAMP,
            (
                "紮營",
                "露營",
                "營地",
                "過夜",
                "天亮再走",
                "山屋",
                "臨時避風",
                "camp",
                "bivouac",
            ),
        ),
        (
            DecisionType.WATER,
            ("水量", "飲水", "取水", "水源", "water", "hydrate"),
        ),
        (
            DecisionType.COMMUNICATION,
            (
                "訊號",
                "通訊",
                "求救訊息",
                "隊伍",
                "隊友",
                "前隊",
                "後隊",
                "全員",
                "領隊",
                "專業人員",
                "lora",
                "lte",
                "衛星",
                "communication",
            ),
        ),
        (
            DecisionType.READINESS_PACE,
            (
                "腳程",
                "配速",
                "上坡速度",
                "下坡速度",
                "負重",
                "最慢者",
                "pace fit",
                "readiness",
            ),
        ),
        (
            DecisionType.HAZARD,
            (
                "危險",
                "風險",
                "崩壁",
                "落石",
                "碎石坡",
                "滑墜",
                "斷崖",
                "狹窄路段",
                "hazard",
            ),
        ),
        (
            DecisionType.WEATHER,
            (
                "天氣",
                "下雨",
                "大雨",
                "豪雨",
                "降雨",
                "雷雨",
                "雷暴",
                "風勢",
                "強風",
                "起霧",
                "迷霧",
                "能見度",
                "白牆",
                "weather",
                "rain",
            ),
        ),
        (
            DecisionType.NAVIGATION,
            (
                "偏離",
                "走錯",
                "岔路",
                "方向",
                "定位",
                "gps",
                "導航",
                "route alignment",
            ),
        ),
        (
            DecisionType.WILDLIFE,
            ("野生動物", "熊", "蛇", "蜂", "wildlife"),
        ),
        (
            DecisionType.HISTORY,
            ("歷史", "文化", "古道", "駐在所", "舊社", "history", "culture"),
        ),
        (
            DecisionType.ROUTE_PLANNING,
            (
                "行程",
                "路線",
                "幾天",
                "cp",
                "撤退點",
                "支線",
                "替代線",
                "改走",
                "改計畫",
                "原計畫",
                "不再成立",
                "change plan",
                "change_plan",
                "no go",
                "no_go",
                "延後出發",
                "route plan",
                "itinerary",
            ),
        ),
    )

    _CRITICALITY = {
        profile.decision_type: profile.criticality
        for profile in DECISION_PROFILES.values()
    }

    def classify(
        self,
        question: str,
        *,
        decision_hint: DecisionType | None = None,
    ) -> DecisionIntent:
        normalized = _normalize(question)
        matches = [
            decision_type
            for decision_type, terms in self._RULES
            if any(_matches_term(normalized, term) for term in terms)
        ]
        if decision_hint is not None:
            primary = decision_hint
            confidence = 0.9
            alternatives = tuple(
                item for item in dict.fromkeys(matches) if item != decision_hint
            )
        else:
            primary = matches[0] if matches else DecisionType.GENERAL
            confidence = 0.96 if matches else 0.45
            alternatives = tuple(dict.fromkeys(matches[1:]))
        return DecisionIntent(
            question=question.strip(),
            primary_type=primary,
            alternative_types=alternatives,
            confidence=confidence,
            criticality=self._CRITICALITY[primary],
            rationale=(
                f"Used validated decision hint {decision_hint.value}; matched question labels remain modifiers."
                if decision_hint is not None
                else f"Matched decision vocabulary for {primary.value}."
                if matches
                else "No domain-specific decision vocabulary matched; clarification is required."
            ),
        )


class DecisionProfileRegistry:
    def get(self, decision_type: DecisionType) -> DecisionCompactProfile:
        return DECISION_PROFILES[decision_type]

    def compose(self, intent: DecisionIntent) -> DecisionCompactProfile:
        base = self.get(intent.primary_type)
        requirements = list(base.requirements)
        known_dimensions = {requirement.dimension for requirement in base.requirements}
        for alternative in intent.alternative_types:
            for requirement in _MODIFIER_REQUIREMENTS.get(alternative, ()):
                if requirement.dimension not in known_dimensions:
                    requirements.append(requirement)
                    known_dimensions.add(requirement.dimension)
        suffix = (
            ""
            if not intent.alternative_types
            else "+" + "+".join(item.value for item in intent.alternative_types)
        )
        return base.model_copy(
            update={
                "profile_id": f"{base.profile_id}{suffix}",
                "requirements": tuple(requirements),
            }
        )


class ContextReductionEngine:
    """Build an inclusion-minimal context and a task-relative sufficiency proof."""

    def __init__(self, *, profiles: DecisionProfileRegistry | None = None) -> None:
        self._profiles = profiles or DecisionProfileRegistry()

    def reduce(
        self,
        *,
        intent: DecisionIntent,
        environment: EnvironmentalRepresentation,
        now: datetime | None = None,
    ) -> MinimalSufficientContext:
        profile = self._profiles.compose(intent)
        reference_time = _as_utc(now or datetime.now(UTC))
        by_dimension: dict[CompactDimension, list[CompactSignal]] = defaultdict(list)
        for signal in environment.all_signals():
            by_dimension[signal.dimension].append(signal)

        selected: dict[str, CompactSignal] = {}
        coverage: list[DimensionCoverage] = []
        needs: list[InformationNeed] = []
        missing: list[CompactDimension] = []
        stale: list[CompactDimension] = []
        low_confidence: list[CompactDimension] = []
        contradictory: list[CompactDimension] = []

        for requirement in profile.requirements:
            candidates = by_dimension.get(requirement.dimension, [])
            result = self._cover_requirement(
                requirement=requirement,
                candidates=candidates,
                now=reference_time,
            )
            coverage.append(result[0])
            for signal in result[1]:
                selected[signal.signal_id] = signal
            if result[2] is not None:
                need = result[2]
                needs.append(need)
                {
                    GapKind.MISSING: missing,
                    GapKind.STALE: stale,
                    GapKind.LOW_CONFIDENCE: low_confidence,
                    GapKind.CONTRADICTORY: contradictory,
                }[need.gap_kind].append(requirement.dimension)

        preserved_high_risk: list[str] = []
        for signal in environment.all_signals():
            if (
                signal.availability == SignalAvailability.AVAILABLE
                and signal.risk_upper_bound is not None
                and signal.risk_upper_bound >= profile.risk_preservation_threshold
            ):
                selected[signal.signal_id] = signal
                preserved_high_risk.append(signal.signal_id)

        covered_count = sum(item.status == "covered" for item in coverage)
        required_count = len(profile.requirements)
        ratio = covered_count / required_count if required_count else 1.0
        status = self._status(
            intent=intent,
            needs=needs,
            contradictory=contradictory,
            coverage_ratio=ratio,
            minimum_ratio=profile.minimum_coverage_ratio,
        )
        selected_signals = tuple(
            sorted(
                selected.values(),
                key=lambda item: (item.dimension.value, item.signal_id),
            )
        )
        selected_dimensions = {signal.dimension for signal in selected_signals}
        discarded_dimensions = tuple(
            sorted(
                {
                    signal.dimension
                    for signal in environment.all_signals()
                    if signal.dimension not in selected_dimensions
                },
                key=lambda item: item.value,
            )
        )
        source_refs = tuple(
            dict.fromkeys(
                source_ref
                for signal in selected_signals
                for source_ref in signal.source_refs
            )
        )
        counterfactual_required = tuple(
            item.requirement.dimension
            for item in coverage
            if item.status == "covered" and item.requirement.mandatory
        )
        certificate = SufficiencyCertificate(
            status=status,
            required_dimension_count=required_count,
            covered_dimension_count=covered_count,
            coverage_ratio=ratio,
            coverage=tuple(coverage),
            missing_dimensions=tuple(missing),
            stale_dimensions=tuple(stale),
            low_confidence_dimensions=tuple(low_confidence),
            contradictory_dimensions=tuple(contradictory),
            counterfactual_required_dimensions=counterfactual_required,
            preserved_high_risk_signal_ids=tuple(sorted(set(preserved_high_risk))),
            source_refs=source_refs,
            explanation=_certificate_explanation(status, needs),
        )
        context_key = "|".join(
            (
                intent.question,
                environment.representation_id,
                profile.profile_id,
                reference_time.isoformat(),
            )
        )
        return MinimalSufficientContext(
            context_id=f"mser-{hashlib.sha256(context_key.encode()).hexdigest()[:16]}",
            intent=intent,
            profile_id=profile.profile_id,
            selected_signals=selected_signals,
            discarded_dimensions=discarded_dimensions,
            information_needs=tuple(needs),
            certificate=certificate,
        )

    def _cover_requirement(
        self,
        *,
        requirement: DimensionRequirement,
        candidates: list[CompactSignal],
        now: datetime,
    ) -> tuple[DimensionCoverage, tuple[CompactSignal, ...], InformationNeed | None]:
        if not candidates:
            return self._gap(requirement, GapKind.MISSING, "No signal was projected.")

        candidate_ids = {candidate.signal_id for candidate in candidates}
        conflicting_ids: set[str] = set()
        for candidate in candidates:
            referenced = candidate_ids.intersection(candidate.conflicts_with)
            if referenced:
                conflicting_ids.add(candidate.signal_id)
                conflicting_ids.update(referenced)
        conflicting = tuple(
            candidate
            for candidate in candidates
            if candidate.signal_id in conflicting_ids
        )
        if conflicting and requirement.preserve_conflicts:
            return self._gap(
                requirement,
                GapKind.CONTRADICTORY,
                "Conflicting evidence must be resolved before compression.",
                selected=conflicting,
            )

        usable = [
            candidate
            for candidate in candidates
            if candidate.availability == SignalAvailability.AVAILABLE
        ]
        if not usable:
            explicit_stale = any(
                candidate.availability == SignalAvailability.STALE
                for candidate in candidates
            )
            kind = GapKind.STALE if explicit_stale else GapKind.MISSING
            return self._gap(
                requirement,
                kind,
                "Projected signals are stale or unavailable.",
            )

        fresh = [
            candidate
            for candidate in usable
            if not _is_stale(candidate, requirement=requirement, now=now)
        ]
        if not fresh:
            return self._gap(
                requirement,
                GapKind.STALE,
                "All available signals exceed the decision profile freshness limit.",
            )

        confident = [
            candidate
            for candidate in fresh
            if candidate.confidence >= requirement.minimum_confidence
        ]
        if not confident:
            best = max(fresh, key=_signal_quality)
            return self._gap(
                requirement,
                GapKind.LOW_CONFIDENCE,
                (
                    f"Best confidence {best.confidence:.2f} is below "
                    f"{requirement.minimum_confidence:.2f}."
                ),
                selected=(best,),
            )

        best = max(confident, key=_signal_quality)
        coverage = DimensionCoverage(
            requirement=requirement,
            selected_signal_ids=(best.signal_id,),
            status="covered",
            explanation="Highest-quality fresh signal covers this proof obligation.",
        )
        return coverage, (best,), None

    @staticmethod
    def _gap(
        requirement: DimensionRequirement,
        kind: GapKind,
        explanation: str,
        *,
        selected: tuple[CompactSignal, ...] = (),
    ) -> tuple[DimensionCoverage, tuple[CompactSignal, ...], InformationNeed]:
        coverage = DimensionCoverage(
            requirement=requirement,
            selected_signal_ids=tuple(signal.signal_id for signal in selected),
            status=kind,
            explanation=explanation,
        )
        need = InformationNeed(
            dimension=requirement.dimension,
            gap_kind=kind,
            reason=explanation,
            minimum_confidence=requirement.minimum_confidence,
            max_age_seconds=requirement.max_age_seconds,
            suggested_capabilities=_capability_hints(requirement.dimension),
        )
        return coverage, selected, need

    @staticmethod
    def _status(
        *,
        intent: DecisionIntent,
        needs: list[InformationNeed],
        contradictory: list[CompactDimension],
        coverage_ratio: float,
        minimum_ratio: float,
    ) -> SufficiencyStatus:
        if intent.confidence < 0.5:
            return SufficiencyStatus.AMBIGUOUS_DECISION
        if contradictory:
            return SufficiencyStatus.CONTRADICTORY
        if needs or coverage_ratio < minimum_ratio:
            return SufficiencyStatus.INSUFFICIENT
        return SufficiencyStatus.SUFFICIENT


class MinimalToolPlanner:
    """Greedy weighted set cover over exact MSER evidence gaps."""

    def plan(
        self,
        *,
        context: MinimalSufficientContext,
        capabilities: Iterable[ToolCapability],
        max_tool_calls: int = 10,
    ) -> MinimalToolPlan:
        if max_tool_calls < 10:
            raise ValueError("MSER construction budget cannot be lower than 10")
        uncovered = {need.dimension for need in context.information_needs}
        available = [
            capability
            for capability in capabilities
            if capability.availability == "available" and capability.read_only
        ]
        selected: list[PlannedCompactTool] = []
        used_tools: set[str] = set()

        while uncovered and len(selected) < max_tool_calls:
            ranked: list[
                tuple[
                    int, float, float, int, str, ToolCapability, set[CompactDimension]
                ]
            ] = []
            for capability in available:
                if capability.tool_id in used_tools:
                    continue
                new_coverage = uncovered.intersection(capability.produces_dimensions)
                if not new_coverage:
                    continue
                ranked.append(
                    (
                        -len(new_coverage),
                        -capability.expected_confidence,
                        capability.estimated_cost,
                        capability.expected_latency_ms,
                        capability.tool_id,
                        capability,
                        new_coverage,
                    )
                )
            if not ranked:
                break
            *_, capability, new_coverage = min(ranked)
            dimensions = tuple(sorted(new_coverage, key=lambda item: item.value))
            selected.append(
                PlannedCompactTool(
                    tool_id=capability.tool_id,
                    fills_dimensions=dimensions,
                    reason=(
                        "Covers unresolved MSER proof obligations: "
                        + ", ".join(item.value for item in dimensions)
                    ),
                )
            )
            used_tools.add(capability.tool_id)
            uncovered.difference_update(new_coverage)

        unresolved = tuple(sorted(uncovered, key=lambda item: item.value))
        return MinimalToolPlan(
            selected_tools=tuple(selected),
            uncovered_dimensions=unresolved,
            coverage_complete=not unresolved,
            objective=(
                "Minimize read-only tool calls subject to complete coverage of "
                "all unresolved MSER sufficiency obligations."
            ),
            max_tool_calls=max_tool_calls,
        )


class MemoryReductionEngine:
    """Retain consequential events while keeping raw streams outside model memory."""

    def reduce(
        self,
        *,
        events: Iterable[MemoryEvent],
        decision_type: DecisionType,
        relevance_threshold: float = 0.55,
        max_noncritical_events: int = 64,
    ) -> ReducedMemory:
        all_events = tuple(events)
        critical: list[MemoryEvent] = []
        noncritical_by_cluster: dict[str, MemoryEvent] = {}
        for event in all_events:
            score = _memory_score(event, decision_type)
            if (
                event.decision_point
                or event.anomaly
                or event.detour
                or event.stop
                or event.hazard_severity >= 0.6
            ):
                critical.append(event)
                continue
            if score < relevance_threshold:
                continue
            cluster_key = event.cluster_key or event.event_id
            current = noncritical_by_cluster.get(cluster_key)
            if current is None or _memory_score(current, decision_type) < score:
                noncritical_by_cluster[cluster_key] = event

        noncritical = sorted(
            noncritical_by_cluster.values(),
            key=lambda item: (_memory_score(item, decision_type), item.observed_at),
            reverse=True,
        )[:max_noncritical_events]
        selected_by_id = {event.event_id: event for event in (*critical, *noncritical)}
        selected = tuple(
            sorted(selected_by_id.values(), key=lambda item: item.observed_at)
        )
        raw_refs = tuple(
            dict.fromkeys(
                source_ref for event in all_events for source_ref in event.source_refs
            )
        )
        return ReducedMemory(
            selected_events=selected,
            omitted_event_count=max(0, len(all_events) - len(selected)),
            raw_event_refs_preserved=raw_refs,
            reduction_rule=(
                "Always retain decision points, hazards, detours, and anomalies; "
                "deduplicate lower-impact events by cluster and decision relevance."
            ),
        )


class KnowledgeReductionEngine:
    """Select an inclusion-minimal authoritative set that covers required dimensions."""

    def reduce(
        self,
        *,
        candidates: Iterable[KnowledgeCandidate],
        decision_type: DecisionType,
        required_dimensions: Iterable[CompactDimension],
        max_candidates: int = 32,
    ) -> ReducedKnowledge:
        required = set(required_dimensions)
        selected: list[KnowledgeCandidate] = []
        uncovered = set(required)
        pool = [
            candidate
            for candidate in candidates
            if candidate.source_refs
            and (
                not candidate.decision_types
                or decision_type in candidate.decision_types
            )
        ]

        while uncovered and len(selected) < max_candidates:
            ranked: list[
                tuple[int, float, str, KnowledgeCandidate, set[CompactDimension]]
            ] = []
            for candidate in pool:
                if candidate in selected:
                    continue
                coverage = uncovered.intersection(candidate.supports_dimensions)
                if not coverage:
                    continue
                ranked.append(
                    (
                        -len(coverage),
                        -_knowledge_quality(candidate),
                        candidate.knowledge_id,
                        candidate,
                        coverage,
                    )
                )
            if not ranked:
                break
            *_, candidate, coverage = min(ranked)
            selected.append(candidate)
            uncovered.difference_update(coverage)

        selected = _prune_redundant_knowledge(selected, required)
        covered = {
            dimension
            for candidate in selected
            for dimension in candidate.supports_dimensions
            if dimension in required
        }
        return ReducedKnowledge(
            selected_candidates=tuple(selected),
            covered_dimensions=tuple(sorted(covered, key=lambda item: item.value)),
            uncovered_dimensions=tuple(
                sorted(required - covered, key=lambda item: item.value)
            ),
            source_refs_verified=all(candidate.source_refs for candidate in selected),
            reduction_rule=(
                "Filter by decision relevance and provenance, apply weighted set "
                "cover, then remove any candidate whose evidence coverage is redundant."
            ),
        )


class MSEREngine:
    """Thin orchestration boundary placed before bounded tool execution."""

    def __init__(
        self,
        *,
        classifier: DecisionTypeClassifier | None = None,
        reducer: ContextReductionEngine | None = None,
        planner: MinimalToolPlanner | None = None,
    ) -> None:
        self._classifier = classifier or DecisionTypeClassifier()
        self._reducer = reducer or ContextReductionEngine()
        self._planner = planner or MinimalToolPlanner()

    def prepare(
        self,
        *,
        question: str,
        environment: EnvironmentalRepresentation,
        capabilities: Iterable[ToolCapability] = (),
        decision_hint: DecisionType | None = None,
        now: datetime | None = None,
    ) -> MSERDecisionPacket:
        intent = self._classifier.classify(
            question,
            decision_hint=decision_hint,
        )
        context = self._reducer.reduce(
            intent=intent,
            environment=environment,
            now=now,
        )
        tool_plan = self._planner.plan(
            context=context,
            capabilities=capabilities,
        )
        status = context.certificate.status
        if status == SufficiencyStatus.SUFFICIENT:
            next_stage = MSERStage.READY_TO_REASON
        elif status == SufficiencyStatus.CONTRADICTORY:
            next_stage = MSERStage.CONTRADICTORY_STATE
        elif status == SufficiencyStatus.AMBIGUOUS_DECISION:
            next_stage = MSERStage.AMBIGUOUS_DECISION
        elif tool_plan.selected_tools:
            next_stage = MSERStage.TOOL_PLAN_READY
        else:
            next_stage = MSERStage.INSUFFICIENT_EVIDENCE
        return MSERDecisionPacket(
            intent=intent,
            compact_context=context,
            tool_plan=tool_plan,
            next_stage=next_stage,
        )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _matches_term(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9][a-z0-9 _/-]*", term):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",
                text,
            )
        )
    return term in text


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_stale(
    signal: CompactSignal,
    *,
    requirement: DimensionRequirement,
    now: datetime,
) -> bool:
    if signal.availability == SignalAvailability.STALE:
        return True
    if signal.valid_until is not None:
        return _as_utc(signal.valid_until) < now
    if requirement.max_age_seconds is None:
        return False
    if signal.observed_at is None:
        return True
    age_seconds = (now - _as_utc(signal.observed_at)).total_seconds()
    return age_seconds > requirement.max_age_seconds


def _signal_quality(signal: CompactSignal) -> tuple[float, float]:
    observed_at = _as_utc(signal.observed_at).timestamp() if signal.observed_at else 0.0
    return signal.confidence, observed_at


def _capability_hints(dimension: CompactDimension) -> tuple[str, ...]:
    domain = dimension.value.split(".", maxsplit=1)[0]
    hints = {
        "terrain": ("scout.context.total_info", "scout.terrain.compact_state"),
        "weather": ("scout.context.total_info", "scout.weather.compact_state"),
        "human": ("scout.context.total_info", "scout.human.compact_state"),
        "communication": (
            "scout.context.total_info",
            "scout.communication.compact_state",
        ),
        "navigation": (
            "scout.context.total_info",
            "scout.navigation.compact_state",
        ),
        "operation": ("scout.context.total_info", "scout.mission.compact_state"),
        "knowledge": ("scout.context.total_info", "scout.knowledge.find"),
    }
    return hints[domain]


def _certificate_explanation(
    status: SufficiencyStatus,
    needs: list[InformationNeed],
) -> str:
    if status == SufficiencyStatus.SUFFICIENT:
        return (
            "Every mandatory decision dimension has fresh, confident, sourced "
            "coverage; removing any counterfactual-required dimension breaks coverage."
        )
    if status == SufficiencyStatus.AMBIGUOUS_DECISION:
        return (
            "Decision type confidence is too low; clarify the requested decision first."
        )
    if status == SufficiencyStatus.CONTRADICTORY:
        return (
            "Conflicting evidence was preserved and must be resolved before reasoning."
        )
    dimensions = ", ".join(need.dimension.value for need in needs)
    return f"MSER is not sufficient yet; unresolved proof obligations: {dimensions}."


def _memory_score(event: MemoryEvent, decision_type: DecisionType) -> float:
    relevance = 1.0 if decision_type in event.decision_types else 0.0
    flags = 1.0 if (event.decision_point or event.detour or event.anomaly) else 0.0
    return max(
        event.importance,
        event.surprise,
        event.hazard_severity,
        relevance,
        flags,
    )


def _knowledge_quality(candidate: KnowledgeCandidate) -> float:
    return (
        0.35 * candidate.authority
        + 0.25 * candidate.freshness
        + 0.2 * candidate.spatial_relevance
        + 0.2 * candidate.temporal_relevance
    )


def _prune_redundant_knowledge(
    selected: list[KnowledgeCandidate],
    required: set[CompactDimension],
) -> list[KnowledgeCandidate]:
    result = list(selected)
    for candidate in reversed(selected):
        remaining = [
            item for item in result if item.knowledge_id != candidate.knowledge_id
        ]
        coverage = {
            dimension
            for item in remaining
            for dimension in item.supports_dimensions
            if dimension in required
        }
        if required.issubset(coverage):
            result = remaining
    return result


__all__ = [
    "ContextReductionEngine",
    "DECISION_PROFILES",
    "DecisionProfileRegistry",
    "DecisionTypeClassifier",
    "KnowledgeReductionEngine",
    "MSEREngine",
    "MemoryReductionEngine",
    "MinimalToolPlanner",
]
