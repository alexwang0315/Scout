# Scout Diagnostic 分類契約

Scout 的 Diagnostic 分成兩條互不混算的驗收軌道。

## A. Scout AI Score

這條軌道測量 Scout AI 的能力，不要求「bug free」或 100% PASS。失敗會降低分數，並保留案例、工具呼叫、證據與回答品質，作為模型能力與版本趨勢指標。

| family | 測量內容 | 失敗的處理 |
| --- | --- | --- |
| `answer_quality` | 是否回答正確、完整、符合問題 | 記為分數與案例，不直接判定程式 bug |
| `tool_grounding` | 是否選對工具、取得足夠證據並正確引用 | 分開模型問題、工具問題與資料缺口 |
| `domain_reasoning` | 六力、Weather、route context、pace、risk、permission、navigation 的候選推理 | 形成能力分數；涉及安全與資料契約的錯誤轉交 Correctness Gate |
| `model_runtime` | DeepSeek、retrieval、model gateway、Praison MCP 與回答流程能力 | 記錄 provider／模型能力退化，不吸收 correctness FAIL |

目前屬於這條軌道的測試包括：Cloud DeepSeek policy、Builtin eval、Weather candidate、Same-version integrated 中的 AI answer/evidence 部分、Recorded trace、workspace retrieval、tool selection、CWA／GEE／Weather decision、route context 與六力分析。

Weather 的 `130/231 PASS` 是混合結果，必須在報告中再拆成回答品質、工具證據、資料缺口與決策整合，不能直接當成 101 個模型 bug。

## B. Correctness Gate

這條軌道測量程式與資料是否正確。這裡的目標是所有適用檢查 100% PASS；FAIL、WARN、SKIP 或未驗證都不能宣稱完成。

| family | 測量內容 | 失敗的處理 |
| --- | --- | --- |
| `workspace_and_identity` | project、workspace、Golden GPX、source SHA 是否正確綁定 | 可能是 bug；不同 workspace 不進行 historical 比較 |
| `dashboard_and_map` | 所有 Dashboard 地圖、圖磚、向量、縮放、平移、恢復與 layer contract | 使用者可見功能錯誤，需修正或明確保留阻塞 |
| `artifact_and_serialization` | metadata、optional 欄位、Pydantic roundtrip、GPX／彙整資料與 artifact binding | 資料契約錯誤，不能用 AI 分數抵銷 |
| `runtime_and_safety` | runtime graph、目錄順序、candidate-only、runtime safety truth、no-write guard | correctness／安全問題，立即追根因 |
| `release_and_fixture` | Release capture、project matrix、fixture hygiene、builder 自洽 | 必須修正或取得明確規格裁決 |

Release capture、Artifact 5、Runtime graph、Matrix candidate、fixture hygiene、DASH-001～DASH-050 的 Dashboard／地圖／runtime 檢查，原則上都屬於 Correctness Gate。它們不是 Scout AI 聰明程度的分數。

## 結果呈現規則

報告必須同時輸出兩個 summary，禁止只輸出一個總 PASS／FAIL：

```text
scout_ai_score:
  score: <0..100>
  cases: <n>
  pass: <n>
  fail: <n>
  trend: <previous comparison>

correctness_gate:
  applicable: <n>
  pass: <n>
  fail: <n>
  warning: <n>
  unverified: <n>
  release_ready: true only when every applicable item is PASS
```

兩條軌道的失敗不能互相抵銷：AI 分數低不代表程式有 bug；Correctness Gate FAIL 也不能用模型分數高來掩蓋。

## Historical 與 Golden GPX

Historical 只是一個同一 workspace、同一來源身分下的參考版本。Golden GPX 可以替換，不能把舊名稱、數量或大小永久寫成標準答案。workspace 或 Golden 身分不同時，結果應為 `NOT_APPLICABLE`，不得比較，更不能因此產生 FAIL。
