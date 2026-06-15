import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills.example_scout_skill.schemas import ScoutSkillInput, requires_human_approval


BASE = Path(__file__).resolve().parents[1] / "skills" / "example_scout_skill" / "examples"


def load(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def test_valid_payload_passes():
    payload = ScoutSkillInput.model_validate(load("valid.json"))
    assert payload.request_id == "req_00000001"
    assert requires_human_approval(payload) is False


def test_edge_payload_requires_hitl():
    payload = ScoutSkillInput.model_validate(load("edge.json"))
    assert requires_human_approval(payload) is True


def test_invalid_payload_fails():
    with pytest.raises(ValidationError):
        ScoutSkillInput.model_validate(load("invalid.json"))
