from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tests.qualification.contracts import canonical_sha256, file_sha256
from tests.qualification.phase3_catalog import (
    CANONICAL_ROUTE_DISPOSITION,
    DOMAIN_IDS,
    DOMAIN_SPECS,
    PHASE3_DESIGN_CANONICAL_SHA256,
)
from tests.qualification.phase3_contracts import (
    DashboardEntrypoint,
    DashboardExecutableEntrypointManifest,
    Phase3Finding,
)


_STATIC_ROUTE_RE = re.compile(r'data-route="([a-z0-9-]+)"')
_JS_FUNCTION_RE = re.compile(
    r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|"
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=.*?=>\s*\{"
)
_FRONTEND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("frontend_event", re.compile(r"\.addEventListener\s*\(")),
    (
        "frontend_timer",
        re.compile(r"(?:window\.)?(?:setTimeout|setInterval|requestAnimationFrame)\s*\("),
    ),
    (
        "frontend_storage",
        re.compile(r"(?:localStorage|sessionStorage)\.(?:getItem|setItem|removeItem|clear)\s*\("),
    ),
    ("frontend_fetch", re.compile(r"\bfetch\s*\(")),
    (
        "frontend_stream",
        re.compile(r"new\s+(?:WebSocket|EventSource|Worker)\s*\("),
    ),
    ("frontend_message", re.compile(r"\.postMessage\s*\(")),
    (
        "frontend_dynamic_dispatch",
        re.compile(
            r"(?:renderers|handlers|routeRenderers|diagnosticChecks|checks)\s*\[|"
            r"\b[A-Za-z_$][\w$]*\s*\[[A-Za-z_$][\w$]*\]\s*\("
        ),
    ),
)

_BACKEND_ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "websocket"}
_ALLOWED_DISPOSITIONS = {
    "qualified_domain",
    "presentation_only_shell",
    "separate-runtime-diagnostic",
    "evidence_backed_exclusion",
}


@dataclass(frozen=True)
class SurfaceDiscovery:
    routes: tuple[str, ...]
    manifest: DashboardExecutableEntrypointManifest
    findings: tuple[Phase3Finding, ...]
    source_hashes: tuple[tuple[str, str], ...]

    @property
    def identity(self) -> str:
        return canonical_sha256(
            {
                "routes": self.routes,
                "manifest": self.manifest,
                "findings": self.findings,
                "source_hashes": self.source_hashes,
            }
        )


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


def _domain_from_text(value: str) -> tuple[str | None, str]:
    lowered = value.casefold().replace("_", "-")
    if "diagnostic" in lowered:
        return None, "separate-runtime-diagnostic"
    rules: tuple[tuple[tuple[str, ...], str], ...] = (
        (("permission", "mission-baseline"), "contextual-permission"),
        (("body-index", "bodyindex", "wearable"), "body-index-privacy"),
        (("observer", "mqtt", "lorawan", "gnss", "sensorlogger"), "observer-hardware-boundary"),
        (("assistant", "agent", "tool-plan", "skill-router"), "assistant-planner"),
        (("emergency", "living", "safety", "approval", "sandbox"), "safety-emergency"),
        (("weather", "navigation", "terrain", "imagery", "rainfall", "tile", "features-lbs", "map-evidence"), "geospatial-weather-navigation"),
        (("route-context", "routecontext", "architecture", "pace-fit", "pacefit", "briefing"), "route-intelligence"),
        (("workspace", "trip-intake", "import-new-trip", "country-material", "connected-preparation", "prepare-layers", "publication"), "workspace-lifecycle"),
    )
    for tokens, domain in rules:
        if any(token in lowered for token in tokens):
            return domain, "qualified_domain"
    return "dashboard-shell-control", "presentation_only_shell"


def discover_dashboard_routes(html: str) -> tuple[str, ...]:
    return tuple(sorted(set(_STATIC_ROUTE_RE.findall(html))))


