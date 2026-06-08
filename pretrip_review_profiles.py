from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_CHILAI_PROJECT_REF = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)


class StrictProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewProfileId(StrEnum):
    QUICK = "quick_review.v0"
    GUIDED = "guided_review.v0"
    EXPEDITION = "expedition_review.v0"


class ReviewFrictionLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RouteClassId(StrEnum):
    SIMPLE_SINGLE_DAY = "simple_single_day"
    LONG_SINGLE_DAY = "long_single_day"
    DEEP_MOUNTAIN_OUT_AND_BACK = "deep_mountain_out_and_back"
    MULTI_DAY_OUT_AND_BACK = "multi_day_out_and_back"
    TRAVERSE = "traverse"
    TECHNICAL_OR_HIGH_EXPOSURE = "technical_or_high_exposure"
    FIELD_EXPLORATION_UNKNOWN_ROUTE = "field_exploration_unknown_route"


class FieldVerifyBlockPolicy(StrEnum):
    CRITICAL_ONLY = "critical_only"
    BROAD_CRITICAL_SET = "broad_critical_set"


class RouteNoteReviewPolicy(StrEnum):
    PARTIAL_ALLOWED = "partial_allowed"
    WARNING_ONLY = "warning_only"
    WARNING_AND_CRITICAL = "warning_and_critical"


class SecondReviewPolicy(StrEnum):
    NONE_BY_DEFAULT = "none_by_default"
    CONFIGURABLE = "configurable"
    CONFIGURABLE_FOR_CRITICAL = "configurable_for_critical"


class HardBlockerPolicyRef(StrEnum):
    BASELINE = "baseline_hard_blockers.v0"
    BASELINE_ROUTE = "baseline_plus_route_hard_blockers.v0"
    BASELINE_EXPEDITION = "baseline_plus_expedition_hard_blockers.v0"


class HardBlockerId(StrEnum):
    WEATHER_NO_GO = "weather_no_go"
    NO_VALID_ROUTE = "no_valid_route"
    UNVERIFIED_WILD_ROUTE_WITHOUT_PUBLIC_GPX = (
        "unverified_wild_route_without_public_gpx"
    )
    NO_RETREAT_POLICY_FOR_REQUIRED_ROUTE = "no_retreat_policy_for_required_route"
    NO_REVIEWED_PACKAGE = "no_reviewed_package"
    NO_FINAL_MISSION_GRAPH = "no_final_mission_graph"
    CORRUPT_PACKAGE_OR_GRAPH_HASH = "corrupt_package_or_graph_hash"
    MISSING_RUNTIME_TARGET = "missing_runtime_target"


class ProfileBoundary(StrictProfileModel):
    planning_metadata_only: Literal[True] = True
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    reviewed_package_activates_runtime: Literal[False] = False
    runtime_handoff_required: Literal[True] = True
    notes: list[str] = Field(default_factory=list)


class PlanningReviewProfile(StrictProfileModel):
    profile_id: ReviewProfileId
    display_name: str
    display_name_zh: str
    description_zh: str
    intended_trip_classes: list[RouteClassId]
    friction_level: ReviewFrictionLevel
    allows_bulk_accept: bool
    bulk_accept_policy: str
    bulk_accept_policy_zh: str
    requires_second_review: bool
    route_note_review_required: RouteNoteReviewPolicy
    retreat_policy_required: bool
    field_verify_blocks_departure: FieldVerifyBlockPolicy
    runtime_handoff_second_confirm: bool
    second_review_requirement_policy: SecondReviewPolicy
    professional_review_triggers: list[str] = Field(default_factory=list)
    professional_review_triggers_zh: list[str] = Field(default_factory=list)
    blocker_override_requires_reason: bool
    hard_blocker_override_allowed: Literal[False] = False
    hard_blocker_policy_ref: HardBlockerPolicyRef
    stores_package_hash: Literal[True] = True
    stores_handoff_manifest: Literal[True] = True
    boundary: ProfileBoundary = Field(default_factory=ProfileBoundary)


class HardBlockerPolicy(StrictProfileModel):
    blocker_id: HardBlockerId
    label: str
    label_zh: str
    explanation: str
    explanation_zh: str
    trigger_criteria: list[str]
    allowed_resolution_path: str
    allowed_resolution_path_zh: str
    profile_dependent: bool
    override_allowed: Literal[False] = False


class HardBlockerCatalog(StrictProfileModel):
    catalog_id: HardBlockerPolicyRef
    display_name: str
    display_name_zh: str
    blockers: list[HardBlockerPolicy]

    @model_validator(mode="after")
    def require_non_overridable_baseline(self) -> "HardBlockerCatalog":
        if any(blocker.override_allowed for blocker in self.blockers):
            raise ValueError("hard blockers must not be overrideable")
        return self


