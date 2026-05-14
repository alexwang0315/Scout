from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from phase1_phase2_adapter import (
    adapt_phase1_incident_package,
    load_phase1_incident_package,
    persist_phase1_adapter_output,
)
from phase2_brain_models import BrainNode
from phase2_brain_store import BrainFileStore


def import_phase1_incident_package(
    *,
    incident_package_path: Path,
    store_root: Path,
    mission_id: str | None = None,
    source_uri: str | None = None,
) -> dict[str, Any]:
    package = load_phase1_incident_package(incident_package_path)
    output = adapt_phase1_incident_package(
        package,
        source_uri=source_uri or incident_package_path.as_posix(),
        mission_id=mission_id,
    )
    store = BrainFileStore(store_root)
    paths = persist_phase1_adapter_output(store, output)

    return {
        "incident_id": package.incident_id,
        "store_root": store.root.as_posix(),
        "counts": _counts_by_type(output.nodes),
        "node_ids": [node.id for node in output.nodes],
        "key_artifact_ids": [artifact.id for artifact in output.artifacts],
        "written_paths": [path.as_posix() for path in paths],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import an existing persisted Phase 1 incident package into a Phase 2 Brain store."
    )
    parser.add_argument(
        "--incident-package",
        required=True,
        type=Path,
        help="Path to a persisted Phase 1 IncidentPackage JSON file.",
    )
    parser.add_argument(
        "--store-root",
        required=True,
        type=Path,
        help="Target Phase 2 Brain store root.",
    )
    parser.add_argument(
        "--mission-id",
        help="Optional Phase 2 mission id to attach to imported nodes.",
    )
    parser.add_argument(
        "--source-uri",
        help="Optional stable or redacted source URI for the incident package artifact.",
    )
    args = parser.parse_args(argv)

    try:
        summary = import_phase1_incident_package(
            incident_package_path=args.incident_package,
            store_root=args.store_root,
            mission_id=args.mission_id,
            source_uri=args.source_uri,
        )
    except Exception as exc:
        print(f"failed to import Phase 1 incident package: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


def _counts_by_type(nodes: list[BrainNode]) -> dict[str, int]:
    counts = Counter(node.type.value for node in nodes)
    return {key: counts[key] for key in sorted(counts)}


if __name__ == "__main__":
    raise SystemExit(main())