def _balanced_brace_delta(line: str) -> int:
    scrubbed = re.sub(r"(['\"]).*?\1", "", line)
    return scrubbed.count("{") - scrubbed.count("}")


def discover_frontend_entrypoints(
    html: str,
    *,
    source_ref: str = "docs/admin/scout-dashboard-v0.1.html",
) -> tuple[tuple[DashboardEntrypoint, ...], tuple[str, ...]]:
    entries: list[DashboardEntrypoint] = []
    unresolved: list[str] = []
    depth = 0
    stack: list[tuple[int, str]] = []
    for line_number, line in enumerate(html.splitlines(), start=1):
        match = _JS_FUNCTION_RE.search(line)
        if match:
            stack.append((depth + max(1, line[: match.end()].count("{")), match.group(1) or match.group(2)))
        symbol = stack[-1][1] if stack else "module-bootstrap"
        context = f"{symbol} {line.strip()}"
        for entrypoint_class, pattern in _FRONTEND_PATTERNS:
            for occurrence, _ in enumerate(pattern.finditer(line), start=1):
                domain, disposition = _domain_from_text(context)
                if disposition == "separate-runtime-diagnostic":
                    domain = None
                target = line.strip()[:240]
                entry_id = (
                    f"frontend:{source_ref}:{line_number}:{entrypoint_class}:{occurrence}"
                )
                entries.append(
                    DashboardEntrypoint(
                        entrypoint_id=entry_id,
                        source_ref=source_ref,
                        line=line_number,
                        symbol=symbol,
                        entrypoint_class=entrypoint_class,
                        registration_site=f"{source_ref}:{line_number}",
                        reachable_target=target,
                        semantic_classification="ui-control-or-read",
                        effect_classification=(
                            "browser-state-or-network"
                            if entrypoint_class
                            in {"frontend_storage", "frontend_fetch", "frontend_stream", "frontend_message"}
                            else "local-ui"
                        ),
                        disposition=disposition,
                        domain_id=domain,
                        exclusion_evidence=(
                            "runtime Diagnostic is retained separately and is not a qualification oracle"
                            if disposition == "separate-runtime-diagnostic"
                            else None
                        ),
                    )
                )
                if entrypoint_class == "frontend_dynamic_dispatch" and domain is None:
                    unresolved.append(entry_id)
        depth += _balanced_brace_delta(line)
        while stack and depth < stack[-1][0]:
            stack.pop()
    return tuple(entries), tuple(sorted(unresolved))


def _constant_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{dynamic}")
        return "".join(parts)
    return None


def _decorator_entrypoint(
    decorator: ast.AST,
) -> tuple[str, str] | None:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    method = decorator.func.attr
    if method in _BACKEND_ROUTE_METHODS:
        path = _constant_string(decorator.args[0]) if decorator.args else None
        return f"backend_{method}", path if path is not None else "<dynamic-route>"
    if method == "middleware":
        middleware_kind = _constant_string(decorator.args[0]) if decorator.args else None
        return "backend_middleware", middleware_kind or "<dynamic-middleware>"
    return None


