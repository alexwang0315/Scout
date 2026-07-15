"""Deterministic activation policy and optional runtime detection for L5."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
import json
import os
from pathlib import Path
import site
from typing import Any

from scout.schemas.l5_code_mode import (
    L5ActivationDecision,
    L5ActivationRequest,
    L5ActivationState,
    L5RuntimeStatus,
    L5SafetyLevel,
)

L5_CODE_MODE_MAX_RETRIES = 10


_SAFETY_RANK = {
    L5SafetyLevel.NORMAL: 0,
    L5SafetyLevel.WATCH: 1,
    L5SafetyLevel.CONCERN: 2,
    L5SafetyLevel.DISTRESS: 3,
    L5SafetyLevel.EMERGENCY: 4,
}
_UNDER_CONSTRUCTION_ENV = "SCOUT_L5_CODE_MODE_UNDER_CONSTRUCTION"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
L5_HARNESS_VERSION = "0.7.0"
L5_MONTY_VERSION = "0.0.18"


class L5CodeModeRuntimeUnavailable(RuntimeError):
    """Raised instead of silently escaping to host execution."""


class L5CodeModePolicy:
    """Keep development enablement separate from production activation."""

    def __init__(
        self,
        *,
        minimum_information_value: float = 0.5,
        under_construction: bool | None = None,
    ) -> None:
        if not 0.0 <= minimum_information_value <= 1.0:
            raise ValueError("minimum_information_value must be between 0 and 1")
        self.minimum_information_value = minimum_information_value
        self.under_construction = resolve_l5_under_construction(
            explicit=under_construction
        )

    def evaluate(self, request: L5ActivationRequest) -> L5ActivationDecision:
        if request.under_construction or self.under_construction:
            return L5ActivationDecision(
                l5_code_mode=True,
                state=L5ActivationState.ENABLED_UNDER_CONSTRUCTION,
                reason=(
                    "L5 Code Mode is explicitly available while under construction; "
                    "agents must not block development by applying the production gate."
                ),
            )

        blockers = self._production_blockers(request)
        if blockers:
            return L5ActivationDecision(
                l5_code_mode=False,
                state=L5ActivationState.BLOCKED,
                reason="Production L5 prerequisites are incomplete.",
                blockers=blockers,
            )

        return L5ActivationDecision(
            l5_code_mode=True,
            state=L5ActivationState.ENABLED_SYSTEM,
            reason=(
                "The deterministic system assessment found L3+ risk, a critical "
                "capability gap, sandbox availability, sufficient resources, and "
                "enough expected information value."
            ),
        )

    def _production_blockers(self, request: L5ActivationRequest) -> list[str]:
        blockers: list[str] = []
        if not request.system_assessment:
            blockers.append("system_assessment_required")
        if _SAFETY_RANK[request.safety_level] < 3:
            blockers.append("minimum_safety_level_l3_required")
        if not request.critical_capability_gap:
            blockers.append("critical_capability_gap_required")
        if not request.sandbox_available:
            blockers.append("sandbox_required")
        if not request.resource_budget_available:
            blockers.append("resource_budget_required")
        if request.expected_information_value < self.minimum_information_value:
            blockers.append("information_value_below_threshold")
        return blockers


def detect_l5_code_mode_runtime() -> L5RuntimeStatus:
    """Attest the pinned Harness runtime without executing model-authored code."""

    harness_spec = find_spec("pydantic_ai_harness")
    monty_spec = find_spec("pydantic_monty")
    harness_available = harness_spec is not None
    monty_available = monty_spec is not None
    missing = [
        name
        for name, available in (
            ("pydantic_ai_harness", harness_available),
            ("pydantic_monty", monty_available),
        )
        if not available
    ]
    if missing:
        return _unavailable_runtime(
            f"Optional L5 runtime dependencies are missing: {', '.join(missing)}."
        )
    try:
        harness_version = version("pydantic-ai-harness")
        monty_version = version("pydantic-monty")
    except PackageNotFoundError as exc:
        return _unavailable_runtime(f"L5 runtime package metadata is missing: {exc.name}.")
    if (
        harness_version != L5_HARNESS_VERSION
        or monty_version != L5_MONTY_VERSION
    ):
        return _unavailable_runtime(
            "L5 runtime versions do not match the reviewed pins.",
            harness_version=harness_version,
            monty_version=monty_version,
        )
    if not _runtime_origin_attested(harness_spec) or not _runtime_origin_attested(
        monty_spec
    ):
        return _unavailable_runtime(
            "L5 runtime module origin is outside an installed site-packages directory.",
            harness_version=harness_version,
            monty_version=monty_version,
        )
    try:
        from pydantic_ai_harness import CodeMode  # noqa: F401
        from pydantic_monty import MountDir  # noqa: F401
    except (ImportError, OSError) as exc:
        return _unavailable_runtime(
            f"Pinned L5 runtime import failed: {type(exc).__name__}.",
            harness_version=harness_version,
            monty_version=monty_version,
        )
    return L5RuntimeStatus(
        available=True,
        reason="Pinned Pydantic AI Harness and Monty runtime attestation passed.",
        harness_version=harness_version,
        monty_version=monty_version,
        runtime_attested=True,
    )


def _unavailable_runtime(
    reason: str,
    *,
    harness_version: str | None = None,
    monty_version: str | None = None,
) -> L5RuntimeStatus:
    return L5RuntimeStatus(
        available=False,
        reason=reason,
        install_hint=(
            f'Install the reviewed "pydantic-ai-harness[codemode]=={L5_HARNESS_VERSION}" '
            "optional runtime."
        ),
        stop_condition=(
            "Do not fall back to host Python or shell execution when the sandbox "
            "runtime is unavailable."
        ),
        harness_version=harness_version,
        monty_version=monty_version,
    )


def _runtime_origin_attested(spec: Any) -> bool:
    origin = getattr(spec, "origin", None)
    if not isinstance(origin, str) or not origin:
        return False
    try:
        resolved = Path(origin).resolve()
        site_roots = [Path(item).resolve() for item in site.getsitepackages()]
    except (OSError, RuntimeError):
        return False
    return any(resolved.is_relative_to(root) for root in site_roots)


def resolve_l5_under_construction(
    *,
    explicit: bool | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Resolve the development override without changing production defaults."""

    if explicit is not None:
        return explicit
    values = os.environ if environ is None else environ
    return values.get(_UNDER_CONSTRUCTION_ENV, "").strip().casefold() in _TRUE_VALUES


