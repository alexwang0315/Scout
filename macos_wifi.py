import subprocess
import re
from typing import List, Dict, Optional
from pydantic import BaseModel

class MacOSWifiWorld:
    def __init__(self):
        self.last_best_strength = -100.0
        self.airport_path = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/resources/airport"

    def scan_all(self) -> List[Dict]:
        """掃描所有周邊 Wi-Fi"""
        try:
            result = subprocess.check_output([self.airport_path, "-s"], stderr=subprocess.STDOUT).decode('utf-8')
            lines = result.split('\n')
            wifi_list = []
            rssi_pattern = re.compile(r'\s(-?\d{2,3})\s+')
            for line in lines:
                line = line.strip()
                if not line or "SSID" in line: continue
                match = rssi_pattern.search(line)
                if match:
                    rssi_val = float(match.group(1))
                    ssid = line[:match.start()].strip()
                    wifi_list.append({"ssid": ssid, "rssi": rssi_val})
            return wifi_list
        except Exception as e:
            print(f"掃描出錯: {e}")
            return []

    def get_best_signal(self) -> Dict:
        """獲取當前最強訊號"""
        all_wifi = self.scan_all()
        if not all_wifi: return {"ssid": "None", "rssi": -100.0}
        return max(all_wifi, key=lambda x: x['rssi'])

    def get_full_snapshot(self) -> Dict[str, float]:
        """獲取所有 SSID 及其強度的映射表"""
        all_wifi = self.scan_all()
        return {wifi['ssid']: wifi['rssi'] for wifi in all_wifi}

    def move(self, direction: str):
        return f"用戶已向 {direction} 移動"
