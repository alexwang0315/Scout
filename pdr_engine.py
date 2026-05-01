import math
import time
from typing import Dict, Tuple

class PDREngine:
    def __init__(self, step_length=0.75): 
        """
        S.C.O.U.T. 行人航位推算引擎 (PDR)
        :param step_length: 平均每步長度 (米), 默認 0.75m
        """
        self.step_length = step_length
        self.current_x = 0.0
        self.current_y = 0.0
        self.current_heading = 0.0
        self.total_steps = 0
        self.last_update = time.time()
        self.history = []

    def update_position(self, steps: int, heading: float):
        """
        根據步數和航向更新相對座標
        :param steps: 自上次更新後走過的步數
        :param heading: 絕對航向 (0-360度, 0為正北)
        """
        self.current_heading = heading
        self.total_steps += steps
        
        # 將角度轉化為弧度 (S.C.O.U.T. 定義: 0度=正北, 90度=正東)
        rad = math.radians(heading)
        
        # 計算位移 (X=東, Y=北)
        dx = steps * self.step_length * math.sin(rad)
        dy = steps * self.step_length * math.cos(rad)
        
        self.current_x += dx
        self.current_y += dy
        
        # 記錄軌跡點
        timestamp = time.time()
        self.history.append({
            "timestamp": timestamp,
            "x": round(self.current_x, 2),
            "y": round(self.current_y, 2),
            "heading": heading,
            "steps": steps
        })
        
        return self.current_x, self.current_y

    def get_current_pose(self) -> Tuple[float, float, float]:
        """獲取當前狀態 (X, Y, Heading)"""
        return self.current_x, self.current_y, self.current_heading

    def reset(self):
        """重置座標系"""
        self.current_x = 0.0
        self.current_y = 0.0
        self.total_steps = 0
        self.history = []
