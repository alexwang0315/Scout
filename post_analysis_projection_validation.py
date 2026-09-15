"""Validate persisted post-analysis selections before attaching any derived evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from post_analysis_capability import summarize_capability_artifacts


class _InvalidProjection(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_validated_active_projection(
    *,
    active_path: Path,
    case_id: str,
    project_id: str | None,
    selection_key: str,
    outputs_parent: Path,
    outputs_leaf: str,
    active_track_path: Path,
    route_family: str,
    root: Path,
    completed_track_builder: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Read one coherent selection; reject stale/cross-project derived artifacts.

    Paths supplied by the service come from the requested workspace or the
    fixed legacy case layout, never from the persisted record being checked.
    Legacy records may omit project_id, but must retain the fixed case_id.
    """
    if not active_path.exists() and not active_path.is_symlink():
        return None
    snapshots: dict[Path, str] = {}

    def reject(code: str, message: str) -> None:
        raise _InvalidProjection(code, message)

    def regular_path(path: Path, expected: Path, label: str) -> Path:
        actual = path.expanduser().absolute()
        target = expected.expanduser().absolute()
        if actual.resolve() != target or target.resolve() != target:
            reject(f"{label}_path_mismatch", f"{label} 路徑不屬於目前選取的行程，已拒收後分析結果。")
        if not target.is_file():
            reject(f"{label}_missing", f"缺少 {label}；請重新選取紀錄並完成後分析。")
        return target

    def read_object(path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        snapshots[path] = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw)
        if not isinstance(value, dict):
            reject("artifact_invalid", "後分析資料格式不正確，已拒收。")
        return value

    validation: dict[str, Any] = {
        "status": "rejected",
        "case_id": case_id,
        "project_id": project_id or case_id,
        "active_record_path": str(active_path),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }
    try:
        regular_path(active_path, active_path, "active_record")
        active = read_object(active_path)
        if active.get("case_id") != case_id:
            reject("case_id_mismatch", "啟用紀錄的行程身分與目前行程不同，已拒收。")
        recorded_project_id = active.get("project_id")
        if (project_id is not None and recorded_project_id != project_id) or (
            recorded_project_id is not None and recorded_project_id != case_id
        ):
            reject("project_id_mismatch", "啟用紀錄的 workspace 與目前 workspace 不同，已拒收。")
        selection = active.get(selection_key)
        if not isinstance(selection, dict):
            reject("selection_missing", "缺少選取紀錄的身分；請重新選取紀錄。")
        selection_id = selection.get(f"{selection_key}_id")
        if (
            not isinstance(selection_id, str)
            or not selection_id
            or selection_id in {".", ".."}
            or Path(selection_id).name != selection_id
            or "\\" in selection_id
        ):
            reject("selection_id_invalid", "選取紀錄的識別碼不正確，已拒收。")
        validation["selection_id"] = selection_id

        expected_outputs = outputs_parent.absolute() / selection_id
        if outputs_leaf:
            expected_outputs /= outputs_leaf
        output_value = active.get("outputs_dir")
        if not isinstance(output_value, str) or not output_value:
            reject("outputs_path_missing", "缺少後分析輸出路徑；請重新選取紀錄。")
        outputs = Path(output_value).expanduser().absolute()
        if outputs.resolve() != expected_outputs or expected_outputs.resolve() != expected_outputs:
            reject("outputs_path_mismatch", "後分析輸出指向其他行程或其他紀錄，已拒收。")

        timeline_path = regular_path(
            outputs / "capability_timeline.json",
            expected_outputs / "capability_timeline.json",
            "timeline",
        )
        capsule_path = regular_path(
            outputs / "capability_capsule.json",
            expected_outputs / "capability_capsule.json",
            "capsule",
        )
        timeline = read_object(timeline_path)
        capsule = read_object(capsule_path)
        analysis_case_id = f"{case_id}.{selection_id}"
        if timeline.get("case_id") != analysis_case_id or capsule.get("case_id") != analysis_case_id:
            reject("analysis_case_id_mismatch", "後分析產物屬於另一段行程紀錄，已拒收。")
        if timeline.get("route_family") != route_family:
            reject("route_family_mismatch", "後分析產物的路線身分與目前 workspace 不同，已拒收。")

        def validate_companion_identity(artifact: dict[str, Any], label: str) -> None:
            # Optional legacy fields may be absent; a supplied identity must agree.
            for field, expected in (("case_id", analysis_case_id), ("route_family", route_family)):
                if field in artifact and artifact[field] != expected:
                    reject(
                        f"companion_{field}_mismatch",
                        f"{label} 的行程或路線身分與目前紀錄不同，已拒收後分析結果。",
                    )

        validate_companion_identity(capsule, "能力摘要")

        track_value = active.get("active_completed_track_gpx")
        if not isinstance(track_value, str) or not track_value:
            reject("active_track_missing", "缺少已選取的 GPX；請重新選取紀錄。")
        track_path = regular_path(Path(track_value), active_track_path, "active_track")
        source = timeline.get("source_track")
        if not isinstance(source, dict) or not source.get("source_path"):
            reject("source_track_missing", "後分析產物缺少 GPX 來源，已拒收。")
        source_path = Path(source["source_path"])
        if not source_path.is_absolute():
            source_path = root / source_path
        if source_path.resolve() != track_path:
            reject("source_track_path_mismatch", "後分析使用的 GPX 路徑與已選取紀錄不同，已拒收。")
        track_sha256 = hashlib.sha256(track_path.read_bytes()).hexdigest()
        snapshots[track_path] = track_sha256
        if source.get("sha256") != track_sha256:
            reject("source_track_hash_mismatch", "GPX 已變動或由其他紀錄取代，後分析結果已過期；請重新選取紀錄。")
        if selection.get("sha256") and selection["sha256"] != track_sha256:
            reject("selection_track_hash_mismatch", "已選取紀錄的 GPX 雜湊不一致，已拒收。")

        # Never trust cached evidence embedded in the active JSON.
        active = {
            key: value
            for key, value in active.items()
            if key not in {"capability_timeline", "scout_reaction_simulation", "completed_trip_track"}
        }
        for name in ("capability_share_preview.json", "capability_route_time_comparison.json"):
            path = outputs / name
            if path.exists() or path.is_symlink():
                regular_path(path, expected_outputs / name, "optional_artifact")
                artifact = read_object(path)
                label = "分享摘要" if name == "capability_share_preview.json" else "路線時間比較"
                validate_companion_identity(artifact, label)
        reaction_path = outputs / "scout_reaction_simulation.json"
        if reaction_path.exists() or reaction_path.is_symlink():
            regular_path(reaction_path, expected_outputs / reaction_path.name, "reaction")
            reaction = read_object(reaction_path)
            if reaction.get("case_id") != case_id or reaction.get("scenario_id") != selection_id:
                reject("reaction_identity_mismatch", "行程反應紀錄屬於其他行程，已拒收。")
            reaction_source = Path(str(reaction.get("source_gpx") or ""))
            if not reaction_source.is_absolute():
                reaction_source = root / reaction_source
            if reaction_source.resolve() != track_path:
                reject("reaction_source_mismatch", "行程反應紀錄使用另一份 GPX，已拒收。")
            active["scout_reaction_simulation"] = reaction
        active["outputs_dir"] = str(expected_outputs)
        active["active_completed_track_gpx"] = str(track_path)
        active["capability_timeline"] = summarize_capability_artifacts(
            timeline_path=timeline_path,
            capsule_path=capsule_path,
            root=root,
        )
        if completed_track_builder is not None:
            active["completed_trip_track"] = completed_track_builder(track_path, active)
        for path, expected_sha256 in snapshots.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
                reject("projection_changed_during_read", "讀取期間行程紀錄已變動；請重新載入。")
        validation.update(status="validated", issues=[], source_track_sha256=track_sha256)
        active["projection_validation"] = validation
        return active
    except _InvalidProjection as exc:
        code, message = exc.code, str(exc)
    except (OSError, ValueError, KeyError, TypeError):
        code, message = "artifact_unreadable", "後分析資料缺少、尚未寫入完成或格式不正確；請重新選取紀錄。"

    validation["issues"] = [{"code": code, "message": message}]
    return {
        "artifact_kind": "rejected_completed_trip_projection",
        "status": "rejected",
        "projection_validation": validation,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "human_review_required": True,
            "workspace_file_mutation_allowed": False,
        },
    }
