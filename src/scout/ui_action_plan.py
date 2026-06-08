from __future__ import annotations

from typing import Any


ARTIFACT_KIND = "scout_ui_action_plan"
ARTIFACT_VERSION = "scout_ui_action_plan.v0"

SUPPORTED_SURFACES = ("admin", "debug", "pretrip")

RISK_LAYER_IDS = ("risk-score", "risk-ribbon", "risk-heatmap", "risk-delta")
ROUTE_CONTEXT_LAYER_IDS = ("corridors", "route", "segments", "checkpoints", "mcp")
BASEMAP_LAYER_IDS = (
    "imagery",
    "rudy",
    "rudy-twmap",
    "relief",
    "geology",
    "topo-5k",
    "forest",
    "osm",
)
COMMON_LAYER_IDS = (
    *BASEMAP_LAYER_IDS,
    "terrain",
    *RISK_LAYER_IDS,
    "corridors",
    "overpass",
    "route",
    "reference-tracks",
    "retreat",
    "segments",
    "checkpoints",
    "pois",
    "hazards",
    "mcp",
    "route-notes",
    "events",
    "weather-api",
)
SURFACE_LAYER_IDS: dict[str, tuple[str, ...]] = {
    "admin": (
        *BASEMAP_LAYER_IDS,
        "terrain",
        *RISK_LAYER_IDS,
        "corridors",
        "overpass",
        "route",
        "completed-track",
        "reference-tracks",
        "retreat",
        "segments",
        "checkpoints",
        "pois",
        "hazards",
        "mcp",
        "route-notes",
        "events",
        "weather-api",
    ),
    "debug": COMMON_LAYER_IDS,
    "pretrip": COMMON_LAYER_IDS,
}


SURFACE_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "surface": "admin",
        "route": "/admin",
        "label": "After-action admin",
        "primary_functions": [
            "Inspect completed-trip evidence tree, capability timeline, and source refs.",
            "Operate map layers, pan/zoom/fit route, select evidence, and double-click evidence to focus the map.",
            "Compare completed GPX, reference GPX, risk score/ribbon/heatmap/delta, terrain, weather, MCP, CP, hazards, and event layers.",
            "Ask the read-only assistant about selected after-action evidence and source support.",
        ],
        "ui_action_examples": [
            "show risk-only map layers",
            "focus selected after-action evidence on the map",
            "fit the completed trip and reference route",
        ],
        "mutation_boundary": "session UI only; no incident/evidence rewrite, Brain write, runtime safety mutation, outbound send, or hardware control.",
    },
    {
        "surface": "debug",
        "route": "/admin/debug",
        "label": "Runtime debug",
        "primary_functions": [
            "Inspect runtime/debug timeline events, provider status, mock outbound state, hardware readiness, and mobile/wearable ingress projection.",
            "Click or double-click timeline evidence to select it, zoom/focus the map target, and update selected event detail panels.",
            "Operate map layers, pan/zoom/fit route, focus CP/event/map targets, and inspect route progress projections.",
            "Ask the read-only assistant about the selected timeline event without changing runtime state.",
        ],
        "ui_action_examples": [
            "zoom to selected timeline evidence",
            "show only risk score layers",
            "open provider or mobile ingress debug panel",
        ],
        "mutation_boundary": "debug projection only; no /safety/* calls, no live runtime mutation, no outbound send, and no hardware control.",
    },
    {
        "surface": "pretrip",
        "route": "/admin/pretrip",
        "label": "Pre-trip planning",
        "primary_functions": [
            "Review route, CP/MCP, risk, terrain, weather, overpass, corridor, retreat, and readiness evidence.",
            "Operate map layers, pan/zoom/fit route, select route evidence, and double-click evidence to focus the map.",
            "Search/read workspace facts through Scout KB and evidence tools.",
            "Review planning candidates, accept/reject/correct review items, link/split/downgrade MCPs, and create candidate-only CP/retreat-route workspace edit intents.",
        ],
        "ui_action_examples": [
            "open Review tab and show blocker items",
            "add CP from selected map coordinate as workspace edit intent",
            "hide all layers except risk score/ribbon/heatmap/delta",
        ],
        "mutation_boundary": "workspace controls are candidate/review intents only; no departure approval, runtime handoff, Phase 1 safety mutation, outbound send, or hardware control.",
    },
)


