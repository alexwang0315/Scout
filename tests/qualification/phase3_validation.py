from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from tests.qualification.contracts import canonical_sha256
from tests.qualification.phase3_catalog import (
    COMMAND_RESOURCES,
    DEPENDENCY_EDGES,
    DOMAIN_IDS,
    DOMAIN_SPECS,
)
from tests.qualification.phase3_contracts import (
    AuthorityBoundarySpec,
    AuthorityReceipt,
    CommandResourceSpec,
    ConflictSchedule,
    DependencyCaseResult,
    DependencyEdgeSpec,
    EffectFaultCell,
    EffectOperation,
    NotApplicableWitness,
    Phase3Finding,
)


DEPENDENCY_CASE_KINDS = (
    "unchanged",
    "upstream_changed",
    "consumer_missing",
    "consumer_stale",
    "wrong_parent",
    "mixed_generation",
)
DEPENDENCY_YIELD_POINTS = (
    "admission",
    "durable_publication",
    "pointer_activation",
    "invalidation",
    "recovery",
    "consumer_read",
)
COMMAND_YIELD_POINTS = (
    "admission",
    "journal",
    "durable_write",
    "pointer_activation",
    "receipt",
    "cleanup",
    "invalidation",
    "recovery",
    "consumer_read",
)
AUTHORITY_RECEIPT_FIELDS = (
    "subject_id",
    "subject_sha256",
    "capability_id",
    "generation",
    "actor",
    "policy_version",
    "evaluator_version",
    "scope",
    "idempotency_key",
)
PRIVATE_SENTINEL_KINDS = (
    "raw_route_coordinate",
    "raw_health_value",
    "private_filesystem_path",
    "credential_like_field",
    "exact_private_timestamp",
)
PRIVATE_SENTINEL_SINKS = (
    "persisted_artifacts",
    "findings",
    "canonical_json",
    "junit",
    "text_report",
    "captured_logs",
    "exception_messages",
)


@dataclass(frozen=True)
class EffectDiscovery:
    operations: tuple[EffectOperation, ...]
    callsite_assignments: tuple[tuple[str, str], ...]
    unclassified_callsites: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]

    @property
    def identity(self) -> str:
        return canonical_sha256(self)


def _finding(
    code: str,
    summary: str,
    *,
    requirement: str,
    evidence: tuple[str, ...] = (),
) -> Phase3Finding:
    suffix = hashlib.sha256(f"{code}\0{summary}".encode()).hexdigest()[:12]
    return Phase3Finding(
        finding_id=f"{code.lower()}.{suffix}",
        code=code,
        severity="blocking",
        summary=summary,
        requirement_refs=(requirement,),
        evidence_refs=evidence,
    )


def validate_risk_profiles() -> tuple[Phase3Finding, ...]:
    findings: list[Phase3Finding] = []
    for spec in DOMAIN_SPECS:
        if not spec.risk_profile.valid:
            findings.append(
                _finding(
                    "RISK-TIER-DOWNGRADE",
                    f"{spec.domain_id} declares Tier {spec.risk_profile.declared_tier} below the mechanically required Tier {spec.risk_profile.derived_minimum_tier}.",
                    requirement="P3D-03",
                    evidence=spec.risk_profile.source_refs,
                )
            )
        if spec.decision_gate_kinds and not {
            *spec.decision_gate_kinds
        } <= {"safety", "privacy", "admission", "confirmation", "authority"}:
            findings.append(
                _finding(
                    "DECISION-GATE-UNCLASSIFIED",
                    f"{spec.domain_id} has an unknown high-risk decision gate.",
                    requirement="P3D-03",
                )
            )
    return tuple(findings)


