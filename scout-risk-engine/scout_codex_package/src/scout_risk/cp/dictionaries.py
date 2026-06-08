from __future__ import annotations

HAZARD_KEYWORDS: dict[str, list[str]] = {
    "collapse": ["大崩壁", "崩塌", "坍方", "土石流", "崩溝", "落石"],
    "exposure": ["危崖", "斷崖", "瘦稜", "曝露", "兩側深谷"],
    "climbing": ["拉繩", "攀岩", "手腳並用", "陡上", "陡下"],
    "reroute": ["高繞", "低繞", "改道", "不可通行", "路基流失"],
    "valley_water": ["溪溝", "過溪", "下切", "溯溪", "瀑布", "濕滑"],
    "navigation": ["路跡不明", "易迷", "岔路", "布條少", "獸徑"],
    "vegetation": ["箭竹", "芒草", "咬人貓", "倒木", "藤蔓"],
}

HAZARD_BASE_SCORES: dict[str, float] = {
    "collapse": 95.0,
    "exposure": 90.0,
    "climbing": 72.0,
    "reroute": 82.0,
    "valley_water": 70.0,
    "navigation": 68.0,
    "vegetation": 48.0,
}

