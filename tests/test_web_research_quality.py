from __future__ import annotations

from scout.agents.web_research_quality import (
    ResearchQuestionSpec,
    build_web_evidence_bundle,
    compact_evidence_for_synthesis,
    evaluate_web_research,
    extract_research_links,
    select_research_url,
)


def _trace(*fetches: tuple[str, str]) -> dict[str, object]:
    search_results = [
        {"title": f"result {index}", "url": url, "snippet": content[:80]}
        for index, (url, content) in enumerate(fetches, start=1)
    ]
    tool_calls = [{"tool_name": "scout_web_search"}]
    tool_returns: list[dict[str, object]] = [
        {"tool_name": "scout_web_search", "content": search_results}
    ]
    for url, content in fetches:
        tool_calls.append({"tool_name": "scout_web_fetch"})
        tool_returns.append(
            {
                "tool_name": "scout_web_fetch",
                "content": {
                    "url": url,
                    "status": 200,
                    "content_type": "text/html",
                    "content": content,
                    "fetched_at": "2026-08-20T04:00:00Z",
                    "content_hash": "sha256:test",
                    "truncated": False,
                },
            }
        )
    return {
        "model_request_count": 3,
        "tool_call_count": len(tool_calls),
        "tool_return_count": len(tool_returns),
        "tool_calls": tool_calls,
        "tool_returns": tool_returns,
        "retry_prompts": [],
        "source_urls": [url for url, _content in fetches],
    }


def _case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "case_id": "WEB-TEST",
        "question": "請查官方資料並回答。",
        "allowed_domains": ["cwa.gov.tw"],
        "requires_search": True,
        "requires_fetch": True,
        "freshness_required": False,
        "topic_terms": [],
        "required_fields": ["url"],
        "required_evidence_literals": [],
        "source_groups": {"official": ["cwa.gov.tw"]},
        "absence_sensitive": False,
    }
    case.update(overrides)
    return case


def test_extract_research_links_finds_relevant_same_domain_adjacent_page() -> None:
    content = """
    <nav>
      <a href="?code=list&amp;ids=66">119、112</a>
      <a href="index.php?code=list&amp;ids=68">報案要領</a>
      <a href="https://example.com/untrusted">報案要領鏡像</a>
    </nav>
    """

    links = extract_research_links(
        content,
        base_url="https://www.nfa.gov.tw/cht/?code=list&ids=66",
        focus_terms=["報案要領", "案發地點", "相對位置", "座標"],
        allowed_domains=["nfa.gov.tw"],
    )

    assert links == [
        {
            "title": "報案要領",
            "url": "https://www.nfa.gov.tw/cht/index.php?code=list&ids=68",
            "snippet": "報案要領",
        }
    ]


def test_url_selector_prefers_descriptive_topic_over_generic_numeric_term() -> None:
    spec = ResearchQuestionSpec.model_validate(
        {
            "case_id": "WEB-012",
            "question": "山域事故打119時最少應提供哪些資訊？",
            "allowed_domains": ["nfa.gov.tw"],
            "topic_terms": ["119", "報案要領", "位置"],
            "required_evidence_literals": [
                "119",
                "案發地點",
                "相對位置",
                "座標",
                "原因",
            ],
        }
    )
    results = [
        {
            "title": "119、112",
            "url": "https://www.nfa.gov.tw/cht/?code=list&ids=66",
            "snippet": "119、112使用時機",
        },
        {
            "title": "報案要領",
            "url": "https://www.nfa.gov.tw/cht/index.php?code=list&ids=68",
            "snippet": "報案要領",
        },
    ]

    selected = select_research_url(results, spec, attempted_urls=set())

    assert selected is not None
    assert selected["url"].endswith("ids=68")


def test_evidence_bundle_uses_existing_evidence_card_contract() -> None:
    url = "https://www.cwa.gov.tw/V8/C/W/Warning.html"
    spec = ResearchQuestionSpec.model_validate(_case())

    bundle = build_web_evidence_bundle(
        _trace((url, "中央氣象署 豪雨特報 2026-08-20")),
        spec,
    )

    assert len(bundle.cards) == 1
    assert bundle.cards[0].tool_id == "scout_web_fetch"
    assert bundle.cards[0].source_refs == [url]
    assert bundle.cards[0].evidence_records[0].source_hash == "sha256:test"
    assert bundle.source_groups_found == ["official"]