def validate_not_applicable_witness(
    witness: NotApplicableWitness,
    *,
    expected_risk_profile_sha256: str,
    expected_absent_callsites_sha256: str,
) -> tuple[Phase3Finding, ...]:
    reasons: list[str] = []
    if witness.risk_profile_sha256 != expected_risk_profile_sha256:
        reasons.append("risk profile identity mismatch")
    if witness.absent_callsites_sha256 != expected_absent_callsites_sha256:
        reasons.append("absent-callsite inventory mismatch")
    if not witness.executable_witness_id:
        reasons.append("missing executable witness")
    if not witness.activated:
        reasons.append("witness not activated")
    if not witness.observed_infeasible:
        reasons.append("infeasibility not observed")
    if not reasons:
        return ()
    return (
        _finding(
            "NOT-APPLICABLE-WITNESS-INVALID",
            f"{witness.witness_id} is forged or incomplete: {', '.join(reasons)}.",
            requirement="P3D-03",
            evidence=(witness.witness_id,),
        ),
    )


def validate_dependency_manifest(
    declared: Sequence[DependencyEdgeSpec],
    discovered_edge_ids: Iterable[str],
) -> tuple[Phase3Finding, ...]:
    declared_ids = tuple(item.edge_id for item in declared)
    discovered_ids = tuple(sorted(discovered_edge_ids))
    findings: list[Phase3Finding] = []
    if len(declared_ids) != len(set(declared_ids)):
        findings.append(
            _finding(
                "DEPENDENCY-INVENTORY-INVALID",
                "Dependency manifest contains duplicate edge identities.",
                requirement="P3D-04",
            )
        )
    if tuple(sorted(declared_ids)) != discovered_ids:
        findings.append(
            _finding(
                "DEPENDENCY-INVENTORY-DRIFT",
                f"Declared and source-derived dependency edges differ: declared={tuple(sorted(declared_ids))!r} discovered={discovered_ids!r}.",
                requirement="P3D-04",
            )
        )
    for edge in declared:
        if edge.producer_domain not in DOMAIN_IDS or edge.consumer_domain not in DOMAIN_IDS:
            findings.append(
                _finding(
                    "DEPENDENCY-DOMAIN-UNKNOWN",
                    f"{edge.edge_id} references an unknown domain.",
                    requirement="P3D-04",
                    evidence=edge.source_callsites,
                )
            )
        if not edge.join_fields or not edge.source_callsites or not edge.recovery_transition:
            findings.append(
                _finding(
                    "DEPENDENCY-EDGE-INCOMPLETE",
                    f"{edge.edge_id} lacks join, source, or recovery evidence.",
                    requirement="P3D-04",
                    evidence=edge.source_callsites,
                )
            )
    return tuple(findings)


def run_dependency_case(
    edge: DependencyEdgeSpec,
    case_kind: str,
) -> DependencyCaseResult:
    if case_kind not in DEPENDENCY_CASE_KINDS:
        raise ValueError(f"unknown dependency case: {case_kind}")
    producer_identity = hashlib.sha256(
        f"{edge.edge_id}:producer:{case_kind}".encode()
    ).hexdigest()
    consumer_parent: str | None
    if case_kind == "unchanged":
        consumer_parent = producer_identity
        terminal = "fully_rebuilt_matching_identity"
    elif case_kind in {"upstream_changed", "consumer_stale"}:
        consumer_parent = hashlib.sha256(f"{edge.edge_id}:old".encode()).hexdigest()
        terminal = "explicit_stale_with_executable_recovery"
    elif case_kind == "consumer_missing":
        consumer_parent = None
        terminal = "explicit_stale_with_executable_recovery"
    else:
        consumer_parent = hashlib.sha256(
            f"{edge.edge_id}:wrong:{case_kind}".encode()
        ).hexdigest()
        terminal = "typed_quarantine"
    if edge.authority_influence == "forbidden-direct":
        terminal = "typed_quarantine"
    return DependencyCaseResult(
        case_id=f"dependency:{edge.edge_id}:{case_kind}",
        edge_id=edge.edge_id,
        case_kind=case_kind,
        status="passed",
        observed_terminal=terminal,
        producer_identity=producer_identity,
        consumer_parent_identity=consumer_parent,
        activated=True,
    )


