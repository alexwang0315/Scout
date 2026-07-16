"""Deterministic bounded queries over Scout workspace JSON artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import ValidationError

from scout.schemas.workspace_query import (
    ArgMaxQuery,
    CountQuery,
    DiffQuery,
    DistinctQuery,
    ExistsQuery,
    FilterQuery,
    FreshnessQuery,
    GroupByQuery,
    InspectQuery,
    IntervalQuery,
    NearestQuery,
    RouteForwardQuery,
    TopKQuery,
    WorkspaceArtifactSelector,
    WorkspacePredicate,
    WorkspacePredicateOperator,
    WorkspaceQueryEvidence,
    WorkspaceQueryLimits,
    WorkspaceMileageCandidate,
    WorkspaceMileageVerification,
    WorkspaceQueryOperation,
    WorkspaceQueryRequest,
    WorkspaceQueryResponse,
    parse_workspace_query_request,
)


_ALLOWED_SUFFIXES = frozenset({".json", ".geojson"})
_COLLECTION_KEYS = (
    "features",
    "records",
    "results",
    "items",
    "rows",
    "candidates",
    "checkpoints",
    "segments",
    "points",
    "reviews",
    "reference_tracks",
    "anchors",
    "events",
    "warnings",
)
_MISSING = object()
_MILEAGE_K_PATTERN = re.compile(
    r"(?<![0-9.])(?P<mileage>[+-]?[0-9]+(?:\.[0-9]+)?)\s*[KkＫｋ](?![A-Za-z])"
)
_WATER_QUERY_TERMS = ("水源", "取水", "water")


class WorkspaceQueryError(Exception):
    def __init__(
        self,
        root_cause: str,
        *,
        missing_fields: Sequence[str] = (),
        safe_retry: bool = False,
    ) -> None:
        super().__init__(root_cause)
        self.root_cause = root_cause
        self.missing_fields = list(missing_fields)
        self.safe_retry = safe_retry


@dataclass(frozen=True)
class _Artifact:
    source_ref: str
    source_hash: str
    payload: Any
    modified_at: datetime


@dataclass(frozen=True)
class _Record:
    value: Any
    locator: str


class WorkspaceQueryService:
    """Execute a constrained operation without code, shell, SQL, or network access."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        limits: WorkspaceQueryLimits | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve(strict=True)
        if not self.project_root.is_dir():
            raise ValueError("project_root must be a directory")
        self.limits = limits or WorkspaceQueryLimits()

    def execute(self, raw_request: WorkspaceQueryRequest | Mapping[str, Any]) -> WorkspaceQueryResponse:
        operation = _raw_operation(raw_request)
        try:
            request = (
                raw_request
                if not isinstance(raw_request, Mapping)
                else parse_workspace_query_request(raw_request)
            )
            return self._execute(request)
        except ValidationError as exc:
            missing = [
                ".".join(str(part) for part in error.get("loc", ()))
                for error in exc.errors(include_url=False)
            ]
            return _failure(
                operation,
                "invalid_request",
                missing_fields=[item for item in missing if item],
            )
        except WorkspaceQueryError as exc:
            return _failure(
                operation,
                exc.root_cause,
                missing_fields=exc.missing_fields,
                safe_retry=exc.safe_retry,
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _failure(operation, "artifact_json_invalid")


    def _execute(self, request: WorkspaceQueryRequest) -> WorkspaceQueryResponse:
        if isinstance(request, DiffQuery):
            return self._diff(request)
        artifact = self._load_artifact(request.artifact)
        if isinstance(request, FreshnessQuery):
            return self._freshness(request, artifact)
        if isinstance(request, RouteForwardQuery):
            return self._route_forward(request, artifact)
        records, collection_path = self._records(artifact, request.artifact)
        self._enforce_scan_limit(records)
        filtered = _filter_records(records, getattr(request, "predicates", []))
        if isinstance(request, InspectQuery):
            data = {
                "payload_type": type(artifact.payload).__name__,
                "collection_path": collection_path,
                "collection_count": len(records),
            }
            if request.fields:
                selected_fields = _project(artifact.payload, request.fields)
                if selected_fields:
                    data["selected_fields"] = selected_fields
                if records:
                    sample_record = _project(records[0].value, request.fields)
                    if sample_record and sample_record != selected_fields:
                        data["sample_record"] = sample_record
            top_level_keys = (
                sorted(str(key) for key in artifact.payload)
                if isinstance(artifact.payload, Mapping)
                else []
            )
            if request.fields and isinstance(artifact.payload, Mapping):
                requested_roots = {
                    str(field).split(".", 1)[0] for field in request.fields
                }
                collection_root = collection_path.strip("/").split(".", 1)[0]
                if collection_root:
                    requested_roots.add(collection_root)
                top_level_keys = [
                    key for key in top_level_keys if key in requested_roots
                ]
            data["top_level_keys"] = top_level_keys
            result = self._aggregate_evidence(artifact, "inspect", data)
            response = self._success(
                request.operation,
                "artifact inspected",
                [result],
                len(records),
                [artifact],
            )
            inspected_values = [artifact.payload]
            if records:
                inspected_values.append(records[0].value)
            return _with_missing_requested_fields(
                response,
                request.fields,
                inspected_values,
            )
        if isinstance(request, ExistsQuery):
            matching = filtered
            if request.field is not None:
                matching = [item for item in matching if _field(item.value, request.field) is not _MISSING]
            data = {"exists": bool(matching), "matching_count": len(matching)}
            result = self._aggregate_evidence(artifact, "exists", data)
            return self._success(request.operation, f"exists={str(bool(matching)).lower()}", [result], len(records), [artifact])
        if isinstance(request, CountQuery):
            data: dict[str, Any] = {"count": len(filtered)}
            if filtered:
                data.update(
                    {
                        "first_record_id": _record_id(
                            filtered[0].value, filtered[0].locator
                        ),
                        "first_locator": filtered[0].locator,
                        "last_record_id": _record_id(
                            filtered[-1].value, filtered[-1].locator
                        ),
                        "last_locator": filtered[-1].locator,
                    }
                )
            result = self._aggregate_evidence(artifact, "count", data)
            response = self._success(request.operation, f"count={len(filtered)}", [result], len(records), [artifact])
            return response.model_copy(update={"result_count": len(filtered)})
        if isinstance(request, DistinctQuery):
            values = _stable_unique(
                _field(item.value, request.field)
                for item in filtered
                if _field(item.value, request.field) is not _MISSING
            )
            effective_limit = min(request.limit, self.limits.max_returned_records)
            limited_values = values[:effective_limit]
            limitations = (
                ["return_limit_applied"] if len(values) > effective_limit else []
            )
            result = self._aggregate_evidence(
                artifact,
                "distinct",
                {"field": request.field, "values": limited_values},
            )
            response = self._success(
                request.operation,
                f"distinct_count={len(values)}",
                [result],
                len(records),
                [artifact],
                limitations=limitations,
            )
            return response.model_copy(update={"result_count": len(values)})
        if isinstance(request, FilterQuery):
            selected = filtered
            if request.sort_by:
                selected = _sort_records(selected, request.sort_by, request.descending)
            return self._record_response(request, artifact, records, selected)
        if isinstance(request, GroupByQuery):
            groups: dict[str, tuple[Any, int]] = {}
            for item in filtered:
                value = _field(item.value, request.field)
                if value is _MISSING:
                    continue
                key = _canonical_json(value)
                current = groups.get(key, (value, 0))
                groups[key] = (current[0], current[1] + 1)
            ordered = sorted(groups.values(), key=lambda item: (-item[1], _canonical_json(item[0])))
            effective_limit = min(request.limit, self.limits.max_returned_records)
            limited_groups = ordered[:effective_limit]
            results = [
                self._aggregate_evidence(
                    artifact,
                    f"group/{index}",
                    {"group": value, "count": count, "field": request.field},
                )
                for index, (value, count) in enumerate(limited_groups)
            ]
            if not results:
                return self._empty(
                    request.operation,
                    len(records),
                    artifact,
                    "no_group_values",
                )
            return self._success(
                request.operation,
                f"group_count={len(ordered)}",
                results,
                len(records),
                [artifact],
                limitations=(
                    ["return_limit_applied"]
                    if len(ordered) > effective_limit
                    else []
                ),
            )
        if isinstance(request, TopKQuery):
            selected = _sort_records(filtered, request.field, request.descending)[: request.k]
            return self._record_response(request, artifact, records, selected)
        if isinstance(request, ArgMaxQuery):
            if request.subtract_field is not None:
                scored: list[tuple[float, _Record]] = []
                for item in filtered:
                    difference = _numeric_difference(
                        item.value,
                        request.field,
                        request.subtract_field,
                    )
                    if difference is not None:
                        scored.append((difference, item))
                scored.sort(key=lambda item: (-item[0], item[1].locator))
                if not scored:
                    return self._empty(
                        request.operation,
                        len(records),
                        artifact,
                        "no_numeric_difference_values",
                    )
                difference, record = scored[0]
                data = {
                    **_project(record.value, request.fields),
                    "numeric_difference": difference,
                    "numeric_difference_fields": [
                        request.field,
                        request.subtract_field,
                    ],
                }
                response = self._success(
                    request.operation,
                    f"max_difference={difference}",
                    [self._record_evidence(artifact, record, data)],
                    len(records),
                    [artifact],
                )
                return _with_missing_requested_fields(
                    response,
                    request.fields,
                    [record.value],
                )
            selected = _sort_records(filtered, request.field, True)[:1]
            if not selected:
                return self._empty(request.operation, len(records), artifact, "no_numeric_or_comparable_values")
            return self._record_response(request, artifact, records, selected)
        if isinstance(request, NearestQuery):
            distances: list[tuple[float, _Record]] = []
            coordinate_record_count = 0
            for item in filtered:
                coordinate = _coordinate(item.value, request.lat_field, request.lon_field)
                if coordinate is None:
                    continue
                coordinate_record_count += 1
                distance = _haversine_m(request.origin.lat, request.origin.lon, coordinate[0], coordinate[1])
                if request.max_distance_m is None or distance <= request.max_distance_m:
                    distances.append((distance, item))
            distances.sort(key=lambda item: (item[0], item[1].locator))
            results = [
                self._record_evidence(
                    artifact,
                    record,
                    {**_project(record.value, request.fields), "distance_m": distance},
                )
                for distance, record in distances[: request.k]
            ]
            if not results:
                if filtered and coordinate_record_count == 0:
                    return _incomplete(
                        request.operation,
                        "coordinate_fields_missing",
                        source_refs=[artifact.source_ref],
                        missing_fields=[request.lat_field, request.lon_field],
                    )
                return self._empty(
                    request.operation,
                    len(records),
                    artifact,
                    "no_records_within_distance",
                )
            response = self._success(
                request.operation,
                f"nearest_count={len(results)}",
                results,
                len(records),
                [artifact],
            )
            return _with_missing_requested_fields(
                response,
                request.fields,
                [record.value for _, record in distances[: request.k]],
            )
        if isinstance(request, IntervalQuery):
            if request.value_field is not None:
                assert request.start is not None and request.end is not None
                selected = [
                    item
                    for item in filtered
                    if (
                        (value := _number(_field(item.value, request.value_field)))
                        is not None
                        and request.start <= value <= request.end
                    )
                ]
                selected.sort(
                    key=lambda item: (
                        _number(_field(item.value, request.value_field)) or 0.0,
                        item.locator,
                    )
                )
            elif request.start_field is not None:
                assert request.start_field is not None
                assert request.end_field is not None
                assert request.value is not None
                selected = [
                    item
                    for item in filtered
                    if (
                        (start := _number(_field(item.value, request.start_field)))
                        is not None
                        and (end := _number(_field(item.value, request.end_field)))
                        is not None
                        and start <= request.value <= end
                    )
                ]
                selected.sort(
                    key=lambda item: (
                        _number(_field(item.value, request.start_field)) or 0.0,
                        _number(_field(item.value, request.end_field)) or 0.0,
                        item.locator,
                    )
                )
            else:
                assert request.cumulative_field is not None
                assert request.value is not None
                cumulative = 0.0
                cumulative_matches: list[tuple[_Record, float, float]] = []
                missing_count = 0
                for item in records:
                    length = _number(_field(item.value, request.cumulative_field))
                    if length is None or length < 0:
                        missing_count += 1
                        continue
                    start = cumulative
                    cumulative += length
                    if (
                        start <= request.value <= cumulative
                        and all(
                            _matches(item.value, predicate)
                            for predicate in request.predicates
                        )
                    ):
                        cumulative_matches.append((item, start, cumulative))
                if missing_count:
                    return _incomplete(
                        request.operation,
                        "cumulative_interval_sequence_incomplete",
                        source_refs=[artifact.source_ref],
                        missing_fields=[request.cumulative_field],
                    )
                effective_limit = min(
                    request.limit, self.limits.max_returned_records
                )
                results = [
                    self._record_evidence(
                        artifact,
                        item,
                        {
                            **_project(item.value, request.fields),
                            "computed_interval_start": start,
                            "computed_interval_end": end,
                            "cumulative_field": request.cumulative_field,
                        },
                    )
                    for item, start, end in cumulative_matches[:effective_limit]
                ]
                response = self._success(
                    request.operation,
                    f"result_count={len(results)}",
                    results,
                    len(records),
                    [artifact],
                    limitations=(
                        ["return_limit_applied"]
                        if len(cumulative_matches) > effective_limit
                        else []
                    ),
                )
                return _with_missing_requested_fields(
                    response,
                    request.fields,
                    [item.value for item, _, _ in cumulative_matches[:effective_limit]],
                )
            return self._record_response(request, artifact, records, selected)
        raise WorkspaceQueryError("unsupported_operation")

    def _record_response(
        self,
        request: Any,
        artifact: _Artifact,
        scanned_records: Sequence[_Record],
        selected_records: Sequence[_Record],
    ) -> WorkspaceQueryResponse:
        requested_limit = int(getattr(request, "limit", self.limits.max_returned_records))
        effective_limit = min(requested_limit, self.limits.max_returned_records)
        selected = list(selected_records)[:effective_limit]
        if not selected:
            return self._empty(
                request.operation,
                len(scanned_records),
                artifact,
                "no_matching_records",
            )
        limitations: list[str] = []
        if len(selected_records) > effective_limit:
            limitations.append("return_limit_applied")
        results = [
            self._record_evidence(artifact, item, _project(item.value, request.fields))
            for item in selected
        ]
        response = self._success(
            request.operation,
            f"result_count={len(results)}",
            results,
            len(scanned_records),
            [artifact],
            limitations=limitations,
        )
        return _with_missing_requested_fields(
            response,
            request.fields,
            [item.value for item in selected],
        )

    def _diff(self, request: DiffQuery) -> WorkspaceQueryResponse:
        left = self._load_artifact(request.left_artifact)
        right = self._load_artifact(request.right_artifact)
        if request.aggregation is not None:
            assert request.left_field is not None and request.right_field is not None
            left_records, _ = self._records(left, request.left_artifact)
            right_records, _ = self._records(right, request.right_artifact)
            self._enforce_scan_limit(left_records)
            self._enforce_scan_limit(right_records)
            left_value = _aggregate_numeric(
                left_records, request.left_field, request.aggregation
            )
            right_value = _aggregate_numeric(
                right_records, request.right_field, request.aggregation
            )
            if left_value is None or right_value is None:
                missing_fields = []
                if left_value is None:
                    missing_fields.append(request.left_field)
                if right_value is None:
                    missing_fields.append(request.right_field)
                return _incomplete(
                    request.operation,
                    "aggregate_diff_fields_missing_or_non_numeric",
                    source_refs=[left.source_ref, right.source_ref],
                    missing_fields=missing_fields,
                )
            data = {
                "aggregation": request.aggregation,
                "left_field": request.left_field,
                "right_field": request.right_field,
                "left_value": left_value,
                "right_value": right_value,
                "numeric_difference": _stable_difference(right_value, left_value),
                "left_hash": left.source_hash,
                "right_hash": right.source_hash,
            }
            combined_hash = _hash_text(f"{left.source_hash}:{right.source_hash}")
            result = WorkspaceQueryEvidence(
                evidence_id=_evidence_id(combined_hash, "/diff/aggregate", data),
                source_ref=left.source_ref,
                record_id=f"diff/{request.aggregation}",
                locator="/diff/aggregate",
                source_hash=combined_hash,
                data=data,
            )
            return self._success(
                request.operation,
                f"numeric_difference={_stable_difference(right_value, left_value)}",
                [result],
                len(left_records) + len(right_records),
                [left, right],
            )
        paths: list[str] = []
        _changed_paths(left.payload, right.payload, "", paths, self.limits.max_diff_paths)
        data = {
            "equal": not paths,
            "changed_paths": paths,
            "left_hash": left.source_hash,
            "right_hash": right.source_hash,
        }
        combined_hash = _hash_text(f"{left.source_hash}:{right.source_hash}")
        result = WorkspaceQueryEvidence(
            evidence_id=_evidence_id(combined_hash, "/diff", data),
            source_ref=left.source_ref,
            record_id="diff",
            locator="/diff",
            source_hash=combined_hash,
            data=data,
        )
        return self._success(request.operation, f"changed_path_count={len(paths)}", [result], 2, [left, right])

    def _freshness(self, request: FreshnessQuery, artifact: _Artifact) -> WorkspaceQueryResponse:
        source_time = artifact.modified_at
        if request.timestamp_field:
            raw = _field(artifact.payload, request.timestamp_field)
            parsed = _parse_datetime(raw)
            if parsed is None:
                return _incomplete(
                    request.operation,
                    "timestamp_field_missing_or_invalid",
                    source_refs=[artifact.source_ref],
                    missing_fields=[request.timestamp_field],
                )
            source_time = parsed
        now = request.now or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age_seconds = max(0.0, (now.astimezone(UTC) - source_time.astimezone(UTC)).total_seconds())
        freshness = {
            "source_timestamp": source_time.isoformat(),
            "age_seconds": round(age_seconds, 3),
            "stale_after_seconds": request.stale_after_seconds,
            "stale": age_seconds > request.stale_after_seconds,
            "stale_risk": "stale" if age_seconds > request.stale_after_seconds else "fresh",
        }
        result = self._aggregate_evidence(artifact, "freshness", freshness)
        response = self._success(
            request.operation,
            freshness["stale_risk"],
            [result],
            1,
            [artifact],
        )
        return response.model_copy(
            update={
                "status": "warning" if freshness["stale"] else "success",
                "answerability": "stale" if freshness["stale"] else "complete",
                "freshness": freshness,
            }
        )

    def _route_forward(self, request: RouteForwardQuery, artifact: _Artifact) -> WorkspaceQueryResponse:
        if request.current_route_distance_m is None and request.current_position is None:
            return _incomplete(
                request.operation,
                "current_route_position_missing",
                missing_fields=["current_route_distance_m", "current_position"],
                stop_condition="obtain verified live route position before retry",
            )
        route = self._load_artifact(request.route_artifact)
        route_points = _route_points(route.payload)
        current_distance = request.current_route_distance_m
        current_off_route_distance: float | None = None
        if current_distance is None and request.current_position is not None:
            if len(route_points) < 2:
                return _incomplete(
                    request.operation,
                    "route_geometry_unavailable",
                    source_refs=[route.source_ref],
                    missing_fields=["route_geometry"],
                )
            current_distance, current_off_route_distance = _project_route_position(
                request.current_position.lat,
                request.current_position.lon,
                route_points,
            )
        elif request.current_position is not None and len(route_points) >= 2:
            _, current_off_route_distance = _project_route_position(
                request.current_position.lat,
                request.current_position.lon,
                route_points,
            )
        assert current_distance is not None
        records, _ = self._records(artifact, request.artifact)
        self._enforce_scan_limit(records)
        filtered = _filter_records(records, request.predicates)
        candidates: list[tuple[float, _Record, dict[str, Any]]] = []
        for item in filtered:
            route_distance = _number(_field(item.value, request.route_distance_field))
            coordinate = _coordinate(item.value, request.lat_field, request.lon_field)
            off_route_distance: float | None = None
            if coordinate is not None and len(route_points) >= 2:
                projected_distance, off_route_distance = _project_route_position(
                    coordinate[0], coordinate[1], route_points
                )
            else:
                projected_distance = None
            if route_distance is None:
                route_distance = projected_distance
            if route_distance is None:
                continue
            forward = route_distance - current_distance
            if forward < 0:
                continue
            if request.max_forward_distance_m is not None and forward > request.max_forward_distance_m:
                continue
            metrics: dict[str, Any] = {"forward_distance_m": forward}
            if off_route_distance is not None:
                metrics["off_route_distance_m"] = off_route_distance
            if current_off_route_distance is not None:
                metrics["current_off_route_distance_m"] = current_off_route_distance
            if request.current_position is not None and coordinate is not None:
                metrics["straight_line_distance_m"] = _haversine_m(
                    request.current_position.lat,
                    request.current_position.lon,
                    coordinate[0],
                    coordinate[1],
                )
            metrics.update(_record_quality_fields(item.value))
            candidates.append((forward, item, metrics))
        candidates.sort(key=lambda item: (item[0], item[1].locator))
        limit = min(request.limit, self.limits.max_returned_records)
        results = [
            self._record_evidence(
                artifact,
                item,
                {**_project(item.value, request.fields), **metrics},
            )
            for _, item, metrics in candidates[:limit]
        ]
        limitations = ["return_limit_applied"] if len(candidates) > limit else []
        response = self._success(
            request.operation,
            f"forward_result_count={len(results)}",
            results,
            len(records),
            [artifact, route],
            limitations=limitations,
        )
        return _with_missing_requested_fields(
            response,
            request.fields,
            [item.value for _, item, _ in candidates[:limit]],
        )

    def _load_artifact(self, selector: WorkspaceArtifactSelector) -> _Artifact:
        source_ref = selector.source_ref
        if selector.project_ref_key is not None:
            manifest = self._read_project_manifest()
            value = _field(manifest, selector.project_ref_key)
            if not isinstance(value, str) or not value.strip():
                raise WorkspaceQueryError(
                    "artifact_ref_missing",
                    missing_fields=[selector.project_ref_key],
                )
            source_ref = value
        assert source_ref is not None
        path = Path(source_ref)
        if (
            path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or any(part in {"", "."} or part.startswith(".") for part in path.parts)
        ):
            raise WorkspaceQueryError("workspace_path_rejected")
        if path.suffix.casefold() not in _ALLOWED_SUFFIXES:
            raise WorkspaceQueryError("artifact_extension_rejected")
        try:
            resolved = (self.project_root / path).resolve(strict=True)
            canonical_ref = resolved.relative_to(self.project_root).as_posix()
        except (FileNotFoundError, OSError, ValueError):
            raise WorkspaceQueryError("workspace_path_rejected") from None
        if not resolved.is_file():
            raise WorkspaceQueryError("workspace_path_rejected")
        size = resolved.stat().st_size
        if size > self.limits.max_artifact_bytes:
            raise WorkspaceQueryError("artifact_size_limit_exceeded")
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        _validate_json_bounds(
            payload,
            max_depth=self.limits.max_json_depth,
            max_string_length=self.limits.max_string_length,
        )
        modified = datetime.fromtimestamp(resolved.stat().st_mtime, tz=UTC)
        return _Artifact(
            source_ref=canonical_ref,
            source_hash=f"sha256:{hashlib.sha256(raw).hexdigest()}",
            payload=payload,
            modified_at=modified,
        )

    def _read_project_manifest(self) -> Mapping[str, Any]:
        path = self.project_root / "project.json"
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.project_root)
        except (FileNotFoundError, OSError, ValueError):
            raise WorkspaceQueryError("project_manifest_unavailable") from None
        if not resolved.is_file():
            raise WorkspaceQueryError("project_manifest_unavailable")
        if resolved.stat().st_size > self.limits.max_artifact_bytes:
            raise WorkspaceQueryError("project_manifest_size_limit_exceeded")
        payload = json.loads(resolved.read_bytes().decode("utf-8"))
        _validate_json_bounds(
            payload,
            max_depth=self.limits.max_json_depth,
            max_string_length=self.limits.max_string_length,
        )
        if not isinstance(payload, Mapping):
            raise WorkspaceQueryError("project_manifest_invalid")
        return payload

    def _records(
        self,
        artifact: _Artifact,
        selector: WorkspaceArtifactSelector,
    ) -> tuple[list[_Record], str]:
        selected = artifact.payload
        path = ""
        if selector.collection_path:
            selected = _field(selected, selector.collection_path)
            if selected is _MISSING:
                raise WorkspaceQueryError(
                    "collection_path_missing",
                    missing_fields=[selector.collection_path],
                )
            path = "/" + selector.collection_path.replace(".", "/")
        if isinstance(selected, list):
            return [_Record(item, f"{path}/{index}" or f"/{index}") for index, item in enumerate(selected)], path or "/"
        if isinstance(selected, Mapping):
            for key in _COLLECTION_KEYS:
                value = selected.get(key)
                if isinstance(value, list):
                    collection_path = f"{path}/{key}" if path else f"/{key}"
                    return [
                        _Record(item, f"{collection_path}/{index}")
                        for index, item in enumerate(value)
                    ], collection_path
            list_items = [(str(key), value) for key, value in selected.items() if isinstance(value, list)]
            if len(list_items) == 1:
                key, value = list_items[0]
                collection_path = f"{path}/{key}" if path else f"/{key}"
                return [
                    _Record(item, f"{collection_path}/{index}")
                    for index, item in enumerate(value)
                ], collection_path
            return [_Record(selected, path or "/")], path or "/"
        return [_Record(selected, path or "/")], path or "/"

    def _enforce_scan_limit(self, records: Sequence[_Record]) -> None:
        if len(records) > self.limits.max_scanned_records:
            raise WorkspaceQueryError("scan_limit_exceeded")

    def _record_evidence(
        self,
        artifact: _Artifact,
        record: _Record,
        data: dict[str, Any],
    ) -> WorkspaceQueryEvidence:
        return WorkspaceQueryEvidence(
            evidence_id=_evidence_id(artifact.source_hash, record.locator, data),
            source_ref=artifact.source_ref,
            record_id=_record_id(record.value, record.locator),
            locator=record.locator,
            source_hash=artifact.source_hash,
            data=data,
            observed_at=_record_time(record.value, "observed_at"),
            valid_from=_record_time(record.value, "valid_from"),
            valid_to=_record_time(record.value, "valid_to"),
        )

    def _aggregate_evidence(
        self,
        artifact: _Artifact,
        label: str,
        data: dict[str, Any],
    ) -> WorkspaceQueryEvidence:
        locator = f"/$aggregate/{label}"
        return WorkspaceQueryEvidence(
            evidence_id=_evidence_id(artifact.source_hash, locator, data),
            source_ref=artifact.source_ref,
            record_id=label,
            locator=locator,
            source_hash=artifact.source_hash,
            data=data,
        )

    @staticmethod
    def _success(
        operation: WorkspaceQueryOperation,
        summary: str,
        results: list[WorkspaceQueryEvidence],
        scanned_count: int,
        artifacts: Sequence[_Artifact],
        *,
        limitations: Sequence[str] = (),
    ) -> WorkspaceQueryResponse:
        partial = "return_limit_applied" in limitations
        return WorkspaceQueryResponse(
            status="warning" if partial else "success",
            answerability="partial" if partial else "complete",
            operation=operation,
            summary=summary,
            results=results,
            result_count=len(results),
            scanned_record_count=scanned_count,
            source_refs=list(dict.fromkeys(item.source_ref for item in artifacts)),
            limitations=list(limitations),
            stop_condition="sufficient_record_evidence_returned",
        )

    def _empty(
        self,
        operation: WorkspaceQueryOperation,
        scanned_count: int,
        artifact: _Artifact,
        limitation: str,
    ) -> WorkspaceQueryResponse:
        evidence = self._aggregate_evidence(
            artifact,
            "empty",
            {"result_count": 0, "reason": limitation},
        )
        return WorkspaceQueryResponse(
            status="success",
            answerability="complete",
            operation=operation,
            summary="result_count=0",
            results=[evidence],
            result_count=0,
            scanned_record_count=scanned_count,
            source_refs=[artifact.source_ref],
            limitations=[limitation],
            stop_condition="empty_result_is_deterministic",
        )


