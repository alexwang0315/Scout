#!/usr/bin/env python3
"""Print one deterministic MSER decision packet for inspection."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scout.schemas.mser import (  # noqa: E402
    CompactDimension,
    CompactSignal,
    EnvironmentalRepresentation,
    HumanLatentState,
    OperationalLatentState,
    TerrainLatentState,
    ToolCapability,
    WeatherLatentState,
)
from scout.services.mser_engine import MSEREngine  # noqa: E402


REFERENCE_TIME = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def _signal(
    dimension: CompactDimension,
    value: float | str,
    *,
    confidence: float = 0.9,
) -> CompactSignal:
    return CompactSignal(
        signal_id=f"demo.{dimension.value}",
        dimension=dimension,
        value=value,
        confidence=confidence,
        observed_at=REFERENCE_TIME,
        valid_until=REFERENCE_TIME + timedelta(hours=3),
        source_refs=(f"demo://{dimension.value}",),
    )


def _environment(*, omit_daylight: bool) -> EnvironmentalRepresentation:
    return EnvironmentalRepresentation(
        representation_id="mser-demo-rest",
        terrain=TerrainLatentState(
            exposure_risk=_signal(CompactDimension.EXPOSURE_RISK, 0.25),
            escape_cost=_signal(CompactDimension.ESCAPE_COST, 0.35),
        ),
        weather=WeatherLatentState(
            weather_stability=_signal(CompactDimension.WEATHER_STABILITY, 0.78),
        ),
        human=HumanLatentState(
            fatigue_index=_signal(CompactDimension.FATIGUE_INDEX, 0.58),
            energy_reserve=_signal(CompactDimension.ENERGY_RESERVE, 0.61),
        ),
        operation=OperationalLatentState(
            team_distance=_signal(CompactDimension.TEAM_DISTANCE, 16.0),
            remaining_daylight=(
                None
                if omit_daylight
                else _signal(CompactDimension.REMAINING_DAYLIGHT, 205.0)
            ),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="可以停十分鐘嗎？")
    parser.add_argument(
        "--omit-daylight",
        action="store_true",
        help="Demonstrate an insufficient certificate and gap-derived tool plan.",
    )
    args = parser.parse_args()
    packet = MSEREngine().prepare(
        question=args.question,
        environment=_environment(omit_daylight=args.omit_daylight),
        capabilities=(
            ToolCapability(
                tool_id="scout.context.total_info.v1",
                produces_dimensions=(CompactDimension.REMAINING_DAYLIGHT,),
                expected_confidence=0.9,
            ),
        ),
        now=REFERENCE_TIME,
    )
    print(packet.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
