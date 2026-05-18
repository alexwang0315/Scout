# Continuation Prompt: Scout Cross-Surface AI Assistant

Use this prompt in a new Codex conversation.

```text
請在 /Users/alexwang0315/scout-fusion 繼續 Scout 的 Milestone 10: Cross-Surface AI Assistant Guardrails。

背景狀態：
- Phase 1 / Phase 2 / Phase 3 integration gate 已完成。
- Phase 3.5 Runtime Readiness and Debug Tooling 已完成：
  - /debug JSON API read-only
  - /admin/debug runtime debug UI
  - runtime debug event log
  - simulator/replay demo
  - mock outbound transport
  - phase35_runtime_readiness_check.py ok: true
  - focused Phase 3.5 + Phase 1/3 boundary tests 已通過
- Phase 4 是 pre-trip planning workspace，不應混進 Phase 3.5 core。

請先讀這些文件：
- docs/specs/scout-cross-surface-ai-assistant.md
- docs/specs/phase-3-5-runtime-readiness-debug-tooling.md
- docs/specs/pre-trip-planning-admin.md
- docs/specs/scout-admin-ui-direction.md
- agent.py
- server.py
- debug_api.py
- docs/admin/phase-3-5-runtime-debug.html

目標：
建立 Scout 全域的 cross-surface AI assistant capability，讓 admin、debug、pre-planning、future hardware readiness 介面都能接入 Pydantic AI 或 mock assistant，回答目前資料狀態與「為什麼系統這樣判斷」。

重要邊界：
- 不改 Phase 1 safety decision。
- 不呼叫 /safety/* mutation。
- 不寫 ObservedFact。
- 不寫 Phase 2 Brain。
- 不改 IncidentStore。
- 不接受或拒絕 pre-trip candidate。
- 不改 HumanReview / review decision。
- 不送 outbound message。
- 不接真 SOS / 真簡訊 / 真衛星。
- 不控制硬體或 provider。
- Pydantic AI provider 必須 opt-in，預設先用 deterministic/mock provider。
- AI 回答必須標示為 read-only model interpretation。

請採用 spec-first / incremental / TDD：
1. 先做 repo exploration，確認現有 admin/debug/pretrip surface 的資料來源與測試慣例。
2. 不要直接做大型 UI 或真模型串接。
3. 先提出小 slice plan，除非我明確要求實作。
4. 第一個實作 slice 建議是 assistant request/response Pydantic models + deterministic mock provider + focused tests。

建議 slice：
1. Assistant models / contract
   - ScoutAssistantQuery
   - ScoutAssistantResponse
   - AssistantBoundary
   - AssistantSourceRef
   - per-surface constraint enum
   - tests/test_assistant_models.py

2. Mock assistant provider
   - deterministic response
   - no network
   - no store writes
   - tests/test_assistant_provider.py

3. Context adapter foundation
   - debug_assistant_context.py
   - admin_assistant_context.py
   - pretrip_assistant_context.py
   - bounded read-only context

4. Read-only assistant API
   - POST /assistant/query as read-only query body endpoint
   - opt-in mount only with SCOUT_AI_ASSISTANT_ENABLED=1
   - provider defaults to mock
   - no PUT/PATCH/DELETE

5. Shared assistant UI shell
   - no action buttons
   - show surface, answer, limitations, sources, read-only boundary
   - start with /admin/debug + /admin/pretrip

6. Pydantic AI opt-in provider
   - separate from /navigate
   - timeout/context budget
   - prompt injection guardrails
   - failure isolated

請用中文回覆，並保持 Scout 的 phase 邊界清楚。
```
