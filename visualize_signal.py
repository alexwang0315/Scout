import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import griddata
import os
import logging

logger = logging.getLogger("S.C.O.U.T.")

def generate_heatmap(world):
    """
    生成熱力圖（GPS/PDR融合）：
    - 從 world.trajectory 提取 x, y 與信號強度（rssi）
    - 使用 SciPy 的 griddata 插值生成平滑熱力圖
    - 儲存為 heatmap.png
    """
    # 1. 取得軌跡數據
    traj = getattr(world, 'trajectory', [])
    
    # 2. 數據完整性檢查
    if len(traj) < 3:
        logger.warning("⚠️ 熱力圖點數不足（需至少3點）、無法生成圖表")
        return False
        
    try:
        # 提取 x, y, rssi（使用最大信號強度）
        x_values = np.array([p['x'] for p in traj])
        y_values = np.array([p['y'] for p in traj])
        # 從 signals 中取最大 rssi，若無則使用預設值
        z_values = np.array([
            max(p.get('signals', {}).values()) if p.get('signals') else -100
            for p in traj
        ])
        
        # 3. 數據範圍擴張（避免邊界急激變化）
        x_min, x_max = x_values.min() - 2, x_values.max() + 2
        y_min, y_max = y_values.min() - 2, y_values.max() + 2
        
        # 建立插值網格
        xi = np.linspace(x_min, x_max, 100)
        yi = np.linspace(y_min, y_max, 100)
        xi, yi = np.meshgrid(xi, yi)
        
        # 使用線性插值生成熱力圖
        zi = griddata(
            (x_values, y_values), 
            z_values, 
            (xi, yi), 
            method='linear'
        )
        
        # 4. 繪製熱力圖
        plt.figure(figsize=(12, 10))
        plt.contourf(xi, yi, zi, 30, cmap='viridis')  # 使用更新的色散映射
        plt.colorbar(label='最大信號強度 (dBm)')
        
        # 標示軌跡點
        plt.scatter(x_values, y_values, c='black', edgecolors='white', s=30, alpha=0.7)
        plt.plot(x_values, y_values, 'white--', alpha=0.5)
        
        # 5. 儲存並清理
        output_path = os.path.join(os.path.dirname(__file__), 'heatmap.png')
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"✅ 熱力圖已生成至 {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"🔥 熱力圖生成錯誤：{str(e)}")
        return False
