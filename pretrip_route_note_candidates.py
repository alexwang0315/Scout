from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_RUDY_LIKE_GPX = Path(
    "/Users/alexwang0315/downloads/6966d6fa4d9d9652b2da064c7345fb22_p.gpx"
)
ROUTE_NOTE_STALE_AFTER_DAYS = 365 * 5
ROUTE_NOTE_AGING_AFTER_DAYS = 365 * 2


class RouteNoteModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteNoteCandidate(RouteNoteModel):
    candidate_id: str
    source_waypoint_index: int = Field(ge=0)
    lat: float
    lon: float
    ele_m: float | None = None
    time: str | None = None
    name: str = ""
    cmt: str = ""
    desc: str = ""
    normalized_note: str
    note_category: Literal[
        "hazard_hint",
        "route_condition_hint",
        "camp_or_water_hint",
        "landmark_hint",
        "uncategorized_note",
    ]
    potential_ln_signal: bool = False
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_attribution: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    extractor_version: str = "pretrip_route_note_candidates.v0"
    extractor_method: str = "pretrip_route_note_candidates.build_route_note_candidates_from_gpx"
    pydantic_ai_prompt_version: str = "deterministic_schema_ready.no_live_model.v0"
    model_output_sha256: str = "manual_fixture_no_model_hash"
    model_output_summary: str = "manual fixture route-note classification"
    confidence: Literal["low", "medium", "high", "unknown"] = "medium"
    stale_risk: Literal["unknown", "low", "medium", "high"] = "unknown"
    review_state: Literal["needs_review"] = "needs_review"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    route_note_age_days: int | None = None
    route_note_freshness: Literal["unknown", "recent", "aging", "stale"] = "unknown"
    stale_route_note: bool = False
    scout_interpretation: Literal["ModelInterpretation"] = "ModelInterpretation"
    requires_human_review: Literal[True] = True
    observed_fact_candidate: Literal[False] = False
    derived_measurement_candidate: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False
    source_fields_present: tuple[str, ...] = Field(default_factory=tuple)


class RouteNoteCounts(RouteNoteModel):
    waypoint_count: int = Field(ge=0)
    note_candidate_count: int = Field(ge=0)
    hazard_hint_count: int = Field(ge=0)
    route_condition_hint_count: int = Field(ge=0)
    camp_or_water_hint_count: int = Field(ge=0)
    landmark_hint_count: int = Field(ge=0)
    potential_ln_signal_count: int = Field(ge=0)
    route_note_time_unknown_count: int = Field(default=0, ge=0)
    stale_route_note_count: int = Field(default=0, ge=0)
    observed_fact_count: Literal[0] = 0
    raw_payload_count: Literal[0] = 0


