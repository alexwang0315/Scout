from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scout_contextual_permission_workbench import (
    BaselineAuthoringRequest,
    ContextualPermissionConflict,
)
from test_scout_contextual_permission_workbench import _workbench


FOUR_DAY_TEXT = (
    "D1：中平林道18K - 沛源石礦岔路 - 石礦鞍部 - 森林鞍西北側迷你鞍C1\n"
    "(273689/2589087)\n"
    "D2：C1 - 崩坡絕壁 - 三岔峰營地 - 玉里山 - 清八岔 - 單攻往阿桑來戛探一小段 -\n"
    "H1648營C2\n"
    "D3：C2 - 巨石獵營 - 1148鞍 - 單攻異祿閣 - 1148鞍旁平地C3\n"
    "D4：C3 - 腰繞至Nas-maya - 卓溪山岔 - 卓溪山 - 卓溪山產道"
)


def _preview(tmp_path: Path, text: str):
    return _workbench(tmp_path).preview_baseline(
        BaselineAuthoringRequest(mode="human_text", human_text=text)
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_actual_four_day_wrapping_preserves_places_day_ends_and_pending_intent(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    before = _files(tmp_path)
    draft = workbench.preview_baseline(
        BaselineAuthoringRequest(mode="human_text", human_text=FOUR_DAY_TEXT)
    )

    assert [day.mission_day_id for day in draft.days] == ["D1", "D2", "D3", "D4"]
    assert [day.ordered_place_mentions for day in draft.days] == [
        ["中平林道18K", "沛源石礦岔路", "石礦鞍部", "森林鞍西北側迷你鞍"],
        ["崩坡絕壁", "三岔峰營地", "玉里山", "清八岔", "往阿桑來戛探一小段", "H1648營"],
        ["巨石獵營", "1148鞍", "異祿閣", "1148鞍旁平地"],
        ["腰繞至Nas-maya", "卓溪山岔", "卓溪山", "卓溪山產道"],
    ]
    assert [day.operator_aliases for day in draft.days] == [
        ["C1"], ["C1", "C2"], ["C2", "C3"], ["C3"],
    ]
    assert draft.days[0].coordinate_hints == [
        {"raw_text": "273689/2589087", "confirmed_crs": None, "reviewed": False}
    ]
    assert all(not day.coordinate_hints for day in draft.days[1:])
    assert draft.days[0].source_text.endswith("\n(273689/2589087)")
    assert draft.days[1].source_text.endswith("-\nH1648營C2")
    assert [day.branch_candidates for day in draft.days] == [
        [],
        [{"label": "往阿桑來戛探一小段", "kind": "out_and_back_candidate", "reviewed": False}],
        [{"label": "異祿閣", "kind": "out_and_back_candidate", "reviewed": False}],
        [],
    ]
    assert not any(gap.startswith("unparsed_line:") for gap in draft.unresolved_gaps)
    assert "D1:coordinate_crs:273689/2589087" in draft.unresolved_gaps
    assert "D2:H1648營" in draft.unresolved_gaps
    assert "D3:branch_review:異祿閣" in draft.unresolved_gaps
    assert draft.source_text == FOUR_DAY_TEXT
    assert draft.source_sha256 == hashlib.sha256(FOUR_DAY_TEXT.encode()).hexdigest()
    assert draft.validation_state == "needs_review"
    assert draft.source_refs == [] and draft.source_hashes == {}
    assert set(draft.route_axis_validation.values()) == {"unknown"}
    for day in draft.days:
        assert day.resolved_targets == []
        assert day.resolved_target_refs == {} and day.resolved_target_hashes == {}
        assert day.start_anchor is None and day.primary_day_end_proposal is None
        assert day.eta_proposal is None and day.segment_ids == []
    assert draft.candidate_only is True
    assert draft.runtime_safety_truth is False
    assert draft.departure_approval_granted is False
    assert draft.writes_performed is False
    assert _files(tmp_path) == before


@pytest.mark.parametrize("separator", [" - ", "-", "–", "—", "——", "－", "→", ">", "->"])
def test_route_separators_preserve_hyphenated_place_names(
    tmp_path: Path, separator: str,
) -> None:
    draft = _preview(tmp_path, f"D1：起點{separator}腰繞至Nas-maya{separator}終點C1")
    assert draft.days[0].ordered_place_mentions == ["起點", "腰繞至Nas-maya", "終點"]
    assert draft.days[0].operator_aliases == ["C1"]


@pytest.mark.parametrize("separator", ["-", "–", "—", "－－", "→", "->"])
@pytest.mark.parametrize("separator_on_next_line", [False, True])
def test_explicit_route_continuation_remains_in_day_before_next_day_header(
    tmp_path: Path, separator: str, separator_on_next_line: bool,
) -> None:
    wrapped = f"起點\n {separator} 營地C1" if separator_on_next_line else f"起點 {separator}\n 營地C1"
    draft = _preview(tmp_path, f"D1：{wrapped}\nD2：C1 - 終點C2")
    assert draft.days[0].ordered_place_mentions == ["起點", "營地"]
    assert draft.days[0].operator_aliases == ["C1"]
    assert draft.days[1].ordered_place_mentions == ["終點"]
    assert draft.days[1].operator_aliases == ["C1", "C2"]


@pytest.mark.parametrize("coordinate", ["(273689/2589087)", "（273689/2589087）"])
def test_coordinate_continuation_retains_unconfirmed_crs_without_location(
    tmp_path: Path, coordinate: str,
) -> None:
    draft = _preview(tmp_path, f"D1：起點 - 迷你鞍C1\n{coordinate}\nD2：C1 - 營地C2")
    assert draft.days[0].coordinate_hints == [
        {"raw_text": "273689/2589087", "confirmed_crs": None, "reviewed": False}
    ]
    assert draft.days[0].ordered_place_mentions == ["起點", "迷你鞍"]
    assert draft.days[1].coordinate_hints == []
    assert draft.days[0].resolved_target_refs == {}


def test_unrelated_or_malformed_lines_do_not_inherit_previous_day(tmp_path: Path) -> None:
    draft = _preview(
        tmp_path,
        "請協助解析以下行程\n(273689/2589087)\n"
        "D1：起點 - C1\n備註：這一行不是行程\n- 不可接回D1\n"
        "D2：C1 - 營地C2 -\nD3 沒有冒號\n(273734/2589025)\n"
        "D4：C2 - 終點C3\n\n（273689/2589087）",
    )
    assert [day.mission_day_id for day in draft.days] == ["D1", "D2", "D4"]
    assert [day.ordered_place_mentions for day in draft.days] == [["起點"], ["營地"], ["終點"]]
    assert all(day.coordinate_hints == [] for day in draft.days)
    assert {gap for gap in draft.unresolved_gaps if gap.startswith("unparsed_line:")} == {
        "unparsed_line:請協助解析以下行程",
        "unparsed_line:(273689/2589087)",
        "unparsed_line:備註：這一行不是行程",
        "unparsed_line:- 不可接回D1",
        "unparsed_line:D3 沒有冒號",
        "unparsed_line:(273734/2589025)",
        "unparsed_line:（273689/2589087）",
    }


def test_day_header_takes_precedence_over_trailing_separator(tmp_path: Path) -> None:
    draft = _preview(tmp_path, "D0: Taipei - trailhead C0\nD1: C0 - summit -\nD2: camp C1")
    assert draft.days[0].day_kind == "logistics"
    assert draft.days[0].resolved_targets == ["Taipei", "trailhead"]
    assert draft.days[1].ordered_place_mentions == ["summit"]
    assert draft.days[2].ordered_place_mentions == ["camp"]
    assert all(day.day_kind == "on_trail" for day in draft.days[1:])


def test_exact_submission_hash_is_not_changed_by_parse_normalization(tmp_path: Path) -> None:
    source = " \r\n D1： 起點 -\r\n  Nas-maya C1  \r\n"
    workbench = _workbench(tmp_path)
    request = BaselineAuthoringRequest(mode="human_text", human_text=source)
    first = workbench.preview_baseline(request)
    repeated = workbench.preview_baseline(request)
    single_line = workbench.preview_baseline(
        BaselineAuthoringRequest(mode="human_text", human_text="D1：起點 - Nas-maya C1")
    )
    assert first.source_text == source
    assert first.source_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert repeated.draft_id == first.draft_id
    assert single_line.source_sha256 != first.source_sha256
    assert single_line.days[0].ordered_place_mentions == first.days[0].ordered_place_mentions


def test_orphan_only_input_still_requires_a_day_header(tmp_path: Path) -> None:
    with pytest.raises(ContextualPermissionConflict) as error:
        _preview(tmp_path, "(273689/2589087)\nH1648營C2\n- Nas-maya")
    assert error.value.code == "baseline_days_missing"


def test_actual_four_day_text_through_preview_api_has_no_workspace_effects(
    tmp_path: Path,
) -> None:
    from test_scout_contextual_permission_workbench_api import PROJECT_ID, _client

    client, store_root = _client(tmp_path)
    # The HTTP middleware appends its normal runtime audit outside the project.
    # The preview contract forbids changes to workspace data and candidate state.
    workspace_root = tmp_path / "workspace"
    before = _files(workspace_root)
    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline/preview",
        json={"mode": "human_text", "human_text": FOUR_DAY_TEXT},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_text"] == FOUR_DAY_TEXT
    assert payload["source_sha256"] == hashlib.sha256(FOUR_DAY_TEXT.encode()).hexdigest()
    assert [day["mission_day_id"] for day in payload["days"]] == ["D1", "D2", "D3", "D4"]
    assert payload["days"][0]["coordinate_hints"][0]["confirmed_crs"] is None
    assert payload["days"][1]["ordered_place_mentions"][-1] == "H1648營"
    assert payload["days"][3]["ordered_place_mentions"][0] == "腰繞至Nas-maya"
    assert payload["days"][2]["branch_candidates"] == [
        {"label": "異祿閣", "kind": "out_and_back_candidate", "reviewed": False}
    ]
    assert payload["validation_state"] == "needs_review"
    assert payload["writes_performed"] is False
    assert payload["candidate_only"] is True and payload["runtime_safety_truth"] is False
    assert payload["departure_approval_granted"] is False
    assert not store_root.exists()
    assert _files(workspace_root) == before