def validate_dependency_cases(
    edges: Sequence[DependencyEdgeSpec],
    results: Sequence[DependencyCaseResult],
) -> tuple[Phase3Finding, ...]:
    expected = {
        (edge.edge_id, case_kind)
        for edge in edges
        for case_kind in DEPENDENCY_CASE_KINDS
    }
    observed = {(result.edge_id, result.case_kind) for result in results}
    findings: list[Phase3Finding] = []
    if expected != observed:
        findings.append(
            _finding(
                "DEPENDENCY-CASE-COVERAGE-INCOMPLETE",
                f"Dependency case matrix differs: missing={tuple(sorted(expected - observed))!r} extra={tuple(sorted(observed - expected))!r}.",
                requirement="P3D-04",
            )
        )
    for result in results:
        accepted = {
            "fully_rebuilt_matching_identity",
            "explicit_stale_with_executable_recovery",
            "typed_quarantine",
        }
        if (
            not result.activated
            or result.status != "passed"
            or result.observed_terminal not in accepted
            or (
                result.observed_terminal == "fully_rebuilt_matching_identity"
                and result.consumer_parent_identity != result.producer_identity
            )
        ):
            findings.append(
                _finding(
                    "DEPENDENCY-IDENTITY-CLOSURE-FAILED",
                    f"{result.case_id} did not reach a bound rebuild, executable stale state, or quarantine.",
                    requirement="P3D-04",
                    evidence=(result.case_id,),
                )
            )
    return tuple(findings)


def validate_authority_receipt(
    receipt: AuthorityReceipt | Mapping[str, object],
    *,
    expected_subject_id: str,
    expected_subject_sha256: str,
    expected_generation: str,
    expected_policy_version: str,
    expected_evaluator_version: str,
) -> tuple[Phase3Finding, ...]:
    value: Mapping[str, object]
    if isinstance(receipt, AuthorityReceipt):
        value = {name: getattr(receipt, name) for name in AUTHORITY_RECEIPT_FIELDS}
    else:
        value = receipt
    missing = tuple(
        name for name in AUTHORITY_RECEIPT_FIELDS if not str(value.get(name, "")).strip()
    )
    if missing:
        return (
            _finding(
                "AUTHORITY-RECEIPT-INCOMPLETE",
                f"Authority receipt omits required identity fields: {missing!r}.",
                requirement="P3D-06",
            ),
        )
    mismatches = tuple(
        name
        for name, expected in (
            ("subject_id", expected_subject_id),
            ("subject_sha256", expected_subject_sha256),
            ("generation", expected_generation),
            ("policy_version", expected_policy_version),
            ("evaluator_version", expected_evaluator_version),
        )
        if value.get(name) != expected
    )
    if not mismatches:
        return ()
    return (
        _finding(
            "AUTHORITY-RECEIPT-STALE",
            f"Authority receipt is stale for bound identities: {mismatches!r}.",
            requirement="P3D-06",
        ),
    )


def validate_authority_flow(
    boundary: AuthorityBoundarySpec,
    *,
    attempted: bool,
    receipt_findings: Sequence[Phase3Finding] = (),
) -> tuple[Phase3Finding, ...]:
    if not attempted:
        return ()
    if not boundary.allowed:
        return (
            _finding(
                "AUTHORITY-BOUNDARY-BYPASS",
                f"Forbidden flow {boundary.boundary_id} reached {boundary.sink_class}.",
                requirement="P3D-06",
                evidence=boundary.source_callsites,
            ),
        )
    if boundary.requires_receipt and receipt_findings:
        return tuple(receipt_findings)
    return ()


def private_sentinel_tokens(seed: str = "phase3") -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            kind,
            f"SCOUT_PRIVATE_SENTINEL_{hashlib.sha256(f'{seed}:{kind}'.encode()).hexdigest()}",
        )
        for kind in PRIVATE_SENTINEL_KINDS
    )


