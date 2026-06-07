from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout_weather_integration import (
    CWA_36H_FORECAST,
    CWA_TOWNSHIP_WEEKLY_FORECAST,
    build_route_weather_package,
    cwa_dataset_url,
    cwa_fileapi_url,
    fetch_cwa_dataset,
    normalize_cwa_weather_points,
    segment_gpx_route,
    weather_risk_score,
    write_route_weather_package,
)
from scout_weather_window_tool import assess_scout_weather_window
from taiwan_township_lookup import make_township_lookup_callback


def test_cwa_dataset_url_uses_server_side_authorization_parameter() -> None:
    url = cwa_dataset_url(
        CWA_36H_FORECAST,
        api_key="server-only-key",
        params={"locationName": "南投縣"},
    )

    assert url.startswith("https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001")
    assert "Authorization=server-only-key" in url
    assert "format=JSON" in url
    assert "locationName=%E5%8D%97%E6%8A%95%E7%B8%A3" in url


def test_cwa_fileapi_url_supports_zip_downloads() -> None:
    url = cwa_fileapi_url(
        CWA_TOWNSHIP_WEEKLY_FORECAST,
        api_key="server-only-key",
        file_format="ZIP",
    )

    assert url.startswith(
        "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/F-D0047-093"
    )
    assert "Authorization=server-only-key" in url
    assert "downloadType=WEB" in url
    assert "format=ZIP" in url


def test_fetch_cwa_dataset_requires_server_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CWA_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="CWA_API_KEY"):
        fetch_cwa_dataset(CWA_36H_FORECAST)


def test_normalize_cwa_36h_forecast_to_scout_weather_points() -> None:
    payload = {
        "records": {
            "location": [
                {
                    "locationName": "仁愛鄉",
                    "weatherElement": [
                        {
                            "elementName": "Wx",
                            "time": [
                                {
                                    "startTime": "2099-06-08T04:00:00+08:00",
                                    "endTime": "2099-06-08T07:00:00+08:00",
                                    "parameter": {"parameterName": "午後雷陣雨"},
                                }
                            ],
                        },
                        {
                            "elementName": "PoP",
                            "time": [
                                {
                                    "startTime": "2099-06-08T04:00:00+08:00",
                                    "endTime": "2099-06-08T07:00:00+08:00",
                                    "parameter": {"parameterName": "80"},
                                }
                            ],
                        },
                        {
                            "elementName": "MinT",
                            "time": [
                                {
                                    "startTime": "2099-06-08T04:00:00+08:00",
                                    "endTime": "2099-06-08T07:00:00+08:00",
                                    "parameter": {"parameterName": "6"},
                                }
                            ],
                        },
                    ],
                }
            ]
        }
    }

    points = normalize_cwa_weather_points(
        CWA_36H_FORECAST,
        payload,
        source_run_id="cwa.run.fixture",
    )

    assert len(points) == 1
    assert points[0]["source"] == CWA_36H_FORECAST
    assert points[0]["source_run_id"] == "cwa.run.fixture"
    assert points[0]["areaName"] == "仁愛鄉"
    assert points[0]["weatherText"] == "午後雷陣雨"
    assert points[0]["rainProbability"] == 80.0
    assert points[0]["tempC"] == 6.0


