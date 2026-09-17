"""Execute all existing assessors on Recorded inputs, without assessor mocks."""
from __future__ import annotations

import hashlib
import json

import pytest

from scout_planned_analysis_producers import run_planned_analyses
from scout_recorded_analysis import save_recorded_version
from scout_recorded_jobs import recorded_binding
from test_scout_recorded_analysis import recorded, _files


@pytest.mark.parametrize("evidence_role,excluded,matched", [
    ("forecast",1,False),
    ("historical_weather_observation",0,True),
])
def test_real_six_assessors_use_recorded_clock_and_historical_weather_only(recorded,tmp_path,evidence_role,excluded,matched):
    root,request=recorded
    # This is a faithful synthetic fixture with explicit fixture time/source
    # roles. It is never a claim that the real user completed the activity.
    request={**request,"recordings":[{**r,"observation_kind":"fixture_replay"} for r in request["recordings"]]}
    bundle=save_recorded_version(root,request)
    weather=root/"normalized/weather/forecast_snapshots.json"
    weather.parent.mkdir(parents=True,exist_ok=True)
    weather.write_text(json.dumps([{
        "lat":24.001,"lon":121,"valid_from":"2026-09-30T00:00:00Z","valid_to":"2026-10-03T00:00:00Z",
        "issued_at":"2026-09-29T00:00:00Z","evidence_role":evidence_role,"temperature_c":16,"wind_speed_mps":2,
        "precipitation_probability":0,"source_id":"explicit-weather-fixture",
    }]))
    owner_before=_files(root)
    run=tmp_path/"six-real-assessors"
    result=run_planned_analyses(root,bundle,run,{
        "status":"completed_with_gaps","subject_binding":recorded_binding(bundle),
        "terrain_parts":[],"map_sources":{},"coverage":{"terrain_point_coverage":"unverified"},
        "candidate_only":True,"runtime_safety_truth":False,"recorded_track":True,
    })
    assert result["pretrip_report"] is None
    assert _files(root)==owner_before
    assert set(result["projections"])=={"permission","pace_fit","architecture","navigation","weather","route_context"}
    assert not result["runtime_safety_truth"] and result["recorded_track"]
    for role,projection in result["projections"].items():
        assert projection["status"]=="partial",projection
        raw=(run/projection["artifact_ref"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==projection["artifact_sha256"]
        artifact=json.loads(raw)
        assert artifact["artifact_kind"]=="recorded_analysis_projection"
        assert artifact["analysis_subject_kind"]=="recorded_gpx"
        assert artifact["candidate_only"] and not artifact["runtime_safety_truth"] and artifact["recorded_track"]
        assert artifact["input_binding"]["manifest_sha256"]==bundle["manifest"]["manifest_sha256"]
        assert artifact["input_binding"]["source_times_role"]=="fixture_replay_time"
        assert artifact["result"]["source_times_role"]=="fixture_replay_time"
        assert artifact["result"]["planned_timetable_role"]=="recorded_observation_alias"
        assert set(artifact["result"]["comparison"])=={"golden","planned"}
        assert not any(m["code"]=="producer_failed" for m in artifact["missing_inputs"])
        if role=="weather":
            assert artifact["result"]["current_forecasts_excluded"]==excluded
            assert bool(artifact["result"]["segment_matches"]) is matched
            assert artifact["result"]["historical_weather_status"]==("observations_matched" if matched else "unknown")
