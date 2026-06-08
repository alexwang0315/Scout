from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


MODULES = (
    "scout",
    "scout.main",
    "scout.config",
    "scout.ui_action_plan",
    "scout.schemas.workflow",
    "scout.schemas.capability",
    "scout.schemas.learning",
    "scout.schemas.permissions",
    "scout.schemas.runtime",
    "scout.agents.deps",
    "scout.agents.workflow_compiler",
    "scout.agents.execution_planner",
    "scout.agents.code_builder",
    "scout.agents.learner",
    "scout.agents.model_policy",
    "scout.evals.regression",
    "scout.hardware",
    "scout.hardware.ai_os_smoke",
    "scout.cli.hardware_smoke",
    "scout.services.db",
    "scout.services.workflow_store",
    "scout.services.capability_registry",
    "scout.services.application_router",
    "scout.services.memory_store",
    "scout.services.permission_gate",
    "scout.services.sandbox_runner",
    "scout.services.notification_gateway",
    "scout.services.docs_search",
    "scout.runtime.scheduler",
    "scout.runtime.executor",
    "scout.runtime.triggers",
    "scout.runtime.actions",
    "scout.api.routes",
)


def test_phase_1_scaffold_modules_are_importable() -> None:
    for module_name in MODULES:
        importlib.import_module(module_name)


def test_phase_1_fastapi_app_scaffold_exists() -> None:
    from scout.main import app

    assert app.title == "Scout AI OS"


def test_phase_1_docs_and_builtins_exist() -> None:
    expected_paths = [
        "AGENTS.md",
        "pyproject.toml",
        "docs/IMPLEMENTATION_PLAN.md",
        "docs/ARCHITECTURE.md",
        "docs/SECURITY_MODEL.md",
        "docs/API.md",
        "docs/specs/SCOUT_AI_OS_MVP_SPEC.md",
        "src/scout/evals/workflow_router_cases.json",
        "src/scout/capabilities/builtins/manual_notification/capability.yaml",
        "src/scout/capabilities/builtins/time_reminder/capability.yaml",
        "src/scout/capabilities/builtins/json_transform/capability.yaml",
        "src/scout/capabilities/builtins/ui_operation_bridge/capability.yaml",
    ]
    for relative_path in expected_paths:
        assert (ROOT / relative_path).exists(), relative_path