class RouteClassDefinition(StrictProfileModel):
    class_id: RouteClassId
    label: str
    label_zh: str
    explanation_zh: str


class RouteReviewContext(StrictProfileModel):
    route_name: str
    distance_m: float = Field(ge=0.0)
    route_days: int = Field(default=1, ge=1)
    elevation_max_m: float | None = None
    has_valid_route: bool = True
    route_evidence_trusted: bool = True
    has_public_or_reviewed_gpx: bool = True
    is_deep_mountain: bool = False
    is_traverse: bool = False
    is_wild_or_offtrail: bool = False
    is_technical_or_high_exposure: bool = False
    retreat_policy_accepted: bool = False
    retreat_policy_type: str | None = None
    retreat_difficulty: Literal["clear", "moderate", "difficult", "unclear"] = "unclear"
    weather_no_go: bool = False
    expected_arrival_after_last_light: bool = False
    water_uncertainty_affects_safety: bool = False
    route_corridor_has_poi: bool = True
    communication_uncertainty_affects_remote_checkin: bool = False
    high_risk_route_note_terms: list[str] = Field(default_factory=list)
    unresolved_field_verification_categories: list[str] = Field(default_factory=list)
    critical_provenance_gaps: list[str] = Field(default_factory=list)
    reviewed_package_exists: bool = True
    final_mission_graph_exists: bool = False
    package_or_graph_hash_valid: bool = True
    runtime_target_present: bool = False
    user_explicitly_selected_lower_friction: bool = False


class RouteClassification(StrictProfileModel):
    primary_class: RouteClassId
    route_classes: list[RouteClassId]
    explanation: str
    explanation_zh: str


class EscalationRule(StrictProfileModel):
    rule_id: str
    trigger_field: str
    target_profile_id: ReviewProfileId
    label: str
    label_zh: str
    explanation_zh: str


class ProfileSelectionResult(StrictProfileModel):
    requested_profile_id: ReviewProfileId
    selected_profile_id: ReviewProfileId
    required_profile_id: ReviewProfileId
    recommended_profile_id: ReviewProfileId
    route_classification: RouteClassification
    escalation_reasons: list[EscalationRule] = Field(default_factory=list)
    hard_blockers: list[HardBlockerPolicy] = Field(default_factory=list)
    quick_review_allowed: bool
    explanation_zh: str
    boundary: ProfileBoundary = Field(default_factory=ProfileBoundary)


PROFILE_ORDER: dict[ReviewProfileId, int] = {
    ReviewProfileId.QUICK: 0,
    ReviewProfileId.GUIDED: 1,
    ReviewProfileId.EXPEDITION: 2,
}


ROUTE_CLASS_DEFINITIONS: tuple[RouteClassDefinition, ...] = (
    RouteClassDefinition(
        class_id=RouteClassId.SIMPLE_SINGLE_DAY,
        label="Simple single day",
        label_zh="簡單單日",
        explanation_zh="單日、距離短、暴露低，適合低摩擦審核。",
    ),
    RouteClassDefinition(
        class_id=RouteClassId.LONG_SINGLE_DAY,
        label="Long single day",
        label_zh="長日單攻",
        explanation_zh="雖然是單日，但距離、時間或體力風險足以要求更清楚的審核。",
    ),
    RouteClassDefinition(
        class_id=RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK,
        label="Deep mountain out-and-back",
        label_zh="深山原路折返",
        explanation_zh="深山路線且主要撤退策略是原路折返；可以低摩擦，但不能略過 hard blocker。",
    ),
    RouteClassDefinition(
        class_id=RouteClassId.MULTI_DAY_OUT_AND_BACK,
        label="Multi-day out-and-back",
        label_zh="多日折返",
        explanation_zh="多日行程需要更保守的撤退、資源與交接審核。",
    ),
    RouteClassDefinition(
        class_id=RouteClassId.TRAVERSE,
        label="Traverse",
        label_zh="縱走",
        explanation_zh="非原路折返，撤退與接駁風險較高。",
    ),
    RouteClassDefinition(
        class_id=RouteClassId.TECHNICAL_OR_HIGH_EXPOSURE,
        label="Technical or high exposure",
        label_zh="技術或高暴露風險",
        explanation_zh="技術地形、暴露路段或高後果風險需要專家模式。",
    ),
    RouteClassDefinition(
        class_id=RouteClassId.FIELD_EXPLORATION_UNKNOWN_ROUTE,
        label="Field exploration or unknown route",
        label_zh="探勘或未知路線",
        explanation_zh="缺少可信路線證據時，不能用快捷模式降低審核門檻。",
    ),
)