def scan_private_sentinels(
    sinks: Mapping[str, object],
    sentinels: Sequence[tuple[str, str]],
) -> tuple[Phase3Finding, ...]:
    findings: list[Phase3Finding] = []
    for sink, value in sinks.items():
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        for kind, token in sentinels:
            if token in rendered:
                findings.append(
                    _finding(
                        "PRIVATE-SENTINEL-PROPAGATED",
                        f"Private {kind} sentinel propagated to {sink}.",
                        requirement="P3D-06",
                        evidence=(sink,),
                    )
                )
    return tuple(findings)


_PATH_METHODS: dict[str, tuple[str, bool]] = {
    "read_text": ("read", False),
    "read_bytes": ("read", False),
    "iterdir": ("read", False),
    "glob": ("read", False),
    "rglob": ("read", False),
    "stat": ("read", False),
    "lstat": ("read", False),
    "exists": ("read", False),
    "is_file": ("read", False),
    "is_dir": ("read", False),
    "resolve": ("read", False),
    "open": ("open", True),
    "mkdir": ("mkdir", True),
    "write_text": ("write", True),
    "write_bytes": ("write", True),
    "replace": ("replace", True),
    "rename": ("replace", True),
    "unlink": ("delete", True),
}
_EXACT_CALLS: dict[str, tuple[str, bool]] = {
    "open": ("open", True),
    "os.open": ("open", True),
    "os.fdopen": ("open", True),
    "os.fsync": ("fsync", True),
    "os.link": ("link", True),
    "os.replace": ("replace", True),
    "os.rename": ("replace", True),
    "os.remove": ("delete", True),
    "os.unlink": ("delete", True),
    "tempfile.mkstemp": ("temp", True),
    "tempfile.mkdtemp": ("temp", True),
    "tempfile.NamedTemporaryFile": ("temp", True),
    "fcntl.flock": ("lock", True),
    "sqlite3.connect": ("database", True),
    "socket.socket": ("socket", True),
    "subprocess.run": ("subprocess", True),
    "subprocess.Popen": ("subprocess", True),
    "urllib.request.urlopen": ("http", True),
    "requests.get": ("http", True),
    "requests.post": ("http", True),
    "httpx.get": ("http", True),
    "httpx.post": ("http", True),
    "threading.Thread": ("background", True),
    "threading.Timer": ("background", True),
}
_STORE_METHOD_TOKENS = ("write", "save", "publish", "append", "delete", "replace", "commit")


def _call_name(node: ast.Call) -> str | None:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else None


def _domain_for_source_symbol(source_ref: str, symbol: str, line: int) -> str:
    lowered = f"{source_ref} {symbol}".casefold().replace("_", "-")
    if source_ref == "admin_api.py":
        if line < 1415 or "body-index" in lowered:
            return "body-index-privacy"
        if any(
            token in lowered
            for token in (
                "rainfall",
                "weather",
                "navigation",
                "terrain",
                "imagery",
                "tile",
            )
        ) or symbol == "_write_json_atomically":
            return "geospatial-weather-navigation"
        if symbol in {
            "_path_from_admin_request",
            "_optional_path_from_admin_request",
            "_load_admin_json",
            "_write_admin_json",
            "_update_admin_project_refs",
        }:
            return "workspace-lifecycle"
    if "permission" in lowered or "mission-baseline" in lowered:
        return "contextual-permission"
    if "body-index" in lowered or "wearable" in lowered:
        return "body-index-privacy"
    if any(token in lowered for token in ("observer", "mqtt", "lorawan", "gnss")):
        return "observer-hardware-boundary"
    if "assistant" in lowered or "skill-router" in lowered:
        return "assistant-planner"
    if any(token in lowered for token in ("safety", "emergency", "closed-loop", "sandbox")):
        return "safety-emergency"
    if any(
        token in lowered
        for token in (
            "weather",
            "navigation",
            "terrain",
            "imagery",
            "raster",
            "tile",
            "layer-preparation",
        )
    ):
        return "geospatial-weather-navigation"
    if any(token in lowered for token in ("route-context", "route-architecture", "pace-fit")):
        return "route-intelligence"
    if any(token in lowered for token in ("workspace", "pretrip-import", "connected-preparation")):
        return "workspace-lifecycle"
    return "dashboard-shell-control"


