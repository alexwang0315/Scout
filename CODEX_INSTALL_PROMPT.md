# Prompt 給 Codex 使用

請在目前 Scout 專案中安裝並整合我提供的 `scout-skill-starter-pack`。請依照以下步驟執行：

1. 將起步包內容合併到 repo root，保留既有檔案；若有衝突，先列出差異再採用最小破壞合併。
2. 確認以下檔案存在：
   - `.github/PULL_REQUEST_TEMPLATE/scout-skill.md`
   - `.codex/checklist.yaml`
   - `skills/example_scout_skill/schemas.py`
   - `tests/test_example_scout_skill_schemas.py`
   - `docs/example_scout_skill-api.md`
   - `observability/example_scout_skill-events.md`
   - `Makefile`
3. 依 Scout 專案現有結構調整 import path；若 repo 已有 `pyproject.toml`，把 `pydantic`, `pytest`, `pyyaml` 合併進 dev dependencies，不要重複建立衝突設定。
4. 執行：
   ```bash
   make install
   make test
   ```
5. 如果測試失敗，修正到通過為止。
6. 新增一個 Codex governance check：
   - 驗證 `schema_version` 是否存在且符合 semver。
   - 驗證 valid/edge/invalid example 是否符合 Pydantic 預期。
   - 驗證 high risk 必須有 HITL 規則。
   - 驗證 telemetry required fields 齊全。
7. 建立一個 draft PR，標籤：
   - `scout-governance/v1`
   - `schema:minor`
   - `risk:low`
8. PR 描述請使用 `.github/PULL_REQUEST_TEMPLATE/scout-skill.md`，並填入本次整合內容。
9. 完成後回報：
   - 新增/修改檔案清單
   - 測試結果
   - 未解決風險
   - 後續建議

重要原則：
- 不要刪除既有 Scout 功能。
- 不要硬編碼 secret。
- 不要把 raw PII 寫入 log。
- 高風險或低信心動作必須進 HITL。