PLANNING_REVIEW_PROFILES: tuple[PlanningReviewProfile, ...] = (
    PlanningReviewProfile(
        profile_id=ReviewProfileId.QUICK,
        display_name="Quick Review",
        display_name_zh="快捷模式",
        description_zh="低摩擦審核模式，不是低安全模式；仍保留 route、retreat、hard blocker 與 handoff 不可略過條件。",
        intended_trip_classes=[
            RouteClassId.SIMPLE_SINGLE_DAY,
            RouteClassId.LONG_SINGLE_DAY,
            RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK,
        ],
        friction_level=ReviewFrictionLevel.LOW,
        allows_bulk_accept=True,
        bulk_accept_policy="low_risk_ai_candidates_only",
        bulk_accept_policy_zh="僅允許低風險 AI 候選批次接受。",
        requires_second_review=False,
        route_note_review_required=RouteNoteReviewPolicy.PARTIAL_ALLOWED,
        retreat_policy_required=True,
        field_verify_blocks_departure=FieldVerifyBlockPolicy.CRITICAL_ONLY,
        runtime_handoff_second_confirm=False,
        second_review_requirement_policy=SecondReviewPolicy.NONE_BY_DEFAULT,
        blocker_override_requires_reason=True,
        hard_blocker_policy_ref=HardBlockerPolicyRef.BASELINE,
        boundary=ProfileBoundary(
            notes=[
                "Quick Review reduces review friction only; it does not reduce safety invariants.",
            ]
        ),
    ),
    PlanningReviewProfile(
        profile_id=ReviewProfileId.GUIDED,
        display_name="Guided Review",
        display_name_zh="標準模式",
        description_zh="一般登山計畫預設模式，要求 critical route、retreat、ETA、daylight 與資源項目完成審核。",
        intended_trip_classes=[
            RouteClassId.LONG_SINGLE_DAY,
            RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK,
            RouteClassId.SIMPLE_SINGLE_DAY,
        ],
        friction_level=ReviewFrictionLevel.MEDIUM,
        allows_bulk_accept=True,
        bulk_accept_policy="low_risk_repeated_candidates_only",
        bulk_accept_policy_zh="僅重複且低風險候選可批次接受。",
        requires_second_review=False,
        route_note_review_required=RouteNoteReviewPolicy.WARNING_ONLY,
        retreat_policy_required=True,
        field_verify_blocks_departure=FieldVerifyBlockPolicy.CRITICAL_ONLY,
        runtime_handoff_second_confirm=False,
        second_review_requirement_policy=SecondReviewPolicy.CONFIGURABLE,
        professional_review_triggers=["health", "technical"],
        professional_review_triggers_zh=["健康限制", "技術地形"],
        blocker_override_requires_reason=True,
        hard_blocker_policy_ref=HardBlockerPolicyRef.BASELINE_ROUTE,
        boundary=ProfileBoundary(
            notes=[
                "Guided Review still produces planning metadata only and requires explicit runtime handoff.",
            ]
        ),
    ),
    PlanningReviewProfile(
        profile_id=ReviewProfileId.EXPEDITION,
        display_name="Expedition Review",
        display_name_zh="專家模式",
        description_zh="多日、縱走、深山困難撤退或高後果路線使用；critical 候選必須人工審核並保留 hash-linked 交接紀錄。",
        intended_trip_classes=[
            RouteClassId.MULTI_DAY_OUT_AND_BACK,
            RouteClassId.TRAVERSE,
            RouteClassId.TECHNICAL_OR_HIGH_EXPOSURE,
            RouteClassId.FIELD_EXPLORATION_UNKNOWN_ROUTE,
            RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK,
        ],
        friction_level=ReviewFrictionLevel.HIGH,
        allows_bulk_accept=False,
        bulk_accept_policy="no_bulk_accept_for_critical_candidates",
        bulk_accept_policy_zh="critical 候選不得批次接受。",
        requires_second_review=True,
        route_note_review_required=RouteNoteReviewPolicy.WARNING_AND_CRITICAL,
        retreat_policy_required=True,
        field_verify_blocks_departure=FieldVerifyBlockPolicy.BROAD_CRITICAL_SET,
        runtime_handoff_second_confirm=True,
        second_review_requirement_policy=SecondReviewPolicy.CONFIGURABLE_FOR_CRITICAL,
        professional_review_triggers=["health", "technical", "expedition"],
        professional_review_triggers_zh=["健康限制", "技術地形", "遠征或長程路線"],
        blocker_override_requires_reason=True,
        hard_blocker_policy_ref=HardBlockerPolicyRef.BASELINE_EXPEDITION,
        boundary=ProfileBoundary(
            notes=[
                "Expedition Review requires high-friction handoff confirmation but still does not mutate runtime.",
            ]
        ),
    ),
)


