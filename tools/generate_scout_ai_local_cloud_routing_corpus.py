"""Generate the 100-question local/cloud routing corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/specs/scout-ai-local-cloud-routing-100-question-corpus.json"
DEFAULT_MARKDOWN_OUTPUT = ROOT / "docs/specs/scout-ai-local-cloud-routing-100-question-corpus.md"


def local(question_id: str, question: str, answer: str, category: str) -> dict:
    return {
        "question_id": question_id,
        "question": question,
        "category": category,
        "expected_route": "local",
        "capabilities": ["static_fact"],
        "standard_answer": answer,
        "answer_contract": {"kind": "exact", "expected": answer},
        "source_refs": ["prompt://given-facts"],
        "required_tools": [],
        "cloud_reason": None,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def cloud(
    question_id: str,
    question: str,
    category: str,
    capability: str,
    tool: str,
    reason: str,
) -> dict:
    return {
        "question_id": question_id,
        "question": question,
        "category": category,
        "expected_route": "cloud",
        "capabilities": [capability],
        "standard_answer": "需取得外部或 workspace 證據後回答；不能用固定答案代替查證。",
        "answer_contract": {
            "kind": "evidence_grounded",
            "expected": None,
            "required_fields": ["answer", "source_refs", "freshness_or_unknowns"],
            "must_state_unknowns": True,
        },
        "source_refs": [f"tool://{tool}"],
        "required_tools": [tool],
        "cloud_reason": reason,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


LOCAL_CASES = [
    local("LOCAL-001", "已知路段 A 為 3.5 公里、B 為 2.25 公里，合計幾公里？", "5.75 公里", "arithmetic"),
    local("LOCAL-002", "把 2 小時 30 分鐘換算成分鐘，答案是多少？", "150 分鐘", "unit_conversion"),
    local("LOCAL-003", "將 4,500 公尺換算成公里，保留小數兩位。", "4.50 公里", "unit_conversion"),
    local("LOCAL-004", "每小時走 3 公里，走 2 小時 20 分鐘的距離是多少？", "7 公里", "arithmetic"),
    local("LOCAL-005", "起點海拔 420 公尺、終點海拔 1,020 公尺，爬升多少？", "600 公尺", "arithmetic"),
    local("LOCAL-006", "四段距離分別為 1.2、0.8、2.5、1.5 公里，總長是多少？", "6.0 公里", "arithmetic"),
    local("LOCAL-007", "剩餘 9 公里，平均速度 3 公里／小時，估計需要幾小時？", "3 小時", "arithmetic"),
    local("LOCAL-008", "將 75 分鐘加上 1 小時 10 分鐘，總共幾分鐘？", "145 分鐘", "arithmetic"),
    local("LOCAL-009", "里程從 12.4 公里增加到 15.1 公里，增加多少？", "2.7 公里", "arithmetic"),
    local("LOCAL-010", "一箱有 24 瓶水，分給 6 人且平均分配，每人幾瓶？", "4 瓶", "arithmetic"),
    local("LOCAL-011", "海拔 1,250 公尺下降到 980 公尺，下降多少？", "270 公尺", "arithmetic"),
    local("LOCAL-012", "路線全長 18 公里，已走 7.5 公里，剩餘多少？", "10.5 公里", "arithmetic"),
    local("LOCAL-013", "三個檢查點間距為 2、3.5、1.5 公里，這三段合計多少？", "7 公里", "arithmetic"),
    local("LOCAL-014", "一個坡段長 800 公尺，來回一次，總距離是多少？", "1,600 公尺", "arithmetic"),
    local("LOCAL-015", "把 0.75 公里換算成公尺。", "750 公尺", "unit_conversion"),
    local("LOCAL-016", "資料卡寫著 CP=12、MCP=4、休息點=3。CP 數是多少？", "12", "structured_extraction"),
    local("LOCAL-017", "資料卡寫著總長 21.4 km、爬升 860 m。總長是多少？", "21.4 公里", "structured_extraction"),
    local("LOCAL-018", "表格欄位為 route_name=東段、surface=土路、grade=12%。surface 的值是什麼？", "土路", "structured_extraction"),
    local("LOCAL-019", "紀錄為 start=08:10、break=00:20、finish=15:40。start 是幾點？", "08:10", "structured_extraction"),
    local("LOCAL-020", "清單依序是入口、溪溝、鞍部、終點。第三個項目是什麼？", "鞍部", "structured_extraction"),
    local("LOCAL-021", "JSON 摘要為 {\"status\":\"ready\",\"count\":8}。status 是什麼？", "ready", "structured_extraction"),
    local("LOCAL-022", "欄位 elevation_m=1,234、segment_id=S07。elevation_m 是多少？", "1,234 公尺", "structured_extraction"),
    local("LOCAL-023", "資料列的 weather_source 是 cwa，rain_probability_pct 是 40。來源是什麼？", "cwa", "structured_extraction"),
    local("LOCAL-024", "路線標籤為 northbound，方向欄位的值是什麼？", "northbound", "structured_extraction"),
    local("LOCAL-025", "檔案有 5 個候選點，其中第 2 個標記 requires_human_review=true。該標記值是什麼？", "true", "structured_extraction"),
    local("LOCAL-026", "一筆紀錄含有 source=survey、confidence=0.8。source 欄位內容是什麼？", "survey", "structured_extraction"),
    local("LOCAL-027", "表格的四欄是 id、name、distance_km、note；第三欄名稱是什麼？", "distance_km", "structured_extraction"),
    local("LOCAL-028", "訊息標籤為 [route, terrain, candidate]。第二個標籤是什麼？", "terrain", "structured_extraction"),
    local("LOCAL-029", "摘要寫著 freshness=stale、candidate_only=true。freshness 是什麼？", "stale", "structured_extraction"),
    local("LOCAL-030", "記錄為 {\"temperature_c\":18.5,\"unit\":\"C\"}。溫度數值是多少？", "18.5°C", "structured_extraction"),
    local("LOCAL-031", "已知 A=8、B=5。A 是否大於 B？只回答是或否。", "是", "comparison"),
    local("LOCAL-032", "已知路段長度 4 公里且上限為 5 公里，是否超過上限？只回答是或否。", "否", "comparison"),
    local("LOCAL-033", "若資料標記 stale，是否等同於資料為零？只回答是或否。", "否", "boundary"),
    local("LOCAL-034", "若欄位值為 null，是否可以直接回答為 0？只回答是或否。", "否", "boundary"),
    local("LOCAL-035", "若來源標為 candidate，是否等同於 runtime safety truth？只回答是或否。", "否", "boundary"),
    local("LOCAL-036", "若題目只給觀察值，能否直接宣稱造成觀察的原因？只回答是或否。", "否", "boundary"),
    local("LOCAL-037", "若單位是毫米，能否不換算就當成公尺？只回答是或否。", "否", "unit_discipline"),
    local("LOCAL-038", "若兩個資料來源數值不同，是否應保留衝突而不是任選一個？只回答是或否。", "是", "evidence_boundary"),
    local("LOCAL-039", "若題目明確提供所有運算數字，是否需要 web search 才能計算？只回答是或否。", "否", "routing_boundary"),
    local("LOCAL-040", "若答案契約要求 exact，回答時是否應加入未提供的推測背景？只回答是或否。", "否", "answer_contract"),
    local("LOCAL-041", "標準答案要求列出三個欄位，但輸入只提供兩個，應填空白還是指出缺欄？", "指出缺欄", "evidence_gap"),
    local("LOCAL-042", "一個數字標記為 60%，它的單位應回答百分比還是毫米？", "百分比", "unit_discipline"),
    local("LOCAL-043", "題目說只回答 CP 數；資料是 CP=9、MCP=2。應回答哪個數字？", "9", "instruction_following"),
    local("LOCAL-044", "若輸入明確寫著 eastbound，eastbound 的反方向是什麼？", "westbound", "label_mapping"),
    local("LOCAL-045", "三個值為 2、2、3；最大值是多少？", "3", "comparison"),
    local("LOCAL-046", "三個值為 2、2、3；最小值是多少？", "2", "comparison"),
    local("LOCAL-047", "若 A=10 且 B=10，A 與 B 的關係是什麼？", "相等", "comparison"),
    local("LOCAL-048", "資料列有 4 個項目，其中 1 個是 null。非 null 項目有幾個？", "3 個", "counting"),
    local("LOCAL-049", "路段標記為 dry。dry 的中文是什麼？", "乾燥", "translation"),
    local("LOCAL-050", "route_summary 的中文可翻成什麼？", "路線摘要", "translation"),
    local("LOCAL-051", "候選結果若 candidate_only=true，最安全的描述是「候選結果」還是「已核准結果」？", "候選結果", "safety_boundary"),
    local("LOCAL-052", "未提供座標時，能否回答精確經緯度？只回答是或否。", "否", "evidence_boundary"),
    local("LOCAL-053", "未提供來源時，能否把一般常識寫成 workspace 事實？只回答是或否。", "否", "source_boundary"),
    local("LOCAL-054", "若題目要求繁體中文，是否應使用簡體中文作答？只回答是或否。", "否", "language"),
    local("LOCAL-055", "若輸入是 90 分鐘，換算為幾小時幾分鐘？", "1 小時 30 分鐘", "unit_conversion"),
    local("LOCAL-056", "若 1 公里等於 1,000 公尺，6.2 公里等於多少公尺？", "6,200 公尺", "unit_conversion"),
    local("LOCAL-057", "若坡度欄位為 0%，應回答有坡度還是無坡度？", "無坡度", "structured_interpretation"),
    local("LOCAL-058", "若狀態欄位為 ready，ready 的中文是什麼？", "就緒", "translation"),
    local("LOCAL-059", "若輸入只有一個明確答案，回答應選一個答案還是列出三個猜測？", "選一個答案", "answer_contract"),
    local("LOCAL-060", "若題目明確給出 20-8，結果是多少？", "12", "arithmetic"),
    local("LOCAL-061", "若題目明確給出 7×6，結果是多少？", "42", "arithmetic"),
    local("LOCAL-062", "若題目明確給出 81÷9，結果是多少？", "9", "arithmetic"),
    local("LOCAL-063", "若 5 個相同物品平均分給 5 人，每人幾個？", "1 個", "arithmetic"),
    local("LOCAL-064", "若原值 10、增加 25%，新值是多少？", "12.5", "arithmetic"),
    local("LOCAL-065", "若距離 10 公里中已完成 40%，完成距離是多少？", "4 公里", "arithmetic"),
    local("LOCAL-066", "若資料排序為低、中、高，第二個等級是什麼？", "中", "ordering"),
    local("LOCAL-067", "若布林欄位為 false，中文應回答真還是假？", "假", "structured_extraction"),
    local("LOCAL-068", "若資料的 freshness 是 fresh，中文應回答新鮮、最新或過期？", "最新", "translation"),
    local("LOCAL-069", "若答案只需回傳 JSON 欄位 answer，是否應加入 markdown code fence？只回答是或否。", "否", "format"),
    local("LOCAL-070", "若問題不涉及即時資料、web 或工具，預設應選本地還是雲端？", "本地", "routing_boundary"),
]


CLOUD_CASES = [
    cloud("CLOUD-071", "查詢今天八通關古道沿線的即時降雨與有效時間。", "current_weather", "fresh_live_data", "scout_weather_tool", "需要即時天氣與 freshness/TTL。"),
    cloud("CLOUD-072", "查詢今天玉山區域的日落時間，並附官方來源。", "current_daylight", "web_search", "scout_web_search", "需要當日資料與外部來源。"),
    cloud("CLOUD-073", "查詢目前官方是否對該路線發布封閉或管制公告。", "current_regulation", "web_search", "scout_web_search", "需要最新官方公告。"),
    cloud("CLOUD-074", "查詢本週末路線所在地的天氣預報，並比較降雨機率與 QPF。", "forecast", "web_search", "scout_web_search", "需要 web search、時間有效性與單位辨識。"),
    cloud("CLOUD-075", "查詢最近一次官方山域警報，判斷是否涵蓋這條路線。", "warning", "web_search", "scout_web_search", "需要最新警報與路線範圍比對。"),
    cloud("CLOUD-076", "從 workspace 找出所有 checkpoint candidate 並計算數量。", "workspace_aggregate", "tool_use", "scout_workspace_query", "需要 workspace tool 讀取與聚合。"),
    cloud("CLOUD-077", "從 workspace 找出 requires_human_review=true 的地形候選。", "workspace_filter", "tool_use", "scout_workspace_query", "需要條件篩選 workspace artifact。"),
    cloud("CLOUD-078", "把 route_summary 與 route_mileage_k_anchors 對照，找出里程不一致處。", "cross_artifact_join", "cross_artifact_join", "scout_workspace_query", "需要跨 artifact join 與衝突證據。"),
    cloud("CLOUD-079", "找出與 route corridor 相交的風險段，並列出來源 artifact。", "spatial_join", "spatial_query", "scout_gis_spatial", "需要 GIS 空間相交查詢。"),
    cloud("CLOUD-080", "判斷某個候選崩塌點是否位於目前路線 buffer 內。", "spatial_join", "spatial_query", "scout_gis_spatial", "需要座標與空間 buffer 計算。"),
    cloud("CLOUD-081", "查詢這個歷史地名的由來，並比較至少兩個可追溯來源。", "historical_research", "web_search", "scout_web_search", "需要外部歷史資料與來源比較。"),
    cloud("CLOUD-082", "查詢八通關古道某段的文化脈絡，區分已證實與推測內容。", "cultural_research", "web_search", "scout_web_search", "需要研究資料與來源歸因。"),
    cloud("CLOUD-083", "查詢目前官方入山或進入許可要求，並附有效日期。", "permission", "web_search", "scout_web_search", "法規與許可會變動，需查官方來源。"),
    cloud("CLOUD-084", "比較 workspace 中兩份 GPX 的總長與通過點，說明差異來源。", "artifact_comparison", "cross_artifact_join", "scout_workspace_query", "需要讀取並比較多個 artifact。"),
    cloud("CLOUD-085", "從 workspace 讀取最新 weather_daylight_evidence 並檢查是否過期。", "freshness", "fresh_live_data", "scout_workspace_query", "需要讀取 timestamp、valid_to 與 TTL。"),
    cloud("CLOUD-086", "查詢目前 route context 的生成版本、來源與 hash。", "runtime_metadata", "tool_use", "scout_workspace_query", "需要 workspace metadata/tool read。"),
    cloud("CLOUD-087", "把路線高程段與風險分數做空間及 segment join，列出最高三段。", "spatial_aggregate", "spatial_query", "scout_gis_spatial", "需要 GIS join、排序與聚合。"),
    cloud("CLOUD-088", "查詢指定日期是否有颱風或豪雨警報影響路線所在行政區。", "historical_weather", "web_search", "scout_web_search", "需要日期限定的外部歷史資料。"),
    cloud("CLOUD-089", "查詢目前交通或道路進入條件，並與 workspace 起點位置對照。", "access", "cross_artifact_join", "scout_web_search", "需要外部現況與 workspace location join。"),
    cloud("CLOUD-090", "根據最新天氣、路線暴露段與日落時間產生候選風險摘要。", "weather_route_compound", "safety_sensitive", "scout_weather_tool", "需要多來源證據；JEV 不得直接授權安全行動。"),
    cloud("CLOUD-091", "查詢當前溪流水位或上游降雨，再比對路線渡涉點。", "hydrology", "fresh_live_data", "scout_weather_tool", "需要即時環境資料與路線工具。"),
    cloud("CLOUD-092", "查詢指定座標附近目前是否有道路施工或封閉資訊。", "current_access", "web_search", "scout_web_search", "需要即時 web search 與座標關聯。"),
    cloud("CLOUD-093", "從 workspace 找出所有缺少 source_ref 的候選結果。", "provenance_audit", "tool_use", "scout_workspace_query", "需要讀取並稽核 artifact provenance。"),
    cloud("CLOUD-094", "比較兩個不同時間的 route weather snapshot，判斷哪個較新且仍有效。", "freshness_comparison", "cross_artifact_join", "scout_workspace_query", "需要時間欄位、TTL 與多 artifact 比較。"),
    cloud("CLOUD-095", "查詢官方地圖或公告是否有新的路線名稱或改線資訊。", "route_change", "web_search", "scout_web_search", "需要最新官方來源與歷史比較。"),
    cloud("CLOUD-096", "計算 route corridor 與警報 polygon 是否相交，並列出不相交時的證據缺口。", "warning_spatial", "spatial_query", "scout_gis_spatial", "需要 GIS intersection 與缺證據處理。"),
    cloud("CLOUD-097", "查詢沿線可用的避難或撤退點，再與 workspace route segments 配對。", "retreat_join", "cross_artifact_join", "scout_workspace_query", "需要外部/工作區資料配對。"),
    cloud("CLOUD-098", "查詢官方對該區域的野生動物或環境注意事項，附來源與日期。", "environment_research", "web_search", "scout_web_search", "需要外部官方資料、日期與引用。"),
    cloud("CLOUD-099", "使用最新定位、天氣與路線 evidence，判斷目前資料是否足以形成候選摘要。", "evidence_sufficiency", "safety_sensitive", "scout_workspace_query", "需要即時多源 evidence sufficiency gate。"),
    cloud("CLOUD-100", "若本地模型無法回答某題，查明是否因缺少工具、過期資料或題目需要 web search，並提出升級理由。", "failure_escalation", "tool_use", "scout_workspace_query", "需要檢查工具、freshness 與 failure trace。"),
]


def build_document() -> dict:
    questions = [*LOCAL_CASES, *CLOUD_CASES]
    if len(questions) != 100:
        raise AssertionError(f"expected 100 questions, got {len(questions)}")
    return {
        "schema_version": "scout.ai.local_cloud_routing_corpus.v1",
        "workspace_id": "dongqing_batongguan_historic_trail_newImport",
        "description": "70 題可由短小固定答案處理的 local 題，及 30 題需要 web search、workspace/GIS tool 或即時證據的 cloud 題。",
        "routing_authority": "deterministic_gate_with_jev_advisory",
        "questions": questions,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def markdown_document(document: dict) -> str:
    lines = [
        "# Scout AI local/cloud routing 100 題 corpus",
        "",
        "這是可供 JEV advisory routing 的題庫：70 題 local 使用短小固定答案，30 題 cloud 需要 web search、workspace/GIS tool 或即時證據。JEV 不得把 cloud-required 題降級成本地模型。所有輸出仍是 `candidate_only=true`，不是 runtime safety truth。",
        "",
        "## Routing contract",
        "",
        "- local：`exact` / `choice` / `structured`，無 required tool、無外部資料依賴。",
        "- cloud：`evidence_grounded`，必須附 source refs、freshness 或 unknowns。",
        "- JEV 可以把 local 題 advisory 升級到 cloud，但不能把 cloud-required 題降成 local。JEV、LLM 與模型輸出都不是硬體或安全 authority。",
        "",
        "## 題目",
        "",
        "| ID | route | category | question | standard answer / cloud reason |",
        "|---|---|---|---|---|",
    ]
    for item in document["questions"]:
        answer = item["standard_answer"] if item["expected_route"] == "local" else item["cloud_reason"]
        question = item["question"].replace("|", "\\|")
        answer = str(answer).replace("|", "\\|")
        lines.append(
            f"| `{item['question_id']}` | `{item['expected_route']}` | `{item['category']}` | {question} | {answer} |"
        )
    lines.extend(
        [
            "",
            "## Machine-readable source",
            "",
            "`scout-ai-local-cloud-routing-100-question-corpus.json` 是執行與驗證使用的 canonical artifact；此 Markdown 由 generator 產生。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    document = build_document()
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown_document(document), encoding="utf-8")
    print(f"wrote {args.output} ({len(LOCAL_CASES)} local, {len(CLOUD_CASES)} cloud)")


if __name__ == "__main__":
    main()