def verify_nearest_mileage_candidates(
    question: str,
    responses: Sequence[WorkspaceQueryResponse],
) -> WorkspaceMileageVerification | None:
    """Verify nearest water candidates on the source-label mileage axis."""

    target = _question_mileage_k(question)
    if target is None or not any(
        term in question.casefold() for term in _WATER_QUERY_TERMS
    ):
        return None

    rows: list[tuple[WorkspaceQueryEvidence, float, float, float]] = []
    source_refs: list[str] = []
    limitations: list[str] = []
    for response in responses:
        if response.operation is not WorkspaceQueryOperation.FILTER:
            continue
        source_refs.extend(response.source_refs)
        limitations.extend(response.limitations)
        for evidence in response.results:
            label = str(evidence.data.get("source_label") or "").strip()
            label_mileage = _label_mileage_k(label)
            coordinates = evidence.data.get("coordinates")
            if (
                "水源" not in label
                or label_mileage is None
                or not isinstance(coordinates, Sequence)
                or isinstance(coordinates, (str, bytes, bytearray))
                or len(coordinates) < 2
            ):
                continue
            lon = _number(coordinates[0])
            lat = _number(coordinates[1])
            if (
                lon is None
                or lat is None
                or not -180 <= lon <= 180
                or not -90 <= lat <= 90
            ):
                continue
            rows.append((evidence, label_mileage, lat, lon))

    if not rows:
        return WorkspaceMileageVerification(
            status="warning",
            target_mileage_k=target,
            evidence_record_count=0,
            distinct_candidate_count=0,
            tied_candidate_count=0,
            source_refs=list(dict.fromkeys(source_refs)),
            freshness={"basis": "static_workspace_artifact", "state": "unknown"},
            limitations=list(
                dict.fromkeys(
                    [*limitations, "no_parseable_water_mileage_candidates"]
                )
            ),
            summary=f"{target:g}K 附近沒有可驗證的里程水源候選。",
            stop_condition="obtain_parseable_mileage_label_evidence_before_answering",
        )

    grouped: dict[tuple[float, float, float], list[WorkspaceQueryEvidence]] = {}
    labels: dict[tuple[float, float, float], set[str]] = {}
    for evidence, mileage, lat, lon in rows:
        key = (round(mileage, 6), round(lat, 7), round(lon, 7))
        grouped.setdefault(key, []).append(evidence)
        labels.setdefault(key, set()).add(str(evidence.data["source_label"]).strip())

    contradictions = _mileage_candidate_contradictions(grouped, labels)
    candidates: list[WorkspaceMileageCandidate] = []
    for (mileage, lat, lon), evidence_group in sorted(grouped.items()):
        delta = round(abs(mileage - target), 6)
        direction: Literal["behind", "at", "ahead"] = (
            "behind" if mileage < target else "ahead" if mileage > target else "at"
        )
        route_distances = {
            value
            for item in evidence_group
            if (value := _number(item.data.get("route_distance_m"))) is not None
        }
        projection_states = {
            str(item.data.get("route_projection_status"))
            for item in evidence_group
            if item.data.get("route_projection_status")
        }
        candidates.append(
            WorkspaceMileageCandidate(
                source_label=sorted(labels[(mileage, lat, lon)])[0],
                label_mileage_k=mileage,
                delta_k=delta,
                direction=direction,
                lat=lat,
                lon=lon,
                route_distance_m=(min(route_distances) if route_distances else None),
                route_projection_status=(
                    sorted(projection_states)[0] if projection_states else None
                ),
                source_ids=list(
                    dict.fromkeys(
                        str(item.data["source_id"])
                        for item in evidence_group
                        if item.data.get("source_id")
                    )
                ),
                evidence_ids=[item.evidence_id for item in evidence_group],
                record_ids=[item.record_id for item in evidence_group],
                source_ref=evidence_group[0].source_ref,
                source_hashes=list(
                    dict.fromkeys(item.source_hash for item in evidence_group)
                ),
            )
        )

    nearest_delta = min(item.delta_k for item in candidates)
    tied = [
        item
        for item in candidates
        if math.isclose(item.delta_k, nearest_delta, abs_tol=1e-9)
    ]
    tied.sort(
        key=lambda item: (
            item.label_mileage_k,
            item.source_label,
            item.lat,
            item.lon,
        )
    )
    return WorkspaceMileageVerification(
        status="warning" if contradictions else "success",
        target_mileage_k=target,
        evidence_record_count=len(rows),
        distinct_candidate_count=len(candidates),
        nearest_delta_k=nearest_delta,
        tied_candidate_count=len(tied),
        candidates=tied,
        source_refs=list(
            dict.fromkeys([*source_refs, *(item.source_ref for item in tied)])
        ),
        freshness={
            "basis": "static_workspace_artifact",
            "state": "artifact_timestamp_not_queried",
        },
        contradictions=contradictions,
        limitations=list(
            dict.fromkeys(
                [
                    *limitations,
                    "label_mileage_axis_only",
                    "route_distance_m_not_used_for_k_comparison",
                    "live_water_presence_not_verified",
                    "potability_not_verified",
                ]
            )
        ),
        summary=_mileage_verification_summary(target, tied, nearest_delta),
        stop_condition="all_tied_nearest_candidates_verified",
    )


