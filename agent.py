import os
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic import BaseModel
from typing import Literal
from macos_wifi import MacOSWifiWorld
from dotenv import load_dotenv

# 1. 加載環境變量
load_dotenv(os.path.expanduser('~/scout-fusion/.env'))
api_key = os.getenv('OPENROUTER_API_KEY')

# 2. 極限注入：直接修改操作系統環境變數
# 這會強制所有 OpenAI-compatible 模型自動使用 OpenRouter 端點，無需在代碼中指定 base_url
os.environ['OPENAI_API_KEY'] = api_key
os.environ['OPENAI_BASE_URL'] = 'https://openrouter.ai/api/v1'

# 3. 簡潔實例化
# 此時 pydantic-ai 會自動從 os.environ 讀取 API Key 和 Base URL
model = OpenAIModel('google/gemma-4-31b-it')

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
    )
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
