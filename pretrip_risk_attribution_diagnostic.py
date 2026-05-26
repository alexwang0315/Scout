from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


RISK_ATTRIBUTION_VERSION = "0.2.0"
DEFAULT_WORKSPACE = Path("/tmp/scout-fusion-pretrip-workspaces/chilai_nanhua_day1")
RISK_DIMENSIONS = ("teii_20m", "tri", "sri", "lec", "scp", "pretrip_risk")
FACTOR_DIMENSIONS = ("teii_20m", "tri", "sri", "lec", "scp")
SEMANTIC_ATTENTION_GROUPS = {"danger", "technical_caution"}
EARTH_RADIUS_M = 6_371_000.0
DEFAULT_EXCLUDED_EXTREME_PERCENTILE = 0.95
DEFAULT_MAX_WARNING_CP_PROPOSALS = 50

DANGER_TERMS = (
    "危險",
    "崩塌",
    "大崩",
    "崩壁",
    "崩崖",
    "斷崖",
    "崩",
    "勿",
    "小心",
    "拉繩",
    "架繩",
    "需繩",
    "迷路",
    "路跡不明",
)
TECHNICAL_CAUTION_TERMS = (
    "高繞",
    "腰繞",
    "低繞",
    "上切",
    "下切",
    "切點",
    "回河床",
    "上稜",
    "下稜",
    "獸徑",
    "獸俓",
    "布條",
)


@dataclass(frozen=True)
class RouteRiskPoint:
    sample_id: str
    lat: float
    lon: float
    properties: dict[str, Any]


def build_risk_attribution_diagnostic(
    *,
    route_risk_path: Path | str,
    gis_perception_path: Path | str | None = None,
    route_note_ln_proposals_path: Path | str | None = None,
    join_radius_m: float = 100.0,
    top_n: int = 10,
    excluded_extreme_percentile: float = DEFAULT_EXCLUDED_EXTREME_PERCENTILE,
    max_warning_cp_proposals: int = DEFAULT_MAX_WARNING_CP_PROPOSALS,
) -> dict[str, Any]:
    route_risk_path = Path(route_risk_path)
    route_points = load_route_risk_points(route_risk_path)
    semantic_cps = load_semantic_checkpoints(
        gis_perception_path=gis_perception_path,
        route_note_ln_proposals_path=route_note_ln_proposals_path,
    )
    route_dimension_stats = dimension_stats(point.properties for point in route_points)
    route_thresholds = {
        dimension: {
            "p75": route_dimension_stats[dimension]["p75"],
            "p90": route_dimension_stats[dimension]["p90"],
            "zero_variance": (
                route_dimension_stats[dimension]["min"]
                == route_dimension_stats[dimension]["max"]
            ),
        }
        for dimension in RISK_DIMENSIONS
    }

    joined = [
        join_semantic_checkpoint(
            checkpoint=checkpoint,
            route_points=route_points,
            route_thresholds=route_thresholds,
            join_radius_m=join_radius_m,
        )
        for checkpoint in semantic_cps
    ]
    groups = build_group_summaries(
        joined=joined,
        route_points=route_points,
        route_dimension_stats=route_dimension_stats,
        join_radius_m=join_radius_m,
    )
    top_attention = [
        slim_joined_checkpoint(item)
        for item in sorted(
            (
                item
                for item in joined
                if item["semantic_group"] in SEMANTIC_ATTENTION_GROUPS
            ),
            key=lambda item: (
                item["matched_within_join_radius"],
                item["nearest_dimensions"].get("pretrip_risk") or 0,
                item["nearest_dimensions"].get("teii_20m") or 0,
            ),
            reverse=True,
        )[:top_n]
    ]
    observations = build_observations(
        route_dimension_stats=route_dimension_stats,
        groups=groups,
        joined=joined,
        join_radius_m=join_radius_m,
    )
    factor_analysis = build_factor_analysis(
        groups=groups,
        route_dimension_stats=route_dimension_stats,
    )
    warning_cp_proposals = build_excluded_extreme_warning_cp_proposals(
        route_points=route_points,
        route_dimension_stats=route_dimension_stats,
        factor_analysis=factor_analysis,
        extreme_percentile=excluded_extreme_percentile,
        max_proposals=max_warning_cp_proposals,
    )

    semantic_counts = Counter(item["semantic_group"] for item in joined)
    return {
        "artifact_kind": "pretrip_risk_attribution_diagnostic",
        "schema_version": RISK_ATTRIBUTION_VERSION,
        "status": "candidate_only_diagnostic",
        "boundary": {
            "candidate_only": True,
            "human_review_required_before_use": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "weighted_risk_score_mutation_allowed": False,
            "notes": [
                "Risk attribution diagnostic（風險歸因診斷）拆解既有 route risk 維度，只觀察，不改原始分數。",
                "Semantic CP（語意檢查點）來自 GPX route-note AI 中介判斷，仍是 pretrip candidate evidence（行前候選證據）。",
            ],
        },
        "inputs": {
            "route_risk_path": str(route_risk_path),
            "gis_perception_path": str(gis_perception_path)
            if gis_perception_path is not None
            else None,
            "route_note_ln_proposals_path": str(route_note_ln_proposals_path)
            if route_note_ln_proposals_path is not None
            else None,
            "join_radius_m": join_radius_m,
            "excluded_extreme_percentile": excluded_extreme_percentile,
        },
        "counts": {
            "route_sample_count": len(route_points),
            "semantic_checkpoint_count": len(joined),
            "semantic_attention_checkpoint_count": sum(
                semantic_counts[group] for group in SEMANTIC_ATTENTION_GROUPS
            ),
            "danger_checkpoint_count": semantic_counts["danger"],
            "technical_caution_checkpoint_count": semantic_counts[
                "technical_caution"
            ],
            "context_checkpoint_count": semantic_counts["context"],
            "attention_matched_within_join_radius_count": sum(
                1
                for item in joined
                if item["semantic_group"] in SEMANTIC_ATTENTION_GROUPS
                and item["matched_within_join_radius"]
            ),
            "excluded_extreme_warning_cp_proposal_count": warning_cp_proposals[
                "counts"
            ]["proposal_count"],
        },
        "risk_dimensions": list(RISK_DIMENSIONS),
        "factor_dimensions": list(FACTOR_DIMENSIONS),
        "route_dimension_stats": route_dimension_stats,
        "groups": groups,
        "factor_analysis": factor_analysis,
        "excluded_extreme_warning_cp_proposals": warning_cp_proposals,
        "top_semantic_attention_matches": top_attention,
        "observations": observations,
    }


