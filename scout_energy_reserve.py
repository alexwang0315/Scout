from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from scout_companion_match_models import build_companion_capability_capsule
from scout_energy_baseline import build_energy_reserve_baseline
from scout_energy_models import (
    ScoutEnergyReserveBaseline,
    ScoutEnergyReserveExplanation,
    WearableActivitySummary,
    aggregate_sha256,
    load_wearable_activity_summaries,
)
from scout_wearable_adapters import write_normalized_wearable_imports
from scout_wearable_live_frames import write_field_observations_from_live_frame_fixture
from scout_wearable_raw_importers import (
    inspect_provider_archive,
    write_sanitized_import_batch_from_provider_api_fixture,
    write_sanitized_import_batch_from_provider_archive,
    write_sanitized_import_batch_from_raw_file,
    write_sanitized_import_from_raw_file,
)


ENERGY_BASELINE_FILENAME = "scout_energy_reserve_baseline.json"
ENERGY_EXPLANATION_FILENAME = "scout_energy_reserve_explanation.json"
COMPANION_CAPSULE_FILENAME = "scout_companion_capability_capsule.json"


def build_energy_reserve_from_fixture_paths(
    paths: list[Path],
    *,
    reference_date: date | None = None,
    root: Path | None = None,
) -> ScoutEnergyReserveBaseline:
    activities = load_wearable_activity_summaries(paths, root=root)
    return build_energy_reserve_baseline(activities, reference_date=reference_date)


