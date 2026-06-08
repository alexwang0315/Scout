from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

from pretrip_spatial_imprint_export import (
    write_pretrip_spatial_imprint_export_for_workspace,
)
from spatial_imprint_models import SpatialImprintSet, SpatialImprintTriggerContext
from spatial_imprint_store import (
    delete_spatial_imprint_tombstone,
    expire_spatial_imprint,
    load_spatial_imprint_store,
    plant_spatial_imprint,
    spatial_imprint_set_from_store,
)
from spatial_imprint_trigger import evaluate_spatial_imprints


def run_spatial_imprint_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "trigger-dry-run":
        return _run_trigger_dry_run(args)
    if args.command == "export-pretrip":
        return _run_export_pretrip(args)
    if args.command == "store-list":
        return _run_store_list(args)
    if args.command == "plant":
        return _run_plant(args)
    if args.command == "expire":
        return _run_expire(args)
    if args.command == "delete":
        return _run_delete(args)
    parser.error("missing command")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    exit_code, payload = _run_parsed(args, parser)
    output_path = getattr(args, "output", None)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(_json(payload), encoding="utf-8")
    else:
        sys.stdout.write(_json(payload))
    return exit_code


def _run_parsed(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[int, dict[str, Any]]:
    if args.command == "trigger-dry-run":
        return _run_trigger_dry_run(args)
    if args.command == "export-pretrip":
        return _run_export_pretrip(args)
    if args.command == "store-list":
        return _run_store_list(args)
    if args.command == "plant":
        return _run_plant(args)
    if args.command == "expire":
        return _run_expire(args)
    if args.command == "delete":
        return _run_delete(args)
    parser.error("missing command")


def _run_trigger_dry_run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        imprint_set = SpatialImprintSet.model_validate(_load_json(args.imprint_set))
        context = SpatialImprintTriggerContext.model_validate(_load_json(args.context))
        report = evaluate_spatial_imprints(
            imprint_set,
            context,
            previous_trigger_keys=tuple(args.previous_trigger_key or []),
        )
    except (OSError, ValueError, ValidationError) as exc:
        return (
            2,
            {
                "artifact_kind": "spatial_imprint_trigger_dry_run_error",
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "live_safety_api_calls_allowed": False,
                "phase1_safety_mutation_allowed": False,
                "remote_outbound_send_allowed": False,
            },
        )
    payload = report.model_dump(mode="json")
    return 0, payload


def _run_export_pretrip(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        manifest = write_pretrip_spatial_imprint_export_for_workspace(args.project_root)
    except (OSError, ValueError, ValidationError) as exc:
        return (
            2,
            {
                "artifact_kind": "spatial_imprint_export_pretrip_error",
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "live_safety_api_calls_allowed": False,
                "phase1_safety_mutation_allowed": False,
                "remote_outbound_send_allowed": False,
                "hardware_control_allowed": False,
            },
        )
    return 0, manifest.model_dump(mode="json")


def _run_store_list(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        store = load_spatial_imprint_store(args.store, trip_id=args.trip_id)
        imprint_set = spatial_imprint_set_from_store(
            store,
            include_inactive=args.include_inactive,
        )
    except (OSError, ValueError, ValidationError) as exc:
        return _store_error(exc)
    return (
        0,
        {
            "artifact_kind": "spatial_imprint_store_list",
            "status": "completed",
            "store": store.model_dump(mode="json"),
            "active_imprint_set": imprint_set.model_dump(mode="json"),
            "boundary": _store_boundary(),
        },
    )


def _run_plant(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        store = plant_spatial_imprint(
            args.store,
            _load_json(args.input),
            trip_id=args.trip_id,
            authorized_by=args.authorized_by,
            planted_at=args.planted_at,
            reason=args.reason,
            allow_admin_persistent=args.allow_admin_persistent,
        )
    except (OSError, ValueError, ValidationError) as exc:
        return _store_error(exc)
    return (
        0,
        {
            "artifact_kind": "spatial_imprint_store_write_result",
            "status": "completed",
            "action": "planted",
            "store": store.model_dump(mode="json"),
            "boundary": _store_boundary(),
        },
    )


def _run_expire(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        store = expire_spatial_imprint(
            args.store,
            imprint_id=args.imprint_id,
            authorized_by=args.authorized_by,
            expired_at=args.expired_at,
            reason=args.reason,
        )
    except (OSError, ValueError, ValidationError) as exc:
        return _store_error(exc)
    return (
        0,
        {
            "artifact_kind": "spatial_imprint_store_write_result",
            "status": "completed",
            "action": "expired",
            "store": store.model_dump(mode="json"),
            "boundary": _store_boundary(),
        },
    )


def _run_delete(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        store = delete_spatial_imprint_tombstone(
            args.store,
            imprint_id=args.imprint_id,
            authorized_by=args.authorized_by,
            deleted_at=args.deleted_at,
            reason=args.reason,
        )
    except (OSError, ValueError, ValidationError) as exc:
        return _store_error(exc)
    return (
        0,
        {
            "artifact_kind": "spatial_imprint_store_write_result",
            "status": "completed",
            "action": "deleted_tombstone",
            "store": store.model_dump(mode="json"),
            "boundary": _store_boundary(),
        },
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scout Spatial Imprint CLI.")
    subparsers = parser.add_subparsers(dest="command")
    trigger = subparsers.add_parser(
        "trigger-dry-run",
        description="Evaluate a spatial imprint set against a fixture trigger context.",
    )
    trigger.add_argument("--imprint-set", type=Path, required=True)
    trigger.add_argument("--context", type=Path, required=True)
    trigger.add_argument("--output", type=Path)
    trigger.add_argument("--previous-trigger-key", action="append", default=[])

    export_pretrip = subparsers.add_parser(
        "export-pretrip",
        description="Export reviewed pretrip spatial imprints into an advisory imprint set.",
    )
    export_pretrip.add_argument("--project-root", type=Path, required=True)
    export_pretrip.add_argument("--output", type=Path)

    store_list = subparsers.add_parser(
        "store-list",
        description="List a runtime spatial imprint store and active trigger set.",
    )
    store_list.add_argument("--store", type=Path, required=True)
    store_list.add_argument("--trip-id")
    store_list.add_argument("--include-inactive", action="store_true")
    store_list.add_argument("--output", type=Path)

    plant = subparsers.add_parser(
        "plant",
        description="Plant an authorized runtime spatial imprint into a local store.",
    )
    plant.add_argument("--store", type=Path, required=True)
    plant.add_argument("--input", type=Path, required=True)
    plant.add_argument("--trip-id", required=True)
    plant.add_argument("--authorized-by", required=True)
    plant.add_argument("--planted-at")
    plant.add_argument("--reason")
    plant.add_argument("--allow-admin-persistent", action="store_true")
    plant.add_argument("--output", type=Path)

    expire = subparsers.add_parser(
        "expire",
        description="Expire an imprint by setting expires_at while keeping audit history.",
    )
    expire.add_argument("--store", type=Path, required=True)
    expire.add_argument("--imprint-id", required=True)
    expire.add_argument("--authorized-by", required=True)
    expire.add_argument("--expired-at")
    expire.add_argument("--reason")
    expire.add_argument("--output", type=Path)

    delete = subparsers.add_parser(
        "delete",
        description="Delete an imprint by writing a tombstone lifecycle state.",
    )
    delete.add_argument("--store", type=Path, required=True)
    delete.add_argument("--imprint-id", required=True)
    delete.add_argument("--authorized-by", required=True)
    delete.add_argument("--deleted-at")
    delete.add_argument("--reason")
    delete.add_argument("--output", type=Path)
    return parser


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _store_error(exc: Exception) -> tuple[int, dict[str, Any]]:
    return (
        2,
        {
            "artifact_kind": "spatial_imprint_store_error",
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "boundary": _store_boundary(),
        },
    )


def _store_boundary() -> dict[str, bool]:
    return {
        "advisory_cue_store": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
