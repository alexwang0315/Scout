"""Deterministic permission checks for Scout AI OS MVP."""

from __future__ import annotations

from typing import Any

from scout.schemas.capability import (
    CapabilityRisk,
    CapabilitySpec,
    GeneratedCapabilityPackage,
)
from scout.schemas.permissions import PermissionDecision
from scout.schemas.workflow import (
    ActionSpec,
    ActionType,
    TriggerType,
    WorkflowLifecycle,
    WorkflowSpec,
)


APPROVAL_PERMISSION_KEYWORDS = (
    "location",
    "private",
    "email",
    "calendar",
    "file",
    "web",
    "scrape",
    "monitor",
    "generated",
)

DENY_PERMISSION_KEYWORDS = (
    "payment",
    "purchase",
    "delete",
    "destructive",
    "credential",
    "secret",
    "production_db",
    "external_message",
)

APPROVAL_ACTION_TYPES = {
    ActionType.CALL_API,
    ActionType.RUN_SANDBOX_SCRIPT,
}

DENY_ACTION_TERMS = (
    "payment",
    "purchase",
    "delete",
    "destructive",
    "credential",
    "secret",
    "production database",
)


class PermissionGate:
    """Evaluate workflow and capability installation permission decisions."""

    def evaluate_workflow(self, workflow: WorkflowSpec) -> PermissionDecision:
        permission_text = " ".join(workflow.permissions.required).lower()
        action_text = " ".join(
            [
                action.description.lower()
                for action in workflow.actions
                if action.type is not ActionType.UI_ACTION
            ]
        )
        ui_action_decisions = [
            self._evaluate_ui_workflow_action(action)
            for action in workflow.actions
            if action.type is ActionType.UI_ACTION
        ]

        deny_reasons: list[str] = []
        if any(term in permission_text for term in DENY_PERMISSION_KEYWORDS):
            deny_reasons.append("workflow requests high-risk permissions")
        if any(term in action_text for term in DENY_ACTION_TERMS):
            deny_reasons.append("workflow describes a high-risk action")
        deny_reasons.extend(
            f"UI action denied: {decision.reason}"
            for decision in ui_action_decisions
            if not decision.allowed
        )

        if deny_reasons:
            reason = "; ".join(deny_reasons)
            return PermissionDecision(
                allowed=False,
                requires_user_approval=False,
                reason=reason,
                user_message=f"Refused automation: {reason}.",
            )

        approval_reasons: list[str] = []
        if workflow.lifecycle is WorkflowLifecycle.PERMANENT:
            approval_reasons.append("permanent workflow")
        if workflow.trigger.type in {
            TriggerType.LOCATION,
            TriggerType.EMAIL,
            TriggerType.CALENDAR,
            TriggerType.WEB_CHANGE,
            TriggerType.FILE_CHANGE,
        }:
            approval_reasons.append(f"{workflow.trigger.type.value} trigger")
        if any(term in permission_text for term in APPROVAL_PERMISSION_KEYWORDS):
            approval_reasons.append("sensitive permission")
        if any(action.type in APPROVAL_ACTION_TYPES for action in workflow.actions):
            approval_reasons.append("action requires approval")
        approval_reasons.extend(
            decision.reason
            for decision in ui_action_decisions
            if decision.allowed and decision.requires_user_approval
        )
        if workflow.permissions.approval_required:
            approval_reasons.append(workflow.permissions.reason or "workflow requests approval")

        if approval_reasons:
            reason = "; ".join(dict.fromkeys(approval_reasons))
            return PermissionDecision(
                allowed=True,
                requires_user_approval=True,
                reason=reason,
                user_message=f"Approval required before enabling this workflow: {reason}.",
            )

        return PermissionDecision(
            allowed=True,
            requires_user_approval=False,
            reason="low-risk workflow",
            user_message="Workflow is allowed by MVP permission rules.",
        )

    def _evaluate_ui_workflow_action(self, action: ActionSpec) -> PermissionDecision:
        plan = _ui_action_plan_from_action(action)
        if plan is None:
            return PermissionDecision(
                allowed=False,
                requires_user_approval=False,
                reason="ui_action requires ui_action_plan or surface/request_text config",
                user_message=(
                    "Scout AI refused this workflow because its UI action is "
                    "missing a validated action plan."
                ),
            )
        return self.evaluate_ui_action_plan(plan)

    def evaluate_capability_install(
        self,
        package_or_spec: CapabilitySpec | GeneratedCapabilityPackage,
    ) -> PermissionDecision:
        generated = isinstance(package_or_spec, GeneratedCapabilityPackage)
        spec = package_or_spec.spec if generated else package_or_spec

        if spec.risk_level is CapabilityRisk.HIGH:
            return PermissionDecision(
                allowed=False,
                requires_user_approval=False,
                reason="high-risk capability is denied by default",
                user_message="High-risk generated or installed capabilities are denied in the MVP.",
            )

        if generated or spec.risk_level is CapabilityRisk.MEDIUM:
            reason = "generated capability" if generated else "medium-risk capability"
            return PermissionDecision(
                allowed=True,
                requires_user_approval=True,
                reason=reason,
                user_message=f"Approval required before installing this {reason}.",
            )

        return PermissionDecision(
            allowed=True,
            requires_user_approval=False,
            reason="low-risk capability",
            user_message="Capability is allowed by MVP permission rules.",
        )

    def evaluate_ui_action_plan(self, plan: dict[str, Any]) -> PermissionDecision:
        """Evaluate a session-local UI action plan without applying it."""

        status = str(plan.get("status") or "")
        boundary = plan.get("boundary") if isinstance(plan.get("boundary"), dict) else {}
        actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []

        if status == "unsupported":
            reason = str(plan.get("unsupported_reason") or "unsupported UI action")
            return PermissionDecision(
                allowed=False,
                requires_user_approval=False,
                reason=reason,
                user_message=f"UI action is not executable by Scout AI: {reason}.",
            )

        forbidden_boundary_flags = {
            "workspace_file_write_allowed": True,
            "safety_api_called": True,
            "phase1_l0_l4_state_mutated": True,
            "outbound_send_performed": True,
            "hardware_control_performed": True,
            "model_output_is_runtime_truth": True,
        }
        for flag, forbidden_value in forbidden_boundary_flags.items():
            if boundary.get(flag) is forbidden_value:
                return PermissionDecision(
                    allowed=False,
                    requires_user_approval=False,
                    reason=f"UI action violates boundary flag {flag}",
                    user_message=(
                        "Scout AI refused this UI action because it would cross a "
                        f"forbidden boundary: {flag}."
                    ),
                )

        if any(
            bool(action.get("workspace_write_intent"))
            or bool(action.get("requires_confirmation"))
            for action in actions
            if isinstance(action, dict)
        ):
            return PermissionDecision(
                allowed=True,
                requires_user_approval=True,
                reason="workspace write intent requires explicit confirmation",
                user_message=(
                    "This UI action can only be presented as a confirmation-gated "
                    "workspace intent."
                ),
            )

        return PermissionDecision(
            allowed=True,
            requires_user_approval=False,
            reason="session-local UI action",
            user_message="UI action is allowed as session-local state only.",
        )


def _ui_action_plan_from_action(action: ActionSpec) -> dict[str, Any] | None:
    plan = action.config.get("ui_action_plan")
    if isinstance(plan, dict):
        return plan
    if plan is not None:
        return None

    surface = action.config.get("surface")
    if not isinstance(surface, str) or not surface.strip():
        return None

    from scout.ui_action_plan import build_scout_ui_action_plan

    try:
        return build_scout_ui_action_plan(
            surface=surface,
            request_text=_config_string(action.config, "request_text")
            or action.description,
            preset=_config_string(action.config, "preset"),
            target_kind=_config_string(action.config, "target_kind"),
            target_ref=_config_string(action.config, "target_ref"),
            query=_config_string(action.config, "query"),
            tab=_config_string(action.config, "tab"),
        )
    except ValueError:
        return None


def _config_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value if isinstance(value, str) else None


__all__ = ["PermissionGate"]
