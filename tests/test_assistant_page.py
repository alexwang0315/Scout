import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEBUG_PAGE = ROOT / "docs" / "admin" / "phase-3-5-runtime-debug.html"
PRETRIP_PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
ADMIN_PAGE = ROOT / "docs" / "admin" / "phase1-after-action.html"
HARDWARE_PAGE = ROOT / "docs" / "admin" / "phase-3-6-hardware-readiness.html"
ASSISTANT_UI_SCRIPT = ROOT / "docs" / "admin" / "scout-assistant-ui.js"
MUTATION_BUTTON_RE = re.compile(
    r"<\s*button\b[^>]*>(?:[^<]*(?:accept|approve|reject|send|write|mutate|control|apply)[^<]*)</button>",
    re.IGNORECASE,
)
FORBIDDEN_QUERY_FIELDS = (
    "approve",
    "send",
    "write_fact",
    "mutate",
    "control_provider",
)


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
    assert MUTATION_BUTTON_RE.search(shell) is None


def assert_live_query_contract(html: str, shell: str, surface: str) -> None:
    shared_script = read_page(ASSISTANT_UI_SCRIPT)
    combined = html + shared_script
    assert 'id="assistantQuestionInput"' in shell
    assert 'id="assistantAskButton"' in shell
    assert "Ask read-only assistant" in shell
    assert 'id="assistantStatus"' in shell
    assert 'id="assistantAnswerText"' in shell
    assert 'id="assistantLimitationsList"' in shell
    assert 'id="assistantSourcesList"' in shell
    assert 'src="/admin/scout-assistant-ui.js"' in html
    assert "window.ScoutAssistantUI" in shared_script
    assert '"/assistant/query"' in html
    assert 'method: "POST"' in combined
    assert '"Content-Type": "application/json"' in combined
    assert f'surface: "{surface}"' in html
    assert "renderAssistantResponse" in html
    assert "Assistant query failed" in html
    payload_function = function_block(html, "assistantQueryPayload")
    for field in FORBIDDEN_QUERY_FIELDS:
        assert f"{field}:" not in payload_function


def assert_status_and_context_panel_contract(html: str, shell: str) -> None:
    combined = html + read_page(ASSISTANT_UI_SCRIPT)
    assert 'id="assistantProviderStatus"' in shell
    assert 'id="assistantProviderStatusDetail"' in shell
    assert 'id="assistantContextList"' in shell
    assert "Provider" in shell
    assert "Context" in shell
    assert '"/assistant/status"' in html
    assert "loadAssistantStatus" in html
    assert "renderAssistantContext" in html
    assert "token_values_exposed" in combined
    assert "api_key" not in shell.lower()


def function_block(html: str, name: str) -> str:
    start = html.index(f"function {name}")
    next_function = html.find("\n    function ", start + 1)
    next_async_function = html.find("\n    async function ", start + 1)
    candidates = [index for index in (next_function, next_async_function) if index != -1]
    end = min(candidates) if candidates else len(html)
    return html[start:end]


def css_block(html: str, selector: str) -> str:
    start = html.index(selector)
    end = html.index("}", start)
    return html[start:end]


def test_debug_page_has_read_only_assistant_shell_and_live_query_controls():
    html = read_page(DEBUG_PAGE)
    shell = assistant_shell(html)

    assert_shared_assistant_contract(shell, "debug")
    assert_live_query_contract(html, shell, "debug")
    assert_status_and_context_panel_contract(html, shell)
    assert "grid-template-rows: minmax(220px, 1fr) minmax(300px, 0.9fr);" in css_block(html, ".timeline-column")
    assert "overflow-y: auto;" in css_block(html, ".assistant-body")
    assert "debug assistant" in shell.lower()
    assert "/assistant/query" in shell
    assert "/debug/events" in shell
    assert "/debug/state" in shell
    assert "/debug/messages" in shell
    assert "selected timeline node" in shell
    assert "No safety runtime mutation" in shell
    assert "No Phase 2 writeback" in shell
    payload_function = function_block(html, "assistantQueryPayload")
    assert "selected_event_id: debugPageState.selectedEventId || null" in payload_function


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
    assert 'data-assistant-question="Why did CP2 become an L2 event?"' in shell
    assert "runAssistantQuestion" in html
    assert MUTATION_BUTTON_RE.search(shell) is None


