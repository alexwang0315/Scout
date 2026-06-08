from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from assistant_api import create_assistant_app
from assistant_models import AssistantSourceRef, ScoutAssistantQuery
from geo_utils import haversine_m
from tools.pi_gnss_nmea_smoke import parse_raw_nmea


DEFAULT_PROJECT_ROOT = Path("tests/fixtures/pretrip/projects/chilai_nanhua_day1")
DEFAULT_QUESTION = "我現在是不是離主路太近但站在危險邊緣？"
DEFAULT_ALLOWED_CORRIDOR_M = 30.0
DEFAULT_HAZARD_OFFSET_M = 45.0
HIGH_RISK_SCORE_THRESHOLD = 70.0


@dataclass(frozen=True)
class RouteRiskSample:
    sample_id: str
    segment_id: str
    lat: float
    lon: float
    distance_m: float | None
    score: float
    risk_bucket: str | None
    risk_level: int | None


def build_probe_report(
    *,
    project_root: Path = DEFAULT_PROJECT_ROOT,
    question: str = DEFAULT_QUESTION,
    allowed_corridor_m: float = DEFAULT_ALLOWED_CORRIDOR_M,
    hazard_offset_m: float = DEFAULT_HAZARD_OFFSET_M,
) -> dict[str, Any]:
    samples = _load_route_risk_samples(project_root)
    if not samples:
        raise ValueError(f"no route/risk samples found under {project_root}")
    normal_sample = min(samples, key=lambda item: item.score)
    hazard_sample = max(samples, key=lambda item: item.score)
    scenarios = [
        _build_scenario(
            "normal_inside_corridor_low_risk",
            sample=normal_sample,
            samples=samples,
            allowed_corridor_m=allowed_corridor_m,
            offset_east_m=0.0,
        ),
        _build_scenario(
            "off_route_high_risk_candidate",
            sample=hazard_sample,
            samples=samples,
            allowed_corridor_m=allowed_corridor_m,
            offset_east_m=hazard_offset_m,
        ),
    ]
    assistant_results = [
        _ask_assistant(question=question, scenario=scenario) for scenario in scenarios
    ]
    return {
        "artifact_kind": "scout_ai_nmea_live_navigation_probe",
        "artifact_version": "scout_ai_nmea_live_navigation_probe.v0",
        "question": question,
        "project_root": str(project_root),
        "allowed_corridor_m": allowed_corridor_m,
        "hazard_offset_m": hazard_offset_m,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "assistant_results": assistant_results,
        "boundary": {
            "read_only": True,
            "runtime_safety_truth": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "outbound_send_performed": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Scout AI NMEA Live Navigation Probe",
        "",
        f"- artifact_kind: `{report['artifact_kind']}`",
        f"- artifact_version: `{report['artifact_version']}`",
        f"- question: {report['question']}",
        f"- project_root: `{report['project_root']}`",
        f"- allowed_corridor_m: `{report['allowed_corridor_m']}`",
        "- boundary: read-only; no `/safety/*`; no Phase 1 L0-L4 mutation; no outbound send",
        "",
        "## Summary",
        "",
        "| Scenario | Expected Classification | Route Distance | Risk | Assistant Verdict |",
        "| --- | --- | ---: | --- | --- |",
    ]
    results_by_id = {
        item["scenario_id"]: item for item in report.get("assistant_results", [])
    }
    for scenario in report.get("scenarios", []):
        result = results_by_id.get(scenario["scenario_id"], {})
        route = scenario["route_match"]
        risk = scenario["risk_context"]
        answer = str(result.get("answer") or "").replace("|", "\\|")
        lines.append(
            "| {scenario_id} | `{classification}` | {distance_m:.2f} m | {score} / {bucket} | {answer} |".format(
                scenario_id=scenario["scenario_id"],
                classification=scenario["evaluation"]["classification"],
                distance_m=float(route["distance_m"]),
                score=risk.get("score"),
                bucket=risk.get("risk_bucket"),
                answer=answer,
            )
        )
    lines.extend(["", "## NMEA Packets", ""])
    for scenario in report.get("scenarios", []):
        lines.append(f"### {scenario['scenario_id']}")
        lines.append("")
        lines.append("```text")
        lines.extend(scenario["nmea_sentences"])
        lines.append("```")
        lines.append("")
        lines.append("Parsed GNSS fix:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(scenario["gnss_fix"], ensure_ascii=False, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def write_probe_outputs(
    report: dict[str, Any],
    *,
    output_json: Path | None = None,
    output_markdown: Path | None = None,
) -> None:
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if output_markdown is not None:
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(render_markdown(report), encoding="utf-8")


def _build_scenario(
    scenario_id: str,
    *,
    sample: RouteRiskSample,
    samples: list[RouteRiskSample],
    allowed_corridor_m: float,
    offset_east_m: float,
) -> dict[str, Any]:
    lat, lon = _offset_lat_lon(sample.lat, sample.lon, east_m=offset_east_m, north_m=0.0)
    nmea_sentences = _build_nmea_packet(
        lat=lat,
        lon=lon,
        altitude_m=1280.5,
        time_utc="010203.00",
        date_ddmmyy="070626",
        speed_knots=1.2,
        course_deg=45.0,
        satellites=4,
        hdop=0.8,
    )
    parsed_payloads = parse_raw_nmea(
        "\n".join(nmea_sentences),
        device_port="fixture://nmea-live-navigation-probe",
        baud=115200,
        capture_mode="fixture_nmea_scenario",
    )
    gnss_fix = _merged_gnss_fix(parsed_payloads)
    route_match = _nearest_route_match(samples, lat, lon, allowed_corridor_m=allowed_corridor_m)
    risk_context = _nearest_highest_risk(samples, lat, lon, radius_m=160.0)
    evaluation = _classify(route_match=route_match, risk_context=risk_context)
    return {
        "scenario_id": scenario_id,
        "source_sample": {
            "sample_id": sample.sample_id,
            "segment_id": sample.segment_id,
            "lat": round(sample.lat, 8),
            "lon": round(sample.lon, 8),
            "score": sample.score,
            "risk_bucket": sample.risk_bucket,
        },
        "offset_east_m": offset_east_m,
        "nmea_sentences": nmea_sentences,
        "parsed_payload_count": len(parsed_payloads),
        "checksum_valid_count": sum(1 for payload in parsed_payloads if payload.get("checksum_valid") is True),
        "gnss_fix": gnss_fix,
        "route_match": route_match,
        "risk_context": risk_context,
        "evaluation": evaluation,
        "read_only": True,
        "runtime_safety_truth": False,
    }


def _ask_assistant(*, question: str, scenario: dict[str, Any]) -> dict[str, Any]:
    source = AssistantSourceRef(
        source_id="assistant_context.live_navigation_nmea_scenario",
        source_path="tools/scout_ai_nmea_live_navigation_probe.py",
        evidence_type="live_navigation_nmea_scenario",
        selected=True,
        context_summary=scenario,
    )

    def resolver(query: ScoutAssistantQuery) -> list[AssistantSourceRef]:
        return [source]

    client = TestClient(create_assistant_app(context_resolver=resolver))
    response = client.post(
        "/assistant/query",
        json={
            "surface": "debug",
            "question": question,
            "context_ref": scenario["scenario_id"],
        },
    )
    payload = response.json()
    return {
        "scenario_id": scenario["scenario_id"],
        "http_status": response.status_code,
        "answer": payload.get("answer"),
        "limitations": payload.get("limitations", []),
        "boundary": payload.get("boundary"),
        "sources": payload.get("sources", []),
    }


def _load_route_risk_samples(project_root: Path) -> list[RouteRiskSample]:
    path = project_root / "outputs" / "risk_ribbon.geojson"
    payload = json.loads(path.read_text(encoding="utf-8"))
    samples: list[RouteRiskSample] = []
    for index, feature in enumerate(payload.get("features", [])):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        lat_lon = _representative_lat_lon(geometry)
        score = _float_or_none(properties.get("pretrip_risk") or properties.get("rs"))
        if lat_lon is None or score is None:
            continue
        lat, lon = lat_lon
        samples.append(
            RouteRiskSample(
                sample_id=str(
                    properties.get("sample_id")
                    or properties.get("from_sample_id")
                    or f"risk_sample.{index:04d}"
                ),
                segment_id=str(properties.get("segment_id") or f"risk_segment.{index:04d}"),
                lat=lat,
                lon=lon,
                distance_m=_float_or_none(properties.get("distance_m"))
                or _midpoint_distance(properties),
                score=round(float(score), 3),
                risk_bucket=str(properties.get("risk_bucket") or "") or None,
                risk_level=_int_or_none(properties.get("risk_level")),
            )
        )
    return samples


def _representative_lat_lon(geometry: dict[str, Any]) -> tuple[float, float] | None:
    coords = geometry.get("coordinates")
    if geometry.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    if geometry.get("type") == "LineString" and isinstance(coords, list) and coords:
        first = coords[0]
        last = coords[-1]
        if (
            isinstance(first, list)
            and isinstance(last, list)
            and len(first) >= 2
            and len(last) >= 2
        ):
            return (float(first[1]) + float(last[1])) / 2.0, (
                float(first[0]) + float(last[0])
            ) / 2.0
    return None


def _nearest_route_match(
    samples: list[RouteRiskSample],
    lat: float,
    lon: float,
    *,
    allowed_corridor_m: float,
) -> dict[str, Any]:
    nearest = min(samples, key=lambda item: haversine_m(lat, lon, item.lat, item.lon))
    distance_m = haversine_m(lat, lon, nearest.lat, nearest.lon)
    return {
        "nearest_sample_id": nearest.sample_id,
        "nearest_segment_id": nearest.segment_id,
        "distance_m": round(distance_m, 2),
        "allowed_corridor_m": allowed_corridor_m,
        "inside_corridor": distance_m <= allowed_corridor_m,
        "nearest_route_lat": round(nearest.lat, 8),
        "nearest_route_lon": round(nearest.lon, 8),
    }


def _nearest_highest_risk(
    samples: list[RouteRiskSample],
    lat: float,
    lon: float,
    *,
    radius_m: float,
) -> dict[str, Any]:
    candidates = []
    for sample in samples:
        distance_m = haversine_m(lat, lon, sample.lat, sample.lon)
        if distance_m <= radius_m:
            candidates.append((sample.score, -distance_m, sample, distance_m))
    if not candidates:
        nearest = min(samples, key=lambda item: haversine_m(lat, lon, item.lat, item.lon))
        distance_m = haversine_m(lat, lon, nearest.lat, nearest.lon)
        sample = nearest
    else:
        _, _, sample, distance_m = max(candidates)
    return {
        "sample_id": sample.sample_id,
        "segment_id": sample.segment_id,
        "score": sample.score,
        "risk_bucket": sample.risk_bucket,
        "risk_level": sample.risk_level,
        "distance_m": round(distance_m, 2),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _classify(*, route_match: dict[str, Any], risk_context: dict[str, Any]) -> dict[str, Any]:
    inside_corridor = bool(route_match.get("inside_corridor"))
    score = _float_or_none(risk_context.get("score")) or 0.0
    risk_bucket = str(risk_context.get("risk_bucket") or "").lower()
    risk_level = _int_or_none(risk_context.get("risk_level")) or 0
    high_risk = score >= HIGH_RISK_SCORE_THRESHOLD or risk_bucket == "high" or risk_level >= 4
    if inside_corridor and not high_risk:
        classification = "normal_inside_corridor_low_risk"
    elif inside_corridor and high_risk:
        classification = "inside_corridor_high_risk_candidate"
    elif not inside_corridor and high_risk:
        classification = "off_route_high_risk_candidate"
    else:
        classification = "off_route_without_high_risk"
    return {
        "classification": classification,
        "inside_corridor": inside_corridor,
        "high_risk_candidate": high_risk,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _build_nmea_packet(
    *,
    lat: float,
    lon: float,
    altitude_m: float,
    time_utc: str,
    date_ddmmyy: str,
    speed_knots: float,
    course_deg: float,
    satellites: int,
    hdop: float,
) -> list[str]:
    lat_value, lat_hemi = _decimal_to_nmea_lat_lon(lat, is_lat=True)
    lon_value, lon_hemi = _decimal_to_nmea_lat_lon(lon, is_lat=False)
    return [
        _nmea_sentence(
            "GPGGA,{time},{lat},{lat_hemi},{lon},{lon_hemi},1,{satellites:02d},{hdop:.1f},{altitude:.1f},M,0.0,M,,".format(
                time=time_utc,
                lat=lat_value,
                lat_hemi=lat_hemi,
                lon=lon_value,
                lon_hemi=lon_hemi,
                satellites=satellites,
                hdop=hdop,
                altitude=altitude_m,
            )
        ),
        _nmea_sentence(
            "GPRMC,{time},A,{lat},{lat_hemi},{lon},{lon_hemi},{speed:.2f},{course:.1f},{date},,,A".format(
                time=time_utc,
                lat=lat_value,
                lat_hemi=lat_hemi,
                lon=lon_value,
                lon_hemi=lon_hemi,
                speed=speed_knots,
                course=course_deg,
                date=date_ddmmyy,
            )
        ),
        _nmea_sentence(
            "GPGSV,1,1,04,01,45,083,42,02,17,308,38,03,28,123,36,04,67,210,41"
        ),
    ]


def _decimal_to_nmea_lat_lon(value: float, *, is_lat: bool) -> tuple[str, str]:
    hemisphere = "N" if is_lat and value >= 0 else "S" if is_lat else "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60.0
    if is_lat:
        return f"{degrees:02d}{minutes:08.5f}", hemisphere
    return f"{degrees:03d}{minutes:08.5f}", hemisphere


def _nmea_sentence(body: str) -> str:
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


def _offset_lat_lon(
    lat: float,
    lon: float,
    *,
    east_m: float,
    north_m: float,
) -> tuple[float, float]:
    lat_offset = north_m / 111_111.0
    lon_offset = east_m / (111_111.0 * math.cos(math.radians(lat)))
    return lat + lat_offset, lon + lon_offset


def _merged_gnss_fix(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    fix = {
        "lat": None,
        "lon": None,
        "altitude_m": None,
        "gnss_time_utc": None,
        "valid": False,
        "quality": None,
        "satellites": None,
        "hdop": None,
        "course_deg": None,
        "speed_mps": None,
        "checksum_valid": all(payload.get("checksum_valid") is True for payload in payloads),
    }
    for payload in payloads:
        sentence_type = str(payload.get("sentence_type") or "")
        position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
        for key in ("lat", "lon", "altitude_m"):
            if position.get(key) is not None:
                fix[key] = position.get(key)
        fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
        if sentence_type.endswith(("GGA", "RMC")) and fix_quality.get("valid") is not None:
            fix["valid"] = bool(fix_quality.get("valid"))
        for key in ("quality", "satellites", "hdop"):
            if fix_quality.get(key) is not None:
                fix[key] = fix_quality.get(key)
        motion = payload.get("motion") if isinstance(payload.get("motion"), dict) else {}
        for key in ("course_deg", "speed_mps"):
            if motion.get(key) is not None:
                fix[key] = motion.get(key)
        if payload.get("gnss_time_utc"):
            fix["gnss_time_utc"] = payload.get("gnss_time_utc")
    return fix


def _midpoint_distance(properties: dict[str, Any]) -> float | None:
    start = _float_or_none(properties.get("start_distance_m"))
    end = _float_or_none(properties.get("end_distance_m"))
    if start is None or end is None:
        return None
    return (start + end) / 2.0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe Scout AI live-navigation answers from fixture NMEA packets."
    )
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--allowed-corridor-m", type=float, default=DEFAULT_ALLOWED_CORRIDOR_M)
    parser.add_argument("--hazard-offset-m", type=float, default=DEFAULT_HAZARD_OFFSET_M)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_probe_report(
        project_root=args.project_root,
        question=args.question,
        allowed_corridor_m=args.allowed_corridor_m,
        hazard_offset_m=args.hazard_offset_m,
    )
    write_probe_outputs(
        report,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
