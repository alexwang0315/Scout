import json
from pathlib import Path

from scout_wearable_validator import validate_wearable_activity_summary_contract


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_ROOT = ROOT / "tests" / "fixtures" / "wearables"


def test_validates_provider_neutral_wearable_summary_contract():
    report = validate_wearable_activity_summary_contract(
        WEARABLE_ROOT / "apple_health_clean_activity.json",
        root=ROOT,
    )
    payload = report.model_dump(mode="json")

    assert payload["artifact_kind"] == "scout_wearable_activity_summary_validation"
    assert payload["valid"] is True
    assert payload["source_provider"] == "apple_health_export"
    assert payload["source_path"] == "tests/fixtures/wearables/apple_health_clean_activity.json"
    assert len(payload["sha256"]) == 64
    assert payload["summary"]["heart_rate_sample_count"] == 6
    assert "samples" not in payload["summary"]
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_samples_embedded"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_calls_allowed"] is False


def test_rejects_raw_payload_and_runtime_truth_fields(tmp_path):
    source = json.loads(
        (WEARABLE_ROOT / "apple_health_clean_activity.json").read_text(
            encoding="utf-8"
        )
    )
    source["raw_health_payload"] = {"forbidden": True}
    source["privacy"] = {"raw_health_payload_shared": True}
    source["boundary"] = {"phase1_runtime_safety_truth": True}
    path = tmp_path / "bad_wearable_summary.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    report = validate_wearable_activity_summary_contract(path, root=tmp_path)

    assert report.valid is False
    errors = " ".join(report.errors)
    assert "forbidden raw field present: raw_health_payload" in errors
    assert "extra_forbidden" in errors
    assert report.boundary.phase1_runtime_safety_truth is False
