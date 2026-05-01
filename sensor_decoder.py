from typing import Dict, Any, Optional
from pydantic import BaseModel

class DecodedPDR(BaseModel):
    """標準化後的 PDR 數據格式"""
    distance: float  # 移動距離 (米)
    heading: float   # 絕對航向 (度)
    raw_source: str  # 數據來源 (Distance 或 Steps)

class SensorLogDecoder:
    """
    專為 SensorLog 數據流設計的解碼器。
    將 SensorLog 的 Form-encoded 或 JSON 數據轉化為標準 PDR 參數。
    """
    def __init__(self, default_step_length=0.75):
        self.default_step_length = default_step_length

    def decode(self, raw_data: Dict[str, Any]) -> Optional[DecodedPDR]:
        """
        解析原始數據並返回 DecodedPDR 對象。
        """
        try:
            # 1. 提取距離/步數 (優先使用 pedometerDistance)
            dist_val = raw_data.get("pedometerDistance")
            step_val = raw_data.get("pedometerNumberofSteps")
            
            distance = 0.0
            source = ""
            
            if dist_val is not None:
                distance = float(dist_val)
                source = "pedometerDistance"
            elif step_val is not None:
                distance = float(step_val) * self.default_step_length
                source = "pedometerNumberofSteps"
            else:
                return None # 缺失距離-相關數據

            # 2. 提取航向 (優先使用 motionHeading)
            heading_val = raw_data.get("motionHeading") or raw_data.get("locationCourse")
            if heading_val is None:
                return None # 缺失方向數據
            
            heading = float(heading_val)

            return DecodedPDR(
                distance=distance,
                heading=heading,
                raw_source=source
            )
        except (ValueError, TypeError) as e:
            print(f"Decoder Error: {e}")
            return None
