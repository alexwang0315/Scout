from pathlib import Path

from ins_dr_navigation import route_heading_deg
from route_matching import load_gpx_route
from safety_api import ingest_safety_observation_body
from safety_runtime_session import SafetyRuntimeSession


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_safety_observation_ingest_accepts_gnss_and_dr_provider_payloads() -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    session = SafetyRuntimeSession(MISSION_PATH)

    response = ingest_safety_observation_body(
        {
            "payload": {
                "payloads": [
                    {
                        "source": "pi_gnss_nmea_smoke",
                        "timestamp_s": 10.0,
                        "sentence_type": "GPGGA",
                        "position": {"lat": anchor.lat, "lon": anchor.lon},
                        "fix_quality": {"quality": 1, "valid": True, "satellites": 9, "hdop": 0.8},
                    },
                    {
                        "source": "wheel_odometry",
                        "timestamp_s": 11.0,
                        "odometry": {
                            "distance_delta_m": 3.0,
                            "heading_deg": heading,
                        },
                    },
                ]
            },
            "device": "scout_pi",
        },
        runtime_session=session,
    )

    assert response["status"] == "accepted"
    assert response["observations_accepted"] == 2
    assert response["snapshot"]["observations_processed"] == 2
    assert response["latest_capabilities"]["dead_reckoning_delta"]["status"] == "available"
    assert response["latest_position_estimate"]["source"] == "dead_reckoning"
    assert response["latest_position_estimate"]["primary_truth_source"] == "raw_gnss+dead_reckoning"
    assert response["latest_position_estimate"]["pdr_delta_m"] == 3.0
