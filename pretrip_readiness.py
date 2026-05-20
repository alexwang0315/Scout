from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ReadinessSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class ReadinessStatus(StrEnum):
    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ReadinessFinding:
    rule_id: str
    severity: ReadinessSeverity
    message: str
    missing_any: tuple[str, ...] = field(default_factory=tuple)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadinessReport:
    status: ReadinessStatus
    findings: tuple[ReadinessFinding, ...]


DEFAULT_SKILL_CONFIG_MANIFEST: dict[str, Any] = {
    "manifest_id": "skill_config_manifest.pretrip_readiness.v0",
    "artifact_kind": "skill_config_manifest",
    "version": "0.1.0",
    "scope": "pretrip_readiness",
    "config": {
        "short_route_max_distance_m": 15000,
        "readiness_rules": [
            {
                "rule_id": "same_day_short_requires_alternate_route",
                "severity": "warning",
                "message": "Same-day short routes should include an alternate route before compile.",
                "match": [
                    {"field": "route_days", "op": "lte", "value": 1},
                    {
                        "field": "distance_m",
                        "op": "lte",
                        "value_from": "short_route_max_distance_m",
                    },
                    {"field": "route_kind", "op": "not_contains", "value": "traverse"},
                ],
                "required_any": ["alternate_route_ref", "alternate_routes"],
            },
            {
                "rule_id": "multiday_or_traverse_requires_alternate_or_retreat_route",
                "severity": "blocker",
                "message": "Multiday or traverse routes require an alternate or retreat route before compile.",
                "match_any": [
                    {"field": "route_days", "op": "gte", "value": 2},
                    {"field": "route_kind", "op": "contains", "value": "traverse"},
                ],
                "required_any": [
                    "alternate_route_ref",
                    "alternate_routes",
                    "retreat_route_ref",
                    "retreat_routes",
                ],
            },
        ],
    },
}


def load_skill_config_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_pretrip_readiness(
    route_plan: dict[str, Any],
    *,
    skill_config_manifest: dict[str, Any] | None = None,
) -> ReadinessReport:
    manifest = skill_config_manifest or DEFAULT_SKILL_CONFIG_MANIFEST
    config = manifest.get("config", manifest)
    findings: list[ReadinessFinding] = []

    for rule in config.get("readiness_rules", []):
        if not _rule_matches(rule, route_plan, config):
            continue

        required_any = tuple(rule.get("required_any", ()))
        if required_any and not any(_has_value(route_plan, field_name) for field_name in required_any):
            findings.append(
                ReadinessFinding(
                    rule_id=rule["rule_id"],
                    severity=ReadinessSeverity(rule["severity"]),
                    message=rule["message"],
                    missing_any=required_any,
                    evidence={
                        "route_days": route_plan.get("route_days"),
                        "distance_m": route_plan.get("distance_m"),
                        "route_kind": route_plan.get("route_kind"),
                    },
                )
            )

    return ReadinessReport(status=_status_for(findings), findings=tuple(findings))


def _rule_matches(rule: dict[str, Any], route_plan: dict[str, Any], config: dict[str, Any]) -> bool:
    all_conditions = rule.get("match", [])
    any_conditions = rule.get("match_any", [])
    return all(_condition_matches(condition, route_plan, config) for condition in all_conditions) and (
        not any_conditions or any(_condition_matches(condition, route_plan, config) for condition in any_conditions)
    )


def _condition_matches(condition: dict[str, Any], route_plan: dict[str, Any], config: dict[str, Any]) -> bool:
    actual = route_plan.get(condition["field"])
    expected = config[condition["value_from"]] if "value_from" in condition else condition.get("value")
    op = condition["op"]

    if op == "eq":
        return actual == expected
    if op == "gte":
        return actual is not None and actual >= expected
    if op == "lte":
        return actual is not None and actual <= expected
    if op == "contains":
        if isinstance(actual, str):
            return expected == actual or expected in actual.split(",")
        return isinstance(actual, list | tuple | set) and expected in actual
    if op == "not_contains":
        if actual is None:
            return True
        if isinstance(actual, str):
            return expected != actual and expected not in actual.split(",")
        return not (isinstance(actual, list | tuple | set) and expected in actual)

    raise ValueError(f"Unsupported readiness condition operator: {op}")


def _has_value(route_plan: dict[str, Any], field_name: str) -> bool:
    value = route_plan.get(field_name)
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _status_for(findings: list[ReadinessFinding]) -> ReadinessStatus:
    if any(finding.severity == ReadinessSeverity.BLOCKER for finding in findings):
        return ReadinessStatus.BLOCKED
    if any(finding.severity == ReadinessSeverity.WARNING for finding in findings):
        return ReadinessStatus.WARNING
    return ReadinessStatus.READY