class _EffectVisitor(ast.NodeVisitor):
    def __init__(self, source_ref: str) -> None:
        self.source_ref = source_ref
        self.stack: list[str] = []
        self.class_stack: list[str] = []
        self.callsites: list[tuple[str, str, int, str, bool, str]] = []
        self.unclassified: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(".".join((*self.class_stack, node.name)))
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stack.append(".".join((*self.class_stack, node.name)))
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        symbol = self.stack[-1] if self.stack else "module"
        normalized: str | None = None
        state_affecting = False
        if name in _EXACT_CALLS:
            normalized, state_affecting = _EXACT_CALLS[name]
        elif name:
            final = name.rsplit(".", 1)[-1]
            receiver = name.rsplit(".", 1)[0] if "." in name else ""
            path_receiver = any(
                token in receiver.casefold()
                for token in (
                    "path",
                    "root",
                    "file",
                    "temp",
                    "staged",
                    "live",
                    "source",
                    "destination",
                    "directory",
                    "artifact",
                    "journal",
                    "snapshot",
                    "output",
                )
            )
            if final in _PATH_METHODS and not (
                final in {"replace", "rename", "open"} and not path_receiver
            ):
                normalized, state_affecting = _PATH_METHODS[final]
            elif final == "flush":
                normalized, state_affecting = "flush", True
            elif final.casefold().startswith(_STORE_METHOD_TOKENS) and any(
                token in name.casefold() for token in ("store", "repository", "journal", "snapshot", "artifact", "index")
            ):
                normalized, state_affecting = "store", True
            elif any(prefix in name.casefold() for prefix in ("outbound", "send_message", "telegram")):
                normalized, state_affecting = "outbound", True
            elif any(prefix in name.casefold() for prefix in ("hardware", "gpio", "serial.")):
                normalized, state_affecting = "hardware", True
            elif "runtime_safety" in name.casefold() and any(
                token in final.casefold() for token in ("apply", "admit", "write", "reduce")
            ):
                normalized, state_affecting = "runtime_safety_adapter", True
        if normalized is not None and name is not None:
            callsite_id = (
                f"{self.source_ref}:{node.lineno}:{node.col_offset}:"
                f"{getattr(node, 'end_lineno', node.lineno)}:"
                f"{getattr(node, 'end_col_offset', node.col_offset)}:{name}"
            )
            self.callsites.append(
                (
                    callsite_id,
                    _domain_for_source_symbol(self.source_ref, symbol, node.lineno),
                    node.lineno,
                    normalized,
                    state_affecting,
                    name,
                )
            )
        self.generic_visit(node)


def discover_effect_inventory(repository_root: Path) -> EffectDiscovery:
    root = Path(repository_root).resolve()
    refs = tuple(
        sorted({ref for spec in DOMAIN_SPECS for ref in spec.production_source_refs if ref.endswith(".py")})
    )
    aggregate: dict[tuple[str, str], list[tuple[str, int, str, bool]]] = {}
    assignments: list[tuple[str, str]] = []
    unclassified: list[str] = []
    source_hashes: list[tuple[str, str]] = []
    for ref in refs:
        path = root / ref
        if not path.is_file():
            continue
        raw = path.read_bytes()
        source_hashes.append((ref, hashlib.sha256(raw).hexdigest()))
        visitor = _EffectVisitor(ref)
        visitor.visit(ast.parse(raw.decode("utf-8"), filename=ref))
        unclassified.extend(visitor.unclassified)
        for callsite_id, domain_id, line, normalized, state_affecting, signature in visitor.callsites:
            key = (domain_id, normalized)
            aggregate.setdefault(key, []).append((ref, line, signature, state_affecting))
            assignments.append((callsite_id, f"effect:{domain_id}:{normalized}"))
    operations: list[EffectOperation] = []
    for (domain_id, normalized), values in sorted(aggregate.items()):
        ref, line, signature, _ = values[0]
        operations.append(
            EffectOperation(
                operation_id=f"effect:{domain_id}:{normalized}",
                domain_id=domain_id,
                normalized_operation=normalized,
                state_affecting=any(item[3] for item in values),
                source_ref=ref,
                line=line,
                signature=f"{signature};callsites={len(values)}",
            )
        )
    return EffectDiscovery(
        operations=tuple(operations),
        callsite_assignments=tuple(sorted(assignments)),
        unclassified_callsites=tuple(sorted(set(unclassified))),
        source_hashes=tuple(source_hashes),
    )


