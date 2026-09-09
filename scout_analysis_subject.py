"""Read-only identity and dependency evidence shared by the six Outdoor views.

This describes an analysis, never a runtime permission. Source observations,
adopted schedules and current weather keep separate roles and revisions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalysisSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str | None = None
    sha256: str | None = None
    expected_sha256: str | None = None
    status: Literal["available", "missing", "invalid", "changed"] = "missing"


class AnalysisSubject(BaseModel):
    schema_version: Literal["scoutAnalysisSubject.v1"] = "scoutAnalysisSubject.v1"
    project_id: str
    subject_kind: str = "golden_gpx"
    subject_id: str
    analysis_revision: str
    geometry_fingerprint: str
    timing_fingerprint: str
    sources: dict[str, AnalysisSource]
    original_golden_provenance: dict[str, Any] = Field(default_factory=dict)
    selected_baseline_ref: str | None = None
    selected_baseline_sha256: str | None = None
    schedule_status: str
    schedule_time_role: str
    timezone: str | None = None
    mission_day_estimates: list[dict[str, Any]] = Field(default_factory=list)
    day_segment_mapping: list[dict[str, Any]] = Field(default_factory=list)
    overnight_gaps: list[dict[str, Any]] = Field(default_factory=list)
    unknown_ranges: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: dict[str, dict[str, Any]] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    selected_plan_version_id: str | None = None
    planned_bundle_ref: str | None = None
    planned_bundle_sha256: str | None = None
    planning_review_ref: str | None = None
    route_axis: dict[str, Any] | list[Any] | None = None
    planned_route_geojson: dict[str, Any] | None = None
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    itinerary: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    departure_approval_granted: Literal[False] = False


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


class _Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.payloads: dict[str, dict] = {}
        self.hashes: dict[str, str] = {}

    def path(self, ref: object) -> Path | None:
        if not isinstance(ref, str) or not ref:
            return None
        path = (self.root / ref).resolve()
        return path if self.root in path.parents else None

    def digest(self, ref: object) -> str | None:
        path = self.path(ref)
        if path is None or not path.is_file():
            return None
        key = str(path)
        if key not in self.hashes:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            self.hashes[key] = digest.hexdigest()
        return self.hashes[key]

    def read(self, ref: object) -> dict:
        path = self.path(ref)
        if path is None or not path.is_file():
            return {}
        key = str(path)
        if key not in self.payloads:
            try:
                content = path.read_bytes()
                payload = json.loads(content)
                self.hashes[key] = hashlib.sha256(content).hexdigest()
            except (OSError, ValueError):
                payload = {}
            self.payloads[key] = payload if isinstance(payload, dict) else {}
        return self.payloads[key]

    def source(self, ref: object, expected: str | None = None) -> dict:
        path = self.path(ref)
        sha = self.digest(ref)
        return AnalysisSource(
            ref=path.relative_to(self.root).as_posix() if path else None,
            sha256=sha, expected_sha256=expected,
            status=("invalid" if ref and path is None else "missing" if not sha
                    else "changed" if expected and expected != sha else "available"),
        ).model_dump()


def _geometry_binding(ws: _Workspace, project: dict) -> dict:
    report = ws.read(project.get("gpx_speed_filter_report_ref", "outputs/gpx_speed_filter_report.json"))
    primary = report.get("primary") or {}
    refs = ws.read(project.get("reference_tracks_ref", "outputs/reference_tracks.json"))
    golden = refs.get("golden_route") or refs.get("primary_route") or {}
    golden_ref = primary.get("output_path") or golden.get("source_uri") or golden.get("source_path")
    sources = {
        "golden_geometry": ws.source(golden_ref, primary.get("output_sha256") or golden.get("sha256")),
        "checkpoints": ws.source(project.get("checkpoint_candidates_ref", "candidates/checkpoints.json")),
        "segments": ws.source(project.get("segment_display_geometry_ref", "outputs/segment_display_geometry.json")),
        "checkpoint_times": ws.source(project.get("checkpoint_events_ref", "outputs/checkpoint_events.json")),
        "reference_tracks": ws.source(project.get("reference_tracks_ref", "outputs/reference_tracks.json")),
        "recorded_pace": ws.source(project.get("reference_pace_energy_analysis_ref", "outputs/reference_pace_energy_analysis.json")),
    }
    for role in ("segments", "checkpoint_times"):
        payload = ws.read(sources[role]["ref"])
        source_sha = (payload.get("source_gpx") or {}).get("sha256")
        if source_sha and source_sha != sources["golden_geometry"]["sha256"]:
            sources[role]["status"] = "changed"
    identity = {key: {k: value[k] for k in ("ref", "sha256", "status")}
                for key, value in sources.items()}
    return {
        "schema_version": "analysisGeometryBinding.v1",
        "project_id": project.get("project_id", ws.root.name),
        "geometry_fingerprint": _digest({key: identity[key] for key in (
            "golden_geometry", "checkpoints", "segments", "reference_tracks",
        )}),
        "timing_fingerprint": _digest({key: identity[key] for key in (
            "golden_geometry", "checkpoint_times",
        )}),
        "sources": sources,
    }


def capture_analysis_geometry_binding(project_root: Path) -> dict:
    """Snapshot the actual workspace inputs for a preparation producer receipt."""
    ws = _Workspace(Path(project_root))
    return _geometry_binding(ws, ws.read("project.json"))


def _signed(payload: dict, field: str, expected: object = None) -> bool:
    actual = payload.get(field)
    return bool(actual and (expected is None or actual == expected)
                and actual == _digest({k: v for k, v in payload.items() if k != field}))


def _schedule(ws: _Workspace, project: dict) -> tuple[str, dict, dict, list[str]]:
    for directory in ("reviews/mission_baseline_accept_transactions", "reviews/contextual_permission_rebuild_transactions"):
        if any(path.is_file() and not path.name.startswith(".") for path in (ws.root / directory).glob("*.json")):
            return "rebuild_required", {}, {}, ["baseline_or_projection_write_in_doubt"]
    ref = project.get("reviewed_mission_baseline_ref")
    sha = project.get("reviewed_mission_baseline_sha256")
    if not ref and not sha:
        return "not_adopted", {}, {}, []
    reviewed = ws.read(ref)
    if not _signed(reviewed, "reviewed_baseline_sha256", sha):
        return "stale", {}, {}, ["reviewed_baseline_hash_mismatch"]
    review_id = reviewed.get("review_id")
    accepted = ws.read(f"reviews/mission_baseline_accept_receipts/{review_id}.json")
    if not (_signed(accepted, "review_sha256")
            and accepted.get("reviewed_baseline_ref") == ref
            and accepted.get("reviewed_baseline_sha256") == sha):
        return "stale", {}, {}, ["baseline_review_receipt_mismatch"]
    candidate = ws.read(reviewed.get("candidate_ref"))
    # The immutable candidate stores its content hash separately from file bytes.
    candidate_sha = candidate.get("version_sha256")
    if (candidate_sha != reviewed.get("candidate_sha256")
            or not _signed(candidate, "version_sha256")
            or candidate.get("project_id", project.get("project_id", ws.root.name)) != project.get("project_id", ws.root.name)
            or candidate.get("days") != reviewed.get("days")
            or candidate.get("reference_reconstruction") != reviewed.get("reference_reconstruction")):
        return "stale", {}, {}, ["baseline_candidate_lineage_mismatch"]
    reconstruction = reviewed.get("reference_reconstruction") or {}
    if (not isinstance(reconstruction, dict)
            or not isinstance(reconstruction.get("source_hashes", {}), dict)
            or not isinstance(reviewed.get("days"), list)
            or not all(isinstance(day, dict) for day in reviewed["days"])):
        return "stale", {}, {}, ["invalid_reviewed_schedule"]
    for source_ref, expected in (reconstruction.get("source_hashes") or {}).items():
        if ws.digest(source_ref) != expected:
            return "stale", reviewed, {}, ["reviewed_source_changed"]
    for source_ref, expected in (candidate.get("source_hashes") or {}).items():
        if ws.digest(source_ref) != expected:
            return "stale", reviewed, {}, ["reviewed_candidate_source_changed"]
    eta_ref = project.get("planned_eta_ref", "outputs/planned_eta.json")
    eta = ws.read(eta_ref)
    receipt = ws.read(project.get("contextual_permission_projection_rebuild_ref"))
    if not receipt or receipt.get("reviewed_baseline_sha256") != sha:
        return "rebuild_required", reviewed, {}, ["adopted_schedule_rebuild_required"]
    if not (_signed(receipt, "rebuild_sha256", project.get("contextual_permission_projection_rebuild_sha256"))
            and receipt.get("planned_eta_ref") == eta_ref
            and receipt.get("planned_eta_sha256") == ws.digest(eta_ref)
            and eta.get("reviewed_baseline_sha256") == sha
            and eta.get("project_id") == project.get("project_id", ws.root.name)):
        return "stale", reviewed, {}, ["planned_eta_rebuild_binding_mismatch"]
    seed = ws.read(receipt.get("workbench_seed_ref"))
    baseline = seed.get("baseline") or {}
    if (baseline.get("baseline_sha256") != sha
            or (baseline.get("source_hashes") or {}).get("planned_eta_ref") != ws.digest(eta_ref)):
        return "stale", reviewed, {}, ["planned_eta_seed_binding_mismatch"]
    expected_days = [{
        "mission_day_id": day.get("mission_day_id"), "eta": day.get("eta_proposal"),
        "segment_ids": day.get("segment_ids", []),
        "primary_day_end_proposal_id": (day.get("primary_day_end_proposal") or {}).get("proposal_id"),
        **({"reference_replay": day["reference_replay"]} if day.get("reference_replay") is not None else {}),
    } for day in reviewed.get("days", [])]
    if eta.get("mission_day_estimates") != expected_days:
        return "stale", reviewed, {}, ["planned_eta_reviewed_day_mismatch"]
    return "adopted", reviewed, eta, []


def _build_golden_analysis_subject(project_root: Path) -> AnalysisSubject:
    ws = _Workspace(Path(project_root))
    project = ws.read("project.json")
    binding = _geometry_binding(ws, project)
    original = ws.read(project.get("gpx_speed_filter_report_ref", "outputs/gpx_speed_filter_report.json")).get("primary") or {}
    status, reviewed, eta, issues = _schedule(ws, project)
    reconstruction = reviewed.get("reference_reconstruction") or {}
    days = eta.get("mission_day_estimates", []) if status == "adopted" else []
    manifest = ws.read(project.get("layer_preparation_manifest_ref", "outputs/layers/layer_preparation_manifest.json"))
    previous = manifest.get("analysis_geometry_binding") or {}
    current = manifest.get("analysis_geometry_binding_current") or {}
    geometry_current = bool(previous and current
        and previous.get("geometry_fingerprint") == current.get("geometry_fingerprint") == binding["geometry_fingerprint"]
        and not manifest.get("analysis_geometry_drift", True)
        and all(binding["sources"][role]["status"] == "available"
                for role in ("golden_geometry", "checkpoints", "segments")))
    timing_current = bool(geometry_current and previous.get("timing_fingerprint")
        == current.get("timing_fingerprint") == binding["timing_fingerprint"])
    outputs = manifest.get("analysis_projection_outputs") or {}
    dependencies = {}
    roles = {
        "route_context": "Golden 路線脈絡；來源文字與停留候選，不代表當次現場觀察",
        "architecture": "Golden 記錄與 Ref. 統計的結構比較；固定截止假設另列，不代替已採用日程",
        "navigation": "Golden 幾何與地形候選；不授予可通行或當下行動權限",
    }
    for role, time_role in roles.items():
        artifacts = outputs.get(role, [])
        valid = bool(artifacts) and all(
            item.get("status") in {"ready", "completed", "partial"}
            and ws.digest(item.get("ref")) == item.get("sha256")
            for item in artifacts
        )
        current_inputs = timing_current if role == "architecture" else geometry_current
        dependencies[role] = {
            "status": "current_sources" if current_inputs and valid else "stale_or_unverified",
            "time_role": time_role,
            "schedule_dependency": "source_observation_only",
            "projection_refs": artifacts,
            "reason": None if current_inputs and valid else "Preparation source/output binding is missing or changed; retained reports are not a refreshed analysis.",
        }
    dependencies["permission"] = {
        "status": status, "time_role": "採用後日程的候選情境分析；不授予出發或 runtime 權限",
        "schedule_dependency": "adopted_schedule",
    }
    dependencies["pace_fit"] = {
        "status": status, "time_role": "Golden 原始分日、到離時刻與推估停留；缺口保持未知",
        "schedule_dependency": "adopted_schedule",
    }
    dependencies["weather"] = {
        "status": "separate_current_context", "time_role": "目前現況／預報另列；Golden 歷史天候未知，不能由 GPX 推知",
        "schedule_dependency": "not_historical_weather",
        "historical_weather_status": "unknown",
    }
    mapping = []
    segments = ws.read(binding["sources"]["segments"]["ref"]).get("segments", [])
    for day in days:
        replay = day.get("reference_replay") or {}
        windows = replay.get("checkpoint_windows", [])
        first = (replay.get("start") or {}).get("point_index")
        last = (replay.get("end") or {}).get("point_index")
        cp_segments = []
        if isinstance(first, int) and isinstance(last, int):
            for segment in segments:
                start = segment.get("route_point_start_index")
                end = segment.get("route_point_end_index")
                if not isinstance(start, int) or not isinstance(end, int) or end <= first or start >= last:
                    continue
                cp_segments.append({
                    "segment_id": segment.get("segment_candidate_id"),
                    "from_checkpoint_id": segment.get("from_candidate_id"),
                    "to_checkpoint_id": segment.get("to_candidate_id"),
                    "overlap_start_point_index": max(start, first),
                    "overlap_end_point_index": min(end, last),
                    "crosses_day_boundary": start < first or end > last,
                })
        mapping.append({
            "mission_day_id": day.get("mission_day_id"),
            "source_day_id": replay.get("source_day_id"),
            "segment_ids": day.get("segment_ids", []),
            "checkpoint_ids": [item.get("anchor_id") for item in windows],
            "start_point_index": first, "end_point_index": last,
            "cp_segments": cp_segments,
        })
    revision = _digest({
        "project_id": binding["project_id"], "geometry": binding["geometry_fingerprint"],
        "recorded_timing": binding["timing_fingerprint"],
        "selected_baseline_sha256": project.get("reviewed_mission_baseline_sha256"),
        "planned_eta_sha256": ws.digest(project.get("planned_eta_ref", "outputs/planned_eta.json")),
        "schedule_status": status, "policy": "golden_observations_and_adopted_schedule.v1",
    })
    return AnalysisSubject(
        project_id=binding["project_id"],
        subject_id="golden." + str(binding["sources"]["golden_geometry"]["sha256"] or "missing"),
        analysis_revision=revision,
        geometry_fingerprint=binding["geometry_fingerprint"], timing_fingerprint=binding["timing_fingerprint"],
        sources=binding["sources"], selected_baseline_ref=project.get("reviewed_mission_baseline_ref"),
        original_golden_provenance={
            "source_ref": original.get("source_path"),
            "recorded_sha256": original.get("source_sha256"),
            "role": "original_import_provenance; filtered Golden is the geometry/time analysis source",
            "source_file_reopened": False,
        },
        selected_baseline_sha256=project.get("reviewed_mission_baseline_sha256"),
        schedule_status=status, schedule_time_role="historical_reconstruction" if reconstruction else "planning_assumption_or_unknown",
        timezone=reconstruction.get("timezone"), mission_day_estimates=days,
        day_segment_mapping=mapping,
        overnight_gaps=reconstruction.get("overnight_gaps", []) if status == "adopted" else [],
        unknown_ranges=reconstruction.get("unknown_ranges", []) if status == "adopted" else [],
        dependencies=dependencies, issues=issues,
    )


def _build_planned_analysis_subject(project_root: Path, bundle: dict) -> AnalysisSubject:
    """Expose the selected plan's own graph and timetable, with honest gaps."""
    from scout_planned_route_artifacts import STORE_REF, planned_day_bindings

    ws = _Workspace(Path(project_root))
    manifest, preview = bundle["manifest"], bundle["preview"]
    version_id = manifest["version_id"]
    prefix = f"{STORE_REF}/versions/{version_id}"
    current = bundle["source_status"]["status"] == "current"
    axis = preview.get("route_axis")
    checkpoints, segments = preview.get("checkpoints", []), preview.get("segments", [])
    graph_present = bool(axis and checkpoints and segments)
    itinerary = preview.get("itinerary") or {}
    coverage = preview.get("coverage") or {"status": "unverified", "reason": "Planned map/DEM coverage has not been verified."}
    coverage_needed = coverage.get("status") not in {"within_existing_coverage", "existing_golden_scope"}
    reason = ("Saved planning sources changed; create and review a new Planned version." if not current
              else "The Planned route axis or checkpoint/segment graph is missing." if not graph_present else None)
    dependencies = {}
    for role in ("permission", "pace_fit"):
        dependencies[role] = {
            "status": "current_planned_candidate" if current and graph_present else "needs_reanalysis",
            "subject_version_id": version_id, "geometry_sha256": manifest["geometry_sha256"],
            "itinerary_sha256": manifest["itinerary_sha256"], "schedule_dependency": "reviewed_planned_itinerary",
            "time_role": "人工規劃的移動／休息／紮營時間；未知保留，不是歷史記錄或出發許可",
            "reason": reason,
            "legacy_projection_status": "golden_only_not_applicable_to_planned",
        }
    for role in ("architecture", "navigation", "route_context", "weather"):
        dependencies[role] = {
            "status": "coverage_needed" if coverage_needed and role in {"navigation", "weather", "route_context"} else "needs_reanalysis",
            "subject_version_id": version_id, "geometry_sha256": manifest["geometry_sha256"],
            "itinerary_sha256": manifest["itinerary_sha256"], "schedule_dependency": "planned_route_and_itinerary",
            "time_role": "Planned 新路線／日程；既有 Golden 分析不是此版本的重分析",
            "reason": reason or (coverage.get("reason") if coverage_needed and role in {"navigation", "weather", "route_context"}
                                  else f"No {role} projection is bound to Planned version {version_id}."),
            "projection_refs": [], "legacy_projection_status": "golden_only_not_applicable_to_planned",
        }
    dependencies["weather"].update(historical_weather_status="unknown", current_forecast_status="requires_planned_route_binding")
    sources = {
        "planned_geometry": ws.source(f"{prefix}/planned.gpx", manifest["files"]["planned.gpx"]["sha256"]),
        "planned_itinerary": ws.source(f"{prefix}/itinerary.json", manifest["files"]["itinerary.json"]["sha256"]),
        "planned_route_axis": ws.source(f"{prefix}/route_axis.json", manifest["files"]["route_axis.json"]["sha256"]),
        "checkpoints": ws.source(f"{prefix}/checkpoints.json", manifest["files"]["checkpoints.json"]["sha256"]),
        "segments": ws.source(f"{prefix}/segments.json", manifest["files"]["segments.json"]["sha256"]),
    }
    for index, (ref, expected) in enumerate(manifest["source_hashes"].items()):
        sources[f"source_{index}"] = ws.source(ref, expected)
    return AnalysisSubject(
        project_id=manifest["project_id"], subject_kind="planned_gpx", subject_id=version_id,
        analysis_revision=_digest({"selection": bundle["selection"]["selection_sha256"],
                                   "manifest": manifest["manifest_sha256"], "source_status": bundle["source_status"],
                                   "dependencies": dependencies}),
        geometry_fingerprint=manifest["geometry_sha256"], timing_fingerprint=manifest["itinerary_sha256"],
        sources=sources, selected_plan_version_id=version_id,
        planned_bundle_ref=f"{prefix}/manifest.json", planned_bundle_sha256=manifest["manifest_sha256"],
        planning_review_ref=bundle["review"]["review_ref"],
        selected_baseline_ref=f"{prefix}/mission_baseline_candidate.json",
        selected_baseline_sha256=manifest["files"]["mission_baseline_candidate.json"]["sha256"],
        original_golden_provenance={"role": "Preserved source and accepted baseline; Planned is a separate candidate version.",
                                    "golden_baseline_mutated": False},
        schedule_status="planned_reviewed" if current and graph_present else "stale" if not current else "needs_reanalysis",
        schedule_time_role="planned_estimate", timezone=itinerary.get("timezone"),
        mission_day_estimates=itinerary.get("days", []) if current and graph_present else [],
        day_segment_mapping=planned_day_bindings(preview),
        unknown_ranges=[item if isinstance(item, dict) else {"reason": str(item)} for item in itinerary.get("unknowns", [])],
        overnight_gaps=[item for item in itinerary.get("timeline", []) if item.get("kind") in {"camp", "overnight"}],
        dependencies=dependencies, issues=[reason] if reason else [],
        route_axis=axis, planned_route_geojson=preview.get("route_geojson"), checkpoints=checkpoints, segments=segments,
        itinerary=itinerary, comparison=preview.get("comparison"), coverage=coverage,
    )


def build_analysis_subject(project_root: Path) -> AnalysisSubject:
    from scout_planned_route_artifacts import selected_planned_bundle
    from scout_planned_route_models import PlannedRouteConflict

    try:
        planned = selected_planned_bundle(project_root)
    except (PlannedRouteConflict, ValueError, TypeError, KeyError) as exc:
        # An invalid selected plan cannot silently reveal old Golden outputs as
        # if they satisfied the user's new analysis selection.
        reason = getattr(exc, "code", "invalid_planned_selection")
        return AnalysisSubject(
            project_id=Path(project_root).name, subject_kind="unresolved_selection", subject_id="selection.invalid",
            analysis_revision=_digest({"project": str(project_root), "issue": reason}),
            geometry_fingerprint=_digest(None), timing_fingerprint=_digest(None), sources={},
            schedule_status="blocked", schedule_time_role="unknown", issues=[reason],
            dependencies={role: {"status": "needs_reanalysis", "reason": reason}
                          for role in ("permission", "pace_fit", "architecture", "navigation", "route_context", "weather")},
        )
    return (_build_planned_analysis_subject(project_root, planned) if planned is not None
            else _build_golden_analysis_subject(project_root))