class RouteNoteBoundary(RouteNoteModel):
    extracted_from_gpx_waypoints: Literal[True] = True
    source_fields: tuple[Literal["name", "cmt", "desc"], ...] = ("name", "cmt", "desc")
    candidate_only: Literal[True] = True
    scout_interpretation_only: Literal[True] = True
    requires_human_review_before_ln_upgrade: Literal[True] = True
    observed_fact_allowed: Literal[False] = False
    derived_measurement_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class RouteNoteCandidateSet(RouteNoteModel):
    artifact_id: str
    artifact_kind: Literal["pretrip_route_note_candidates"] = "pretrip_route_note_candidates"
    project_id: str
    source_artifact_id: str
    source_uri: str
    source_sha256: str
    status: Literal["candidate_only"] = "candidate_only"
    counts: RouteNoteCounts
    boundary: RouteNoteBoundary
    candidates: tuple[RouteNoteCandidate, ...]
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def enforce_counts(self) -> "RouteNoteCandidateSet":
        categories = Counter(candidate.note_category for candidate in self.candidates)
        if self.counts.note_candidate_count != len(self.candidates):
            raise ValueError("note_candidate_count must match candidates")
        if self.counts.hazard_hint_count != categories["hazard_hint"]:
            raise ValueError("hazard_hint_count must match candidates")
        if self.counts.route_condition_hint_count != categories["route_condition_hint"]:
            raise ValueError("route_condition_hint_count must match candidates")
        if self.counts.camp_or_water_hint_count != categories["camp_or_water_hint"]:
            raise ValueError("camp_or_water_hint_count must match candidates")
        if self.counts.landmark_hint_count != categories["landmark_hint"]:
            raise ValueError("landmark_hint_count must match candidates")
        ln_count = sum(1 for candidate in self.candidates if candidate.potential_ln_signal)
        if self.counts.potential_ln_signal_count != ln_count:
            raise ValueError("potential_ln_signal_count must match candidates")
        unknown_count = sum(
            1 for candidate in self.candidates
            if candidate.route_note_freshness == "unknown"
        )
        if self.counts.route_note_time_unknown_count != unknown_count:
            raise ValueError("route_note_time_unknown_count must match candidates")
        stale_count = sum(1 for candidate in self.candidates if candidate.stale_route_note)
        if self.counts.stale_route_note_count != stale_count:
            raise ValueError("stale_route_note_count must match candidates")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_route_note_candidates_from_gpx(
    gpx_path: Path | str = DEFAULT_RUDY_LIKE_GPX,
    *,
    project_id: str = "chilai_nanhua_day1",
    source_artifact_id: str = "source.comparison.rudy_like_gpx",
    source_key: str = "rudy_like_gpx",
    artifact_version: str = "v0",
    freshness_as_of: str | datetime | None = None,
) -> RouteNoteCandidateSet:
    source_path = Path(gpx_path).expanduser()
    root = ET.parse(source_path).getroot()
    namespace = _namespace(root.tag)
    waypoints = root.findall(f".//{namespace}wpt")
    as_of = _freshness_as_of(freshness_as_of)
    source_sha256 = _sha256_file(source_path)
    candidates = tuple(
        candidate
        for index, waypoint in enumerate(waypoints)
        if (
            candidate := _route_note_candidate(
                index,
                waypoint,
                namespace,
                source_key,
                source_artifact_id=source_artifact_id,
                source_sha256=source_sha256,
                freshness_as_of=as_of,
            )
        )
        is not None
    )
    categories = Counter(candidate.note_category for candidate in candidates)
    return RouteNoteCandidateSet(
        artifact_id=f"route_note_candidates.{project_id}.{source_key}.{artifact_version}",
        project_id=project_id,
        source_artifact_id=source_artifact_id,
        source_uri=source_path.as_posix(),
        source_sha256=source_sha256,
        counts=RouteNoteCounts(
            waypoint_count=len(waypoints),
            note_candidate_count=len(candidates),
            hazard_hint_count=categories["hazard_hint"],
            route_condition_hint_count=categories["route_condition_hint"],
            camp_or_water_hint_count=categories["camp_or_water_hint"],
            landmark_hint_count=categories["landmark_hint"],
            potential_ln_signal_count=sum(
                1 for candidate in candidates if candidate.potential_ln_signal
            ),
            route_note_time_unknown_count=sum(
                1 for candidate in candidates
                if candidate.route_note_freshness == "unknown"
            ),
            stale_route_note_count=sum(
                1 for candidate in candidates if candidate.stale_route_note
            ),
        ),
        boundary=RouteNoteBoundary(
            notes=(
                "GPX waypoint name/cmt/desc fields are treated as route-note candidates.",
                "These notes can seed future Ln coverage after human review; they are not ObservedFact or runtime warnings in this slice.",
                "Route note freshness（路線註記新鮮度）is flagged from waypoint time when available; old notes remain evidence but need stronger review.",
                "The fixture stores extracted note metadata only and does not version the raw GPX.",
            ),
        ),
        candidates=candidates,
        notes=(
            "Route notes from a similar Rudy Map GPX are comparison evidence, not authoritative mission truth.",
            "Recent hiker descriptions may be richer than static map data and should remain review-gated before promotion.",
        ),
    )


def load_route_note_candidates(path: Path | str) -> RouteNoteCandidateSet:
    return RouteNoteCandidateSet.model_validate_json(Path(path).read_text(encoding="utf-8"))


def route_note_candidates_to_json(candidate_set: RouteNoteCandidateSet) -> str:
    return candidate_set.to_json()


