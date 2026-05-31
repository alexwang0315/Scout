import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wheel_encoder_gpio_smoke import (
    build_wheel_encoder_records_from_ticks,
    capture_wheel_encoder_records,
    summarize_wheel_encoder_records,
)
from tools.pi_wheel_odometry_delta_smoke import build_wheel_odometry_delta_payloads


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wheel_encoder_gpio_smoke.py"


def test_build_wheel_encoder_records_from_ticks_outputs_cumulative_distance() -> None:
    records = build_wheel_encoder_records_from_ticks(
        left_ticks=[0, 12],
        right_ticks=[0, 10],
        meters_per_tick=0.05,
        provider="scout_gpio_wheel_encoder",
        dry_run=False,
    )

    assert len(records) == 2
    assert records[1]["source"] == "pi_wheel_encoder_gpio_smoke"
    assert records[1]["provider"] == "scout_gpio_wheel_encoder"
    assert records[1]["wheel"]["left_ticks"] == 12
    assert records[1]["wheel"]["right_ticks"] == 10
    assert records[1]["odometry"]["cumulative_distance_m"] == 0.55
    assert records[1]["dry_run"] is False
    assert records[1]["hardware_control_scope"] == "diagnostic_gpio_wheel_encoder_capture_only"


def test_gpio_wheel_encoder_records_feed_delta_converter() -> None:
    records = build_wheel_encoder_records_from_ticks(
        left_ticks=[0, 12],
        right_ticks=[0, 10],
        meters_per_tick=0.05,
        dry_run=False,
    )

    payloads = build_wheel_odometry_delta_payloads(records, provider="scout_gpio_wheel_encoder")

    assert len(payloads) == 1
    assert payloads[0]["distance_delta_m"] == 0.55
    assert payloads[0]["provider"] == "scout_gpio_wheel_encoder"
    assert payloads[0]["odometry_delta_method"] == "cumulative_distance_m"


def test_wheel_encoder_summary_requires_live_positive_movement() -> None:
    live_records = build_wheel_encoder_records_from_ticks(
        left_ticks=[0, 12],
        right_ticks=[0, 10],
        meters_per_tick=0.05,
        dry_run=False,
    )
    idle_records = build_wheel_encoder_records_from_ticks(
        left_ticks=[0, 0],
        right_ticks=[0, 0],
        meters_per_tick=0.05,
        dry_run=False,
    )
    dry_run_records = build_wheel_encoder_records_from_ticks(
        left_ticks=[0, 12],
        right_ticks=[0, 10],
        meters_per_tick=0.05,
        dry_run=True,
    )

    live_summary = summarize_wheel_encoder_records(live_records)
    idle_summary = summarize_wheel_encoder_records(idle_records)
    dry_run_summary = summarize_wheel_encoder_records(dry_run_records)

    assert live_summary["left_tick_delta"] == 12
    assert live_summary["right_tick_delta"] == 10
    assert live_summary["distance_delta_m"] == 0.55
    assert live_summary["wheel_movement_observed"] is True
    assert live_summary["live_positive_wheel_movement_ready"] is True
    assert live_summary["line_activity_observed"] is False
    assert live_summary["missing_reason"] is None
    assert idle_summary["wheel_movement_observed"] is False
    assert idle_summary["live_positive_wheel_movement_ready"] is False
    assert idle_summary["missing_reason"] == "no_positive_wheel_motion_observed"
    assert dry_run_summary["wheel_movement_observed"] is True
    assert dry_run_summary["live_positive_wheel_movement_ready"] is False
    assert dry_run_summary["missing_reason"] == "dry_run_not_navigation_evidence"


def test_wheel_encoder_live_capture_records_gpio_line_activity() -> None:
    reader = _SequenceWheelReader(
        [
            (0, 0),
            (1, 0),
            (1, 1),
            (0, 1),
            (1, 0),
        ]
    )

    records = capture_wheel_encoder_records(
        left_gpio=20,
        right_gpio=21,
        meters_per_tick=0.05,
        duration_seconds=0.03,
        sample_interval_seconds=0.005,
        poll_interval_ms=1.0,
        reader=reader,
    )
    summary = summarize_wheel_encoder_records(records)

    assert records[-1]["wheel"]["left_level_change_count"] >= 2
    assert records[-1]["wheel"]["right_level_change_count"] >= 2
    assert summary["line_activity_observed"] is True
    assert summary["left_level_change_delta"] >= 1
    assert summary["right_level_change_delta"] >= 1
    assert summary["wheel_movement_observed"] is True
    assert summary["live_positive_wheel_movement_ready"] is True


def test_gpio_wheel_encoder_cli_dry_run_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "wheel-gpio.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--meters-per-tick",
            "0.05",
            "--simulate-left-ticks",
            "0,12",
            "--simulate-right-ticks",
            "0,10",
            "--output-jsonl",
            str(output),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert report["source"] == "pi_wheel_encoder_gpio_smoke"
    assert report["dry_run"] is True
    assert report["final_cumulative_distance_m"] == 0.55
    assert report["line_activity_observed"] is False
    assert len(records) == 2
    assert records[1]["dry_run"] is True


def test_gpio_wheel_encoder_cli_rejects_non_monotonic_ticks(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--meters-per-tick",
            "0.05",
            "--simulate-left-ticks",
            "2,1",
            "--simulate-right-ticks",
            "0,1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must be monotonic" in result.stderr


def test_gpio_wheel_encoder_cli_require_live_positive_movement_rejects_dry_run(tmp_path: Path) -> None:
    output = tmp_path / "wheel-gpio.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--meters-per-tick",
            "0.05",
            "--simulate-left-ticks",
            "0,12",
            "--simulate-right-ticks",
            "0,10",
            "--output-jsonl",
            str(output),
            "--require-live-positive-movement",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["wheel_movement_observed"] is True
    assert report["live_positive_wheel_movement_ready"] is False
    assert report["missing_reason"] == "dry_run_not_navigation_evidence"


class _SequenceWheelReader:
    def __init__(self, levels: list[tuple[int, int]]) -> None:
        self._levels = levels
        self._index = 0

    def read_levels(self) -> tuple[int, int]:
        level = self._levels[min(self._index, len(self._levels) - 1)]
        self._index += 1
        return level

    def close(self) -> None:
        return None
