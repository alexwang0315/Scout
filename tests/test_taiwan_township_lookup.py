from __future__ import annotations

import json
from pathlib import Path

from taiwan_township_lookup import (
    TAIWAN_TOWNSHIP_LOOKUP_KIND,
    load_township_gazetteer,
    lookup_township,
    lookup_township_name,
    main,
    make_township_lookup_callback,
)


def _write_gazetteer(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "townships": [
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
                    },
                    {
                        "county": "花蓮縣",
                        "township": "秀林鄉",
                        "centroid": {"lat": 24.1, "lon": 121.45},
                        "bbox": [23.8, 121.35, 24.5, 121.8],
                    },
                    {
                        "county": "臺中市",
                        "township": "和平區",
                        "latitude": 24.25,
                        "longitude": 120.95,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_lookup_township_prefers_bbox_match(tmp_path: Path) -> None:
    gazetteer_path = _write_gazetteer(tmp_path / "townships.json")

    result = lookup_township(24.0, 121.2, gazetteer_path=gazetteer_path)

    assert result["artifact_kind"] == TAIWAN_TOWNSHIP_LOOKUP_KIND
    assert result["matched"] is True
    assert result["county"] == "南投縣"
    assert result["township"] == "仁愛鄉"
    assert result["method"] == "bbox_centroid"
    assert result["confidence"] == "high"
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
    assert result["boundary"]["replaces_polygon_mapping_for_safety"] is False


def test_lookup_township_falls_back_to_nearest_centroid(tmp_path: Path) -> None:
    gazetteer_path = _write_gazetteer(tmp_path / "townships.json")

    result = lookup_township(24.24, 120.96, gazetteer_path=gazetteer_path)

    assert result["matched"] is True
    assert result["township"] == "和平區"
    assert result["method"] == "nearest_centroid"
    assert result["confidence"] in {"high", "medium"}


def test_lookup_township_rejects_far_away_points(tmp_path: Path) -> None:
    gazetteer_path = _write_gazetteer(tmp_path / "townships.json")

    result = lookup_township(25.6, 122.6, gazetteer_path=gazetteer_path, max_distance_km=5)

    assert result["matched"] is False
    assert result["confidence"] == "missing"
    assert "nearest_centroid_outside_max_distance" in result["warnings"]
    assert result["candidates"]


def test_lookup_township_name_and_callback_return_weather_area_name(tmp_path: Path) -> None:
    gazetteer_path = _write_gazetteer(tmp_path / "townships.json")

    assert lookup_township_name(24.0, 121.2, gazetteer_path=gazetteer_path) == "仁愛鄉"

    callback = make_township_lookup_callback(gazetteer_path=gazetteer_path)
    assert callback(24.0, 121.2) == "仁愛鄉"

    metadata_callback = make_township_lookup_callback(
        gazetteer_path=gazetteer_path,
        return_metadata=True,
    )
    metadata = metadata_callback(24.0, 121.2)
    assert isinstance(metadata, dict)
    assert metadata["township"] == "仁愛鄉"


def test_load_township_gazetteer_accepts_feature_properties(tmp_path: Path) -> None:
    path = tmp_path / "features.json"
    path.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "properties": {
                            "COUNTYNAME": "南投縣",
                            "TOWNNAME": "仁愛鄉",
                            "centroidLat": 24.02,
                            "centroidLon": 121.16,
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records = load_township_gazetteer(path)

    assert records == [
        {
            "county": "南投縣",
            "township": "仁愛鄉",
            "lat": 24.02,
            "lon": 121.16,
            "bbox": None,
        }
    ]


def test_load_township_gazetteer_can_derive_centroid_from_geojson_geometry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "features.json"
    path.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "COUNTYNAME": "南投縣",
                            "TOWNNAME": "仁愛鄉",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [121.0, 23.8],
                                    [121.3, 23.8],
                                    [121.3, 24.2],
                                    [121.0, 24.2],
                                    [121.0, 23.8],
                                ]
                            ],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = lookup_township(24.0, 121.2, gazetteer_path=path)

    assert result["matched"] is True
    assert result["township"] == "仁愛鄉"
    assert result["method"] == "bbox_centroid"


def test_cli_outputs_json_lookup_result(tmp_path: Path, capsys) -> None:
    gazetteer_path = _write_gazetteer(tmp_path / "townships.json")

    code = main(
        [
            "--lat",
            "24.0",
            "--lon",
            "121.2",
            "--gazetteer",
            str(gazetteer_path),
        ]
    )

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["township"] == "仁愛鄉"
    assert out["candidate_only"] is True
