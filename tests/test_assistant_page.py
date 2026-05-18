import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEBUG_PAGE = ROOT / "docs" / "admin" / "phase-3-5-runtime-debug.html"
PRETRIP_PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
CONTROL_TAG_RE = re.compile(r"<\s*(button|form|input|select|textarea)\b", re.IGNORECASE)


def read_page(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assistant_shell(html: str) -> str:
    start = "<!-- assistant-shell:start -->"
    end = "<!-- assistant-shell:end -->"
    assert start in html
    assert end in html
    return html.split(start, 1)[1].split(end, 1)[0]


def assert_shared_assistant_contract(shell: str, surface: str) -> None:
    assert f'data-assistant-surface="{surface}"' in shell
    assert 'data-assistant-boundary="read-only model interpretation"' in shell
    assert "read-only model interpretation" in shell
    assert "Answer" in shell
    assert "Limitations" in shell
    assert "Sources" in shell
    assert 'class="assistant-answer"' in shell
    assert 'class="assistant-limitations"' in shell
    assert 'class="assistant-sources"' in shell
    assert CONTROL_TAG_RE.search(shell) is None


def test_debug_page_has_read_only_assistant_shell_without_controls_or_mutation_api():
    html = read_page(DEBUG_PAGE)
    shell = assistant_shell(html)

    assert_shared_assistant_contract(shell, "debug")
    assert "debug assistant" in shell.lower()
    assert "/assistant/query" in shell
    assert "/debug/events" in shell
    assert "/debug/state" in shell
    assert "/debug/messages" in shell
    assert "selected timeline node" in shell
    assert "No safety runtime mutation" in shell
    assert "No Phase 2 writeback" in shell
    assert "POST" not in shell
    assert "method:" not in shell
    assert "body:" not in shell
    assert 'fetchJson("/assistant/query' not in html


def test_debug_page_assistant_shell_shows_selected_timeline_prompt_suggestions():
    html = read_page(DEBUG_PAGE)
    shell = assistant_shell(html)

    assert "assistantPromptSuggestions" in html
    assert "suggestedAssistantQuestions" in html
    assert 'id="assistantPromptSuggestions"' in shell
    assert "Suggested questions" in shell
    assert "selected timeline context" in shell
    assert "CP2" in shell
    assert "L2" in shell
    assert "Why did CP2 become an L2 event?" in shell
    assert "Which sources support this timeline state?" in shell
    assert "What is missing from this context?" in shell
    assert CONTROL_TAG_RE.search(shell) is None


def test_pretrip_page_has_read_only_assistant_shell_without_action_controls():
    html = read_page(PRETRIP_PAGE)
    shell = assistant_shell(html)

    assert_shared_assistant_contract(shell, "pretrip")
    assert "pretrip assistant" in shell.lower()
    assert "POST /assistant/query" in shell
    assert "review queue" in shell
    assert "readiness" in shell
    assert "candidate provenance" in shell
    assert "No review decision is created" in shell
    assert "No departure approval is granted" in shell
    assert "No runtime handoff or hardware control is opened" in shell
    assert "action" not in re.findall(r"<\s*button\b[^>]*>(.*?)</button>", shell, re.IGNORECASE)
