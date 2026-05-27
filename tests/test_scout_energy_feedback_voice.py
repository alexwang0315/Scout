import json
from pathlib import Path

from post_analysis_energy_feedback import build_post_analysis_energy_feedback
from pretrip_energy_projection import write_pretrip_energy_reserve_projection
from scout_energy_models import load_wearable_activity_summaries
from scout_energy_reserve import write_energy_reserve_artifacts
from scout_energy_voice_cue import voice_cue_from_energy_projection


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_ROOT / "garmin_body_battery_provider_values.json",
]
PRETRIP_ETA = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "planned_eta.json"
)
TIMELINE = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "outputs"
    / "capability_timeline.json"
)


def _projection(tmp_path: Path) -> dict:
    energy = write_energy_reserve_artifacts(
        load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT),
        output_dir=tmp_path,
    )
    projection = write_pretrip_energy_reserve_projection(
        eta_plan_path=PRETRIP_ETA,
        energy_baseline_path=Path(energy["baseline_path"]),
        output_path=tmp_path / "pretrip_energy_reserve_projection.json",
        project_root=ROOT,
    )
    return projection.model_dump(mode="json")


def test_post_analysis_energy_feedback_compares_projection_with_actual_timeline(tmp_path):
    projection = _projection(tmp_path)
    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))

    feedback = build_post_analysis_energy_feedback(
        pretrip_projection=projection,
        capability_timeline=timeline,
        pretrip_projection_source_path="outputs/pretrip_energy_reserve_projection.json",
        capability_timeline_source_path="outputs/capability_timeline.json",
    )
    payload = feedback.model_dump(mode="json")

    assert payload["artifact_kind"] == "post_analysis_energy_reserve_feedback"
    assert payload["predicted_depletion_checkpoint_name"] == "雲海保線所"
    assert payload["actual_elapsed_duration_minutes"] == 37
    assert payload["actual_moving_duration_minutes"] == 30
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "<trkpt" not in json.dumps(payload)


def test_energy_projection_voice_cue_is_read_only_local_body_advisory(tmp_path):
    projection = _projection(tmp_path)

    cue = voice_cue_from_energy_projection(projection)
    payload = cue.model_dump(mode="json")

    assert cue.category == "body"
    assert cue.priority == "caution"
    assert "雲海保線所" in cue.text_zh
    assert payload["boundary"]["safety_decision_change_allowed"] is False
    assert payload["boundary"]["phase1_safety_runtime_mutation_allowed"] is False
    assert payload["boundary"]["remote_outbound_allowed"] is False
    assert payload["boundary"]["hardware_control_allowed"] is False
    assert payload["boundary"]["endpoint_calls"] == []