class _PythonEntrypointVisitor(ast.NodeVisitor):
    def __init__(self, source_ref: str) -> None:
        self.source_ref = source_ref
        self.entries: list[DashboardEntrypoint] = []
        self.class_stack: list[str] = []
        self.unresolved: list[str] = []

    def _add(
        self,
        node: ast.AST,
        symbol: str,
        entrypoint_class: str,
        target: str,
        *,
        semantic: str = "program-control",
        effect: str = "unknown-until-effect-reconciliation",
    ) -> None:
        context = f"{self.source_ref} {symbol} {target}"
        domain, disposition = _domain_from_text(context)
        if disposition == "separate-runtime-diagnostic":
            domain = None
        entry_id = f"backend:{self.source_ref}:{getattr(node, 'lineno', 0)}:{entrypoint_class}:{symbol}"
        self.entries.append(
            DashboardEntrypoint(
                entrypoint_id=entry_id,
                source_ref=self.source_ref,
                line=getattr(node, "lineno", 0),
                symbol=symbol,
                entrypoint_class=entrypoint_class,
                registration_site=f"{self.source_ref}:{getattr(node, 'lineno', 0)}",
                reachable_target=target,
                semantic_classification=semantic,
                effect_classification=effect,
                disposition=disposition,
                domain_id=domain,
                exclusion_evidence=None,
            )
        )
        if "<dynamic" in target:
            self.unresolved.append(entry_id)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = ".".join((*self.class_stack, node.name))
        decorated = False
        for decorator in node.decorator_list:
            item = _decorator_entrypoint(decorator)
            if item:
                decorated = True
                self._add(node, qualified, item[0], item[1])
        lowered = qualified.casefold()
        if node.name == "main":
            self._add(node, qualified, "backend_cli", qualified)
        if self.class_stack and any(token in lowered for token in ("watch", "observer")) and node.name in {"start", "stop", "run", "_run", "_run_loop", "handle_message", "poll"}:
            self._add(node, qualified, "backend_watcher_callback", qualified)
        if any(token in node.name.casefold() for token in ("_run_background", "_schedule_next", "_install_next_timer")):
            self._add(node, qualified, "backend_background_callback", qualified)
        if node.name.startswith(("assess_scout_", "normalize_")) or node.name.endswith("_tool"):
            self._add(node, qualified, "backend_tool", qualified, semantic="candidate-or-normalization-tool")
        if not decorated:
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                name = _call_name(child)
                if name in {"threading.Thread", "Timer", "threading.Timer"}:
                    self._add(child, qualified, "backend_background_registration", name)
                elif name and name.endswith(".add_task"):
                    self._add(child, qualified, "backend_background_registration", name)
                elif name and name.endswith(".on_shutdown.append"):
                    self._add(child, qualified, "backend_lifecycle", name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)


def _call_name(node: ast.Call) -> str | None:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else None


def discover_python_entrypoints(
    path: Path,
    *,
    source_ref: str,
) -> tuple[tuple[DashboardEntrypoint, ...], tuple[str, ...]]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=source_ref)
    visitor = _PythonEntrypointVisitor(source_ref)
    visitor.visit(tree)
    return tuple(visitor.entries), tuple(sorted(set(visitor.unresolved)))


def _source_refs() -> tuple[str, ...]:
    refs = {
        "admin_api.py",
        "assistant_api.py",
        "docs/admin/scout-dashboard-v0.1.html",
        "scout_contextual_permission_workbench_api.py",
        "scout_emergency_mobile_closed_loop_api.py",
    }
    for domain in DOMAIN_SPECS:
        refs.update(domain.production_source_refs)
    return tuple(sorted(refs))