UI_ACTION_PROMPTS: tuple[dict[str, Any], ...] = (
    {
        "id": "ui_prompt.001",
        "surface": "pretrip",
        "prompt_zh": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
        "expected_action_kind": "set_layer_preset",
        "expected_preset": "risk_only",
    },
    {
        "id": "ui_prompt.002",
        "surface": "admin",
        "prompt_zh": "在 after-action 地圖只顯示風險圖層，其他圖層先關掉。",
        "expected_action_kind": "set_layer_preset",
        "expected_preset": "risk_only",
    },
    {
        "id": "ui_prompt.003",
        "surface": "debug",
        "prompt_zh": "debug 地圖只留下 risk score、baseline、calibrated 和 delta。",
        "expected_action_kind": "set_layer_preset",
        "expected_preset": "risk_only",
    },
    {
        "id": "ui_prompt.004",
        "surface": "pretrip",
        "prompt_zh": "把所有圖層都打開，讓我看完整地圖。",
        "expected_action_kind": "set_layer_preset",
        "expected_preset": "all_layers",
    },
    {
        "id": "ui_prompt.005",
        "surface": "pretrip",
        "prompt_zh": "只留下主路、走廊、CP、MCP 和分段圖層。",
        "expected_action_kind": "set_layer_preset",
        "expected_preset": "route_context",
    },
    {
        "id": "ui_prompt.006",
        "surface": "pretrip",
        "prompt_zh": "幫我關閉影像、OSM、Rudy 等底圖，只看疊加資料。",
        "expected_action_kind": "set_layer_visibility",
    },
    {
        "id": "ui_prompt.007",
        "surface": "pretrip",
        "prompt_zh": "幫我 zoom in 一階。",
        "expected_action_kind": "click_control",
        "expected_control_id": "zoomIn",
    },
    {
        "id": "ui_prompt.008",
        "surface": "pretrip",
        "prompt_zh": "幫我 zoom out 一階。",
        "expected_action_kind": "click_control",
        "expected_control_id": "zoomOut",
    },
    {
        "id": "ui_prompt.009",
        "surface": "admin",
        "prompt_zh": "把地圖縮放回整條路線。",
        "expected_action_kind": "click_control",
        "expected_control_id": "fitRoute",
    },
    {
        "id": "ui_prompt.010",
        "surface": "debug",
        "prompt_zh": "請 zoom to timeline evidence debug_event.test.000002。",
        "expected_action_kind": "focus_map_target",
        "expected_target_kind": "timeline_event",
    },
    {
        "id": "ui_prompt.011",
        "surface": "pretrip",
        "prompt_zh": "請把地圖移到 CP003 附近。",
        "expected_action_kind": "focus_map_target",
        "expected_target_kind": "checkpoint",
    },
    {
        "id": "ui_prompt.012",
        "surface": "admin",
        "prompt_zh": "請聚焦目前選取的 after-action evidence，並顯示標籤。",
        "expected_action_kind": "focus_map_target",
        "expected_target_kind": "selected_evidence",
    },
    {
        "id": "ui_prompt.013",
        "surface": "pretrip",
        "prompt_zh": "幫我搜尋 workspace 裡有關黑水塘的事實。",
        "expected_action_kind": "workspace_search",
    },
    {
        "id": "ui_prompt.014",
        "surface": "pretrip",
        "prompt_zh": "切到 Review 頁籤。",
        "expected_action_kind": "set_tab",
        "expected_tab_id": "review_workspace",
    },
    {
        "id": "ui_prompt.015",
        "surface": "pretrip",
        "prompt_zh": "Review queue 只顯示 blocker。",
        "expected_action_kind": "set_review_filter",
    },
    {
        "id": "ui_prompt.016",
        "surface": "pretrip",
        "prompt_zh": "選取目前可見的 review items。",
        "expected_action_kind": "click_control",
        "expected_control_id": "reviewSelectVisible",
    },
    {
        "id": "ui_prompt.017",
        "surface": "pretrip",
        "prompt_zh": "清除 review selection。",
        "expected_action_kind": "click_control",
        "expected_control_id": "reviewClearSelection",
    },
    {
        "id": "ui_prompt.018",
        "surface": "pretrip",
        "prompt_zh": "把選取的 review items accept 成 workspace review intent。",
        "expected_action_kind": "click_control",
        "expected_control_id": "workspaceAcceptSelectedReviews",
        "requires_confirmation": True,
    },
    {
        "id": "ui_prompt.019",
        "surface": "pretrip",
        "prompt_zh": "用目前地圖點新增一個 CP。",
        "expected_action_kind": "click_control",
        "expected_control_id": "addCheckpoint",
        "requires_confirmation": True,
    },
    {
        "id": "ui_prompt.020",
        "surface": "pretrip",
        "prompt_zh": "刪除目前選取的 CP。",
        "expected_action_kind": "click_control",
        "expected_control_id": "removeCheckpoint",
        "requires_confirmation": True,
    },
)


