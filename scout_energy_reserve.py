from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scout_companion_match_models import CompanionCapabilityCapsule, build_companion_capability_capsule
from scout_energy_baseline import build_energy_reserve_baseline
from scout_energy_models import (
    ScoutEnergyReserveBaseline,
    ScoutEnergyReserveExplanation,
    WearableActivitySummary,
    aggregate_sha256,
    load_wearable_activity_summaries,
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
        "baseline_path": str(baseline_path),
        "explanation_path": str(explanation_path),
        "companion_capsule_path": str(companion_path),
        "baseline": baseline.model_dump(mode="json"),
        "explanation": explanation.model_dump(mode="json"),
        "companion_capsule": companion_capsule.model_dump(mode="json"),
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