def _route_note_candidate(
    index: int,
    waypoint: ET.Element,
    namespace: str,
    source_key: str,
    *,
    source_artifact_id: str,
    source_sha256: str,
    freshness_as_of: datetime,
) -> RouteNoteCandidate | None:
    name = _child_text(waypoint, namespace, "name")
    cmt = _child_text(waypoint, namespace, "cmt")
    desc = _child_text(waypoint, namespace, "desc")
    normalized_note = _normalize_note(name, cmt, desc)
    if not normalized_note:
        return None
    category = _classify_note(normalized_note)
    waypoint_time = _child_text(waypoint, namespace, "time") or None
    freshness = _route_note_freshness(waypoint_time, freshness_as_of=freshness_as_of)
    source_fields_present = tuple(
        field
        for field, value in (("name", name), ("cmt", cmt), ("desc", desc))
        if value
    )
    candidate_id = f"route_note.{source_key}.wpt_{index:03d}"
    confidence = _route_note_confidence(category, source_fields_present)
    stale_risk = _stale_risk_from_freshness(freshness["freshness"])
    model_output_summary = (
        f"{category}; potential_ln_signal={category in {'hazard_hint', 'route_condition_hint'}}; "
        f"freshness={freshness['freshness']}"
    )
    return RouteNoteCandidate(
        candidate_id=candidate_id,
        source_waypoint_index=index,
        lat=float(waypoint.attrib["lat"]),
        lon=float(waypoint.attrib["lon"]),
        ele_m=_optional_float(_child_text(waypoint, namespace, "ele")),
        time=waypoint_time,
        name=name,
        cmt=cmt,
        desc=desc,
        normalized_note=normalized_note,
        note_category=category,
        potential_ln_signal=category in {"hazard_hint", "route_condition_hint"},
        source_refs=(source_artifact_id,),
        source_attribution=(
            {
                "source_kind": "gpx_route_note",
                "source_ref": source_artifact_id,
                "source_sha256": source_sha256,
                "source_key": source_key,
                "source_waypoint_index": index,
                "source_fields_present": source_fields_present,
                "extractor_version": "pretrip_route_note_candidates.v0",
                "extractor_method": "pretrip_route_note_candidates.build_route_note_candidates_from_gpx",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ),
        model_output_sha256=_sha256_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "normalized_note": normalized_note,
                    "note_category": category,
                    "potential_ln_signal": category
                    in {"hazard_hint", "route_condition_hint"},
                    "route_note_freshness": freshness["freshness"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
        model_output_summary=model_output_summary,
        confidence=confidence,
        stale_risk=stale_risk,
        route_note_age_days=freshness["age_days"],
        route_note_freshness=freshness["freshness"],
        stale_route_note=freshness["stale"],
        source_fields_present=source_fields_present,
    )


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", maxsplit=1)[0] + "}"
    return ""


def _child_text(parent: ET.Element, namespace: str, child: str) -> str:
    element = parent.find(f"{namespace}{child}")
    return (element.text or "").strip() if element is not None and element.text else ""


def _normalize_note(*values: str) -> str:
    unique_values: list[str] = []
    for value in values:
        cleaned = " ".join(value.split())
        if cleaned and cleaned not in unique_values and not _looks_like_datetime(cleaned):
            unique_values.append(cleaned)
    return " | ".join(unique_values)


def _looks_like_datetime(value: str) -> bool:
    return len(value) >= 19 and value[4:5] == "-" and value[13:14] == ":"


def _classify_note(note: str) -> str:
    if any(token in note for token in ("危險", "勿", "小心", "架繩", "斷崖")):
        return "hazard_hint"
    if any(token in note for token in ("營地", "C1", "水塘", "水源", "黑水")):
        return "camp_or_water_hint"
    if any(
        token in note
        for token in (
            "有路",
            "路跡",
            "路徑",
            "好走",
            "茂密",
            "林相",
            "芒草",
            "箭竹",
            "腰繞",
            "高繞",
            "低繞",
            "繞路",
            "上切",
            "下切",
            "獸俓",
        )
    ):
        return "route_condition_hint"
    if any(token in note for token in ("崩塌", "崩壁")):
        return "hazard_hint"
    if any(token in note for token in ("峰", "山", "鞍", "岔", "稜")):
        return "landmark_hint"
    return "uncategorized_note"


def _optional_float(value: str) -> float | None:
    if not value:
        return None
    parsed = float(value)
    return parsed if parsed != 0.0 else None


def _freshness_as_of(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = _parse_gpx_time(value)
        if parsed is None:
            raise ValueError(f"invalid freshness_as_of datetime: {value}")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _route_note_freshness(
    waypoint_time: str | None,
    *,
    freshness_as_of: datetime,
) -> dict[str, object]:
    parsed = _parse_gpx_time(waypoint_time)
    if parsed is None:
        return {"age_days": None, "freshness": "unknown", "stale": False}
    age_days = max(0, (freshness_as_of - parsed).days)
    if age_days >= ROUTE_NOTE_STALE_AFTER_DAYS:
        return {"age_days": age_days, "freshness": "stale", "stale": True}
    if age_days >= ROUTE_NOTE_AGING_AFTER_DAYS:
        return {"age_days": age_days, "freshness": "aging", "stale": False}
    return {"age_days": age_days, "freshness": "recent", "stale": False}


def _route_note_confidence(category: str, source_fields_present: tuple[str, ...]) -> str:
    if category == "uncategorized_note":
        return "low"
    if len(source_fields_present) >= 2:
        return "medium"
    return "low"


def _stale_risk_from_freshness(freshness: str) -> str:
    if freshness == "stale":
        return "high"
    if freshness == "aging":
        return "medium"
    if freshness == "recent":
        return "low"
    return "unknown"


def _parse_gpx_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
