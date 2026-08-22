from pathlib import Path
import json
import re
import sys

import yaml
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ".codex/checklist.yaml",
    ".github/PULL_REQUEST_TEMPLATE/scout-skill.md",
    "skills/example_scout_skill/schemas.py",
    "skills/example_scout_skill/examples/valid.json",
    "skills/example_scout_skill/examples/edge.json",
    "skills/example_scout_skill/examples/invalid.json",
    "docs/example_scout_skill-api.md",
    "observability/example_scout_skill-events.md",
]

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def fail(message: str) -> int:
    print(f"Scout governance checklist: FAIL - {message}")
    return 1


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def telemetry_fields_from_markdown(path: Path) -> set[str]:
    fields: set[str] = set()
    in_required = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.lower() == "required fields:":
            in_required = True
            continue
        if in_required and stripped.startswith("## "):
            break
        if in_required and stripped.startswith("- "):
            fields.add(stripped[2:].strip())
    return fields


def validate_schema_versions(examples: dict[str, dict], schema_version: str) -> str | None:
    if not schema_version or not SEMVER_RE.fullmatch(schema_version):
        return f"SCHEMA_VERSION is missing or not semver: {schema_version!r}"
    for name, payload in examples.items():
        value = payload.get("schema_version")
        if value is None:
            return f"{name} missing schema_version"
        if not SEMVER_RE.fullmatch(str(value)):
            return f"{name} schema_version is not semver: {value!r}"
    return None


def main() -> int:
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    if missing:
        print("Missing required files:")
        for p in missing:
            print(f" - {p}")
        return 1

    sys.path.insert(0, str(ROOT))
    from skills.example_scout_skill.schemas import (
        SCHEMA_VERSION,
        ScoutSkillInput,
        requires_human_approval,
    )

    examples_dir = ROOT / "skills/example_scout_skill/examples"
    examples = {
        name: load_json(examples_dir / name)
        for name in ["valid.json", "edge.json", "invalid.json"]
    }

    schema_version_error = validate_schema_versions(examples, SCHEMA_VERSION)
    if schema_version_error:
        return fail(schema_version_error)

    try:
        valid_payload = ScoutSkillInput.model_validate(examples["valid.json"])
        edge_payload = ScoutSkillInput.model_validate(examples["edge.json"])
    except ValidationError as exc:
        return fail(f"valid/edge example failed Pydantic validation: {exc}")

    try:
        ScoutSkillInput.model_validate(examples["invalid.json"])
    except ValidationError:
        pass
    else:
        return fail("invalid example unexpectedly passed Pydantic validation")

    checklist = yaml.safe_load((ROOT / ".codex/checklist.yaml").read_text(encoding="utf-8"))
    hitl_rules = checklist.get("risk", {}).get("require_human_approval", {}).get("when", [])
    if "risk_level == 'high'" not in hitl_rules:
        return fail("high risk is not covered by HITL checklist rules")
    if requires_human_approval(edge_payload) is not True:
        return fail("high-risk edge example does not require HITL")
    high_risk_probe = valid_payload.model_copy(update={"risk_level": "high"})
    if requires_human_approval(high_risk_probe) is not True:
        return fail("high-risk payload does not require HITL")

    telemetry_required = set(checklist.get("telemetry", {}).get("required_fields", []))
    if not telemetry_required:
        return fail("telemetry.required_fields is empty")
    telemetry_documented = telemetry_fields_from_markdown(
        ROOT / "observability/example_scout_skill-events.md"
    )
    missing_telemetry = sorted(telemetry_required - telemetry_documented)
    if missing_telemetry:
        return fail(f"telemetry required fields missing from spec: {missing_telemetry}")

    print("Scout governance checklist: OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
