from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_RUDY_LIKE_GPX = Path(
    "/Users/alexwang0315/downloads/6966d6fa4d9d9652b2da064c7345fb22_p.gpx"
)


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
) -> RouteNoteCandidateSet:
    source_path = Path(gpx_path).expanduser()
    root = ET.parse(source_path).getroot()
    namespace = _namespace(root.tag)
    waypoints = root.findall(f".//{namespace}wpt")
    candidates = tuple(
        candidate
        for index, waypoint in enumerate(waypoints)
        if (candidate := _route_note_candidate(index, waypoint, namespace)) is not None
    )
    categories = Counter(candidate.note_category for candidate in candidates)
    return RouteNoteCandidateSet(
        artifact_id=f"route_note_candidates.{project_id}.rudy_like_gpx.v0",
        project_id=project_id,
        source_artifact_id=source_artifact_id,
        source_uri=source_path.as_posix(),
        source_sha256=_sha256_file(source_path),
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
        ),
        boundary=RouteNoteBoundary(
            notes=(
                "GPX waypoint name/cmt/desc fields are treated as route-note candidates.",
                "These notes can seed future Ln coverage after human review; they are not ObservedFact or runtime warnings in this slice.",
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
) -> RouteNoteCandidate | None:
    name = _child_text(waypoint, namespace, "name")
    cmt = _child_text(waypoint, namespace, "cmt")
    desc = _child_text(waypoint, namespace, "desc")
    normalized_note = _normalize_note(name, cmt, desc)
    if not normalized_note:
        return None
    category = _classify_note(normalized_note)
    return RouteNoteCandidate(
        candidate_id=f"route_note.rudy_like_gpx.wpt_{index:03d}",
        source_waypoint_index=index,
        lat=float(waypoint.attrib["lat"]),
        lon=float(waypoint.attrib["lon"]),
        ele_m=_optional_float(_child_text(waypoint, namespace, "ele")),
        time=_child_text(waypoint, namespace, "time") or None,
        name=name,
        cmt=cmt,
        desc=desc,
        normalized_note=normalized_note,
        note_category=category,
        potential_ln_signal=category in {"hazard_hint", "route_condition_hint"},
        source_fields_present=tuple(
            field
            for field, value in (("name", name), ("cmt", cmt), ("desc", desc))
            if value
        ),
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
    if any(token in note for token in ("危險", "崩塌", "勿", "小心", "架繩", "斷崖")):
        return "hazard_hint"
    if any(token in note for token in ("營地", "C1", "水塘", "水源", "黑水")):
        return "camp_or_water_hint"
    if any(token in note for token in ("有路", "路徑", "好走", "腰繞", "上切", "下切", "獸俓")):
        return "route_condition_hint"
    if any(token in note for token in ("峰", "山", "鞍", "岔", "稜")):
        return "landmark_hint"
    return "uncategorized_note"


def _optional_float(value: str) -> float | None:
    if not value:
        return None
    parsed = float(value)
    return parsed if parsed != 0.0 else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