def test_normalize_cwa_township_zip_week24_xml_to_weather_points() -> None:
    payload = {
        "artifact_kind": "cwa_fileapi_zip",
        "dataset_id": CWA_TOWNSHIP_WEEKLY_FORECAST,
        "documents": [
            {
                "name": "10008_Week24_CH.xml",
                "text": """<?xml version="1.0" encoding="utf-8"?>
<cwaopendata xmlns="urn:cwa:gov:tw:cwacommon:0.1">
  <Dataset>
    <Locations>
      <LocationsName>南投縣</LocationsName>
      <Location>
        <LocationName>仁愛鄉</LocationName>
        <Latitude>24.021</Latitude>
        <Longitude>121.161</Longitude>
        <WeatherElement>
          <ElementName>平均溫度</ElementName>
          <Time>
            <StartTime>2099-06-08T00:00:00+08:00</StartTime>
            <EndTime>2099-06-09T00:00:00+08:00</EndTime>
            <ElementValue><Temperature>9</Temperature></ElementValue>
          </Time>
        </WeatherElement>
        <WeatherElement>
          <ElementName>24小時降雨機率</ElementName>
          <Time>
            <StartTime>2099-06-08T00:00:00+08:00</StartTime>
            <EndTime>2099-06-09T00:00:00+08:00</EndTime>
            <ElementValue><ProbabilityOfPrecipitation>80</ProbabilityOfPrecipitation></ElementValue>
          </Time>
        </WeatherElement>
        <WeatherElement>
          <ElementName>風速</ElementName>
          <Time>
            <StartTime>2099-06-08T00:00:00+08:00</StartTime>
            <EndTime>2099-06-09T00:00:00+08:00</EndTime>
            <ElementValue><WindSpeed>12</WindSpeed></ElementValue>
          </Time>
        </WeatherElement>
        <WeatherElement>
          <ElementName>天氣現象</ElementName>
          <Time>
            <StartTime>2099-06-08T00:00:00+08:00</StartTime>
            <EndTime>2099-06-09T00:00:00+08:00</EndTime>
            <ElementValue><Weather>午後雷陣雨</Weather></ElementValue>
          </Time>
        </WeatherElement>
      </Location>
    </Locations>
  </Dataset>
</cwaopendata>
""",
            },
            {
                "name": "10008_72hr_CH.xml",
                "text": """<?xml version="1.0" encoding="utf-8"?>
<cwaopendata xmlns="urn:cwa:gov:tw:cwacommon:0.1">
  <Dataset>
    <Locations>
      <LocationsName>南投縣</LocationsName>
      <Location>
        <LocationName>埔里鎮</LocationName>
        <WeatherElement>
          <ElementName>溫度</ElementName>
          <Time>
            <DataTime>2099-06-08T00:00:00+08:00</DataTime>
            <ElementValue><Temperature>20</Temperature></ElementValue>
          </Time>
        </WeatherElement>
      </Location>
    </Locations>
  </Dataset>
</cwaopendata>
""",
            },
        ],
    }

    points = normalize_cwa_weather_points(
        CWA_TOWNSHIP_WEEKLY_FORECAST,
        payload,
        source_run_id="cwa.zip.fixture",
    )

    assert len(points) == 1
    assert points[0]["source"] == CWA_TOWNSHIP_WEEKLY_FORECAST
    assert points[0]["source_run_id"] == "cwa.zip.fixture"
    assert points[0]["source_document"] == "10008_Week24_CH.xml"
    assert points[0]["county"] == "南投縣"
    assert points[0]["areaName"] == "仁愛鄉"
    assert points[0]["validFrom"] == "2099-06-08T00:00:00+08:00"
    assert points[0]["validTo"] == "2099-06-09T00:00:00+08:00"
    assert points[0]["tempC"] == 9.0
    assert points[0]["rainProbability"] == 80.0
    assert points[0]["windSpeedMps"] == 12.0
    assert points[0]["weatherText"] == "午後雷陣雨"