BASELINE_HARD_BLOCKER_CATALOG = HardBlockerCatalog(
    catalog_id=HardBlockerPolicyRef.BASELINE,
    display_name="Baseline hard blockers",
    display_name_zh="基準不可覆寫阻擋項目",
    blockers=[
        HardBlockerPolicy(
            blocker_id=HardBlockerId.WEATHER_NO_GO,
            label="Weather no-go",
            label_zh="天氣不允許",
            explanation="Weather policy marks the route unsafe to start.",
            explanation_zh="天氣規則判定此路線不適合出發，例如颱風、豪雨、雷擊或官方封閉。",
            trigger_criteria=["weather_no_go is true"],
            allowed_resolution_path="Wait for conditions to clear or select another route/date.",
            allowed_resolution_path_zh="等待天候改善，或改選路線/日期；不能以 override 略過。",
            profile_dependent=False,
        ),
        HardBlockerPolicy(
            blocker_id=HardBlockerId.NO_VALID_ROUTE,
            label="No valid route",
            label_zh="無有效路線",
            explanation="Route artifact is missing or cannot validate.",
            explanation_zh="缺少可驗證路線，或路線 artifact 驗證失敗。",
            trigger_criteria=["has_valid_route is false"],
            allowed_resolution_path="Provide and validate a route artifact.",
            allowed_resolution_path_zh="補上並驗證路線 artifact。",
            profile_dependent=False,
        ),
        HardBlockerPolicy(
            blocker_id=HardBlockerId.UNVERIFIED_WILD_ROUTE_WITHOUT_PUBLIC_GPX,
            label="Unverified wild route without public GPX",
            label_zh="無公開 GPX 或可信路線證據的野路",
            explanation="Wild or off-trail route lacks public, trusted, downloaded, or manually reviewed route evidence.",
            explanation_zh="探勘或離線野路缺少公開、可信、已下載或人工審核過的 GPX/路線證據。",
            trigger_criteria=[
                "is_wild_or_offtrail is true",
                "has_public_or_reviewed_gpx is false",
            ],
            allowed_resolution_path="Add trusted route evidence or manually review route evidence.",
            allowed_resolution_path_zh="加入可信路線證據，或完成路線人工審核。",
            profile_dependent=True,
        ),
        HardBlockerPolicy(
            blocker_id=HardBlockerId.NO_RETREAT_POLICY_FOR_REQUIRED_ROUTE,
            label="No retreat policy for required route",
            label_zh="必要撤退策略缺失",
            explanation="Deep mountain, traverse, or high-exposure route lacks an accepted retreat policy.",
            explanation_zh="深山、縱走或高暴露路線缺少已接受的撤退策略。",
            trigger_criteria=[
                "route requires retreat policy",
                "retreat_policy_accepted is false",
            ],
            allowed_resolution_path="Review and accept a retreat or alternate-route policy.",
            allowed_resolution_path_zh="審核並接受撤退或替代路線策略。",
            profile_dependent=True,
        ),
        HardBlockerPolicy(
            blocker_id=HardBlockerId.NO_REVIEWED_PACKAGE,
            label="No reviewed package",
            label_zh="無已審核規劃包",
            explanation="Departure is requested before package review.",
            explanation_zh="尚未形成已審核規劃包就要求出發評估。",
            trigger_criteria=["reviewed_package_exists is false"],
            allowed_resolution_path="Complete package review first.",
            allowed_resolution_path_zh="先完成規劃包審核。",
            profile_dependent=False,
        ),
        HardBlockerPolicy(
            blocker_id=HardBlockerId.NO_FINAL_MISSION_GRAPH,
            label="No final MissionGraph",
            label_zh="無最終任務圖",
            explanation="Runtime handoff is requested before Final MissionGraph exists.",
            explanation_zh="尚未產生 Final MissionGraph 就要求 runtime 交接。",
            trigger_criteria=["final_mission_graph_exists is false when handoff is requested"],
            allowed_resolution_path="Generate and validate Final MissionGraph after departure approval.",
            allowed_resolution_path_zh="出發關卡通過後產生並驗證 Final MissionGraph。",
            profile_dependent=False,
        ),
        HardBlockerPolicy(
            blocker_id=HardBlockerId.CORRUPT_PACKAGE_OR_GRAPH_HASH,
            label="Corrupt package or graph hash",
            label_zh="package 或 MissionGraph hash 不一致",
            explanation="Handoff artifact integrity cannot be verified.",
            explanation_zh="交接 artifact 完整性無法驗證。",
            trigger_criteria=["package_or_graph_hash_valid is false"],
            allowed_resolution_path="Regenerate or reverify the package and MissionGraph hashes.",
            allowed_resolution_path_zh="重新產生或重新驗證 package 與 MissionGraph hash。",
            profile_dependent=False,
        ),
        HardBlockerPolicy(
            blocker_id=HardBlockerId.MISSING_RUNTIME_TARGET,
            label="Missing runtime target",
            label_zh="缺少 runtime 目標",
            explanation="Handoff target is not specified or cannot be validated.",
            explanation_zh="未指定或無法驗證 runtime 交接目標。",
            trigger_criteria=["runtime_target_present is false when handoff is requested"],
            allowed_resolution_path="Specify and validate the runtime target.",
            allowed_resolution_path_zh="指定並驗證 runtime 目標。",
            profile_dependent=False,
        ),
    ],
)


