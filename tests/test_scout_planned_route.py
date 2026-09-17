"""P1/P2/P3/P6: source geometry and a new clock, without workspace mutation."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from scout_planned_route import compile_planned_route, distance, load_planned_catalog
from scout_planned_route_models import PlannedRouteConflict


def _write(root, ref, payload):
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gpx(parts, labels=None):
    tree = ET.Element('gpx', {'version': '1.1'})
    for label, lat, lon in labels or []:
        p = ET.SubElement(tree, 'wpt', lat=str(lat), lon=str(lon))
        ET.SubElement(p, 'name').text = label
    track = ET.SubElement(tree, 'trk')
    for points in parts:
        segment = ET.SubElement(track, 'trkseg')
        for lat, lon, ele, stamp in points:
            p = ET.SubElement(segment, 'trkpt', lat=str(lat), lon=str(lon))
            ET.SubElement(p, 'ele').text = str(ele)
            if stamp:
                ET.SubElement(p, 'time').text = stamp
    return ET.tostring(tree, encoding='unicode')


def planned_workspace(tmp_path: Path):
    root = tmp_path / 'planned_source_project'
    root.mkdir()
    golden = [(24 + i * .001, 121, 100 + i * 20, f'2020-01-01T06:{i*10:02d}:00+08:00') for i in range(4)]
    branch = [(24.001, 121 + i * .001, 120 + i * 25, f'2021-01-01T07:{i*5:02d}:00+08:00') for i in range(3)]
    sha = _write(root, 'normalized/golden.gpx', _gpx([golden]))
    ref_sha = _write(root, 'normalized/branch.gpx', _gpx([branch], [('山頭 B', 24.001, 121.002)]))
    _write(root, 'outputs/gpx_speed_filter_report.json', {'primary': {'output_path': 'normalized/golden.gpx', 'output_sha256': sha},
                                                      'references': [{'output_path': 'normalized/branch.gpx', 'output_sha256': ref_sha}]})
    _write(root, 'project.json', {'project_id': root.name})
    _write(root, 'candidates/checkpoints.json', [
        {'candidate_id': 'cp.start', 'label': '起點', 'route_point_index': 0},
        {'candidate_id': 'cp.junction', 'label': '營地 A', 'route_point_index': 1},
        {'candidate_id': 'cp.view', 'label': '觀景點 C', 'route_point_index': 2},
        {'candidate_id': 'cp.finish', 'label': '終點', 'route_point_index': 3},
    ])
    return root


def _hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def _request(**changes):
    return {'departure_at': '2026-10-01T06:00:00+08:00', **changes}


def test_p1_fixed_stop_changes_time_not_geometry_and_preview_has_no_writes(tmp_path):
    root = planned_workspace(tmp_path); before = _hashes(root)
    base = compile_planned_route(root, _request())
    changed = compile_planned_route(root, _request(human_text='沿 Golden；在觀景點 C 多停 40 分鐘；7點出發'))
    assert base['status'] == changed['status'] == 'ready'
    assert base['geometry_sha256'] == changed['geometry_sha256']
    assert base['itinerary_sha256'] != changed['itinerary_sha256']
    assert base['itinerary']['days'][0]['arrival_at'] == '2026-10-01T06:30:00+08:00'
    assert changed['itinerary']['days'][0]['arrival_at'] == '2026-10-01T08:10:00+08:00'
    assert changed['itinerary']['days'][0]['fixed_rest_minutes'] == 40
    assert '<time>' not in changed['planned_gpx']
    assert 'role="planned"' in changed['planned_gpx']
    assert _hashes(root) == before


def test_p2_named_branch_round_trip_includes_exact_source_points_and_new_time(tmp_path):
    root = planned_workspace(tmp_path); before = _hashes(root)
    result = compile_planned_route(root, _request(human_text='從營地 A 單攻山頭 B 後回營地 A；在山頭 B 停留 40 分鐘', default_speed_kmh=2))
    assert result['status'] == 'needs_review', result['issues']
    segments = [s for s in result['segments'] if s['source_kind'] == 'reference_gpx']
    assert len(segments) == 2
    assert [s['direction'] for s in segments] == ['forward', 'reverse']
    assert [(s['source_start_index'], s['source_end_index']) for s in segments] == [(0, 2), (2, 0)]
    assert segments[0]['ascent_m'] == segments[1]['descent_m'] == 50
    assert result['comparison']['added_distance_m'] == pytest.approx(2 * segments[0]['length_m'], abs=.002)
    assert result['itinerary']['days'][0]['fixed_rest_minutes'] == 40
    assert result['itinerary']['days'][0]['moving_minutes'] > 40
    assert result['coverage']['status'] == 'coverage_needed'
    assert _hashes(root) == before


def test_p3_preserves_crossing_order_and_reverse_selection(tmp_path):
    root = planned_workspace(tmp_path)
    catalog = load_planned_catalog(root)
    ref = next(s for s in catalog['sources'] if s['kind'] == 'reference_gpx')
    result = compile_planned_route(root, _request(default_speed_kmh=2, route_selections=[
        {'source_id': 'golden', 'start_index': 0, 'end_index': 1},
        {'source_id': ref['source_id'], 'start_index': 0, 'end_index': 2},
        {'source_id': ref['source_id'], 'start_index': 2, 'end_index': 0},
        {'source_id': 'golden', 'start_index': 1, 'end_index': 3},
    ]))
    assert not any(i['severity'] == 'error' for i in result['issues'])
    assert [s['direction'] for s in result['segments']] == ['forward', 'forward', 'reverse', 'forward']
    assert result['route_axis'][-1]['source_point_index'] == 3
    repeated = compile_planned_route(root, _request(default_speed_kmh=2,
        route_selections=result['request']['route_selections'], operations=[{'kind':'stop','at':'營地 A','duration_minutes':10}]))
    assert repeated['status'] == 'blocked'
    assert 'route_visit_ambiguous' in {i['code'] for i in repeated['issues']}
    chosen = compile_planned_route(root, _request(default_speed_kmh=2,
        route_selections=result['request']['route_selections'], operations=[{'kind':'stop','at':'營地 A','visit':2,'duration_minutes':10}]))
    assert chosen['status'] == 'needs_review'


def test_p3_missing_track_segment_does_not_gain_a_straight_connector(tmp_path):
    root = planned_workspace(tmp_path)
    raw = _gpx([[(24,121,100,None),(24.001,121,120,None)], [(24.05,121,150,None),(24.051,121,160,None)]])
    sha = _write(root, 'normalized/golden.gpx', raw)
    report = json.loads((root/'outputs/gpx_speed_filter_report.json').read_text())
    report['primary']['output_sha256'] = sha
    _write(root,'outputs/gpx_speed_filter_report.json', report)
    result = compile_planned_route(root, _request(default_speed_kmh=2))
    assert result['status'] == 'blocked'
    assert len(result['route_geojson']['features']) == 2
    assert result['comparison']['planned_length_m'] < 300
    assert 'disconnected_geometry' in {i['code'] for i in result['issues']}


def test_p3_two_reference_sources_keep_explicit_crossing_and_return_order(tmp_path):
    root = planned_workspace(tmp_path)
    # Stored in the opposite direction: A -> main-line crossing C -> corner -> B.
    raw = _gpx([[(24.001, 121, 120, None), (24.002, 121, 140, None),
                 (24.002, 121.002, 170, None), (24.001, 121.002, 170, None)]])
    sha = _write(root, 'normalized/second.gpx', raw)
    report = json.loads((root/'outputs/gpx_speed_filter_report.json').read_text())
    report['references'].append({'output_path': 'normalized/second.gpx', 'output_sha256': sha})
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    sources = load_planned_catalog(root)['sources']
    first = next(s for s in sources if s.get('ref') == 'normalized/branch.gpx')
    second = next(s for s in sources if s.get('ref') == 'normalized/second.gpx')
    result = compile_planned_route(root, _request(default_speed_kmh=2, route_selections=[
        {'source_id': 'golden', 'start_index': 0, 'end_index': 1},
        {'source_id': first['source_id'], 'start_index': 0, 'end_index': 2},
        {'source_id': second['source_id'], 'start_index': 3, 'end_index': 0},
        {'source_id': 'golden', 'start_index': 1, 'end_index': 3},
    ]))
    assert result['status'] == 'needs_review', result['issues']
    assert [s['source_id'] for s in result['segments']] == [
        'golden', first['source_id'], second['source_id'], 'golden']
    assert [p['source_point_index'] for p in result['route_axis']
            if p['source_id'] == second['source_id']] == [3, 2, 1, 0]
    # Visiting the crossing does not jump directly onto the Golden suffix.
    assert [(p['lat'], p['lon']) for p in result['route_axis'][5:9]] == [
        (24.001, 121.002), (24.002, 121.002), (24.002, 121), (24.001, 121)]
    assert len(result['route_geojson']['features']) == 4


def test_existing_golden_recording_gap_stays_unknown_in_same_geometry_plan(tmp_path):
    root = planned_workspace(tmp_path)
    raw = _gpx([[(24,121,100,'2020-01-01T06:00:00Z'),(24.001,121,120,'2020-01-01T06:10:00Z'),
                 (24.05,121,150,'2020-01-01T06:20:00Z'),(24.051,121,160,'2020-01-01T06:30:00Z')]])
    sha = _write(root, 'normalized/golden.gpx', raw)
    report = json.loads((root/'outputs/gpx_speed_filter_report.json').read_text())
    report['primary']['output_sha256'] = sha
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    result = compile_planned_route(root, _request(default_speed_kmh=2,operations=[{'kind':'stop','at':'終點','duration_minutes':40}]))
    assert result['status'] == 'needs_review'
    assert result['comparison']['geometry_changed'] is False
    assert len(result['golden_geojson']['features']) == len(result['route_geojson']['features']) == 2
    assert result['itinerary']['days'][0]['arrival_at'] is None
    assert result['itinerary']['days'][0]['unknown_count'] == 1
    assert result['itinerary']['days'][0]['fixed_rest_minutes'] == 40


def test_p6_camp_and_midnight_keep_dates_and_unknowns(tmp_path):
    root = planned_workspace(tmp_path)
    result = compile_planned_route(root, _request(departure_at='2026-10-01T23:50:00+08:00', operations=[
        {'kind':'camp','at':'營地 A','departure_at':'2026-10-02T06:00:00+08:00'},
        {'kind':'stop','at':'觀景點 C','duration_minutes':40},
    ]))
    assert result['status'] == 'ready', result['issues']
    assert result['itinerary']['days'][0]['arrival_at'] == '2026-10-02T00:00:00+08:00'
    assert result['itinerary']['days'][1]['arrival_at'] == '2026-10-02T07:00:00+08:00'
    unknown = compile_planned_route(root, _request(route_selections=[{'source_id':'golden','start_index':3,'end_index':0}]))
    assert unknown['itinerary']['days'][0]['arrival_at'] is None
    assert len(unknown['itinerary']['unknowns']) == 3
    assert unknown['itinerary']['days'][0]['moving_minutes'] == 0


def test_p6_conflicting_camp_or_arrival_constraint_is_not_silently_repaired(tmp_path):
    root = planned_workspace(tmp_path)
    result = compile_planned_route(root, _request(operations=[
        {'kind':'deadline','at':'終點','latest_arrival_at':'2026-10-01T06:20:00+08:00'}]))
    assert result['status'] == 'blocked'
    assert result['itinerary']['days'][0]['arrival_at'] == '2026-10-01T06:30:00+08:00'
    assert result['itinerary']['conflicts'][0]['code'] == 'arrival_constraint_unsatisfied'


def test_p6_source_stationary_time_is_counted_once_before_additional_stop(tmp_path):
    root = planned_workspace(tmp_path)
    raw = _gpx([[(24,121,100,'2020-01-01T06:00:00Z'),(24.001,121,120,'2020-01-01T06:10:00Z'),
                 (24.001,121,120,'2020-01-01T06:35:00Z'),(24.002,121,140,'2020-01-01T06:45:00Z')]])
    sha = _write(root,'normalized/golden.gpx',raw)
    report=json.loads((root/'outputs/gpx_speed_filter_report.json').read_text())
    report['primary']['output_sha256']=sha
    _write(root,'outputs/gpx_speed_filter_report.json',report)
    result=compile_planned_route(root,_request(operations=[{'kind':'stop','at':'營地 A','duration_minutes':40}]))
    day=result['itinerary']['days'][0]
    assert day['moving_minutes']==20
    assert day['source_rest_minutes']==25
    assert day['fixed_rest_minutes']==40
    assert day['rest_minutes']==65
    assert day['arrival_at']=='2026-10-01T07:25:00+08:00'


def test_named_branch_target_must_match_the_selected_geometry(tmp_path):
    root = planned_workspace(tmp_path)
    result = compile_planned_route(root, _request(default_speed_kmh=2, operations=[{
        'kind':'branch','at':'營地 A','to':'山頭 B',
        'selection':{'source_id':'golden','start_index':1,'end_index':2}}]))
    assert result['status']=='blocked'
    assert 'branch_target_mismatch' in {i['code'] for i in result['issues']}


def test_arrival_deadline_precedes_rest_independent_of_form_order(tmp_path):
    root = planned_workspace(tmp_path)
    ops=[{'kind':'stop','at':'終點','duration_minutes':40},
         {'kind':'deadline','at':'終點','latest_arrival_at':'2026-10-01T06:35:00+08:00'}]
    first=compile_planned_route(root,_request(operations=ops))
    second=compile_planned_route(root,_request(operations=list(reversed(ops))))
    assert first['status']==second['status']=='ready'
    assert first['itinerary']==second['itinerary']


def test_explicit_camp_departure_replaces_original_overnight_stay(tmp_path):
    root=planned_workspace(tmp_path)
    sha=_write(root,'normalized/golden.gpx',_gpx([[
        (24,121,100,'2020-01-01T06:00:00Z'),(24.001,121,120,'2020-01-01T06:10:00Z'),
        (24.001,121,120,'2020-01-02T06:10:00Z'),(24.002,121,140,'2020-01-02T06:20:00Z')]]))
    report=json.loads((root/'outputs/gpx_speed_filter_report.json').read_text())
    report['primary']['output_sha256']=sha
    _write(root,'outputs/gpx_speed_filter_report.json',report)
    result=compile_planned_route(root,_request(operations=[
        {'kind':'camp','at':'營地 A','departure_at':'2026-10-02T06:00:00+08:00'}]))
    assert result['itinerary']['days'][1]['arrival_at']=='2026-10-02T06:10:00+08:00'
    assert result['itinerary']['days'][1]['source_rest_minutes']==0
    assert 'source_stay_replaced_by_explicit_departure' in {r.get('method') for r in result['itinerary']['timeline']}


def test_unparsed_text_never_silently_becomes_a_complete_plan(tmp_path):
    root = planned_workspace(tmp_path)
    result = compile_planned_route(root, _request(human_text='從營地A直接飛到不存在的山頭'))
    assert result['status'] == 'blocked'
    assert result['issues'][0]['code'] == 'unresolved_itinerary_clause'


def test_source_snapshot_is_checked_and_untrusted_path_cannot_escape_project(tmp_path):
    root = planned_workspace(tmp_path)
    with pytest.raises(PlannedRouteConflict, match='Sources changed'):
        compile_planned_route(root, _request(source_snapshot_sha256='0'*64))
    report = json.loads((root/'outputs/gpx_speed_filter_report.json').read_text())
    report['references'][0]['output_path'] = '../outside.gpx'
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    with pytest.raises(PlannedRouteConflict, match='Unavailable project source'):
        compile_planned_route(root, _request())


def _filtered_workspace(tmp_path):
    root = planned_workspace(tmp_path)
    report = json.loads((root / 'outputs/gpx_speed_filter_report.json').read_text())
    for record in [report['primary'], *report['references']]:
        original = root / record['output_path']
        record['output_path'] = f'normalized/routes/filtered/{original.name}'
        assert _write(root, record['output_path'], original.read_text()) == record['output_sha256']
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    return root, report


def test_filtered_catalog_relocates_hash_bound_golden_and_references_without_writes(tmp_path):
    root, report = _filtered_workspace(tmp_path)
    original_catalog = load_planned_catalog(root)
    request = _request(human_text='從營地 A 單攻山頭 B 後回營地 A', default_speed_kmh=2)
    original_preview = compile_planned_route(root, request)
    for record in [report['primary'], *report['references']]:
        old_path = tmp_path / 'old-mac' / root.name / record['output_path']
        _write(tmp_path, old_path.relative_to(tmp_path), 'not GPX: this external file must never be read')
        record['output_path'] = str(old_path)
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    before = _hashes(tmp_path)

    relocated = load_planned_catalog(root)
    preview = compile_planned_route(root, request)

    assert relocated['sources'] == original_catalog['sources']
    assert relocated['anchors'] == original_catalog['anchors']
    assert {s['ref'] for s in relocated['sources']} == {
        'normalized/routes/filtered/golden.gpx', 'normalized/routes/filtered/branch.gpx'}
    assert preview['geometry_sha256'] == original_preview['geometry_sha256']
    assert preview['itinerary_sha256'] == original_preview['itinerary_sha256']
    assert preview['status'] == original_preview['status'] == 'needs_review'
    assert _hashes(tmp_path) == before


@pytest.mark.parametrize(('path_template', 'sha_override', 'error_code'), [
    ('/old/other_project/normalized/routes/filtered/branch.gpx', 'keep', 'source_missing_or_outside_project'),
    ('/old/{project_id}/unrelated/branch.gpx', 'keep', 'source_missing_or_outside_project'),
    ('/old/{project_id}/normalized/routes/raw/branch.gpx', 'keep', 'source_missing_or_outside_project'),
    ('/old/{project_id}/normalized/routes/filtered/nested/branch.gpx', 'keep', 'source_missing_or_outside_project'),
    ('/old/../{project_id}/normalized/routes/filtered/branch.gpx', 'keep', 'source_missing_or_outside_project'),
    ('/old/{project_id}/normalized/routes/filtered/branch.gpx', None, 'source_missing_or_outside_project'),
    ('/old/{project_id}/normalized/routes/filtered/branch.gpx', '', 'source_missing_or_outside_project'),
    ('/old/{project_id}/normalized/routes/filtered/branch.gpx', 'not-a-sha256', 'source_missing_or_outside_project'),
    ('/old/{project_id}/normalized/routes/filtered/branch.gpx', 'a' * 63, 'source_missing_or_outside_project'),
    ('/old/{project_id}/normalized/routes/filtered/branch.gpx', '0' * 64, 'source_hash_changed'),
    ('/old/{project_id}/normalized/routes/filtered/missing.gpx', 'keep', 'source_missing_or_outside_project'),
])
def test_filtered_catalog_portability_rejects_unbound_or_mismatched_sources(tmp_path, path_template, sha_override, error_code):
    root, report = _filtered_workspace(tmp_path)
    record = report['references'][0]
    record['output_path'] = path_template.format(project_id=root.name)
    if sha_override is None:
        record.pop('output_sha256')
    elif sha_override != 'keep':
        record['output_sha256'] = sha_override
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    before = _hashes(root)
    with pytest.raises(PlannedRouteConflict) as exc:
        load_planned_catalog(root)
    assert exc.value.code == error_code
    assert _hashes(root) == before


def test_filtered_catalog_portability_uses_project_identity_not_directory_name(tmp_path):
    root, report = _filtered_workspace(tmp_path)
    _write(root, 'project.json', {'project_id': 'actual_project_identity'})
    record = report['primary']
    record['output_path'] = '/old/actual_project_identity/normalized/routes/filtered/golden.gpx'
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    assert load_planned_catalog(root)['project_id'] == 'actual_project_identity'
    record['output_path'] = f'/old/{root.name}/normalized/routes/filtered/golden.gpx'
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    with pytest.raises(PlannedRouteConflict) as exc:
        load_planned_catalog(root)
    assert exc.value.code == 'source_missing_or_outside_project'


def test_filtered_catalog_portability_cannot_follow_external_symlink(tmp_path):
    root, report = _filtered_workspace(tmp_path)
    external = tmp_path / 'outside.gpx'
    external.write_bytes((root / report['primary']['output_path']).read_bytes())
    (root / 'normalized/routes/filtered/linked.gpx').symlink_to(external)
    report['primary']['output_path'] = f'/old/{root.name}/normalized/routes/filtered/linked.gpx'
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    before = _hashes(tmp_path)
    with pytest.raises(PlannedRouteConflict) as exc:
        load_planned_catalog(root)
    assert exc.value.code == 'source_missing_or_outside_project'
    assert _hashes(tmp_path) == before


def test_filtered_catalog_preserves_local_absolute_path_without_sha(tmp_path):
    root = planned_workspace(tmp_path)
    report = json.loads((root / 'outputs/gpx_speed_filter_report.json').read_text())
    report['primary']['output_path'] = str(root / 'normalized/golden.gpx')
    report['primary'].pop('output_sha256')
    _write(root, 'outputs/gpx_speed_filter_report.json', report)
    assert load_planned_catalog(root)['sources'][0]['ref'] == 'normalized/golden.gpx'


def test_p7_export_reimport_keeps_planning_role_and_rejects_recorded_stage(tmp_path):
    from pretrip_import import PretripImportRequest, _golden_route_role, _stage_source_inbox, _validate_request
    root = planned_workspace(tmp_path)
    result = compile_planned_route(root, _request())
    exported = tmp_path / 'planned.gpx'
    exported.write_text(result['planned_gpx'])
    request = PretripImportRequest(project_id='reimport_plan', primary_gpx=exported, workspace_root=tmp_path/'reimport')
    _validate_request(request)
    assert _golden_route_role(request) == 'planned_gpx_reference'
    manifest = _stage_source_inbox(project_root=tmp_path/'staged', project_id='reimport_plan', primary_gpx=exported, reference_paths=[])
    assert manifest['sources'][0]['role'] == 'planned_gpx_reference'
    assert manifest['sources'][0]['gpx_provenance_role'] == 'planned'
    request = replace(request, import_stage='post_analysis')
    with pytest.raises(ValueError, match='planned_gpx_is_not_recorded'):
        _validate_request(request)