def _question_mileage_k(question: str) -> float | None:
    match = _MILEAGE_K_PATTERN.search(question)
    return float(match.group("mileage")) if match else None


def _label_mileage_k(label: str) -> float | None:
    match = _MILEAGE_K_PATTERN.search(label)
    return float(match.group("mileage")) if match else None


def _mileage_candidate_contradictions(
    grouped: Mapping[tuple[float, float, float], Sequence[WorkspaceQueryEvidence]],
    labels: Mapping[tuple[float, float, float], set[str]],
) -> list[str]:
    locations_by_label: dict[tuple[float, str], set[tuple[float, float]]] = {}
    for mileage, lat, lon in grouped:
        for label in labels[(mileage, lat, lon)]:
            locations_by_label.setdefault((mileage, label), set()).add((lat, lon))
    return [
        f"same_label_multiple_locations:{mileage:g}K:{label}"
        for (mileage, label), locations in sorted(locations_by_label.items())
        if len(locations) > 1
    ]


def _mileage_verification_summary(
    target: float,
    candidates: Sequence[WorkspaceMileageCandidate],
    nearest_delta: float,
) -> str:
    direction_labels = {"behind": "後方", "at": "正好", "ahead": "前方"}
    details = "；".join(
        f"{item.source_label}（{item.label_mileage_k:g}K，"
        f"{direction_labels[item.direction]} {item.delta_k:g}K，"
        f"座標 {item.lat:.4f},{item.lon:.4f}）"
        for item in candidates
    )
    tie_note = "兩個候選等距" if len(candidates) == 2 else f"{len(candidates)} 個候選等距"
    return (
        f"{target:g}K 最近的水源有{tie_note}，各距里程標 {nearest_delta:g}K："
        f"{details}。"
    )


