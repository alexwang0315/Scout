"""Deterministic permission checks for Scout AI OS MVP."""

from __future__ import annotations

from scout.schemas.capability import (
    CapabilityRisk,
    CapabilitySpec,
    GeneratedCapabilityPackage,
)
from scout.schemas.permissions import PermissionDecision
from scout.schemas.workflow import (
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
            [action.description.lower() for action in workflow.actions]
        )

        deny_reasons: list[str] = []
        if any(term in permission_text for term in DENY_PERMISSION_KEYWORDS):
            deny_reasons.append("workflow requests high-risk permissions")
        if any(term in action_text for term in DENY_ACTION_TERMS):
            deny_reasons.append("workflow describes a high-risk action")

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


__all__ = ["PermissionGate"]
