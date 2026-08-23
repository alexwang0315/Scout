from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pretrip_route_context_scout_ai_regenerate import (
    EDITORIAL_PLAN_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    RouteContextRegenerationError,
    regenerate_route_context_briefing,
)


def test_regeneration_archives_baseline_and_deterministically_renders_evidence(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    evidence_path = _write_evidence(project_root)
    baseline = (
        project_root / "outputs" / "briefings" / "route_context_briefing.html"
    )
    baseline_sha256 = hashlib.sha256(baseline.read_bytes()).hexdigest()
    captured: dict[str, object] = {}

    def fake_model_caller(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "plan": _editorial_plan(),
            "usage": {
                "requests": 1,
                "input_tokens": 1000,
                "output_tokens": 300,
            },
            "response_metadata": {
                "provider_name": "openrouter",
                "model_name": "deepseek/deepseek-v3.2",
            },
        }

    result = regenerate_route_context_briefing(
        project_root=project_root,
        evidence_path=evidence_path,
        model_config_path=_write_model_config(tmp_path),
        skill_path=_write_skill(tmp_path),
        model_caller=fake_model_caller,
        generated_at="2026-07-30T12:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["model"] == "deepseek/deepseek-v3.2"
    assert result["briefing_sha256"] != baseline_sha256
    assert result["baseline_sha256"] == baseline_sha256
    assert result["boundary"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "model_wrote_html": False,
    }

    archive = project_root / result["archive_ref"]
    assert archive.is_file()
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == baseline_sha256

    html = baseline.read_text(encoding="utf-8")
    assert "<h1>東清八通關古道</h1>" in html
    assert "綁定軌跡：20210220清朝八通關全線" in html
    assert "目前不可作為可直接成行的開放路線" in html
    assert "未開放路線的脈絡導覽" in html
    assert "第 0 道閘門" in html
    assert "不得直接套用為今日規劃模板" in html
    assert "等待官方恢復「其他路線」" in html
    assert "D1" in html
    assert "東埔第二登山口至觀高" in html
    assert "其他路線" in html
    assert "入園日前 10 天至 2 個月" in html
    assert "歷史參考，不是今日建議行程" in html
    assert "帶著這些問題讀" in html
    assert "帶著三個問題讀" not in html
    assert "P0" in html
    assert "P1" in html
    assert "P2" in html
    assert "六層路線脈絡" in html
    assert "隊伍回顧與軌跡線索" in html
    assert "1</b>P2 路線線索" in html
    assert "1 筆專案內路線線索保留在上一節" in html
    assert "project:" not in html
    assert "Scout AI" not in html
    assert "runtime_safety_truth" not in html

    plan = json.loads(
        (project_root / result["editorial_plan_ref"]).read_text(encoding="utf-8")
    )
    receipt = json.loads(
        (project_root / result["receipt_ref"]).read_text(encoding="utf-8")
    )
    assert plan["plan"]["title"] == "東清八通關古道"
    assert plan["prompt_sha256"] == result["prompt_sha256"]
    assert receipt["briefing_sha256"] == result["briefing_sha256"]
    assert receipt["evidence_sha256"] == hashlib.sha256(
        evidence_path.read_bytes()
    ).hexdigest()
    assert "evidence_packet" in str(captured["prompt"])
    assert captured["model_name"] == "deepseek/deepseek-v3.2"


def test_regeneration_can_create_a_missing_canonical_briefing(tmp_path: Path) -> None:
    project_root = _write_project(tmp_path)
    evidence_path = _write_evidence(project_root)
    briefing_path = (
        project_root / "outputs" / "briefings" / "route_context_briefing.html"
    )
    briefing_path.unlink()

    result = regenerate_route_context_briefing(
        project_root=project_root,
        evidence_path=evidence_path,
        model_config_path=_write_model_config(tmp_path),
        skill_path=_write_skill(tmp_path),
        model_caller=lambda **_: {
            "plan": _editorial_plan(),
            "usage": {"requests": 1},
            "response_metadata": {"provider_name": "openrouter"},
        },
        generated_at="2026-08-02T04:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["archive_ref"] is None
    assert briefing_path.is_file()
    assert "<h1>東清八通關古道</h1>" in briefing_path.read_text(encoding="utf-8")


def test_regeneration_rejects_claim_with_unknown_source_before_model_call(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    evidence_path = _write_evidence(project_root)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["current_status"]["source_ids"] = ["missing-source"]
    evidence_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    called = False

    def should_not_call(**_: object) -> dict[str, object]:
        nonlocal called
        called = True
        raise AssertionError("model should not be called")

    with pytest.raises(
        RouteContextRegenerationError,
        match="unknown source_id",
    ):
        regenerate_route_context_briefing(
            project_root=project_root,
            evidence_path=evidence_path,
            model_config_path=_write_model_config(tmp_path),
            skill_path=_write_skill(tmp_path),
            model_caller=should_not_call,
        )
    assert called is False


def test_regeneration_rejects_model_plan_that_omits_required_section(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    evidence_path = _write_evidence(project_root)
    invalid_plan = _editorial_plan()
    invalid_plan["section_order"] = [
        item
        for item in invalid_plan["section_order"]
        if item != "source_ledger"
    ]

    with pytest.raises(
        RouteContextRegenerationError,
        match="section_order",
    ):
        regenerate_route_context_briefing(
            project_root=project_root,
            evidence_path=evidence_path,
            model_config_path=_write_model_config(tmp_path),
            skill_path=_write_skill(tmp_path),
            model_caller=lambda **_: {
                "plan": invalid_plan,
                "usage": {"requests": 1},
                "response_metadata": {},
            },
        )

    briefing = (
        project_root / "outputs" / "briefings" / "route_context_briefing.html"
    )
    assert "OLD BRIEFING" in briefing.read_text(encoding="utf-8")


def test_regeneration_rejects_trip_photo_heading_without_p2_images(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    invalid_plan = _editorial_plan()
    invalid_plan["section_headings"]["visual_essay"] = "行程照片清單"

    with pytest.raises(
        RouteContextRegenerationError,
        match="mislabels non-P2 imagery",
    ):
        regenerate_route_context_briefing(
            project_root=project_root,
            evidence_path=_write_evidence(project_root),
            model_config_path=_write_model_config(tmp_path),
            skill_path=_write_skill(tmp_path),
            model_caller=lambda **_: {
                "plan": invalid_plan,
                "usage": {"requests": 1},
                "response_metadata": {},
            },
        )


def test_regeneration_rejects_model_route_rename(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    invalid_plan = _editorial_plan()
    invalid_plan["title"] = "清代八通關東段"

    with pytest.raises(
        RouteContextRegenerationError,
        match="exactly match evidence display_name",
    ):
        regenerate_route_context_briefing(
            project_root=project_root,
            evidence_path=_write_evidence(project_root),
            model_config_path=_write_model_config(tmp_path),
            skill_path=_write_skill(tmp_path),
            model_caller=lambda **_: {
                "plan": invalid_plan,
                "usage": {"requests": 1},
                "response_metadata": {},
            },
        )


def test_regeneration_repairs_closed_claim_for_unknown_route_status(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    evidence_path = _write_evidence(project_root)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["current_status"].update(
        {
            "operability": "unknown",
            "label": "本次狀態待查",
            "summary": "尚未取得足以判定開放或封閉的最新官方證據。",
            "reason": "必須重新查核官方公告。",
        }
    )
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    closed_claim = _editorial_plan()
    corrected = _editorial_plan()
    corrected["section_headings"]["decision_snapshot"] = "目前狀態待查：先確認官方公告"
    corrected["subtitle"] = "路線資料已綁定，開放狀態仍待官方查核"
    corrected["closing_note"] = "出發前重查官方開放狀態、路況與接駁安排"
    calls = 0

    def fake_model_caller(**_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "plan": closed_claim if calls == 1 else corrected,
            "usage": {"requests": 1},
            "response_metadata": {"provider_name": "openrouter"},
        }

    result = regenerate_route_context_briefing(
        project_root=project_root,
        evidence_path=evidence_path,
        model_config_path=_write_model_config(tmp_path),
        skill_path=_write_skill(tmp_path),
        model_caller=fake_model_caller,
    )

    assert calls == 2
    assert result["editorial_contract"]["mode"] == "unknown_route_non_regression"
    html = (
        project_root / "outputs" / "briefings" / "route_context_briefing.html"
    ).read_text(encoding="utf-8")
    assert "目前狀態待查：先確認官方公告" in html
    assert "目前未開放：不可直接成行" not in html


def test_regeneration_repairs_a_weak_closed_route_editorial_plan(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    weak_plan = _editorial_plan()
    weak_plan["section_headings"]["decision_snapshot"] = "目前狀態先於行程"
    weak_plan["section_headings"]["p2_route_memory"] = "P2路線記憶"
    weak_plan["reader_questions"] = [
        "這條路線目前可以申請嗎？",
        "大水窟之後的清代東段有什麼不同？",
        "舊紀錄的九天行程能直接沿用嗎？",
        "卓溪端接駁現在怎麼安排？",
    ]
    weak_plan["closing_note"] = "出發前，先確認官方已恢復其他路線申請。"
    repaired_plan = _editorial_plan()
    prompts: list[str] = []

    def fake_model_caller(**kwargs: object) -> dict[str, object]:
        prompts.append(str(kwargs["prompt"]))
        return {
            "plan": weak_plan if len(prompts) == 1 else repaired_plan,
            "usage": {
                "requests": 1,
                "input_tokens": 100,
                "output_tokens": 20,
            },
            "response_metadata": {"provider_name": "openrouter"},
        }

    result = regenerate_route_context_briefing(
        project_root=project_root,
        evidence_path=_write_evidence(project_root),
        model_config_path=_write_model_config(tmp_path),
        skill_path=_write_skill(tmp_path),
        model_caller=fake_model_caller,
        generated_at="2026-08-02T06:00:00Z",
    )

    assert len(prompts) == 2
    assert "closed-route editorial contract" in prompts[1]
    assert result["model_request_count"] == 2
    assert result["editorial_contract"]["status"] == "PASS"
    plan_record = json.loads(
        (project_root / result["editorial_plan_ref"]).read_text(encoding="utf-8")
    )
    assert [attempt["status"] for attempt in plan_record["attempts"]] == [
        "rejected",
        "accepted",
    ]
    assert plan_record["usage"]["requests"] == 2
    assert plan_record["usage"]["input_tokens"] == 200


def test_regeneration_keeps_baseline_when_all_editorial_repairs_are_weak(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    evidence_path = _write_evidence(project_root)
    weak_plan = _editorial_plan()
    weak_plan["section_headings"]["decision_snapshot"] = "目前狀態先於行程"
    weak_plan["section_headings"]["p2_route_memory"] = "P2路線記憶"
    weak_plan["reader_questions"] = [
        "這條路線目前可以申請嗎？",
        "舊紀錄的九天行程能直接沿用嗎？",
        "卓溪端接駁現在怎麼安排？",
    ]
    weak_plan["closing_note"] = "出發前，先確認官方已恢復其他路線申請。"
    calls = 0

    def fake_model_caller(**_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "plan": weak_plan,
            "usage": {"requests": 1},
            "response_metadata": {"provider_name": "openrouter"},
        }

    with pytest.raises(
        RouteContextRegenerationError,
        match="closed-route editorial contract",
    ):
        regenerate_route_context_briefing(
            project_root=project_root,
            evidence_path=evidence_path,
            model_config_path=_write_model_config(tmp_path),
            skill_path=_write_skill(tmp_path),
            model_caller=fake_model_caller,
        )

    assert calls == 3
    briefing_path = (
        project_root / "outputs" / "briefings" / "route_context_briefing.html"
    )
    assert "OLD BRIEFING" in briefing_path.read_text(encoding="utf-8")


def _write_project(tmp_path: Path) -> Path:
    root = tmp_path / "dongqing_fixture"
    briefing = root / "outputs" / "briefings" / "route_context_briefing.html"
    briefing.parent.mkdir(parents=True)
    briefing.write_text(
        "<!doctype html><html><body><h1>OLD BRIEFING</h1></body></html>",
        encoding="utf-8",
    )
    _write_json(
        root / "project.json",
        {
            "project_id": "dongqing_fixture",
            "route_name": "20210220清朝八通關全線",
            "route_context_briefing_ref": (
                "outputs/briefings/route_context_briefing.html"
            ),
            "route_context_media_manifest_ref": (
                "normalized/context/route_context/media_manifest.json"
            ),
            "route_context_points_ref": (
                "candidates/route_context_points.json"
            ),
            "route_summary_ref": "normalized/routes/route_summary.json",
        },
    )
    _write_json(
        root / "normalized" / "routes" / "route_summary.json",
        {
            "route_name": "20210220清朝八通關全線",
            "distance_m": 89827.14,
            "elevation_min_m": 595.3,
            "elevation_max_m": 3248.96,
            "point_count": 5649,
        },
    )
    _write_json(
        root
        / "normalized"
        / "context"
        / "route_context"
        / "media_manifest.json",
        {
            "project_id": "dongqing_fixture",
            "images": [
                {
                    "url": "https://example.test/route-map.jpg",
                    "alt": "清代八通關古道路線圖",
                    "caption": "清代八通關古道路線圖",
                    "page_url": "https://example.test/official-history",
                    "source_tier": "P0",
                }
            ],
        },
    )
    _write_json(
        root / "candidates" / "route_context_points.json",
        {
            "project_id": "dongqing_fixture",
            "points": [
                {
                    "label": "大水窟山屋",
                    "distance_m": 38225.3,
                    "source_tier": "P1",
                    "context_kind": "resource_context",
                    "sec6_layers": ["cultural", "terrain"],
                },
                {
                    "label": "公山",
                    "distance_m": 47163.9,
                    "source_tier": "P1",
                    "context_kind": "viewpoint",
                    "sec6_layers": [
                        "historical",
                        "cultural",
                        "terrain",
                        "observation_point",
                    ],
                },
                {
                    "label": "1K",
                    "distance_m": 1000,
                    "source_tier": "P2",
                    "context_kind": "route_context",
                    "sec6_layers": ["historical"],
                },
            ],
        },
    )
    return root


def _write_evidence(project_root: Path) -> Path:
    path = project_root / "inputs" / "route_context_regeneration_evidence.json"
    _write_json(
        path,
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "project_id": "dongqing_fixture",
            "display_name": "東清八通關古道",
            "checked_at": "2026-07-30T10:00:00+08:00",
            "route_identity": {
                "bound_track_name": "20210220清朝八通關全線",
                "direction": "東埔至卓溪",
                "explanation": (
                    "本頁以東清八通關古道為導覽名稱；數值綁定"
                    " 20210220清朝八通關全線軌跡。"
                ),
                "source_ids": ["p1-gpx"],
            },
            "current_status": {
                "operability": "closed",
                "label": "截至 2026-07-30 的官方查核",
                "summary": "目前不可作為可直接成行的開放路線。",
                "reason": (
                    "官方只恢復部分長程路線，其他尚未開放路線另待公告。"
                ),
                "source_ids": ["p0-reopen", "p0-other-route"],
            },
            "reference_itinerary": {
                "label": "2020/12/26–2021/01/03 九天實走參考",
                "caveat": "歷史參考，不是今日建議行程。",
                "days": [
                    {
                        "day": "D1",
                        "route": "東埔第二登山口至觀高",
                        "notes": "經雲龍瀑布、樂樂與對關。",
                    },
                    {
                        "day": "D2",
                        "route": "觀高至大水窟山屋",
                        "notes": "經八通關草原與中央金礦。",
                    },
                ],
                "source_ids": ["p1-trip"],
            },
            "logistics": {
                "access": "參考隊伍以包車前往東埔，前一晚住宿。",
                "exit": "參考隊伍自卓溪山產業道路包車至玉里車站。",
                "unresolved": [
                    "現行接駁業者、時間與價格尚未查證。",
                    "營地與宿點不得沿用舊紀錄，須按申請案重建。",
                ],
                "source_ids": ["p1-trip"],
            },
            "application": {
                "classification": "其他路線",
                "summary": (
                    "完整登山計畫書須在入園日前 10 天至 2 個月上傳。"
                ),
                "requirements": [
                    "每隊 1 至 12 人，領隊須為成年人。",
                    "依最新公告確認路線是否開放後再送件。",
                ],
                "source_ids": ["p0-other-route"],
            },
            "context_claims": [
                {
                    "layer": "historical",
                    "title": "清代古道與日治越道路不同線",
                    "text": "東段清代古道在拉庫拉庫溪北岸，日治越道路在南岸。",
                    "source_ids": ["p0-history"],
                },
                {
                    "layer": "terrain",
                    "title": "非例行巡查路線",
                    "text": "其他路線未規劃完整步道、牌示、安全與住宿設施。",
                    "source_ids": ["p0-other-route"],
                },
            ],
            "unresolved_items": [
                "最新現地路況與所有渡溪點狀態。",
                "逐日合法宿營點與承載量。",
                "隊伍能力、留守與後援計畫。",
            ],
            "sources": [
                {
                    "source_id": "p0-reopen",
                    "tier": "P0",
                    "title": "部分長程路線恢復公告",
                    "url": "https://example.test/reopen",
                    "published_at": "2026-07-26",
                    "checked_at": "2026-07-30",
                },
                {
                    "source_id": "p0-other-route",
                    "tier": "P0",
                    "title": "其他路線申請方式",
                    "url": "https://example.test/other-route",
                    "published_at": "2026-05-08",
                    "checked_at": "2026-07-30",
                },
                {
                    "source_id": "p0-history",
                    "tier": "P0",
                    "title": "清代與日治八通關道路比較",
                    "url": "https://example.test/official-history",
                    "checked_at": "2026-07-30",
                },
                {
                    "source_id": "p1-trip",
                    "tier": "P1",
                    "title": "2020 清八通關實走紀錄",
                    "url": "https://example.test/trip",
                    "published_at": "2021-01-12",
                    "checked_at": "2026-07-30",
                },
                {
                    "source_id": "p1-gpx",
                    "tier": "P1",
                    "title": "清朝八通關古道全線 GPX",
                    "url": "https://example.test/gpx",
                    "published_at": "2021-02-24",
                    "checked_at": "2026-07-30",
                },
            ],
        },
    )
    return path


def _editorial_plan() -> dict[str, object]:
    return {
        "artifact_kind": "scout_ai_route_context_editorial_plan",
        "schema_version": EDITORIAL_PLAN_SCHEMA_VERSION,
        "title": "東清八通關古道",
        "eyebrow": "東埔到卓溪，一條需要先讀懂身分的古道",
        "subtitle": "先判斷現在能不能走，再閱讀九天實走與歷史地景。",
        "section_order": [
            "decision_snapshot",
            "route_identity",
            "reference_itinerary",
            "logistics_and_application",
            "route_atlas",
            "visual_essay",
            "six_context_layers",
            "p2_route_memory",
            "source_ledger",
        ],
        "section_headings": {
            "decision_snapshot": "目前未開放：不可直接成行",
            "route_identity": "同名古道，先分清哪一條線",
            "reference_itinerary": "九天實走，只作歷史參考",
            "logistics_and_application": "接駁與申請，從缺口開始",
            "route_atlas": "把九十公里放回地形",
            "visual_essay": "用官方圖像讀歷史",
            "six_context_layers": "六層路線脈絡",
            "p2_route_memory": "隊伍回顧與軌跡線索",
            "source_ledger": "每一句重要結論都能回到來源",
        },
        "reader_questions": [
            "這份舊行程能證明什麼，不能證明什麼？",
            "目前哪一項官方條件直接阻止成行？",
            "若未來重開，第一批要重查哪些資料？",
            "清代東段與日治越道路線有什麼差異？",
        ],
        "closing_note": "官方恢復後仍要重查路況與接駁，再談能不能出發。",
    }


def _write_model_config(tmp_path: Path) -> Path:
    path = tmp_path / "assistant-models.json"
    _write_json(
        path,
        {
            "active_profile": "cloud",
            "cloud_model": {
                "profile": "cloud",
                "model_name": "deepseek/deepseek-v3.2",
                "base_url": "https://openrouter.ai/api/v1",
                "backend": "openai_compatible",
                "token_env_var": "OPENROUTER_API_KEY",
                "tool_calling": "disabled",
            },
            "local_model": {
                "profile": "local",
                "model_name": "hailo:qwen3:1.7b",
                "backend": "hailo_ollama",
                "tool_calling": "disabled",
            },
        },
    )
    return path


def _write_skill(tmp_path: Path) -> Path:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "# Scout route context briefing\n"
        "Use P0, P1, and P2 evidence. Compile facts deterministically.\n",
        encoding="utf-8",
    )
    return path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