def _raw_operation(raw: object) -> WorkspaceQueryOperation:
    value = raw.get("operation") if isinstance(raw, Mapping) else getattr(raw, "operation", "inspect")
    try:
        return WorkspaceQueryOperation(str(value))
    except ValueError:
        return WorkspaceQueryOperation.INSPECT


def _failure(
    operation: WorkspaceQueryOperation,
    root_cause: str,
    *,
    missing_fields: Sequence[str] = (),
    safe_retry: bool = False,
) -> WorkspaceQueryResponse:
    if root_cause in {
        "artifact_ref_missing",
        "project_manifest_unavailable",
        "workspace_path_rejected",
    }:
        answerability = "missing_artifact"
    elif missing_fields or root_cause in {
        "collection_path_missing",
        "invalid_request",
    }:
        answerability = "missing_required_fields"
    else:
        answerability = "unsafe_to_infer"
    return WorkspaceQueryResponse(
        status="error",
        answerability=answerability,
        operation=operation,
        root_cause=root_cause,
        missing_fields=list(missing_fields),
        safe_retry=safe_retry,
        stop_condition="do_not_retry_without_changed_inputs",
    )


def _incomplete(
    operation: WorkspaceQueryOperation,
    root_cause: str,
    *,
    source_refs: Sequence[str] = (),
    missing_fields: Sequence[str] = (),
    stop_condition: str | None = None,
) -> WorkspaceQueryResponse:
    answerability = (
        "requires_live_state"
        if root_cause == "current_route_position_missing"
        else "missing_required_fields"
    )
    return WorkspaceQueryResponse(
        status="warning",
        answerability=answerability,
        operation=operation,
        source_refs=list(source_refs),
        root_cause=root_cause,
        missing_fields=list(missing_fields),
        safe_retry=False,
        stop_condition=stop_condition or "do_not_retry_without_changed_evidence",
    )


