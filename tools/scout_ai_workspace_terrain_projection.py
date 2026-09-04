#!/usr/bin/env python3
"""Create an experimental Route/DEM projection without modifying a Workspace."""

from __future__ import annotations

import argparse
from pathlib import Path

from scout.nextgen.workspace_terrain_projection import build_workspace_terrain_projection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--qgis-run", type=Path, required=True)
    parser.add_argument("--dem-source", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_directory.resolve()
    if output.is_relative_to(args.workspace.resolve()):
        parser.error("projection output must be outside the original Workspace")
    projection = build_workspace_terrain_projection(args.workspace, args.qgis_run, args.dem_source)
    output.mkdir(parents=True, exist_ok=True)
    (output / "projection.json").write_text(projection.model_dump_json(indent=2) + "\n")
    (output / "evidence-catalog.json").write_text(
        projection.evidence_catalog.model_dump_json(indent=2) + "\n"
    )
    print(projection.metrics.model_dump_json())
    print(f"projection={output / 'projection.json'}")
    print(f"input_hash={projection.workspace_binding.input_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