def test_false_sunrise_times_are_a_semantic_hard_fail() -> None:
    url = "https://www.cwa.gov.tw/V8/C/W/Astronomy.html"
    case = _case(
        case_id="WEB-004",
        question="明天南投縣日出與日沒時間？",
        topic_terms=["日出", "日沒"],
        required_fields=["date", "time:2", "url"],
    )

    grading = evaluate_web_research(
        case,
        answer=f"2026-08-21 日出06:00、日沒18:00。{url}",
        trace=_trace((url, "南投縣 日出日沒資料 日期 2026-08-21")),
        current_date="2026-08-20",
    )

    assert grading["layers"]["transport"]["passed"] is True
    assert grading["layers"]["evidence_sufficiency"]["passed"] is False
    assert grading["layers"]["semantic_correctness"]["passed"] is False
    assert "unsupported_factual_tokens" in grading["hard_fail_reasons"]
    assert grading["passed"] is False


def test_generic_page_cannot_prove_no_closure() -> None:
    url = "https://www.taroko.gov.tw/ch"
    case = _case(
        case_id="WEB-005",
        question="奇萊山區目前是否封閉或管制？",
        allowed_domains=["taroko.gov.tw"],
        topic_terms=["奇萊", "管制"],
        required_fields=["status", "url"],
        source_groups={"trail_status": ["taroko.gov.tw"]},
        absence_sensitive=True,
    )

    grading = evaluate_web_research(
        case,
        answer=f"目前奇萊山區沒有封閉或管制，可正常通行。{url}",
        trace=_trace((url, "太魯閣國家公園 奇萊山步道景觀介紹")),
        current_date="2026-08-20",
    )

    assert grading["checks"]["absence_claim_supported"] is False
    assert "unsupported_absence_claim" in grading["hard_fail_reasons"]
    assert grading["passed"] is False


def test_wrong_dataset_code_is_rejected_even_with_topic_overlap() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/forecast"
    case = _case(
        case_id="WEB-013",
        question="F-C0041-001 是什麼資料？",
        allowed_domains=["opendata.cwa.gov.tw"],
        topic_terms=["F-C0041-001", "降水"],
        required_fields=["dataset_code", "time_range", "update_frequency", "url"],
        required_evidence_literals=["F-C0041-001"],
        required_answer_literals=["F-C0041-001"],
        source_groups={"cwa_dataset": ["opendata.cwa.gov.tw"]},
    )

    grading = evaluate_web_research(
        case,
        answer=f"O-A0001-001 是逐時氣象觀測資料。{url}",
        trace=_trace((url, "F-C0041-001 0-6 小時定量降水預報 每 6 小時更新")),
        current_date="2026-08-20",
    )

    assert grading["checks"]["required_literals_in_answer"] is False
    assert grading["checks"]["factual_tokens_grounded"] is False
    assert grading["passed"] is False


def test_chinese_answer_dates_match_iso_evidence_and_run_date() -> None:
    url = "https://tconline.forest.gov.tw/"
    case = _case(
        question="天池山莊目前最新公告是什麼？",
        allowed_domains=["forest.gov.tw"],
        freshness_required=True,
        topic_terms=["天池山莊"],
        required_fields=["date", "status", "url"],
        required_answer_literals=["2026-08-10", "減少開放"],
        source_groups={"official": ["forest.gov.tw"]},
    )
    answer = (
        "截至2026年8月20日，天池山莊最新公告日期為2026年8月10日，"
        f"狀態是減少開放部分床位與營地。來源：{url}"
    )

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=_trace((url, "天池山莊 2026-08-10 公告：減少開放部分床位與營地。")),
        current_date="2026-08-20",
    )

    assert grading["checks"]["factual_tokens_grounded"] is True
    assert grading["passed"] is True