ESCALATION_RULES: tuple[EscalationRule, ...] = (
    EscalationRule(
        rule_id="multi_day_itinerary",
        trigger_field="route_days",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="Multi-day itinerary",
        label_zh="多日行程",
        explanation_zh="多日行程需要專家模式處理資源、撤退與交接風險。",
    ),
    EscalationRule(
        rule_id="traverse_route",
        trigger_field="is_traverse",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="Traverse route",
        label_zh="縱走路線",
        explanation_zh="縱走不是單純原路折返，撤退策略必須更嚴格。",
    ),
    EscalationRule(
        rule_id="deep_mountain_unclear_retreat",
        trigger_field="retreat_difficulty",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="Deep mountain with unclear retreat",
        label_zh="深山撤退不明",
        explanation_zh="深山且撤退不清楚時不能維持快捷模式。",
    ),
    EscalationRule(
        rule_id="wild_route_missing_trusted_evidence",
        trigger_field="has_public_or_reviewed_gpx",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="Wild route missing trusted evidence",
        label_zh="野路缺少可信證據",
        explanation_zh="野路缺少公開或可信 GPX/路線證據時必須升級。",
    ),
    EscalationRule(
        rule_id="weather_policy_no_go",
        trigger_field="weather_no_go",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="Weather policy no-go",
        label_zh="天氣不允許",
        explanation_zh="天氣 no-go 是 hard blocker，不能用較低 profile 略過。",
    ),
    EscalationRule(
        rule_id="arrival_near_or_after_last_light",
        trigger_field="expected_arrival_after_last_light",
        target_profile_id=ReviewProfileId.GUIDED,
        label="Arrival near or after last light",
        label_zh="抵達時間接近或晚於天黑",
        explanation_zh="日照餘裕不足時至少需要標準模式審核 ETA 與撤退門檻。",
    ),
    EscalationRule(
        rule_id="no_accepted_retreat_policy",
        trigger_field="retreat_policy_accepted",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="No accepted retreat policy",
        label_zh="缺少已接受撤退策略",
        explanation_zh="必要撤退策略缺失時不能降低審核層級。",
    ),
    EscalationRule(
        rule_id="water_uncertainty_long_or_overnight",
        trigger_field="water_uncertainty_affects_safety",
        target_profile_id=ReviewProfileId.GUIDED,
        label="Water uncertainty affects safety",
        label_zh="水源不確定影響安全",
        explanation_zh="長日或過夜行程的水源不確定至少需要標準模式。",
    ),
    EscalationRule(
        rule_id="route_corridor_no_poi",
        trigger_field="route_corridor_has_poi",
        target_profile_id=ReviewProfileId.GUIDED,
        label="Route corridor has no POI",
        label_zh="路線走廊缺少 POI",
        explanation_zh="缺少 POI 會影響定位、撤退與遠端說明，應升級審核。",
    ),
    EscalationRule(
        rule_id="communication_uncertainty",
        trigger_field="communication_uncertainty_affects_remote_checkin",
        target_profile_id=ReviewProfileId.GUIDED,
        label="Communication uncertainty",
        label_zh="通訊不確定",
        explanation_zh="通訊不確定會影響遠端 check-in 或救援假設。",
    ),
    EscalationRule(
        rule_id="high_risk_route_notes",
        trigger_field="high_risk_route_note_terms",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="High-risk route note terms",
        label_zh="高風險路線筆記詞彙",
        explanation_zh="崩塌、暴露、不明路徑、繞行、危坡或缺路等提示需要更嚴格審核。",
    ),
    EscalationRule(
        rule_id="critical_field_verification_unresolved",
        trigger_field="unresolved_field_verification_categories",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="Critical field verification unresolved",
        label_zh="critical 現地確認未完成",
        explanation_zh="route、retreat、hazard、water、camp 或 runtime target 未確認時需升級。",
    ),
    EscalationRule(
        rule_id="critical_provenance_gap",
        trigger_field="critical_provenance_gaps",
        target_profile_id=ReviewProfileId.EXPEDITION,
        label="Critical provenance gap",
        label_zh="critical 來源缺口",
        explanation_zh="來源證據有 critical 缺口時不能低摩擦交接。",
    ),
)


