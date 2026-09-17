"""Stable separation between Scout AI scoring and correctness diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DiagnosticPurpose(StrEnum):
    SCOUT_AI_SCORE = "scout_ai_score"
    CORRECTNESS_GATE = "correctness_gate"


@dataclass(frozen=True)
class DiagnosticFamily:
    family_id: str
    purpose: DiagnosticPurpose
    label: str
    description: str
    failure_action: str


SCOUT_AI_SCORE_FAMILIES = (
    DiagnosticFamily(
        "answer_quality",
        DiagnosticPurpose.SCOUT_AI_SCORE,
        "回答能力分數",
        "模型是否能以正確 workspace 證據回答問題；結果作為能力分數，不要求零失敗。",
        "記錄分數、案例、證據缺口與趨勢；不能直接當成程式 bug。",
    ),
    DiagnosticFamily(
        "tool_grounding",
        DiagnosticPurpose.SCOUT_AI_SCORE,
        "工具與證據整合分數",
        "模型是否選對工具、取得足夠證據，並把 Weather、CWA、GEE、GPX 等來源整合到回答。",
        "拆分模型品質、工具缺口、資料缺口；不把所有 FAIL 合併成模型智力問題。",
    ),
    DiagnosticFamily(
        "domain_reasoning",
        DiagnosticPurpose.SCOUT_AI_SCORE,
        "戶外領域推理分數",
        "六力、route context、pace、risk、permission、navigation 等候選分析的完整性與可用性。",
        "形成可比較的分數與案例集；需要人工 review 的安全結論仍由正確性 gate 控制。",
    ),
    DiagnosticFamily(
        "model_runtime",
        DiagnosticPurpose.SCOUT_AI_SCORE,
        "模型 runtime 能力分數",
        "DeepSeek、model gateway、retrieval、Praison MCP 與回答流程的可用能力。",
        "記錄模型／工具／provider 的能力分數與退化，不以單次失敗宣稱程式 bug。",
    ),
)


CORRECTNESS_GATE_FAMILIES = (
    DiagnosticFamily(
        "workspace_and_identity",
        DiagnosticPurpose.CORRECTNESS_GATE,
        "Workspace 與來源身分正確性",
        "確認 project、workspace、Golden GPX、source SHA 與結果沒有錯綁；不同 workspace 不互相比較。",
        "FAIL 即視為可能 bug，立即追根因或提交明確裁決。",
    ),
    DiagnosticFamily(
        "dashboard_and_map",
        DiagnosticPurpose.CORRECTNESS_GATE,
        "Dashboard、地圖與圖磚正確性",
        "確認所有頁面的 renderer、圖磚、向量、縮放、平移、恢復與 map layer contract。",
        "FAIL 代表使用者可見功能不正確，需修正或保留為明確阻塞。",
    ),
    DiagnosticFamily(
        "artifact_and_serialization",
        DiagnosticPurpose.CORRECTNESS_GATE,
        "Artifact 與 serialization 正確性",
        "確認 metadata、optional 欄位、Pydantic 讀寫、GPX／彙整資料與 artifact binding。",
        "FAIL 代表資料契約或綁定可能損壞，不能用 AI 分數吸收。",
    ),
    DiagnosticFamily(
        "runtime_and_safety",
        DiagnosticPurpose.CORRECTNESS_GATE,
        "Runtime 與安全邊界正確性",
        "確認 runtime graph、目錄建立順序、candidate-only、runtime_safety_truth 與 no-write guard。",
        "FAIL 立即視為 correctness／安全問題，不能降級成模型能力分數。",
    ),
    DiagnosticFamily(
        "release_and_fixture",
        DiagnosticPurpose.CORRECTNESS_GATE,
        "Release、matrix 與 fixture 正確性",
        "確認 release gate、project matrix、fixture hygiene 與 current builder 自洽。",
        "FAIL 需修正；current／historical 僅在同一 workspace 身分下依比較政策判定。",
    ),
)


def all_families() -> tuple[DiagnosticFamily, ...]:
    return SCOUT_AI_SCORE_FAMILIES + CORRECTNESS_GATE_FAMILIES


def family_for(family_id: str) -> DiagnosticFamily:
    for family in all_families():
        if family.family_id == family_id:
            return family
    raise KeyError(f"unknown diagnostic family: {family_id}")