def build_scout_ui_capability_report(surface: str | None = None) -> dict[str, Any]:
    normalized_surface = _normalize_surface(surface) if surface else None
    surfaces = [
        item
        for item in SURFACE_CAPABILITIES
        if normalized_surface is None or item["surface"] == normalized_surface
    ]
    return {
        "artifact_kind": "scout_ui_capability_report",
        "artifact_version": "scout_ui_capability_report.v0",
        "status": "completed",
        "surface_count": len(surfaces),
        "surfaces": surfaces,
        "supported_layer_presets": _layer_preset_catalog(),
        "boundary": _boundary(),
    }


def list_scout_ui_action_prompts(surface: str | None = None) -> dict[str, Any]:
    normalized_surface = _normalize_surface(surface) if surface else None
    prompts = [
        prompt
        for prompt in UI_ACTION_PROMPTS
        if normalized_surface is None or prompt["surface"] == normalized_surface
    ]
    return {
        "artifact_kind": "scout_ui_action_prompt_corpus",
        "artifact_version": "scout_ui_action_prompt_corpus.v0",
        "status": "completed",
        "prompt_count": len(prompts),
        "prompts": prompts,
        "boundary": _boundary(),
    }


def build_scout_ui_action_plan(
    *,
    surface: str,
    request_text: str = "",
    preset: str | None = None,
    target_kind: str | None = None,
    target_ref: str | None = None,
    query: str | None = None,
    tab: str | None = None,
) -> dict[str, Any]:
    normalized_surface = _normalize_surface(surface)
    request = request_text.strip()
    warnings: list[str] = []

    if _looks_like_forbidden_direct_action(request):
        return _unsupported_plan(
            normalized_surface,
            request,
            unsupported_reason="forbidden_runtime_or_outbound_action",
            warnings=[
                "UI action planner refuses direct safety, SOS, outbound, runtime, or hardware commands.",
            ],
        )

    action: dict[str, Any] | None = None
    normalized_preset = _normalize_preset(preset) if preset else None
    if normalized_preset:
        action = _layer_preset_action(normalized_surface, normalized_preset)
    elif target_kind or target_ref:
        action = _focus_target_action(
            normalized_surface,
            target_kind=target_kind or "map_target",
            target_ref=target_ref or "selected",
        )
    elif query:
        action = _workspace_search_action(normalized_surface, query)
    elif tab:
        action = _tab_action(normalized_surface, tab)
    else:
        action = _infer_action_from_text(normalized_surface, request)

    if action is None:
        return _unsupported_plan(
            normalized_surface,
            request,
            unsupported_reason="no_allowlisted_ui_action_matched",
            warnings=[
                "No allowlisted UI action matched this request. Scout AI should answer with instructions or ask for a more specific UI target.",
            ],
        )

    if action.get("workspace_write_intent"):
        warnings.append(
            "This is only a UI plan for a confirmation-gated workspace control; the planner does not write workspace files."
        )
    if action.get("requires_confirmation"):
        warnings.append("Frontend must require explicit user confirmation before applying this action.")

    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "status": "planned",
        "surface": normalized_surface,
        "request_text": request,
        "action_count": 1,
        "actions": [_with_action_id(normalized_surface, action, 1)],
        "front_end_executor": {
            "global": "window.ScoutAssistantUI.applyUiActionPlan",
            "session_only": True,
            "requires_allowlist": True,
        },
        "boundary": _boundary(),
        "warnings": warnings,
    }


