from __future__ import annotations

import json
import re
import sqlite3
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
    retrieval_engine: str = "heuristic"
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
    records.extend(_route_mileage_anchor_records(root, project))
    records.extend(_mileage_tag_alignment_records(root, project))
    records.extend(_raster_label_records(root, project))
    records.extend(_route_note_records(root, project))
    records.extend(_review_queue_records(root, project))
    records.extend(_spatial_imprint_records(root, project))
    records.extend(_mcp_records(root, project))
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


def write_local_evidence_sqlite_index(
    project_root: Path | str,
    output_path: Path | str,
) -> ScoutAgentKbIndex:
    index = build_local_evidence_index(project_root)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.tmp")
    if temporary.exists():
        temporary.unlink()

    try:
        with sqlite3.connect(temporary) as conn:
            _initialize_sqlite_index(conn)
            _write_sqlite_metadata(conn, index)
            _write_sqlite_records(conn, index)
            conn.commit()
        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
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
        retrieval_engine="heuristic",
        result_count=len(results),
        results=results,
        searched_record_count=len(index.records),
    )


def query_local_evidence_sqlite_index(
    index_path: Path | str,
    *,
    query: str,
    limit: int = 8,
    evidence_types: set[str] | None = None,
) -> ScoutAgentKbQueryResult:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("kb query must not be blank")
    if limit <= 0:
        limit = 0

    path = Path(index_path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        metadata = _read_sqlite_metadata(conn)
        project_id = _required_metadata(metadata, "project_id")
        record_count = int(_required_metadata(metadata, "record_count"))
        boundary = ScoutAgentKbBoundary.model_validate_json(
            _required_metadata(metadata, "boundary_json")
        )
        match_query = _fts_match_query(normalized_query)
        if not match_query or limit == 0:
            rows: list[sqlite3.Row] = []
        else:
            candidate_limit = _sqlite_candidate_limit(
                limit=limit,
                evidence_types=evidence_types,
            )
            sql, params = _sqlite_query_sql(
                match_query,
                limit=candidate_limit,
                evidence_types=evidence_types,
            )
            rows = list(conn.execute(sql, params))

    results = _diversify_sqlite_results(
        [_sqlite_row_to_result(row, normalized_query) for row in rows],
        limit=limit,
        evidence_types=evidence_types,
    )
    return ScoutAgentKbQueryResult(
        project_id=project_id,
        query=normalized_query,
        retrieval_engine="sqlite_fts5_bm25",
        result_count=len(results),
        results=results,
        searched_record_count=record_count,
        boundary=boundary,
    )


def query_project_local_evidence(
    project_root: Path | str,
    *,
    query: str,
    limit: int = 8,
    evidence_types: set[str] | None = None,
    use_sqlite_index: bool | None = None,
) -> ScoutAgentKbQueryResult:
    root = Path(project_root)
    sqlite_index_path = _default_sqlite_index_path(root)
    if use_sqlite_index is not False and sqlite_index_path.exists():
        try:
            return query_local_evidence_sqlite_index(
                sqlite_index_path,
                query=query,
                limit=limit,
                evidence_types=evidence_types,
            )
        except Exception:
            if use_sqlite_index is True:
                raise

    return query_local_evidence_index(
        build_local_evidence_index(root),
        query=query,
        limit=limit,
        evidence_types=evidence_types,
    )


def _default_sqlite_index_path(project_root: Path) -> Path:
    return project_root / "outputs" / "kb" / "local-evidence-index.sqlite3"


def _initialize_sqlite_index(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE records (
            rowid INTEGER PRIMARY KEY,
            record_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            record_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE records_fts USING fts5(
            record_id UNINDEXED,
            evidence_type UNINDEXED,
            title,
            body,
            tags,
            token_text
        )
        """
    )


def _write_sqlite_metadata(
    conn: sqlite3.Connection,
    index: ScoutAgentKbIndex,
) -> None:
    metadata = {
        "artifact_kind": "scout_local_evidence_sqlite_index",
        "schema_version": index.schema_version,
        "project_id": index.project_id,
        "source_root": index.source_root,
        "record_count": str(index.record_count),
        "boundary_json": index.boundary.model_dump_json(),
    }
    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        sorted(metadata.items(), key=lambda item: item[0]),
    )


def _write_sqlite_records(
    conn: sqlite3.Connection,
    index: ScoutAgentKbIndex,
) -> None:
    for rowid, record in enumerate(index.records, start=1):
        record_json = record.model_dump_json()
        conn.execute(
            """
            INSERT INTO records(rowid, record_id, evidence_type, record_json)
            VALUES (?, ?, ?, ?)
            """,
            (rowid, record.record_id, record.evidence_type, record_json),
        )
        conn.execute(
            """
            INSERT INTO records_fts(
                rowid,
                record_id,
                evidence_type,
                title,
                body,
                tags,
                token_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rowid,
                record.record_id,
                record.evidence_type,
                record.title,
                record.text,
                " ".join(record.tags),
                " ".join(_tokens(_record_search_text(record))),
            ),
        )


def _read_sqlite_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key, value FROM metadata")
    }


def _required_metadata(metadata: dict[str, str], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        raise ValueError(f"sqlite local evidence index missing metadata: {key}")
    return value


def _sqlite_query_sql(
    match_query: str,
    *,
    limit: int,
    evidence_types: set[str] | None,
) -> tuple[str, list[Any]]:
    where = ["records_fts MATCH ?"]
    params: list[Any] = [match_query]
    if evidence_types:
        placeholders = ", ".join("?" for _ in evidence_types)
        where.append(f"records_fts.evidence_type IN ({placeholders})")
        params.extend(sorted(evidence_types))
    params.append(limit)
    sql = f"""
        SELECT
            records.record_json AS record_json,
            bm25(records_fts) AS bm25_rank
        FROM records_fts
        JOIN records ON records.rowid = records_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY bm25_rank ASC, records.evidence_type ASC, records.record_id ASC
        LIMIT ?
    """
    return sql, params


def _sqlite_candidate_limit(
    *,
    limit: int,
    evidence_types: set[str] | None,
) -> int:
    if evidence_types and len(evidence_types) == 1:
        return limit
    return max(limit, limit * 8)


def _diversify_sqlite_results(
    results: list[dict[str, Any]],
    *,
    limit: int,
    evidence_types: set[str] | None,
) -> list[dict[str, Any]]:
    if evidence_types and len(evidence_types) == 1:
        return results[:limit]

    per_type_soft_cap = 2 if limit >= 4 else 1
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for result in results:
        evidence_type = str(result.get("evidence_type") or "")
        count = counts.get(evidence_type, 0)
        if count < per_type_soft_cap:
            selected.append(result)
            counts[evidence_type] = count + 1
        else:
            deferred.append(result)
        if len(selected) >= limit:
            return selected[:limit]

    selected.extend(deferred)
    return selected[:limit]


def _sqlite_row_to_result(row: sqlite3.Row, query: str) -> dict[str, Any]:
    record = ScoutAgentKbRecord.model_validate_json(str(row["record_json"]))
    tokens = _tokens(query)
    rank = float(row["bm25_rank"])
    return {
        "score": round(-rank, 9),
        "retrieval_rank": rank,
        "record_id": record.record_id,
        "evidence_type": record.evidence_type,
        "source_path": record.source_path,
        "title": record.title,
        "snippet": _snippet(record.text, query, tokens),
        "tags": record.tags,
        "metadata": record.metadata,
        "boundary": record.boundary.model_dump(mode="json"),
    }


def _fts_match_query(query: str) -> str:
    tokens = _tokens(query)
    query_parts = _dedupe_preserving_order([query, *tokens])
    quoted = [_quote_fts_token(token) for token in query_parts[:64] if token.strip()]
    return " OR ".join(quoted)


def _quote_fts_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _record_search_text(record: ScoutAgentKbRecord) -> str:
    metadata_text = json.dumps(record.metadata, ensure_ascii=False, sort_keys=True)
    return " ".join(
        (
            record.record_id,
            record.evidence_type,
            record.title,
            record.text,
            " ".join(record.tags),
            metadata_text,
        )
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


def _route_mileage_anchor_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("route_mileage_k_anchors_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "route_mileage_k_anchors_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    records: list[ScoutAgentKbRecord] = []
    for index, item in enumerate(payload.get("anchors", []) or []):
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("candidate_id") or f"route_mileage_anchor.{index:05d}")
        label = str(
            item.get("display_label")
            or item.get("normalized_mileage_k")
            or item.get("raw_mileage_text")
            or record_id
        )
        text = _compact_text(
            {
                "display_label": item.get("display_label"),
                "normalized_mileage_k": item.get("normalized_mileage_k"),
                "mileage_k": item.get("mileage_k"),
                "mileage_m": item.get("mileage_m"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "label_role": item.get("label_role"),
                "mileage_anchor_kind": item.get("mileage_anchor_kind"),
                "raw_label_examples": item.get("raw_label_examples"),
                "supporting_candidate_ids": item.get("supporting_candidate_ids"),
                "review_required": item.get("review_required"),
                "candidate_only": item.get("candidate_only"),
                "runtime_safety_truth": item.get("runtime_safety_truth"),
            },
            max_chars=1200,
        )
        records.append(
            _record(
                record_id=record_id,
                evidence_type="pretrip_route_mileage_k_anchor",
                source_path=str(ref),
                title=label,
                text=text or label,
                tags=[
                    "route_mileage",
                    "mileage_anchor",
                    "trail_mileage_k_anchor",
                    str(item.get("normalized_mileage_k") or ""),
                ],
                metadata={
                    "candidate_id": item.get("candidate_id"),
                    "normalized_mileage_k": item.get("normalized_mileage_k"),
                    "mileage_k": item.get("mileage_k"),
                    "mileage_m": item.get("mileage_m"),
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                    "review_required": item.get("review_required"),
                    "candidate_only": item.get("candidate_only"),
                    "runtime_safety_truth": item.get("runtime_safety_truth"),
                },
            )
        )
    return records


def _mileage_tag_alignment_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("mileage_tag_alignment_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "mileage_tag_alignment_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    records: list[ScoutAgentKbRecord] = []
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    route_alignment = (
        payload.get("route_mileage_alignment")
        if isinstance(payload.get("route_mileage_alignment"), dict)
        else {}
    )
    records.append(
        _record(
            record_id="mileage_tag_alignment.summary",
            evidence_type="pretrip_mileage_tag_alignment_summary",
            source_path=str(ref),
            title="Mileage tag alignment summary",
            text=_compact_text(
                {
                    "artifact_kind": payload.get("artifact_kind"),
                    "status": payload.get("status"),
                    "counts": counts,
                    "policy": payload.get("policy"),
                    "raw_source_summary": payload.get("raw_source_summary"),
                    "usable_anchor_count": route_alignment.get("usable_anchor_count"),
                    "projected_anchor_count": route_alignment.get("projected_anchor_count"),
                    "rejected_anchor_count": route_alignment.get("rejected_anchor_count"),
                },
                max_chars=1800,
            ),
            tags=["mileage_tag_alignment", "route_mileage", "workspace_summary"],
            metadata={
                "artifact_kind": payload.get("artifact_kind"),
                "status": payload.get("status"),
                "counts": counts,
                "mileage_tag_alignment_geojson_ref": payload.get(
                    "mileage_tag_alignment_geojson_ref"
                ),
                "candidate_only": (payload.get("boundary") or {}).get("candidate_only")
                if isinstance(payload.get("boundary"), dict)
                else None,
                "runtime_safety_truth": (payload.get("boundary") or {}).get(
                    "runtime_safety_truth"
                )
                if isinstance(payload.get("boundary"), dict)
                else None,
            },
        )
    )
    usable_anchors = route_alignment.get("usable_anchors")
    if isinstance(usable_anchors, list):
        for index, item in enumerate(usable_anchors[:128]):
            if not isinstance(item, dict):
                continue
            label = str(
                item.get("display_label")
                or item.get("normalized_mileage_k")
                or f"mileage_alignment_anchor.{index:05d}"
            )
            records.append(
                _record(
                    record_id=str(
                        item.get("candidate_id")
                        or f"mileage_alignment_anchor.{index:05d}"
                    ),
                    evidence_type="pretrip_mileage_tag_alignment_anchor",
                    source_path=str(ref),
                    title=label,
                    text=_compact_text(item, max_chars=1200) or label,
                    tags=[
                        "mileage_tag_alignment",
                        "usable_anchor",
                        str(item.get("normalized_mileage_k") or ""),
                    ],
                    metadata={
                        "normalized_mileage_k": item.get("normalized_mileage_k"),
                        "mileage_k": item.get("mileage_k"),
                        "mileage_m": item.get("mileage_m"),
                        "lat": item.get("lat"),
                        "lon": item.get("lon"),
                        "candidate_only": item.get("candidate_only"),
                        "runtime_safety_truth": item.get("runtime_safety_truth"),
                    },
                )
            )
    return records


def _raster_label_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    records: list[ScoutAgentKbRecord] = []
    evidence_ref = project.get("raster_label_evidence_ref")
    if evidence_ref:
        evidence_path = _project_path(root, str(evidence_ref), "raster_label_evidence_ref")
        if evidence_path.exists():
            payload = _load_json_object(evidence_path)
            for index, feature in enumerate(payload.get("features", []) or []):
                if not isinstance(feature, dict):
                    continue
                properties = (
                    feature.get("properties")
                    if isinstance(feature.get("properties"), dict)
                    else {}
                )
                geometry = (
                    feature.get("geometry")
                    if isinstance(feature.get("geometry"), dict)
                    else {}
                )
                coordinates = geometry.get("coordinates")
                lon = lat = None
                if isinstance(coordinates, list) and len(coordinates) >= 2:
                    lon = coordinates[0]
                    lat = coordinates[1]
                record_id = str(
                    properties.get("candidate_id")
                    or feature.get("id")
                    or f"raster_label.{index:05d}"
                )
                label = str(
                    properties.get("label_text")
                    or properties.get("label")
                    or record_id
                )
                records.append(
                    _record(
                        record_id=record_id,
                        evidence_type="pretrip_raster_label_ocr",
                        source_path=str(evidence_ref),
                        title=label,
                        text=_compact_text(
                            {
                                "label_text": properties.get("label_text"),
                                "label_role": properties.get("label_role"),
                                "confidence": properties.get("confidence"),
                                "review_state": properties.get("review_state"),
                                "review_required": properties.get("review_required"),
                                "source_ref": properties.get("source_ref"),
                                "source_payload_ref": properties.get("source_payload_ref"),
                                "tile_id": properties.get("tile_id"),
                                "lat": lat,
                                "lon": lon,
                                "candidate_only": properties.get("candidate_only"),
                                "runtime_safety_truth": properties.get(
                                    "runtime_safety_truth"
                                ),
                            },
                            max_chars=1200,
                        )
                        or label,
                        tags=[
                            "raster_label",
                            "ocr",
                            str(properties.get("label_role") or ""),
                            str(properties.get("label_text") or ""),
                        ],
                        metadata={
                            "candidate_id": properties.get("candidate_id")
                            or feature.get("id"),
                            "label_text": properties.get("label_text"),
                            "label_role": properties.get("label_role"),
                            "confidence": properties.get("confidence"),
                            "review_required": properties.get("review_required"),
                            "lat": lat,
                            "lon": lon,
                            "source_payload_ref": properties.get("source_payload_ref"),
                            "candidate_only": properties.get("candidate_only"),
                            "runtime_safety_truth": properties.get(
                                "runtime_safety_truth"
                            ),
                        },
                    )
                )
    output_ref = project.get("raster_label_ocr_output_ref")
    if output_ref:
        output_path = _project_path(root, str(output_ref), "raster_label_ocr_output_ref")
        if output_path.exists():
            payload = _load_json_object(output_path)
            for index, item in enumerate(payload.get("labels", []) or []):
                if not isinstance(item, dict):
                    continue
                record_id = str(item.get("id") or f"raster_ocr_output.{index:05d}")
                label = str(item.get("label_text") or record_id)
                records.append(
                    _record(
                        record_id=f"{record_id}.raw",
                        evidence_type="pretrip_raster_label_ocr_raw",
                        source_path=str(output_ref),
                        title=label,
                        text=_compact_text(
                            {
                                "label_text": item.get("label_text"),
                                "label_role": item.get("label_role"),
                                "confidence": item.get("confidence"),
                                "source_ref": item.get("source_ref"),
                                "source_id": item.get("source_id"),
                                "tile_z": item.get("tile_z"),
                                "tile_x": item.get("tile_x"),
                                "tile_y": item.get("tile_y"),
                                "review_required": item.get("review_required"),
                                "candidate_only": item.get("candidate_only"),
                                "runtime_safety_truth": item.get(
                                    "runtime_safety_truth"
                                ),
                            },
                            max_chars=1200,
                        )
                        or label,
                        tags=[
                            "raster_label",
                            "ocr_raw",
                            str(item.get("label_role") or ""),
                            str(item.get("label_text") or ""),
                        ],
                        metadata={
                            "candidate_id": item.get("id"),
                            "label_text": item.get("label_text"),
                            "label_role": item.get("label_role"),
                            "confidence": item.get("confidence"),
                            "review_required": item.get("review_required"),
                            "candidate_only": item.get("candidate_only"),
                            "runtime_safety_truth": item.get("runtime_safety_truth"),
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


def _mcp_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    records: list[ScoutAgentKbRecord] = []
    records.extend(_mcp_named_point_records(root, project))
    records.extend(_mcp_candidate_records(root, project))
    records.extend(_mcp_cp_support_records(root, project))
    return records


def _mcp_named_point_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("mcp_named_point_evidence_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "mcp_named_point_evidence_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    records: list[ScoutAgentKbRecord] = []
    for index, item in enumerate(payload.get("named_points", []) or []):
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("named_point_id") or f"mcp_named_point.{index:05d}")
        route_position = item.get("route_position") if isinstance(item.get("route_position"), dict) else {}
        boundary = item.get("boundary") if isinstance(item.get("boundary"), dict) else {}
        title = str(item.get("canonical_name") or record_id)
        text = _compact_text(
            {
                "canonical_name": item.get("canonical_name"),
                "aliases": item.get("aliases"),
                "point_class": item.get("point_class"),
                "source_families": item.get("source_families"),
                "missing_source_families": item.get("missing_source_families"),
                "mention_page_count": item.get("mention_page_count"),
                "mention_ratio": item.get("mention_ratio"),
                "stale_risk": item.get("stale_risk"),
                "distance_m": route_position.get("distance_m"),
                "lat": route_position.get("lat"),
                "lon": route_position.get("lon"),
                "coordinate_confidence": route_position.get("coordinate_confidence"),
                "candidate_only": boundary.get("candidate_only"),
                "runtime_safety_truth": boundary.get("phase1_runtime_safety_truth"),
            },
            max_chars=1200,
        )
        records.append(
            _record(
                record_id=record_id,
                evidence_type="pretrip_mcp_named_point",
                source_path=str(ref),
                title=title,
                text=text or title,
                tags=[
                    "mcp",
                    "named_point",
                    *[str(value) for value in item.get("point_class", []) if value],
                ],
                metadata={
                    "named_point_id": item.get("named_point_id"),
                    "canonical_name": item.get("canonical_name"),
                    "aliases": item.get("aliases"),
                    "point_class": item.get("point_class"),
                    "distance_m": route_position.get("distance_m"),
                    "lat": route_position.get("lat"),
                    "lon": route_position.get("lon"),
                    "coordinate_confidence": route_position.get("coordinate_confidence"),
                    "mention_ratio": item.get("mention_ratio"),
                    "stale_risk": item.get("stale_risk"),
                    "candidate_only": boundary.get("candidate_only"),
                    "runtime_safety_truth": boundary.get("phase1_runtime_safety_truth"),
                },
            )
        )
    return records


def _mcp_candidate_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("mcp_candidates_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "mcp_candidates_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    records: list[ScoutAgentKbRecord] = []
    for index, item in enumerate(payload.get("mcp_candidates", []) or []):
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("mcp_id") or f"mcp_candidate.{index:05d}")
        nearest_cp = item.get("nearest_scout_cp") if isinstance(item.get("nearest_scout_cp"), dict) else {}
        boundary = item.get("boundary") if isinstance(item.get("boundary"), dict) else {}
        title = str(item.get("label") or record_id)
        text = _compact_text(
            {
                "label": item.get("label"),
                "mcp_id": item.get("mcp_id"),
                "mcp_classes": item.get("mcp_classes"),
                "linked_named_points": item.get("linked_named_points"),
                "linked_cp_candidates": item.get("linked_cp_candidates"),
                "nearest_scout_cp": nearest_cp,
                "promotion_reasons": item.get("promotion_reasons"),
                "missing_source_gaps": item.get("missing_source_gaps"),
                "confidence": item.get("confidence"),
                "review_state": item.get("review_state"),
                "mention_ratio": item.get("mention_ratio"),
                "distance_m": item.get("distance_m"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "candidate_only": boundary.get("candidate_only"),
                "runtime_safety_truth": boundary.get("runtime_safety_truth"),
            },
            max_chars=1600,
        )
        records.append(
            _record(
                record_id=record_id,
                evidence_type="pretrip_major_critical_point_candidate",
                source_path=str(ref),
                title=title,
                text=text or title,
                tags=[
                    "mcp",
                    "major_critical_point",
                    *[str(value) for value in item.get("mcp_classes", []) if value],
                ],
                metadata={
                    "mcp_id": item.get("mcp_id"),
                    "label": item.get("label"),
                    "mcp_classes": item.get("mcp_classes"),
                    "linked_cp_candidates": item.get("linked_cp_candidates"),
                    "nearest_cp_candidate_id": nearest_cp.get("candidate_id"),
                    "nearest_cp_distance_m": nearest_cp.get("distance_m"),
                    "support_found": nearest_cp.get("support_found"),
                    "support_radius_m": nearest_cp.get("support_radius_m"),
                    "distance_m": item.get("distance_m"),
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                    "confidence": item.get("confidence"),
                    "review_state": item.get("review_state"),
                    "candidate_only": boundary.get("candidate_only"),
                    "runtime_safety_truth": boundary.get("runtime_safety_truth"),
                },
            )
        )
    return records


def _mcp_cp_support_records(root: Path, project: dict[str, Any]) -> list[ScoutAgentKbRecord]:
    ref = project.get("mcp_cp_support_reconciliation_ref")
    if not ref:
        return []
    path = _project_path(root, str(ref), "mcp_cp_support_reconciliation_ref")
    if not path.exists():
        return []
    payload = _load_json_object(path)
    records: list[ScoutAgentKbRecord] = []
    for index, item in enumerate(payload.get("rows", []) or []):
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("mcp_id") or f"mcp_cp_support.{index:05d}")
        nearest_cp = item.get("nearest_scout_cp") if isinstance(item.get("nearest_scout_cp"), dict) else {}
        title = str(item.get("label") or record_id)
        text = _compact_text(
            {
                "label": item.get("label"),
                "mcp_id": item.get("mcp_id"),
                "linked_cp_candidates": item.get("linked_cp_candidates"),
                "nearest_scout_cp": nearest_cp,
                "support_status": item.get("support_status"),
                "recommendation": item.get("recommendation"),
                "review_required": item.get("review_required"),
                "suggested_cp_insertion": item.get("suggested_cp_insertion"),
                "spacing_suppression_details": item.get("spacing_suppression_details"),
                "candidate_only": item.get("candidate_only"),
                "runtime_safety_truth": item.get("runtime_safety_truth"),
            },
            max_chars=1600,
        )
        records.append(
            _record(
                record_id=record_id,
                evidence_type="pretrip_mcp_cp_support_reconciliation",
                source_path=str(ref),
                title=title,
                text=text or title,
                tags=[
                    "mcp",
                    "cp_support",
                    str(item.get("support_status") or ""),
                ],
                metadata={
                    "mcp_id": item.get("mcp_id"),
                    "label": item.get("label"),
                    "linked_cp_candidates": item.get("linked_cp_candidates"),
                    "nearest_cp_candidate_id": nearest_cp.get("candidate_id"),
                    "nearest_cp_distance_m": nearest_cp.get("distance_m"),
                    "support_found": nearest_cp.get("support_found"),
                    "support_radius_m": nearest_cp.get("support_radius_m"),
                    "support_status": item.get("support_status"),
                    "review_required": item.get("review_required"),
                    "candidate_only": item.get("candidate_only"),
                    "runtime_safety_truth": item.get("runtime_safety_truth"),
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
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_:-]+|[\u4e00-\u9fff]+", query):
        if not token:
            continue
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            max_ngram = min(4, len(token))
            for size in range(2, max_ngram + 1):
                tokens.extend(
                    token[index : index + size]
                    for index in range(0, len(token) - size + 1)
                )
    return _dedupe_preserving_order(tokens)


def _dedupe_preserving_order(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


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