def test_build_route_weather_package_outputs_segment_risk_and_wx_alert(
    tmp_path: Path,
) -> None:
    weather_point = {
        "source": CWA_36H_FORECAST,
        "source_run_id": "cwa.run.fixture",
        "validFrom": "2099-06-08T04:00:00+08:00",
        "validTo": "2099-06-08T07:00:00+08:00",
        "areaName": "仁愛鄉",
        "weatherText": "午後雷陣雨",
        "rainProbability": 80,
        "rainfallMm": 18,
        "windSpeedMps": 12,
    }
    route_segments = [
        {
            "segmentId": "seg.042",
            "fromM": 3200,
            "toM": 3450,
            "etaFrom": "2099-06-08T04:30:00+08:00",
            "etaTo": "2099-06-08T05:10:00+08:00",
            "township": "仁愛鄉",
            "terrainRisk": 0.72,
        }
    ]

    package = build_route_weather_package(
        route_id="fixture-route",
        route_segments=route_segments,
        weather_points=[weather_point],
        generated_at="2099-06-07T08:00:00Z",
        valid_until="2099-06-10T08:00:00Z",
        source_run_ids=["cwa.run.fixture"],
    )

    assert package["artifact_kind"] == "route_weather_package"
    assert package["provider"] == "server_side_cwa_ingestor"
    assert package["boundary"]["client_cwa_api_key_allowed"] is False
    assert package["segments"][0]["segmentId"] == "seg.042"
    assert package["segments"][0]["weatherRisk"] >= 0.7
    assert package["segments"][0]["finalRisk"] >= 0.7
    assert package["segments"][0]["riskLevel"] in {"HIGH", "ELEVATED"}
    assert package["wx_alerts"][0]["type"] == "WX_ALERT"
    assert "RAIN" in package["wx_alerts"][0]["code"]

    project_root = tmp_path / "project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "fixture-route",
                "route_weather_package_ref": "outputs/route_weather_package.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_route_weather_package(
        project_root / "outputs" / "route_weather_package.json",
        package,
    )

    assessed = assess_scout_weather_window(project_root, query="下雨後哪段風險高?")
    assert assessed["answerability"] == "route_weather_risk_available"
    assert assessed["missing_fields"] == []
    assert assessed["result_count"] == 1
    assert assessed["wx_alerts"][0]["seg"] == "seg.042"


def test_segment_gpx_route_outputs_100_to_250m_route_segments(tmp_path: Path) -> None:
    gpx_path = tmp_path / "route.gpx"
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="scout-test">
  <trk><trkseg>
    <trkpt lat="24.0000" lon="121.0000" />
    <trkpt lat="24.0000" lon="121.0010" />
    <trkpt lat="24.0000" lon="121.0020" />
    <trkpt lat="24.0000" lon="121.0030" />
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

    segments = segment_gpx_route(
        gpx_path,
        segment_length_m=120,
        default_township="仁愛鄉",
        start_at="2099-06-08T04:00:00Z",
        speed_mps=1.0,
        terrain_risk=0.4,
    )

    assert segments
    assert all(100 <= segment["toM"] - segment["fromM"] <= 250 for segment in segments)
    assert segments[0]["segmentId"] == "seg.0000"
    assert segments[0]["township"] == "仁愛鄉"
    assert segments[0]["etaFrom"] == "2099-06-08T04:00:00Z"
    assert segments[0]["terrainRisk"] == 0.4


def test_segment_gpx_route_accepts_township_lookup_metadata(tmp_path: Path) -> None:
    gpx_path = tmp_path / "route.gpx"
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="scout-test">
  <trk><trkseg>
    <trkpt lat="24.0000" lon="121.2000" />
    <trkpt lat="24.0000" lon="121.2020" />
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    gazetteer_path = tmp_path / "townships.json"
    gazetteer_path.write_text(
        json.dumps(
            [
                {
                    "county": "南投縣",
                    "township": "仁愛鄉",
                    "lat": 24.02,
                    "lon": 121.16,
                    "bbox": {
                        "min_lat": 23.8,
                        "max_lat": 24.3,
                        "min_lon": 121.0,
                        "max_lon": 121.35,
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    segments = segment_gpx_route(
        gpx_path,
        segment_length_m=100,
        township_lookup=make_township_lookup_callback(
            gazetteer_path=gazetteer_path,
            return_metadata=True,
        ),
    )

    assert segments
    assert segments[0]["township"] == "仁愛鄉"
    assert segments[0]["townshipLookup"] == {
        "artifact_kind": "taiwan_township_lookup_result",
        "matched": True,
        "county": "南投縣",
        "township": "仁愛鄉",
        "distance_km": segments[0]["townshipLookup"]["distance_km"],
        "method": "bbox_centroid",
        "confidence": "high",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def test_weather_risk_score_reports_missing_weather_point() -> None:
    score, factors = weather_risk_score(None)

    assert score == 0.0
    assert factors == ["weather_missing"]
