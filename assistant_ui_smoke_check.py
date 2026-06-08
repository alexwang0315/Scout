from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent

ASSISTANT_SURFACES = {
    "debug": "docs/admin/phase-3-5-runtime-debug.html",
    "pretrip": "docs/admin/phase4-pretrip-planning.html",
    "admin": "docs/admin/phase1-after-action.html",
    "hardware_readiness": "docs/admin/phase-3-6-hardware-readiness.html",
}

ASSISTANT_UI_SCRIPT = "docs/admin/scout-assistant-ui.js"
ASSISTANT_UI_SCRIPT_SRC = '/admin/scout-assistant-ui.js'
ASSISTANT_SHELL_START = "<!-- assistant-shell:start -->"
ASSISTANT_SHELL_END = "<!-- assistant-shell:end -->"
FORBIDDEN_ACTION_BUTTON_TOKENS = (
    "accept",
    "approve",
    "reject",
    "send",
    "write",
    "mutate",
    "control",
)

_WORD_RE = re.compile(r"[a-z]+")


def build_assistant_ui_smoke_check(repo_root: Path | str = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    checks: dict[str, Any] = {
        "shared_script": _check_shared_script(root),
        "surfaces": {},
    }
    missing_required: list[str] = list(checks["shared_script"]["missing"])

    for surface, relative_path in ASSISTANT_SURFACES.items():
        surface_check = _check_surface(root, surface, relative_path)
        checks["surfaces"][surface] = surface_check
        missing_required.extend(surface_check["missing"])
        missing_required.extend(
            f"{surface}:forbidden_action_button:{item['token']}:{item['label']}"
            for item in surface_check["forbidden_action_buttons"]
        )

    failed_checks = []
    if not checks["shared_script"]["ok"]:
        failed_checks.append("shared_script")
    failed_checks.extend(
        surface
        for surface, check in checks["surfaces"].items()
        if not check["ok"]
    )

    return {
        "ok": not failed_checks,
        "repo_root": str(root),
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_required_artifacts": sorted(set(missing_required)),
    }


def _check_shared_script(root: Path) -> dict[str, Any]:
    path = root / ASSISTANT_UI_SCRIPT
    missing = [] if path.exists() else [f"shared_script:missing:{ASSISTANT_UI_SCRIPT}"]
    return {
        "ok": not missing,
        "path": ASSISTANT_UI_SCRIPT,
        "missing": missing,
    }


def _check_surface(root: Path, surface: str, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    if not path.exists():
        return {
            "ok": False,
            "path": relative_path,
            "missing": [f"{surface}:missing_page:{relative_path}"],
            "forbidden_action_buttons": [],
        }

    html = path.read_text(encoding="utf-8")
    missing: list[str] = []
    missing.extend(_missing_page_tokens(surface, html))

    shell = _extract_assistant_shell(html)
    forbidden_buttons: list[dict[str, str]] = []
    if shell is None:
        missing.append(f"{surface}:missing_shell:{ASSISTANT_SHELL_START}")
    else:
        missing.extend(_missing_shell_tokens(surface, shell))
        forbidden_buttons = _forbidden_action_buttons(shell)

    return {
        "ok": not missing and not forbidden_buttons,
        "path": relative_path,
        "missing": missing,
        "forbidden_action_buttons": forbidden_buttons,
    }


def _missing_page_tokens(surface: str, html: str) -> list[str]:
    required = (
        f'src="{ASSISTANT_UI_SCRIPT_SRC}"',
        "/assistant/query",
        "/assistant/status",
    )
    return [
        f"{surface}:page_token:{token}"
        for token in required
        if token not in html
    ]


def _missing_shell_tokens(surface: str, shell: str) -> list[str]:
    required = (
        f'data-assistant-surface="{surface}"',
        'data-assistant-boundary="read-only model interpretation"',
        "read-only model interpretation",
        "Context",
        "Offline fallback",
        "Workflow readiness status not loaded.",
        "Limitations",
        "Sources",
    )
    return [
        f"{surface}:shell_token:{_token_label(token)}"
        for token in required
        if token not in shell
    ]


def _token_label(token: str) -> str:
    if token.startswith('data-assistant-surface="'):
        value = token.split('"', 2)[1]
        return f"data-assistant-surface={value}"
    if token == 'data-assistant-boundary="read-only model interpretation"':
        return "data-assistant-boundary=read-only model interpretation"
    return token


def _extract_assistant_shell(html: str) -> str | None:
    if ASSISTANT_SHELL_START not in html or ASSISTANT_SHELL_END not in html:
        return None
    return html.split(ASSISTANT_SHELL_START, 1)[1].split(ASSISTANT_SHELL_END, 1)[0]


def _forbidden_action_buttons(shell: str) -> list[dict[str, str]]:
    parser = _ButtonCollector()
    parser.feed(shell)
    forbidden: list[dict[str, str]] = []

    for button in parser.buttons:
        label = button["label"]
        searchable = " ".join(
            value
            for value in (
                label,
                button["attrs"].get("aria-label", ""),
                button["attrs"].get("title", ""),
                button["attrs"].get("value", ""),
                button["attrs"].get("data-assistant-question", ""),
            )
            if value
        )
        token = _first_forbidden_button_token(searchable)
        if token:
            forbidden.append({"label": label or searchable, "token": token})

    return forbidden


def _first_forbidden_button_token(value: str) -> str | None:
    words = set(_WORD_RE.findall(value.lower()))
    for token in FORBIDDEN_ACTION_BUTTON_TOKENS:
        if token in words:
            return token
    return None


class _ButtonCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.buttons: list[dict[str, Any]] = []
        self._button_depth = 0
        self._attrs: dict[str, str] = {}
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "button":
            return
        if self._button_depth == 0:
            self._attrs = {name: value or "" for name, value in attrs}
            self._text_parts = []
        self._button_depth += 1

    def handle_data(self, data: str) -> None:
        if self._button_depth:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "button" or not self._button_depth:
            return
        self._button_depth -= 1
        if self._button_depth == 0:
            label = " ".join("".join(self._text_parts).split())
            self.buttons.append({"label": label, "attrs": dict(self._attrs)})
            self._attrs = {}
            self._text_parts = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Scout assistant UI static smoke gate."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    result = build_assistant_ui_smoke_check(args.repo_root)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
