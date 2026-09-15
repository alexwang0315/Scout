from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.qualification import phase3_discovery
from tests.qualification.phase3_discovery import (
    discover_dashboard_surface,
    discover_python_entrypoints,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ASSET_BINDINGS = {
    "/scout-planned-map-review.js": "pretrip_workflow_script",
    "/scout-planned-review-ui.js": "pretrip_workflow_script",
    "/scout-exploration-workflow.js": "pretrip_workflow_script",
    "/scout-recorded-workflow.js": "pretrip_workflow_script",
}


def _assert_workflow_asset_bindings(entries: tuple) -> None:
    """Four actual URLs must retain their single production handler bindings."""
    for target, expected_symbol in WORKFLOW_ASSET_BINDINGS.items():
        matches = tuple(
            entry
            for entry in entries
            if entry.entrypoint_class == "backend_get"
            and entry.reachable_target == target
        )
        assert len(matches) == 1, (target, matches)
        assert matches[0].symbol == expected_symbol, (target, matches[0].symbol)


def test_stacked_decorators_have_actual_registration_sites_and_unique_ids(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bindings.py"
    source.write_text(
        "".join(f'@router.get("{target}")\n' for target in WORKFLOW_ASSET_BINDINGS)
        + "def pretrip_workflow_script(request):\n    return request\n",
        encoding="utf-8",
    )
    entries, unresolved = discover_python_entrypoints(source, source_ref="bindings.py")

    assert not unresolved
    assert len(entries) == len(WORKFLOW_ASSET_BINDINGS) == 4
    assert len({entry.entrypoint_id for entry in entries}) == 4
    assert {entry.line for entry in entries} == {1, 2, 3, 4}
    assert {entry.registration_site for entry in entries} == {
        "bindings.py:1", "bindings.py:2", "bindings.py:3", "bindings.py:4",
    }
    _assert_workflow_asset_bindings(entries)


def test_current_workflow_assets_keep_all_four_real_endpoint_handler_bindings() -> None:
    entries, _ = discover_python_entrypoints(ROOT / "admin_api.py", source_ref="admin_api.py")
    _assert_workflow_asset_bindings(entries)
    selected = tuple(entry for entry in entries if entry.reachable_target in WORKFLOW_ASSET_BINDINGS)
    assert len({entry.entrypoint_id for entry in selected}) == 4
    assert len({entry.registration_site for entry in selected}) == 4


@pytest.mark.parametrize("target", tuple(WORKFLOW_ASSET_BINDINGS))
def test_workflow_binding_guard_rejects_wrong_handler(target: str) -> None:
    entries, _ = discover_python_entrypoints(ROOT / "admin_api.py", source_ref="admin_api.py")
    corrupted = tuple(
        replace(entry, symbol="wrong_handler") if entry.reachable_target == target else entry
        for entry in entries
    )
    with pytest.raises(AssertionError):
        _assert_workflow_asset_bindings(corrupted)


@pytest.mark.parametrize("mutation", ("missing", "duplicate"))
def test_workflow_binding_guard_rejects_lost_or_duplicate_registration(mutation: str) -> None:
    entries, _ = discover_python_entrypoints(ROOT / "admin_api.py", source_ref="admin_api.py")
    target = next(iter(WORKFLOW_ASSET_BINDINGS))
    selected = next(entry for entry in entries if entry.reachable_target == target)
    corrupted = (
        tuple(entry for entry in entries if entry is not selected)
        if mutation == "missing"
        else (*entries, replace(selected, entrypoint_id="a-different-id-does-not-hide-duplicate"))
    )
    with pytest.raises(AssertionError):
        _assert_workflow_asset_bindings(corrupted)


def test_surface_reconciliation_still_rejects_a_real_duplicate_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discover = phase3_discovery.discover_python_entrypoints

    def duplicate(path: Path, *, source_ref: str):
        entries, unresolved = discover(path, source_ref=source_ref)
        if source_ref == "admin_api.py":
            entry = next(item for item in entries if item.reachable_target in WORKFLOW_ASSET_BINDINGS)
            entries = (*entries, entry)
        return entries, unresolved

    monkeypatch.setattr(phase3_discovery, "discover_python_entrypoints", duplicate)
    result = discover_dashboard_surface(ROOT)
    assert any(
        finding.code == "SURFACE-INVENTORY-DRIFT"
        and finding.summary == "Executable entrypoint discovery produced duplicate identities."
        for finding in result.findings
    )


def test_surface_reconciliation_still_rejects_an_unknown_route() -> None:
    html = (ROOT / "docs/admin/scout-dashboard-v0.1.html").read_text(encoding="utf-8")
    result = discover_dashboard_surface(
        ROOT, html_override=html + '<button data-route="unknown-phase3-route"></button>'
    )
    assert any(
        finding.code == "SURFACE-INVENTORY-DRIFT"
        and "unknown-phase3-route" in finding.summary
        for finding in result.findings
    )