def test_complete_fields_without_question_topic_are_incomplete() -> None:
    url = "https://tconline.forest.gov.tw/"
    case = _case(
        question="天池山莊目前最新公告是什麼？",
        allowed_domains=["forest.gov.tw"],
        topic_terms=["天池山莊"],
        required_fields=["date", "status", "url"],
        source_groups={"official": ["forest.gov.tw"]},
    )

    grading = evaluate_web_research(
        case,
        answer=f"2026-08-10、減少開放。來源：{url}",
        trace=_trace((url, "天池山莊 2026-08-10 公告：減少開放。")),
        current_date="2026-08-20",
    )

    assert grading["checks"]["topic_coverage"] is False
    assert grading["passed"] is False


def test_placeholder_and_prompt_leak_are_hard_failures() -> None:
    url = "https://www.cwa.gov.tw/V8/C/W/Warning.html"
    trace = _trace((url, "南投縣目前無生效中的豪雨特報"))

    placeholder = evaluate_web_research(
        _case(),
        answer="繁中短答，含日期與實際URL",
        trace=trace,
        current_date="2026-08-20",
    )
    leaked = evaluate_web_research(
        _case(),
        answer='工具證據:{"action":"tool","tool_name":"scout_web_fetch"}',
        trace=trace,
        current_date="2026-08-20",
    )

    assert "placeholder_output" in placeholder["hard_fail_reasons"]
    assert "prompt_leak" in leaked["hard_fail_reasons"]


def test_multi_source_join_requires_every_source_group() -> None:
    cwa_url = "https://www.cwa.gov.tw/V8/C/W/Warning.html"
    case = _case(
        case_id="WEB-019",
        question="比較南投天氣與台14甲道路狀態。",
        allowed_domains=["cwa.gov.tw", "thb.gov.tw"],
        topic_terms=["南投", "台14甲"],
        required_fields=["status", "url:2", "manual_review_reason"],
        source_groups={
            "weather": ["cwa.gov.tw"],
            "road": ["thb.gov.tw", "168.thb.gov.tw"],
        },
    )

    grading = evaluate_web_research(
        case,
        answer=f"南投天氣需人工複核，但尚未確認台14甲。{cwa_url}",
        trace=_trace((cwa_url, "南投縣豪雨特報")),
        current_date="2026-08-20",
    )

    assert grading["checks"]["required_source_groups"] is False
    assert grading["layers"]["evidence_sufficiency"]["passed"] is False


def test_url_selector_prefers_required_dataset_over_first_generic_result() -> None:
    spec = ResearchQuestionSpec.model_validate(
        _case(
            case_id="WEB-013",
            question="F-C0041-001 是什麼資料？",
            allowed_domains=["cwa.gov.tw", "opendata.cwa.gov.tw"],
            topic_terms=["F-C0041-001", "降水"],
            required_evidence_literals=["F-C0041-001"],
        )
    )
    results = [
        {
            "title": "中央氣象署首頁",
            "url": "https://www.cwa.gov.tw/",
            "snippet": "天氣與地震資訊",
        },
        {
            "title": "F-C0041-001 定量降水預報",
            "url": "https://opendata.cwa.gov.tw/dataset/F-C0041-001",
            "snippet": "0-6小時定量降水預報資料集",
        },
    ]

    selected = select_research_url(results, spec, attempted_urls=set())

    assert selected is not None
    assert selected["url"].endswith("F-C0041-001")


def test_url_selector_prefers_dated_status_notice_over_route_overview() -> None:
    spec = ResearchQuestionSpec.model_validate(
        _case(
            question="能高越嶺道目前有沒有最新開放、施工或封閉公告？",
            topic_terms=["天池山莊", "能高越嶺"],
            required_fields=["date", "status", "url"],
            absence_sensitive=True,
        )
    )
    results = [
        {
            "title": "能高越嶺道",
            "url": "https://tconline.forest.gov.tw/fetrip/?parent_id=195",
            "snippet": "能高越嶺道歷史與路線介紹，天池山莊提供住宿。",
        },
        {
            "title": "天池山莊",
            "url": "https://tconline.forest.gov.tw/",
            "snippet": "能高越嶺道115年1月1日起開放，另有最新注意事項。",
        },
    ]

    selected = select_research_url(results, spec, attempted_urls=set())

    assert selected is not None
    assert selected["url"] == "https://tconline.forest.gov.tw/"


