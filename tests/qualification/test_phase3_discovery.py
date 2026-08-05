from __future__ import annotations

from pathlib import Path

from tests.qualification.phase3_discovery import discover_dashboard_surface


ROOT = Path(__file__).resolve().parents[2]


def test_current_dashboard_surface_closes_without_inventory_drift() -> None:
    result = discover_dashboard_surface(ROOT)

    assert len(result.routes) == 22
    assert not result.findings
    assert result.manifest.entries
    classes = {entry.entrypoint_class for entry in result.manifest.entries}
    assert {
        "backend_get",
        "backend_post",
        "backend_middleware",
        "backend_lifecycle",
        "backend_background_callback",
        "backend_watcher_callback",
        "backend_cli",
        "backend_tool",
        "frontend_event",
        "frontend_timer",
        "frontend_storage",
        "frontend_fetch",
        "frontend_dynamic_dispatch",
    } <= classes


def test_runtime_diagnostic_is_inventory_only_and_never_an_oracle_domain() -> None:
    result = discover_dashboard_surface(ROOT)
    diagnostic = tuple(
        entry
        for entry in result.manifest.entries
        if entry.disposition == "separate_runtime_diagnostic"
        or entry.disposition == "separate-runtime-diagnostic"
    )
    assert diagnostic
    assert all(entry.domain_id is None for entry in diagnostic)


def test_removed_route_is_blocking_surface_inventory_drift() -> None:
    html = (ROOT / "docs/admin/scout-dashboard-v0.1.html").read_text(encoding="utf-8")
    mutated = html.replace('data-route="observer"', 'data-removed-route="observer"')

    result = discover_dashboard_surface(ROOT, html_override=mutated)

    assert "SURFACE-INVENTORY-DRIFT" in {item.code for item in result.findings}


def test_all_discovered_entrypoints_have_one_valid_disposition() -> None:
    result = discover_dashboard_surface(ROOT)
    allowed = {
        "qualified_domain",
        "presentation_only_shell",
        "separate_runtime_diagnostic",
        "separate-runtime-diagnostic",
        "evidence_backed_exclusion",
    }
    assert len({item.entrypoint_id for item in result.manifest.entries}) == len(
        result.manifest.entries
    )
    assert all(item.disposition in allowed for item in result.manifest.entries)