def build_l5_code_mode_capability(
    *,
    project_root: Path,
    workspace_root: Path,
    activation_request: L5ActivationRequest,
    policy: L5CodeModePolicy | None = None,
) -> Any:
    """Construct the official read-only CodeMode capability when installed.

    This adapter deliberately has no host-Python fallback. L5 eligibility and
    runtime availability are separate so development cannot be policy-blocked
    while an unavailable sandbox still fails closed at execution time.
    """

    decision = (policy or L5CodeModePolicy()).evaluate(activation_request)
    if not decision.l5_code_mode:
        raise PermissionError("L5 Code Mode activation decision is blocked")
    validate_l5_project_root(
        project_root=project_root,
        workspace_root=workspace_root,
    )
    status = detect_l5_code_mode_runtime()
    if not status.available:
        raise L5CodeModeRuntimeUnavailable(
            f"{status.reason} {status.stop_condition} {status.install_hint}"
        )

    from pydantic_ai_harness import CodeMode
    return CodeMode(
        tools=["query_scout_workspace"],
        mount=None,
        max_retries=L5_CODE_MODE_MAX_RETRIES,
    )


def validate_l5_project_root(
    *,
    project_root: Path,
    workspace_root: Path,
) -> Path:
    """Confine L5 to one manifest project below the configured workspace root."""

    try:
        workspace = workspace_root.expanduser().resolve(strict=True)
        project = project_root.expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise ValueError("L5 workspace or project root is unavailable") from exc
    if project == workspace or not project.is_relative_to(workspace):
        raise ValueError("L5 project root is outside configured workspace")
    manifest_path = project / "project.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("L5 project root requires a regular project.json manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("L5 project manifest is unreadable") from exc
    project_id = manifest.get("project_id") if isinstance(manifest, dict) else None
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("L5 project manifest requires project_id")
    if project_id.strip() != project.name:
        raise ValueError("L5 project manifest identity does not match directory")
    return project


__all__ = [
    "L5CodeModePolicy",
    "L5CodeModeRuntimeUnavailable",
    "L5_HARNESS_VERSION",
    "L5_MONTY_VERSION",
    "build_l5_code_mode_capability",
    "detect_l5_code_mode_runtime",
    "resolve_l5_under_construction",
    "validate_l5_project_root",
]
