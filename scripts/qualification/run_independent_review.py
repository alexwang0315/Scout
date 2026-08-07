from __future__ import annotations

import argparse
import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_REVIEW_OPT_IN_VALUES = {"1", "true", "yes", "on"}
SENSITIVE_REVIEW_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])-[_A-Za-z0-9-]{12,}\b"),
    re.compile(
        r'(?i)"(?:authorization|cookie|set-cookie|api[_-]?key|access[_-]?token|'
        r'refresh[_-]?token|password|private[_-]?key)"\s*:\s*"'
        r'(?!<redacted>|\[redacted\]|none|null|false|true)[^"]{8,}"'
    ),
)


def _api_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in schema.items()
        if key not in {"$schema", "$id"}
    }


def _image_content(evidence_root: Path, relative: str) -> dict[str, str] | None:
    path = evidence_root / relative
    if not path.is_file():
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{encoded}",
        "detail": "low",
    }


def _assert_reviewer_input_safe(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if any(pattern.search(encoded) for pattern in SENSITIVE_REVIEW_PATTERNS):
        raise RuntimeError("reviewer input contains sensitive material")


def run_review(evidence_root: Path, *, model: str) -> dict[str, Any]:
    external_review_enabled = os.environ.get(
        "SCOUT_QUALIFICATION_ALLOW_EXTERNAL_REVIEW",
        "",
    ).strip().lower() in EXTERNAL_REVIEW_OPT_IN_VALUES
    if not external_review_enabled:
        raise RuntimeError("external evidence review must be explicitly enabled")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for independent evidence review")
    reviewer_input = json.loads(
        (evidence_root / "reviewer-input.json").read_text(encoding="utf-8")
    )
    _assert_reviewer_input_safe(reviewer_input)
    schema = json.loads(
        (ROOT / "qualification/schemas/qualification-review.schema.json").read_text(
            encoding="utf-8"
        )
    )
    prompt = (ROOT / "qualification/prompts/gpt-reviewer.md").read_text(
        encoding="utf-8"
    )
    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": json.dumps(reviewer_input, ensure_ascii=False, sort_keys=True),
        }
    ]
    for relative in reviewer_input.get("screenshots") or []:
        image = _image_content(evidence_root, str(relative))
        if image is not None:
            content.append(image)
    response = OpenAI().responses.create(
        model=model,
        instructions=prompt,
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": "scout_dashboard_qualification_review",
                "schema": _api_schema(schema),
                "strict": True,
            }
        },
        store=False,
    )
    verdict = json.loads(response.output_text)
    Draft202012Validator(schema).validate(verdict)
    if verdict["commit_sha"] != reviewer_input["commit_sha"]:
        raise ValueError("review commit does not match reviewer input")
    if verdict["evidence_root_sha256"] != reviewer_input["evidence_root_sha256"]:
        raise ValueError("review evidence root does not match reviewer input")
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Run independent read-only GPT evidence review.")
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument(
        "--model",
        default=(
            os.environ.get("SCOUT_QUALIFICATION_REVIEW_MODEL", "").strip()
            or "gpt-5"
        ),
    )
    args = parser.parse_args()
    verdict = run_review(args.evidence_root, model=args.model)
    output = args.evidence_root / "reviewer-verdict.json"
    output.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
