from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from phase2_brain_models import BrainNode, BrainNodeType
from phase2_brain_store import BrainFileStore
from pretrip_brain_seed import (
    PreTripBrainSeedBundle,
    export_chilai_pretrip_brain_seed,
    validate_pretrip_brain_seed,
)


@dataclass(frozen=True)
class PreTripBrainSeedStoreResult:
    node_ids: list[str]
    paths: dict[str, str]
    counts_by_node_type: dict[str, int]
    observed_fact_count: int = 0

    def model_dump(self) -> dict[str, Any]:
        return {
            "node_ids": list(self.node_ids),
            "paths": dict(self.paths),
            "counts_by_node_type": dict(self.counts_by_node_type),
            "observed_fact_count": self.observed_fact_count,
        }


def write_chilai_pretrip_seed_to_brain_store(
    store: BrainFileStore,
    project_dir: Path | str,
    *,
    reviewed: bool = False,
    mission_id: str | None = None,
    package_uri: str | None = None,
    review_log_uri: str | None = None,
    strict_artifact_refs: bool = True,
) -> PreTripBrainSeedStoreResult:
    seed = export_chilai_pretrip_brain_seed(
        project_dir,
        reviewed=reviewed,
        mission_id=mission_id,
        package_uri=package_uri,
        review_log_uri=review_log_uri,
    )
    return write_pretrip_seed_to_brain_store(
        store,
        seed,
        strict_artifact_refs=strict_artifact_refs,
    )


def write_pretrip_seed_to_brain_store(
    store: BrainFileStore,
    seed: PreTripBrainSeedBundle,
    *,
    strict_artifact_refs: bool = True,
) -> PreTripBrainSeedStoreResult:
    validate_pretrip_brain_seed(seed)

    paths: dict[str, str] = {}
    node_ids: list[str] = []
    counts: dict[str, int] = {}
    for node in _ordered_seed_nodes(seed):
        path = store.write_node(node, strict_artifact_refs=strict_artifact_refs)
        node_ids.append(node.id)
        paths[node.id] = path.as_posix()
        counts[node.type.value] = counts.get(node.type.value, 0) + 1

    return PreTripBrainSeedStoreResult(
        node_ids=node_ids,
        paths=paths,
        counts_by_node_type=dict(sorted(counts.items())),
        observed_fact_count=0,
    )


def _ordered_seed_nodes(seed: PreTripBrainSeedBundle) -> list[BrainNode]:
    return [
        *sorted(seed.artifacts, key=_node_order_key),
        *sorted(seed.human_reviews, key=_node_order_key),
        *sorted(seed.derived_measurements, key=_node_order_key),
        *sorted(seed.model_interpretations, key=_node_order_key),
    ]


def _node_order_key(node: BrainNode) -> tuple[str, str]:
    return (_node_type_order(node.type), node.id)


def _node_type_order(node_type: BrainNodeType) -> str:
    if node_type == BrainNodeType.ARTIFACT:
        return "0"
    if node_type == BrainNodeType.HUMAN_REVIEW:
        return "1"
    if node_type == BrainNodeType.DERIVED_MEASUREMENT:
        return "2"
    if node_type == BrainNodeType.MODEL_INTERPRETATION:
        return "3"
    return "4"