def get_planning_review_profiles() -> dict[ReviewProfileId, PlanningReviewProfile]:
    return {profile.profile_id: profile for profile in PLANNING_REVIEW_PROFILES}


def get_baseline_hard_blocker_catalog() -> HardBlockerCatalog:
    return BASELINE_HARD_BLOCKER_CATALOG


def build_chilai_review_context(project_root: Path | str) -> RouteReviewContext:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)
    route_summary = _load_json(fixture_root / project["route_summary_ref"])
    retreat_routes = _load_json(fixture_root / project["retreat_routes_ref"])
    reviewed_retreat = next(
        (
            route
            for route in retreat_routes
            if route.get("review_state") == "accepted"
            and route.get("retreat_type") == "return_to_entry"
        ),
        None,
    )
    return RouteReviewContext(
        route_name=route_summary["route_name"],
        distance_m=route_summary["distance_m"],
        route_days=1,
        elevation_max_m=route_summary.get("elevation_max_m"),
        is_deep_mountain=True,
        retreat_policy_accepted=reviewed_retreat is not None,
        retreat_policy_type=(
            reviewed_retreat.get("retreat_type") if reviewed_retreat else None
        ),
        retreat_difficulty="clear" if reviewed_retreat else "unclear",
        user_explicitly_selected_lower_friction=True,
        final_mission_graph_exists=True,
        runtime_target_present=True,
    )


def classify_route_for_review(context: RouteReviewContext) -> RouteClassification:
    classes: list[RouteClassId] = []

    if context.route_days >= 2 and context.retreat_policy_type == "return_to_entry":
        classes.append(RouteClassId.MULTI_DAY_OUT_AND_BACK)
    if context.is_traverse:
        classes.append(RouteClassId.TRAVERSE)
    if context.is_technical_or_high_exposure:
        classes.append(RouteClassId.TECHNICAL_OR_HIGH_EXPOSURE)
    if context.is_wild_or_offtrail and not context.has_public_or_reviewed_gpx:
        classes.append(RouteClassId.FIELD_EXPLORATION_UNKNOWN_ROUTE)
    if context.route_days == 1 and context.distance_m >= 12000:
        classes.append(RouteClassId.LONG_SINGLE_DAY)
    if _is_deep_mountain_out_and_back(context):
        classes.append(RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK)
    if not classes and context.route_days == 1:
        classes.append(RouteClassId.SIMPLE_SINGLE_DAY)

    primary_class = _highest_route_class(classes)
    return RouteClassification(
        primary_class=primary_class,
        route_classes=classes,
        explanation=(
            f"{context.route_name} classified as {primary_class.value} from deterministic planning metadata."
        ),
        explanation_zh=_classification_explanation_zh(classes),
    )


def select_planning_review_profile(
    context: RouteReviewContext,
    requested_profile_id: ReviewProfileId = ReviewProfileId.GUIDED,
) -> ProfileSelectionResult:
    requested_profile_id = ReviewProfileId(requested_profile_id)
    classification = classify_route_for_review(context)
    escalation_reasons = _matching_escalation_rules(context, classification)
    hard_blockers = _matching_hard_blockers(context, handoff_requested=False)
    quick_allowed = _quick_review_allowed(context, hard_blockers)

    required_profile_id = _highest_profile_id(
        [requested_profile_id, *(rule.target_profile_id for rule in escalation_reasons)]
    )
    recommended_profile_id = required_profile_id
    if (
        requested_profile_id == ReviewProfileId.QUICK
        and quick_allowed
        and context.user_explicitly_selected_lower_friction
    ):
        required_profile_id = ReviewProfileId.QUICK

    selected_profile_id = _highest_profile_id([requested_profile_id, required_profile_id])

    return ProfileSelectionResult(
        requested_profile_id=requested_profile_id,
        selected_profile_id=selected_profile_id,
        required_profile_id=required_profile_id,
        recommended_profile_id=recommended_profile_id,
        route_classification=classification,
        escalation_reasons=escalation_reasons,
        hard_blockers=hard_blockers,
        quick_review_allowed=quick_allowed,
        explanation_zh=_selection_explanation_zh(
            requested_profile_id=requested_profile_id,
            selected_profile_id=selected_profile_id,
            quick_allowed=quick_allowed,
            hard_blockers=hard_blockers,
            escalation_reasons=escalation_reasons,
        ),
        boundary=ProfileBoundary(
            notes=[
                "Profile selection is planning metadata only.",
                "No Phase 1 runtime mutation is performed.",
                "No live safety endpoint is called.",
            ]
        ),
    )


