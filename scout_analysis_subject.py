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
                payload = json.loads(path.read_text(encoding="utf-8"))
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
    golden_ref = primary.get("output_path") or golden.get("source_path") or golden.get("source_gpx")
    sources = {
        "golden_geometry": ws.source(golden_ref, primary.get("output_sha256")),
        "checkpoints": ws.source(project.get("checkpoint_candidates_ref", "candidates/checkpoints.json")),
        "segments": ws.source(project.get("segment_display_geometry_ref", "outputs/segment_display_geometry.json")),
        "checkpoint_times": ws.source(project.get("checkpoint_events_ref", "outputs/checkpoint_events.json")),
        "reference_tracks": ws.source(project.get("reference_tracks_ref", "outputs/reference_tracks.json")),
        "recorded_pace": ws.source(project.get("reference_pace_energy_analysis_ref", "outputs/reference_pace_energy_analysis.json")),
    }
    identity = {key: {k: value[k] for k in ("ref", "sha256", "status")}
                for key, value in sources.items()}
    return {
        "schema_version": "analysisGeometryBinding.v1",
        "project_id": project.get("project_id", ws.root.name),
        "geometry_fingerprint": _digest({key: identity[key] for key in (
            "golden_geometry", "checkpoints", "segments", "reference_tracks",
        )}),
        "timing_fingerprint": _digest({key: identity[key] for key in (
            "golden_geometry", "checkpoint_times", "recorded_pace",
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
            or candidate.get("days") != reviewed.get("days")
            or candidate.get("reference_reconstruction") != reviewed.get("reference_reconstruction")):
        return "stale", {}, {}, ["baseline_candidate_lineage_mismatch"]
    reconstruction = reviewed.get("reference_reconstruction") or {}
    for source_ref, expected in (reconstruction.get("source_hashes") or {}).items():
        if ws.digest(source_ref) != expected:
            return "stale", reviewed, {}, ["reviewed_source_changed"]
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


def build_analysis_subject(project_root: Path) -> AnalysisSubject:
    ws = _Workspace(Path(project_root))
    project = ws.read("project.json")
    binding = _geometry_binding(ws, project)
    status, reviewed, eta, issues = _schedule(ws, project)
    reconstruction = reviewed.get("reference_reconstruction") or {}
    days = eta.get("mission_day_estimates", []) if status == "adopted" else []
    manifest = ws.read(project.get("layer_preparation_manifest_ref", "outputs/layers/layer_preparation_manifest.json"))
    previous = manifest.get("analysis_geometry_binding") or {}
    current = manifest.get("analysis_geometry_binding_current") or {}
    geometry_current = bool(previous and current
        and previous.get("geometry_fingerprint") == current.get("geometry_fingerprint") == binding["geometry_fingerprint"]
        and not manifest.get("analysis_geometry_drift", True))
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
    for day in days:
        replay = day.get("reference_replay") or {}
        windows = replay.get("checkpoint_windows", [])
        mapping.append({
            "mission_day_id": day.get("mission_day_id"),
            "source_day_id": replay.get("source_day_id"),
            "segment_ids": day.get("segment_ids", []),
            "checkpoint_ids": [item.get("anchor_id") for item in windows],
            "start_point_index": (replay.get("start") or {}).get("point_index"),
            "end_point_index": (replay.get("end") or {}).get("point_index"),
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
        selected_baseline_sha256=project.get("reviewed_mission_baseline_sha256"),
        schedule_status=status, schedule_time_role="historical_reconstruction" if reconstruction else "planning_assumption_or_unknown",
        timezone=reconstruction.get("timezone"), mission_day_estimates=days,
        day_segment_mapping=mapping,
        overnight_gaps=reconstruction.get("overnight_gaps", []) if status == "adopted" else [],
        unknown_ranges=reconstruction.get("unknown_ranges", []) if status == "adopted" else [],
        dependencies=dependencies, issues=issues,
    )
