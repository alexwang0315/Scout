# example_scout_skill API Contract

## Purpose
示範 Scout Skill 的輸入、輸出、風險控管與人為覆核接口。

## Input
見 `skills/example_scout_skill/schemas.py::ScoutSkillInput`

## Output
見 `skills/example_scout_skill/schemas.py::ScoutSkillOutput`

## Error Codes
- `SCHEMA_VERSION_UNSUPPORTED`
- `VALIDATION_ERROR`
- `HITL_REQUIRED`
- `MODEL_TIMEOUT`
- `TOOL_EXECUTION_FAILED`

## Runtime
- Timeout: 30s
- Retry: 2 次，僅限暫時性錯誤
- High-risk action 必須進入 HITL