def evaluate_hard_blockers(
    context: RouteReviewContext,
    *,
    handoff_requested: bool = False,
) -> list[HardBlockerPolicy]:
    return _matching_hard_blockers(context, handoff_requested=handoff_requested)


def _resolve_chilai_project_path(path: Path) -> Path:
    if path.is_file():
        return path
    if path.name == "chilai_nanhua_day1":
        return path / "project.json"
    candidate = path / DEFAULT_CHILAI_PROJECT_REF
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"could not find Chilai pretrip project.json under {path}")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_deep_mountain_out_and_back(context: RouteReviewContext) -> bool:
    deep_mountain = (
        context.is_deep_mountain
        or (context.elevation_max_m is not None and context.elevation_max_m >= 2500)
        or any(token in context.route_name for token in ("奇萊", "南華", "能高"))
    )
    return (
        deep_mountain
        and context.route_days == 1
        and context.retreat_policy_accepted
        and context.retreat_policy_type == "return_to_entry"
    )


def _highest_route_class(classes: list[RouteClassId]) -> RouteClassId:
    priority = {
        RouteClassId.SIMPLE_SINGLE_DAY: 0,
        RouteClassId.LONG_SINGLE_DAY: 1,
        RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK: 2,
        RouteClassId.MULTI_DAY_OUT_AND_BACK: 3,
        RouteClassId.TRAVERSE: 4,
        RouteClassId.TECHNICAL_OR_HIGH_EXPOSURE: 5,
        RouteClassId.FIELD_EXPLORATION_UNKNOWN_ROUTE: 5,
    }
    return max(classes, key=lambda route_class: priority[route_class])


def _classification_explanation_zh(classes: list[RouteClassId]) -> str:
    labels = {
        definition.class_id: definition.label_zh for definition in ROUTE_CLASS_DEFINITIONS
    }
    return "、".join(labels[route_class] for route_class in classes)


def _matching_escalation_rules(
    context: RouteReviewContext,
    classification: RouteClassification,
) -> list[EscalationRule]:
    matched: list[EscalationRule] = []
    if context.route_days >= 2:
        matched.append(_rule("multi_day_itinerary"))
    if context.is_traverse:
        matched.append(_rule("traverse_route"))
    if context.is_deep_mountain and context.retreat_difficulty in {"difficult", "unclear"}:
        matched.append(_rule("deep_mountain_unclear_retreat"))
    if context.is_wild_or_offtrail and not context.has_public_or_reviewed_gpx:
        matched.append(_rule("wild_route_missing_trusted_evidence"))
    if context.weather_no_go:
        matched.append(_rule("weather_policy_no_go"))
    if context.expected_arrival_after_last_light:
        matched.append(_rule("arrival_near_or_after_last_light"))
    if _route_requires_retreat_policy(classification, context) and not context.retreat_policy_accepted:
        matched.append(_rule("no_accepted_retreat_policy"))
    if (
        context.water_uncertainty_affects_safety
        and (
            context.route_days >= 2
            or RouteClassId.LONG_SINGLE_DAY in classification.route_classes
        )
    ):
        matched.append(_rule("water_uncertainty_long_or_overnight"))
    if not context.route_corridor_has_poi:
        matched.append(_rule("route_corridor_no_poi"))
    if context.communication_uncertainty_affects_remote_checkin:
        matched.append(_rule("communication_uncertainty"))
    if context.high_risk_route_note_terms:
        matched.append(_rule("high_risk_route_notes"))
    if _has_critical_field_verification_gap(context):
        matched.append(_rule("critical_field_verification_unresolved"))
    if context.critical_provenance_gaps:
        matched.append(_rule("critical_provenance_gap"))
    return matched