def _infer_action_from_text(surface: str, request: str) -> dict[str, Any] | None:
    text = request.lower()
    if not text:
        return None
    if _looks_like_risk_only(text):
        return _layer_preset_action(surface, "risk_only")
    if any(term in text for term in ("全部圖層", "所有圖層", "all layers", "完整地圖")) and any(
        term in text for term in ("打開", "開啟", "顯示", "show", "enable")
    ):
        return _layer_preset_action(surface, "all_layers")
    if any(term in text for term in ("主路", "route only", "route context", "路線")) and any(
        term in text for term in ("只留下", "只顯示", "only", "留下")
    ):
        return _layer_preset_action(surface, "route_context")
    if any(term in text for term in ("關閉影像", "關掉影像", "關閉底圖", "關掉底圖", "hide basemap")):
        return _layer_visibility_action(
            surface,
            visible_layers=[layer for layer in SURFACE_LAYER_IDS[surface] if layer not in BASEMAP_LAYER_IDS],
            label="Hide basemap layers",
        )
    if "zoom in" in text or "放大" in text:
        return _click_control_action(surface, "zoomIn", "Zoom in one step")
    if "zoom out" in text or "縮小" in text:
        return _click_control_action(surface, "zoomOut", "Zoom out one step")
    if any(term in text for term in ("fit route", "整條路線", "縮放回", "fit")):
        return _click_control_action(surface, "fitRoute", "Fit route to map")
    if "timeline" in text or "debug_event" in text:
        return _focus_target_action(
            surface,
            target_kind="timeline_event",
            target_ref=_extract_debug_event_ref(request) or "selected",
        )
    cp_ref = _extract_cp_ref(request)
    if cp_ref:
        return _focus_target_action(surface, target_kind="checkpoint", target_ref=cp_ref)
    if any(term in text for term in ("selected evidence", "選取的 evidence", "目前選取")) and "cp" not in text:
        return _focus_target_action(surface, target_kind="selected_evidence", target_ref="selected")
    if "搜尋" in text or "search" in text or ("workspace" in text and any(term in text for term in ("有關", "關於", "查詢", "find"))):
        return _workspace_search_action(surface, _search_query_from_text(request))
    if "review" in text and any(term in text for term in ("頁籤", "tab", "切到", "打開")):
        return _tab_action(surface, "review_workspace")
    if "blocker" in text and "review" in text:
        return _review_filter_action(surface, severity="blocker")
    if "select visible" in text or "可見的 review" in text:
        return _click_control_action(surface, "reviewSelectVisible", "Select visible review items")
    if "select map" in text or "地圖範圍" in text:
        return _click_control_action(surface, "reviewSelectViewport", "Select review items in map viewport")
    if ("clear" in text or "清除" in text or "清空" in text) and "review" in text:
        return _click_control_action(surface, "reviewClearSelection", "Clear review selection")
    if "accept" in text and "review" in text:
        return _click_control_action(
            surface,
            "workspaceAcceptSelectedReviews",
            "Accept selected review items",
            requires_confirmation=True,
            workspace_write_intent=True,
        )
    if "reject" in text and "review" in text:
        return _click_control_action(
            surface,
            "workspaceRejectSelectedReviews",
            "Reject selected review items",
            requires_confirmation=True,
            workspace_write_intent=True,
        )
    if ("新增" in text or "add" in text) and "cp" in text:
        return _click_control_action(
            surface,
            "addCheckpoint",
            "Add checkpoint from selected map coordinate",
            requires_confirmation=True,
            workspace_write_intent=True,
            required_context=["selected_map_coordinate"],
        )
    if ("刪除" in text or "remove" in text or "delete" in text) and "cp" in text:
        return _click_control_action(
            surface,
            "removeCheckpoint",
            "Remove selected checkpoint",
            requires_confirmation=True,
            workspace_write_intent=True,
            required_context=["selected_checkpoint"],
        )
    return None