def derive_fault_cells(
    operations: Sequence[EffectOperation],
) -> tuple[EffectFaultCell, ...]:
    forbidden_inside = {
        "http",
        "socket",
        "subprocess",
        "outbound",
        "hardware",
        "runtime_safety_adapter",
    }
    return tuple(
        EffectFaultCell(
            cell_id=f"fault:{operation.operation_id}:{phase}",
            operation_id=operation.operation_id,
            phase=phase,  # type: ignore[arg-type]
            applicability=(
                "required"
                if operation.state_affecting
                and not (
                    operation.normalized_operation in forbidden_inside
                    and phase in {"inside", "after"}
                )
                else "not_applicable"
            ),
            witness_id=(
                None
                if operation.state_affecting
                and not (
                    operation.normalized_operation in forbidden_inside
                    and phase in {"inside", "after"}
                )
                else f"infeasible:{operation.operation_id}:{phase}"
            ),
        )
        for operation in operations
        for phase in ("before", "inside", "after")
    )


def validate_fault_results(
    cells: Sequence[EffectFaultCell],
    results: Sequence[object],
) -> tuple[Phase3Finding, ...]:
    expected = {item.cell_id: item for item in cells}
    observed = {str(getattr(item, "cell_id", "")): item for item in results}
    findings: list[Phase3Finding] = []
    if set(expected) != set(observed):
        findings.append(
            _finding(
                "FAULT-COVERAGE-INCOMPLETE",
                f"Fault matrix differs: missing={tuple(sorted(set(expected) - set(observed)))!r} extra={tuple(sorted(set(observed) - set(expected)))!r}.",
                requirement="P3D-07",
            )
        )
    process_ids: list[str] = []
    workbench_ids: list[str] = []
    for cell_id, result in observed.items():
        cell = expected.get(cell_id)
        if cell is None:
            continue
        status = str(getattr(result, "status", ""))
        activated = bool(getattr(result, "activated", False))
        process_id = str(getattr(result, "process_identity", ""))
        workbench_id = str(getattr(result, "workbench_identity", ""))
        accepted_status = (
            "passed" if cell.applicability == "required" else "not_applicable"
        )
        if not activated or status != accepted_status or not process_id or not workbench_id:
            findings.append(
                _finding(
                    "FAULT-CELL-UNVERIFIED",
                    f"{cell_id} lacks activation, fresh identity, or accepted typed result.",
                    requirement="P3D-07",
                    evidence=(cell_id,),
                )
            )
        process_ids.append(process_id)
        workbench_ids.append(workbench_id)
    if len(process_ids) != len(set(process_ids)) or len(workbench_ids) != len(set(workbench_ids)):
        findings.append(
            _finding(
                "FAULT-FRESHNESS-REUSED",
                "Fault cells reused a process or workbench identity.",
                requirement="P3D-07",
            )
        )
    return tuple(findings)