def test_explicit_official_absence_can_pass() -> None:
    url = "https://www.cwa.gov.tw/V8/C/W/Warning.html"
    case = _case(
        case_id="WEB-001",
        question="南投目前是否有豪雨特報？",
        topic_terms=["南投", "特報"],
        required_fields=["status", "url"],
        absence_sensitive=True,
    )
    answer = f"截至2026-08-20，官方狀態顯示南投目前無生效中的豪雨特報。{url}"

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=_trace((url, "南投縣目前無生效中的豪雨特報 更新日期 2026-08-20")),
        current_date="2026-08-20",
    )

    assert grading["checks"]["absence_claim_supported"] is True
    assert grading["hard_fail_reasons"] == []
    assert grading["passed"] is True


def test_compound_no_construction_or_closure_claim_needs_absence_evidence() -> None:
    url = "https://tconline.forest.gov.tw/fetrip/?parent_id=195"
    case = _case(
        question="能高越嶺道目前有沒有施工或封閉公告？",
        topic_terms=["能高越嶺"],
        required_fields=["date", "status", "url"],
        absence_sensitive=True,
    )
    answer = f"截至2026-08-20，目前開放，無施工或封閉公告。來源：{url}"

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=_trace((url, "能高越嶺道路線介紹 更新日期2026-08-20")),
        current_date="2026-08-20",
    )

    assert grading["checks"]["absence_claim_supported"] is False
    assert "unsupported_absence_claim" in grading["hard_fail_reasons"]


def test_bare_absence_cannot_contradict_active_warning_evidence() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-001"
    case = _case(
        case_id="WEB-017",
        question="目前是否有濃霧或陸上強風特報？",
        topic_terms=["濃霧", "強風"],
        required_fields=["status", "url"],
        absence_sensitive=True,
    )
    answer = (
        "目前中央氣象署未發佈濃霧或陸上強風特報。"
        "證據卡顯示官方資料中無濃霧或陸上強風特報的生效記錄。"
        f"來源：{url}"
    )

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=_trace(
            (
                url,
                "查詢狀態=active；災種狀態=濃霧:inactive,陸上強風:active；"
                "陸上強風特報目前生效中",
            )
        ),
        current_date="2026-08-20",
    )

    assert grading["checks"]["status_not_contradictory"] is False
    assert "contradictory_status_claim" in grading["hard_fail_reasons"]
    assert grading["passed"] is False


def test_labeled_field_dump_is_not_a_natural_language_answer() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-001"
    answer = (
        "查詢日期:2026-08-20\n"
        "目前狀態:豪雨特報生效中\n"
        f"官方來源網址:{url}"
    )

    grading = evaluate_web_research(
        _case(
            topic_terms=["豪雨"],
            required_fields=["date", "status", "url"],
        ),
        answer=answer,
        trace=_trace((url, "豪雨特報生效中 2026-08-20")),
        current_date="2026-08-20",
    )

    assert "machine_labeled_user_answer" in grading["hard_fail_reasons"]
    assert grading["checks"]["natural_language_answer"] is False
    assert grading["passed"] is False


def test_markdown_labeled_field_dump_is_not_a_natural_language_answer() -> None:
    url = "https://tconline.forest.gov.tw/"
    answer = (
        "目前有最新公告。\n"
        "- **date**: 2026-08-10\n"
        "- **status**: 減少開放部分床位\n"
        f"- **url**: {url}"
    )

    grading = evaluate_web_research(
        _case(required_fields=["date", "status", "url"]),
        answer=answer,
        trace=_trace((url, "2026-08-10 減少開放部分床位")),
        current_date="2026-08-20",
    )

    assert "machine_labeled_user_answer" in grading["hard_fail_reasons"]
    assert grading["checks"]["natural_language_answer"] is False


