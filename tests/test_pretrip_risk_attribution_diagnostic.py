import json
from pathlib import Path

from pretrip_risk_attribution_diagnostic import (
    build_risk_attribution_diagnostic,
    classify_semantic_checkpoint,
)


def test_classifies_semantic_attention_from_ai_route_note_fields() -> None:
    assert (
        classify_semantic_checkpoint(
            {
                "checkpoint_type": "warning_review",
                "source_note_category": "hazard_hint",
                "route_note_summary": "大崩塌勿右切/架繩取左小徑",
            }
        )
        == "danger"
    )
    assert (
        classify_semantic_checkpoint(
            {
                "checkpoint_type": "hint_review",
                "source_note_category": "route_condition_hint",
                "route_note_summary": "上切後接稜線",
            }
        )
        == "technical_caution"
    )
    assert (
        classify_semantic_checkpoint(
            {
                "checkpoint_type": "water_or_camp_review",
                "source_note_category": "camp_or_water_hint",
                "route_note_summary": "034-下切水源",
            }
        )
        == "context"
    )


def test_builds_decomposed_risk_attribution_without_mutating_score(tmp_path: Path) -> None:
    route_risk = tmp_path / "route_risk.geojson"
    gis_perception = tmp_path / "gis_perception_candidates.json"
    route_note_ln = tmp_path / "route_note_ln_proposals.json"
    route_risk.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _risk_feature(
                        sample_id="sample.low",
                        lat=24.0,
                        lon=121.0,
                        teii_20m=20,
                        tri=10,
                        sri=0,
                        lec=30,
                        scp=0,
                        pretrip_risk=20,
                    ),
                    _risk_feature(
                        sample_id="sample.high",
                        lat=24.0005,
                        lon=121.0005,
                        teii_20m=95,
                        tri=98,
                        sri=40,
                        lec=97,
                        scp=0,
                        pretrip_risk=76,
                    ),
                    _risk_feature(
                        sample_id="sample.mid",
                        lat=24.001,
                        lon=121.001,
                        teii_20m=60,
                        tri=50,
                        sri=10,
                        lec=70,
                        scp=0,
                        pretrip_risk=55,
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    gis_perception.write_text(
        json.dumps(
            {
                "checkpoint_candidates": [
                    {
                        "candidate_id": "gis_cp.warning",
                        "source_route_note_candidate_id": "route_note.warning",
                        "checkpoint_type": "warning_review",
                        "source_note_category": "hazard_hint",
                        "route_note_summary": "大崩塌勿右切",
                        "lat": 24.00051,
                        "lon": 121.00051,
                        "candidate_only": True,
                    },
                    {
                        "candidate_id": "gis_cp.water",
                        "source_route_note_candidate_id": "route_note.water",
                        "checkpoint_type": "water_or_camp_review",
                        "source_note_category": "camp_or_water_hint",
                        "route_note_summary": "最後水源",
                        "lat": 24.0,
                        "lon": 121.0,
                        "candidate_only": True,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    route_note_ln.write_text(
        json.dumps(
            {
                "proposals": [
                    {
                        "proposal_id": "ln_proposal.warning",
                        "source_route_note_candidate_id": "route_note.warning",
                        "proposal_kind": "warning_coverage",
                        "source_note_category": "hazard_hint",
                        "route_note_summary": "大崩塌勿右切",
                        "lat": 24.00051,
                        "lon": 121.00051,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    diagnostic = build_risk_attribution_diagnostic(
        route_risk_path=route_risk,
        gis_perception_path=gis_perception,
        route_note_ln_proposals_path=route_note_ln,
        join_radius_m=100,
    )

    assert diagnostic["status"] == "candidate_only_diagnostic"
    assert diagnostic["boundary"]["weighted_risk_score_mutation_allowed"] is False
    assert diagnostic["counts"]["danger_checkpoint_count"] == 1
    assert diagnostic["counts"]["context_checkpoint_count"] == 1
    assert diagnostic["counts"]["attention_matched_within_join_radius_count"] == 1
    danger_group = diagnostic["groups"]["danger"]
    assert danger_group["nearest_sample_dimension_stats"]["teii_20m"]["mean"] == 95
    assert (
        danger_group["matched_nearest_sample_dimension_stats"]["teii_20m"]["mean"]
        == 95
    )
    assert danger_group["nearest_dimension_ratios"]["teii_20m"]["above_route_p75_ratio"] == 1
    assert (
        danger_group["matched_nearest_dimension_ratios"]["teii_20m"][
            "above_route_p75_ratio"
        ]
        == 1
    )
    assert danger_group["nearest_dimension_ratios"]["scp"]["reason"] == "zero_variance"
    assert any(
        observation["observation_id"] == "semantic_scp_not_reflected"
        for observation in diagnostic["observations"]
    )
    formula = diagnostic["factor_analysis"]["formula_candidate"]
    assert formula["status"] == "candidate_only"
    assert formula["selected_dimensions"] == ["tri", "teii_20m", "lec"]
    assert "sri" in diagnostic["factor_analysis"]["excluded_dimensions"]
    warning_cp = diagnostic["excluded_extreme_warning_cp_proposals"]
    assert warning_cp["status"] == "candidate_only"
    assert warning_cp["selected_formula_dimensions"] == [
        "lec",
        "teii_20m",
        "tri",
    ]
    assert warning_cp["excluded_dimensions"] == ["sri"]
    assert warning_cp["counts"]["proposal_count"] >= 1
    assert warning_cp["proposals"][0]["candidate_kind"] == "warning_cp_proposal"
    assert warning_cp["proposals"][0]["runtime_safety_truth"] is False
    assert diagnostic["top_semantic_attention_matches"][0]["nearest_dimensions"] == {
        "teii_20m": 95.0,
        "tri": 98.0,
        "sri": 40.0,
        "lec": 97.0,
        "scp": 0.0,
        "pretrip_risk": 76.0,
    }


def _risk_feature(
    *,
    sample_id: str,
    lat: float,
    lon: float,
    teii_20m: float,
    tri: float,
    sri: float,
    lec: float,
    scp: float,
    pretrip_risk: float,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": {
            "sample_id": sample_id,
            "teii_20m": teii_20m,
            "tri": tri,
            "sri": sri,
            "lec": lec,
            "scp": scp,
            "pretrip_risk": pretrip_risk,
        },
    }