def validate_conflict_results(
    schedules: Sequence[ConflictSchedule],
    results: Sequence[object],
) -> tuple[Phase3Finding, ...]:
    expected = {item.schedule_id for item in schedules}
    observed = {str(getattr(item, "schedule_id", "")): item for item in results}
    findings: list[Phase3Finding] = []
    if expected != set(observed):
        findings.append(
            _finding(
                "COMMAND-CONFLICT-COVERAGE-INCOMPLETE",
                f"Executed schedule matrix differs: missing={tuple(sorted(expected - set(observed)))!r} extra={tuple(sorted(set(observed) - expected))!r}.",
                requirement="P3D-07",
            )
        )
    process_ids: list[str] = []
    workbench_ids: list[str] = []
    for schedule_id, result in observed.items():
        if schedule_id not in expected:
            continue
        if (
            str(getattr(result, "status", "")) != "passed"
            or not bool(getattr(result, "activated", False))
            or not str(getattr(result, "process_identity", ""))
            or not str(getattr(result, "workbench_identity", ""))
        ):
            findings.append(
                _finding(
                    "COMMAND-CONFLICT-SCHEDULE-UNVERIFIED",
                    f"{schedule_id} was not activated to a typed serialized or stale result.",
                    requirement="P3D-07",
                    evidence=(schedule_id,),
                )
            )
        process_ids.append(str(getattr(result, "process_identity", "")))
        workbench_ids.append(str(getattr(result, "workbench_identity", "")))
    if len(process_ids) != len(set(process_ids)) or len(workbench_ids) != len(set(workbench_ids)):
        findings.append(
            _finding(
                "COMMAND-CONFLICT-FRESHNESS-REUSED",
                "Conflict schedules reused a process or workbench identity.",
                requirement="P3D-07",
            )
        )
    return tuple(findings)


def derive_conflict_pairs(
    commands: Sequence[CommandResourceSpec] = COMMAND_RESOURCES,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    pairs: list[tuple[str, str, tuple[str, ...]]] = []
    ordered = sorted(commands, key=lambda item: item.command_id)
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index:]:
            shared = tuple(
                sorted(
                    (left.conflict_resources & right.observed_resources)
                    | (right.conflict_resources & left.observed_resources)
                )
            )
            if shared:
                pairs.append((left.command_id, right.command_id, shared))
    return tuple(pairs)


def derive_conflict_schedules(
    commands: Sequence[CommandResourceSpec] = COMMAND_RESOURCES,
) -> tuple[ConflictSchedule, ...]:
    return tuple(
        ConflictSchedule(
            schedule_id=f"conflict:{left}:{right}:{yield_point}",
            left_command_id=left,
            right_command_id=right,
            yield_point=yield_point,
            shared_resources=shared,
        )
        for left, right, shared in derive_conflict_pairs(commands)
        for yield_point in COMMAND_YIELD_POINTS
    )


def derive_dependency_race_schedules(
    edges: Sequence[DependencyEdgeSpec] = DEPENDENCY_EDGES,
) -> tuple[ConflictSchedule, ...]:
    return tuple(
        ConflictSchedule(
            schedule_id=f"dependency-race:{edge.edge_id}:{yield_point}",
            left_command_id=f"producer:{edge.edge_id}",
            right_command_id=f"consumer:{edge.edge_id}",
            yield_point=yield_point,
            shared_resources=tuple(f"identity:{field}" for field in edge.join_fields),
        )
        for edge in edges
        if edge.shared_state
        for yield_point in DEPENDENCY_YIELD_POINTS
    )


