import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import griddata
import os
import random

def generate_heatmap(world):
    traj = getattr(world, 'trajectory', [])
    if len(traj) < 3:
        print("⚠️ Data points insufficient (need at least 3 points for mapping).")
        return

    # 提取 X, Y, RSSI
    x = np.array([p['x'] for p in traj])
    y = np.array([p['y'] for p in traj])
    z = np.array([max(p.get('signals', {}).values()) if p.get('signals') else -100 for p in traj])

    # --- 關鍵修正：引入微小擾動 (Jitter) 解決共線/共面崩潰問題 ---
    # 給每個點增加 +/- 0.01m 的隨機偏移
    x = x + np.random.uniform(-0.01, 0.01, size=x.shape)
    y = y + np.random.uniform(-0.01, 0.01, size=y.shape)

    # 建立網格
    xi = np.linspace(x.min() - 2, x.max() + 2, 100)
    yi = np.linspace(y.min() - 2, y.max() + 2, 100)
    xi, yi = np.meshgrid(xi, yi)

    try:
        # 嘗試使用線性插值 (高品質)
        zi = griddata((x, y), z, (xi, yi), method='linear')
        
        # 處理線性插值產生的 NaN (邊緣區域)
        # 使用 nearest 填補 NaN 區域，確保地圖完整
        nan_mask = np.isnan(zi)
        if np.any(nan_mask):
            zi_nearest = griddata((x, y), z, (xi, yi), method='nearest')
            zi[nan_mask] = zi_nearest[nan_mask]
            
    except Exception as e:
        print(f"Linear interpolation failed, falling back to nearest: {e}")
        zi = griddata((x, y), z, (xi, yi), method='nearest')

    # 繪圖
    plt.figure(figsize=(10, 8))
    contour = plt.contourf(xi, yi, zi, 20, cmap='jet')
    plt.colorbar(contour, label='Max Signal Strength (dBm)')
    plt.scatter(x, y, c='black', edgecolors='white', s=30, label='Sample Points')
    plt.plot(x, y, 'w--', alpha=0.5, label='Path')
    plt.title('S.C.O.U.T. Fusion Signal Map (Jitter-Corrected)')
    plt.xlabel('Relative X (m)')
    plt.ylabel('Relative Y (m)')
    plt.legend()

    save_path = os.path.expanduser('~/scout-fusion/heatmap.png')
    plt.savefig(save_path)
    plt.close()
    print(f"✅ Heatmap successfully generated: {save_path}")
