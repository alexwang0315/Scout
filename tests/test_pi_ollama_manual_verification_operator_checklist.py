from __future__ import annotations

from pathlib import Path

from assistant_readiness_check import REQUIRED_PATHS


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "admin" / "pi-ollama-manual-verification.md"
SPEC_PATH = ROOT / "docs" / "specs" / "scout-cross-surface-ai-assistant.md"


def test_operator_checklist_documents_slice9_manual_flow() -> None:
    doc_source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "Milestone 10.2 Slice 9",
        "operator checklist",
        "checked_by_operator",
        "validate result fixture",
        "optional append-only index",
        "run read-only CLI renderer",
        "assistant_readiness_check.py --pretty",
        "not part of the assistant readiness gate",
        "不啟動本地模型",
        "不寫 Scout state",
    ):
        assert token in doc_source


def test_operator_checklist_preserves_phase_and_runtime_boundaries() -> None:
    doc_source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "不呼叫 `/safety/*` mutation",
        "不改 Phase 1 safety decision",
        "不寫 ObservedFact",
        "不寫 Phase 2 Brain",
        "不寫 IncidentStore",
        "不接受或拒絕 pretrip candidate",
        "不改 HumanReview",
        "不送 outbound message",
        "不控制 hardware",
        "不控制 provider",
        "read-only model interpretation",
    ):
        assert token in doc_source


def test_operator_checklist_is_not_a_required_readiness_artifact() -> None:
    assert "docs/admin/pi-ollama-manual-verification.md" not in REQUIRED_PATHS


def test_spec_tracks_slice9_and_next_slice_candidate() -> None:
    spec_source = SPEC_PATH.read_text(encoding="utf-8")

    for token in (
        "Milestone 10.2 Slice 9: Operator Checklist",
        "checked_by_operator",
        "validate result fixture",
        "run read-only CLI renderer",
        "not part of the assistant readiness gate",
    ):
        assert token in spec_source
    assert "Milestone 10.2 Slice 9 operator checklist is complete when" in spec_source
    assert "## Next Slice Candidates" in spec_source
