from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_TIMESTAMP_FIELDS = {"observed_at", "selected_observed_at", "updated_at"}
_SOURCE_REF_PREFIXES = ("prod://", "pi://", "provider://", "cwa://")


@dataclass(frozen=True)
class FreshnessSourceSpec:
    source_id: str
    source_ref: str
    artifact_path: Path
    timestamp_field: str
    max_age_minutes: int = 180

    def __post_init__(self) -> None:
        if not _SOURCE_ID_PATTERN.fullmatch(self.source_id):
            raise ValueError("source_id contains unsupported characters")
        if not self.source_ref.startswith(_SOURCE_REF_PREFIXES):
            raise ValueError("source_ref must use an approved opaque reference")
        if self.timestamp_field not in _TIMESTAMP_FIELDS:
            raise ValueError("timestamp_field is not approved")
        if self.max_age_minutes < 1:
            raise ValueError("max_age_minutes must be positive")
        object.__setattr__(self, "artifact_path", Path(self.artifact_path))


def evaluate_freshness_sources(
    sources: Iterable[FreshnessSourceSpec],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("freshness observation time must be timezone-aware")
    rows = [_evaluate_source(source, now=observed_at) for source in sources]
    current_count = sum(row["status"] == "current" for row in rows)
    stale_count = sum(row["status"] == "stale" for row in rows)
    missing_count = sum(row["status"] == "missing" for row in rows)
    invalid_count = sum(row["status"] == "invalid" for row in rows)
    stale_rejected = stale_count > 0 and all(
        not row["eligible"] for row in rows if row["status"] == "stale"
    )
    return {
        "artifact_kind": "scout_resident_freshness_attestor_status",
        "artifact_version": "resident_freshness_attestor_status.v0",
        "status": (
            "freshness_attestation_complete"
            if rows and missing_count == 0 and invalid_count == 0
            else "blocked_freshness_source_unavailable"
        ),
        "observed_at": observed_at.isoformat(),
        "source_count": len(rows),
        "current_source_count": current_count,
        "stale_source_count": stale_count,
        "missing_source_count": missing_count,
        "invalid_source_count": invalid_count,
        "freshness_window_enforced": bool(rows),
        "stale_source_rejected": stale_rejected,
        "sources": rows,
        "credential_material_embedded": False,
        "raw_payload_embedded": False,
        "raw_location_payload_embedded": False,
        "runtime_safety_truth_mutated": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_transport_invoked": False,
        "hardware_control_performed": False,
    }


def run_freshness_attestor_cycles(
    sources: Iterable[FreshnessSourceSpec],
    *,
    output_path: str | Path,
    max_cycles: int,
    poll_seconds: float,
    now_factory: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if max_cycles < 1:
        raise ValueError("max_cycles must be positive")
    if poll_seconds < 0:
        raise ValueError("poll_seconds must be non-negative")
    source_list = list(sources)
    if not source_list:
        raise ValueError("at least one freshness source is required")
    clock = now_factory or (lambda: datetime.now(timezone.utc))
    output = Path(output_path)
    latest: dict[str, Any] = {}
    started_at = clock()
    for cycle in range(1, max_cycles + 1):
        latest = evaluate_freshness_sources(source_list, now=started_at if cycle == 1 else clock())
        latest = {
            **latest,
            "started_at": started_at.isoformat(),
            "heartbeat_count": cycle,
            "resident_process_observed": cycle >= 2,
            "max_cycles": max_cycles,
            "poll_seconds": poll_seconds,
        }
        _write_json_atomic(output, latest)
        if cycle < max_cycles:
            sleep(poll_seconds)
    return latest


def _evaluate_source(
    source: FreshnessSourceSpec,
    *,
    now: datetime,
) -> dict[str, Any]:
    base = {
        "source_id": source.source_id,
        "source_ref": source.source_ref,
        "artifact_sha256": None,
        "source_observed_at": None,
        "source_age_minutes": None,
        "max_age_minutes": source.max_age_minutes,
        "status": "missing",
        "eligible": False,
    }
    try:
        raw = source.artifact_path.read_bytes()
    except OSError:
        return base
    base["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("artifact must be an object")
        value = payload.get(source.timestamp_field)
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {**base, "status": "invalid"}
    age_minutes = max(
        0.0,
        (
            now.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)
        ).total_seconds()
        / 60,
    )
    current = age_minutes <= source.max_age_minutes
    return {
        **base,
        "source_observed_at": timestamp.isoformat(),
        "source_age_minutes": round(age_minutes, 6),
        "status": "current" if current else "stale",
        "eligible": current,
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_source(value: str) -> FreshnessSourceSpec:
    parts = value.split("|")
    if len(parts) != 5:
        raise argparse.ArgumentTypeError(
            "source must be source_id|source_ref|artifact_path|timestamp_field|max_age_minutes"
        )
    try:
        return FreshnessSourceSpec(
            source_id=parts[0],
            source_ref=parts[1],
            artifact_path=Path(parts[2]),
            timestamp_field=parts[3],
            max_age_minutes=int(parts[4]),
        )
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded resident freshness attestor over sanitized artifacts."
    )
    parser.add_argument("--source", action="append", type=_parse_source, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-cycles", type=int, default=3)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)

    result = run_freshness_attestor_cycles(
        args.source,
        output_path=args.output,
        max_cycles=args.max_cycles,
        poll_seconds=args.poll_seconds,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "heartbeat_count": result["heartbeat_count"],
                "resident_process_observed": result["resident_process_observed"],
                "current_source_count": result["current_source_count"],
                "stale_source_count": result["stale_source_count"],
                "output": str(Path(args.output)),
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "freshness_attestation_complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
