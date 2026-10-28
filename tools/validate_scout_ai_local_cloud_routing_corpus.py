"""Validate the local/cloud routing corpus and its Jev boundary contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.nextgen.jev_model_routing import (  # noqa: E402
    ModelRoute,
    load_routing_corpus,
    validate_routing_corpus,
)


DEFAULT_CORPUS = ROOT / "docs/specs/scout-ai-local-cloud-routing-100-question-corpus.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()
    try:
        corpus = load_routing_corpus(args.corpus)
        errors = validate_routing_corpus(corpus)
    except Exception as exc:  # noqa: BLE001 - CLI should return a concise failure.
        print(f"INVALID: {type(exc).__name__}: {exc}")
        return 1
    local = sum(item.expected_route is ModelRoute.LOCAL for item in corpus.questions)
    cloud = sum(item.expected_route is ModelRoute.CLOUD for item in corpus.questions)
    print(f"questions={len(corpus.questions)} local={local} cloud={cloud}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("PASS: deterministic route contract and Jev advisory boundary are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

