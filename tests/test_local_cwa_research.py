from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from scout.agents.local_cwa_research import (
    fetch_cwa_research_dataset,
    project_cwa_research_payload,
)


def test_cwa_research_dataset_uses_file_api_after_rest_404() -> None:
    calls: list[tuple[str, str]] = []

    def rest_fetcher(dataset_id: str, **_kwargs: object) -> dict[str, object]:
        calls.append(("rest", dataset_id))
        raise HTTPError("https://example.invalid", 404, "Not Found", None, None)

    def file_fetcher(
        dataset_id: str,
        *,
        file_format: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        calls.append((f"file-{file_format}", dataset_id))
        return {"cwaopendata": {"dataset": dataset_id}}

    result = fetch_cwa_research_dataset(
        "F-C0041-001",
        timeout_seconds=30,
        rest_fetcher=rest_fetcher,
        file_fetcher=file_fetcher,
    )

    assert result["cwaopendata"] == {"dataset": "F-C0041-001"}
    assert calls == [
        ("rest", "F-C0041-001"),
        ("file-JSON", "F-C0041-001"),
    ]


def test_cwa_research_dataset_does_not_hide_non_404_http_error() -> None:
    def rest_fetcher(dataset_id: str, **_kwargs: object) -> dict[str, object]:
        del dataset_id
        raise HTTPError("https://example.invalid", 401, "Unauthorized", None, None)

    with pytest.raises(HTTPError) as exc_info:
        fetch_cwa_research_dataset(
            "F-C0041-001",
            rest_fetcher=rest_fetcher,
            file_fetcher=lambda *_args, **_kwargs: {},
        )

    assert exc_info.value.code == 401


def test_project_cwa_payload_preserves_provenance_without_credentials() -> None:
    payload = {
        "success": "true",
        "records": {
            "datasetDescription": "0-6小時定量降水預報",
            "updateFrequency": "每6小時更新",
            "locations": [{"locationName": "南投縣", "rainfall": 12.5}],
        },
    }

    result = project_cwa_research_payload(
        "F-C0041-001",
        payload,
        query="時間範圍 更新頻率 降水",
        fetched_at="2026-08-20T04:00:00Z",
    )

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["dataset_id"] == "F-C0041-001"
    assert result["source_url"] == (
        "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
    )
    assert result["content_hash"].startswith("sha256:")
    assert "0-6小時" in result["content"]
    assert "每6小時" in result["content"]
    assert "Authorization" not in serialized
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False


def test_project_cwa_payload_adds_verified_dataset_metadata() -> None:
    result = project_cwa_research_payload(
        "F-C0041-001",
        {"records": {}},
        query="F-C0041-001",
        fetched_at="2026-08-20T04:00:00Z",
    )

    assert result["dataset_metadata"]["time_range"] == "0-6小時"
    assert result["dataset_metadata"]["update_frequency"] == "每6小時"
    assert "定量降水" in result["content"]


def test_structured_projection_is_bounded_to_relevant_scalar_paths() -> None:
    payload = {
        "records": {
            "warnings": [
                {
                    "areaName": "南投縣",
                    "headline": "豪雨特報",
                    "status": "目前生效中",
                }
            ],
            "unrelated": [f"value-{index}" for index in range(500)],
        }
    }

    result = project_cwa_research_payload(
        "W-C0033-001",
        payload,
        query="南投 豪雨 特報",
        fetched_at="2026-08-20T04:00:00Z",
    )

    assert "南投縣" in result["content"]
    assert "豪雨特報" in result["content"]
    assert result["projection_count"] <= 120


def test_warning_projection_reports_location_specific_inactive_state() -> None:
    payload = {
        "success": "true",
        "records": {
            "location": [
                {
                    "locationName": "新竹縣",
                    "hazardConditions": {
                        "hazards": [
                            {
                                "info": {"phenomena": "豪雨", "significance": "特報"},
                                "validTime": {
                                    "startTime": "2026-08-20 14:00:00",
                                    "endTime": "2026-08-20 20:00:00",
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }

    result = project_cwa_research_payload(
        "W-C0033-001",
        payload,
        query="南投縣目前是否有大雨或豪雨特報？",
        fetched_at="2026-08-20T04:00:00Z",
    )

    assert result["official_state"] == "active"
    assert result["query_summary"]["state"] == "inactive"
    assert result["query_summary"]["matching_record_count"] == 0
    assert result["query_summary"]["requested_hazard_states"] == {
        "大雨": "inactive",
        "豪雨": "inactive",
    }
    assert "查詢狀態=inactive" in result["content"]


def test_warning_projection_reports_matching_location_and_hazard() -> None:
    payload = {
        "success": "true",
        "records": {
            "location": [
                {
                    "locationName": "南投縣",
                    "hazardConditions": {
                        "hazards": [
                            {
                                "info": {"phenomena": "豪雨", "significance": "特報"},
                                "validTime": {
                                    "startTime": "2026-08-20 14:00:00",
                                    "endTime": "2026-08-20 20:00:00",
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }

    result = project_cwa_research_payload(
        "W-C0033-001",
        payload,
        query="南投縣目前是否有大雨或豪雨特報？",
        fetched_at="2026-08-20T04:00:00Z",
    )

    assert result["query_summary"]["state"] == "active"
    assert result["query_summary"]["matching_record_count"] == 1
    assert result["query_summary"]["matches"][0]["phenomena"] == "豪雨"
    assert result["query_summary"]["requested_hazard_states"] == {
        "大雨": "inactive",
        "豪雨": "active",
    }
    assert "災種狀態=大雨:inactive,豪雨:active" in result["content"]


def test_typhoon_release_headline_is_an_inactive_official_state() -> None:
    result = project_cwa_research_payload(
        "W-C0034-001",
        {
            "success": "true",
            "records": {
                "info": [
                    {
                        "headline": "解除颱風警報",
                        "description": "第13號颱風過去位置與風速歷史細節",
                    }
                ]
            },
        },
        query="目前是否發布颱風警報？",
        fetched_at="2026-08-20T04:00:00Z",
    )

    assert result["official_state"] == "inactive"
    assert "官方狀態目前0筆生效記錄" in result["content"]
    assert "過去位置與風速歷史細節" not in result["content"]