def repository_source_identity(root: Path, refs: Iterable[str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    hashes: list[tuple[str, str]] = []
    for ref in sorted(set(refs)):
        path = root / ref
        if path.is_file():
            hashes.append((ref, file_sha256(path)))
    frozen = tuple(hashes)
    return canonical_sha256(frozen), frozen


def verify_design_packet(root: Path) -> tuple[bool, str]:
    path = root / "docs/evals/dashboard-internal-qualification-phase3-design-rev2.json"
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    embedded = str(payload.pop("content_sha256", ""))
    actual = canonical_sha256(payload)
    return embedded == PHASE3_DESIGN_CANONICAL_SHA256 == actual, actual


def discover_dashboard_surface(
    repository_root: Path,
    *,
    html_override: str | None = None,
) -> SurfaceDiscovery:
    root = Path(repository_root).resolve()
    html_ref = "docs/admin/scout-dashboard-v0.1.html"
    html = html_override if html_override is not None else (root / html_ref).read_text(encoding="utf-8")
    routes = discover_dashboard_routes(html)
    findings: list[Phase3Finding] = []
    expected_routes = tuple(sorted(route for route, _ in CANONICAL_ROUTE_DISPOSITION))
    if routes != expected_routes:
        findings.append(
            _finding(
                "SURFACE-INVENTORY-DRIFT",
                f"Dashboard routes differ from the accepted 22-route inventory: observed={routes!r} expected={expected_routes!r}.",
                requirement="P3D-01",
                evidence=(html_ref,),
            )
        )
    design_ok, design_actual = verify_design_packet(root)
    if not design_ok:
        findings.append(
            _finding(
                "DESIGN-IDENTITY-DRIFT",
                f"Phase 3 design packet identity changed: {design_actual}.",
                requirement="P3D-10",
                evidence=("docs/evals/dashboard-internal-qualification-phase3-design-rev2.json",),
            )
        )

    entries, unresolved = discover_frontend_entrypoints(html, source_ref=html_ref)
    all_entries = list(entries)
    all_unresolved = list(unresolved)
    refs = _source_refs()
    for ref in refs:
        path = root / ref
        if ref == html_ref:
            continue
        if not path.is_file():
            findings.append(
                _finding(
                    "SURFACE-SOURCE-MISSING",
                    f"Declared production source does not exist: {ref}.",
                    requirement="P3D-01",
                    evidence=(ref,),
                )
            )
            continue
        if path.suffix != ".py":
            continue
        discovered, unresolved_python = discover_python_entrypoints(path, source_ref=ref)
        all_entries.extend(discovered)
        all_unresolved.extend(unresolved_python)

    ids = [entry.entrypoint_id for entry in all_entries]
    if len(ids) != len(set(ids)):
        findings.append(
            _finding(
                "SURFACE-INVENTORY-DRIFT",
                "Executable entrypoint discovery produced duplicate identities.",
                requirement="P3D-01",
            )
        )
    invalid_entries = tuple(
        entry.entrypoint_id
        for entry in all_entries
        if entry.disposition not in _ALLOWED_DISPOSITIONS
        or (
            entry.disposition == "qualified_domain"
            and entry.domain_id not in DOMAIN_IDS
        )
        or (
            entry.disposition in {"presentation_only_shell", "qualified_domain"}
            and entry.domain_id is None
        )
    )
    if invalid_entries:
        findings.append(
            _finding(
                "SURFACE-INVENTORY-DRIFT",
                f"Executable entrypoints are not exactly dispositioned: {invalid_entries!r}.",
                requirement="P3D-01",
                evidence=invalid_entries,
            )
        )
    if all_unresolved:
        findings.append(
            _finding(
                "SURFACE-DYNAMIC-DISPATCH-UNRESOLVED",
                f"Dynamic registrations could not be resolved: {tuple(sorted(set(all_unresolved)))!r}.",
                requirement="P3D-01",
                evidence=tuple(sorted(set(all_unresolved))),
            )
        )
    source_identity, source_hashes = repository_source_identity(root, refs)
    manifest = DashboardExecutableEntrypointManifest(
        repository_identity=source_identity,
        roots=(
            html_ref,
            "admin_api.py:create_admin_app",
            "admin_api.py:create_admin_router",
            "assistant_api.py",
            "registered production tools and callbacks",
        ),
        entries=tuple(sorted(all_entries, key=lambda item: item.entrypoint_id)),
        unresolved_dynamic_dispatch=tuple(sorted(set(all_unresolved))),
    )
    return SurfaceDiscovery(
        routes=routes,
        manifest=manifest,
        findings=tuple(sorted(findings, key=lambda item: item.finding_id)),
        source_hashes=source_hashes,
    )


__all__ = [
    "SurfaceDiscovery",
    "discover_dashboard_routes",
    "discover_dashboard_surface",
    "discover_frontend_entrypoints",
    "discover_python_entrypoints",
    "repository_source_identity",
    "verify_design_packet",
]
