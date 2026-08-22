from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SENSITIVE_REVIEW_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])-[_A-Za-z0-9-]{12,}\b"),
    re.compile(
        r'(?i)"(?:authorization|cookie|set-cookie|api[_-]?key|access[_-]?token|'
        r'refresh[_-]?token|password|private[_-]?key)"\s*:\s*"'
        r'(?!<redacted>|\[redacted\]|none|null|false|true)[^"]{8,}"'
    ),
)


def _assert_reviewer_input_safe(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if any(pattern.search(encoded) for pattern in SENSITIVE_REVIEW_PATTERNS):
        raise RuntimeError("reviewer input contains sensitive material")


def run_review(evidence_root: Path, *, model: str) -> dict[str, Any]:
    del evidence_root, model
    raise RuntimeError(
        "Direct API review cannot qualify Scout Dashboard; use "
        "$gpt-pro-collaboration in the Codex in-app browser."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reject direct API review; use gpt-pro-collaboration in the Codex "
            "in-app browser."
        )
    )
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    run_review(args.evidence_root, model="not-applicable")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
