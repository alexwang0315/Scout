import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg, route_point_at_progress
from route_matching import load_gpx_route
from tools.ins_dr_field_completion_gate import run_field_completion_gate
from tools.pi_gnss_nmea_smoke import parse_raw_nmea
from tools.pi_wheel_odometry_delta_smoke import (
    build_template_records,
    build_wheel_odometry_delta_payloads,
    render_template_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wheel_odometry_delta_smoke.py"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_build_wheel_odometry_delta_payloads_preserves_provider_provenance() -> None:
    payloads = build_wheel_odometry_delta_payloads(
        [
            {
                "timestamp_s": 10.0,
                "dry_run": False,
                "raw_evidence_ref": "wheel.jsonl:1",
                "odometry": {"cumulative_distance_m": 120.0, "heading_deg": 87.5},
            },
            {
                "timestamp_s": 11.0,
                "dry_run": False,
                "raw_evidence_ref": "wheel.jsonl:2",
                "odometry": {"cumulative_distance_m": 123.0, "heading_deg": 88.0},
            },
        ],
        provider="scout_wheel_encoder",
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["source"] == "wheel_odometry"
    assert payload["provider"] == "scout_wheel_encoder"
    assert payload["hardware_kind"] == "dead_reckoning_delta_evidence"
    assert payload["distance_delta_m"] == 3.0
    assert payload["heading_deg"] == 88.0
    assert payload["odometry_delta_method"] == "cumulative_distance_m"
    assert payload["previous_raw_evidence_ref"] == "wheel.jsonl:1"
    assert payload["current_raw_evidence_ref"] == "wheel.jsonl:2"
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["primary_truth_allowed"] is False
    assert payload["dry_run"] is False
    assert payload["previous_dry_run"] is False
    assert payload["current_dry_run"] is False
    assert payload["hardware_control_scope"] == "diagnostic_wheel_odometry_delta_only"


def test_wheel_odometry_template_records_are_actionable() -> None:
    records = build_template_records()
    markdown = render_template_markdown(records)

    assert len(records) == 2
    assert records[0]["odometry"]["cumulative_distance_m"] is None
    assert "Scout Wheel Odometry JSONL Worksheet" in markdown
    assert "pi_wheel_odometry_delta_smoke.py" in markdown


def test_wheel_odometry_delta_cli_writes_template_files(tmp_path: Path) -> None:
    template_jsonl = tmp_path / "wheel-template.jsonl"
    template_md = tmp_path / "wheel-template.md"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--write-template-jsonl",
            str(template_jsonl),
            "--write-template-md",
            str(template_md),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["hardware_control_scope"] == "diagnostic_wheel_odometry_template_only"
    assert len(template_jsonl.read_text(encoding="utf-8").splitlines()) == 2
    assert "cumulative_distance_m" in template_md.read_text(encoding="utf-8")


def test_wheel_odometry_delta_cli_converts_ticks_to_dr_jsonl(tmp_path: Path) -> None:
    wheel_jsonl = tmp_path / "wheel.jsonl"
    output_jsonl = tmp_path / "dr.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {"timestamp_s": 10.0, "wheel": {"left_ticks": 100, "right_ticks": 100, "heading_deg": 90.0}},
                {"timestamp_s": 11.0, "wheel": {"left_ticks": 130, "right_ticks": 120, "heading_deg": 91.0}},
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input-jsonl",
            str(wheel_jsonl),
            "--meters-per-tick",
            "0.04",
            "--output-jsonl",
            str(output_jsonl),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    payloads = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    assert report["source"] == "pi_wheel_odometry_delta_smoke"
    assert report["hardware_control_scope"] == "diagnostic_wheel_odometry_delta_only"
    assert report["payload_count"] == 1
    assert payloads[0]["distance_delta_m"] == 1.0
    assert payloads[0]["wheel_ticks"] == {"left": 130, "right": 120, "meters_per_tick": 0.04}
    assert payloads[0]["dry_run"] is False


def test_wheel_odometry_delta_cli_rejects_dry_run_records(tmp_path: Path) -> None:
    wheel_jsonl = tmp_path / "wheel.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {"timestamp_s": 10.0, "dry_run": True, "odometry": {"cumulative_distance_m": 20.0}},
                {"timestamp_s": 11.0, "dry_run": True, "odometry": {"cumulative_distance_m": 23.0}},
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input-jsonl",
            str(wheel_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "dry-run wheel odometry cannot be converted" in result.stderr


def test_wheel_odometry_delta_requires_meters_per_tick_for_tick_only_records(tmp_path: Path) -> None:
    wheel_jsonl = tmp_path / "wheel.jsonl"
    wheel_jsonl.write_text(
        json.dumps({"timestamp_s": 10.0, "wheel": {"left_ticks": 100, "right_ticks": 100}}) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input-jsonl",
            str(wheel_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "meters_per_tick is required" in result.stderr


def test_wheel_odometry_delta_output_can_drive_completion_gate(tmp_path: Path) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    reanchor = route_point_at_progress(route, anchor.progress_m + 3.0)
    heading = route_heading_deg(route, anchor.progress_m)
    anchor_payloads = parse_raw_nmea(
        _gga_sentence(lat=anchor.lat, lon=anchor.lon, time_value="000010.000"),
        device_port="/dev/ttyUSB0",
        baud=9600,
        capture_mode="serial_device",
    )
    reanchor_payloads = parse_raw_nmea(
        _gga_sentence(lat=reanchor.lat, lon=reanchor.lon, time_value="000012.000"),
        device_port="/dev/ttyUSB0",
        baud=9600,
        capture_mode="serial_device",
    )
    wheel_jsonl = tmp_path / "wheel.jsonl"
    dr_jsonl = tmp_path / "dr.jsonl"
    anchor_jsonl = tmp_path / "anchor.jsonl"
    reanchor_jsonl = tmp_path / "reanchor.jsonl"
    wheel_jsonl.write_text(
        "\n".join(
            json.dumps(payload)
            for payload in (
                {"timestamp_s": 10.5, "odometry": {"cumulative_distance_m": 20.0, "heading_deg": heading}},
                {"timestamp_s": 11.0, "odometry": {"cumulative_distance_m": 23.0, "heading_deg": heading}},
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input-jsonl",
            str(wheel_jsonl),
            "--output-jsonl",
            str(dr_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    dr_payloads = [json.loads(line) for line in dr_jsonl.read_text(encoding="utf-8").splitlines()]
    _write_jsonl(anchor_payloads, anchor_jsonl)
    _write_jsonl(reanchor_payloads, reanchor_jsonl)
    report = run_field_completion_gate(
        mission_graph_path=MISSION_PATH,
        payloads=anchor_payloads + dr_payloads + reanchor_payloads,
        input_jsonl_paths=[anchor_jsonl, dr_jsonl, reanchor_jsonl],
        raw_nmea=None,
        runtime_updates_path=tmp_path / "runtime-updates.jsonl",
        field_report_path=tmp_path / "field-report.json",
        proof_manifest_path=tmp_path / "proof-manifest.json",
        verification_report_path=tmp_path / "verification-report.json",
        require_reanchor=True,
    )

    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["completion_ready"] is True
    field_report = json.loads(Path(report["field_report_json"]).read_text(encoding="utf-8"))
    assert field_report["dr_distance_source_failure_count"] == 0
    assert field_report["dr_distance_source_summary"]["kind_counts"] == {"wheel_or_encoder_odometry": 1}


def _write_jsonl(payloads: list[dict], path: Path) -> None:
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _gga_sentence(*, lat: float, lon: float, time_value: str) -> str:
    lat_value, lat_hemi = _nmea_lat(lat)
    lon_value, lon_hemi = _nmea_lon(lon)
    body = f"GPGGA,{time_value},{lat_value},{lat_hemi},{lon_value},{lon_hemi},1,09,0.8,80.0,M,20.1,M,,"
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


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