def _layer_preset_catalog() -> list[dict[str, Any]]:
    return [
        {
            "preset_id": "risk_only",
            "label": "Risk score related layers only",
            "visible_layers": list(RISK_LAYER_IDS),
        },
        {
            "preset_id": "all_layers",
            "label": "Enable every available surface layer",
            "visible_layers": "all_surface_layers",
        },
        {
            "preset_id": "route_context",
            "label": "Route corridor, route, segment, CP, and MCP layers",
            "visible_layers": list(ROUTE_CONTEXT_LAYER_IDS),
        },
    ]


def _layer_preset_action(surface: str, preset: str) -> dict[str, Any]:
    if preset == "risk_only":
        return _layer_visibility_action(
            surface,
            visible_layers=list(RISK_LAYER_IDS),
            label="Show only Scout risk layers",
            preset_id=preset,
        )
    if preset == "all_layers":
        return _layer_visibility_action(
            surface,
            visible_layers=list(SURFACE_LAYER_IDS[surface]),
            label="Show all map layers",
            preset_id=preset,
        )
    if preset == "route_context":
        return _layer_visibility_action(
            surface,
            visible_layers=[layer for layer in ROUTE_CONTEXT_LAYER_IDS if layer in SURFACE_LAYER_IDS[surface]],
            label="Show route context layers",
            preset_id=preset,
        )
    raise ValueError(f"unsupported UI layer preset: {preset}")


def _layer_visibility_action(
    surface: str,
    *,
    visible_layers: list[str],
    label: str,
    preset_id: str | None = None,
) -> dict[str, Any]:
    surface_layers = list(SURFACE_LAYER_IDS[surface])
    visible = [layer for layer in visible_layers if layer in surface_layers]
    hidden = [layer for layer in surface_layers if layer not in visible]
    action = {
        "action_kind": "set_layer_visibility",
        "label": label,
        "surface": surface,
        "selector_strategy": "data-layer-checkbox",
        "visible_layers": visible,
        "hidden_layers": hidden,
        "requires_confirmation": False,
        "session_only": True,
        "workspace_write_intent": False,
    }
    if preset_id:
        action["preset_id"] = preset_id
        action["action_kind"] = "set_layer_preset"
    return action


def _click_control_action(
    surface: str,
    control_id: str,
    label: str,
    *,
    requires_confirmation: bool = False,
    workspace_write_intent: bool = False,
    required_context: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "action_kind": "click_control",
        "label": label,
        "surface": surface,
        "control_id": control_id,
        "selector": f"#{control_id}",
        "requires_confirmation": requires_confirmation,
        "session_only": True,
        "workspace_write_intent": workspace_write_intent,
        "required_context": required_context or [],
    }


def _focus_target_action(surface: str, *, target_kind: str, target_ref: str) -> dict[str, Any]:
    return {
        "action_kind": "focus_map_target",
        "label": f"Focus map target {target_ref}",
        "surface": surface,
        "target_kind": target_kind,
        "target_ref": target_ref,
        "show_label": True,
        "requires_confirmation": False,
        "session_only": True,
        "workspace_write_intent": False,
    }


def _workspace_search_action(surface: str, query: str) -> dict[str, Any]:
    return {
        "action_kind": "workspace_search",
        "label": "Search Scout workspace evidence",
        "surface": surface,
        "query": query.strip() or "workspace facts",
        "tool_id": "scout.kb.query",
        "requires_confirmation": False,
        "session_only": True,
        "workspace_write_intent": False,
    }


