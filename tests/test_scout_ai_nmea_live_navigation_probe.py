from __future__ import annotations

from tools.pi_gnss_nmea_smoke import nmea_checksum_valid
from tools.scout_ai_nmea_live_navigation_probe import (
    DEFAULT_QUESTION,
    build_probe_report,
)


def test_nmea_live_navigation_probe_generates_two_checksum_valid_scenarios() -> None:
    report = build_probe_report(question=DEFAULT_QUESTION)

    assert report["scenario_count"] == 2
    by_id = {scenario["scenario_id"]: scenario for scenario in report["scenarios"]}
    assert set(by_id) == {
        "normal_inside_corridor_low_risk",
        "off_route_high_risk_candidate",
    }

    for scenario in by_id.values():
        assert len(scenario["nmea_sentences"]) == 3
        assert all(nmea_checksum_valid(sentence) for sentence in scenario["nmea_sentences"])
        assert scenario["checksum_valid_count"] == 3
        assert scenario["gnss_fix"]["valid"] is True
        assert scenario["gnss_fix"]["lat"] is not None
        assert scenario["gnss_fix"]["lon"] is not None

    normal = by_id["normal_inside_corridor_low_risk"]
    assert normal["evaluation"]["classification"] == "normal_inside_corridor_low_risk"
    assert normal["route_match"]["inside_corridor"] is True
    assert normal["risk_context"]["score"] < 70.0

    hazard = by_id["off_route_high_risk_candidate"]
    assert hazard["evaluation"]["classification"] == "off_route_high_risk_candidate"
    assert hazard["route_match"]["inside_corridor"] is False
    assert hazard["route_match"]["distance_m"] > hazard["route_match"]["allowed_corridor_m"]
    assert hazard["risk_context"]["score"] >= 70.0


def test_scout_ai_answers_normal_and_hazard_nmea_scenarios_differently() -> None:
    report = build_probe_report(question=DEFAULT_QUESTION)
    answers = {
        item["scenario_id"]: item["answer"]
        for item in report["assistant_results"]
    }

    assert "目前不像是站在危險邊緣" in answers["normal_inside_corridor_low_risk"]
    assert "已偏離主路且靠近高風險邊緣" in answers["off_route_high_risk_candidate"]
    assert "沒有呼叫 /safety/*" in answers["off_route_high_risk_candidate"]
    assert all(
        result["boundary"]["safety_mutation_allowed"] is False
        and result["boundary"]["outbound_send_allowed"] is False
        for result in report["assistant_results"]
    )