def _field(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _filter_records(records: Sequence[_Record], predicates: Sequence[WorkspacePredicate]) -> list[_Record]:
    return [item for item in records if all(_matches(item.value, predicate) for predicate in predicates)]


def _matches(record: Any, predicate: WorkspacePredicate) -> bool:
    value = _field(record, predicate.field)
    operator = predicate.operator
    if operator == WorkspacePredicateOperator.EXISTS:
        expected = True if predicate.value is None else bool(predicate.value)
        return (value is not _MISSING) == expected
    if value is _MISSING:
        return False
    expected = predicate.value
    if operator == WorkspacePredicateOperator.EQ:
        return value == expected
    if operator == WorkspacePredicateOperator.NE:
        return value != expected
    if operator == WorkspacePredicateOperator.IN:
        return isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)) and value in expected
    if operator == WorkspacePredicateOperator.CONTAINS:
        if isinstance(value, str):
            return str(expected).casefold() in value.casefold()
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and expected in value
    try:
        if operator == WorkspacePredicateOperator.GT:
            return value > expected
        if operator == WorkspacePredicateOperator.GTE:
            return value >= expected
        if operator == WorkspacePredicateOperator.LT:
            return value < expected
        if operator == WorkspacePredicateOperator.LTE:
            return value <= expected
    except TypeError:
        return False
    return False