def _tab_action(surface: str, tab_id: str) -> dict[str, Any]:
    return {
        "action_kind": "set_tab",
        "label": f"Open {tab_id} tab",
        "surface": surface,
        "tab_id": tab_id,
        "selector": f'[data-tab="{tab_id}"]',
        "requires_confirmation": False,
        "session_only": True,
        "workspace_write_intent": False,
    }


def _review_filter_action(surface: str, *, severity: str) -> dict[str, Any]:
    return {
        "action_kind": "set_review_filter",
        "label": f"Filter review queue by {severity}",
        "surface": surface,
        "severity": severity,
        "control_id": "reviewSeverityFilter",
        "requires_confirmation": False,
        "session_only": True,
        "workspace_write_intent": False,
    }


def _with_action_id(surface: str, action: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "action_id": f"ui_action.{surface}.{action['action_kind']}.{index:03d}",
        **action,
    }


def _unsupported_plan(
    surface: str,
    request_text: str,
    *,
    unsupported_reason: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "status": "unsupported",
        "surface": surface,
        "request_text": request_text,
        "action_count": 0,
        "actions": [],
        "unsupported_reason": unsupported_reason,
        "boundary": _boundary(),
        "warnings": warnings,
    }


def _boundary() -> dict[str, bool]:
    return {
        "ui_session_state_only": True,
        "action_plan_only": True,
        "workspace_file_write_allowed": False,
        "runtime_safety_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
        "hardware_control_performed": False,
        "model_output_is_runtime_truth": False,
    }


def _normalize_surface(surface: str | None) -> str:
    normalized = (surface or "").strip().lower().replace("-", "_")
    aliases = {
        "after_action": "admin",
        "after-action": "admin",
        "admin_after_action": "admin",
        "pre_trip": "pretrip",
        "pre-trip": "pretrip",
        "admin_pretrip": "pretrip",
        "runtime_debug": "debug",
        "admin_debug": "debug",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_SURFACES:
        raise ValueError(f"unsupported UI surface: {surface}")
    return normalized


def _normalize_preset(preset: str) -> str:
    normalized = preset.strip().lower().replace("-", "_")
    aliases = {
        "risk": "risk_only",
        "risk_score": "risk_only",
        "risk_layers": "risk_only",
        "risk_only_layers": "risk_only",
        "all": "all_layers",
        "all_layer": "all_layers",
        "route": "route_context",
        "route_only": "route_context",
    }
    return aliases.get(normalized, normalized)


def _looks_like_risk_only(text: str) -> bool:
    has_risk = any(term in text for term in ("risk", "風險", "baseline", "calibrated", "delta"))
    has_only = any(term in text for term in ("只留下", "只顯示", "only", "關掉所有", "關閉所有", "hide all"))
    return has_risk and has_only


def _looks_like_forbidden_direct_action(text: str) -> bool:
    normalized = text.lower()
    blocked_terms = (
        "sos",
        "sms",
        "satellite",
        "發送",
        "通報",
        "報案",
        "/safety/",
        "觸發ln",
        "觸發 l",
        "gpioset",
        "hardware control",
        "runtime mutation",
    )
    return any(term in normalized for term in blocked_terms)


def _extract_debug_event_ref(text: str) -> str | None:
    for token in text.replace(",", " ").split():
        if token.startswith("debug_event."):
            return token.strip().rstrip("。.,，;；")
    return None


def _extract_cp_ref(text: str) -> str | None:
    normalized = text.replace("-", "").replace("_", "").upper()
    marker = "CP"
    index = normalized.find(marker)
    if index < 0:
        return None
    digits = []
    for char in normalized[index + len(marker) :]:
        if char.isdigit():
            digits.append(char)
        elif digits:
            break
    if not digits:
        return None
    return f"CP{int(''.join(digits)):03d}"


def _search_query_from_text(text: str) -> str:
    for separator in ("：", ":", "有關", "關於"):
        if separator in text:
            candidate = text.split(separator, 1)[1].strip()
            if candidate:
                return candidate
    return text.strip()