def _rule(rule_id: str) -> EscalationRule:
    for rule in ESCALATION_RULES:
        if rule.rule_id == rule_id:
            return rule
    raise KeyError(rule_id)


def _matching_hard_blockers(
    context: RouteReviewContext,
    *,
    handoff_requested: bool,
) -> list[HardBlockerPolicy]:
    blockers: list[HardBlockerId] = []
    classification = classify_route_for_review(context)

    if context.weather_no_go:
        blockers.append(HardBlockerId.WEATHER_NO_GO)
    if not context.has_valid_route:
        blockers.append(HardBlockerId.NO_VALID_ROUTE)
    if context.is_wild_or_offtrail and not context.has_public_or_reviewed_gpx:
        blockers.append(HardBlockerId.UNVERIFIED_WILD_ROUTE_WITHOUT_PUBLIC_GPX)
    if _route_requires_retreat_policy(classification, context) and not context.retreat_policy_accepted:
        blockers.append(HardBlockerId.NO_RETREAT_POLICY_FOR_REQUIRED_ROUTE)
    if not context.reviewed_package_exists:
        blockers.append(HardBlockerId.NO_REVIEWED_PACKAGE)
    if handoff_requested and not context.final_mission_graph_exists:
        blockers.append(HardBlockerId.NO_FINAL_MISSION_GRAPH)
    if not context.package_or_graph_hash_valid:
        blockers.append(HardBlockerId.CORRUPT_PACKAGE_OR_GRAPH_HASH)
    if handoff_requested and not context.runtime_target_present:
        blockers.append(HardBlockerId.MISSING_RUNTIME_TARGET)

    catalog_by_id = {
        blocker.blocker_id: blocker for blocker in BASELINE_HARD_BLOCKER_CATALOG.blockers
    }
    return [catalog_by_id[blocker_id] for blocker_id in blockers]


def _route_requires_retreat_policy(
    classification: RouteClassification,
    context: RouteReviewContext,
) -> bool:
    return (
        context.is_deep_mountain
        or context.is_traverse
        or context.is_technical_or_high_exposure
        or any(
            route_class
            in {
                RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK,
                RouteClassId.MULTI_DAY_OUT_AND_BACK,
                RouteClassId.TRAVERSE,
                RouteClassId.TECHNICAL_OR_HIGH_EXPOSURE,
            }
            for route_class in classification.route_classes
        )
    )


def _has_critical_field_verification_gap(context: RouteReviewContext) -> bool:
    critical_categories = {"route", "retreat", "hazard", "water", "camp", "runtime_target"}
    return any(
        category in critical_categories
        for category in context.unresolved_field_verification_categories
    )


def _quick_review_allowed(
    context: RouteReviewContext,
    hard_blockers: list[HardBlockerPolicy],
) -> bool:
    if hard_blockers:
        return False
    if context.weather_no_go or not context.has_valid_route:
        return False
    if context.is_wild_or_offtrail and not context.has_public_or_reviewed_gpx:
        return False
    if context.is_traverse or context.route_days >= 2 or context.is_technical_or_high_exposure:
        return False
    if context.is_deep_mountain:
        return (
            context.route_evidence_trusted
            and context.has_public_or_reviewed_gpx
            and context.retreat_policy_accepted
            and context.retreat_policy_type == "return_to_entry"
            and context.retreat_difficulty == "clear"
            and not _has_critical_field_verification_gap(context)
        )
    return True


def _highest_profile_id(profile_ids: list[ReviewProfileId]) -> ReviewProfileId:
    return max(profile_ids, key=lambda profile_id: PROFILE_ORDER[profile_id])


def _selection_explanation_zh(
    *,
    requested_profile_id: ReviewProfileId,
    selected_profile_id: ReviewProfileId,
    quick_allowed: bool,
    hard_blockers: list[HardBlockerPolicy],
    escalation_reasons: list[EscalationRule],
) -> str:
    if hard_blockers:
        blocker_labels = "、".join(blocker.label_zh for blocker in hard_blockers)
        return f"存在 hard blocker：{blocker_labels}；profile 不能用來略過這些阻擋。"
    if requested_profile_id == ReviewProfileId.QUICK and quick_allowed:
        return "符合快捷模式條件；仍需有效路線、撤退策略、出發批准與 runtime 交接。"
    if escalation_reasons:
        reason_labels = "、".join(reason.label_zh for reason in escalation_reasons)
        return f"因 {reason_labels}，建議或要求升級為 {selected_profile_id.value}。"
    return "未觸發升級規則，維持所選審核設定檔。"