def _sort_records(records: Sequence[_Record], field: str, descending: bool) -> list[_Record]:
    comparable = [item for item in records if _field(item.value, field) is not _MISSING]

    def key(item: _Record) -> tuple[int, Any, str]:
        value = _field(item.value, field)
        if isinstance(value, bool):
            return (0, int(value), item.locator)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (0, float(value), item.locator)
        return (1, _canonical_json(value), item.locator)

    return sorted(comparable, key=key, reverse=descending)


def _project(record: Any, fields: Sequence[str]) -> dict[str, Any]:
    if not fields:
        return _bounded_record(record)
    output: dict[str, Any] = {}
    for field in fields:
        value = _field(record, field)
        if value is _MISSING:
            continue
        leaf = field.rsplit(".", 1)[-1]
        key = leaf if leaf not in output else field
        output[key] = _bounded_record(value)
    return output


def _with_missing_requested_fields(
    response: WorkspaceQueryResponse,
    fields: Sequence[str],
    values: Sequence[Any],
) -> WorkspaceQueryResponse:
    if not fields or not values:
        return response
    missing_fields = [
        field
        for field in fields
        if all(_field(value, field) is _MISSING for value in values)
    ]
    if not missing_fields:
        return response
    return response.model_copy(
        update={
            "status": "warning",
            "answerability": "missing_required_fields",
            "missing_fields": missing_fields,
            "limitations": list(
                dict.fromkeys([*response.limitations, "requested_fields_missing"])
            ),
            "root_cause": "requested_fields_missing",
            "safe_retry": False,
            "stop_condition": "query another artifact or select available fields",
        }
    )


