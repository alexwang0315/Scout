from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from tests.qualification.contracts import canonical_sha256
from tests.qualification.effects import EffectAudit
from tests.qualification.phase3_catalog import CANONICAL_ROUTE_DISPOSITION, DOMAIN_SPECS
from tests.qualification.phase3_discovery import discover_dashboard_surface, verify_design_packet
from tests.qualification.phase3_telemetry import READ_TELEMETRY_CONTRACTS

ROOT = Path(__file__).resolve().parents[2]


def test_route_addendum_retains_historical_packet_and_all_original_dispositions() -> None:
    historical = json.loads((ROOT / "docs/evals/dashboard-internal-qualification-phase3-design-rev2.json").read_text())
    original = tuple(tuple(row) for row in historical["canonical_route_disposition"])
    assert len(original) == 22 and verify_design_packet(ROOT)[0]
    assert CANONICAL_ROUTE_DISPOSITION[:22] == original
    assert CANONICAL_ROUTE_DISPOSITION[22:] == (
        ("runtime-audit", "dashboard-shell-control"),
        ("surface-intelligence", "assistant-planner"),
        ("scout-monitor", "observer-hardware-boundary"),
        ("trip-notebook", "workspace-lifecycle"),
    )
    assert len(set(CANONICAL_ROUTE_DISPOSITION)) == 26


def test_new_telemetry_routes_have_full_declared_domain_obligations() -> None:
    domains = {domain.domain_id: domain for domain in DOMAIN_SPECS}
    assert len(domains) == 9
    for contract in READ_TELEMETRY_CONTRACTS:
        domain = domains[contract.domain_id]
        assert contract.route in domain.ui_routes
        assert set(contract.api_routes) <= set(domain.api_route_prefixes)
        assert set(contract.sources) <= set(domain.production_source_refs)
        for field in ("persisted_capabilities", "observation_fields", "transitions", "terminals", "recovery_transitions"):
            assert getattr(contract, field)
            assert set(getattr(contract, field)) <= set(getattr(domain, field))
        assert set(contract.start_states) <= set(domain.supported_start_states)
        assert len(contract.replay_nodes) == len(set(contract.replay_nodes))
        assert all((ROOT / ref).is_file() for ref in contract.sources)
        assert domain.risk_profile.valid
        assert domain.risk_profile.declared_tier <= 1


def test_discovery_includes_telemetry_readers_routers_and_embedded_controls() -> None:
    discovered = discover_dashboard_surface(ROOT)
    assert not discovered.findings
    counts = Counter(entry.source_ref for entry in discovered.manifest.entries)
    for ref in (
        "runtime_audit_api.py",
        "src/scout/nextgen/dashboard_telemetry_api.py",
        "tools/hardware_monitor_proxy.py",
        "docs/admin/scout-intelligence-telemetry.html",
        "tools/scout_hardware_monitor.html",
    ):
        assert counts[ref] > 0, ref
    assert len({entry.entrypoint_id for entry in discovered.manifest.entries}) == len(discovered.manifest.entries)


def test_duplicate_sidebar_route_cannot_be_hidden_by_unique_route_set() -> None:
    html = (ROOT / "docs/admin/scout-dashboard-v0.1.html").read_text()
    duplicate = '<button class="nav-item" data-route="home">duplicate</button>'
    result = discover_dashboard_surface(ROOT, html_override=html.replace("</aside>", duplicate + "</aside>", 1))
    assert any(
        finding.code == "SURFACE-INVENTORY-DRIFT" and "duplicates=('home',)" in finding.summary
        for finding in result.findings
    )


def test_default_effect_audit_still_rejects_any_sqlite_connection(tmp_path: Path) -> None:
    import sqlite3
    with EffectAudit(transition_id="read-telemetry.default-deny", roots=(("execution", tmp_path),)) as audit:
        with pytest.raises(PermissionError, match="external_store_database"):
            sqlite3.connect(":memory:")
    assert audit.attempts[-1].outcome == "blocked_before_invocation"


