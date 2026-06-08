import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from scout_companion_match_models import (
    build_companion_capability_capsule,
    build_companion_match_review_artifact,
    write_companion_match_review_artifact,
)
from scout_energy_models import load_wearable_activity_summaries
from scout_mobile_handoff import build_mobile_energy_companion_handoff
from scout_wearable_admin import import_wearable_activity_log
from scout_wearable_daily_home import build_daily_home_preview


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_ROOT / "garmin_body_battery_provider_values.json",
]


def test_builds_local_mobile_energy_companion_handoff_without_network_or_safety_truth(tmp_path):
    inventory_root = tmp_path / "admin" / "wearables"
    _seed_inventory(inventory_root)
    daily = build_daily_home_preview(
        inventory_root=inventory_root,
        reference_date=date(2026, 5, 27),
        write_artifact=True,
    )
    review_path = _write_companion_review(tmp_path / "companion_match_review.json")

    result = build_mobile_energy_companion_handoff(
        daily_home_preview_path=Path(daily["preview_path"]),
        companion_match_review_path=review_path,
        output_path=tmp_path / "mobile_handoff.json",
    )
    handoff = result["handoff"]
    serialized = json.dumps(handoff, sort_keys=True)

    assert result["artifact_kind"] == "scout_mobile_energy_companion_handoff_result"
    assert result["persisted"] is True
    assert Path(result["handoff_path"]).exists()
    assert handoff["artifact_kind"] == "scout_mobile_energy_companion_handoff"
    assert handoff["surface"] == "mobile_energy_companion_home"
    assert handoff["energy"]["hero"]["reserve_band"] == "rest_suggested"
    assert len(handoff["energy"]["trend_cards"]) == 3
    assert handoff["companion_match"]["available"] is True
    assert handoff["companion_match"]["ranked_matches"][0]["match_score"] == 100
    assert handoff["sync_policy"]["handoff_only"] is True
    assert handoff["sync_policy"]["network_sync_allowed"] is False
    assert handoff["sync_policy"]["network_sync_performed"] is False
    assert handoff["sync_policy"]["mobile_runtime_authority"] is False
    assert handoff["sync_policy"]["phase1_safety_state_authority"] is False
    assert handoff["privacy"]["raw_health_payload_shared"] is False
    assert handoff["privacy"]["raw_track_shared"] is False
    assert handoff["privacy"]["exact_timestamps_shared"] is False
    assert handoff["boundary"]["medical_diagnosis"] is False
    assert handoff["boundary"]["phase1_runtime_safety_truth"] is False
    assert handoff["boundary"]["safety_api_calls_allowed"] is False
    assert result["mutation"]["network_sync_performed"] is False
    assert result["mutation"]["mobile_runtime_state_mutated"] is False
    assert result["mutation"]["safety_api_called"] is False
    assert "/safety/" not in serialized
    assert '"samples"' not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "heartRateSamples" not in serialized
    assert "<trkpt" not in serialized


def test_mobile_handoff_cli_writes_local_package(tmp_path):
    inventory_root = tmp_path / "admin" / "wearables"
    _seed_inventory(inventory_root)
    daily = build_daily_home_preview(
        inventory_root=inventory_root,
        reference_date=date(2026, 5, 27),
        write_artifact=True,
    )
    review_path = _write_companion_review(tmp_path / "companion_match_review.json")
    output_path = tmp_path / "mobile_handoff.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_mobile_handoff",
            "build",
            "--daily-home-preview",
            str(daily["preview_path"]),
            "--companion-match-review",
            str(review_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    handoff = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["artifact_kind"] == "scout_mobile_energy_companion_handoff_result"
    assert handoff["artifact_kind"] == "scout_mobile_energy_companion_handoff"
    assert handoff["companion_match"]["available"] is True
    assert handoff["sync_policy"]["network_sync_performed"] is False
    assert handoff["boundary"]["phase1_runtime_safety_truth"] is False
    assert "/safety/" not in json.dumps(payload)


def test_admin_writes_mobile_handoff_from_daily_home_and_companion_review(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app())
    review_path = _write_companion_review(tmp_path / "companion_match_review.json")

    for fixture in WEARABLE_FIXTURES:
        imported = client.post(
            "/admin/wearables/import",
            json={"source_path": str(fixture)},
        )
        assert imported.status_code == 200

    response = client.post(
        "/admin/wearables/mobile-handoff",
        json={
            "reference_date": "2026-05-27",
            "companion_match_review_path": str(review_path),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "scout_mobile_energy_companion_handoff_result"
    assert Path(payload["handoff_path"]).exists()
    assert payload["handoff"]["energy"]["hero"]["reserve_band"] == "rest_suggested"
    assert payload["handoff"]["companion_match"]["available"] is True
    assert payload["handoff"]["sync_policy"]["network_sync_performed"] is False
    assert payload["handoff"]["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["mutation"]["network_sync_performed"] is False
    assert payload["mutation"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)


def _seed_inventory(inventory_root: Path) -> None:
    for fixture in WEARABLE_FIXTURES:
        import_wearable_activity_log(
            source_path=fixture,
            inventory_root=inventory_root,
            source_root=ROOT,
        )


def _write_companion_review(path: Path) -> Path:
    activities = load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT)
    query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
    candidate = build_companion_capability_capsule(activities, owner_profile_ref="candidate.private")
    review = build_companion_match_review_artifact(
        query,
        [candidate],
        query_profile_ref="local_user.private",
        candidate_profile_refs=["candidate.local"],
    )
    write_companion_match_review_artifact(review, path)
    return path
