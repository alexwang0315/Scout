from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoutAgentKbModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutAgentKbBoundary(ScoutAgentKbModel):
    offline_only: bool = True
    local_evidence_only: bool = True
    runtime_safety_truth: bool = False
    live_safety_api_calls_allowed: bool = False
    phase1_safety_mutation_allowed: bool = False
    remote_outbound_send_allowed: bool = False
    hardware_control_allowed: bool = False
    raw_payloads_embedded: bool = False


class ScoutAgentKbRecord(ScoutAgentKbModel):
    record_id: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    boundary: ScoutAgentKbBoundary = Field(default_factory=ScoutAgentKbBoundary)


class ScoutAgentKbIndex(ScoutAgentKbModel):
    artifact_kind: str = "scout_local_evidence_index"
    schema_version: str = "0.1.0"
    project_id: str = Field(min_length=1)
    source_root: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    records: list[ScoutAgentKbRecord] = Field(default_factory=list)
    boundary: ScoutAgentKbBoundary = Field(default_factory=ScoutAgentKbBoundary)

    @model_validator(mode="after")
    def enforce_record_count(self) -> "ScoutAgentKbIndex":
        if self.record_count != len(self.records):
            raise ValueError("record_count must match records")
        _assert_no_forbidden_fragments(self.model_dump(mode="json"))
        return self


class ScoutAgentKbQueryResult(ScoutAgentKbModel):
    artifact_kind: str = "scout_local_evidence_query_result"
    schema_version: str = "0.1.0"
    project_id: str
    query: str
    result_count: int = Field(ge=0)
    results: list[dict[str, Any]]
    searched_record_count: int = Field(ge=0)
    boundary: ScoutAgentKbBoundary = Field(default_factory=ScoutAgentKbBoundary)


def build_local_evidence_index(project_root: Path | str) -> ScoutAgentKbIndex:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = _require_project_id(project)
    records: list[ScoutAgentKbRecord] = []
    records.extend(_route_records(root, project))
    records.extend(_list_records(root, project, "checkpoint_candidates_ref", "pretrip_checkpoint_candidate"))
    records.extend(_list_records(root, project, "segment_candidates_ref", "pretrip_segment_candidate"))
    records.extend(_route_note_records(root, project))
    records.extend(_review_queue_records(root, project))
    records.extend(_spatial_imprint_records(root, project))
    records.extend(_optional_summary_record(root, project, "calibrated_risk_heatmap_metadata_ref", "pretrip_risk_heatmap_metadata"))
    records.extend(_optional_summary_record(root, project, "spatial_imprint_manifest_ref", "pretrip_spatial_imprint_manifest"))
    return ScoutAgentKbIndex(
        project_id=project_id,
        source_root=str(root),
        record_count=len(records),
        records=records,
    )


