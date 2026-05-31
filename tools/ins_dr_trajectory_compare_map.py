from __future__ import annotations

import argparse
import html
import json
import math
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geo_utils import haversine_m  # noqa: E402


DR_SOURCES = {"dead_reckoning", "dead_reckoning_expired"}
EVIDENCE_REF_RE = re.compile(r"(?P<path>.+?\.json):(?P<line>\d+):(?P<kind>[^:]+)(?::.*)?$")


def build_trajectory_comparison(
    *,
    sensorlog_paths: list[Path],
    estimates_jsonl_path: Path,
    overpass_geojson_path: Path | None = None,
    output_dir: Path,
    max_horizontal_accuracy_m: float = 25.0,
    max_interpolation_gap_s: float = 10.0,
    top_error_count: int = 20,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    gps_tracks = {
        str(path.expanduser().resolve()): _load_sensorlog_track(
            path.expanduser().resolve(),
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
        )
        for path in sensorlog_paths
    }
    no_good_gps = {
        str(path.expanduser().resolve()): _load_no_good_gps_summary(
            path.expanduser().resolve(),
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
        )
        for path in sensorlog_paths
    }
    estimates = _load_estimates(estimates_jsonl_path.expanduser().resolve())
    reports = []
    html_datasets = []
    for path_key, gps_track in gps_tracks.items():
        file_estimates = [estimate for estimate in estimates if estimate["path_key"] == path_key]
        compared = _compare_estimates_to_gps(
            estimates=file_estimates,
            gps_track=gps_track,
            max_interpolation_gap_s=max_interpolation_gap_s,
        )
        file_report = _file_report(
            path_key=path_key,
            gps_track=gps_track,
            compared=compared,
            all_estimates=file_estimates,
            no_good_gps_summary=no_good_gps[path_key],
        )
        reports.append(file_report)
        html_datasets.append(
            _html_dataset(
                file_report=file_report,
                gps_track=gps_track,
                all_estimates=file_estimates,
                compared=compared,
                no_good_gps_summary=no_good_gps[path_key],
                top_n=top_error_count,
            )
        )

    overpass_geojson = _load_json(overpass_geojson_path.expanduser().resolve()) if overpass_geojson_path else None
    bundle_report = {
        "artifact_kind": "scout_ins_dr_trajectory_comparison",
        "source_tool": "ins_dr_trajectory_compare_map",
        "estimates_jsonl_path": str(estimates_jsonl_path.expanduser().resolve()),
        "sensorlog_paths": [str(path.expanduser().resolve()) for path in sensorlog_paths],
        "overpass_geojson_path": str(overpass_geojson_path.expanduser().resolve()) if overpass_geojson_path else None,
        "max_horizontal_accuracy_m": max_horizontal_accuracy_m,
        "max_interpolation_gap_s": max_interpolation_gap_s,
        "reports": reports,
        "bundle_summary": _bundle_summary(reports),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_trajectory_comparison_only",
        "live_navigation_completion_proof": False,
    }

    report_path = output_dir / "trajectory_diff_report.json"
    html_path = output_dir / "trajectory_diff_map.html"
    png_path = output_dir / "trajectory_diff_overpass.png"
    report_path.write_text(json.dumps(bundle_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_html_map(
        output_path=html_path,
        report=bundle_report,
        datasets=html_datasets,
        overpass_geojson=overpass_geojson,
    )
    _write_static_png(
        output_path=png_path,
        datasets=html_datasets,
        overpass_geojson=overpass_geojson,
    )
    bundle_report["outputs"] = {
        "report_json": str(report_path),
        "html_map": str(html_path),
        "static_png": str(png_path),
    }
    report_path.write_text(json.dumps(bundle_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle_report


def _load_sensorlog_track(path: Path, *, max_horizontal_accuracy_m: float) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        records = [item for item in payload.get("imu_data", []) if isinstance(item, dict)] or [payload]
    else:
        raise ValueError(f"SensorLog JSON must be list or object: {path}")

    track = []
    for index, record in enumerate(records):
        lat = _float_or_none(record.get("locationLatitude"))
        lon = _float_or_none(record.get("locationLongitude"))
        accuracy = _float_or_none(record.get("locationHorizontalAccuracy"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        if accuracy is not None and accuracy > max_horizontal_accuracy_m:
            continue
        track.append(
            {
                "timestamp_s": _track_timestamp_s(record, fallback_timestamp_s=float(index)),
                "lat": lat,
                "lon": lon,
                "accuracy_m": accuracy,
                "index": index + 1,
            }
        )
    if not track:
        raise ValueError(f"No valid GPS samples at or below {max_horizontal_accuracy_m:g} m accuracy: {path}")
    track.sort(key=lambda point: point["timestamp_s"])
    return track


def _load_no_good_gps_summary(path: Path, *, max_horizontal_accuracy_m: float) -> dict[str, Any]:
    payload = _load_json(path)
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        records = [item for item in payload.get("imu_data", []) if isinstance(item, dict)] or [payload]
    else:
        raise ValueError(f"SensorLog JSON must be list or object: {path}")

    weak_points = []
    no_location_count = 0
    pdr_count = 0
    imu_count = 0
    gaps: list[dict[str, Any]] = []
    current_gap: dict[str, Any] | None = None

    for index, record in enumerate(records, start=1):
        lat = _float_or_none(record.get("locationLatitude"))
        lon = _float_or_none(record.get("locationLongitude"))
        accuracy = _float_or_none(record.get("locationHorizontalAccuracy"))
        good = lat is not None and lon is not None and (accuracy is None or accuracy <= max_horizontal_accuracy_m)
        if good:
            if current_gap is not None:
                gaps.append(current_gap)
                current_gap = None
            continue

        if current_gap is None:
            current_gap = {
                "start_index": index,
                "end_index": index,
                "count": 0,
                "time_start": record.get("loggingTime"),
                "time_end": record.get("loggingTime"),
            }
        current_gap["end_index"] = index
        current_gap["count"] += 1
        current_gap["time_end"] = record.get("loggingTime")

        if lat is None or lon is None:
            no_location_count += 1
        else:
            weak_points.append(
                {
                    "timestamp_s": _timestamp_s(record, fallback_timestamp_s=float(index)),
                    "lat": lat,
                    "lon": lon,
                    "accuracy_m": accuracy,
                    "index": index,
                }
            )
        if _has_pdr(record):
            pdr_count += 1
        if _has_imu(record):
            imu_count += 1

    if current_gap is not None:
        gaps.append(current_gap)
    return {
        "sample_count": len(records),
        "no_good_gps_count": len(weak_points) + no_location_count,
        "weak_location_point_count": len(weak_points),
        "no_location_count": no_location_count,
        "pdr_on_no_good_gps_count": pdr_count,
        "imu_on_no_good_gps_count": imu_count,
        "gaps": gaps,
        "weak_points": weak_points,
    }


def _load_estimates(path: Path) -> list[dict[str, Any]]:
    estimates = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            estimate = json.loads(stripped)
            if not isinstance(estimate, dict):
                continue
            lat = _float_or_none(estimate.get("lat"))
            lon = _float_or_none(estimate.get("lon"))
            timestamp_s = _float_or_none(estimate.get("timestamp_s"))
            path_key = _estimate_path_key(estimate)
            if lat is None or lon is None or timestamp_s is None or path_key is None:
                continue
            estimates.append(
                {
                    **estimate,
                    "lat": lat,
                    "lon": lon,
                    "timestamp_s": timestamp_s,
                    "path_key": path_key,
                    "line_number": line_number,
                }
            )
    return estimates


def _compare_estimates_to_gps(
    *,
    estimates: list[dict[str, Any]],
    gps_track: list[dict[str, Any]],
    max_interpolation_gap_s: float,
) -> list[dict[str, Any]]:
    compared = []
    for estimate in estimates:
        gps = _interpolate_gps_at(gps_track, estimate["timestamp_s"], max_gap_s=max_interpolation_gap_s)
        if gps is None:
            continue
        error_m = haversine_m(estimate["lat"], estimate["lon"], gps["lat"], gps["lon"])
        compared.append(
            {
                "timestamp_s": estimate["timestamp_s"],
                "source": estimate.get("source"),
                "lat": estimate["lat"],
                "lon": estimate["lon"],
                "gps_lat": gps["lat"],
                "gps_lon": gps["lon"],
                "gps_accuracy_m": gps.get("accuracy_m"),
                "gps_interpolation_gap_s": gps.get("gap_s"),
                "error_m": error_m,
                "confidence": estimate.get("confidence"),
                "degraded": estimate.get("degraded"),
                "degradation_reasons": estimate.get("degradation_reasons") or [],
                "primary_truth_source": estimate.get("primary_truth_source"),
                "raw_evidence_refs": estimate.get("raw_evidence_refs") or [],
                "line_number": estimate.get("line_number"),
            }
        )
    compared.sort(key=lambda item: item["timestamp_s"])
    return compared


def _interpolate_gps_at(track: list[dict[str, Any]], timestamp_s: float, *, max_gap_s: float) -> dict[str, Any] | None:
    if not track:
        return None
    if timestamp_s < track[0]["timestamp_s"] or timestamp_s > track[-1]["timestamp_s"]:
        return None
    lo = 0
    hi = len(track) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if track[mid]["timestamp_s"] < timestamp_s:
            lo = mid + 1
        else:
            hi = mid
    after = track[lo]
    before = track[max(0, lo - 1)]
    if abs(after["timestamp_s"] - timestamp_s) < 1e-6:
        return {**after, "gap_s": 0.0}
    if after is before:
        return None
    gap_s = after["timestamp_s"] - before["timestamp_s"]
    if gap_s <= 0 or gap_s > max_gap_s:
        nearest = min((before, after), key=lambda point: abs(point["timestamp_s"] - timestamp_s))
        if abs(nearest["timestamp_s"] - timestamp_s) <= max_gap_s:
            return {**nearest, "gap_s": abs(nearest["timestamp_s"] - timestamp_s)}
        return None
    ratio = (timestamp_s - before["timestamp_s"]) / gap_s
    accuracy = None
    if before.get("accuracy_m") is not None and after.get("accuracy_m") is not None:
        accuracy = before["accuracy_m"] + (after["accuracy_m"] - before["accuracy_m"]) * ratio
    return {
        "timestamp_s": timestamp_s,
        "lat": before["lat"] + (after["lat"] - before["lat"]) * ratio,
        "lon": before["lon"] + (after["lon"] - before["lon"]) * ratio,
        "accuracy_m": accuracy,
        "gap_s": gap_s,
    }


def _file_report(
    *,
    path_key: str,
    gps_track: list[dict[str, Any]],
    compared: list[dict[str, Any]],
    all_estimates: list[dict[str, Any]],
    no_good_gps_summary: dict[str, Any],
) -> dict[str, Any]:
    all_errors = [item["error_m"] for item in compared]
    dr_errors = [item["error_m"] for item in compared if item["source"] in DR_SOURCES]
    anchor_errors = [item["error_m"] for item in compared if item["source"] not in DR_SOURCES]
    return {
        "input_path": path_key,
        "gps_sample_count": len(gps_track),
        "raw_ins_dr_estimate_count": len(all_estimates),
        "ins_dr_sample_count": len(compared),
        "ins_dr_without_gps_comparison_count": max(0, len(all_estimates) - len(compared)),
        "dead_reckoning_sample_count": sum(1 for item in compared if item["source"] in DR_SOURCES),
        "anchor_or_reanchor_sample_count": sum(1 for item in compared if item["source"] not in DR_SOURCES),
        "no_good_gps_summary": {
            key: value
            for key, value in no_good_gps_summary.items()
            if key != "weak_points"
        },
        "gps_time_start_s": gps_track[0]["timestamp_s"],
        "gps_time_end_s": gps_track[-1]["timestamp_s"],
        "ins_dr_time_start_s": compared[0]["timestamp_s"] if compared else None,
        "ins_dr_time_end_s": compared[-1]["timestamp_s"] if compared else None,
        "all_error_m": _numeric_summary(all_errors),
        "dead_reckoning_error_m": _numeric_summary(dr_errors),
        "anchor_or_reanchor_error_m": _numeric_summary(anchor_errors),
        "max_error_sample": max(compared, key=lambda item: item["error_m"]) if compared else None,
    }


def _html_dataset(
    *,
    file_report: dict[str, Any],
    gps_track: list[dict[str, Any]],
    all_estimates: list[dict[str, Any]],
    compared: list[dict[str, Any]],
    no_good_gps_summary: dict[str, Any],
    top_n: int,
) -> dict[str, Any]:
    ins_dr = [
        {
            "lat": item["lat"],
            "lon": item["lon"],
            "source": item.get("source"),
        }
        for item in all_estimates
    ]
    top_errors = sorted(compared, key=lambda item: item["error_m"], reverse=True)[:top_n]
    return {
        "name": Path(file_report["input_path"]).name,
        "report": file_report,
        "gps": [{"lat": point["lat"], "lon": point["lon"], "accuracy_m": point.get("accuracy_m")} for point in gps_track],
        "weakGps": [
            {
                "lat": point["lat"],
                "lon": point["lon"],
                "accuracy_m": point.get("accuracy_m"),
                "index": point.get("index"),
            }
            for point in no_good_gps_summary.get("weak_points", [])
        ],
        "insdr": ins_dr,
        "topErrors": top_errors,
    }


def _write_html_map(
    *,
    output_path: Path,
    report: dict[str, Any],
    datasets: list[dict[str, Any]],
    overpass_geojson: dict[str, Any] | None,
) -> None:
    center = _map_center(datasets)
    summary_html = _summary_html(report)
    payload = {
        "center": center,
        "datasets": datasets,
        "overpass": overpass_geojson,
    }
    output_path.write_text(
        f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Scout INS/DR vs GPS Trajectory Comparison</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .legend {{
      background: rgba(255, 255, 255, 0.94);
      padding: 12px 14px;
      border-radius: 8px;
      box-shadow: 0 2px 14px rgba(0,0,0,0.18);
      font: 13px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      max-width: 360px;
    }}
    .legend h1 {{ font-size: 15px; margin: 0 0 8px; }}
    .legend p {{ margin: 4px 0; }}
    .swatch {{ display:inline-block; width:14px; height:4px; vertical-align:middle; margin-right:6px; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const payload = {json.dumps(payload, ensure_ascii=False)};
    const map = L.map('map').setView([payload.center.lat, payload.center.lon], 15);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);
    const layers = {{}};
    if (payload.overpass) {{
      layers['Overpass OSM corridors'] = L.geoJSON(payload.overpass, {{
        style: () => ({{ color: '#6b7280', weight: 1, opacity: 0.42 }})
      }}).addTo(map);
    }}
    const bounds = [];
    for (const dataset of payload.datasets) {{
      const gpsLine = dataset.gps.map(p => [p.lat, p.lon]);
      const weakGpsLine = dataset.weakGps.map(p => [p.lat, p.lon]);
      const insLine = dataset.insdr.map(p => [p.lat, p.lon]);
      gpsLine.forEach(p => bounds.push(p));
      weakGpsLine.forEach(p => bounds.push(p));
      insLine.forEach(p => bounds.push(p));
      const gpsLayer = L.polyline(gpsLine, {{ color: '#2563eb', weight: 4, opacity: 0.82 }}).addTo(map);
      const weakGpsLayer = L.polyline(weakGpsLine, {{ color: '#f59e0b', weight: 3, opacity: 0.72, dashArray: '6 6' }}).addTo(map);
      const insLayer = L.polyline(insLine, {{ color: '#dc2626', weight: 3, opacity: 0.88 }}).addTo(map);
      layers[dataset.name + ' GPS'] = gpsLayer;
      layers[dataset.name + ' weak/no-good GPS with IMU/PDR'] = weakGpsLayer;
      layers[dataset.name + ' INS/DR'] = insLayer;
      for (const sample of dataset.topErrors) {{
        const connector = L.polyline([[sample.lat, sample.lon], [sample.gps_lat, sample.gps_lon]], {{
          color: '#f97316', weight: 2, opacity: 0.75, dashArray: '5 5'
        }}).addTo(map);
        connector.bindPopup(`<b>${{dataset.name}}</b><br/>error: ${{sample.error_m.toFixed(1)}} m<br/>source: ${{sample.source}}`);
        L.circleMarker([sample.lat, sample.lon], {{
          radius: 5, color: '#7f1d1d', fillColor: '#fca5a5', fillOpacity: 0.8, weight: 1
        }}).bindPopup(`<b>INS/DR</b><br/>error: ${{sample.error_m.toFixed(1)}} m`).addTo(map);
      }}
    }}
    if (bounds.length) {{
      map.fitBounds(bounds, {{ padding: [30, 30] }});
    }}
    const legend = L.control({{ position: 'topright' }});
    legend.onAdd = function() {{
      const div = L.DomUtil.create('div', 'legend');
      div.innerHTML = {json.dumps(summary_html, ensure_ascii=False)};
      return div;
    }};
    legend.addTo(map);
    L.control.layers(null, layers, {{ collapsed: false }}).addTo(map);
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )


def _write_static_png(
    *,
    output_path: Path,
    datasets: list[dict[str, Any]],
    overpass_geojson: dict[str, Any] | None,
) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 9), dpi=160)
    if overpass_geojson:
        for line in _geojson_lines(overpass_geojson):
            if len(line) < 2:
                continue
            lons = [point[0] for point in line]
            lats = [point[1] for point in line]
            ax.plot(lons, lats, color="#9ca3af", linewidth=0.35, alpha=0.45, zorder=1)
    colors = [("#2563eb", "#dc2626"), ("#0891b2", "#be123c")]
    for index, dataset in enumerate(datasets):
        gps_color, ins_color = colors[index % len(colors)]
        gps_lons = [point["lon"] for point in dataset["gps"]]
        gps_lats = [point["lat"] for point in dataset["gps"]]
        ins_lons = [point["lon"] for point in dataset["insdr"]]
        ins_lats = [point["lat"] for point in dataset["insdr"]]
        ax.plot(gps_lons, gps_lats, color=gps_color, linewidth=2.0, alpha=0.86, label=f"{dataset['name']} GPS", zorder=3)
        weak_lons = [point["lon"] for point in dataset["weakGps"]]
        weak_lats = [point["lat"] for point in dataset["weakGps"]]
        if weak_lons:
            ax.scatter(
                weak_lons,
                weak_lats,
                color="#f59e0b",
                s=4,
                alpha=0.55,
                label=f"{dataset['name']} weak GPS + IMU/PDR",
                zorder=3,
            )
        ax.plot(ins_lons, ins_lats, color=ins_color, linewidth=1.7, alpha=0.88, label=f"{dataset['name']} INS/DR", zorder=4)
        for sample in dataset["topErrors"][:8]:
            ax.plot(
                [sample["lon"], sample["gps_lon"]],
                [sample["lat"], sample["gps_lat"]],
                color="#f97316",
                linewidth=0.8,
                alpha=0.75,
                zorder=5,
            )
    ax.set_title("Scout INS/DR vs GPS trajectory difference over Overpass OSM context")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, color="#e5e7eb", linewidth=0.5)
    ax.legend(loc="best", fontsize=7)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)


def _summary_html(report: dict[str, Any]) -> str:
    lines = [
        "<h1>Scout INS/DR vs GPS</h1>",
        '<p><span class="swatch" style="background:#2563eb"></span>GPS track</p>',
        '<p><span class="swatch" style="background:#f59e0b"></span>Weak/no-good GPS samples that still carry IMU/PDR</p>',
        '<p><span class="swatch" style="background:#dc2626"></span>Scout INS/DR estimate</p>',
        '<p><span class="swatch" style="background:#f97316"></span>Top error connectors</p>',
    ]
    for item in report["reports"]:
        name = html.escape(Path(item["input_path"]).name)
        dr = item["dead_reckoning_error_m"]
        lines.append(
            f"<p><b>{name}</b><br/>DR median {_fmt_m(dr['median'])}, mean {_fmt_m(dr['mean'])}, "
            f"p95 {_fmt_m(dr['p95'])}, max {_fmt_m(dr['max'])}<br/>"
            f"no-good GPS + PDR {item['no_good_gps_summary']['pdr_on_no_good_gps_count']} samples</p>"
        )
    return "".join(lines)


def _bundle_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    dr_errors = []
    all_errors = []
    for report in reports:
        if report["dead_reckoning_error_m"]["values"]:
            dr_errors.extend(report["dead_reckoning_error_m"]["values"])
        if report["all_error_m"]["values"]:
            all_errors.extend(report["all_error_m"]["values"])
    return {
        "file_count": len(reports),
        "gps_sample_count": sum(report["gps_sample_count"] for report in reports),
        "ins_dr_sample_count": sum(report["ins_dr_sample_count"] for report in reports),
        "dead_reckoning_sample_count": sum(report["dead_reckoning_sample_count"] for report in reports),
        "dead_reckoning_error_m": _numeric_summary(dr_errors, include_values=False),
        "all_error_m": _numeric_summary(all_errors, include_values=False),
        "live_navigation_completion_proof": False,
    }


def _numeric_summary(values: list[float], *, include_values: bool = True) -> dict[str, Any]:
    if not values:
        summary = {"count": 0, "min": None, "max": None, "mean": None, "median": None, "p95": None}
    else:
        ordered = sorted(values)
        summary = {
            "count": len(values),
            "min": ordered[0],
            "max": ordered[-1],
            "mean": statistics.fmean(ordered),
            "median": statistics.median(ordered),
            "p95": _percentile(ordered, 95),
        }
    if include_values:
        summary["values"] = values
    return summary


def _percentile(ordered: list[float], percentile: float) -> float:
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * percentile / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] * (high - rank) + ordered[high] * (rank - low)


def _estimate_path_key(estimate: dict[str, Any]) -> str | None:
    refs = estimate.get("raw_evidence_refs")
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, str):
            continue
        match = EVIDENCE_REF_RE.match(ref)
        if match:
            return str(Path(match.group("path")).expanduser().resolve())
    return None


def _map_center(datasets: list[dict[str, Any]]) -> dict[str, float]:
    points = []
    for dataset in datasets:
        points.extend(dataset["gps"])
        points.extend(dataset["insdr"])
    if not points:
        return {"lat": 25.0, "lon": 121.0}
    return {
        "lat": statistics.fmean(point["lat"] for point in points),
        "lon": statistics.fmean(point["lon"] for point in points),
    }


def _geojson_lines(geojson: dict[str, Any]) -> list[list[tuple[float, float]]]:
    lines: list[list[tuple[float, float]]] = []
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict):
            continue
        _collect_geometry_lines(geometry, lines)
    return lines


def _collect_geometry_lines(geometry: dict[str, Any], lines: list[list[tuple[float, float]]]) -> None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString" and isinstance(coordinates, list):
        lines.append(_lon_lat_line(coordinates))
    elif geometry_type == "MultiLineString" and isinstance(coordinates, list):
        for line in coordinates:
            lines.append(_lon_lat_line(line))
    elif geometry_type == "Polygon" and isinstance(coordinates, list):
        for ring in coordinates:
            lines.append(_lon_lat_line(ring))
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        for polygon in coordinates:
            for ring in polygon:
                lines.append(_lon_lat_line(ring))


def _lon_lat_line(raw_points: list[Any]) -> list[tuple[float, float]]:
    points = []
    for item in raw_points:
        if isinstance(item, list) and len(item) >= 2:
            lon = _float_or_none(item[0])
            lat = _float_or_none(item[1])
            if lat is not None and lon is not None:
                points.append((lon, lat))
    return points


def _load_json(path: Path | None) -> Any:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _timestamp_s(record: dict[str, Any], *, fallback_timestamp_s: float) -> float:
    for key in ("timestamp_s", "locationTimestamp_since1970", "loggingTimestamp_s", "motionTimestamp_sinceReboot"):
        value = _float_or_none(record.get(key))
        if value is not None:
            return value
    raw = record.get("loggingTime") or record.get("heartRateBPMTimestamp")
    if isinstance(raw, str) and raw and raw != "null":
        parsed = _parse_datetime_s(raw)
        if parsed is not None:
            return parsed
    return fallback_timestamp_s


def _track_timestamp_s(record: dict[str, Any], *, fallback_timestamp_s: float) -> float:
    raw = record.get("loggingTime") or record.get("heartRateBPMTimestamp")
    if isinstance(raw, str) and raw and raw != "null":
        parsed = _parse_datetime_s(raw)
        if parsed is not None:
            return parsed
    return _timestamp_s(record, fallback_timestamp_s=fallback_timestamp_s)


def _parse_datetime_s(value: str) -> float | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _fmt_m(value: Any) -> str:
    parsed = _float_or_none(value)
    return "n/a" if parsed is None else f"{parsed:.1f} m"


def _has_pdr(record: dict[str, Any]) -> bool:
    return (
        _float_or_none(record.get("pedometerDistance")) is not None
        or _float_or_none(record.get("pedometerNumberOfSteps") or record.get("pedometerNumberofSteps")) is not None
    )


def _has_imu(record: dict[str, Any]) -> bool:
    return any(
        record.get(key) not in (None, "", "null")
        for key in (
            "accelerometerAccelerationX",
            "accelerometerAccelerationY",
            "accelerometerAccelerationZ",
            "motionYaw",
            "motionPitch",
            "motionRoll",
            "motionUserAccelerationX",
            "motionUserAccelerationY",
            "motionUserAccelerationZ",
            "motionRotationRateX",
            "motionRotationRateY",
            "motionRotationRateZ",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare Scout INS/DR replay trajectory with GPS and render an Overpass overlay map.")
    parser.add_argument("--sensorlog", type=Path, action="append", required=True, help="Original SensorLog JSON. May repeat.")
    parser.add_argument("--estimates-jsonl", type=Path, required=True, help="INS/DR estimates JSONL from replay.")
    parser.add_argument("--overpass-geojson", type=Path, help="Optional Overpass-derived GeoJSON context.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-horizontal-accuracy-m", type=float, default=25.0)
    parser.add_argument("--max-interpolation-gap-s", type=float, default=10.0)
    parser.add_argument("--top-error-count", type=int, default=20)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = build_trajectory_comparison(
            sensorlog_paths=args.sensorlog,
            estimates_jsonl_path=args.estimates_jsonl,
            overpass_geojson_path=args.overpass_geojson,
            output_dir=args.output_dir.expanduser().resolve(),
            max_horizontal_accuracy_m=args.max_horizontal_accuracy_m,
            max_interpolation_gap_s=args.max_interpolation_gap_s,
            top_error_count=args.top_error_count,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
