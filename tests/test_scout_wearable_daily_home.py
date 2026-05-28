from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from scout_wearable_admin import import_wearable_activity_log
from scout_wearable_daily_home import build_daily_home_preview


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_FIXTURE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_FIXTURE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_FIXTURE_ROOT / "garmin_body_battery_provider_values.json",
]


def test_builds_mobile_daily_home_preview_from_daily_overview(tmp_path: Path) -> None:
    inventory_root = tmp_path / "admin" / "wearables"
    _seed_inventory(inventory_root)

    result = build_daily_home_preview(
        inventory_root=inventory_root,
        reference_date=date(2026, 5, 27),
        write_artifact=True,
    )

    preview = result["preview"]
    html_path = Path(result["html_path"])
    preview_path = Path(result["preview_path"])
    assert result["artifact_kind"] == "scout_wearable_daily_home_preview_result"
    assert result["source_provider"] == "mixed_wearable_activity_summaries"
    assert result["source_path"] == preview["source_path"]
    assert result["sha256"] == preview["sha256"]
    assert result["data_quality"] == preview["data_quality"]
    assert result["privacy"] == preview["privacy"]
    assert result["boundary"] == preview["boundary"]
    assert result["mutation"]["daily_home_preview_written"] is True
    assert result["mutation"]["safety_api_called"] is False
    assert result["mutation"]["phase1_runtime_mutated"] is False
    assert result["mutation"]["raw_health_payload_shared"] is False

    assert preview_path.exists()
    assert html_path.exists()
    assert json.loads(preview_path.read_text(encoding="utf-8")) == preview
    assert preview["artifact_kind"] == "scout_wearable_daily_home_preview"
    assert preview["artifact_version"] == "wearable_daily_home_preview.v1"
    assert preview["surface"] == "daily_home_preview"
    assert preview["source_artifacts"][0]["artifact_kind"] == "scout_wearable_daily_energy_overview"
    assert preview["hero"]["reserve_band"] == "rest_suggested"
    assert preview["hero"]["reserve_score"] == 36
    assert [card["window_days"] for card in preview["trend_cards"]] == [7, 28, 90]
    assert preview["trend_cards"][0]["activity_count"] == 1
    assert preview["trend_cards"][1]["activity_count"] == 2
    assert preview["trend_cards"][2]["activity_count"] == 3
    assert preview["next_day_soft_cue"]["cue_type"] == "rest_or_easy_day"
    assert preview["display_language_policy"]["medical_language_allowed"] is False
    assert preview["display_language_policy"]["runtime_safety_truth"] is False
    assert preview["boundary"]["medical_diagnosis"] is False
    assert preview["boundary"]["phase1_runtime_safety_truth"] is False
    assert preview["boundary"]["safety_api_calls_allowed"] is False
    assert preview["privacy"]["raw_health_payload_shared"] is False
    assert preview["privacy"]["raw_track_shared"] is False
    assert preview["privacy"]["exact_timestamps_shared"] is False

    html = html_path.read_text(encoding="utf-8")
    assert "Scout Daily" in html
    assert 'id="scoutDailyHomePreviewArtifact"' in html
    assert "rest suggested" in html
    assert "7 day" in html
    assert "28 day" in html
    assert "90 day" in html
    assert '"medical_diagnosis": false' in html
    assert '"phase1_runtime_safety_truth": false' in html
    assert '"raw_health_payload_shared": false' in html
    assert "/safety/" not in html
    assert '"samples"' not in html
    assert "raw GPX" not in html
    assert "precise timestamp" not in html

    visible_text = _visible_text(html).lower()
    for forbidden in ("disease", "dehydration", "arrhythmia", "overtraining", "diagnosed"):
        assert forbidden not in visible_text


def test_admin_writes_and_serves_daily_home_preview_html(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app())

    for fixture in WEARABLE_FIXTURES:
        imported = client.post(
            "/admin/wearables/import",
            json={"source_path": str(fixture)},
        )
        assert imported.status_code == 200

    response = client.post(
        "/admin/wearables/daily-home-preview",
        json={"reference_date": "2026-05-27"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_kind"] == "scout_wearable_daily_home_preview_result"
    assert Path(payload["html_path"]).exists()
    assert payload["preview"]["surface"] == "daily_home_preview"
    assert payload["preview"]["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["preview"]["privacy"]["raw_track_shared"] is False
    assert payload["mutation"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)

    page = client.get("/admin/wearables/daily-home-preview")
    assert page.status_code == 200
    assert "Scout Daily" in page.text
    assert 'id="scoutDailyHomePreviewArtifact"' in page.text
    assert "/safety/" not in page.text


def _seed_inventory(inventory_root: Path) -> None:
    for fixture in WEARABLE_FIXTURES:
        import_wearable_activity_log(
            source_path=fixture,
            inventory_root=inventory_root,
            source_root=ROOT,
        )


def _visible_text(html: str) -> str:
    without_scripts = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(r"<[^>]+>", " ", without_scripts)
