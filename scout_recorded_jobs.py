"""Durable six-force analysis jobs for immutable Recorded observation sets."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from typing import Literal

from pydantic import Field

from scout_planned_analysis import PlannedAnalysisManager, PlannedAnalysisResumeRequest
from scout_planned_route_models import PlannedModel, PlannedRouteConflict
from scout_recorded_analysis import (
    BOUNDARY, STORE_REF, VERSION_RE, _bytes, get_recorded_version,
)


class RecordedAnalysisRunRequest(PlannedModel):
    version_id: str = Field(pattern=VERSION_RE.pattern)
    expected_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    explicit_confirmation: Literal[True]


# Resume retains the existing signed run/version identity and explicit operator
# action. No planning-review receipt is required or synthesized for observations.
RecordedAnalysisResumeRequest = PlannedAnalysisResumeRequest


def recorded_binding(bundle: dict) -> dict:
    manifest = bundle["manifest"]
    return {
        "project_id": manifest["project_id"], "version_id": manifest["version_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "manifest_file_sha256": hashlib.sha256(_bytes(manifest)).hexdigest(),
        "geometry_sha256": manifest["geometry_sha256"],
        "itinerary_sha256": manifest["itinerary_sha256"],
        "source_hashes": manifest["source_hashes"],
        "canonical_files": {name: manifest["files"][name]["sha256"] for name in (
            "recorded.gpx", "route_axis.json", "checkpoints.json", "segments.json", "itinerary.json")},
        "kind": "recorded_gpx", "subject_kind": "recorded_gpx",
        "source_times_role": manifest["source_times_role"],
        "observation_kind": manifest["observation_kind"],
        "actual_user_recorded_activity": manifest["actual_user_recorded_activity"],
        "weather_evaluation_mode": "historical_at_observation_time",
        **BOUNDARY,
    }


class RecordedAnalysisManager(PlannedAnalysisManager):
    authority = BOUNDARY
    runs_ref = STORE_REF + "/runs"
    version_pattern = VERSION_RE
    worker_module = "scout_recorded_jobs"

    def _admit_bundle(self, version: str, expected: str) -> dict:
        bundle = get_recorded_version(self.root, version, expected)
        if bundle["source_status"]["status"] != "current":
            raise PlannedRouteConflict("recorded_analysis_sources_changed", "Recorded sources changed; save and select a new observation version.")
        return bundle

    def _binding(self, bundle: dict) -> dict:
        return recorded_binding(bundle)


def manager_for(root: Path) -> RecordedAnalysisManager:
    return RecordedAnalysisManager(root)


def latest_recorded_analysis(root: Path, bundle: dict) -> dict | None:
    manager = manager_for(root)
    runs = manager.list(bundle["manifest"]["version_id"])["runs"]
    return manager.get(runs[0]["run_id"]) if runs else None


def _main() -> None:
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        RecordedAnalysisManager(Path(sys.argv[2]))._run(sys.argv[3], int(sys.argv[4]))
        return
    raise SystemExit("Use --worker with the owner workspace, run ID and inherited lease.")


if __name__ == "__main__":
    _main()
