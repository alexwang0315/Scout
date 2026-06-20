from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from admin_map_layers import (  # noqa: E402
    WORKSPACE_LAYER_CONTROL_IDS,
    _LAYER_SPECS,
    build_after_action_map_layers,
    build_pretrip_map_layers,
    map_layer_ids,
)
from pretrip_layer_preparation import ALLOWED_LAYERS, DEFAULT_LAYERS  # noqa: E402
from scout_layer_contract import (  # noqa: E402
    SCOUT_LAYER_CONTRACT,
    SCOUT_LAYER_CONTRACT_BY_ID,
    SCOUT_LAYER_HTML_FILES,
    SCOUT_LAYER_IDS,
    SCOUT_LAYER_RANKS,
    SCOUT_PREPARATION_LAYER_IDS,
    SCOUT_SURFACE_LAYER_IDS,
)


RASTER_SOURCE_LAYER_IDS = {
    "imagery",
    "rudy",
    "rudy-twmap",
    "relief",
    "geology",
    "topo-5k",
    "forest",
}


def run_checks(
    *,
    repo_root: Path = ROOT,
    project_root: Path | None = None,
    require_workspace: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    layer_results: dict[str, dict[str, Any]] = {
        layer_id: {
            "layer_id": layer_id,
            "contract": True,
            "html": {},
            "python": {},
            "workspace": {},
            "ok": True,
        }
        for layer_id in SCOUT_LAYER_IDS
    }

    _check_canonical_contract(layer_results, errors)
    _check_admin_map_layer_specs(layer_results, errors)
    _check_html_surfaces(repo_root, layer_results, errors)
    _check_layer_preparation_contract(layer_results, errors)
    _check_workspace_project(project_root, require_workspace, layer_results, errors, warnings)

    for layer in layer_results.values():
        layer["ok"] = not any(
            entry is False
            for section in ("python", "html", "workspace")
            for entry in layer[section].values()
        )

    return {
        "ok": not errors,
        "layer_count": len(SCOUT_LAYER_IDS),
        "layers": layer_results,
        "errors": errors,
        "warnings": warnings,
    }


def _check_canonical_contract(
    layer_results: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    if len(SCOUT_LAYER_IDS) != 30:
        errors.append(f"expected 30 Scout layers, got {len(SCOUT_LAYER_IDS)}")
    if len(set(SCOUT_LAYER_IDS)) != len(SCOUT_LAYER_IDS):
        errors.append("Scout layer contract contains duplicate layer ids")
    for layer in SCOUT_LAYER_CONTRACT:
        layer_id = str(layer["layer_id"])
        missing_fields = [
            field
            for field in (
                "required_behavior",
                "components",
                "dependencies",
                "states",
                "verification",
                "surfaces",
                "z_index",
                "render_mode",
                "source_kind",
            )
            if field not in layer or layer.get(field) in (None, "", (), [])
        ]
        if missing_fields:
            errors.append(f"{layer_id}: missing contract fields {missing_fields}")
            layer_results[layer_id]["contract"] = False


def _check_admin_map_layer_specs(
    layer_results: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    if tuple(WORKSPACE_LAYER_CONTROL_IDS) != SCOUT_LAYER_IDS:
        errors.append(
            "admin_map_layers.WORKSPACE_LAYER_CONTROL_IDS does not match "
            "scout_layer_contract.SCOUT_LAYER_IDS"
        )
    missing_specs = [layer_id for layer_id in SCOUT_LAYER_IDS if layer_id not in _LAYER_SPECS]
    extra_specs = [layer_id for layer_id in _LAYER_SPECS if layer_id not in SCOUT_LAYER_IDS]
    if missing_specs:
        errors.append(f"admin_map_layers missing specs: {missing_specs}")
    if extra_specs:
        errors.append(f"admin_map_layers has extra specs: {extra_specs}")

    for layer_id in SCOUT_LAYER_IDS:
        spec = _LAYER_SPECS.get(layer_id)
        contract = SCOUT_LAYER_CONTRACT_BY_ID[layer_id]
        result = layer_results[layer_id]["python"]
        result["spec_present"] = spec is not None
        if spec is None:
            continue
        checks = {
            "z_index": spec.z_index == int(contract["z_index"]),
            "render_mode": spec.render_mode == contract["render_mode"],
            "source_kind": spec.source_kind == contract["source_kind"],
            "label": spec.label == contract["label"],
            "label_zh": spec.label_zh == contract["label_zh"],
            "default_enabled": spec.default_enabled
            == bool(contract.get("default_enabled", True)),
        }
        result.update(checks)
        for check_name, ok in checks.items():
            if not ok:
                errors.append(f"{layer_id}: admin_map_layers {check_name} diverges")

    pretrip_ids = tuple(
        map_layer_ids(build_pretrip_map_layers(source_refs={}, weather={}))
    )
    after_action_ids = tuple(
        map_layer_ids(
            build_after_action_map_layers(
                map_source_path="tests/fixtures/admin/map_context.json",
                map_metadata={"source": "openstreetmap_overpass"},
            )
        )
    )
    expected_sorted_ids = tuple(
        sorted(
            SCOUT_LAYER_IDS,
            key=lambda layer_id: (
                SCOUT_LAYER_RANKS[layer_id],
                SCOUT_LAYER_IDS.index(layer_id),
            ),
        )
    )
    if pretrip_ids != expected_sorted_ids:
        errors.append(
            f"build_pretrip_map_layers order mismatch: {pretrip_ids} != {expected_sorted_ids}"
        )
    if after_action_ids != expected_sorted_ids:
        errors.append(
            "build_after_action_map_layers order mismatch: "
            f"{after_action_ids} != {expected_sorted_ids}"
        )


def _check_html_surfaces(
    repo_root: Path,
    layer_results: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    for surface, relative_path in SCOUT_LAYER_HTML_FILES.items():
        html_path = repo_root / relative_path
        text = html_path.read_text()
        controls = {
            match
            for match in re.findall(r'<input[^>]+data-layer="([^"]+)"', text)
            if "$" not in match
        }
        ranks = _extract_map_layer_ranks(text)
        groups = _extract_static_layer_groups(text)
        expected = set(SCOUT_SURFACE_LAYER_IDS[surface])
        missing_controls = sorted(expected - controls)
        extra_controls = sorted(controls - set(SCOUT_LAYER_IDS))
        if missing_controls:
            errors.append(f"{surface}: missing layer controls {missing_controls}")
        if extra_controls:
            errors.append(f"{surface}: unknown layer controls {extra_controls}")

        for layer_id in SCOUT_LAYER_IDS:
            expected_on_surface = layer_id in expected
            result = layer_results[layer_id]["html"].setdefault(surface, {})
            result["expected_control"] = expected_on_surface
            result["control_present"] = layer_id in controls
            result["rank_present"] = layer_id in ranks
            result["rank_matches_contract"] = (
                not expected_on_surface
                or ranks.get(layer_id) == SCOUT_LAYER_RANKS[layer_id]
            )
            result["render_group_present"] = (
                not expected_on_surface
                or layer_id in groups
                or _has_dynamic_raster_group(text, layer_id)
            )
            if expected_on_surface and not result["control_present"]:
                errors.append(f"{surface}:{layer_id}: missing data-layer control")
            if expected_on_surface and not result["rank_present"]:
                errors.append(f"{surface}:{layer_id}: missing MAP_LAYER_RANKS entry")
            if expected_on_surface and not result["rank_matches_contract"]:
                errors.append(
                    f"{surface}:{layer_id}: MAP_LAYER_RANKS {ranks.get(layer_id)} "
                    f"!= contract {SCOUT_LAYER_RANKS[layer_id]}"
                )
            if expected_on_surface and not result["render_group_present"]:
                errors.append(f"{surface}:{layer_id}: missing render group")


def _check_layer_preparation_contract(
    layer_results: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    missing_default = [
        layer_id for layer_id in SCOUT_PREPARATION_LAYER_IDS if layer_id not in DEFAULT_LAYERS
    ]
    missing_allowed = [
        layer_id for layer_id in SCOUT_PREPARATION_LAYER_IDS if layer_id not in ALLOWED_LAYERS
    ]
    if missing_default:
        errors.append(f"pretrip_layer_preparation.DEFAULT_LAYERS missing {missing_default}")
    if missing_allowed:
        errors.append(f"pretrip_layer_preparation.ALLOWED_LAYERS missing {missing_allowed}")

    for prep_layer_id in SCOUT_PREPARATION_LAYER_IDS:
        ui_layer_id = "weather-api" if prep_layer_id == "weather" else prep_layer_id
        if ui_layer_id in layer_results:
            layer_results[ui_layer_id]["python"]["preparation_default"] = (
                prep_layer_id in DEFAULT_LAYERS
            )
            layer_results[ui_layer_id]["python"]["preparation_allowed"] = (
                prep_layer_id in ALLOWED_LAYERS
            )


def _check_workspace_project(
    project_root: Path | None,
    require_workspace: bool,
    layer_results: dict[str, dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> None:
    if project_root is None:
        if require_workspace:
            errors.append("--require-workspace was set but --project-root was not provided")
        return
    project_json_path = project_root / "project.json"
    if not project_json_path.exists():
        message = f"workspace project.json not found: {project_json_path}"
        if require_workspace:
            errors.append(message)
        else:
            warnings.append(message)
        return
    project = json.loads(project_json_path.read_text())
    refs = _collect_project_refs(project)
    counts = project.get("counts") if isinstance(project.get("counts"), dict) else {}
    required_refs = {
        "terrain": ("terrain_visualization", "terrain_visualization_ref"),
        "risk-score": ("risk_score_points", "risk_score_points_ref"),
        "risk-ribbon": ("risk_ribbon", "risk_ribbon_ref"),
        "risk-heatmap": ("calibrated_risk_heatmap", "calibrated_risk_heatmap_ref"),
        "risk-delta": ("risk_delta", "risk_delta_ref"),
        "overpass": ("overpass_evidence", "overpass_evidence_ref"),
        "route": ("route_summary", "route_summary_ref"),
        "reference-tracks": ("reference_track_display_geometry", "reference_tracks"),
        "segments": ("segments", "segments_ref", "overpass_aligned_segments"),
        "checkpoints": ("checkpoints", "checkpoints_ref", "overpass_aligned_checkpoints"),
        "mcp": ("mcp_candidates", "mcp_candidates_ref", "overpass_aligned_mcp_candidates"),
        "boss-points": ("boss_points", "boss_points_ref", "boss_points_geojson"),
    }
    for layer_id, keys in required_refs.items():
        present = any(key in refs and refs[key] for key in keys)
        layer_results[layer_id]["workspace"]["source_ref_present"] = present
        if require_workspace and not present:
            errors.append(f"workspace:{layer_id}: missing one of refs {keys}")

    count_expectations = {
        "risk-score": ("risk_score_point_count", "risk_score_points_count"),
        "risk-ribbon": ("risk_ribbon_point_count", "risk_ribbon_count"),
        "risk-heatmap": ("calibrated_risk_heatmap_point_count", "risk_heatmap_count"),
        "segments": ("segment_count",),
        "checkpoints": ("checkpoint_count",),
        "mcp": ("mcp_candidate_count",),
        "boss-points": ("boss_point_count", "boss_points_count"),
    }
    for layer_id, keys in count_expectations.items():
        count_value = next((counts.get(key) for key in keys if key in counts), None)
        ok = isinstance(count_value, int) and count_value > 0
        layer_results[layer_id]["workspace"]["positive_count"] = ok
        layer_results[layer_id]["workspace"]["count_value"] = count_value
        if require_workspace and not ok:
            errors.append(f"workspace:{layer_id}: missing positive count in {keys}")


def _collect_project_refs(project: dict[str, Any]) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for key in ("refs", "source_refs", "outputs", "artifacts"):
        value = project.get(key)
        if isinstance(value, dict):
            refs.update(value)
    return refs


def _extract_map_layer_ranks(text: str) -> dict[str, int]:
    match = re.search(r"const\s+MAP_LAYER_RANKS\s*=\s*\{(?P<body>.*?)\n\s*\};", text, re.S)
    if not match:
        return {}
    ranks: dict[str, int] = {}
    for quoted, bare, value in re.findall(
        r'(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*:\s*(\d+)',
        match.group("body"),
    ):
        ranks[quoted or bare] = int(value)
    return ranks


def _extract_static_layer_groups(text: str) -> set[str]:
    groups = set(re.findall(r'data-layer-group="([^"]+)"', text))
    groups.update(re.findall(r'"data-layer-group"\s*:\s*"([^"]+)"', text))
    groups.update(re.findall(r"'data-layer-group'\s*:\s*'([^']+)'", text))
    return groups


def _has_dynamic_raster_group(text: str, layer_id: str) -> bool:
    if layer_id not in RASTER_SOURCE_LAYER_IDS:
        return False
    return f'layerId: "{layer_id}"' in text or f"layerId: '{layer_id}'" in text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--require-workspace", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run_checks(
        repo_root=args.repo_root,
        project_root=args.project_root,
        require_workspace=args.require_workspace,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"{status}: Scout layer contract ({result['layer_count']} layers)")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
