from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_TEMPLATE_RECORDS: list[dict[str, Any]] = [
    {
        "timestamp_s": 10.0,
        "odometry": {
            "cumulative_distance_m": None,
            "heading_deg": None,
        },
        "operator_notes": "first stationary or start sample",
    },
    {
        "timestamp_s": 11.0,
        "odometry": {
            "cumulative_distance_m": None,
            "heading_deg": None,
        },
        "operator_notes": "second sample after forward movement",
    },
]


def build_template_records() -> list[dict[str, Any]]:
    return json.loads(json.dumps(DEFAULT_TEMPLATE_RECORDS))


def render_template_markdown(records: list[dict[str, Any]] | None = None) -> str:
    records = records or build_template_records()
    lines = [
        "# Scout Wheel Odometry JSONL Worksheet",
        "",
        "Fill at least two records with increasing `timestamp_s` and monotonic cumulative distance.",
        "Use either `odometry.cumulative_distance_m`, left/right distances, or encoder ticks with `--meters-per-tick`.",
        "",
        "## JSONL Template",
        "",
        "```jsonl",
    ]
    lines.extend(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)
    lines.extend(
        [
            "```",
            "",
            "## Convert To DR Delta",
            "",
            "```bash",
            "python3 tools/pi_wheel_odometry_delta_smoke.py \\",
            "  --input-jsonl /path/to/wheel-odometry-filled.jsonl \\",
            "  --output-jsonl /path/to/wheel-dr-delta.jsonl",
            "```",
            "",
            "If the raw records only contain `left_ticks` and `right_ticks`, add `--meters-per-tick`.",
            "",
        ]
    )
    return "\n".join(lines)


