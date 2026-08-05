from __future__ import annotations

import ast
import json
from pathlib import Path

from tests.qualification.contracts import (
    HistoricalCapabilityInventory,
    HistoricalCapabilityRecord,
    file_sha256,
)


def _record(value: dict[str, object]) -> HistoricalCapabilityRecord:
    return HistoricalCapabilityRecord(
        schema_version=str(value["schema_version"]),
        capability_id=str(value["capability_id"]),
        discovered_from=tuple(str(item) for item in value["discovered_from"]),
        disposition=str(value["disposition"]),  # type: ignore[arg-type]
        migration_or_recovery_id=(
            None
            if value.get("migration_or_recovery_id") is None
            else str(value["migration_or_recovery_id"])
        ),
    )


def load_declared_historical_inventory(
    repository_root: Path,
    *,
    manifest_path: Path,
) -> HistoricalCapabilityInventory:
    root = Path(repository_root)
    value = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    source_paths = tuple(str(item) for item in value["source_paths"])
    return HistoricalCapabilityInventory(
        source_sha256=tuple(
            (path, file_sha256(root / path)) for path in source_paths
        ),
        records=tuple(_record(item) for item in value["records"]),
    )


def discover_historical_capabilities(
    repository_root: Path,
) -> tuple[HistoricalCapabilityRecord, ...]:
    root = Path(repository_root)
    production_ref = "scout_contextual_permission_workbench.py"
    catalog_ref = (
        "tests/qualification/fixtures/contextual_permission/"
        "supported_state_catalog.json"
    )
    closure_ref = (
        "docs/evals/dashboard-internal-qualification-phase1-closure-rev3.json"
    )
    production_tree = ast.parse(
        (root / production_ref).read_text(encoding="utf-8")
    )
    literals = {
        node.value
        for node in ast.walk(production_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    catalog = json.loads((root / catalog_ref).read_text(encoding="utf-8"))
    catalog_capabilities = {
        str(item["baseline_capability"]) for item in catalog["states"]
    }
    transition_ids = {
        str(item["transition_id"]) for item in catalog["transitions"]
    }
    closure = json.loads((root / closure_ref).read_text(encoding="utf-8"))
    closure_text = json.dumps(closure, sort_keys=True)
    discovered: list[HistoricalCapabilityRecord] = []
    if (
        "legacy_sparse.v1" in literals
        and "legacy_sparse.v1" in catalog_capabilities
        and "legacy_sparse.v1" in closure_text
        and {
            "provide-proposal-inputs-from-candidate",
            "provide-proposal-inputs-from-history",
        }
        <= transition_ids
    ):
        discovered.append(
            HistoricalCapabilityRecord(
                "contextual-permission.capability.v1",
                "legacy_sparse.v1",
                (production_ref, catalog_ref, closure_ref),
                "executable_migration",
                "compatibility.legacy-to-ref-gpx",
            )
        )
    if (
        "ref_gpx_proposal.v1" in literals
        and "ref_gpx_proposal.v1" in catalog_capabilities
        and "ref_gpx_proposal.v1" in closure_text
        and any(
            item.get("state_id") == "qualified-ready"
            and item.get("outcome") == "ready"
            for item in catalog["states"]
        )
    ):
        discovered.append(
            HistoricalCapabilityRecord(
                "contextual-permission.capability.v1",
                "ref_gpx_proposal.v1",
                (production_ref, catalog_ref, closure_ref),
                "direct_support",
            )
        )
    if (
        "unknown_or_unsupported" in literals
        and "unknown_or_unsupported" in catalog_capabilities
        and "quarantine-corrupt-artifact" in transition_ids
    ):
        discovered.append(
            HistoricalCapabilityRecord(
                "contextual-permission.capability.v1",
                "unknown_or_unsupported",
                (production_ref, catalog_ref),
                "quarantined",
                "quarantine.unsupported",
            )
        )
    return tuple(discovered)


__all__ = [
    "discover_historical_capabilities",
    "load_declared_historical_inventory",
]