def test_pretrip_page_has_read_only_assistant_shell_and_live_query_controls():
    html = read_page(PRETRIP_PAGE)
    shell = assistant_shell(html)

    assert_shared_assistant_contract(shell, "pretrip")
    assert_live_query_contract(html, shell, "pretrip")
    assert_status_and_context_panel_contract(html, shell)
    assert "pretrip assistant" in shell.lower()
    assert "POST /assistant/query" in shell
    assert "review queue" in shell
    assert "readiness" in shell
    assert "candidate provenance" in shell
    assert "No review decision is created" in shell
    assert "No departure approval is granted" in shell
    assert "No runtime handoff or hardware control is opened" in shell
    payload_function = function_block(html, "assistantQueryPayload")
    assert "project_id: PROJECT_ID" in payload_function
    assert "selected_artifact_id: evidenceSourceId(state.selected) || null" in payload_function
    assert MUTATION_BUTTON_RE.search(shell) is None


def test_pretrip_page_assistant_shell_shows_selected_artifact_prompt_suggestions():
    html = read_page(PRETRIP_PAGE)
    shell = assistant_shell(html)

    assert "assistantPromptSuggestions" in html
    assert "suggestedAssistantQuestions" in html
    assert 'id="assistantPromptSuggestions"' in shell
    assert "Suggested questions" in shell
    assert "selected planning context" in shell
    assert "Why does this selected item need review?" in shell
    assert "What evidence is missing for this candidate?" in shell
    assert "Could this block departure readiness?" in shell
    assert 'data-assistant-question="Why does this selected item need review?"' in shell
    assert "runAssistantQuestion" in html
    assert "renderAssistantPromptSuggestions(state.selected)" in html
    assert MUTATION_BUTTON_RE.search(shell) is None


def test_shared_assistant_ui_module_has_read_only_fetch_and_render_helpers():
    script = read_page(ASSISTANT_UI_SCRIPT)

    assert "window.ScoutAssistantUI" in script
    assert "fetchJson" in script
    assert "postJson" in script
    assert 'method: "POST"' in script
    assert '"Content-Type": "application/json"' in script
    assert "renderProviderStatus" in script
    assert "observabilityItems" in script
    assert "token_values_exposed" in script
    assert "api_key" not in script.lower()


def test_admin_after_action_page_has_read_only_assistant_shell_and_live_query_controls():
    html = read_page(ADMIN_PAGE)
    shell = assistant_shell(html)

    assert_shared_assistant_contract(shell, "admin")
    assert_live_query_contract(html, shell, "admin")
    assert_status_and_context_panel_contract(html, shell)
    assert "after-action admin assistant" in shell.lower()
    assert "completed mission evidence" in shell
    assert "No historical incident or evidence rewrite" in shell
    assert "No Phase 2 Brain writeback or ObservedFact creation" in shell
    payload_function = function_block(html, "assistantQueryPayload")
    assert "context_ref: CASE_ID" in payload_function
    assert "selected_artifact_id: selectedAssistantContextLabel(state.selected)" in payload_function
    assert "renderAssistantPromptSuggestions(state.selected)" in html
    assert MUTATION_BUTTON_RE.search(shell) is None


def test_hardware_readiness_page_has_read_only_assistant_shell_and_live_query_controls():
    html = read_page(HARDWARE_PAGE)
    shell = assistant_shell(html)

    assert_shared_assistant_contract(shell, "hardware_readiness")
    assert_live_query_contract(html, shell, "hardware_readiness")
    assert_status_and_context_panel_contract(html, shell)
    assert "hardware readiness assistant" in shell.lower()
    assert "fixture-backed provider dry-run" in shell
    assert "No hardware control or provider control" in shell
    assert "No real SOS, SMS, satellite, or outbound transport" in shell
    assert "/admin/hardware-readiness/context" in html
    payload_function = function_block(html, "assistantQueryPayload")
    assert "selected_artifact_id: selectedProviderRef() || null" in payload_function
    assert MUTATION_BUTTON_RE.search(shell) is None
