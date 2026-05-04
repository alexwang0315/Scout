import asyncio
import logging
import os
from typing import List
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from pdr_record import PDRRecord  # ← 必須放在這裡（在使用前）
from pdr_engine import pdr

def is_debug_mode() -> bool:
    return os.getenv('SCOUT_DEBUG', 'false').lower() == 'true'

router = APIRouter(prefix="/imu", tags=["imu"])

imu_buffer: List[PDRRecord] = []
buffer_lock = asyncio.Lock()

@router.post("/upload", response_model=List[PDRRecord])
async def upload_imu(request: Request):
    if is_debug_mode():
        client = request.client.host if request.client else "unknown"
        logging.getLogger("S.C.OUT.").info(f"📥 [IMU] 收到來自 {client} 的請求")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    # 這裡使用 PDRRecord（import 已在檔案開頭）
    if isinstance(payload, dict):
        records = [PDRRecord(**payload)]
    elif isinstance(payload, list):
        records = [PDRRecord(**item) for item in payload]
    else:
        raise HTTPException(status_code=422, detail="Payload must be dict or list of dicts")

    for record in records:
        imu_dict = record.dict()
        
        # 處理 GPS 數據
        if record.locationLatitude is not None and record.locationLongitude is not None:
            pdr.add_gps_point(
                lat=record.locationLatitude,
                lon=record.locationLongitude,
                time_val=datetime.now().timestamp()
            )
            if is_debug_mode():
                logging.getLogger("S.C.OUT.").debug(
                    f"📍 [GPS] 添加點 lat={record.locationLatitude}, lon={record.locationLongitude}"
                )
        
        # 使用 IMU 更新 PDR
        x, y = pdr.update_from_imu(imu_dict)
        
        if is_debug_mode():
            logging.getLogger("S.C.OUT.").debug(
                f"🔹 [IMU] PDR 更新至 ({x:.2f}, {y:.2f})，heading={pdr.heading:.2f} rad"
            )

    async with buffer_lock:
        imu_buffer.extend(records)

    logging.info(f"📥 收到 {len(records)} 筆 IMU/PDR 訊息")
    return records
