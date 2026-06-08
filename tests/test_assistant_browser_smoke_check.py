from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from assistant_browser_smoke_check import (
    ASSISTANT_BROWSER_SURFACES,
    ASSISTANT_BROWSER_VIEWPORTS,
    build_assistant_browser_smoke_check,
    detect_assistant_browser_runtime_availability,
)


ROOT = Path(__file__).resolve().parents[1]


def test_browser_smoke_observations_pass_when_all_surfaces_are_read_only_and_responsive() -> None:
    observations = [
        _observation(surface["name"], viewport["name"], surface["expected_surface"])
        for viewport in ASSISTANT_BROWSER_VIEWPORTS
        for surface in ASSISTANT_BROWSER_SURFACES
    ]

    result = build_assistant_browser_smoke_check(
        base_url="http://127.0.0.1:9111",
        observations=observations,
    )

    assert result["ok"], result["missing_required_artifacts"]
    assert result["failed_checks"] == []
    assert len(result["checks"]) == len(ASSISTANT_BROWSER_SURFACES) * len(ASSISTANT_BROWSER_VIEWPORTS)


def test_browser_smoke_reports_overflow_console_errors_and_forbidden_buttons() -> None:
    observations = [
        _observation(surface["name"], viewport["name"], surface["expected_surface"])
        for viewport in ASSISTANT_BROWSER_VIEWPORTS
        for surface in ASSISTANT_BROWSER_SURFACES
    ]
    observations[0]["consoleErrors"] = ["boom"]
    observations[0]["documentScroll"]["horizontalOverflowPx"] = 12
    observations[0]["forbiddenButtons"] = [{"label": "Control provider", "forbidden": ["control"]}]
    observations[1]["offlineVisible"] = False

    result = build_assistant_browser_smoke_check(
        base_url="http://127.0.0.1:9111",
        observations=observations,
    )

    assert result["ok"] is False
    assert "debug:desktop:console_errors" in result["missing_required_artifacts"]
    assert "debug:desktop:horizontal_overflow:12" in result["missing_required_artifacts"]
    assert "debug:desktop:forbidden_action_buttons" in result["missing_required_artifacts"]
    assert "pretrip:desktop:offline_fallback_not_visible" in result["missing_required_artifacts"]


def test_cli_runs_node_browser_runtime_and_prints_json(tmp_path: Path) -> None:
    fake_node = _write_fake_node(tmp_path, fail=False)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assistant_browser_smoke_check.py"),
            "--base-url",
            "http://127.0.0.1:9111",
            "--node",
            str(fake_node),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["check"] == "assistant_browser_smoke"
    assert payload["base_url"] == "http://127.0.0.1:9111"


