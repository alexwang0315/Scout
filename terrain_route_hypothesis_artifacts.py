"""Deterministic artifact and cache helpers for terrain route hypotheses."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from terrain_route_guidance import TERRAIN_GUIDANCE_COST_MODEL_VERSION
from terrain_route_hypothesis_models import (
    TERRAIN_ROUTE_BAND_MODEL,
    TERRAIN_ROUTE_BAND_SEMANTICS,
    TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
    TERRAIN_ROUTE_PATH_MODEL,
    TerrainRoutingCostConfig,
)


TERRAIN_ROUTE_CACHE_SCHEMA_VERSION = "scout_terrain_route_cache.v0_1"
TERRAIN_ROUTE_CORRIDOR_SEMANTICS = TERRAIN_ROUTE_BAND_SEMANTICS
TERRAIN_ROUTE_SLOPE_FRICTION_EXPRESSION_KIND = "slope_piecewise_friction"
TERRAIN_ROUTE_DRAINAGE_PRESSURE_EXPRESSION_KIND = "drainage_pressure"
TERRAIN_ROUTE_PROFILE_FRICTION_EXPRESSION_KIND = "profile_friction"
TERRAIN_ROUTE_GUIDANCE_FRICTION_EXPRESSION_KIND = "reviewed_guidance_friction"
TERRAIN_ROUTE_CORRIDOR_EXPRESSION_KIND = "symmetric_relative_corridor"
TERRAIN_ROUTE_THRESHOLD_EXPRESSION_KIND = "finite_cell_percentile_mask"
TERRAIN_ROUTE_PATH_OUTSIDE_BAND_EXPRESSION_KIND = "path_outside_percentile_band"
TERRAIN_ROUTE_VISUALIZATION_REVISION = "candidate_corridor_overlay.v0_3"
TERRAIN_ROUTE_PROVENANCE_REVISION = "runtime_versions_and_host.v0_3"

_DECIMAL = r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
_CORRIDOR_EXPRESSION = re.compile(rf"^max\(0,A\+B-({_DECIMAL})\)$")
_THRESHOLD_EXPRESSION = re.compile(rf"^if\(A<=({_DECIMAL}),1,null\(\)\)$")
_PATH_OUTSIDE_BAND_EXPRESSION = "if(!isnull(A)&&isnull(B),1,null())"
_FRICTION_EXPRESSION = re.compile(rf"^({_DECIMAL})\+({_DECIMAL})\*\((.+)\)$")
_DRAINAGE_PRESSURE_EXPRESSION = re.compile(
    rf"^if\(abs\(A\)>=({_DECIMAL}),8,"
    rf"if\(abs\(A\)>=({_DECIMAL}),3,"
    rf"if\(abs\(A\)>=({_DECIMAL}),1,0\)\)\)$"
)
_PROFILE_FRICTION_EXPRESSION = re.compile(rf"^A\+({_DECIMAL})\*B$")
_SIGNED_DECIMAL = rf"-?{_DECIMAL}"
_GUIDANCE_LOCAL_FACTOR = re.compile(
    rf"^if\(sqrt\(pow\(x\(\)-({_SIGNED_DECIMAL}),2\)\+"
    rf"pow\(y\(\)-({_SIGNED_DECIMAL}),2\)\)<=({_DECIMAL}),({_DECIMAL}),1\)$"
)
_MAX_GUIDANCE_COST_MODIFIERS = 16


class TerrainRouteCacheKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TERRAIN_ROUTE_CACHE_SCHEMA_VERSION
    derived_terrain: str = Field(pattern=r"^[a-f0-9]{64}$")
    friction: str = Field(pattern=r"^[a-f0-9]{64}$")
    cost_raster: str = Field(pattern=r"^[a-f0-9]{64}$")
    route_hypothesis: str = Field(pattern=r"^[a-f0-9]{64}$")


def build_terrain_route_source_identity(
    *,
    dem_sha256s: Sequence[str],
    parent_manifest_sha256: str,
) -> dict[str, str]:
    """Build a host-path-independent identity for the authoritative DEM inputs."""

    if not 1 <= len(dem_sha256s) <= 32:
        raise ValueError("terrain route requires one to thirty-two DEM hashes")
    normalized = _validated_hashes(
        {f"dem:{index}": value for index, value in enumerate(sorted(dem_sha256s))}
    )
    parent = _validated_hashes(
        {"terrain_feature_parent_manifest": parent_manifest_sha256}
    )
    return {**normalized, **parent}


def build_terrain_route_resolution_identity(
    source_resolution: dict[str, Any],
) -> dict[str, Any]:
    """Keep resolution semantics while excluding host-specific evidence paths."""

    keys = (
        "status",
        "source_kind",
        "raster_source_count",
        "tile_count",
        "x_m",
        "y_m",
        "resolution_m",
        "crs",
        "adds_source_resolution",
        "parent_dem_sha256",
    )
    identity = {
        key: source_resolution[key]
        for key in keys
        if key in source_resolution
    }
    if not identity:
        raise ValueError("terrain route source resolution identity is unavailable")
    return identity


def build_live_terrain_route_cache_keys(
    *,
    source_hashes: dict[str, str],
    source_resolution: dict[str, Any],
    route_coordinates: Sequence[Sequence[float]],
    analysis_margin_m: float,
    cost_config: TerrainRoutingCostConfig,
    optional_evidence_hashes: dict[str, str] | None = None,
    guidance_review_sha256: str | None = None,
) -> TerrainRouteCacheKeys:
    """Build layered keys so stale DEM or evidence cannot be reused silently."""

    if len(route_coordinates) < 2:
        raise ValueError("terrain route cache requires two route endpoints")
    start = _coordinate(route_coordinates[0])
    destination = _coordinate(route_coordinates[-1])
    margin = float(analysis_margin_m)
    if not math.isfinite(margin) or not 0 <= margin <= 5000:
        raise ValueError("terrain route analysis margin is outside the bounded range")
    normalized_hashes = _validated_hashes(source_hashes)
    evidence_hashes = _validated_hashes(optional_evidence_hashes or {})
    if guidance_review_sha256 is not None and not re.fullmatch(
        r"[a-f0-9]{64}", guidance_review_sha256
    ):
        raise ValueError("terrain guidance review hash is invalid")
    derived = _stable_hash(
        {
            "kind": "derived_terrain",
            "source_hashes": normalized_hashes,
            "source_resolution": source_resolution,
            "start": start,
            "destination": destination,
            "analysis_margin_m": margin,
        }
    )
    friction = _stable_hash(
        {
            "kind": "friction",
            "derived_terrain_key": derived,
            "cost_model": cost_config.model_dump(mode="json"),
        }
    )
    cost_raster = _stable_hash(
        {
            "kind": "cost_raster",
            "friction_key": friction,
            "start": start,
            "destination": destination,
            "movement": {
                "path_model": TERRAIN_ROUTE_PATH_MODEL,
                "path_recipe": "grass:r.walk.coords+grass:r.path",
                "band_model": TERRAIN_ROUTE_BAND_MODEL,
                "band_recipe": "symmetric_grass:r.cost",
                "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
            },
            **(
                {
                    "guidance_review_sha256": guidance_review_sha256,
                    "guidance_cost_model_version": (
                        TERRAIN_GUIDANCE_COST_MODEL_VERSION
                    ),
                }
                if guidance_review_sha256 is not None
                else {}
            ),
        }
    )
    route_hypothesis = _stable_hash(
        {
            "kind": "route_hypothesis",
            "cost_raster_key": cost_raster,
            "algorithm_version": cost_config.algorithm_version,
            "corridor_percentiles": cost_config.corridor_percentiles,
            "corridor_threshold_semantics": TERRAIN_ROUTE_CORRIDOR_SEMANTICS,
            "threshold_comparison_operator": "<=",
            "threshold_tie_handling": "include_all_cells_equal_to_threshold",
            "best_path_union_applied": False,
            "visualization_revision": TERRAIN_ROUTE_VISUALIZATION_REVISION,
            "provenance_revision": TERRAIN_ROUTE_PROVENANCE_REVISION,
            "optional_evidence_hashes": evidence_hashes,
            **(
                {
                    "guidance_review_sha256": guidance_review_sha256,
                    "guidance_cost_model_version": (
                        TERRAIN_GUIDANCE_COST_MODEL_VERSION
                    ),
                }
                if guidance_review_sha256 is not None
                else {}
            ),
        }
    )
    return TerrainRouteCacheKeys(
        derived_terrain=derived,
        friction=friction,
        cost_raster=cost_raster,
        route_hypothesis=route_hypothesis,
    )


def build_slope_friction_expression(config: TerrainRoutingCostConfig) -> str:
    """Compile the typed piecewise slope model to a bounded GRASS expression."""

    unsupported = {
        "roughness_weight": config.roughness_weight,
        "curvature_weight": config.curvature_weight,
        "drainage_weight": config.drainage_weight,
        "ridge_weight": config.ridge_weight,
        "teii_weight": config.teii_weight,
    }
    if any(float(value) != 0.0 for value in unsupported.values()):
        names = ", ".join(name for name, value in unsupported.items() if value)
        raise ValueError(
            "live terrain-route v0.1 supports slope friction only; unsupported weights: "
            + names
        )
    if not 2 <= len(config.slope_cost_bands) <= 12:
        raise ValueError("live slope friction requires two to twelve cost bands")
    terminal = config.slope_cost_bands[-1]
    if terminal.max_degrees is not None:
        raise ValueError("live slope friction requires an open-ended terminal band")
    expression = _format_decimal(terminal.cost)
    for band in reversed(config.slope_cost_bands[:-1]):
        if band.max_degrees is None or band.max_degrees > 90:
            raise ValueError("live slope friction breakpoints must be at most 90 degrees")
        expression = (
            f"if(A<={_format_decimal(band.max_degrees)},"
            f"{_format_decimal(band.cost)},{expression})"
        )
    compiled = (
        f"{_format_decimal(config.base_cost)}+"
        f"{_format_decimal(config.slope_weight)}*({expression})"
    )
    validate_terrain_route_mapcalc_expression(compiled)
    return compiled


def build_drainage_pressure_expression(dem_resolution_m: float) -> str:
    """Compile flow accumulation to bounded, resolution-aware drainage pressure."""

    resolution = float(dem_resolution_m)
    if not math.isfinite(resolution) or not 0 < resolution <= 1_000:
        raise ValueError("DEM resolution is outside drainage-model bounds")
    cell_area_m2 = resolution * resolution
    low_cells = max(1, math.ceil(10_000 / cell_area_m2))
    moderate_cells = max(low_cells + 1, math.ceil(50_000 / cell_area_m2))
    high_cells = max(moderate_cells + 1, math.ceil(250_000 / cell_area_m2))
    expression = (
        f"if(abs(A)>={high_cells},8,"
        f"if(abs(A)>={moderate_cells},3,"
        f"if(abs(A)>={low_cells},1,0)))"
    )
    validate_terrain_route_mapcalc_expression(expression)
    return expression


def build_profile_friction_expression(drainage_penalty_multiplier: float) -> str:
    """Combine slope friction A and drainage pressure B for one route profile."""

    multiplier = float(drainage_penalty_multiplier)
    if not math.isfinite(multiplier) or not 0 <= multiplier <= 100:
        raise ValueError("drainage penalty multiplier is outside bounds")
    expression = f"A+{_format_decimal(multiplier)}*B"
    validate_terrain_route_mapcalc_expression(expression)
    return expression


def build_guidance_friction_expression(
    modifiers: Sequence[Sequence[float]],
) -> str:
    """Apply reviewed-point local preferences without creating zero-cost cells."""

    if not 1 <= len(modifiers) <= _MAX_GUIDANCE_COST_MODIFIERS:
        raise ValueError("reviewed guidance requires one to sixteen cost modifiers")
    factors: list[str] = []
    for modifier in modifiers:
        if len(modifier) != 4:
            raise ValueError("reviewed guidance cost modifier is incomplete")
        x, y, radius_m, multiplier = (float(value) for value in modifier)
        if not all(math.isfinite(value) for value in (x, y)) or any(
            abs(value) > 1_000_000_000 for value in (x, y)
        ):
            raise ValueError("reviewed guidance coordinate is outside bounds")
        if not math.isfinite(radius_m) or not 20 <= radius_m <= 500:
            raise ValueError("reviewed guidance influence radius is outside bounds")
        if not math.isfinite(multiplier) or not 0.5 <= multiplier <= 1:
            raise ValueError("reviewed guidance friction multiplier is outside bounds")
        factors.append(
            "if(sqrt("
            f"pow(x()-{_format_signed_decimal(x)},2)+"
            f"pow(y()-{_format_signed_decimal(y)},2))"
            f"<={_format_decimal(radius_m)},"
            f"{_format_decimal(multiplier)},1)"
        )
    expression = f"A*min(1,{','.join(factors)})"
    validate_terrain_route_mapcalc_expression(expression)
    return expression


def build_relative_corridor_expression(minimum_ab_cost: float) -> str:
    value = _bounded_nonnegative_cost(minimum_ab_cost)
    expression = f"max(0,A+B-{_format_decimal(value)})"
    validate_terrain_route_mapcalc_expression(expression)
    return expression


def build_corridor_threshold_expression(max_relative_cost: float) -> str:
    value = _bounded_nonnegative_cost(max_relative_cost)
    expression = f"if(A<={_format_decimal(value)},1,null())"
    validate_terrain_route_mapcalc_expression(expression)
    return expression


def build_path_outside_band_expression() -> str:
    validate_terrain_route_mapcalc_expression(_PATH_OUTSIDE_BAND_EXPRESSION)
    return _PATH_OUTSIDE_BAND_EXPRESSION


def validate_terrain_route_mapcalc_expression(expression: str) -> str:
    """Accept only expressions emitted by the typed terrain-route compiler."""

    if not isinstance(expression, str) or not 1 <= len(expression) <= 4096:
        raise ValueError("terrain route mapcalc expression length is invalid")
    if expression.startswith("A*min(1,") and expression.endswith(")"):
        body = expression[len("A*min(1,") : -1]
        raw_factors = body.split(",if(")
        factors = [
            raw_factors[0],
            *(f"if({value}" for value in raw_factors[1:]),
        ]
        if not 1 <= len(factors) <= _MAX_GUIDANCE_COST_MODIFIERS:
            raise ValueError("reviewed guidance modifier count is outside bounds")
        for factor in factors:
            match = _GUIDANCE_LOCAL_FACTOR.fullmatch(factor)
            if match is None:
                raise ValueError("reviewed guidance friction expression is malformed")
            x, y, radius_m, multiplier = (float(value) for value in match.groups())
            if not all(math.isfinite(value) for value in (x, y)) or any(
                abs(value) > 1_000_000_000 for value in (x, y)
            ):
                raise ValueError("reviewed guidance coordinate is outside bounds")
            if not 20 <= radius_m <= 500:
                raise ValueError("reviewed guidance influence radius is outside bounds")
            if not 0.5 <= multiplier <= 1:
                raise ValueError("reviewed guidance friction multiplier is outside bounds")
        return TERRAIN_ROUTE_GUIDANCE_FRICTION_EXPRESSION_KIND
    corridor = _CORRIDOR_EXPRESSION.fullmatch(expression)
    if corridor:
        _bounded_nonnegative_cost(float(corridor.group(1)))
        return TERRAIN_ROUTE_CORRIDOR_EXPRESSION_KIND
    threshold = _THRESHOLD_EXPRESSION.fullmatch(expression)
    if threshold:
        _bounded_nonnegative_cost(float(threshold.group(1)))
        return TERRAIN_ROUTE_THRESHOLD_EXPRESSION_KIND
    if expression == _PATH_OUTSIDE_BAND_EXPRESSION:
        return TERRAIN_ROUTE_PATH_OUTSIDE_BAND_EXPRESSION_KIND
    drainage = _DRAINAGE_PRESSURE_EXPRESSION.fullmatch(expression)
    if drainage:
        high, moderate, low = (float(value) for value in drainage.groups())
        if not 1 <= low < moderate < high <= 100_000_000:
            raise ValueError("terrain route drainage thresholds are invalid")
        return TERRAIN_ROUTE_DRAINAGE_PRESSURE_EXPRESSION_KIND
    profile = _PROFILE_FRICTION_EXPRESSION.fullmatch(expression)
    if profile:
        multiplier = float(profile.group(1))
        if not 0 <= multiplier <= 100:
            raise ValueError("terrain route profile friction multiplier is invalid")
        return TERRAIN_ROUTE_PROFILE_FRICTION_EXPRESSION_KIND
    friction = _FRICTION_EXPRESSION.fullmatch(expression)
    if friction:
        base = float(friction.group(1))
        weight = float(friction.group(2))
        if not 0 < base <= 1_000 or not 0 <= weight <= 1_000:
            raise ValueError("terrain route friction coefficients are outside bounds")
        thresholds, costs = _parse_piecewise_friction(friction.group(3))
        if not thresholds or thresholds != sorted(thresholds):
            raise ValueError("terrain route slope thresholds must be increasing")
        if len(set(thresholds)) != len(thresholds) or thresholds[-1] > 90:
            raise ValueError("terrain route slope thresholds are invalid")
        if any(not 0 < cost <= 1_000_000 for cost in costs):
            raise ValueError("terrain route slope costs are outside bounds")
        return TERRAIN_ROUTE_SLOPE_FRICTION_EXPRESSION_KIND
    raise ValueError("expression is not a compiled terrain-route mapcalc expression")


def _parse_piecewise_friction(value: str) -> tuple[list[float], list[float]]:
    thresholds: list[float] = []
    costs: list[float] = []
    remaining = value
    while remaining.startswith("if(A<="):
        body = remaining[6:]
        first_comma = body.find(",")
        second_comma = body.find(",", first_comma + 1)
        if first_comma <= 0 or second_comma <= first_comma + 1 or not body.endswith(")"):
            raise ValueError("terrain route slope expression is malformed")
        threshold_text = body[:first_comma]
        cost_text = body[first_comma + 1 : second_comma]
        if not re.fullmatch(_DECIMAL, threshold_text) or not re.fullmatch(
            _DECIMAL, cost_text
        ):
            raise ValueError("terrain route slope expression contains invalid numbers")
        thresholds.append(float(threshold_text))
        costs.append(float(cost_text))
        remaining = body[second_comma + 1 : -1]
    if not re.fullmatch(_DECIMAL, remaining):
        raise ValueError("terrain route slope expression has an invalid terminal cost")
    costs.append(float(remaining))
    return thresholds, costs


def _bounded_nonnegative_cost(value: float) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1e15:
        raise ValueError("terrain route cost is outside the bounded range")
    return number


def _format_decimal(value: float) -> str:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("terrain route numeric value must be finite and non-negative")
    rendered = f"{number:.12f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _format_signed_decimal(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("terrain route coordinate must be finite")
    rendered = f"{number:.12f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _coordinate(value: Sequence[float]) -> list[float]:
    if len(value) < 2:
        raise ValueError("terrain route endpoint coordinate is incomplete")
    coordinate = [float(value[0]), float(value[1])]
    if not all(math.isfinite(item) for item in coordinate):
        raise ValueError("terrain route endpoint coordinate is not finite")
    return coordinate


def _validated_hashes(values: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in sorted(values.items()):
        digest = str(value).strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError(f"terrain route source hash is invalid: {key}")
        normalized[str(key)] = digest
    return normalized


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "TERRAIN_ROUTE_CACHE_SCHEMA_VERSION",
    "TERRAIN_ROUTE_CORRIDOR_SEMANTICS",
    "TERRAIN_ROUTE_DRAINAGE_PRESSURE_EXPRESSION_KIND",
    "TERRAIN_ROUTE_GUIDANCE_FRICTION_EXPRESSION_KIND",
    "TERRAIN_ROUTE_PROFILE_FRICTION_EXPRESSION_KIND",
    "TERRAIN_ROUTE_PROVENANCE_REVISION",
    "TERRAIN_ROUTE_VISUALIZATION_REVISION",
    "TerrainRouteCacheKeys",
    "build_corridor_threshold_expression",
    "build_drainage_pressure_expression",
    "build_guidance_friction_expression",
    "build_path_outside_band_expression",
    "build_live_terrain_route_cache_keys",
    "build_relative_corridor_expression",
    "build_profile_friction_expression",
    "build_slope_friction_expression",
    "validate_terrain_route_mapcalc_expression",
]
