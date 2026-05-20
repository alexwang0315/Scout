from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from assistant_ui_smoke_check import (
    ASSISTANT_SURFACES,
    build_assistant_ui_smoke_check,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_admin_assistant_shells_pass_static_smoke_gate() -> None:
    result = build_assistant_ui_smoke_check(ROOT)

    assert result["ok"], result["missing_required_artifacts"]
    assert result["failed_checks"] == []
    assert set(result["checks"]["surfaces"]) == set(ASSISTANT_SURFACES)
    for surface, check in result["checks"]["surfaces"].items():
        assert check["ok"], surface
        assert check["forbidden_action_buttons"] == []
        assert check["missing"] == []


def test_complete_minimal_fixture_passes_static_smoke_gate(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)
    _write(
        tmp_path / "docs/admin/phase4-pretrip-planning.html",
        "<button>Accept selected review</button>" + _page("pretrip"),
    )

    result = build_assistant_ui_smoke_check(tmp_path)

    assert result["ok"], result["missing_required_artifacts"]
    assert result["failed_checks"] == []


@pytest.mark.parametrize(
    ("surface", "needle", "expected_missing"),
    [
        (
            "debug",
            "/assistant/status",
            "debug:page_token:/assistant/status",
        ),
        (
            "admin",
            "read-only model interpretation",
            "admin:shell_token:read-only model interpretation",
        ),
        (
            "pretrip",
            'src="/admin/scout-assistant-ui.js"',
            'pretrip:page_token:src="/admin/scout-assistant-ui.js"',
        ),
        (
            "hardware_readiness",
            "<h3>Sources</h3>",
            "hardware_readiness:shell_token:Sources",
        ),
    ],
)
def test_missing_required_shell_or_page_tokens_fail_static_smoke_gate(
    tmp_path: Path,
    surface: str,
    needle: str,
    expected_missing: str,
) -> None:
    _write_complete_minimal_repo(tmp_path)
    page_path = tmp_path / ASSISTANT_SURFACES[surface]
    page_path.write_text(page_path.read_text(encoding="utf-8").replace(needle, ""), encoding="utf-8")

    result = build_assistant_ui_smoke_check(tmp_path)

    assert result["ok"] is False
    assert expected_missing in result["checks"]["surfaces"][surface]["missing"]
    assert expected_missing in result["missing_required_artifacts"]


@pytest.mark.parametrize(
    ("label", "expected_token"),
    [
        ("Approve route", "approve"),
        ("Reject selected item", "reject"),
        ("Send outbound message", "send"),
        ("Write fact", "write"),
        ("Mutate provider", "mutate"),
        ("Control hardware", "control"),
        ("Accept review", "accept"),
    ],
)
def test_forbidden_action_buttons_inside_assistant_shell_fail_static_smoke_gate(
    tmp_path: Path,
    label: str,
    expected_token: str,
) -> None:
    _write_complete_minimal_repo(tmp_path)
    page_path = tmp_path / ASSISTANT_SURFACES["debug"]
    html = page_path.read_text(encoding="utf-8").replace(
        "<button type=\"button\">Ask read-only assistant</button>",
        f"<button type=\"button\">Ask read-only assistant</button><button type=\"button\">{label}</button>",
    )
    page_path.write_text(html, encoding="utf-8")

    result = build_assistant_ui_smoke_check(tmp_path)

    assert result["ok"] is False
    forbidden = result["checks"]["surfaces"]["debug"]["forbidden_action_buttons"]
    assert forbidden == [{"label": label, "token": expected_token}]
    assert f"debug:forbidden_action_button:{expected_token}:{label}" in result["missing_required_artifacts"]


def test_cli_pretty_outputs_json_and_returns_nonzero_on_failure(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)
    (tmp_path / ASSISTANT_SURFACES["admin"]).unlink()

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assistant_ui_smoke_check.py"),
            "--repo-root",
            str(tmp_path),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stdout.startswith("{\n  ")
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert "admin:missing_page:docs/admin/phase1-after-action.html" in payload["missing_required_artifacts"]


def _write_complete_minimal_repo(root: Path) -> None:
    _write(root / "docs/admin/scout-assistant-ui.js", "window.ScoutAssistantUI = {};")
    for surface, relative_path in ASSISTANT_SURFACES.items():
        _write(root / relative_path, _page(surface))


def _page(surface: str) -> str:
    return f"""
<!doctype html>
<html>
<body>
  <!-- assistant-shell:start -->
  <article data-assistant-surface="{surface}" data-assistant-boundary="read-only model interpretation">
    <h2>{surface} assistant</h2>
    <p>read-only model interpretation</p>
    <section><h3>Context</h3><ul><li>selected context</li></ul></section>
    <section><h3>Limitations</h3><ul><li>No writes.</li></ul></section>
    <section><h3>Sources</h3><ul><li>fixture</li></ul></section>
    <button type="button">Ask read-only assistant</button>
  </article>
  <!-- assistant-shell:end -->
  <script src="/admin/scout-assistant-ui.js"></script>
  <script>
    fetchJson("/assistant/status");
    postJson("/assistant/query", {{surface: "{surface}"}});
  </script>
</body>
</html>
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