def load_route_risk_points(path: Path | str) -> list[RouteRiskPoint]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    points: list[RouteRiskPoint] = []
    for index, feature in enumerate(payload.get("features", [])):
        geometry = feature.get("geometry") or {}
        properties = dict(feature.get("properties") or {})
        coordinates = geometry.get("coordinates") or []
        lon = _safe_float(coordinates[0] if len(coordinates) > 0 else properties.get("lon"))
        lat = _safe_float(coordinates[1] if len(coordinates) > 1 else properties.get("lat"))
        if lat is None or lon is None:
            continue
        sample_id = str(properties.get("sample_id") or f"route_risk.sample.{index:04d}")
        points.append(RouteRiskPoint(sample_id=sample_id, lat=lat, lon=lon, properties=properties))
    if not points:
        raise ValueError(f"route risk GeoJSON has no usable point features: {path}")
    return points


def load_semantic_checkpoints(
    *,
    gis_perception_path: Path | str | None,
    route_note_ln_proposals_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    proposal_lookup = load_route_note_ln_proposal_lookup(route_note_ln_proposals_path)
    checkpoints: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    if gis_perception_path is not None and Path(gis_perception_path).exists():
        payload = json.loads(Path(gis_perception_path).read_text(encoding="utf-8"))
        for item in payload.get("checkpoint_candidates", []):
            lat = _safe_float(item.get("lat"))
            lon = _safe_float(item.get("lon"))
            if lat is None or lon is None:
                continue
            source_id = str(
                item.get("source_route_note_candidate_id")
                or item.get("candidate_id")
                or f"semantic_cp.{len(checkpoints):04d}"
            )
            proposal = proposal_lookup.get(source_id, {})
            merged = {**proposal, **item}
            merged["lat"] = lat
            merged["lon"] = lon
            checkpoints.append(normalize_semantic_checkpoint(merged, source_id=source_id))
            seen_source_ids.add(source_id)

    for source_id, item in proposal_lookup.items():
        if source_id in seen_source_ids:
            continue
        lat = _safe_float(item.get("lat"))
        lon = _safe_float(item.get("lon"))
        if lat is None or lon is None:
            continue
        checkpoints.append(normalize_semantic_checkpoint(item, source_id=source_id))
    return checkpoints


def load_route_note_ln_proposal_lookup(path: Path | str | None) -> dict[str, dict[str, Any]]:
    if path is None or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    proposals: dict[str, dict[str, Any]] = {}
    for proposal in payload.get("proposals", []):
        source_id = str(
            proposal.get("source_route_note_candidate_id")
            or proposal.get("proposal_id")
            or f"ln_proposal.{len(proposals):04d}"
        )
        proposals[source_id] = dict(proposal)
    return proposals


def normalize_semantic_checkpoint(item: dict[str, Any], *, source_id: str) -> dict[str, Any]:
    semantic_group = classify_semantic_checkpoint(item)
    return {
        "candidate_id": str(item.get("candidate_id") or item.get("proposal_id") or source_id),
        "source_route_note_candidate_id": source_id,
        "semantic_group": semantic_group,
        "checkpoint_type": item.get("checkpoint_type"),
        "proposal_kind": item.get("proposal_kind"),
        "source_note_category": item.get("source_note_category"),
        "route_note_summary": str(item.get("route_note_summary") or ""),
        "recommended_review_action": item.get("recommended_review_action"),
        "source_gpx_key": item.get("source_gpx_key"),
        "source_gpx_role": item.get("source_gpx_role"),
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
        "time": item.get("time"),
        "route_note_age_days": item.get("route_note_age_days"),
        "route_note_freshness": item.get("route_note_freshness"),
        "stale_route_note": item.get("stale_route_note"),
        "ai_reason_zh": item.get("ai_reason_zh"),
        "ai_confidence": item.get("ai_confidence"),
        "candidate_only": item.get("candidate_only", True),
    }


def classify_semantic_checkpoint(item: dict[str, Any]) -> str:
    checkpoint_type = item.get("checkpoint_type")
    proposal_kind = item.get("proposal_kind")
    source_note_category = item.get("source_note_category")
    if checkpoint_type == "warning_review":
        return "danger"
    if checkpoint_type == "hint_review":
        return "technical_caution"
    if checkpoint_type in {"water_or_camp_review", "landmark_review", "none"}:
        return "context"
    text = " ".join(
        str(item.get(key) or "")
        for key in (
            "route_note_summary",
            "recommended_review_action",
            "proposed_coverage_label",
            "ai_reason_zh",
        )
    )
    if (
        proposal_kind == "warning_coverage"
        or source_note_category == "hazard_hint"
        or any(term in text for term in DANGER_TERMS)
    ):
        return "danger"
    if (
        proposal_kind == "hint_coverage"
        or source_note_category == "route_condition_hint"
        or any(term in text for term in TECHNICAL_CAUTION_TERMS)
    ):
        return "technical_caution"
    return "context"


def join_semantic_checkpoint(
    *,
    checkpoint: dict[str, Any],
    route_points: Sequence[RouteRiskPoint],
    route_thresholds: dict[str, dict[str, Any]],
    join_radius_m: float,
) -> dict[str, Any]:
    distances = [
        (
            haversine_m(
                checkpoint["lat"],
                checkpoint["lon"],
                route_point.lat,
                route_point.lon,
            ),
            route_point,
        )
        for route_point in route_points
    ]
    nearest_distance, nearest_point = min(distances, key=lambda item: item[0])
    local_sample_ids = [
        route_point.sample_id
        for distance_m, route_point in distances
        if distance_m <= join_radius_m
    ]
    nearest_dimensions = {
        dimension: _safe_float(nearest_point.properties.get(dimension))
        for dimension in RISK_DIMENSIONS
    }
    percentile_flags = {}
    for dimension, value in nearest_dimensions.items():
        threshold = route_thresholds[dimension]
        if value is None or threshold["zero_variance"]:
            percentile_flags[dimension] = {
                "above_route_p75": None,
                "above_route_p90": None,
                "reason": "zero_variance" if threshold["zero_variance"] else "missing_value",
            }
            continue
        percentile_flags[dimension] = {
            "above_route_p75": value >= threshold["p75"],
            "above_route_p90": value >= threshold["p90"],
        }
    return {
        **checkpoint,
        "nearest_sample_id": nearest_point.sample_id,
        "nearest_distance_m": round(nearest_distance, 2),
        "matched_within_join_radius": nearest_distance <= join_radius_m,
        "local_route_sample_count": len(local_sample_ids),
        "local_route_sample_ids": local_sample_ids,
        "nearest_dimensions": nearest_dimensions,
        "nearest_dimension_percentile_flags": percentile_flags,
    }


def build_group_summaries(
    *,
    joined: Sequence[dict[str, Any]],
    route_points: Sequence[RouteRiskPoint],
    route_dimension_stats: dict[str, dict[str, Any]],
    join_radius_m: float,
) -> dict[str, Any]:
    route_point_by_id = {point.sample_id: point for point in route_points}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in joined:
        groups[item["semantic_group"]].append(item)
    groups["semantic_attention"] = [
        item for item in joined if item["semantic_group"] in SEMANTIC_ATTENTION_GROUPS
    ]

    summaries: dict[str, Any] = {}
    for group_name in ("danger", "technical_caution", "context", "semantic_attention"):
        items = groups.get(group_name, [])
        matched_items = [
            item for item in items if item["matched_within_join_radius"]
        ]
        local_sample_ids = {
            sample_id
            for item in items
            for sample_id in item.get("local_route_sample_ids", [])
        }
        local_samples = [
            route_point_by_id[sample_id].properties
            for sample_id in sorted(local_sample_ids)
            if sample_id in route_point_by_id
        ]
        nearest_dimensions = [item["nearest_dimensions"] for item in items]
        matched_nearest_dimensions = [
            item["nearest_dimensions"] for item in matched_items
        ]
        nearest_stats = dimension_stats(nearest_dimensions)
        matched_nearest_stats = dimension_stats(matched_nearest_dimensions)
        local_stats = dimension_stats(local_samples)
        summaries[group_name] = {
            "candidate_count": len(items),
            "matched_within_join_radius_count": sum(
                1 for item in items if item["matched_within_join_radius"]
            ),
            "join_radius_m": join_radius_m,
            "nearest_distance_m": value_stats(item["nearest_distance_m"] for item in items),
            "nearest_sample_dimension_stats": nearest_stats,
            "matched_nearest_sample_dimension_stats": matched_nearest_stats,
            "local_route_sample_dimension_stats": local_stats,
            "nearest_dimension_ratios": nearest_dimension_ratios(
                items=items,
                route_dimension_stats=route_dimension_stats,
            ),
            "matched_nearest_dimension_ratios": nearest_dimension_ratios(
                items=matched_items,
                route_dimension_stats=route_dimension_stats,
            ),
            "dimension_delta_vs_route_mean": {
                dimension: _round_or_none(
                    (nearest_stats[dimension]["mean"] - route_dimension_stats[dimension]["mean"])
                    if nearest_stats[dimension]["n"]
                    else None
                )
                for dimension in RISK_DIMENSIONS
            },
            "matched_dimension_delta_vs_route_mean": {
                dimension: _round_or_none(
                    (
                        matched_nearest_stats[dimension]["mean"]
                        - route_dimension_stats[dimension]["mean"]
                    )
                    if matched_nearest_stats[dimension]["n"]
                    else None
                )
                for dimension in RISK_DIMENSIONS
            },
        }
    return summaries


def nearest_dimension_ratios(
    *,
    items: Sequence[dict[str, Any]],
    route_dimension_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for dimension in RISK_DIMENSIONS:
        route_stats = route_dimension_stats[dimension]
        if route_stats["min"] == route_stats["max"]:
            output[dimension] = {
                "above_route_p75_ratio": None,
                "above_route_p90_ratio": None,
                "reason": "zero_variance",
            }
            continue
        values = [
            item["nearest_dimensions"].get(dimension)
            for item in items
            if item["nearest_dimensions"].get(dimension) is not None
        ]
        if not values:
            output[dimension] = {
                "above_route_p75_ratio": None,
                "above_route_p90_ratio": None,
                "reason": "missing_values",
            }
            continue
        output[dimension] = {
            "above_route_p75_ratio": round(
                sum(value >= route_stats["p75"] for value in values) / len(values),
                3,
            ),
            "above_route_p90_ratio": round(
                sum(value >= route_stats["p90"] for value in values) / len(values),
                3,
            ),
        }
    return output


def build_factor_analysis(
    *,
    groups: dict[str, Any],
    route_dimension_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    target_group = _factor_target_group(groups)
    target = groups[target_group]
    context = groups["context"]
    factors = [
        score_factor_dimension(
            dimension=dimension,
            target_group=target_group,
            target=target,
            context=context,
            route_dimension_stats=route_dimension_stats,
        )
        for dimension in FACTOR_DIMENSIONS
    ]
    ranked = sorted(
        factors,
        key=lambda item: (
            item["eligible_for_formula"],
            item["explanatory_strength"],
            item.get("target_above_route_p75_ratio") or 0,
        ),
        reverse=True,
    )
    selected = [
        factor
        for factor in ranked
        if factor["eligible_for_formula"] and factor["explanatory_strength"] > 0
    ][:3]
    formula_candidate = build_formula_candidate(
        selected=selected,
        target_group=target_group,
    )
    return {
        "artifact_kind": "pretrip_risk_factor_analysis",
        "status": "candidate_only_diagnostic",
        "target_group": target_group,
        "target_group_reason_zh": (
            "優先使用 danger CP，因為其與實際危險語意最接近；若 danger 可對位樣本不足才退回 semantic_attention。"
            if target_group == "danger"
            else "danger 可對位樣本不足，改用 semantic_attention（danger + technical caution）做本次校準。"
        ),
        "factor_ranking": ranked,
        "formula_candidate": formula_candidate,
        "excluded_dimensions": [
            factor["dimension"]
            for factor in ranked
            if factor["dimension"] not in formula_candidate["selected_dimensions"]
        ],
        "notes": [
            "Factor analysis（因子分析）只使用本 workspace 的 historical semantic CP 與 route risk 維度。",
            "Formula candidate（公式候選）不會覆寫既有 route_risk.geojson；需人工檢視後才可進下一個校準 slice。",
        ],
    }


def _factor_target_group(groups: dict[str, Any]) -> str:
    danger_count = groups["danger"]["matched_within_join_radius_count"]
    if danger_count >= 5:
        return "danger"
    return "semantic_attention"


def score_factor_dimension(
    *,
    dimension: str,
    target_group: str,
    target: dict[str, Any],
    context: dict[str, Any],
    route_dimension_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    route_stats = route_dimension_stats[dimension]
    target_stats = target["matched_nearest_sample_dimension_stats"][dimension]
    context_stats = context["matched_nearest_sample_dimension_stats"][dimension]
    target_ratios = target["matched_nearest_dimension_ratios"][dimension]
    context_ratios = context["matched_nearest_dimension_ratios"][dimension]
    if route_stats["min"] == route_stats["max"]:
        return {
            "dimension": dimension,
            "target_group": target_group,
            "eligible_for_formula": False,
            "explanatory_strength": 0.0,
            "reason": "zero_variance",
            "reason_zh": "此維度在整條路線沒有變異，不能解釋 historical danger CP。",
            "target_matched_count": target_stats["n"],
        }
    if target_stats["n"] == 0:
        return {
            "dimension": dimension,
            "target_group": target_group,
            "eligible_for_formula": False,
            "explanatory_strength": 0.0,
            "reason": "no_matched_target_samples",
            "reason_zh": "此 workspace 沒有可對位的 target semantic CP，暫不納入公式候選。",
            "target_matched_count": 0,
        }

    target_p75 = target_ratios.get("above_route_p75_ratio") or 0.0
    context_p75 = context_ratios.get("above_route_p75_ratio") or 0.0
    target_p90 = target_ratios.get("above_route_p90_ratio") or 0.0
    context_p90 = context_ratios.get("above_route_p90_ratio") or 0.0
    target_mean = target_stats["mean"] or 0.0
    context_mean = context_stats["mean"] or 0.0
    route_mean = route_stats["mean"] or 0.0
    p75_lift = target_p75 - context_p75
    p90_lift = target_p90 - context_p90
    context_mean_lift = (target_mean - context_mean) / 100.0
    route_mean_lift = (target_mean - route_mean) / 100.0
    strength = 100.0 * (
        0.45 * max(0.0, p75_lift)
        + 0.25 * max(0.0, p90_lift)
        + 0.20 * max(0.0, context_mean_lift)
        + 0.10 * max(0.0, route_mean_lift)
    )
    return {
        "dimension": dimension,
        "target_group": target_group,
        "eligible_for_formula": strength > 0,
        "explanatory_strength": round(strength, 3),
        "target_matched_count": target_stats["n"],
        "target_mean": target_stats["mean"],
        "route_mean": route_stats["mean"],
        "context_mean": context_stats["mean"],
        "target_above_route_p75_ratio": target_p75,
        "context_above_route_p75_ratio": context_p75,
        "p75_lift_vs_context": round(p75_lift, 3),
        "target_above_route_p90_ratio": target_p90,
        "context_above_route_p90_ratio": context_p90,
        "p90_lift_vs_context": round(p90_lift, 3),
        "mean_lift_vs_context": round(target_mean - context_mean, 2),
        "mean_lift_vs_route": round(target_mean - route_mean, 2),
        "reason": "ranked_by_workspace_semantic_fit",
        "reason_zh": (
            f"{dimension} 在 {target_group} CP 附近比 context CP 與整條 route 更常偏高，"
            "因此作為本 workspace 公式候選的排序依據。"
        ),
    }


def build_formula_candidate(
    *,
    selected: Sequence[dict[str, Any]],
    target_group: str,
) -> dict[str, Any]:
    if not selected:
        return {
            "status": "insufficient_signal",
            "target_group": target_group,
            "selected_dimensions": [],
            "terms": [],
            "expression": None,
            "expression_zh": "本 workspace 沒有足夠訊號提出 route-specific risk score 公式候選。",
        }
    strong_score = selected[0]["explanatory_strength"] or 1.0
    terms = []
    for index, factor in enumerate(selected):
        raw_weight = 1.0 if index == 0 else factor["explanatory_strength"] / strong_score
        role = ("strong", "secondary", "weak")[index]
        terms.append(
            {
                "role": role,
                "dimension": factor["dimension"],
                "explanatory_strength": factor["explanatory_strength"],
                "raw_weight": round(raw_weight, 3),
            }
        )
    raw_weight_sum = sum(term["raw_weight"] for term in terms)
    for term in terms:
        term["normalized_weight"] = round(term["raw_weight"] / raw_weight_sum, 3)
    expression_terms = [
        terms[0]["dimension"],
        *[
            f"{term['raw_weight']:.3g}*{term['dimension']}"
            for term in terms[1:]
        ],
    ]
    expression = (
        "("
        + " + ".join(expression_terms)
        + f") / {raw_weight_sum:.3g}"
    )
    return {
        "status": "candidate_only",
        "target_group": target_group,
        "selected_dimensions": [term["dimension"] for term in terms],
        "terms": terms,
        "expression": expression,
        "expression_zh": (
            "本 workspace 的候選公式："
            + expression
            + "。這是 route-specific calibration candidate（路線專屬校準候選），尚未覆寫正式分數。"
        ),
    }


def build_excluded_extreme_warning_cp_proposals(
    *,
    route_points: Sequence[RouteRiskPoint],
    route_dimension_stats: dict[str, dict[str, Any]],
    factor_analysis: dict[str, Any],
    extreme_percentile: float,
    max_proposals: int,
) -> dict[str, Any]:
    selected_dimensions = set(
        factor_analysis.get("formula_candidate", {}).get("selected_dimensions", [])
    )
    excluded_dimensions = [
        dimension
        for dimension in FACTOR_DIMENSIONS
        if dimension not in selected_dimensions
        and route_dimension_stats[dimension]["min"] != route_dimension_stats[dimension]["max"]
    ]
    proposals: list[dict[str, Any]] = []
    for dimension in excluded_dimensions:
        values = [
            _safe_float(point.properties.get(dimension))
            for point in route_points
        ]
        threshold = percentile(
            sorted(value for value in values if value is not None),
            extreme_percentile,
        )
        runs = extreme_route_point_runs(
            route_points=route_points,
            dimension=dimension,
            threshold=threshold,
        )
        for run_index, run in enumerate(runs):
            if len(proposals) >= max_proposals:
                break
            peak = max(run, key=lambda point: _safe_float(point.properties.get(dimension)) or 0.0)
            peak_value = _safe_float(peak.properties.get(dimension)) or 0.0
            proposals.append(
                {
                    "proposal_id": (
                        f"warning_cp.excluded_extreme.{dimension}."
                        f"{_safe_id(peak.sample_id)}.{run_index:03d}"
                    ),
                    "candidate_kind": "warning_cp_proposal",
                    "source": "excluded_extreme_risk_dimension",
                    "excluded_dimension": dimension,
                    "excluded_dimension_value": round(peak_value, 2),
                    "extreme_threshold": round(threshold, 2),
                    "extreme_percentile": extreme_percentile,
                    "lat": peak.lat,
                    "lon": peak.lon,
                    "route_id": peak.properties.get("route_id"),
                    "source_sample_id": peak.sample_id,
                    "distance_m": peak.properties.get("distance_m"),
                    "run_sample_count": len(run),
                    "run_start_distance_m": run[0].properties.get("distance_m"),
                    "run_end_distance_m": run[-1].properties.get("distance_m"),
                    "risk_dimensions": {
                        dim: _safe_float(peak.properties.get(dim))
                        for dim in RISK_DIMENSIONS
                    },
                    "reason_zh": (
                        f"{dimension} 未納入本次 risk score 公式候選，但此處分數 "
                        f"{peak_value:.2f} 達本路線極端門檻 {threshold:.2f}，"
                        "因此保留為 warning CP proposal（警示檢查點候選）供人工複核。"
                    ),
                    "candidate_only": True,
                    "human_review_required": True,
                    "runtime_safety_truth": False,
                }
            )
    return {
        "artifact_kind": "pretrip_excluded_extreme_warning_cp_proposals",
        "schema_version": RISK_ATTRIBUTION_VERSION,
        "status": "candidate_only",
        "counts": {
            "excluded_dimension_count": len(excluded_dimensions),
            "proposal_count": len(proposals),
            "max_proposals": max_proposals,
        },
        "selected_formula_dimensions": sorted(selected_dimensions),
        "excluded_dimensions": excluded_dimensions,
        "boundary": {
            "candidate_only": True,
            "human_review_required_before_use": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "notes": [
                "未納入公式候選的維度若出現極端值，只能形成 Workspace warning CP proposal。",
                "這些 proposal 不會改動既有 route risk score，也不會成為 runtime safety truth。",
            ],
        },
        "proposals": proposals,
    }


def extreme_route_point_runs(
    *,
    route_points: Sequence[RouteRiskPoint],
    dimension: str,
    threshold: float,
    max_gap_m: float = 120.0,
) -> list[list[RouteRiskPoint]]:
    sorted_points = sorted(
        route_points,
        key=lambda point: (
            _safe_float(point.properties.get("distance_m")) is None,
            _safe_float(point.properties.get("distance_m")) or 0.0,
            point.sample_id,
        ),
    )
    runs: list[list[RouteRiskPoint]] = []
    current: list[RouteRiskPoint] = []
    previous_distance: float | None = None
    for point in sorted_points:
        value = _safe_float(point.properties.get(dimension))
        distance = _safe_float(point.properties.get("distance_m"))
        if value is None or value < threshold:
            if current:
                runs.append(current)
                current = []
                previous_distance = None
            continue
        if (
            current
            and distance is not None
            and previous_distance is not None
            and distance - previous_distance > max_gap_m
        ):
            runs.append(current)
            current = []
        current.append(point)
        previous_distance = distance
    if current:
        runs.append(current)
    return runs


def dimension_stats(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    row_list = list(rows)
    return {
        dimension: value_stats(
            _safe_float(row.get(dimension)) for row in row_list if row.get(dimension) is not None
        )
        for dimension in RISK_DIMENSIONS
    }


def value_stats(values: Iterable[float | int | None]) -> dict[str, Any]:
    numeric = sorted(float(value) for value in values if value is not None)
    if not numeric:
        return {
            "n": 0,
            "min": None,
            "mean": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "max": None,
        }
    return {
        "n": len(numeric),
        "min": _round_or_none(numeric[0]),
        "mean": _round_or_none(sum(numeric) / len(numeric)),
        "p50": _round_or_none(percentile(numeric, 0.50)),
        "p75": _round_or_none(percentile(numeric, 0.75)),
        "p90": _round_or_none(percentile(numeric, 0.90)),
        "p95": _round_or_none(percentile(numeric, 0.95)),
        "max": _round_or_none(numeric[-1]),
    }


def percentile(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        raise ValueError("cannot percentile empty values")
    index = int((len(sorted_values) - 1) * fraction)
    return sorted_values[index]


def slim_joined_checkpoint(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": item["candidate_id"],
        "source_route_note_candidate_id": item["source_route_note_candidate_id"],
        "semantic_group": item["semantic_group"],
        "checkpoint_type": item.get("checkpoint_type"),
        "proposal_kind": item.get("proposal_kind"),
        "route_note_summary": item.get("route_note_summary"),
        "source_gpx_key": item.get("source_gpx_key"),
        "source_gpx_role": item.get("source_gpx_role"),
        "nearest_sample_id": item["nearest_sample_id"],
        "nearest_distance_m": item["nearest_distance_m"],
        "matched_within_join_radius": item["matched_within_join_radius"],
        "nearest_dimensions": item["nearest_dimensions"],
        "nearest_dimension_percentile_flags": item["nearest_dimension_percentile_flags"],
        "stale_route_note": item.get("stale_route_note"),
        "route_note_freshness": item.get("route_note_freshness"),
    }


def build_observations(
    *,
    route_dimension_stats: dict[str, dict[str, Any]],
    groups: dict[str, Any],
    joined: Sequence[dict[str, Any]],
    join_radius_m: float,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    attention_items = [
        item for item in joined if item["semantic_group"] in SEMANTIC_ATTENTION_GROUPS
    ]
    matched_attention_count = sum(
        1 for item in attention_items if item["matched_within_join_radius"]
    )
    if route_dimension_stats["scp"]["max"] == 0 and attention_items:
        observations.append(
            {
                "observation_id": "semantic_scp_not_reflected",
                "severity": "high",
                "summary_zh": "目前 route risk 的 SCP 維度全部為 0，語意危險/注意 CP 尚未進入風險拆解結果。",
                "evidence": {
                    "scp_max": route_dimension_stats["scp"]["max"],
                    "semantic_attention_checkpoint_count": len(attention_items),
                },
            }
        )
    if attention_items:
        observations.append(
            {
                "observation_id": "semantic_route_alignment_coverage",
                "severity": "medium"
                if matched_attention_count < len(attention_items) * 0.5
                else "info",
                "summary_zh": "部分語意 CP 來自 reference tracks，離目前 Overpass route base 很遠；校準時應先分開可對位與不可對位樣本。",
                "evidence": {
                    "join_radius_m": join_radius_m,
                    "matched_attention_count": matched_attention_count,
                    "attention_checkpoint_count": len(attention_items),
                },
            }
        )
    for group_name in ("danger", "technical_caution"):
        summary = groups.get(group_name, {})
        ratios = summary.get("matched_nearest_dimension_ratios", {})
        likely_dimensions = [
            dimension
            for dimension, ratio in ratios.items()
            if ratio.get("above_route_p75_ratio") is not None
            and ratio["above_route_p75_ratio"] >= 0.5
        ]
        if likely_dimensions:
            observations.append(
                {
                    "observation_id": f"{group_name}_possible_dimension_signal",
                    "severity": "info",
                    "summary_zh": f"{group_name} CP 在 {', '.join(likely_dimensions)} 有較常高於整條 route P75 的跡象。",
                    "evidence": {
                        dimension: ratios[dimension]
                        for dimension in likely_dimensions
                    },
                }
            )
    return observations


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def write_diagnostic(diagnostic: dict[str, Any], path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_warning_cp_proposals(diagnostic: dict[str, Any], path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            diagnostic["excluded_extreme_warning_cp_proposals"],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _default_route_risk_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "route_risk.geojson"


def _default_gis_perception_path(workspace: Path) -> Path:
    return workspace / "outputs" / "gis_perception_candidates.json"


def _default_route_note_ln_path(workspace: Path) -> Path:
    return workspace / "outputs" / "route_note_ln_proposals.json"


def _default_output_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "risk_attribution_diagnostic.json"


def _default_warning_cp_output_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "excluded_extreme_warning_cp_proposals.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a candidate-only pretrip risk attribution diagnostic "
            "from semantic route-note CPs and decomposed route-risk dimensions."
        )
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--route-risk", type=Path)
    parser.add_argument("--gis-perception", type=Path)
    parser.add_argument("--route-note-ln-proposals", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--warning-cp-out", type=Path)
    parser.add_argument("--join-radius-m", type=float, default=100.0)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument(
        "--excluded-extreme-percentile",
        type=float,
        default=DEFAULT_EXCLUDED_EXTREME_PERCENTILE,
    )
    parser.add_argument(
        "--max-warning-cp-proposals",
        type=int,
        default=DEFAULT_MAX_WARNING_CP_PROPOSALS,
    )
    args = parser.parse_args(argv)

    route_risk_path = args.route_risk or _default_route_risk_path(args.workspace)
    gis_perception_path = args.gis_perception or _default_gis_perception_path(args.workspace)
    route_note_ln_path = args.route_note_ln_proposals or _default_route_note_ln_path(
        args.workspace
    )
    output_path = args.out or _default_output_path(args.workspace)
    warning_cp_output_path = args.warning_cp_out or _default_warning_cp_output_path(
        args.workspace
    )
    diagnostic = build_risk_attribution_diagnostic(
        route_risk_path=route_risk_path,
        gis_perception_path=gis_perception_path,
        route_note_ln_proposals_path=route_note_ln_path,
        join_radius_m=args.join_radius_m,
        top_n=args.top_n,
        excluded_extreme_percentile=args.excluded_extreme_percentile,
        max_warning_cp_proposals=args.max_warning_cp_proposals,
    )
    diagnostic["outputs"] = {
        "risk_attribution_diagnostic_path": str(output_path),
        "excluded_extreme_warning_cp_proposals_path": str(warning_cp_output_path),
    }
    write_diagnostic(diagnostic, output_path)
    write_warning_cp_proposals(diagnostic, warning_cp_output_path)
    print(f"wrote risk attribution diagnostic to {output_path}")
    print(f"wrote excluded extreme warning CP proposals to {warning_cp_output_path}")
    print(json.dumps(diagnostic["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