def test_explicit_field_list_question_accepts_concise_labeled_answer() -> None:
    url = "https://www.nfa.gov.tw/cht/index.php?code=list&ids=68"
    case = _case(
        question="山域事故打119時要提供什麼？請列成精簡欄位。",
        allowed_domains=["nfa.gov.tw"],
        topic_terms=["119", "報案要領"],
        required_fields=["position", "url"],
        required_evidence_literals=["119", "案發地點", "相對位置", "座標", "原因"],
        required_answer_literals=["案發地點", "相對位置", "座標", "原因"],
    )
    answer = (
        "案發地點：具體事故地點。\n"
        "相對位置：鄰近地標。\n"
        "座標：定位座標。\n"
        f"原因：事故原因。\n來源：{url}"
    )

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=_trace(
            (
                url,
                "119報案時先提供案發地點、相對位置、座標，再說明原因。",
            )
        ),
        current_date="2026-08-20",
    )

    assert grading["checks"]["natural_language_answer"] is True
    assert grading["checks"]["required_literals_in_answer"] is True
    assert "machine_labeled_user_answer" not in grading["hard_fail_reasons"]


def test_mixed_warning_answer_can_scope_absence_without_contradiction() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-001"
    case = _case(
        case_id="WEB-017",
        question="目前是否有濃霧或陸上強風特報？",
        topic_terms=["濃霧", "強風"],
        required_fields=["status", "url"],
        absence_sensitive=True,
    )
    evidence = (
        "查詢狀態=active；災種狀態=濃霧:inactive,陸上強風:active；"
        "陸上強風特報目前生效中"
    )
    answer = (
        "目前濃霧或陸上強風警特報狀態已有更新；"
        "其中沒有濃霧特報，但有陸上強風特報生效中。"
        f"來源：{url}"
    )

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=_trace((url, evidence)),
        current_date="2026-08-20",
    )

    assert grading["checks"]["absence_claim_supported"] is True
    assert grading["checks"]["status_not_contradictory"] is True
    assert grading["passed"] is True


def test_mixed_warning_answer_must_name_each_hazard_status() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-001"
    case = _case(
        case_id="WEB-001",
        question="目前是否有大雨或豪雨特報？",
        topic_terms=["大雨", "豪雨"],
        required_fields=["status", "url"],
        absence_sensitive=True,
    )
    evidence = (
        "查詢狀態=active；災種狀態=大雨:inactive,豪雨:active；"
        "豪雨特報目前生效中"
    )
    answer = f"目前狀態為生效中，官方來源網址為{url}"

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=_trace((url, evidence)),
        current_date="2026-08-20",
    )

    assert grading["checks"]["mixed_hazard_statuses_complete"] is False
    assert "incomplete_hazard_statuses" in grading["hard_fail_reasons"]
    assert grading["passed"] is False


def test_mixed_warning_answer_accepts_explicit_active_literals() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-001"
    evidence = "查詢狀態=active；災種狀態=大雨:inactive,豪雨:active"
    answer = (
        "南投縣的大雨狀態是 inactive，豪雨狀態是 active。"
        f"官方來源：{url}"
    )

    grading = evaluate_web_research(
        _case(
            question="目前是否有大雨或豪雨特報？",
            topic_terms=["大雨", "豪雨"],
            required_fields=["status", "url"],
        ),
        answer=answer,
        trace=_trace((url, evidence)),
        current_date="2026-08-20",
    )

    assert grading["checks"]["mixed_hazard_statuses_complete"] is True
    assert "incomplete_hazard_statuses" not in grading["hard_fail_reasons"]


def test_mixed_warning_inverted_states_are_contradictory() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-001"
    evidence = "查詢狀態=active；災種狀態=大雨:inactive,豪雨:active"
    answer = (
        "大雨特報生效，豪雨特報未生效。"
        f"官方來源：{url}"
    )

    grading = evaluate_web_research(
        _case(
            question="目前是否有大雨或豪雨特報？",
            topic_terms=["大雨", "豪雨"],
            required_fields=["status", "url"],
        ),
        answer=answer,
        trace=_trace((url, evidence)),
        current_date="2026-08-20",
    )

    assert grading["checks"]["status_not_contradictory"] is False
    assert grading["checks"]["mixed_hazard_statuses_complete"] is False
    assert "contradictory_status_claim" in grading["hard_fail_reasons"]
    assert grading["passed"] is False