def test_cli_reports_missing_playwright_as_runtime_failure(tmp_path: Path) -> None:
    fake_node = _write_fake_node(tmp_path, fail=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assistant_browser_smoke_check.py"),
            "--base-url",
            "http://127.0.0.1:9111",
            "--node",
            str(fake_node),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert "browser_runtime:playwright_unavailable" in payload["missing_required_artifacts"]


def test_runtime_availability_prefers_playwright_when_browser_modules_exist(
    tmp_path: Path,
) -> None:
    fake_node = _write_fake_runtime_probe_node(
        tmp_path,
        modules={"playwright": True, "jsdom": True},
    )

    result = detect_assistant_browser_runtime_availability(
        node_executable=str(fake_node),
    )

    assert result["ok"] is True
    assert result["preferred_runtime"] == "playwright"
    assert result["browser_backed_smoke_available"] is True
    assert result["dom_backed_smoke_available"] is True
    assert result["missing_runtime_modules"] == []
    assert result["missing_required_artifacts"] == []


def test_runtime_availability_reports_skip_safe_missing_playwright_and_jsdom(
    tmp_path: Path,
) -> None:
    fake_node = _write_fake_runtime_probe_node(
        tmp_path,
        modules={"playwright": False, "jsdom": False},
    )

    result = detect_assistant_browser_runtime_availability(
        node_executable=str(fake_node),
    )

    assert result["ok"] is False
    assert result["preferred_runtime"] is None
    assert result["browser_backed_smoke_available"] is False
    assert result["dom_backed_smoke_available"] is False
    assert result["missing_runtime_modules"] == ["playwright", "jsdom"]
    assert result["missing_required_artifacts"] == [
        "browser_runtime:playwright_unavailable",
        "browser_runtime:jsdom_unavailable",
    ]


def test_cli_runtime_check_only_reports_runtime_availability(tmp_path: Path) -> None:
    fake_node = _write_fake_runtime_probe_node(
        tmp_path,
        modules={"playwright": False, "jsdom": True},
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assistant_browser_smoke_check.py"),
            "--runtime-check-only",
            "--node",
            str(fake_node),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["preferred_runtime"] == "jsdom"
    assert payload["browser_backed_smoke_available"] is False
    assert payload["dom_backed_smoke_available"] is True


def _observation(surface: str, viewport: str, expected_surface: str) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "surface": surface,
        "path": f"/{surface}",
        "expectedSurface": expected_surface,
        "viewport": viewport,
        "viewportSize": {"width": 1440 if viewport == "desktop" else 390, "height": 1000 if viewport == "desktop" else 844},
        "consoleErrors": [],
        "pageErrors": [],
        "status": "complete",
        "documentScroll": {
            "clientWidth": 1440 if viewport == "desktop" else 390,
            "scrollWidth": 1440 if viewport == "desktop" else 390,
            "horizontalOverflowPx": 0,
            "clientHeight": 1000 if viewport == "desktop" else 844,
            "scrollHeight": 1000 if viewport == "desktop" else 844,
        },
        "shellPresent": True,
        "shellSurface": expected_surface,
        "boundary": "read-only model interpretation",
        "shellVisible": True,
        "offlineVisible": True,
        "offlineText": "No offline fallback schema returned.",
        "assistantButtonCount": 4,
        "forbiddenButtons": [],
        "pretripTabCheck": None,
    }
    if surface == "pretrip":
        observation["pretripTabCheck"] = {
            "before": {"title": "chilai_nanhua_day1", "sectionCount": 14},
            "afterPost": {
                "title": "Post-analysis overview",
                "sectionCount": 4,
                "assistantScroll": {
                    "clientHeight": 438,
                    "scrollHeight": 1496,
                    "overflowY": "auto",
                },
            },
            "afterPre": {
                "title": "Pre-trip planning overview",
                "sectionCount": 14,
                "assistantScroll": {
                    "clientHeight": 438,
                    "scrollHeight": 1496,
                    "overflowY": "auto",
                },
            },
        }
    return observation


def _write_fake_node(tmp_path: Path, *, fail: bool) -> Path:
    path = tmp_path / "fake_node.py"
    if fail:
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.stdin.read()\n"
            "sys.stderr.write(\"Error: Cannot find module 'playwright'\\n\")\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
    else:
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "sys.stdin.read()\n"
            "config = json.loads(os.environ['SCOUT_BROWSER_SMOKE_CONFIG'])\n"
            "observations = []\n"
            "for viewport in config['viewports']:\n"
            "    for surface in config['surfaces']:\n"
            "        item = {\n"
            "            'surface': surface['name'], 'path': surface['path'], 'expectedSurface': surface['expected_surface'],\n"
            "            'viewport': viewport['name'], 'viewportSize': {'width': viewport['width'], 'height': viewport['height']},\n"
            "            'consoleErrors': [], 'pageErrors': [], 'status': 'complete',\n"
            "            'documentScroll': {'clientWidth': viewport['width'], 'scrollWidth': viewport['width'], 'horizontalOverflowPx': 0, 'clientHeight': viewport['height'], 'scrollHeight': viewport['height']},\n"
            "            'shellPresent': True, 'shellSurface': surface['expected_surface'], 'boundary': 'read-only model interpretation',\n"
            "            'shellVisible': True, 'offlineVisible': True, 'offlineText': 'No offline fallback schema returned.',\n"
            "            'assistantButtonCount': 4, 'forbiddenButtons': [], 'pretripTabCheck': None,\n"
            "        }\n"
            "        if surface['name'] == 'pretrip':\n"
            "            item['pretripTabCheck'] = {\n"
            "                'before': {'title': 'chilai_nanhua_day1', 'sectionCount': 14},\n"
            "                'afterPost': {'title': 'Post-analysis overview', 'sectionCount': 4, 'assistantScroll': {'clientHeight': 438, 'scrollHeight': 1496, 'overflowY': 'auto'}},\n"
            "                'afterPre': {'title': 'Pre-trip planning overview', 'sectionCount': 14, 'assistantScroll': {'clientHeight': 438, 'scrollHeight': 1496, 'overflowY': 'auto'}},\n"
            "            }\n"
            "        observations.append(item)\n"
            "print(json.dumps(observations))\n",
            encoding="utf-8",
        )
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _write_fake_runtime_probe_node(
    tmp_path: Path,
    *,
    modules: dict[str, bool],
) -> Path:
    path = tmp_path / "fake_runtime_probe_node.py"
    module_payload = {
        name: {
            "available": available,
            "resolved": f"/fixture/node_modules/{name}/index.js" if available else None,
            "error": None if available else "MODULE_NOT_FOUND",
        }
        for name, available in modules.items()
    }
    available_runtimes = [
        name for name, value in module_payload.items() if value["available"]
    ]
    payload = {
        "node_available": True,
        "modules": module_payload,
        "available_runtimes": available_runtimes,
        "preferred_runtime": (
            "playwright"
            if "playwright" in available_runtimes
            else ("jsdom" if "jsdom" in available_runtimes else None)
        ),
    }
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o111)
    return path
