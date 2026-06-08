import json
import subprocess
import sys
from pathlib import Path

from mission_graph import load_mission_graph
from offline_map import load_offline_map_context
from route_matching import load_gpx_route
from tools.ins_dr_field_completion_gate import run_field_completion_gate
from tools.pi_wheel_odometry_delta_smoke import build_wheel_odometry_delta_payloads
from tools.pi_gnss_nmea_smoke import parse_raw_nmea


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_SCRIPT = ROOT / "tools" / "ins_dr_diagnostic_route_scaffold.py"


def test_diagnostic_route_scaffold_creates_mission_route_and_corridor(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCAFFOLD_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--mission-id",
            "ins_dr_test",
            "--lat",
            "25.06370833",
            "--lon",
            "121.654085",
            "--heading-deg",
            "87.5",
            "--distance-m",
            "3.0",
            "--point-count",
            "4",
            "--corridor-half-width-m",
            "6.0",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    route = load_gpx_route(report["route_gpx"])
    mission = load_mission_graph(report["mission_graph_json"])
    map_context = load_offline_map_context(report["map_context_geojson"])
    assert report["hardware_control_scope"] == "diagnostic_route_scaffold_only"
    assert report["primary_truth_allowed"] is False
    assert mission.route_source == "../routes/ins_dr_test_route.gpx"
    assert len(route.points) == 4
    assert route.points[-1].progress_m >= 2.9
    assert map_context.corridors[0].corridor_half_width_m == 6.0


def test_diagnostic_route_scaffold_output_can_drive_serial_capture_completion_gate(tmp_path: Path) -> None:
    scaffold = subprocess.run(
        [
            sys.executable,
            str(SCAFFOLD_SCRIPT),
            "--output-dir",
            str(tmp_path / "scaffold"),
            "--mission-id",
            "ins_dr_field_ready",
            "--lat",
            "25.06370833",
            "--lon",
            "121.654085",
            "--heading-deg",
            "87.5",
            "--distance-m",
            "3.0",
            "--corridor-half-width-m",
            "6.0",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert scaffold.returncode == 0, scaffold.stderr
    scaffold_report = json.loads(scaffold.stdout)

    anchor_payloads = parse_raw_nmea(
        _gga_sentence(
            lat=scaffold_report["start"]["lat"],
            lon=scaffold_report["start"]["lon"],
            time_value="000010.000",
        ),
        device_port="/dev/ttyUSB0",
        baud=9600,
        capture_mode="serial_device",
    )
    reanchor_payloads = parse_raw_nmea(
        _gga_sentence(
            lat=scaffold_report["finish"]["lat"],
            lon=scaffold_report["finish"]["lon"],
            time_value="000012.000",
        ),
        device_port="/dev/ttyUSB0",
        baud=9600,
        capture_mode="serial_device",
    )
    dr_payload = build_wheel_odometry_delta_payloads(
        [
            {
                "timestamp_s": 10.5,
                "raw_evidence_ref": "wheel.jsonl:1",
                "odometry": {"cumulative_distance_m": 20.0, "heading_deg": 87.5},
            },
            {
                "timestamp_s": 11.0,
                "raw_evidence_ref": "wheel.jsonl:2",
                "odometry": {"cumulative_distance_m": 23.0, "heading_deg": 87.5},
            },
        ],
        provider="scout_wheel_encoder",
    )[0]
    output_dir = tmp_path / "field-run"
    anchor_jsonl = output_dir / "anchor.jsonl"
    dr_jsonl = output_dir / "dr.jsonl"
    reanchor_jsonl = output_dir / "reanchor.jsonl"
    _write_jsonl(anchor_payloads, anchor_jsonl)
    _write_jsonl([dr_payload], dr_jsonl)
    _write_jsonl(reanchor_payloads, reanchor_jsonl)
    report = run_field_completion_gate(
        mission_graph_path=Path(scaffold_report["mission_graph_json"]),
        payloads=anchor_payloads + [dr_payload] + reanchor_payloads,
        input_jsonl_paths=[anchor_jsonl, dr_jsonl, reanchor_jsonl],
        raw_nmea=None,
        runtime_updates_path=output_dir / "runtime-updates.jsonl",
        field_report_path=output_dir / "field-report.json",
        proof_manifest_path=output_dir / "proof-manifest.json",
        verification_report_path=output_dir / "verification-report.json",
        require_reanchor=True,
    )

    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["completion_ready"] is True
    field_report = json.loads(Path(report["field_report_json"]).read_text(encoding="utf-8"))
    assert field_report["route_corridor_failure_count"] == 0
    assert field_report["dr_distance_source_failure_count"] == 0


def test_diagnostic_route_scaffold_can_use_first_valid_gnss_jsonl_position(tmp_path: Path) -> None:
    anchor_jsonl = tmp_path / "anchor.jsonl"
    anchor_jsonl.write_text(
        json.dumps(
            {
                "source": "pi_gnss_nmea_smoke",
                "position": {"lat": 25.06370833, "lon": 121.654085},
                "fix_quality": {"valid": True, "quality": 1, "satellites": 9, "hdop": 0.8},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCAFFOLD_SCRIPT),
            "--output-dir",
            str(tmp_path / "scaffold"),
            "--mission-id",
            "ins_dr_from_anchor_jsonl",
            "--anchor-jsonl",
            str(anchor_jsonl),
            "--heading-deg",
            "90.0",
            "--distance-m",
            "4.0",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["start"] == {"lat": 25.06370833, "lon": 121.654085}
    assert Path(report["mission_graph_json"]).exists()


def _gga_sentence(*, lat: float, lon: float, time_value: str) -> str:
    lat_value, lat_hemi = _nmea_lat(lat)
    lon_value, lon_hemi = _nmea_lon(lon)
    body = f"GPGGA,{time_value},{lat_value},{lat_hemi},{lon_value},{lon_hemi},1,09,0.8,80.0,M,20.1,M,,"
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


def _write_jsonl(payloads: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(payload) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _nmea_lat(value: float) -> tuple[str, str]:
    hemi = "N" if value >= 0 else "S"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:02d}{minutes:07.4f}", hemi


def _nmea_lon(value: float) -> tuple[str, str]:
    hemi = "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:03d}{minutes:07.4f}", hemi
