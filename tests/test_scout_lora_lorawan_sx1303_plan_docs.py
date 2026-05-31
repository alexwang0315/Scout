from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_DOC = REPO_ROOT / "docs/specs/scout-lora-lorawan-sx1303-plan.md"
HARDWARE_DIRECTION_DOC = REPO_ROOT / "docs/specs/scout-hardware-direction.md"
HARDWARE_PORT_PLAN_DOC = REPO_ROOT / "docs/specs/hardware-port-plan.md"


def test_lora_lorawan_sx1303_plan_is_mainline_and_bounded() -> None:
    text = PLAN_DOC.read_text(encoding="utf-8")

    required = [
        "Scout reduces the blank after disconnection.",
        "920-925 MHz",
        "AS923_TW_920_925",
        "SX1303",
        "fine timestamp",
        "at least three gateways",
        "phase1_safety_decision_change_allowed",
        "remote_outbound_allowed",
        "diagnostic_gateway_evidence_only",
        "Do not transmit on unvalidated or illegal frequency plans.",
    ]

    for token in required:
        assert token in text


def test_lora_lorawan_sx1303_plan_is_linked_from_hardware_mainline_docs() -> None:
    relative_path = "docs/specs/scout-lora-lorawan-sx1303-plan.md"

    assert relative_path in HARDWARE_DIRECTION_DOC.read_text(encoding="utf-8")
    assert relative_path in HARDWARE_PORT_PLAN_DOC.read_text(encoding="utf-8")
