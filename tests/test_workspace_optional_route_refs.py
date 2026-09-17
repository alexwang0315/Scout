"""Missing optional route artifacts must not mask valid post-trip evidence."""

import json
from pathlib import Path

import pytest

from scout_workspace_search_tools import search_project_route_structure


REF_KEYS = (
    'route_summary_ref',
    'checkpoint_candidates_ref',
    'segment_candidates_ref',
    'historical_gpx_source_index_ref',
    'reference_tracks_ref',
)


@pytest.mark.parametrize('refs', [{}, dict.fromkeys(REF_KEYS, ''), dict.fromkeys(REF_KEYS)])
def test_missing_optional_refs_leave_route_evidence_unavailable(tmp_path: Path, refs: dict) -> None:
    (tmp_path / 'project.json').write_text(json.dumps({'project_id': 'post-trip', **refs}))

    result = search_project_route_structure(tmp_path, query='行後回顧')

    assert result['results'] == []
    assert result['source_ref'] is None
    assert result['summaries']['historical_gpx_overlap']['available'] is False
    assert result['summaries']['reference_tracks']['available'] is False
    assert result['boundary']['runtime_safety_truth'] is False
    assert result['boundary']['read_only'] is True
    assert result['boundary']['phase1_safety_mutation_allowed'] is False


def test_null_historical_gpx_lists_are_treated_as_empty(tmp_path: Path) -> None:
    (tmp_path / 'project.json').write_text(json.dumps({
        'project_id': 'post-trip',
        'historical_gpx_source_index_ref': 'history.json',
        'reference_tracks_ref': 'tracks.json',
    }))
    (tmp_path / 'history.json').write_text(json.dumps({'sources': None}))
    (tmp_path / 'tracks.json').write_text(json.dumps({'reference_tracks': None}))

    result = search_project_route_structure(tmp_path, query='行後回顧')

    assert result['summaries']['historical_gpx_overlap'] == {
        'available': True,
        'source_count': 0,
        'reference_track_count': 0,
        'overlap_count': 0,
        'overlapping_sources': [],
        'source_refs': ['history.json', 'tracks.json'],
        'overlap_source_ref': 'tracks.json',
        'join_method': 'reference_id_numeric_suffix',
        'candidate_only': True,
        'runtime_safety_truth': False,
    }


def test_null_checkpoint_events_are_treated_as_empty(tmp_path: Path) -> None:
    (tmp_path / 'project.json').write_text(json.dumps({'project_id': 'post-trip'}))
    (tmp_path / 'outputs').mkdir()
    (tmp_path / 'outputs' / 'checkpoint_events.json').write_text(
        json.dumps({'events': None})
    )

    result = search_project_route_structure(tmp_path, query='行後回顧')

    assert result['summaries']['checkpoint_events'] == {
        'available': False,
        'event_count': 0,
        'observed_at_count': 0,
        'planned_time_count': 0,
        'live_actual_count': 0,
        'first_observed_at': None,
        'last_observed_at': None,
        'source_ref': 'outputs/checkpoint_events.json',
        'candidate_only': True,
        'runtime_safety_truth': False,
    }


@pytest.mark.parametrize('ref_key', REF_KEYS[:3])
def test_explicit_directory_artifact_ref_still_fails(tmp_path: Path, ref_key: str) -> None:
    (tmp_path / 'project.json').write_text(json.dumps({'project_id': 'bad-ref', ref_key: 'artifact'}))
    (tmp_path / 'artifact').mkdir()

    with pytest.raises(IsADirectoryError):
        search_project_route_structure(tmp_path, query='行後回顧')


@pytest.mark.parametrize('ref_key', REF_KEYS[:3])
def test_invalid_json_artifact_is_not_converted_to_missing(tmp_path: Path, ref_key: str) -> None:
    (tmp_path / 'project.json').write_text(json.dumps({'project_id': 'bad-json', ref_key: 'artifact.json'}))
    (tmp_path / 'artifact.json').write_text('{bad json')

    with pytest.raises(json.JSONDecodeError):
        search_project_route_structure(tmp_path, query='行後回顧')
