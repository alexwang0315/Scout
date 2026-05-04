import asyncio
import os
import logging
import matplotlib
matplotlib.use('Agg')  # 非互動式後端，用於生成圖表
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import matplotlib.pyplot as plt
import numpy as np

from agent import sos_agent
from macos_wifi import MacOSWifiWorld
from visualize_signal import generate_heatmap
from pdr_engine import pdr
from imu_api import router as imu_router

# 載入環境變數
load_dotenv(os.path.expanduser('~/scout-fusion/.env'))

# 配置參數
DEBUG = os.getenv('SCOUT_DEBUG', 'false').lower() == 'true'
PORT = 9099

# 日誌配置
log_level = logging.DEBUG if DEBUG else logging.INFO
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("S.C.O.U.T.")

# 初始化 FastAPI
app = FastAPI(
    title="S.C.O.U.T. Fusion Server",
    description="Wi-Fi 訊號融合 + IMU/PDR 行人航位推算伺服器",
    version="0.2.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局狀態初始化
world = MacOSWifiWorld()
world.trajectory = []
trajectory_lock = asyncio.Lock()
executor = ThreadPoolExecutor(max_workers=3)
last_instruction = "等待初始化..."

# ─── 軌跡圖生成函數 ───────────────────────────────────────────────
def generate_trajectory_plot():
    """生成軌跡圖（GPS + PDR）"""
    try:
        # 獲取合併軌跡
        trajectory = pdr.get_combined_trajectory()
        
        if len(trajectory) < 2:
            logger.warning("軌跡點不足，無法生成圖表")
            return False
            
        # 分離GPS和PDR點
        gps_points = [p for p in trajectory if p['source'] == 'gps']
        pdr_points = [p for p in trajectory if p['source'] == 'pdr']
        
        plt.figure(figsize=(12, 8))
        
        # 繪製GPS軌跡（藍色）
        if gps_points:
            gps_x = [p['x'] for p in gps_points]
            gps_y = [p['y'] for p in gps_points]
            plt.plot(gps_x, gps_y, 'b-', linewidth=2, label='GPS軌跡')
            plt.scatter(gps_x, gps_y, c='blue', s=30, marker='o')
            
        # 繪製PDR軌跡（紅色）
        if pdr_points:
            pdr_x = [p['x'] for p in pdr_points]
            pdr_y = [p['y'] for p in pdr_points]
            plt.plot(pdr_x, pdr_y, 'r-', linewidth=2, label='PDR軌跡')
            plt.scatter(pdr_x, pdr_y, c='red', s=20, marker='x')
            
        # 標記起點和終點
        if gps_points:
            plt.scatter(gps_points[0]['x'], gps_points[0]['y'], 
                       c='green', s=100, marker='^', label='GPS起點')
            plt.scatter(gps_points[-1]['x'], gps_points[-1]['y'], 
                       c='blue', s=100, marker='s', label='GPS終點')
                       
        if pdr_points:
            plt.scatter(pdr_points[0]['x'], pdr_points[0]['y'], 
                       c='orange', s=100, marker='^', label='PDR起點')
            plt.scatter(pdr_points[-1]['x'], pdr_points[-1]['y'], 
                       c='red', s=100, marker='s', label='PDR終點')
        
        # 圖表裝飾
        plt.xlabel('X 坐標 (米)')
        plt.ylabel('Y 坐標 (米)')
        plt.title('行人軌跡圖 (GPS + PDR)')
        plt.grid(True)
        plt.legend(loc='best')
        plt.axis('equal')  # 保持坐標比例一致
        
        # 保存圖表
        plt.savefig('trajectory_map.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info("✅ 軌跡圖已生成: trajectory_map.png")
        return True
        
    except Exception as e:
        logger.error(f"生成軌跡圖失敗: {str(e)}")
        return False

# ─── 註冊路由 ───────────────────────────────────────────────────
app.include_router(imu_router)

# 原有路由（保留）
@app.get("/")
async def root():
    return {"status": "S.C.O.U.T. Fusion Online", "debug": DEBUG, "port": PORT}

@app.get("/status")
async def get_status():
    async with trajectory_lock:
        if not world.trajectory:
            return {"error": "No trajectory data yet"}
        last_pose = world.trajectory[-1]
        best_sig = world.get_best_signal()
        return {
            "x": last_pose['x'],
            "y": last_pose['y'],
            "best_ssid": best_sig['ssid'],
            "best_rssi": best_sig['rssi'],
            "points": len(world.trajectory),
            "instruction": last_instruction,
            "gps_points": len(pdr.gps_trajectory),
            "pdr_points": len(pdr.pdr_trajectory)
        }

@app.post("/pdr/update")
async def update_pdr(request: Request):
    try:
        content_type = request.headers.get("content-type", "")
        data = await request.json() if "application/json" in content_type else await request.form()
        if DEBUG:
            logger.info(f"Incoming PDR Data: {data}")
        
        from sensor_decoder import SensorLogDecoder
        decoder = SensorLogDecoder()
        decoded = decoder.decode(data)
        
        if not decoded:
            return {"status": "skipped", "reason": "Malformed PDR data"}
        
        async with trajectory_lock:
            equiv_steps = int(decoded.distance / 0.75)
            curr_x, curr_y = pdr.update_position(equiv_steps, decoded.heading)
            loop = asyncio.get_event_loop()
            snapshot = await loop.run_in_executor(executor, world.get_full_snapshot)
            world.trajectory.append({"x": curr_x, "y": curr_y, "signals": snapshot})
            return {"status": "success", "pose": {"x": curr_x, "y": curr_y}}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/navigate")
async def get_navigation():
    global last_instruction
    try:
        async with trajectory_lock:
            if not world.trajectory:
                loop = asyncio.get_event_loop()
                snapshot = await loop.run_in_executor(executor, world.get_full_snapshot)
                world.trajectory.append({"x": 0, "y": 0, "signals": snapshot})
            result = await sos_agent.run(
                "請根據最新的 PDR 座標和訊號快照,分析目前最強信號位置,並給出明確的移動指令。",
                deps=world,
                model_settings={"max_tokens": 256}
            )
            response_text = getattr(result, 'output', getattr(result, 'data', str(result)))
            last_instruction = response_text
            return {"instruction": response_text, "best_signal": world.get_best_signal()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/generate_map")
async def trigger_map():
    try:
        async with trajectory_lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, generate_heatmap, world)
            return {"status": "success", "path": "heatmap.png"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── 新增軌跡圖端點 ──────────────────────────────────────────────
@app.get("/trajectory/map")
async def generate_trajectory_endpoint():
    """生成軌跡圖（GPS + PDR融合）"""
    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(executor, generate_trajectory_plot)
        if success:
            return {"status": "success", "path": "trajectory_map.png"}
        else:
            return {"status": "error", "detail": "Failed to generate trajectory plot"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/trajectory/status")
async def trajectory_status():
    """獲取軌跡狀態"""
    return {
        "gps_points": len(pdr.gps_trajectory),
        "pdr_points": len(pdr.pdr_trajectory),
        "total_points": len(pdr.get_combined_trajectory()),
        "gps_available": len(pdr.gps_trajectory) > 0,
        "pdr_available": len(pdr.pdr_trajectory) > 0
    }

# ─── 主入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info(f"🚀 S.C.O.U.T. Fusion 啟動於端口 {PORT}, DEBUG={DEBUG}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