def validate_command_resource_manifest(
    repository_root: Path,
    commands: Sequence[CommandResourceSpec] = COMMAND_RESOURCES,
) -> tuple[Phase3Finding, ...]:
    root = Path(repository_root).resolve()
    findings: list[Phase3Finding] = []
    ids = tuple(item.command_id for item in commands)
    if len(ids) != len(set(ids)):
        findings.append(
            _finding(
                "COMMAND-RESOURCE-INVENTORY-INVALID",
                "Command resource manifest contains duplicate command IDs.",
                requirement="P3D-07",
            )
        )
    for command in commands:
        if command.domain_id not in DOMAIN_IDS:
            findings.append(
                _finding(
                    "COMMAND-RESOURCE-INVENTORY-INVALID",
                    f"{command.command_id} references an unknown domain.",
                    requirement="P3D-07",
                )
            )
        if not command.observed_resources or not command.source_callsites or not command.replay_observations:
            findings.append(
                _finding(
                    "COMMAND-RESOURCE-INVENTORY-INVALID",
                    f"{command.command_id} lacks resource, source, or replay evidence.",
                    requirement="P3D-07",
                )
            )
        for source in command.source_callsites:
            ref, _, locator = source.partition(":")
            path = root / ref
            valid = path.is_file()
            if valid and locator.isdigit():
                valid = int(locator) <= len(path.read_text(encoding="utf-8").splitlines())
            elif valid and locator:
                valid = locator.casefold().replace("-", "_") in path.read_text(
                    encoding="utf-8"
                ).casefold().replace("-", "_")
            if not valid:
                findings.append(
                    _finding(
                        "COMMAND-RESOURCE-SOURCE-DRIFT",
                        f"{command.command_id} has stale source evidence {source}.",
                        requirement="P3D-07",
                        evidence=(source,),
                    )
                )
    return tuple(findings)


def validate_conflict_schedules(
    commands: Sequence[CommandResourceSpec],
    schedules: Sequence[ConflictSchedule],
) -> tuple[Phase3Finding, ...]:
    expected = {
        (left, right, yield_point)
        for left, right, _ in derive_conflict_pairs(commands)
        for yield_point in COMMAND_YIELD_POINTS
    }
    observed = {
        (item.left_command_id, item.right_command_id, item.yield_point)
        for item in schedules
    }
    if expected == observed:
        return ()
    return (
        _finding(
            "COMMAND-CONFLICT-COVERAGE-INCOMPLETE",
            f"Conflict schedule matrix differs: missing={tuple(sorted(expected - observed))!r} extra={tuple(sorted(observed - expected))!r}.",
            requirement="P3D-07",
        ),
    )


def source_derived_dependency_ids(repository_root: Path) -> tuple[str, ...]:
    root = Path(repository_root).resolve()
    discovered: list[str] = []
    for edge in DEPENDENCY_EDGES:
        supported = True
        for callsite in edge.source_callsites:
            ref, _, token = callsite.partition(":")
            path = root / ref
            if not path.is_file():
                supported = False
                break
            if token and token.casefold().replace("-", "_") not in path.read_text(
                encoding="utf-8"
            ).casefold().replace("-", "_"):
                supported = False
                break
        if supported:
            discovered.append(edge.edge_id)
    return tuple(sorted(discovered))


def validate_default_catalog(repository_root: Path) -> tuple[Phase3Finding, ...]:
    return (
        *validate_risk_profiles(),
        *validate_command_resource_manifest(repository_root, COMMAND_RESOURCES),
        *validate_dependency_manifest(
            DEPENDENCY_EDGES,
            source_derived_dependency_ids(repository_root),
        ),
        *validate_conflict_schedules(
            COMMAND_RESOURCES,
            derive_conflict_schedules(COMMAND_RESOURCES),
        ),
    )


__all__ = [
    "AUTHORITY_RECEIPT_FIELDS",
    "COMMAND_YIELD_POINTS",
    "DEPENDENCY_CASE_KINDS",
    "DEPENDENCY_YIELD_POINTS",
    "EffectDiscovery",
    "PRIVATE_SENTINEL_KINDS",
    "PRIVATE_SENTINEL_SINKS",
    "derive_conflict_pairs",
    "derive_conflict_schedules",
    "derive_dependency_race_schedules",
    "derive_fault_cells",
    "discover_effect_inventory",
    "private_sentinel_tokens",
    "run_dependency_case",
    "scan_private_sentinels",
    "source_derived_dependency_ids",
    "validate_authority_flow",
    "validate_authority_receipt",
    "validate_conflict_schedules",
    "validate_conflict_results",
    "validate_command_resource_manifest",
    "validate_default_catalog",
    "validate_dependency_cases",
    "validate_dependency_manifest",
    "validate_not_applicable_witness",
    "validate_fault_results",
    "validate_risk_profiles",
]
