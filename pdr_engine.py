import math
from typing import Dict, Tuple, List

class PDREngine:
    def __init__(self, step_length: float = 0.75):
        self.step_length = step_length
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0          # radians
        self.last_time = None
        self.pdr_trajectory = []   # list of dicts: {"x":..., "y":..., "time":..., "source": "pdr"}
        self.gps_trajectory = []   # list of dicts: {"x":..., "y":..., "lat":..., "lon":..., "time":..., "source": "gps"}

    def update_from_imu(self, imu_data: Dict) -> Tuple[float, float]:
        """根據 IMU 資料更新位置，回傳 (x, y)。"""
        # 1. 時間戳 (秒)
        ts_raw = imu_data.get("motionTimestamp_sinceReboot")
        current_time = (ts_raw / 1e9) if ts_raw is not None else 0.0
        if self.last_time is None:
            self.last_time = current_time
        dt = max(current_time - self.last_time, 0.0)
        self.last_time = current_time

        # 2. 角速度 → 角度變化
        gyro_z = float(imu_data.get("gyroRotationZ", 0.0))
        self.heading = (self.heading + gyro_z * dt) % (2 * math.pi)

        # 3. 加速度 → 步態檢測與位移
        ax = float(imu_data.get("accelerometerAccelerationX", 0.0))
        ay = float(imu_data.get("accelerometerAccelerationY", 0.0))
        az = float(imu_data.get("accelerometerAccelerationZ", 0.0))
        acc_mag = math.sqrt(ax**2 + ay**2 + az**2)
        if acc_mag > 1.5:                     # 簡易閾值判斷步態
            step_len = self.step_length
            dx = step_len * math.cos(self.heading)
            dy = step_len * math.sin(self.heading)
            self.x += dx
            self.y += dy

        # 4. 記錄 PDR 點
        self.pdr_trajectory.append({
            "x": self.x,
            "y": self.y,
            "time": current_time,
            "source": "pdr"
        })
        return self.x, self.y

    def add_gps_point(self, lat: float, lon: float, time_val: float = None):
        """將 GPS 座標加入軌跡。若未提供 time，使用當前時間。"""
        ts = time_val if time_val is not None else time.time()
        # 第一次呼叫時設定起點
        if not self.gps_trajectory:
            self._origin_lat = lat
            self._origin_lon = lon
        # 將經緯度轉為相對平面坐標（米）
        dy = (lat - self._origin_lat) * 111000
        dx = (lon - self._origin_lon) * 111000 * math.cos(math.radians(self._origin_lat))
        self.gps_trajectory.append({
            "x": dx,
            "y": dy,
            "lat": lat,
            "lon": lon,
            "time": ts,
            "source": "gps"
        })

    def get_combined_trajectory(self) -> List[Dict]:
        """回傳合併後的 GPS + PDR 軌跡（依時間排序）。"""
        combined = []
        combined.extend(self.gps_trajectory)
        combined.extend(self.pdr_trajectory)
        combined.sort(key=lambda p: p.get("time", 0))
        return combined

    def reset(self):
        """重置所有狀態，用於重新開始計算。"""
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0
        self.last_time = None
        self.trajectory = []
        self.gps_trajectory = []
        self.pdr_trajectory = []

# 為了讓 server.py 能直接使用 pdr 物件
pdr = PDREngine()