def test_prompt_echo_and_stop_marker_are_hard_failures() -> None:
    url = "https://www.cwa.gov.tw/V8/C/W/Warning.html"
    answer = (
        "今天日期:2026-08-20\n問題:目前有豪雨特報嗎？\n"
        f"目前有豪雨特報。{url}<SCOUT_DONE>"
    )

    grading = evaluate_web_research(
        _case(topic_terms=["豪雨"], required_fields=["status", "url"]),
        answer=answer,
        trace=_trace((url, "豪雨特報目前生效中 2026-08-20")),
        current_date="2026-08-20",
    )

    assert "prompt_leak" in grading["hard_fail_reasons"]
    assert grading["passed"] is False


def test_structured_cwa_fetch_counts_as_official_fetch_evidence() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
    case = _case(
        case_id="WEB-013",
        question="F-C0041-001 是什麼資料？",
        allowed_domains=["opendata.cwa.gov.tw"],
        topic_terms=["F-C0041-001", "降水"],
        required_fields=["dataset_code", "time_range", "update_frequency", "url"],
        required_evidence_literals=["F-C0041-001"],
    )
    trace = {
        "model_request_count": 2,
        "tool_call_count": 1,
        "tool_return_count": 1,
        "tool_calls": [{"tool_name": "scout_cwa_structured_fetch"}],
        "tool_returns": [
            {
                "tool_name": "scout_cwa_structured_fetch",
                "content": {
                    "url": url,
                    "status": 200,
                    "content_type": "application/json",
                    "content": "F-C0041-001 0-6小時定量降水預報，每6小時更新",
                    "fetched_at": "2026-08-20T04:00:00Z",
                    "content_hash": "sha256:test",
                },
            }
        ],
        "source_urls": [url],
    }
    answer = (
        "F-C0041-001 是0-6小時定量降水預報，每6小時更新。"
        f"官方來源：{url}"
    )

    grading = evaluate_web_research(
        case,
        answer=answer,
        trace=trace,
        current_date="2026-08-20",
    )

    assert grading["checks"]["fetch_selection"] is True
    assert grading["checks"]["search_selection"] is True
    assert grading["layers"]["evidence_sufficiency"]["passed"] is True
    assert grading["passed"] is True


def test_compact_synthesis_payload_bounds_large_structured_arrays() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
    spec = ResearchQuestionSpec.model_validate(
        _case(
            allowed_domains=["opendata.cwa.gov.tw"],
            required_fields=["dataset_code", "time_range", "update_frequency", "url"],
        )
    )
    trace = {
        "tool_returns": [
            {
                "tool_name": "scout_cwa_structured_fetch",
                "content": {
                    "url": url,
                    "status": 200,
                    "content_type": "application/json",
                    "content": (
                        "F-C0041-001 0-6小時定量降水預報 每6小時更新 | "
                        + "12.345," * 50_000
                    ),
                    "fetched_at": "2026-08-20T04:00:00Z",
                    "content_hash": "sha256:test",
                },
            }
        ]
    }

    compact = compact_evidence_for_synthesis(build_web_evidence_bundle(trace, spec))

    assert len(compact) < 2_000
    assert "F-C0041-001" in compact
    assert "0-6小時" in compact
    assert "每6小時" in compact


def test_compact_synthesis_payload_selects_late_query_focused_passage() -> None:
    url = "https://www.nfa.gov.tw/cht/index.php?code=list&ids=68"
    spec = ResearchQuestionSpec.model_validate(
        _case(
            allowed_domains=["nfa.gov.tw"],
            required_fields=["position", "url"],
        )
    )
    trace = _trace(
        (
            url,
            "網站導覽 " * 800
            + "報案要領：使用行動電話報案，優先提供案發地點、相對位置、"
            "座標等地點資訊，再表明原因。",
        )
    )

    compact = compact_evidence_for_synthesis(
        build_web_evidence_bundle(trace, spec),
        focus_terms=["報案要領", "案發地點", "相對位置", "座標", "原因"],
        max_chars_per_card=500,
    )

    assert "案發地點" in compact
    assert "相對位置" in compact
    assert "座標" in compact