def load_local_evidence_index(path: Path | str) -> ScoutAgentKbIndex:
    return ScoutAgentKbIndex.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_local_evidence_index(
    project_root: Path | str,
    output_path: Path | str,
) -> ScoutAgentKbIndex:
    index = build_local_evidence_index(project_root)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(index.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index


def query_local_evidence_index(
    index: ScoutAgentKbIndex,
    *,
    query: str,
    limit: int = 8,
    evidence_types: set[str] | None = None,
) -> ScoutAgentKbQueryResult:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("kb query must not be blank")
    tokens = _tokens(normalized_query)
    scored = []
    for record in index.records:
        if evidence_types and record.evidence_type not in evidence_types:
            continue
        score = _score_record(record, normalized_query, tokens)
        if score <= 0:
            continue
        scored.append((score, record))
    scored.sort(key=lambda item: (-item[0], item[1].evidence_type, item[1].record_id))
    results = [
        {
            "score": score,
            "record_id": record.record_id,
            "evidence_type": record.evidence_type,
            "source_path": record.source_path,
            "title": record.title,
            "snippet": _snippet(record.text, normalized_query, tokens),
            "tags": record.tags,
            "metadata": record.metadata,
            "boundary": record.boundary.model_dump(mode="json"),
        }
        for score, record in scored[: max(0, limit)]
    ]
    return ScoutAgentKbQueryResult(
        project_id=index.project_id,
        query=normalized_query,
        result_count=len(results),
        results=results,
        searched_record_count=len(index.records),
    )


def query_project_local_evidence(
    project_root: Path | str,
    *,
    query: str,
    limit: int = 8,
    evidence_types: set[str] | None = None,
) -> ScoutAgentKbQueryResult:
    return query_local_evidence_index(
        build_local_evidence_index(project_root),
        query=query,
        limit=limit,
        evidence_types=evidence_types,
    )


def _route_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("route_summary_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "route_summary_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    text = " ".join(
        str(value)
        for value in (
            payload.get("route_name"),
            payload.get("artifact_id"),
            payload.get("distance_m"),
            payload.get("elevation_min_m"),
            payload.get("elevation_max_m"),
        )
        if value is not None
    )
    return [
        _record(
            record_id=str(payload.get("artifact_id") or "route_summary"),
            evidence_type="pretrip_route_summary",
            source_path=str(ref),
            title=str(payload.get("route_name") or "Route Summary"),
            text=text or "Route Summary",
            tags=["route"],
            metadata={
                "distance_m": payload.get("distance_m"),
                "point_count": payload.get("point_count"),
            },
        )
    ]


def _list_records(
    root: Path,
    project: dict[str, Any],
    project_ref_key: str,
    evidence_type: str,
) -> list[ScoutAgentKbRecord]:
    ref = project.get(project_ref_key)
    if not ref:
        return []
    path = _project_path(root, str(ref), project_ref_key)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else payload.get("items", [])
    if not isinstance(items, list):
        return []
    records = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        record_id = (
            item.get("candidate_id")
            or item.get("checkpoint_id")
            or item.get("segment_id")
            or f"{evidence_type}.{index:05d}"
        )
        title = str(item.get("label") or item.get("name") or record_id)
        text = _compact_text(
            item,
            include_keys=(
                "label",
                "name",
                "summary",
                "checkpoint_type",
                "segment_type",
                "review_state",
            ),
        )
        records.append(
            _record(
                record_id=str(record_id),
                evidence_type=evidence_type,
                source_path=str(ref),
                title=title,
                text=text or title,
                tags=[str(item.get("checkpoint_type") or item.get("segment_type") or evidence_type)],
                metadata={
                    "index": index,
                    "review_state": item.get("review_state"),
                },
            )
        )
    return records


def _route_note_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("route_note_candidates_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "route_note_candidates_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    records = []
    for item in payload.get("candidates", []) or []:
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("candidate_id") or "route_note.unknown")
        note = str(item.get("normalized_note") or item.get("name") or record_id)
        records.append(
            _record(
                record_id=record_id,
                evidence_type="pretrip_route_note_candidate",
                source_path=str(ref),
                title=note,
                text=_compact_text(
                    item,
                    include_keys=(
                        "normalized_note",
                        "name",
                        "desc",
                        "cmt",
                        "note_category",
                        "route_note_freshness",
                    ),
                ),
                tags=[
                    str(item.get("note_category") or "route_note"),
                    "potential_ln_signal" if item.get("potential_ln_signal") else "route_note",
                ],
                metadata={
                    "candidate_id": item.get("candidate_id"),
                    "note_category": item.get("note_category"),
                    "requires_human_review": item.get("requires_human_review"),
                    "potential_ln_signal": item.get("potential_ln_signal"),
                    "route_note_freshness": item.get("route_note_freshness"),
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                    "ele_m": item.get("ele_m"),
                },
            )
        )
    return records


def _review_queue_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("review_queue_manifest_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "review_queue_manifest_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    records = []
    for index, item in enumerate(payload.get("items", []) or []):
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("item_id") or item.get("candidate_ref") or f"review_queue.{index:05d}")
        records.append(
            _record(
                record_id=record_id,
                evidence_type="pretrip_review_queue_item",
                source_path=str(ref),
                title=str(item.get("title") or item.get("summary") or record_id),
                text=_compact_text(
                    item,
                    include_keys=("title", "summary", "category", "severity", "candidate_ref"),
                ),
                tags=[str(item.get("category") or "review_queue")],
                metadata={
                    "category": item.get("category"),
                    "severity": item.get("severity"),
                    "candidate_ref": item.get("candidate_ref"),
                },
            )
        )
    return records


def _spatial_imprint_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    records: list[ScoutAgentKbRecord] = []
    for project_ref_key, item_key, evidence_type in (
        (
            "spatial_imprint_set_ref",
            "imprints",
            "pretrip_reviewed_spatial_imprint",
        ),
        (
            "spatial_imprint_candidates_ref",
            "candidates",
            "pretrip_spatial_imprint_candidate",
        ),
    ):
        ref = project.get(project_ref_key)
        if not ref:
            continue
        path = _project_path(root, str(ref), project_ref_key)
        if not path.exists():
            continue
        payload = _load_json_object(path)
        for index, item in enumerate(payload.get(item_key, []) or []):
            if not isinstance(item, dict):
                continue
            record_id = str(item.get("imprint_id") or f"{evidence_type}.{index:05d}")
            payload_data = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            anchor = item.get("anchor") if isinstance(item.get("anchor"), dict) else {}
            trigger = item.get("trigger") if isinstance(item.get("trigger"), dict) else {}
            predicates = [
                predicate.get("type")
                for predicate in trigger.get("predicates", [])
                if isinstance(predicate, dict) and predicate.get("type")
            ]
            source_refs = [
                str(source.get("source_id") or source.get("source_path"))
                for source in item.get("source_refs", [])
                if isinstance(source, dict) and (source.get("source_id") or source.get("source_path"))
            ]
            text = _compact_text(
                {
                    "label": item.get("label"),
                    "kind": item.get("kind"),
                    "severity": item.get("severity"),
                    "planting_source": item.get("planting_source"),
                    "payload_text_zh": payload_data.get("text_zh"),
                    "payload_type": payload_data.get("payload_type"),
                    "anchor_type": anchor.get("anchor_type"),
                    "segment_ref": anchor.get("segment_ref"),
                    "cp_ref": anchor.get("cp_ref"),
                    "risk_zone_ref": anchor.get("risk_zone_ref"),
                    "trigger_predicates": predicates,
                    "source_refs": source_refs,
                },
                max_chars=1200,
            )
            records.append(
                _record(
                    record_id=record_id,
                    evidence_type=evidence_type,
                    source_path=str(ref),
                    title=str(item.get("label") or record_id),
                    text=text or str(item.get("label") or record_id),
                    tags=[
                        "spatial_imprint",
                        str(item.get("kind") or ""),
                        str(item.get("severity") or ""),
                        *[str(predicate) for predicate in predicates],
                    ],
                    metadata={
                        "imprint_id": item.get("imprint_id"),
                        "kind": item.get("kind"),
                        "severity": item.get("severity"),
                        "planting_source": item.get("planting_source"),
                        "segment_ref": anchor.get("segment_ref"),
                        "cp_ref": anchor.get("cp_ref"),
                        "risk_zone_ref": anchor.get("risk_zone_ref"),
                    },
                )
            )
    return records


def _optional_summary_record(
    root: Path,
    project: dict[str, Any],
    project_ref_key: str,
    evidence_type: str,
) -> list[ScoutAgentKbRecord]:
    ref = project.get(project_ref_key)
    if not ref:
        return []
    path = _project_path(root, str(ref), project_ref_key)
    if not path.exists():
        return []
    payload = _load_json_object(path)
    title = str(payload.get("artifact_kind") or payload.get("artifact_id") or evidence_type)
    return [
        _record(
            record_id=str(payload.get("artifact_id") or payload.get("manifest_id") or evidence_type),
            evidence_type=evidence_type,
            source_path=str(ref),
            title=title,
            text=_compact_text(payload, max_chars=2000),
            tags=[evidence_type],
            metadata={
                "artifact_kind": payload.get("artifact_kind"),
                "status": payload.get("status"),
                "counts": payload.get("counts"),
            },
        )
    ]


def _record(
    *,
    record_id: str,
    evidence_type: str,
    source_path: str,
    title: str,
    text: str,
    tags: list[str],
    metadata: dict[str, Any],
) -> ScoutAgentKbRecord:
    return ScoutAgentKbRecord(
        record_id=record_id,
        evidence_type=evidence_type,
        source_path=source_path,
        title=title,
        text=text,
        tags=[tag for tag in tags if tag],
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _score_record(record: ScoutAgentKbRecord, query: str, tokens: list[str]) -> int:
    haystack = f"{record.record_id} {record.evidence_type} {record.title} {record.text} {' '.join(record.tags)}".lower()
    lowered_query = query.lower()
    score = 0
    if lowered_query in haystack:
        score += 8
    for token in tokens:
        if token.lower() in haystack:
            score += 2
    if any(tag.lower() in lowered_query for tag in record.tags):
        score += 1
    return score


def _tokens(query: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z0-9_:-]+|[\u4e00-\u9fff]+", query)
        if token
    ]


def _snippet(text: str, query: str, tokens: list[str], *, limit: int = 220) -> str:
    lowered = text.lower()
    candidates = [query.lower(), *[token.lower() for token in tokens]]
    start = 0
    for candidate in candidates:
        index = lowered.find(candidate)
        if index >= 0:
            start = max(0, index - 60)
            break
    snippet = text[start : start + limit]
    if start:
        snippet = f"...{snippet}"
    if start + limit < len(text):
        snippet = f"{snippet}..."
    return snippet


def _compact_text(
    payload: dict[str, Any],
    *,
    include_keys: tuple[str, ...] | None = None,
    max_chars: int = 800,
) -> str:
    items = (
        [(key, payload.get(key)) for key in include_keys]
        if include_keys
        else sorted(payload.items(), key=lambda item: item[0])
    )
    parts = []
    for key, value in items:
        if value is None or key in {"geometry", "coordinates", "raw_payload", "raw_gpx"}:
            continue
        if isinstance(value, (dict, list)):
            value_text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            value_text = str(value)
        if value_text:
            parts.append(f"{key}: {value_text}")
    text = "; ".join(parts)
    return text[:max_chars]


def _project_path(root: Path, ref: str, label: str) -> Path:
    path = Path(ref)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be project-relative")
    return root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _require_project_id(project: dict[str, Any]) -> str:
    project_id = project.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project.json missing project_id")
    return project_id


def _assert_no_forbidden_fragments(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for fragment in ("/safety/", "ObservedFact", "Phase1IncidentBridge", "raw_gpx"):
        if fragment in text:
            raise ValueError(f"forbidden local evidence fragment: {fragment}")
