import asyncio
import os
import logging
import matplotlib
matplotlib.use('Agg')

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

from agent import sos_agent
from macos_wifi import MacOSWifiWorld
from visualize_signal import generate_heatmap
from pdr_engine import PDREngine

load_dotenv(os.path.expanduser('~/scout-fusion/.env'))

DEBUG = os.getenv('SCOUNT_DEBUG', 'False').lower() == 'true'
PORT = 9099

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("S.C.O.U.T.")

app = FastAPI(title="S.C.O.U.T. Fusion Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

world = MacOSWifiWorld()
pdr = PDREngine()
world.trajectory = []
trajectory_lock = asyncio.Lock()
executor = ThreadPoolExecutor(max_workers=3)

last_instruction = "等待初始化..."

@app.get("/")
async def root():
    return {"status": "S.C.O.U.T. Fusion Online", "secure": False, "port": PORT}

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
        "instruction": last_instruction
    }

@app.post("/pdr/update")
async def update_pdr(request: Request):
    try:
        content_type = request.headers.get("content-type", "")
        data = await request.json() if "application/json" in content_type else await request.form()
        if DEBUG: logger.info(f"Incoming PDR Data: {data}")
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
            "請根據最新的 PDR 座標和訊號快照，分析目前最強信號位置，並給出明確的移動指令。",
            deps=world,
            model_settings={"max_tokens": 256}
        )
        response_text = getattr(result, 'output', getattr(result, 'data', str(result)))
        last_instruction = response_text
        return { "instruction": response_text, "best_signal": world.get_best_signal() }
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
