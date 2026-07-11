import os
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
from typing import Literal
from macos_wifi import MacOSWifiWorld
from pydantic_ai_runtime_compat import build_chat_model, pydantic_agent_runtime_kwargs
from scout_env import load_scout_env_files

# 1. 加載環境變量
load_scout_env_files()
api_key = os.getenv('OPENROUTER_API_KEY')

# 2. 使用 Pydantic AI v2 OpenRouter provider，不修改全域 OpenAI env。
model = build_chat_model(
    model_name=os.getenv("SCOUT_WIFI_AGENT_MODEL", "openrouter:google/gemma-4-31b-it"),
    api_key=api_key,
)

class SignalAnalysis(BaseModel):
    ssid: str
    strength: float
    trend: str
    status: str

# 4. 建立 Agent
sos_agent = Agent(
    model, 
    deps_type=MacOSWifiWorld,
    system_prompt=(
        "你現在是 S.C.O.U.T. 生存導航專家。目標是引導用戶找到環境中最強的 Wi-Fi 訊號接點（文明接點）。 "
        "你不需要特定 SSID，你必須始終追蹤當前最強的那個訊號。 "
        "溝通風格：生存導航員型。要帶有緊急感、專業且鼓勵性。 "
        "將 -80dBm 描述為 '微弱的脈動'，-40dBm 描述為 '強烈的生存信號'。 "
        "策略：分析目前最強訊號 -> 對比趨勢 -> 給出明確移動方向。 "
        "當最強訊號達到 -30dBm 以上時，宣布救援成功。"
    ),
    **pydantic_agent_runtime_kwargs(),
)

@sos_agent.tool
async def scan_signal(ctx: RunContext[MacOSWifiWorld]) -> SignalAnalysis:
    """掃描實體環境中目前最強的 Wi-Fi 訊號"""
    best = ctx.deps.get_best_signal()
    current = best['rssi']
    ssid = best['ssid']
    
    # 使用正確的名稱 last_best_strength
    trend = "增強" if current > ctx.deps.last_best_strength else "減弱"
    ctx.deps.last_best_strength = current
    
    status = "Found" if current > -30 else "Searching"
    return SignalAnalysis(ssid=ssid, strength=current, trend=trend, status=status)

@sos_agent.tool
async def move_user(ctx: RunContext[MacOSWifiWorld], direction: Literal['north', 'south', 'east', 'west', 'forward', 'backward', 'left', 'right']) -> str:
    """指令用戶向特定方向移動"""
    return f"請實際執行向 {direction} 移動 2-3 米，完成後請輸入 'done'。"