def test_addendum_binds_history_approved_routes_and_exact_fixture_boundary() -> None:
    addendum = json.loads((ROOT / "docs/evals/dashboard-phase3-route-coverage-addendum-20260914.json").read_text())
    historical = json.loads((ROOT / addendum["historical_design"]["path"]).read_text())
    embedded = historical.pop("content_sha256")
    assert canonical_sha256(historical) == embedded == addendum["historical_design"]["canonical_sha256"]
    assert tuple(tuple(row) for row in addendum["canonical_route_disposition"]) == CANONICAL_ROUTE_DISPOSITION
    assert addendum["user_arbitration"]["check_id"] == "DASH-002"
    assert addendum["user_arbitration"]["decision"] == "依建議更新 D002"
    assert addendum["current_route_inventory_arbitration"]["choice"] == "A"
    assert addendum["current_route_inventory_arbitration"]["route_count"] == 26
    assert addendum["domain_count"] == 9
    contracts = {item["route"]: item for item in addendum["new_route_contracts"]}
    for contract in READ_TELEMETRY_CONTRACTS:
        assert tuple(contracts[contract.route]["replay_nodes"]) == contract.replay_nodes
        assert tuple(contracts[contract.route]["synthetic_loopback_primitives"]) == contract.synthetic_loopback_primitives
    assert addendum["validation_boundary"]["official_qualification_eligible"] is False
    assert addendum["validation_boundary"]["runtime_safety_truth"] is False


