import asyncio
import logging
import os
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from agent import sos_agent
from admin_api import create_admin_router
from imu_api import router as imu_router
from macos_wifi import MacOSWifiWorld
from pdr_engine import pdr
from phase2_admin_api import create_phase2_admin_router
from sensor_decoder import SensorLogDecoder
from movement_summary import MovementAggregator, RawSensorSample
from safety_api import SafetyApiSnapshot, create_safety_router
from safety_models import SafetyState
from safety_runtime_session import SafetyRuntimeSession
from shared_queue import pdr_event_queue
from visualize_signal import generate_heatmap

load_dotenv(os.path.expanduser("~/scout-fusion/.env"))

DEBUG = os.getenv("SCOUT_DEBUG", "false").lower() == "true"
PORT = int(os.getenv("SCOUT_PORT", "9099"))
SCOUT_SAFETY_ENABLED = os.getenv("SCOUT_SAFETY_ENABLED", "true").lower() == "true"
SCOUT_ROOT = Path(__file__).resolve().parent
SCOUT_SAFETY_MISSION_GRAPH = Path(
    os.getenv(
        "SCOUT_SAFETY_MISSION_GRAPH",
        str(SCOUT_ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"),
    )
)
SCOUT_SAFETY_ROUTE_PROGRESS_CONFIG = os.getenv("SCOUT_SAFETY_ROUTE_PROGRESS_CONFIG")
SCOUT_SAFETY_INCIDENT_STORE = Path(
    os.getenv("SCOUT_SAFETY_INCIDENT_STORE", os.path.expanduser("~/.scout-fusion/incidents"))
)
SCOUT_PHASE2_ADMIN_API_ENABLED = os.getenv("SCOUT_PHASE2_ADMIN_API_ENABLED", "false")
SCOUT_PHASE2_BRAIN_STORE_ROOT = os.getenv("SCOUT_PHASE2_BRAIN_STORE_ROOT")

log_level = logging.DEBUG if DEBUG else logging.INFO
logging.basicConfig(level=log_level, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("S.C.O.U.T.")

# Global movement aggregator (10Hz → summary every 2s)
# Ship the summary to agent logic when ready.
movement_agg = MovementAggregator(samples_per_summary=20)



@asynccontextmanager
async def lifespan(_: FastAPI):
    global _worker_task
    if _worker_task is None or _worker_task.done():
        logger.info("Starting AI decision worker")
        _worker_task = asyncio.create_task(ai_decision_worker())
    try:
        yield
    finally:
        if _worker_task and not _worker_task.done():
            _worker_task.cancel()
        executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="S.C.O.U.T. Fusion Server",
    description="Wi-Fi signal fusion + IMU/PDR pedestrian dead reckoning server",
    version="0.2.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

world = MacOSWifiWorld()
world.trajectory = []
trajectory_lock = asyncio.Lock()
executor = ThreadPoolExecutor(max_workers=4)
last_instruction = "等待初始化..."
latest_summary_result: Optional[Dict[str, Any]] = None
_worker_task: Optional[asyncio.Task] = None
safety_runtime_session: Optional[SafetyRuntimeSession] = None

if SCOUT_SAFETY_ENABLED:
    try:
        safety_runtime_session = SafetyRuntimeSession(
            SCOUT_SAFETY_MISSION_GRAPH,
            route_progress_config_path=SCOUT_SAFETY_ROUTE_PROGRESS_CONFIG,
            incident_store_path=SCOUT_SAFETY_INCIDENT_STORE,
        )
        logger.info("Phase 1 safety runtime enabled: %s", SCOUT_SAFETY_MISSION_GRAPH)
    except Exception as exc:
        logger.exception("Phase 1 safety runtime disabled after initialization failure: %s", exc)


def _result_text(result: Any) -> str:
    return str(getattr(result, "output", getattr(result, "data", result)))


def _latest_pose() -> Dict[str, float]:
    if pdr.pdr_trajectory:
        last = pdr.pdr_trajectory[-1]
        return {"x": float(last["x"]), "y": float(last["y"])}
    return {"x": float(pdr.x), "y": float(pdr.y)}


def _optional_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _include_phase2_admin_router(app: FastAPI) -> None:
    if not _is_true_like(SCOUT_PHASE2_ADMIN_API_ENABLED):
        logger.info("Phase 2 admin API disabled")
        return

    if not SCOUT_PHASE2_BRAIN_STORE_ROOT or not SCOUT_PHASE2_BRAIN_STORE_ROOT.strip():
        logger.warning(
            "Phase 2 admin API enabled but SCOUT_PHASE2_BRAIN_STORE_ROOT is missing; skipping router mount"
        )
        return

    brain_store_root = Path(SCOUT_PHASE2_BRAIN_STORE_ROOT)
    app.include_router(create_phase2_admin_router(brain_store_root=brain_store_root))
    logger.info("Phase 2 admin API enabled: %s", brain_store_root)


async def process_movement_summary(summary: Any) -> Dict[str, Any]:
    """Create immediate local feedback from a MovementSummary without LLM calls."""
    if summary.confidence < 0.5:
        return {
            "status": "low_confidence",
            "message": "感測數據信心度不足，等待更多樣本",
            "confidence": summary.confidence,
        }

    feedback = "姿態穩定，繼續前進" if summary.is_stable else "檢測到不穩定動作，請放慢腳步"
    return {
        "status": "success",
        "feedback": feedback,
        "heading": summary.heading,
        "confidence": summary.confidence,
        "anomalies": summary.anomalies,
        "summary_text": summary.to_prompt(),
    }


def generate_trajectory_plot() -> bool:
    """Generate trajectory_map.png from combined GPS and PDR trajectories."""
    try:
        trajectory = pdr.get_combined_trajectory()
        if len(trajectory) < 2:
            logger.warning("Not enough trajectory points to generate map")
            return False

        gps_points = [point for point in trajectory if point.get("source") == "gps"]
        pdr_points = [point for point in trajectory if point.get("source") == "pdr"]

        plt.figure(figsize=(12, 8))

        if gps_points:
            gps_x = [point["x"] for point in gps_points]
            gps_y = [point["y"] for point in gps_points]
            plt.plot(gps_x, gps_y, "b-", linewidth=2, label="GPS trajectory")
            plt.scatter(gps_x, gps_y, c="blue", s=30, marker="o")
            plt.scatter(gps_x[0], gps_y[0], c="green", s=100, marker="^", label="GPS start")
            plt.scatter(gps_x[-1], gps_y[-1], c="blue", s=100, marker="s", label="GPS end")

        if pdr_points:
            pdr_x = [point["x"] for point in pdr_points]
            pdr_y = [point["y"] for point in pdr_points]
            plt.plot(pdr_x, pdr_y, "r-", linewidth=2, label="PDR trajectory")
            plt.scatter(pdr_x, pdr_y, c="red", s=20, marker="x")
            plt.scatter(pdr_x[0], pdr_y[0], c="orange", s=100, marker="^", label="PDR start")
            plt.scatter(pdr_x[-1], pdr_y[-1], c="red", s=100, marker="s", label="PDR end")

        plt.xlabel("X (meters)")
        plt.ylabel("Y (meters)")
        plt.title("Pedestrian Trajectory (GPS + PDR)")
        plt.grid(True)
        plt.legend(loc="best")
        plt.axis("equal")
        plt.savefig("trajectory_map.png", dpi=300, bbox_inches="tight")
        plt.close()
        logger.info("trajectory_map.png generated")
        return True
    except Exception as exc:
        logger.exception("Failed to generate trajectory map: %s", exc)
        return False


async def ai_decision_worker() -> None:
    """Process queued PDR events without blocking ingestion endpoints."""
    global last_instruction
    while True:
        event = await pdr_event_queue.get()
        try:
            pose = event.get("pose", _latest_pose())
            signals = event.get("signals", {})
            async with trajectory_lock:
                target_point = None
                for point in reversed(world.trajectory):
                    if point.get("x") == pose["x"] and point.get("y") == pose["y"]:
                        target_point = point
                        break
                if target_point is None:
                    target_point = {"x": pose["x"], "y": pose["y"], "signals": signals, "decision": None}
                    world.trajectory.append(target_point)
                else:
                    target_point.setdefault("signals", signals)
                    target_point.setdefault("decision", None)

            result = await sos_agent.run(
                "請根據最新的 PDR 座標和 Wi-Fi 訊號快照，給出明確且簡短的下一步移動指令。",
                deps=world,
                model_settings={"max_tokens": 256},
            )
            decision = _result_text(result)
            last_instruction = decision

            async with trajectory_lock:
                target_point["decision"] = decision
        except Exception as exc:
            logger.exception("AI worker error: %s", exc)
        finally:
            pdr_event_queue.task_done()


app.include_router(imu_router)
app.include_router(create_admin_router(incident_store_path=SCOUT_SAFETY_INCIDENT_STORE))
app.include_router(
    create_safety_router(
        SafetyApiSnapshot(safety_state=SafetyState()),
        incident_store=safety_runtime_session.incident_store if safety_runtime_session else None,
        runtime_session=safety_runtime_session,
    )
)
_include_phase2_admin_router(app)


@app.get("/")
async def root() -> Dict[str, Any]:
    return {"status": "S.C.O.U.T. Fusion Online", "debug": DEBUG, "port": PORT}


@app.get("/status")
async def get_status() -> Dict[str, Any]:
    async with trajectory_lock:
        pose = _latest_pose() if pdr.pdr_trajectory else (world.trajectory[-1] if world.trajectory else _latest_pose())
        points = len(world.trajectory)

    loop = asyncio.get_event_loop()
    best_sig = await loop.run_in_executor(executor, world.get_best_signal)
    return {
        "x": pose["x"],
        "y": pose["y"],
        "best_ssid": best_sig["ssid"],
        "best_rssi": best_sig["rssi"],
        "points": points,
        "instruction": last_instruction,
        "gps_points": len(pdr.gps_trajectory),
        "pdr_points": len(pdr.pdr_trajectory),
        "queued_events": pdr_event_queue.qsize(),
    }


@app.get("/movement-summary")
async def get_latest_summary() -> Dict[str, Any]:
    if latest_summary_result is not None:
        return latest_summary_result
    return {"status": "no_summary", "message": "No movement summary data available"}


@app.post("/pdr/update")
async def update_pdr(request: Request) -> Dict[str, Any]:
    global latest_summary_result
    try:
        content_type = request.headers.get("content-type", "")
        raw_data = await request.json() if "application/json" in content_type else dict(await request.form())
        if DEBUG:
            logger.debug("Incoming PDR data: %s", raw_data)

        decoded = SensorLogDecoder().decode(raw_data)
        imu_points = 0
        if "imu_data" in raw_data:
            imu_list = raw_data["imu_data"]
            for imu in imu_list:
                if not isinstance(imu, dict):
                    continue

                sample = RawSensorSample(
                    accX=imu.get("accX") or imu.get("accelerometerAccelerationX", 0.0),
                    accY=imu.get("accY") or imu.get("accelerometerAccelerationY", 0.0),
                    accZ=imu.get("accZ") or imu.get("accelerometerAccelerationZ", 0.0),
                    gravityY=imu.get("gravityY") or imu.get("motionGravityY", 0.0),
                    timestamp=imu.get("timestamp") or imu.get("motionTimestamp_sinceReboot", 0.0),
                )
                summary = movement_agg.add_sample(sample)
                if summary:
                    latest_summary_result = await process_movement_summary(summary)
                    logger.info("Movement summary processed: %s", latest_summary_result)

                lat = _optional_float(imu.get("locationLatitude"))
                lon = _optional_float(imu.get("locationLongitude"))
                if lat is not None and lon is not None:
                    pdr.add_gps_point(lat=lat, lon=lon)

                pdr.update_from_imu(imu)
                imu_points += 1

        if decoded is None and imu_points == 0:
            return {"status": "skipped", "reason": "Malformed PDR data"}

        if decoded is not None and (decoded.distance != 0 or imu_points == 0):
            curr_x, curr_y = pdr.update_position(decoded.distance, decoded.heading)
        else:
            pose = _latest_pose()
            curr_x, curr_y = pose["x"], pose["y"]

        loop = asyncio.get_event_loop()
        snapshot = await loop.run_in_executor(executor, world.get_full_snapshot)

        event = {"pose": {"x": curr_x, "y": curr_y}, "signals": snapshot}
        async with trajectory_lock:
            world.trajectory.append({
                "x": curr_x,
                "y": curr_y,
                "signals": snapshot
            })
        
        # 加強佇列監控
        if pdr_event_queue.qsize() > 50:
            logger.warning(f"PDR event queue size is {pdr_event_queue.qsize()}, approaching capacity")
        
        try:
            pdr_event_queue.put_nowait(event)
            queued = True
        except asyncio.QueueFull:
            logger.warning("PDR event queue is full; dropping AI decision event")
            queued = False

        return {"status": "success", "pose": event["pose"], "queued_for_ai": queued, "imu_points": imu_points}
    except Exception as exc:
        logger.exception("PDR update failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


@app.get("/navigate")
async def get_navigation() -> Dict[str, Any]:
    global last_instruction
    try:
        async with trajectory_lock:
            if not world.trajectory:
                loop = asyncio.get_event_loop()
                snapshot = await loop.run_in_executor(executor, world.get_full_snapshot)
                pose = _latest_pose()
                world.trajectory.append({"x": pose["x"], "y": pose["y"], "signals": snapshot})

        result = await sos_agent.run(
            "請根據最新的 PDR 座標和訊號快照，分析目前最強信號位置，並給出明確的移動指令。",
            deps=world,
            model_settings={"max_tokens": 256},
        )
        response_text = _result_text(result)
        last_instruction = response_text

        loop = asyncio.get_event_loop()
        best_signal = await loop.run_in_executor(executor, world.get_best_signal)
        return {"instruction": response_text, "best_signal": best_signal}
    except Exception as exc:
        logger.exception("Navigation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/generate_map")
async def trigger_map() -> Dict[str, str]:
    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(executor, generate_heatmap, world)
        if not success:
            return {"status": "error", "path": "heatmap.png"}
        return {"status": "success", "path": "heatmap.png"}
    except Exception as exc:
        logger.exception("Heatmap generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/trajectory/map")
async def generate_trajectory_endpoint() -> Dict[str, str]:
    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(executor, generate_trajectory_plot)
        if success:
            return {"status": "success", "path": "trajectory_map.png"}
        return {"status": "error", "detail": "Failed to generate trajectory plot"}
    except Exception as exc:
        logger.exception("Trajectory map endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/trajectory/status")
async def trajectory_status() -> Dict[str, Any]:
    return {
        "gps_points": len(pdr.gps_trajectory),
        "pdr_points": len(pdr.pdr_trajectory),
        "total_points": len(pdr.get_combined_trajectory()),
        "gps_available": len(pdr.gps_trajectory) > 0,
        "pdr_available": len(pdr.pdr_trajectory) > 0,
    }


if __name__ == "__main__":
    logger.info("Starting S.C.O.U.T. Fusion on port %s, DEBUG=%s", PORT, DEBUG)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