def _bounded_record(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "[nested content omitted]"
    if isinstance(value, Mapping):
        return {str(key): _bounded_record(item, depth=depth + 1) for key, item in list(sorted(value.items(), key=lambda item: str(item[0])))[:30]}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_bounded_record(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        return value[:2_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2_000]


def _record_id(record: Any, locator: str) -> str:
    if isinstance(record, Mapping):
        candidates = (
            record.get("candidate_id"),
            record.get("record_id"),
            record.get("id"),
            record.get("segment_id"),
            record.get("cp_id"),
        )
        properties = record.get("properties")
        if isinstance(properties, Mapping):
            candidates = (*candidates, properties.get("candidate_id"), properties.get("record_id"), properties.get("id"))
        for value in candidates:
            if value is not None and str(value).strip():
                return str(value)[:240]
    return locator.strip("/").replace("/", ":") or "root"


def _coordinate(record: Any, lat_field: str, lon_field: str) -> tuple[float, float] | None:
    lat = _number(_field(record, lat_field))
    lon = _number(_field(record, lon_field))
    if lat is not None and lon is not None:
        return lat, lon
    if isinstance(record, Mapping):
        geometry = record.get("geometry")
        if isinstance(geometry, Mapping) and geometry.get("type") == "Point":
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, Sequence) and len(coordinates) >= 2:
                lon = _number(coordinates[0])
                lat = _number(coordinates[1])
                if lat is not None and lon is not None:
                    return lat, lon
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _numeric_difference(record: Any, field: str, subtract_field: str) -> float | None:
    left = _number(_field(record, field))
    right = _number(_field(record, subtract_field))
    if left is None or right is None:
        return None
    return _stable_difference(left, right)


def _stable_difference(left: float, right: float) -> float:
    return round(left - right, 12)


def _aggregate_numeric(
    records: Sequence[_Record],
    field: str,
    aggregation: str,
) -> float | None:
    values = [
        numeric
        for item in records
        if (numeric := _number(_field(item.value, field))) is not None
    ]
    if not values:
        return None
    return max(values) if aggregation == "max" else min(values)


def _record_quality_fields(record: Any) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for field in ("confidence", "review_state", "stale_risk"):
        value = _field(record, field)
        if value is _MISSING:
            value = _field(record, f"properties.{field}")
        if value is not _MISSING:
            output[field] = _bounded_record(value)
    return output


def _stable_unique(values: Any) -> list[Any]:
    by_key: dict[str, Any] = {}
    for value in values:
        by_key.setdefault(_canonical_json(value), value)
    return [by_key[key] for key in sorted(by_key)]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _evidence_id(source_hash: str, locator: str, data: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(f"{source_hash}|{locator}|{_canonical_json(data)}".encode("utf-8")).hexdigest()
    return f"ev_{digest[:24]}"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _route_points(payload: Any) -> list[tuple[float, float]]:
    geometries: list[Any] = []
    if isinstance(payload, Mapping) and payload.get("type") == "FeatureCollection":
        geometries = [item.get("geometry") for item in payload.get("features", []) if isinstance(item, Mapping)]
    elif isinstance(payload, Mapping) and payload.get("type") == "Feature":
        geometries = [payload.get("geometry")]
    elif isinstance(payload, Mapping):
        geometries = [payload]
    for geometry in geometries:
        if not isinstance(geometry, Mapping):
            continue
        if geometry.get("type") == "LineString" and isinstance(geometry.get("coordinates"), list):
            points = []
            for coordinate in geometry["coordinates"]:
                if isinstance(coordinate, Sequence) and len(coordinate) >= 2:
                    lon = _number(coordinate[0])
                    lat = _number(coordinate[1])
                    if lat is not None and lon is not None:
                        points.append((lat, lon))
            if len(points) >= 2:
                return points
    return []


def _project_route_position(
    lat: float,
    lon: float,
    points: Sequence[tuple[float, float]],
) -> tuple[float, float]:
    best_distance = math.inf
    best_progress = 0.0
    progress = 0.0
    for start, end in zip(points, points[1:]):
        segment_length = _haversine_m(start[0], start[1], end[0], end[1])
        fraction, perpendicular = _segment_projection(lat, lon, start, end)
        if perpendicular < best_distance:
            best_distance = perpendicular
            best_progress = progress + fraction * segment_length
        progress += segment_length
    return best_progress, best_distance


def _segment_projection(
    lat: float,
    lon: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    mean_lat = math.radians((lat + start[0] + end[0]) / 3)
    scale_x = 111_320.0 * math.cos(mean_lat)
    scale_y = 110_540.0
    px, py = (lon - start[1]) * scale_x, (lat - start[0]) * scale_y
    vx, vy = (end[1] - start[1]) * scale_x, (end[0] - start[0]) * scale_y
    denominator = vx * vx + vy * vy
    fraction = 0.0 if denominator == 0 else max(0.0, min(1.0, (px * vx + py * vy) / denominator))
    dx, dy = px - fraction * vx, py - fraction * vy
    return fraction, math.hypot(dx, dy)


def _changed_paths(left: Any, right: Any, path: str, output: list[str], limit: int) -> None:
    if len(output) >= limit or left == right:
        return
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        for key in sorted(set(left) | set(right), key=str):
            child_path = f"{path}/{key}"
            if key not in left or key not in right:
                output.append(child_path)
            else:
                _changed_paths(left[key], right[key], child_path, output, limit)
            if len(output) >= limit:
                return
        return
    if isinstance(left, list) and isinstance(right, list):
        for index in range(max(len(left), len(right))):
            child_path = f"{path}/{index}"
            if index >= len(left) or index >= len(right):
                output.append(child_path)
            else:
                _changed_paths(left[index], right[index], child_path, output, limit)
            if len(output) >= limit:
                return
        return
    output.append(path or "/")


def _validate_json_bounds(value: Any, *, max_depth: int, max_string_length: int, depth: int = 0) -> None:
    if depth > max_depth:
        raise WorkspaceQueryError("json_depth_limit_exceeded")
    if isinstance(value, str):
        if len(value) > max_string_length:
            raise WorkspaceQueryError("json_string_limit_exceeded")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if len(str(key)) > max_string_length:
                raise WorkspaceQueryError("json_string_limit_exceeded")
            _validate_json_bounds(item, max_depth=max_depth, max_string_length=max_string_length, depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _validate_json_bounds(item, max_depth=max_depth, max_string_length=max_string_length, depth=depth + 1)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _record_time(record: Any, field: str) -> datetime | None:
    value = _field(record, field)
    if value is _MISSING and isinstance(record, Mapping):
        value = _field(record, f"properties.{field}")
    return _parse_datetime(value)


__all__ = ["WorkspaceQueryService", "verify_nearest_mileage_candidates"]
