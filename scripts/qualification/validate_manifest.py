from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def validate_manifest(manifest_path: Path, schema_path: Path) -> dict[str, Any]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = [
        {
            "path": "/".join(str(part) for part in error.absolute_path),
            "message": error.message,
        }
        for error in sorted(
            Draft202012Validator(schema).iter_errors(manifest),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    ]
    capability_ids = [
        str(capability.get("id") or "")
        for surface in (manifest.get("surfaces") or [])
        for capability in (surface.get("capabilities") or [])
    ]
    duplicates = sorted(
        capability_id
        for capability_id in set(capability_ids)
        if capability_ids.count(capability_id) > 1
    )
    errors.extend(
        {"path": "surfaces", "message": f"duplicate capability id: {item}"}
        for item in duplicates
    )
    return {
        "schema": "scout.dashboardCapabilityManifestValidation.v1",
        "valid": not errors,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "capability_count": len(capability_ids),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Dashboard capability manifest.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "qualification/dashboard-capability-manifest.yaml",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT / "qualification/schemas/dashboard-capability-manifest.schema.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_manifest(args.manifest, args.schema)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
