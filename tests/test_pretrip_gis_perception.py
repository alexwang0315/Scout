import json
from pathlib import Path

from pretrip_gis_perception import build_gpx_gis_perception


def test_builds_candidate_only_gis_perception_from_golden_route_and_references(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "能高安東軍縱走.gpx.gpx",
        name="golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.01, 121.01, 1010.0, "2026-05-01T00:10:00Z"),
        ],
        waypoints=[
            (24.001, 121.001, "崩塌小心", "架繩通過", ""),
            (24.004, 121.004, "水源", "穩定水源需複查", ""),
        ],
    )
    reference = _write_gpx(
        tmp_path / "reference.gpx",
        name="reference",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.02, 121.02, 1020.0, "2026-05-01T00:20:00Z"),
        ],
        waypoints=[
            (24.012, 121.012, "路徑不明", "下切後有路", ""),
            (24.014, 121.014, "遠眺點", "山稜展望", ""),
        ],
    )

    result = build_gpx_gis_perception(
        project_id="fixture_import",
        primary_gpx_path=golden_route,
        reference_gpx_paths=[reference],
        primary_artifact_id="artifact.gpx.fixture_import",
    )
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    assert result.route_note_candidates.counts.note_candidate_count == 4
    assert result.route_note_candidates.counts.potential_ln_signal_count == 2
    assert result.route_note_candidates.counts.route_note_time_unknown_count == 4
    assert result.route_note_candidates.counts.stale_route_note_count == 0
    assert result.route_note_ln_proposals.counts.proposal_count == 2
    assert result.gis_perception.counts.source_gpx_count == 2
    assert result.gis_perception.counts.gpx_route_note_candidate_count == 4
    assert result.gis_perception.counts.gpx_ln_proposal_count == 2
    assert result.gis_perception.counts.checkpoint_candidate_count == 3
    assert result.gis_perception.boundary.candidate_only is True
    assert result.gis_perception.boundary.phase1_runtime_mutation_allowed is False
    assert result.gis_perception.classifier.classifier_kind == "pydantic_ai_structured_judgement"
    assert result.gis_perception.classifier.provider_kind == "pydantic_ai_test"
    assert result.gis_perception.classifier.pydantic_ai_invoked is True
    assert result.gis_perception.classifier.judgement_count == 4
    assert result.gis_perception.classifier.prompt_sha256
    assert result.gis_perception.classifier.live_model_call_performed is False
    assert result.gis_perception_ai_judgements.boundary.candidate_only is True
    assert (
        result.gis_perception_ai_judgements.boundary.phase1_runtime_mutation_allowed
        is False
    )
    assert result.gis_perception_ai_judgements.boundary.phase2_writeback_allowed is False
    assert result.gis_perception_ai_judgements.boundary.package_mutation_allowed is False
    assert result.gis_perception_ai_judgements.boundary.raw_gpx_embedded is False
    assert result.gis_perception_ai_judgements.source_refs
    assert result.gis_perception_ai_judgements.counts is not None
    assert result.gis_perception_ai_judgements.counts.input_count == 4
    assert result.gis_perception_ai_judgements.counts.judgement_count == 4
    assert result.gis_perception_ai_judgements.counts.source_ref_count == len(
        result.gis_perception_ai_judgements.source_refs
    )
    assert result.gis_perception_ai_judgements.counts.candidate_only_count == 4
    assert result.gis_perception_ai_judgements.counts.human_review_required_count == 4
    assert result.gis_perception_ai_judgements.counts.runtime_safety_truth_count == 0
    assert result.gis_perception_ai_judgements.counts.package_mutation_count == 0
    assert result.gis_perception_ai_judgements.counts.phase1_runtime_mutation_count == 0
    assert result.gis_perception_ai_judgements.counts.phase2_writeback_count == 0
    assert result.gis_perception_ai_judgements.counts.raw_model_output_count == 0
    assert all(
        judgement.source_refs
        and judgement.prompt_sha256 == result.gis_perception.classifier.prompt_sha256
        and judgement.pydantic_ai_prompt_version
        == "scout.gis_perception.structured_judgement.v0"
        and len(judgement.model_output_sha256) == 64
        and judgement.model_output_summary
        and judgement.review_state == "needs_review"
        and judgement.runtime_safety_truth is False
        for judgement in result.gis_perception_ai_judgements.judgements
    )
    assert {
        candidate.checkpoint_type
        for candidate in result.gis_perception.checkpoint_candidates
    } == {
        "warning_review",
        "hint_review",
        "water_or_camp_review",
    }
    assert all(
        candidate.source_gpx_role in {"golden_route_reference", "reference_track"}
        for candidate in result.gis_perception.checkpoint_candidates
    )
    assert all(
        candidate.ai_judgement_id.startswith("gis_ai_judgement.gpx_route_note.")
        for candidate in result.gis_perception.checkpoint_candidates
    )
    assert all(
        candidate.ai_reason_zh and candidate.runtime_safety_truth is False
        for candidate in result.gis_perception.checkpoint_candidates
    )
    assert all(
        candidate.source_attribution
        and candidate.source_attribution[0].source_kind == "gpx_route_note"
        and candidate.source_attribution[0].source_profile == "gpx_corpus_route_notes"
        and candidate.source_attribution[0].runtime_safety_truth is False
        for candidate in result.gis_perception.checkpoint_candidates
    )
    assert "<gpx" not in serialized.lower()
    assert "<trkpt" not in serialized.lower()


def _write_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float, str]],
    waypoints: list[tuple[float, float, str, str, str]],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wpts = "\n".join(
        (
            f'<wpt lat="{lat}" lon="{lon}">'
            f"<name>{wpt_name}</name><cmt>{cmt}</cmt><desc>{desc}</desc>"
            "</wpt>"
        )
        for lat, lon, wpt_name, cmt, desc in waypoints
    )
    trkpts = "\n".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele><time>{time}</time></trkpt>'
        for lat, lon, ele, time in points
    )
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
                f"<metadata><name>{name}</name></metadata>",
                wpts,
                "<trk><trkseg>",
                trkpts,
                "</trkseg></trk>",
                "</gpx>",
            ]
        ),
        encoding="utf-8",
    )
    return path
