from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scout_weather_integration import (
    CWA_36H_FORECAST,
    build_route_weather_package,
    fetch_cwa_dataset,
    normalize_cwa_weather_points,
)


DECISIONS = (
    "GO",
    "CONDITIONAL_GO",
    "GUIDED_ONLY",
    "CHANGE_PLAN",
    "DELAY",
    "NO_GO",
    "ESCALATE",
)
FORCE_NAMES = {
    "EXP": ("探索力", "Route Context Intelligence"),
    "RPF": ("自信力", "Readiness & Pace Fit"),
    "PER": ("勇氣力", "Contextual Permissioning"),
    "RTE": ("路線力", "Route Architecture Intelligence"),
    "WTH": ("天氣力", "Weather-to-Decision Intelligence"),
    "NAV": ("地圖力", "Navigation & Terrain Intelligence"),
}
QUESTION_RE = re.compile(
    r"^(\d+)\. \*\*((EXP|RPF|PER|RTE|WTH|NAV)-(\d{3}))\*\* (.+)$"
)
SourceMode = Literal["hardware_live", "synthetic_replay"]
WeatherMode = Literal["live_weather_integration", "deterministic_weather_replay"]
Decision = Literal[
    "GO",
    "CONDITIONAL_GO",
    "GUIDED_ONLY",
    "CHANGE_PLAN",
    "DELAY",
    "NO_GO",
    "ESCALATE",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceArtifactRef(StrictModel):
    role: str
    path: str
    sha256: str


class ScenarioContext(StrictModel):
    scenario_id: str
    source_mode: SourceMode
    project_id: str
    observed_at: str
    boss_point_id: str
    boss_rank: int = Field(ge=1)
    lat: float
    lon: float
    elevation_m: float | None = None
    horizontal_accuracy_m: float = Field(ge=0)
    fix_quality: str
    route_progress_m: float = Field(ge=0)
    distance_to_boss_along_route_m: float = Field(ge=0)
    nearest_cp_id: str | None = None
    nearest_cp_route_progress_m: float | None = Field(default=None, ge=0)
    nearest_route_distance_m: float = Field(ge=0)
    heading_deg: float = Field(ge=0, lt=360)
    travel_direction: str
    risk_terrain_candidate: dict[str, Any]
    source_refs: list[SourceArtifactRef]
    condition_overlay_refs: list[str]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    def to_live_navigation_snapshot(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "observed_at": self.observed_at,
            "lat": self.lat,
            "lon": self.lon,
            "elevation_m": self.elevation_m,
            "source": f"six_forces_scenario:{self.source_mode}",
            "snapshot_status": "synthetic_fixture"
            if self.source_mode == "synthetic_replay"
            else "hardware_live",
            "fix_quality": self.fix_quality,
            "hdop": 0.9 if self.source_mode == "synthetic_replay" else None,
            "horizontal_accuracy_m": self.horizontal_accuracy_m,
            "satellite_count": 12 if self.source_mode == "synthetic_replay" else None,
            "max_cno_dbhz": 38 if self.source_mode == "synthetic_replay" else None,
            "nearest_route_distance_m": self.nearest_route_distance_m,
            "route_progress_m": self.route_progress_m,
            "nearest_cp_id": self.nearest_cp_id,
            "heading_deg": self.heading_deg,
            "course_deg": self.heading_deg,
            "speed_mps": 0.8 if self.source_mode == "synthetic_replay" else None,
            "travel_direction": self.travel_direction,
            "distance_to_boss_along_route_m": self.distance_to_boss_along_route_m,
            "boss_point_id": self.boss_point_id,
            "boss_rank": self.boss_rank,
            "ins_dr_source": "scenario_route_interpolation"
            if self.source_mode == "synthetic_replay"
            else None,
            "confidence": 0.95 if self.source_mode == "synthetic_replay" else None,
            "uncertainty_m": self.horizontal_accuracy_m,
            "last_anchor_at": self.observed_at,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }


class ExpectedEvidenceContract(StrictModel):
    required_context: list[str]
    required_evidence: list[str]
    scenario_identity_match_required: Literal[True] = True
    provenance_required: Literal[True] = True
    freshness_required: bool
    route_intersection_required: bool
    missing_semantics: Literal["unknown_not_permission"] = "unknown_not_permission"
    candidate_status_policy: Literal["candidate_must_remain_unconfirmed"] = (
        "candidate_must_remain_unconfirmed"
    )
    required_answer_elements: list[str] = Field(
        default_factory=lambda: [
            "decisive_evidence",
            "opposing_evidence",
            "evidence_gaps",
            "decision_change_conditions",
            "source_refs",
        ]
    )


class ExpectedDecisionBoundary(StrictModel):
    answer_mode: Literal["decision", "factual_context", "compound"]
    allowed_decisions: list[Decision]
    forbidden_claims: list[str]


class SixForcesCase(StrictModel):
    case_id: str
    question_id: str
    global_ordinal: int = Field(ge=1, le=600)
    force_code: Literal["EXP", "RPF", "PER", "RTE", "WTH", "NAV"]
    force_name: str
    capability_name: str
    force_ordinal: int = Field(ge=1, le=100)
    subsection: str
    question_text: str
    question_source_ref: str
    question_record_sha256: str
    scenario_id: str
    expected_evidence_contract: ExpectedEvidenceContract
    expected_decision_boundary: ExpectedDecisionBoundary
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class WeatherEvidenceReceipt(StrictModel):
    receipt_id: str
    mode: WeatherMode
    dataset_id: str
    requested_at: str
    valid_from: str | None
    valid_to: str | None
    raw_sha256: str
    source_ref: str
    matched_route_segment_ids: list[str]
    freshness: Literal["fresh", "stale", "unknown"]
    external_api_calls_made: bool
    api_key_embedded: Literal[False] = False
    client_api_key_allowed: Literal[False] = False
    route_weather_package: dict[str, Any]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ScenarioDecisionOutput(StrictModel):
    scenario_id: str
    decision: Decision
    decisive_evidence: list[str]
    opposing_evidence: list[str]
    evidence_gaps: list[str]
    decision_change_conditions: list[str]
    source_refs: list[str]
    claims: list[str]


class ScenarioDecisionBatch(StrictModel):
    model_provider: str = Field(min_length=1)
    outputs: list[ScenarioDecisionOutput] = Field(min_length=1)


def generate_boss_approach_anchors(
    workspace_root: Path | str,
    *,
    observed_at: str,
    source_mode: SourceMode = "synthetic_replay",
    approach_distance_m: float = 500.0,
) -> list[ScenarioContext]:
    root = Path(workspace_root).expanduser().resolve()
    project = _read_json(root / "project.json")
    refs = {
        "boss_points": _project_ref(project, "boss_points_ref", "outputs/boss_points.json"),
        "risk_ribbon": _project_ref(project, "risk_ribbon_ref", "outputs/risk/risk_ribbon.geojson"),
        "checkpoints": _project_ref(project, "checkpoint_candidates_ref", "candidates/checkpoints.json"),
        "route_summary": _project_ref(project, "route_summary_ref", "normalized/routes/route_summary.json"),
        "terrain_samples": _project_ref(
            project,
            "terrain_route_samples_ref",
            "outputs/layers/normalized/terrain_route_samples.geojson",
        ),
        "terrain_candidates": _project_ref(
            project,
            "terrain_risk_candidates_ref",
            "outputs/layers/candidates/terrain_risk_candidates.json",
        ),
    }
    paths = {name: _contained_path(root, ref) for name, ref in refs.items()}
    boss_payload = _read_json(paths["boss_points"])
    ribbon_features = _feature_list(_read_json(paths["risk_ribbon"]))
    checkpoints = _list_payload(_read_json(paths["checkpoints"]))
    terrain_features = _feature_list(_read_json(paths["terrain_samples"]))
    terrain_candidates = _list_payload(_read_json(paths["terrain_candidates"]))
    cp_progress = _checkpoint_progress(root, checkpoints)
    artifact_refs = [
        SourceArtifactRef(role=role, path=refs[role], sha256=_sha256(paths[role]))
        for role in refs
    ]
    scenarios: list[ScenarioContext] = []
    for boss in sorted(boss_payload.get("boss_points", []), key=lambda item: item["rank"]):
        boss_progress = float(boss["route_position"]["distance_m"])
        target = boss_progress - approach_distance_m
        if target < 0:
            raise ValueError(f"boss {boss.get('boss_point_id')} is before approach offset")
        ribbon = _covering_feature(ribbon_features, target)
        point, fraction = _interpolate_linestring(ribbon, target)
        terrain = _interpolate_terrain(terrain_features, target)
        nearest_cp = min(cp_progress, key=lambda item: abs(item["route_progress_m"] - target))
        nearest_terrain_candidate = _nearest_candidate(
            terrain_candidates,
            lat=point[0],
            lon=point[1],
        )
        properties = ribbon.get("properties") or {}
        rank = int(boss["rank"])
        scenario_id = (
            f"{project.get('project_id') or root.name}.boss-approach.rank-{rank}.v1"
        )
        scenarios.append(
            ScenarioContext(
                scenario_id=scenario_id,
                source_mode=source_mode,
                project_id=str(project.get("project_id") or root.name),
                observed_at=observed_at,
                boss_point_id=str(boss["boss_point_id"]),
                boss_rank=rank,
                lat=round(point[0], 12),
                lon=round(point[1], 12),
                elevation_m=_rounded(terrain.get("elevation_m"), 3),
                horizontal_accuracy_m=5.0 if source_mode == "synthetic_replay" else 15.0,
                fix_quality=(
                    "synthetic_route_interpolation"
                    if source_mode == "synthetic_replay"
                    else "hardware_snapshot_required"
                ),
                route_progress_m=target,
                distance_to_boss_along_route_m=approach_distance_m,
                nearest_cp_id=nearest_cp["candidate_id"],
                nearest_cp_route_progress_m=round(nearest_cp["route_progress_m"], 3),
                nearest_route_distance_m=0.0,
                heading_deg=round(_feature_heading(ribbon), 6),
                travel_direction="increasing_route_progress",
                risk_terrain_candidate={
                    "ribbon_segment_id": properties.get("segment_id"),
                    "start_distance_m": properties.get("start_distance_m"),
                    "end_distance_m": properties.get("end_distance_m"),
                    "interpolation_fraction": round(fraction, 6),
                    "risk_score": properties.get("rs"),
                    "risk_bucket": properties.get("risk_bucket"),
                    "terrain_sample": terrain,
                    "nearest_warning_candidate": nearest_terrain_candidate,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                source_refs=artifact_refs,
                condition_overlay_refs=[],
            )
        )
    if len(scenarios) != 5:
        raise ValueError(f"expected 5 boss approach scenarios, found {len(scenarios)}")
    return scenarios


def build_weather_evidence_receipt(
    scenarios: list[ScenarioContext],
    *,
    mode: WeatherMode,
    replay_fixture_path: Path | str | None = None,
    fetcher: Callable[..., dict[str, Any]] | None = None,
    requested_at: str | None = None,
    weather_area: str | None = None,
) -> WeatherEvidenceReceipt:
    request_time = requested_at or datetime.now(timezone.utc).isoformat()
    if mode == "deterministic_weather_replay":
        if replay_fixture_path is None:
            raise ValueError("deterministic_weather_replay requires replay_fixture_path")
        fixture_path = Path(replay_fixture_path).expanduser().resolve()
        fixture = _read_json(fixture_path)
        dataset_id = str(fixture.get("dataset_id") or CWA_36H_FORECAST)
        weather_points = fixture.get("weather_points") or []
        warnings = fixture.get("warnings") or []
        raw_sha = _sha256(fixture_path)
        source_ref = fixture_path.as_posix()
        external_api_calls_made = False
        request_time = str(fixture.get("request_time") or request_time)
    else:
        dataset_id = CWA_36H_FORECAST
        payload = (fetcher or fetch_cwa_dataset)(dataset_id)
        raw_sha = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        weather_points = normalize_cwa_weather_points(
            dataset_id,
            payload,
            source_run_id=f"six600.live.{request_time}",
        )
        warnings = []
        source_ref = f"server-side-cwa:{dataset_id}"
        external_api_calls_made = True
    if not isinstance(weather_points, list) or not weather_points:
        raise ValueError("weather mode produced no normalized CWA weather points")
    route_segments = [
        {
            "segmentId": scenario.scenario_id,
            "fromM": scenario.route_progress_m,
            "toM": scenario.route_progress_m + scenario.distance_to_boss_along_route_m,
            "etaFrom": scenario.observed_at,
            "etaTo": scenario.observed_at,
            "township": weather_area,
            "terrainRisk": min(
                1.0,
                float(scenario.risk_terrain_candidate.get("risk_score") or 0) / 100.0,
            ),
        }
        for scenario in scenarios
    ]
    valid_from = min(
        (str(item["validFrom"]) for item in weather_points if item.get("validFrom")),
        default=None,
    )
    valid_to = max(
        (str(item["validTo"]) for item in weather_points if item.get("validTo")),
        default=None,
    )
    package = build_route_weather_package(
        route_id=scenarios[0].project_id,
        route_segments=route_segments,
        weather_points=weather_points,
        warnings=warnings if isinstance(warnings, list) else [],
        generated_at=request_time,
        valid_until=valid_to,
        provider=(
            "server_side_cwa_live"
            if mode == "live_weather_integration"
            else "deterministic_cwa_replay_fixture"
        ),
        source_run_ids=[f"six600.{mode}"],
    )
    package = {
        **package,
        "external_api_calls_made": external_api_calls_made,
        "request_time": request_time,
        "raw_sha256": raw_sha,
        "dataset_id": dataset_id,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    matched = [
        str(segment["segmentId"])
        for segment in package.get("segments", [])
        if any(
            float(segment.get("fromM") or 0) <= scenario.route_progress_m
            <= float(segment.get("toM") or 0)
            for scenario in scenarios
            if scenario.scenario_id == segment.get("segmentId")
        )
    ]
    if len(matched) != len(scenarios):
        raise ValueError("weather package does not intersect every scenario route progress")
    freshness = _freshness(request_time, valid_to)
    return WeatherEvidenceReceipt(
        receipt_id=f"weather.{mode}.{raw_sha[:12]}",
        mode=mode,
        dataset_id=dataset_id,
        requested_at=request_time,
        valid_from=valid_from,
        valid_to=valid_to,
        raw_sha256=raw_sha,
        source_ref=source_ref,
        matched_route_segment_ids=matched,
        freshness=freshness,
        external_api_calls_made=external_api_calls_made,
        route_weather_package=package,
    )


def load_question_templates(corpus_path: Path | str) -> tuple[list[dict[str, Any]], str]:
    path = Path(corpus_path).expanduser().resolve()
    raw = path.read_bytes()
    subsection = ""
    rows: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("### "):
            subsection = line[4:].strip()
            continue
        match = QUESTION_RE.match(line)
        if not match:
            continue
        global_ordinal, question_id, force_code, force_ordinal, question = match.groups()
        rows.append(
            {
                "global_ordinal": int(global_ordinal),
                "question_id": question_id,
                "force_code": force_code,
                "force_ordinal": int(force_ordinal),
                "subsection": subsection,
                "question_text": question,
            }
        )
    _validate_question_rows(rows)
    return rows, hashlib.sha256(raw).hexdigest()


def generate_case_mapping(
    corpus_path: Path | str,
    scenarios: list[ScenarioContext],
) -> tuple[list[SixForcesCase], str]:
    rows, corpus_hash = load_question_templates(corpus_path)
    by_rank = {scenario.boss_rank: scenario for scenario in scenarios}
    cases: list[SixForcesCase] = []
    source_ref = Path(corpus_path).as_posix()
    for row in rows:
        force_code = row["force_code"]
        anchor_rank = ((row["force_ordinal"] - 1) % 5) + 1
        scenario = by_rank[anchor_rank]
        required_context, required_evidence = _case_requirements(force_code)
        answer_mode = _answer_mode(row["question_text"], force_code)
        force_name, capability = FORCE_NAMES[force_code]
        record_hash = hashlib.sha256(
            f"{row['question_id']}\n{row['question_text']}".encode("utf-8")
        ).hexdigest()
        cases.append(
            SixForcesCase(
                case_id=f"six600.{row['question_id']}.{scenario.scenario_id}",
                question_id=row["question_id"],
                global_ordinal=row["global_ordinal"],
                force_code=force_code,
                force_name=force_name,
                capability_name=capability,
                force_ordinal=row["force_ordinal"],
                subsection=row["subsection"],
                question_text=row["question_text"],
                question_source_ref=f"{source_ref}#sha256={corpus_hash}",
                question_record_sha256=record_hash,
                scenario_id=scenario.scenario_id,
                expected_evidence_contract=ExpectedEvidenceContract(
                    required_context=required_context,
                    required_evidence=required_evidence,
                    freshness_required=force_code in {"RPF", "PER", "WTH", "NAV"},
                    route_intersection_required=force_code in {"PER", "RTE", "WTH", "NAV"},
                ),
                expected_decision_boundary=ExpectedDecisionBoundary(
                    answer_mode=answer_mode,
                    allowed_decisions=list(DECISIONS) if answer_mode != "factual_context" else [],
                    forbidden_claims=[
                        "candidate terrain is confirmed現場 truth",
                        "missing context is known",
                        "synthetic scenario is runtime safety truth",
                        "weather implies a fixed timeless answer",
                        "guaranteed safe",
                    ],
                ),
            )
        )
    _validate_case_distribution(cases)
    return cases, corpus_hash


def build_per095_replay_contexts(base: ScenarioContext) -> list[dict[str, Any]]:
    variants = [
        {
            "variant_id": "exposed_strong_wind_shelter_ahead",
            "location_status": "fresh_route_match",
            "exposure_candidate": "exposed_ridge_candidate",
            "wind": {"status": "strong", "provenance": "deterministic_cwa_replay"},
            "sheltered_candidate_ahead_m": 180,
            "flat_sheltered_candidate": False,
            "time_buffer_minutes": 35,
        },
        {
            "variant_id": "sheltered_flat_time_available",
            "location_status": "fresh_route_match",
            "exposure_candidate": "sheltered_flat_candidate",
            "wind": {"status": "moderate", "provenance": "deterministic_cwa_replay"},
            "sheltered_candidate_ahead_m": None,
            "flat_sheltered_candidate": True,
            "time_buffer_minutes": 48,
        },
        {
            "variant_id": "gnss_stale_location_unknown",
            "location_status": "stale_unknown",
            "exposure_candidate": None,
            "wind": {"status": "unknown", "provenance": "missing"},
            "sheltered_candidate_ahead_m": None,
            "flat_sheltered_candidate": None,
            "time_buffer_minutes": None,
        },
    ]
    return [
        {
            "scenario": base.model_copy(
                update={
                    "scenario_id": f"{base.scenario_id}.per095.{item['variant_id']}",
                    "condition_overlay_refs": [f"per095:{item['variant_id']}"],
                    "fix_quality": (
                        "stale_unknown"
                        if item["location_status"] == "stale_unknown"
                        else base.fix_quality
                    ),
                }
            ).model_dump(mode="json"),
            "question_id": "PER-095",
            "question_text": "這裡適合做臨時避風停留，還是需要繼續移動？",
            "condition_overlay": item,
            "deterministic_reference": _per095_reference(item),
            "model_answer": None,
            "model_answer_status": "must_be_supplied_by_replay_model_not_reference",
        }
        for item in variants
    ]


def verify_scenario_decision(
    output: ScenarioDecisionOutput,
    *,
    scenario: ScenarioContext,
    case: SixForcesCase,
) -> dict[str, Any]:
    errors: list[str] = []
    if output.scenario_id != scenario.scenario_id:
        errors.append("scenario_id_mismatch")
    allowed = case.expected_decision_boundary.allowed_decisions
    if allowed and output.decision not in allowed:
        errors.append("decision_outside_allowed_boundary")
    for field in (
        output.decisive_evidence,
        output.opposing_evidence,
        output.evidence_gaps,
        output.decision_change_conditions,
        output.source_refs,
    ):
        if not field:
            errors.append("missing_required_answer_element")
            break
    claims = " ".join(output.claims).lower()
    if scenario.candidate_only and any(
        marker in claims for marker in ("confirmed safe", "confirmed hazard", "已確認安全", "已確認危險")
    ):
        errors.append("candidate_promoted_to_confirmed_truth")
    if scenario.fix_quality == "stale_unknown" and any(
        marker in claims for marker in ("這裡是", "目前位於", "current location is")
    ):
        errors.append("unknown_location_claimed_as_known")
    return {"status": "pass" if not errors else "fail", "errors": errors}


def artifact_statistics(cases: list[SixForcesCase]) -> dict[str, Any]:
    force_counts = Counter(case.force_code for case in cases)
    anchor_force = Counter(
        (case.scenario_id.split("rank-")[1].split(".")[0], case.force_code)
        for case in cases
    )
    return {
        "case_count": len(cases),
        "force_counts": dict(sorted(force_counts.items())),
        "anchor_force_counts": {
            f"rank_{rank}.{force}": count
            for (rank, force), count in sorted(anchor_force.items())
        },
        "unique_question_ids": len({case.question_id for case in cases}),
        "unique_case_ids": len({case.case_id for case in cases}),
    }


def _project_ref(project: dict[str, Any], key: str, fallback: str) -> str:
    value = project.get(key)
    return str(value) if isinstance(value, str) and value else fallback


def _contained_path(root: Path, ref: str) -> Path:
    root = root.resolve()
    referenced = Path(ref)
    candidate = referenced if referenced.is_absolute() else root / referenced
    try:
        candidate.resolve().relative_to(root)
    except ValueError:
        workspace_roots = {
            "candidates",
            "inbox",
            "normalized",
            "outputs",
            "reviews",
            "sources",
        }
        try:
            start = next(
                index
                for index, part in enumerate(referenced.parts)
                if part in workspace_roots
            )
        except StopIteration as exc:
            raise ValueError(f"workspace artifact escapes root: {ref}") from exc
        candidate = root.joinpath(*referenced.parts[start:])
    if candidate.is_symlink():
        raise ValueError(f"missing or invalid workspace artifact: {ref}")
    path = candidate.resolve()
    path.relative_to(root)
    if not path.is_file():
        raise ValueError(f"missing or invalid workspace artifact: {ref}")
    return path


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _feature_list(value: Any) -> list[dict[str, Any]]:
    features = value.get("features") if isinstance(value, dict) else None
    return [item for item in features or [] if isinstance(item, dict)]


def _list_payload(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _covering_feature(features: list[dict[str, Any]], target: float) -> dict[str, Any]:
    matches = [
        feature
        for feature in features
        if float((feature.get("properties") or {}).get("start_distance_m", -1))
        <= target
        <= float((feature.get("properties") or {}).get("end_distance_m", -1))
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one risk ribbon segment at {target}, found {len(matches)}")
    return matches[0]


def _interpolate_linestring(feature: dict[str, Any], target: float) -> tuple[tuple[float, float], float]:
    properties = feature["properties"]
    start = float(properties["start_distance_m"])
    end = float(properties["end_distance_m"])
    coordinates = feature["geometry"]["coordinates"]
    if end <= start or len(coordinates) < 2:
        raise ValueError("invalid risk ribbon interpolation segment")
    fraction = (target - start) / (end - start)
    lon = float(coordinates[0][0]) + fraction * (
        float(coordinates[-1][0]) - float(coordinates[0][0])
    )
    lat = float(coordinates[0][1]) + fraction * (
        float(coordinates[-1][1]) - float(coordinates[0][1])
    )
    return (lat, lon), fraction


def _feature_heading(feature: dict[str, Any]) -> float:
    coordinates = feature["geometry"]["coordinates"]
    lon1, lat1 = map(float, coordinates[0][:2])
    lon2, lat2 = map(float, coordinates[-1][:2])
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta = math.radians(lon2 - lon1)
    y = math.sin(delta) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _interpolate_terrain(features: list[dict[str, Any]], target: float) -> dict[str, Any]:
    ordered = sorted(
        features,
        key=lambda item: float((item.get("properties") or {}).get("distance_m", math.inf)),
    )
    lower = max(
        (item for item in ordered if float(item["properties"]["distance_m"]) <= target),
        key=lambda item: float(item["properties"]["distance_m"]),
    )
    upper = min(
        (item for item in ordered if float(item["properties"]["distance_m"]) >= target),
        key=lambda item: float(item["properties"]["distance_m"]),
    )
    low, high = lower["properties"], upper["properties"]
    low_distance, high_distance = float(low["distance_m"]), float(high["distance_m"])
    fraction = 0.0 if high_distance == low_distance else (target - low_distance) / (high_distance - low_distance)
    numeric_keys = ("elevation_m", "pretrip_risk", "lec", "sri", "tri", "teii_20m", "scp")
    result = {
        key: round(float(low[key]) + fraction * (float(high[key]) - float(low[key])), 4)
        for key in numeric_keys
        if low.get(key) is not None and high.get(key) is not None
    }
    return {
        **result,
        "lower_sample_id": low.get("sample_id") or low.get("candidate_id"),
        "upper_sample_id": high.get("sample_id") or high.get("candidate_id"),
        "source_refs": low.get("source_refs") or [],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _checkpoint_progress(root: Path, checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gpx_ref = next(
        (
            item.get("uri")
            for checkpoint in checkpoints
            for item in checkpoint.get("provenance", [])
            if isinstance(item, dict) and item.get("uri")
        ),
        None,
    )
    if not isinstance(gpx_ref, str):
        raise ValueError("checkpoint provenance does not identify filtered GPX")
    gpx_path = _contained_path(root, gpx_ref)
    points = _gpx_points(gpx_path)
    cumulative = [0.0]
    for previous, current in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + _haversine_m(previous[0], previous[1], current[0], current[1]))
    joined = []
    for checkpoint in checkpoints:
        index = checkpoint.get("route_point_index")
        if isinstance(index, int) and 0 <= index < len(cumulative):
            joined.append(
                {
                    "candidate_id": str(checkpoint.get("candidate_id")),
                    "route_progress_m": cumulative[index],
                }
            )
    if not joined:
        raise ValueError("no checkpoints could be joined to canonical route progress")
    return joined


def _gpx_points(path: Path) -> list[tuple[float, float]]:
    root = ET.parse(path).getroot()
    points = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "trkpt":
            continue
        points.append((float(element.attrib["lat"]), float(element.attrib["lon"])))
    return points


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    d_lat, d_lon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    value = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(d_lon / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(value))


def _nearest_candidate(candidates: list[dict[str, Any]], *, lat: float, lon: float) -> dict[str, Any] | None:
    with_coordinates = [
        item for item in candidates if item.get("lat") is not None and item.get("lon") is not None
    ]
    if not with_coordinates:
        return None
    item = min(
        with_coordinates,
        key=lambda candidate: _haversine_m(lat, lon, float(candidate["lat"]), float(candidate["lon"])),
    )
    return {
        "candidate_id": item.get("candidate_id"),
        "distance_m": round(_haversine_m(lat, lon, float(item["lat"]), float(item["lon"])), 3),
        "risk_dimensions": item.get("risk_dimensions"),
        "source_refs": item.get("source_refs") or [],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _rounded(value: Any, digits: int) -> float | None:
    return round(float(value), digits) if value is not None else None


def _validate_question_rows(rows: list[dict[str, Any]]) -> None:
    if len(rows) != 600 or len({row["question_id"] for row in rows}) != 600:
        raise ValueError("six-forces corpus must contain 600 unique question IDs")
    if [row["global_ordinal"] for row in rows] != list(range(1, 601)):
        raise ValueError("six-forces global ordinals must be 1..600")
    counts = Counter(row["force_code"] for row in rows)
    if counts != Counter({force: 100 for force in FORCE_NAMES}):
        raise ValueError(f"invalid force distribution: {dict(counts)}")


def _case_requirements(force: str) -> tuple[list[str], list[str]]:
    common_context = [
        "scenario_location",
        "route_progress_and_direction",
        "current_time",
        "workspace_total_info",
    ]
    evidence = {
        "EXP": ["route_context", "current_position", "source_provenance"],
        "RPF": ["pace_and_body_state", "route_demand", "time_buffer", "device_state"],
        "PER": ["current_position", "terrain_candidate", "weather", "time_buffer", "body_device_state"],
        "RTE": ["canonical_route", "checkpoint_graph", "boss_points", "retreat_candidates"],
        "WTH": ["normalized_cwa", "valid_time", "freshness", "route_intersection", "weather_provenance"],
        "NAV": ["gnss_quality", "canonical_route_match", "heading", "terrain_candidate", "offline_navigation_state"],
    }
    return common_context, evidence[force]


def _answer_mode(question: str, force: str) -> Literal["decision", "factual_context", "compound"]:
    decision_terms = ("適合", "支持", "應該", "要不要", "能不能", "可以", "是否", "決策", "繼續", "撤退", "折返", "出發", "改走", "延期")
    if any(term in question for term in decision_terms):
        return "decision" if force in {"PER", "WTH"} else "compound"
    return "factual_context" if force == "EXP" else "compound"


def _validate_case_distribution(cases: list[SixForcesCase]) -> None:
    stats = artifact_statistics(cases)
    if stats["case_count"] != 600 or stats["unique_case_ids"] != 600:
        raise ValueError("case mapping must contain 600 unique cases")
    if set(stats["force_counts"].values()) != {100}:
        raise ValueError("each force must contain 100 cases")
    if set(stats["anchor_force_counts"].values()) != {20}:
        raise ValueError("each anchor must receive 20 questions from each force")


def _freshness(request_time: str, valid_to: str | None) -> Literal["fresh", "stale", "unknown"]:
    requested = _parse_datetime(request_time)
    valid = _parse_datetime(valid_to)
    if requested is None or valid is None:
        return "unknown"
    return "fresh" if requested <= valid else "stale"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _per095_reference(overlay: dict[str, Any]) -> dict[str, Any]:
    if overlay["location_status"] == "stale_unknown":
        decision, permission = "DELAY", "location_unknown_no_here_claim"
    elif overlay["wind"]["status"] == "strong" and overlay.get("sheltered_candidate_ahead_m"):
        decision, permission = "CHANGE_PLAN", "do_not_hold_here_move_to_candidate"
    elif overlay.get("flat_sheltered_candidate") and float(overlay.get("time_buffer_minutes") or 0) >= 20:
        decision, permission = "CONDITIONAL_GO", "bounded_timed_hold"
    else:
        decision, permission = "NO_GO", "no_hold_permission"
    return {
        "decision": decision,
        "permission": permission,
        "reference_only": True,
        "must_not_be_used_as_model_answer": True,
    }
