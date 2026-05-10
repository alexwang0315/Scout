#!/usr/bin/env python3
"""
MovementSummary – 本地特徵提取層
將高頻 IMU 數據（≥10Hz）聚合為 AI 可讀取的摘要，避免每筆資料都消耗 LLM token。
"""
import asyncio
import logging
import statistics
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 單次摘要聚合的資料筆數（10Hz × 2s = 20 筆）
SAMPLES_PER_SUMMARY = 20


def _to_float(value, default: float = 0.0) -> float:
    """Convert SensorLog string/number values into floats for statistics."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class MovementSummary:
    """經過本地清洗的移動摘要，交給 AI/LLM 使用的唯一輸入"""
    # 基本特徵
    step_count: int  # 小區段偵測到的步數
    cadence: float  # 步頻 (steps/min)
    estimated_stride: float  # 估計步長 (meters)
    motion_intensity: float  # 運動強度向量和 (G-force)
    is_stable: bool  # 感測器數據是否穩定，有無劇烈晃動

    # 其他持續保留的特徵
    avg_accZ: float          # 平均垂直加速度
    avg_accX: float          # 平均水平加速度 X
    avg_accY: float          # 平均水平加速度 Y
    std_accZ: float          # accZ 的標準差（判斷是否穩定）
    heading: float           # 估算方向角度 (0-360°)
    total_distance_m: float  # 累計移動距離（公尺）

    # 信心度
    confidence: float = 0.0  # 0-1, 高信心表示特徵明確

    # 異常標記
    anomalies: list[str] = field(default_factory=list)

    # 原始取樣數
    sample_count: int = 0

    def to_prompt(self) -> str:
        """轉換為給 LLM 的精簡提示"""
        anomalies_str = f", 異常: {', '.join(self.anomalies)}" if self.anomalies else ""
        return (
            f"MovementSummary("
            f"step_count={self.step_count}, "
            f"cadence={self.cadence:.1f} spm, "
            f"estimated_stride={self.estimated_stride:.2f}m, "
            f"motion_intensity={self.motion_intensity:.2f}G, "
            f"is_stable={self.is_stable}, "
            f"accZ={self.avg_accZ:.2f}, accX={self.avg_accX:.2f}, accY={self.avg_accY:.2f}, "
            f"accZ_std={self.std_accZ:.2f}, heading={self.heading:.0f}°, "
            f"distance={self.total_distance_m:.1f}m, confidence={self.confidence:.2f}"
            f"{anomalies_str})"
        )


@dataclass
class RawSensorSample:
    """單筆原始感測器資料"""
    accX: float
    accY: float
    accZ: float
    gravityY: float
    timestamp: float = 0.0  # 相對時間戳

    def __post_init__(self):
        self.accX = _to_float(self.accX)
        self.accY = _to_float(self.accY)
        self.accZ = _to_float(self.accZ)
        self.gravityY = _to_float(self.gravityY)
        self.timestamp = _to_float(self.timestamp)


class MovementAggregator:
    """在本地收集高頻感測資料並產生摘要"""

    def __init__(self, samples_per_summary: int = SAMPLES_PER_SUMMARY):
        self.samples_per_summary = samples_per_summary
        self.buffer: list[RawSensorSample] = []
        self.total_distance = 0.0
        self._last_heading = 0.0

    def add_sample(self, sample: RawSensorSample) -> Optional[MovementSummary]:
        """加入單筆資料，當累積足夠筆數時回傳摘要"""
        self.buffer.append(sample)

        if len(self.buffer) >= self.samples_per_summary:
            summary = self._compute_summary()
            self.buffer.clear()
            return summary
        return None

    def _compute_summary(self) -> MovementSummary:
        """本機特徵提取 – 不消耗任何 LLM 點數"""
        accZ_vals = [s.accZ for s in self.buffer]
        accX_vals = [s.accX for s in self.buffer]
        accY_vals = [s.accY for s in self.buffer]

        # 1. 計算基本統計
        avg_accZ = statistics.mean(accZ_vals)
        avg_accX = statistics.mean(accX_vals)
        avg_accY = statistics.mean(accY_vals)
        std_accZ = statistics.stdev(accZ_vals) if len(accZ_vals) > 1 else 0.0

        # 2. 方向估算（簡易磁力計融合）
        heading = self._estimate_heading(avg_accX, avg_accY)

        # 3. 步態與距離估算（Apple Watch accelerometer 單位為 G）
        step_count = self._estimate_step_count(avg_accZ, std_accZ)
        estimated_stride = self._estimate_step_distance(avg_accZ, std_accZ)
        self.total_distance += step_count * estimated_stride
        cadence = self._estimate_cadence(step_count)
        motion_intensity = max(
            (abs(s.accX) ** 2 + abs(s.accY) ** 2 + abs(s.accZ) ** 2) ** 0.5
            for s in self.buffer
        )
        is_stable = std_accZ < 0.2 and motion_intensity < 2.0

        # 4. 異常偵測
        anomalies = self._detect_anomalies(avg_accZ, std_accZ)

        # 5. 信心度
        confidence = self._compute_confidence(avg_accZ, std_accZ)

        return MovementSummary(
            step_count=step_count,
            cadence=cadence,
            estimated_stride=estimated_stride,
            motion_intensity=motion_intensity,
            is_stable=is_stable,
            avg_accZ=avg_accZ,
            avg_accX=avg_accX,
            avg_accY=avg_accY,
            std_accZ=std_accZ,
            heading=heading,
            total_distance_m=self.total_distance,
            confidence=confidence,
            anomalies=anomalies,
            sample_count=len(self.buffer),
        )

    def _estimate_heading(self, avg_accX: float, avg_accY: float) -> float:
        """簡易方向估算：atan2 轉角度"""
        import math
        angle = math.degrees(math.atan2(avg_accY, avg_accX))
        # 歸一化到 0-360
        return angle % 360

    def _estimate_step_distance(self, avg_accZ: float, std_accZ: float) -> float:
        """簡易步距估算：標準差越大代表步伐越大"""
        # 每步約 0.7m，標準差基準 0.15G
        return 0.7 * min(1.0, max(0.0, std_accZ) / 0.15)

    def _estimate_step_count(self, avg_accZ: float, std_accZ: float) -> int:
        """用垂直加速度相對平均值的擾動粗估步數。"""
        threshold = max(0.08, std_accZ)
        return sum(1 for sample in self.buffer if abs(sample.accZ - avg_accZ) > threshold)

    def _estimate_cadence(self, step_count: int) -> float:
        """估算每分鐘步頻；沒有有效 timestamp 時假設 10Hz 取樣率。"""
        if len(self.buffer) > 1:
            duration = self.buffer[-1].timestamp - self.buffer[0].timestamp
        else:
            duration = 0.0
        if duration <= 0:
            duration = len(self.buffer) / 10.0
        return (step_count / duration) * 60.0 if duration > 0 else 0.0

    def _detect_anomalies(self, avg_accZ: float, std_accZ: float) -> list[str]:
        """本地異常偵測 – 完全不消耗 API 點數"""
        anomalies = []

        # Apple Watch accelerometer 是 G，不是 m/s^2；靜止時約 +/-1G。
        if abs(avg_accZ) < 0.3 or abs(avg_accZ) > 1.5:
            anomalies.append("accZ異常")

        # 資料不穩定
        if std_accZ > 0.5:
            anomalies.append("訊號震盪")

        return anomalies

    def _compute_confidence(self, avg_accZ: float, std_accZ: float) -> float:
        """信心度：Apple Watch accelerometer 使用 G，靜止/行走時 accZ 約 +/-1G。"""
        abs_accZ = abs(avg_accZ)
        if 0.6 < abs_accZ < 1.3 and 0.01 < std_accZ < 0.5:
            return 0.9
        if 0.3 < abs_accZ < 1.5:
            return 0.5
        return 0.2


# ============ 使用範例 ============
if __name__ == "__main__":
    import random, math

    agg = MovementAggregator()

    # 模擬 10Hz 高頻資料（2 秒 = 20 筆）
    for i in range(20):
        sample = RawSensorSample(
            accX=0.15 + random.gauss(0, 0.05),
            accY=-0.05 + random.gauss(0, 0.03),
            accZ=9.81 + random.gauss(0, 0.05),
            gravityY=-9.8,  # 手機倒置
        )
        result = agg.add_sample(sample)
        if result:
            print(f"摘要: {result.to_prompt()}")
            print(f"  → confidence={result.confidence:.2f}, anomalies={result.anomalies}")
            print(f"  → 已消耗 LLM token? ❌ 否（100% 本機計算）")
            break
