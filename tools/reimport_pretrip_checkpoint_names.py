"""Replay GPX import, prove CP identity parity, then replace display names locally.

Prepared GIS evidence and accepted mission baselines are retained. This is a
checkpoint-name reimport, not a connected refresh of weather or map providers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard_workspace_publication import DashboardWorkspacePublication
from pretrip_architecture_preparation import architecture_input_snapshot
from pretrip_checkpoint_naming import POLICY_VERSION, REPORT_REF
from pretrip_gpx_corpus import write_json
from pretrip_import import PretripImportRequest, _stamp_import_checkpoint_candidates, run_pretrip_import
from pretrip_models import PreTripCheckpointCandidate

_IDENTITY_FIELDS = ("candidate_id", "lat", "lon", "route_point_index", "checkpoint_type", "arrival_radius_m", "compression_boundary")
_PROJECTION_REFS = (
    "overpass_aligned_checkpoint_candidates_ref", "package_ref",
    "checkpoint_events_ref", "layer_map_projection_ref",
)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _local_ref(root: Path, ref: str) -> Path:
    path = (root / ref).resolve()
    path.relative_to(root.resolve())
    return path


def verify_checkpoint_identity(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    if len(before) != len(after):
        raise ValueError(f"checkpoint count changed: {len(before)} -> {len(after)}")
    for old, new in zip(before, after):
        for field in _IDENTITY_FIELDS:
            if old.get(field) != new.get(field):
                raise ValueError(f"checkpoint geometry/identity changed: {old.get('candidate_id')} {field}")


def _rewrite_projection(payload: Any, names: dict[str, dict[str, Any]]) -> int:
    changed = 0
    if isinstance(payload, dict):
        identity = next((payload.get(key) for key in ("candidate_id", "checkpoint_candidate_id", "node_id", "checkpoint_id") if payload.get(key) in names), None)
        if identity:
            cp = names[identity]
            for field in ("label", "checkpoint_label"):
                if field in payload and payload[field] != cp["label"]:
                    payload[field] = cp["label"]
                    changed += 1
            if "source_attribution" in payload:
                payload["source_attribution"] = [a for a in payload["source_attribution"] if a.get("source_kind") != "checkpoint_naming"] + [cp["source_attribution"][-1]]
            if payload.get("candidate_id") == identity and "model_output_sha256" in payload:
                payload["model_output_sha256"] = cp["model_output_sha256"]
        for value in payload.values():
            if isinstance(value, (dict, list)):
                changed += _rewrite_projection(value, names)
    elif isinstance(payload, list):
        for value in payload:
            changed += _rewrite_projection(value, names)
    return changed


def _relocate(payload: Any, old_root: Path, new_root: Path) -> Any:
    if isinstance(payload, dict):
        return {key: _relocate(value, old_root, new_root) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_relocate(value, old_root, new_root) for value in payload]
    if isinstance(payload, str) and payload.startswith(str(old_root) + "/"):
        return str(new_root) + payload[len(str(old_root)):]
    return payload


def refresh_architecture_names(stage: Path, project: dict[str, Any], names: dict[str, dict[str, Any]]) -> tuple[dict[str, Any] | None, set[str]]:
    """Project labels over existing measurements; do not rerun pace/risk models.

    Only the CP input hash is advanced. Other recorded inputs stay unchanged,
    so previously stale measurements cannot become fresh through a rename.
    """
    manifest_ref = project.get("architecture_preparation_manifest_ref")
    if not manifest_ref:
        return None, set()
    updated = set()
    labels_updated = 0
    for key in ("reference_pace_energy_analysis_ref", "reference_pace_energy_map_geojson_ref"):
        ref = project.get(key)
        if not ref or not _local_ref(stage, ref).is_file():
            continue
        payload = _read(_local_ref(stage, ref))
        count = _rewrite_projection(payload, names)
        if count:
            write_json(_local_ref(stage, ref), payload)
            updated.add(ref)
        labels_updated += count
    manifest = _read(_local_ref(stage, manifest_ref))
    snapshot = manifest.get("inputs", {})
    for item in snapshot.get("files", []):
        if item.get("input_id") == "checkpoint_candidates":
            item["sha256"] = _sha(_local_ref(stage, project["checkpoint_candidates_ref"]))
    if all(key in snapshot for key in ("project_id", "files", "policy")):
        fingerprint = {key: snapshot[key] for key in ("project_id", "files", "policy")}
        digest = hashlib.sha256(json.dumps(fingerprint, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
        snapshot["input_sha256"] = digest
        manifest["input_sha256"] = digest
        project["architecture_preparation_input_sha256"] = digest
        policy = snapshot["policy"]
        current = architecture_input_snapshot(stage, **{key: policy[key] for key in ("route_bin_m", "match_radius_m", "min_tracks_for_guidance") if key in policy})
        manifest["fresh"] = current["input_sha256"] == digest
    manifest["checkpoint_naming_projection"] = {"policy_version": POLICY_VERSION, "report_ref": REPORT_REF, "label_count": labels_updated, "measurements_recomputed": False}
    write_json(_local_ref(stage, manifest_ref), manifest)
    write_json(stage / "project.json", project)
    updated.add(manifest_ref)
    return {"status": "names_projected", "label_count": labels_updated, "measurements_recomputed": False, "measurement_inputs_fresh": manifest.get("fresh")}, updated


def reimport_checkpoint_names(project_root: Path, *, apply: bool = False, checkpoint_spacing_m: float = 500.0) -> dict[str, Any]:
    live = project_root.expanduser().resolve()
    publication = DashboardWorkspacePublication(live.parent)
    staged = publication.stage(live.name)
    stage = staged.staged_root
    backup = live.parent / ".checkpoint-name-backups" / f"{live.name}.{staged.session_id}"
    try:
        project = _read(stage / "project.json")
        original = _read(_local_ref(stage, project["checkpoint_candidates_ref"]))
        source_manifest = _read(stage / project.get("source_inbox_manifest_ref", "inbox/source_manifest.json"))
        sources = source_manifest["sources"]
        primary = None
        references = []
        for source in sources:
            path = _local_ref(stage, source["workspace_ref"])
            if _sha(path) != source["sha256"]:
                raise ValueError(f"raw GPX hash mismatch: {source['workspace_ref']}")
            if source["role"] == "golden_route_reference":
                if primary is not None:
                    raise ValueError("multiple primary GPX sources")
                primary = path
            else:
                references.append(path)
        if primary is None:
            raise ValueError("no verified primary GPX in source manifest")
        replay_root = staged.session_root / "import-replay"
        old_manifest = _read(stage / project.get("import_manifest_ref", "outputs/import_manifest.json"))
        filtering = old_manifest.get("gpx_speed_filter", {})
        prior_report = _read(stage / REPORT_REF) if (stage / REPORT_REF).is_file() else {}
        replay_manifest = run_pretrip_import(PretripImportRequest(
            project_id=live.name, primary_gpx=primary,
            reference_gpx_paths=tuple(references), workspace_root=replay_root,
            checkpoint_spacing_m=checkpoint_spacing_m,
            max_reasonable_gpx_speed_kmh=filtering.get("max_reasonable_speed_kmh", 120.0),
            max_previous_gpx_speed_ratio=filtering.get("max_previous_speed_ratio", 8.0),
            checkpoint_naming_source_root=stage,
            trusted_checkpoint_name_sha256s=tuple(prior_report.get("policy", {}).get("trusted_source_sha256s", [])),
        ))
        replay = replay_root / live.name
        regenerated = _read(replay / "candidates/checkpoints.json")
        verify_checkpoint_identity(original, regenerated)
        naming = _relocate(_read(replay / REPORT_REF), stage, live)
        named = []
        for old, new in zip(original, regenerated):
            attribution = _relocate(next(a for a in new["source_attribution"] if a.get("source_kind") == "checkpoint_naming"), stage, live)
            updated = {**old, "label": new["label"], "source_refs": list(dict.fromkeys([*old.get("source_refs", []), REPORT_REF])), "source_attribution": [a for a in old.get("source_attribution", []) if a.get("source_kind") != "checkpoint_naming"] + [attribution]}
            named.append(PreTripCheckpointCandidate.model_validate(updated))
        named = _stamp_import_checkpoint_candidates(named, primary_artifact_id=f"artifact.gpx.{live.name}")
        named_rows = [cp.model_dump(mode="json") for cp in named]
        verify_checkpoint_identity(original, named_rows)
        names = {row["candidate_id"]: row for row in named_rows}
        updated_refs = {project["checkpoint_candidates_ref"], REPORT_REF, "project.json"}
        write_json(_local_ref(stage, project["checkpoint_candidates_ref"]), named_rows)
        write_json(stage / REPORT_REF, naming)
        projections = {}
        for key in _PROJECTION_REFS:
            ref = project.get(key)
            if not ref or not _local_ref(stage, ref).is_file():
                continue
            payload = _read(_local_ref(stage, ref))
            projections[key] = _rewrite_projection(payload, names)
            write_json(_local_ref(stage, ref), payload)
            updated_refs.add(ref)
        project.update(checkpoint_naming_ref=REPORT_REF, checkpoint_naming_policy=POLICY_VERSION)
        write_json(stage / "project.json", project)
        architecture, architecture_refs = refresh_architecture_names(stage, project, names)
        updated_refs.update(architecture_refs)
        # Verify the primary consumer actually sees these names after projection.
        aligned_ref = project.get("overpass_aligned_checkpoint_candidates_ref")
        if aligned_ref:
            aligned = _read(_local_ref(stage, aligned_ref))
            if {row["candidate_id"]: row["label"] for row in aligned} != {key: value["label"] for key, value in names.items()}:
                raise ValueError("aligned map checkpoint names differ from import")
        backup.mkdir(parents=True, exist_ok=False)
        changes = []
        for ref in sorted(updated_refs | {".scout-workspace-generation.json"}):
            old_path, new_path = _local_ref(live, ref), _local_ref(stage, ref)
            if not new_path.is_file():
                continue
            if old_path.is_file():
                destination = backup / ref
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_path, destination)
            changes.append({"ref": ref, "before_sha256": _sha(old_path) if old_path.is_file() else None, "after_sha256": _sha(new_path)})
        result = {
            "status": "validated", "scope": "checkpoint_names_from_gpx_import_replay",
            "project_root": str(live), "backup_root": str(backup),
            "checkpoint_count": len(named), "geometry_identity_unchanged": True,
            "naming_counts": naming["counts"], "projections": projections,
            "import_counts": replay_manifest["counts"], "architecture": architecture,
            "changes": changes, "candidate_only": True, "runtime_safety_truth": False,
            "live_network_calls_made": False, "weather_refetched": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json(backup / "reimport_result.json", result)
        if apply:
            result["publication"] = publication.publish(staged)
            result["status"] = "applied"
            write_json(backup / "reimport_result.json", result)
        return result
    finally:
        publication.discard(staged)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--checkpoint-spacing-m", type=float, default=500.0)
    parser.add_argument("--apply", action="store_true", help="Atomically update the local workspace after replay and parity checks.")
    args = parser.parse_args()
    result = reimport_checkpoint_names(args.project_root, apply=args.apply, checkpoint_spacing_m=args.checkpoint_spacing_m)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