def write_energy_reserve_artifacts(
    activities: list[WearableActivitySummary],
    *,
    output_dir: Path,
    reference_date: date | None = None,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = build_energy_reserve_baseline(activities, reference_date=reference_date)
    explanation = build_energy_reserve_explanation(baseline)
    companion_capsule = build_companion_capability_capsule(activities)

    baseline_path = output_dir / ENERGY_BASELINE_FILENAME
    explanation_path = output_dir / ENERGY_EXPLANATION_FILENAME
    companion_path = output_dir / COMPANION_CAPSULE_FILENAME
    _write_json(baseline_path, baseline.model_dump(mode="json"))
    _write_json(explanation_path, explanation.model_dump(mode="json"))
    _write_json(companion_path, companion_capsule.model_dump(mode="json"))
    return {
        "artifact_kind": "scout_energy_reserve_artifact_export",
        "source_provider": baseline.source_provider,
        "source_path": baseline.source_path,
        "sha256": baseline.sha256,
        "baseline_path": str(baseline_path),
        "explanation_path": str(explanation_path),
        "companion_capsule_path": str(companion_path),
        "baseline": baseline.model_dump(mode="json"),
        "explanation": explanation.model_dump(mode="json"),
        "companion_capsule": companion_capsule.model_dump(mode="json"),
        "data_quality": baseline.data_quality.model_dump(mode="json"),
        "privacy": baseline.privacy.model_dump(mode="json"),
        "boundary": baseline.boundary.model_dump(mode="json"),
    }


def write_energy_reserve_artifacts_from_paths(
    paths: list[Path],
    *,
    output_dir: Path,
    reference_date: date | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    activities = load_wearable_activity_summaries(paths, root=root)
    return write_energy_reserve_artifacts(
        activities,
        output_dir=output_dir,
        reference_date=reference_date,
    )


def run_energy_reserve_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "normalize":
        result = write_normalized_wearable_imports(
            list(args.input),
            output_dir=args.output_dir,
            root=args.root,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "summarize-raw":
        result = write_sanitized_import_from_raw_file(
            args.input,
            source_format=args.source_format,
            output_dir=args.output_dir,
            activity_id=args.activity_id,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "summarize-raw-batch":
        result = write_sanitized_import_batch_from_raw_file(
            args.input,
            source_format=args.source_format,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "summarize-provider-archive":
        result = write_sanitized_import_batch_from_provider_archive(
            args.input,
            source_format=args.source_format,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "inspect-provider-archive":
        result = inspect_provider_archive(
            args.input,
            source_format=args.source_format,
        )
        return 0, result
    if args.command == "summarize-provider-api-fixture":
        result = write_sanitized_import_batch_from_provider_api_fixture(
            args.input,
            provider=args.provider,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            activity_type=args.activity_type,
            explicit_consent=args.explicit_consent,
            auth_token_ref=args.auth_token_ref,
            scopes=list(args.scope or []),
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "summarize-live-frame-fixture":
        result = write_field_observations_from_live_frame_fixture(
            args.input,
            provider=args.provider,
            output_dir=args.output_dir,
            stream_id=args.stream_id,
            route_segment_ref=args.route_segment_ref,
            expected_baseline_bpm=args.expected_baseline_bpm,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "build":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_energy_reserve_artifacts_from_paths(
            list(args.activity),
            output_dir=args.output_dir,
            reference_date=reference_date,
            root=args.root,
        )
        return 0, result
    parser.error("missing command")


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = run_energy_reserve_cli(argv)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return exit_code


def build_energy_reserve_explanation(
    baseline: ScoutEnergyReserveBaseline,
) -> ScoutEnergyReserveExplanation:
    band = baseline.reserve_trend.current_band
    headlines = {
        "normal": "Reserve is within the recent personal baseline.",
        "watch": "Reserve is mildly below the recent personal baseline.",
        "rest_suggested": "Reserve trend suggests slowing down or planning extra rest.",
        "stop_and_check": "Reserve trend suggests stopping and checking how you feel.",
    }
    cues = {
        "normal": ["Keep normal pacing and review conditions as usual."],
        "watch": ["Use a quieter pace and keep rest options visible."],
        "rest_suggested": ["Add a rest buffer before harder checkpoints.", "Avoid treating this as a safety state."],
        "stop_and_check": [
            "Pause and ask the user for a manual condition check.",
            "Escalation still requires the normal Scout safety/SOS flow.",
        ],
    }
    return ScoutEnergyReserveExplanation(
        source_provider=baseline.source_provider,
        source_path=baseline.source_path,
        sha256=aggregate_sha256(
            [
                baseline.sha256,
                baseline.reserve_trend.model_dump(mode="json"),
                baseline.data_quality.model_dump(mode="json"),
            ]
        ),
        reserve_band=band,
        headline=headlines[band],
        advisory_cues=cues[band],
        forbidden_interpretations=[
            "medical diagnosis",
            "disease inference",
            "dehydration inference",
            "arrhythmia inference",
            "overtraining inference",
            "Phase 1 runtime safety truth",
        ],
        data_quality=baseline.data_quality,
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Scout Energy Reserve fixture-backed baseline artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    normalize_parser = subparsers.add_parser(
        "normalize",
        help="Normalize sanitized provider/file-derived wearable imports into Scout summaries.",
    )
    normalize_parser.add_argument(
        "--input",
        action="append",
        type=Path,
        required=True,
        help="Sanitized wearable import envelope JSON. Repeat for multiple inputs.",
    )
    normalize_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for normalized wearable activity summary JSON files.",
    )
    normalize_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root used to render source_path values as privacy-preserving relative paths.",
    )
    normalize_parser.add_argument("--overwrite", action="store_true")
    raw_parser = subparsers.add_parser(
        "summarize-raw",
        help="Summarize local Apple Health, Garmin Connect, or GPX/FIT/TCX files into sanitized import envelopes.",
    )
    raw_parser.add_argument("--input", type=Path, required=True)
    raw_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export", "gpx", "fit", "tcx"],
        required=True,
    )
    raw_parser.add_argument("--output-dir", type=Path, required=True)
    raw_parser.add_argument("--activity-id", required=True)
    raw_parser.add_argument("--activity-type", default="hiking")
    raw_parser.add_argument("--overwrite", action="store_true")
    raw_batch_parser = subparsers.add_parser(
        "summarize-raw-batch",
        help="Summarize local Apple Health or Garmin Connect export batches into sanitized import envelopes.",
    )
    raw_batch_parser.add_argument("--input", type=Path, required=True)
    raw_batch_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export"],
        required=True,
    )
    raw_batch_parser.add_argument("--output-dir", type=Path, required=True)
    raw_batch_parser.add_argument("--activity-id-prefix", required=True)
    raw_batch_parser.add_argument("--activity-type", default="hiking")
    raw_batch_parser.add_argument("--overwrite", action="store_true")
    archive_parser = subparsers.add_parser(
        "summarize-provider-archive",
        help="Discover a local Apple Health or Garmin Connect export file in a directory/zip and summarize it.",
    )
    archive_parser.add_argument("--input", type=Path, required=True)
    archive_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export"],
        required=True,
    )
    archive_parser.add_argument("--output-dir", type=Path, required=True)
    archive_parser.add_argument("--activity-id-prefix", required=True)
    archive_parser.add_argument("--activity-type", default="hiking")
    archive_parser.add_argument("--overwrite", action="store_true")
    inspect_archive_parser = subparsers.add_parser(
        "inspect-provider-archive",
        help="Map supported and deferred local Apple Health or Garmin export archive members without importing raw payloads.",
    )
    inspect_archive_parser.add_argument("--input", type=Path, required=True)
    inspect_archive_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export"],
        required=True,
    )
    provider_api_parser = subparsers.add_parser(
        "summarize-provider-api-fixture",
        help="Summarize an offline account-authorized provider API response fixture without live network calls.",
    )
    provider_api_parser.add_argument("--input", type=Path, required=True)
    provider_api_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_api", "garmin_health_api"],
        required=True,
    )
    provider_api_parser.add_argument("--output-dir", type=Path, required=True)
    provider_api_parser.add_argument("--activity-id-prefix", required=True)
    provider_api_parser.add_argument("--activity-type", default="hiking")
    provider_api_parser.add_argument("--scope", action="append", default=[])
    provider_api_parser.add_argument("--auth-token-ref", default=None)
    provider_api_parser.add_argument("--explicit-consent", action="store_true")
    provider_api_parser.add_argument("--overwrite", action="store_true")
    live_frame_parser = subparsers.add_parser(
        "summarize-live-frame-fixture",
        help="Normalize local Apple/Garmin live-like frame fixtures into sanitized field observations.",
    )
    live_frame_parser.add_argument("--input", type=Path, required=True)
    live_frame_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live_fixture", "garmin_live_fixture"],
        required=True,
    )
    live_frame_parser.add_argument("--output-dir", type=Path, required=True)
    live_frame_parser.add_argument("--stream-id", required=True)
    live_frame_parser.add_argument("--route-segment-ref", default=None)
    live_frame_parser.add_argument("--expected-baseline-bpm", type=int, default=None)
    live_frame_parser.add_argument("--overwrite", action="store_true")
    build_parser = subparsers.add_parser(
        "build",
        help="Build local baseline, explanation, and companion capability capsule artifacts.",
    )
    build_parser.add_argument(
        "--activity",
        action="append",
        type=Path,
        required=True,
        help="Provider-neutral wearable activity summary JSON. Repeat for multiple activities.",
    )
    build_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for Scout Energy Reserve output artifacts.",
    )
    build_parser.add_argument(
        "--reference-date",
        default=None,
        help="Reference date for 7/28/90-day windows, formatted YYYY-MM-DD.",
    )
    build_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root used to render source_path values as privacy-preserving relative paths.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
