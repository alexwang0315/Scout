from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import yaml


VALID_STATES = {
    "PASS",
    "FAIL",
    "FLAKY",
    "BLOCKED",
    "NOT_IMPLEMENTED",
    "INSUFFICIENT_EVIDENCE",
}


def evaluate_results(
    manifest: Mapping[str, Any],
    results: Mapping[str, str],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    blocking_states = policy.get("blocking_states") or {}
    blockers: list[dict[str, str]] = []
    normalized_results: dict[str, str] = {}

    for surface in manifest.get("surfaces") or []:
        for capability in surface.get("capabilities") or []:
            capability_id = str(capability.get("id") or "")
            criticality = str(capability.get("criticality") or "P2")
            state = str(results.get(capability_id) or "INSUFFICIENT_EVIDENCE")
            if state not in VALID_STATES:
                state = "INSUFFICIENT_EVIDENCE"
            normalized_results[capability_id] = state
            if state in set(blocking_states.get(criticality) or []):
                blockers.append(
                    {
                        "capability_id": capability_id,
                        "criticality": criticality,
                        "state": state,
                    }
                )

    blockers.sort(
        key=lambda item: (
            {"P0": 0, "P1": 1, "P2": 2}.get(item["criticality"], 3),
            item["capability_id"],
        )
    )
    return {
        "schema": "scout.dashboardQualificationEvaluation.v1",
        "machine_verdict": "FAIL" if blockers else "PASS",
        "merge_permitted": not blockers,
        "results": normalized_results,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Dashboard qualification gates.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    results_payload = json.loads(args.results.read_text(encoding="utf-8"))
    results = results_payload.get("capability_results", results_payload)
    policy = yaml.safe_load(args.policy.read_text(encoding="utf-8"))
    evaluation = evaluate_results(manifest, results, policy)
    encoded = json.dumps(evaluation, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if evaluation["merge_permitted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