def test_intelligence_cannot_run_without_exact_domain_fixture_declaration(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import replace
    from tests.qualification import phase3_telemetry
    from tests.qualification.phase3_intelligence_reads import run_intelligence_reads
    removed = tuple(replace(item, synthetic_loopback_primitives=()) for item in READ_TELEMETRY_CONTRACTS)
    monkeypatch.setattr(phase3_telemetry, "READ_TELEMETRY_CONTRACTS", removed)
    with pytest.raises(ValueError, match="exact declared SQLite fixture primitive"):
        run_intelligence_reads(execution_root=tmp_path / "execution", repository_root=ROOT)
    assert not (tmp_path / "execution").exists()


@pytest.mark.parametrize("source,owner", (
    ("runtime_audit_api.py", "dashboard-shell-control"),
    ("runtime_audit_ledger.py", "dashboard-shell-control"),
    ("src/scout/nextgen/dashboard_telemetry.py", "assistant-planner"),
    ("src/scout/nextgen/dashboard_telemetry_api.py", "assistant-planner"),
    ("src/scout/nextgen/background_job_store.py", "assistant-planner"),
    ("tools/hardware_monitor_proxy.py", "observer-hardware-boundary"),
    ("tools/hardware_monitor_ssh.py", "observer-hardware-boundary"),
))
def test_effect_inventory_assigns_telemetry_callsites_to_their_exact_source_owner(source: str, owner: str) -> None:
    from tests.qualification.phase3_validation import _domain_for_source_symbol, discover_effect_inventory
    assert _domain_for_source_symbol(source, "module", 1) == owner
    inventory = discover_effect_inventory(ROOT)
    assignments = tuple(operation for callsite, operation in inventory.callsite_assignments if callsite.startswith(source + ":"))
    assert all(operation.startswith("effect:" + owner + ":") for operation in assignments)
    if source != "runtime_audit_api.py":
        assert assignments


@pytest.mark.parametrize("source", (
    "copies/tools/hardware_monitor_proxy.py",
    "tools/hardware_monitor_proxy.py.backup",
    "src/scout/nextgen/unrelated_dashboard_telemetry.py",
))
def test_effect_owner_mapping_does_not_match_similar_or_copied_source_names(source: str) -> None:
    from tests.qualification.phase3_validation import _domain_for_source_symbol
    assert _domain_for_source_symbol(source, "module", 1) == "dashboard-shell-control"


def test_effect_owner_mapping_rejects_conflicting_contract_ownership(monkeypatch) -> None:
    from dataclasses import replace
    from tests.qualification import phase3_validation
    original = next(item for item in READ_TELEMETRY_CONTRACTS if item.route == "surface-intelligence")
    ambiguous = replace(original, domain_id="observer-hardware-boundary")
    monkeypatch.setattr(phase3_validation, "READ_TELEMETRY_CONTRACTS", (*READ_TELEMETRY_CONTRACTS, ambiguous), raising=False)
    with pytest.raises(ValueError, match="conflicting telemetry source ownership"):
        phase3_validation._domain_for_source_symbol(original.sources[0], "module", 1)


def test_exact_effect_ownership_keeps_all_callsites_and_unrelated_assignments(monkeypatch) -> None:
    from tests.qualification import phase3_validation
    after = dict(phase3_validation.discover_effect_inventory(ROOT).callsite_assignments)
    owners = {ref: item.domain_id for item in READ_TELEMETRY_CONTRACTS for ref in item.sources}
    monkeypatch.setattr(phase3_validation, "READ_TELEMETRY_CONTRACTS", ())
    original = dict(phase3_validation.discover_effect_inventory(ROOT).callsite_assignments)
    assert set(after) == set(original)
    changed = {callsite for callsite in after if after[callsite] != original[callsite]}
    assert changed
    for callsite in after:
        source = callsite.split(":", 1)[0]
        if source in owners:
            assert after[callsite].startswith("effect:" + owners[source] + ":")
        else:
            assert after[callsite] == original[callsite]


def test_effect_inventory_includes_actual_monitor_opener_http_callsite() -> None:
    import ast
    from tests.qualification.phase3_validation import discover_effect_inventory
    source = "tools/hardware_monitor_proxy.py"
    tree = ast.parse((ROOT / source).read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "fetch_hardware_monitor_json")
    calls = tuple(node for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "opener" and node.func.attr == "open")
    assert len(calls) == 1
    inventory = discover_effect_inventory(ROOT)
    matches = tuple(operation for callsite, operation in inventory.callsite_assignments if callsite.startswith(f"{source}:{calls[0].lineno}:") and callsite.endswith(":opener.open"))
    assert matches == ("effect:observer-hardware-boundary:http",)


@pytest.mark.parametrize("mutation", ("factory", "import"))
def test_monitor_http_inventory_rejects_an_unbound_opener(mutation: str) -> None:
    import ast
    from tests.qualification.phase3_validation import _EffectVisitor
    source = "tools/hardware_monitor_proxy.py"
    text = (ROOT / source).read_text()
    if mutation == "factory":
        mutated = text.replace("opener = build_opener(", "opener = unknown_factory(", 1)
    else:
        mutated = text.replace("from urllib.request import", "from unreviewed.transport import", 1)
    assert mutated != text
    visitor = _EffectVisitor(source)
    visitor.visit(ast.parse(mutated))
    assert any("opener.open" in item for item in visitor.unclassified)
    assert not any(item[3] == "http" for item in visitor.callsites)


def test_real_monitor_fetcher_is_blocked_before_native_socket(tmp_path: Path, monkeypatch) -> None:
    import socket
    from tools.hardware_monitor_proxy import fetch_hardware_monitor_json, HardwareMonitorUpstreamError
    native_calls = []
    def forbidden_native_socket(*args, **kwargs):
        native_calls.append((args, kwargs))
        raise AssertionError("real socket primitive must never be reached")
    monkeypatch.setattr(socket, "socket", forbidden_native_socket)
    with EffectAudit(transition_id="monitor.native-before-call", roots=(("execution", tmp_path),)) as audit:
        with pytest.raises(HardwareMonitorUpstreamError, match="unavailable"):
            fetch_hardware_monitor_json("/api/v1/hardware-monitor/status", {})
    assert native_calls == []
    assert any(item.effect_class == "network_socket" and item.outcome == "blocked_before_invocation" for item in audit.attempts)


def test_monitor_transport_dependency_census_includes_new_ssh_native_callsite() -> None:
    import ast
    from tests.qualification.phase3_validation import discover_effect_inventory
    contract = next(item for item in READ_TELEMETRY_CONTRACTS if item.route == "scout-monitor")
    proxy_source = "tools/hardware_monitor_proxy.py"
    tree = ast.parse((ROOT / proxy_source).read_text())
    dependencies = tuple(node.module.replace(".", "/") + ".py" for node in tree.body
                         if isinstance(node, ast.ImportFrom) and node.module == "tools.hardware_monitor_ssh")
    assert dependencies == ("tools/hardware_monitor_ssh.py",)
    assert set(dependencies) <= set(contract.sources), "production SSH dependency is omitted from Phase 3 source closure"
    source = dependencies[0]
    calls = tuple(node for node in ast.walk(ast.parse((ROOT / source).read_text()))
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                  and node.func.attr == "Popen")
    assert len(calls) == 1
    inventory = discover_effect_inventory(ROOT)
    assert source in dict(inventory.source_hashes)
    matches = tuple(operation for callsite, operation in inventory.callsite_assignments
                    if callsite.startswith(f"{source}:{calls[0].lineno}:") and callsite.endswith(":subprocess.Popen"))
    assert matches == ("effect:observer-hardware-boundary:subprocess",)
