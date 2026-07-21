from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER_SPEC = ROOT / "docs/specs/scout-alpha-mobile-wearable-simulation-sandbox.md"
MASTER_SPEC_NAME = "scout-alpha-mobile-wearable-simulation-sandbox.md"
MASTER_SPEC_REPO_PATH = f"docs/specs/{MASTER_SPEC_NAME}"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_alpha_sandbox_master_spec_is_canonical_and_complete() -> None:
    text = MASTER_SPEC.read_text(encoding="utf-8")

    for heading in (
        "# Scout Alpha Mobile/Wearable Simulation Sandbox",
        "## 1. 文件定位與權責",
        "## 3. 目標部署模型與目前原型",
        "## 5. 功能需求",
        "## 7. Scenario Catalog",
        "## 8. Fault Injection Catalog",
        "## 10. API Contract",
        "## 12. Artifact 與 Provenance Contract",
        "## 13. Safety、Privacy 與 Effect Boundaries",
        "## 16. 驗收標準",
        "## 18. 產品化缺口",
        "## 20. 導覽與來源索引",
    ):
        assert heading in text

    for required_contract in (
        "actual_user_track_available=false",
        "SCOUT_ALPHA_SANDBOX_ENABLED=true",
        "loopback_mqtt_broker",
        "synthetic_direct_feed",
        "candidate_only=true",
        "runtime_safety_truth=false",
        "phase1_l0_l4_state_mutated=false",
        "No real transport or delivery occurred",
        "outputs/sandbox/alpha/last_cli_result.json",
        "scout_alpha_simulation_models.py",
        "scout_alpha_simulation_sandbox.py",
        "scout_local_mqtt_broker_harness.py",
    ):
        assert required_contract in text


def test_existing_alpha_sandbox_surfaces_link_back_to_master_spec() -> None:
    markdown_sources = (
        "docs/specs/scout-runtime-multi-gate-safety-reducer.md",
        "docs/specs/scout-ai-workspace-agent-tool-spec.md",
    )
    html_sources = (
        "docs/emergency/scout-alpha-sandbox-v0.html",
        "docs/emergency/scout-emergency-mobile-approval-v0.html",
    )
    python_sources = (
        "tools/run_scout_alpha_simulation_sandbox.py",
        "tests/test_scout_alpha_simulation_sandbox.py",
        "tests/test_scout_alpha_simulation_ui.py",
        "tests/test_scout_local_mqtt_broker_harness.py",
    )

    for path in markdown_sources:
        assert f"]({MASTER_SPEC_NAME})" in _read(path), path
    for path in html_sources:
        assert f'../specs/{MASTER_SPEC_NAME}' in _read(path), path
    for path in python_sources:
        assert MASTER_SPEC_REPO_PATH in _read(path), path


def test_master_spec_links_to_every_retained_source_surface() -> None:
    text = MASTER_SPEC.read_text(encoding="utf-8")

    for source_path in (
        "scout-runtime-multi-gate-safety-reducer.md",
        "scout-ai-workspace-agent-tool-spec.md",
        "../emergency/scout-alpha-sandbox-v0.html",
        "../emergency/scout-emergency-mobile-approval-v0.html",
        "../../tools/run_scout_alpha_simulation_sandbox.py",
        "../../tests/test_scout_alpha_simulation_sandbox.py",
        "../../tests/test_scout_alpha_simulation_ui.py",
        "../../tests/test_scout_local_mqtt_broker_harness.py",
    ):
        assert source_path in text