def test_compact_synthesis_payload_prioritizes_most_relevant_card() -> None:
    spec = ResearchQuestionSpec.model_validate(
        _case(
            allowed_domains=["nfa.gov.tw"],
            topic_terms=["119", "報案要領"],
            required_evidence_literals=["案發地點", "相對位置", "座標", "原因"],
        )
    )
    generic_url = "https://www.nfa.gov.tw/cht/?code=list&ids=66"
    relevant_url = "https://www.nfa.gov.tw/cht/index.php?code=list&ids=68"
    trace = _trace(
        (generic_url, "119、112使用時機。" * 100),
        (
            relevant_url,
            "報案要領：優先提供案發地點、相對位置、座標，再表明原因。",
        ),
    )

    compact = compact_evidence_for_synthesis(
        build_web_evidence_bundle(trace, spec),
        focus_terms=["119", "報案要領", "案發地點", "相對位置", "座標", "原因"],
        max_chars_per_card=500,
    )

    assert compact.index(relevant_url) < compact.index(generic_url)
    assert compact.count("網站導覽") < 100


def test_machine_json_and_missing_required_answer_literal_are_hard_failures() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
    case = _case(
        case_id="WEB-013",
        question="F-C0041-001 是什麼資料？",
        allowed_domains=["opendata.cwa.gov.tw"],
        topic_terms=["F-C0041-001", "降水"],
        required_fields=["dataset_code", "time_range", "update_frequency", "url"],
        required_evidence_literals=["F-C0041-001"],
        required_answer_literals=["定量降水預報", "0-6小時", "每6小時"],
    )
    trace = {
        "model_request_count": 2,
        "tool_call_count": 1,
        "tool_return_count": 1,
        "tool_calls": [{"tool_name": "scout_cwa_structured_fetch"}],
        "tool_returns": [
            {
                "tool_name": "scout_cwa_structured_fetch",
                "content": {
                    "url": url,
                    "status": 200,
                    "content_type": "application/json",
                    "content": "F-C0041-001 0-6小時定量降水預報，每6小時更新",
                    "fetched_at": "2026-08-20T04:00:00Z",
                    "content_hash": "sha256:test",
                },
            }
        ],
        "source_urls": [url],
    }

    grading = evaluate_web_research(
        case,
        answer=(
            '{"dataset_code":"F-C0041-001","time_range":"02:00-08:00",'
            f'"update_frequency":"每6小時","url":"{url}"}}'
        ),
        trace=trace,
        current_date="2026-08-20",
    )

    assert "machine_structured_user_answer" in grading["hard_fail_reasons"]
    assert "required_answer_literal_missing" in grading["hard_fail_reasons"]
    assert grading["missing_answer_literals"] == ["定量降水預報", "0-6小時"]
    assert grading["passed"] is False


def test_comma_delimited_field_dump_is_not_a_natural_language_answer() -> None:
    url = "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
    case = _case(
        case_id="WEB-013",
        question="F-C0041-001 是什麼資料？",
        allowed_domains=["opendata.cwa.gov.tw"],
        topic_terms=["F-C0041-001", "降水"],
        required_fields=["dataset_code", "time_range", "update_frequency", "url"],
        required_evidence_literals=["F-C0041-001"],
        required_answer_literals=["定量降水預報", "0-6小時", "每6小時"],
    )
    trace = {
        "model_request_count": 2,
        "tool_call_count": 1,
        "tool_return_count": 1,
        "tool_calls": [{"tool_name": "scout_cwa_structured_fetch"}],
        "tool_returns": [
            {
                "tool_name": "scout_cwa_structured_fetch",
                "content": {
                    "url": url,
                    "status": 200,
                    "content_type": "application/json",
                    "content": "F-C0041-001 0-6小時定量降水預報，每6小時更新",
                    "fetched_at": "2026-08-20T04:00:00Z",
                    "content_hash": "sha256:test",
                },
            }
        ],
        "source_urls": [url],
    }

    grading = evaluate_web_research(
        case,
        answer=(
            "F-C0041-001,定量降水預報,0-6小時,每6小時,"
            "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
        ),
        trace=trace,
        current_date="2026-08-20",
    )

    assert grading["checks"]["natural_language_answer"] is False
    assert "machine_delimited_user_answer" in grading["hard_fail_reasons"]
    assert grading["passed"] is False