def load_wheel_odometry_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if not isinstance(payload, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                payload.setdefault("raw_evidence_ref", f"{path}:{line_number}")
                payload.setdefault("_jsonl_path", str(path))
                payload.setdefault("_jsonl_line", line_number)
                records.append(payload)
    return records


def build_wheel_odometry_delta_payloads(
    records: list[dict[str, Any]],
    *,
    source: str = "wheel_odometry",
    provider: str = "scout_wheel_encoder",
    meters_per_tick: float | None = None,
    max_delta_m: float = 25.0,
) -> list[dict[str, Any]]:
    if max_delta_m <= 0:
        raise ValueError("max_delta_m must be positive")
    if meters_per_tick is not None and meters_per_tick <= 0:
        raise ValueError("meters_per_tick must be positive")

    cumulative_samples = [
        _cumulative_sample(record, meters_per_tick=meters_per_tick)
        for record in records
    ]
    samples = [sample for sample in cumulative_samples if sample is not None]
    if len(samples) < 2:
        return []

    payloads: list[dict[str, Any]] = []
    previous = samples[0]
    for sample in samples[1:]:
        if sample["timestamp_s"] <= previous["timestamp_s"]:
            raise ValueError("wheel odometry timestamps must be strictly increasing")
        if previous["dry_run"] or sample["dry_run"]:
            raise ValueError("dry-run wheel odometry cannot be converted into navigation DR evidence")
        distance_delta_m = sample["cumulative_distance_m"] - previous["cumulative_distance_m"]
        if distance_delta_m < 0:
            raise ValueError("wheel odometry cumulative distance must be monotonic")
        if distance_delta_m == 0:
            previous = sample
            continue
        if distance_delta_m > max_delta_m:
            raise ValueError(f"wheel odometry delta {distance_delta_m:g} m exceeds max_delta_m {max_delta_m:g}")

        payload = {
            "source": source,
            "provider": provider,
            "hardware_kind": "dead_reckoning_delta_evidence",
            "timestamp_s": sample["timestamp_s"],
            "distance_delta_m": distance_delta_m,
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "primary_truth_allowed": False,
            "dry_run": False,
            "previous_dry_run": previous["dry_run"],
            "current_dry_run": sample["dry_run"],
            "hardware_control_scope": "diagnostic_wheel_odometry_delta_only",
            "raw_evidence_ref": sample["raw_evidence_ref"],
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "odometry_delta_method": sample["method"],
            "previous_raw_evidence_ref": previous["raw_evidence_ref"],
            "current_raw_evidence_ref": sample["raw_evidence_ref"],
            "previous_cumulative_distance_m": previous["cumulative_distance_m"],
            "current_cumulative_distance_m": sample["cumulative_distance_m"],
        }
        if sample.get("heading_deg") is not None:
            payload["heading_deg"] = sample["heading_deg"]
        if sample.get("left_ticks") is not None or sample.get("right_ticks") is not None:
            payload["wheel_ticks"] = {
                "left": sample.get("left_ticks"),
                "right": sample.get("right_ticks"),
                "meters_per_tick": meters_per_tick,
            }
        payloads.append(payload)
        previous = sample
    return payloads


def write_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def write_template_jsonl(output_path: Path, records: list[dict[str, Any]] | None = None) -> None:
    write_jsonl(records or build_template_records(), output_path)


def _cumulative_sample(record: dict[str, Any], *, meters_per_tick: float | None) -> dict[str, Any] | None:
    timestamp_s = _timestamp_s(record)
    if timestamp_s is None:
        return None

    odometry = record.get("odometry") if isinstance(record.get("odometry"), dict) else {}
    wheel = record.get("wheel") if isinstance(record.get("wheel"), dict) else {}
    encoder = record.get("encoder") if isinstance(record.get("encoder"), dict) else {}

    cumulative_distance_m = _first_float(
        record,
        odometry,
        wheel,
        encoder,
        keys=(
            "cumulative_distance_m",
            "wheel_cumulative_distance_m",
            "encoder_distance_m",
            "distance_m",
            "wheel_distance_m",
        ),
    )
    method = "cumulative_distance_m"

    if cumulative_distance_m is None:
        left_distance_m = _first_float(record, odometry, wheel, encoder, keys=("left_distance_m",))
        right_distance_m = _first_float(record, odometry, wheel, encoder, keys=("right_distance_m",))
        if left_distance_m is not None and right_distance_m is not None:
            cumulative_distance_m = (left_distance_m + right_distance_m) / 2.0
            method = "left_right_distance_m"

    left_ticks = _first_int(record, odometry, wheel, encoder, keys=("left_ticks", "left_encoder_ticks"))
    right_ticks = _first_int(record, odometry, wheel, encoder, keys=("right_ticks", "right_encoder_ticks"))
    if cumulative_distance_m is None and (left_ticks is not None or right_ticks is not None):
        if meters_per_tick is None:
            raise ValueError("meters_per_tick is required when wheel records only provide encoder ticks")
        if left_ticks is None or right_ticks is None:
            raise ValueError("left and right wheel ticks are both required for tick-derived odometry")
        cumulative_distance_m = ((left_ticks + right_ticks) / 2.0) * meters_per_tick
        method = "wheel_ticks"

    if cumulative_distance_m is None:
        return None
    if cumulative_distance_m < 0 or math.isnan(cumulative_distance_m) or math.isinf(cumulative_distance_m):
        raise ValueError("cumulative wheel distance must be a finite non-negative number")

    return {
        "timestamp_s": timestamp_s,
        "cumulative_distance_m": cumulative_distance_m,
        "heading_deg": _heading_deg(record, odometry, wheel, encoder),
        "raw_evidence_ref": str(record.get("raw_evidence_ref") or f"wheel_odometry:{timestamp_s:g}"),
        "method": method,
        "dry_run": record.get("dry_run") is True,
        "left_ticks": left_ticks,
        "right_ticks": right_ticks,
    }


def _timestamp_s(record: dict[str, Any]) -> float | None:
    for key in ("timestamp_s", "timestamp", "observed_at_s", "loggingTimestamp_s"):
        value = _float_or_none(record.get(key))
        if value is not None:
            return value
    for key in ("captured_at", "observed_at", "received_at", "loggingTime"):
        value = record.get(key)
        if isinstance(value, str):
            parsed = _parse_datetime_s(value)
            if parsed is not None:
                return parsed
    return None


def _heading_deg(*mappings: dict[str, Any]) -> float | None:
    value = _first_float(
        *mappings,
        keys=("heading_deg", "yaw_deg", "course_deg", "motionHeading", "locationCourse"),
    )
    if value is None:
        return None
    if value < 0:
        return None
    return value % 360.0


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


def _first_float(*mappings: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for mapping in mappings:
        for key in keys:
            value = _float_or_none(mapping.get(key))
            if value is not None:
                return value
    return None


def _first_int(*mappings: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    value = _first_float(*mappings, keys=keys)
    return int(value) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert cumulative Scout wheel/encoder odometry JSONL into diagnostic DR distance deltas."
    )
    parser.add_argument("--input-jsonl", type=Path, action="append", help="Wheel odometry JSONL input. May repeat.")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--write-template-jsonl", type=Path)
    parser.add_argument("--write-template-md", type=Path)
    parser.add_argument("--source", default="wheel_odometry")
    parser.add_argument("--provider", default="scout_wheel_encoder")
    parser.add_argument("--meters-per-tick", type=float)
    parser.add_argument("--max-delta-m", type=float, default=25.0)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    if args.write_template_jsonl or args.write_template_md:
        records = build_template_records()
        if args.write_template_jsonl:
            write_template_jsonl(args.write_template_jsonl, records)
        if args.write_template_md:
            args.write_template_md.parent.mkdir(parents=True, exist_ok=True)
            args.write_template_md.write_text(render_template_markdown(records), encoding="utf-8")
        report = {
            "source": "pi_wheel_odometry_delta_smoke",
            "hardware_kind": "wheel_odometry_input_template",
            "template_record_count": len(records),
            "template_jsonl": str(args.write_template_jsonl) if args.write_template_jsonl else None,
            "template_md": str(args.write_template_md) if args.write_template_md else None,
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "primary_truth_allowed": False,
            "hardware_control_scope": "diagnostic_wheel_odometry_template_only",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
        return 0

    if not args.input_jsonl:
        parser.error("--input-jsonl is required unless --write-template-jsonl or --write-template-md is used")

    try:
        records = load_wheel_odometry_jsonl(args.input_jsonl)
        payloads = build_wheel_odometry_delta_payloads(
            records,
            source=args.source,
            provider=args.provider,
            meters_per_tick=args.meters_per_tick,
            max_delta_m=args.max_delta_m,
        )
        write_jsonl(payloads, args.output_jsonl)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    report = {
        "source": "pi_wheel_odometry_delta_smoke",
        "hardware_kind": "wheel_odometry_delta_evidence",
        "input_record_count": len(records),
        "input_dry_run_record_count": sum(1 for record in records if record.get("dry_run") is True),
        "payload_count": len(payloads),
        "output_jsonl": str(args.output_jsonl) if args.output_jsonl else None,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "hardware_control_scope": "diagnostic_wheel_odometry_delta_only",
        "payloads": payloads,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
