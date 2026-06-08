# Scout Risk Engine 實作規格書 v1.0

> 目的：本文件是給 Codex / 工程代理執行用的開發規格，將 Scout 對話中的概念收斂成可實作的子系統。  
> 主軸：先精練 20m DEM，透過多層次地形指標建立低容錯安全模型；再用 GPX、CP note、現場感測、隊伍 mesh、無人機資料逐步補足局部微地形不足。

---

## 0. 專案名稱

```text
Scout Risk Engine
```

建議 repo 子目錄：

```text
scout/
  risk_engine/
  field_node/
  team_mesh/
  docs/
```

或獨立子專案：

```text
scout-risk-engine/
```

---

## 1. 核心問題定義

Scout 不直接回答「這裡安全或危險」，而是回答：

> 在這個地形與隊伍狀態下，一旦使用者踩錯、滑倒、偏離路徑、GPS 判斷錯誤，還剩下多少修正空間？

核心輸出不是事故預測，而是：

```text
低容錯地形辨識
通過困難度預估
路段風險排序
現場異常感知
隊伍暴露狀態
```

---

## 2. 系統分層

```text
Layer 1: Pretrip Terrain Risk
- 20m DEM / DTM
- 等高線
- GPX corridor
- CP note
- Route risk profile

Layer 2: On-site Field Node
- GPS
- IMU
- Ultrasonic / ToF
- mmWave
- Button
- OLED / LED / vibration
- LoRa / BLE

Layer 3: Team Mesh
- 前鋒 Scout 主節點
- 後衛 Scout 主節點
- 中間 Smart Pole / Light Node
- 隊伍心跳、跌倒、停滯、求助、通過確認

Layer 4: Drone Recon
- 前方路況確認
- 崩塌 / 高繞 / 溪溝偵察
- 局部 3D 重建
- CP note 驗證

Layer 5: Data Flywheel
- 使用者行為
- 多 GPX 通過模式
- CP note / 回報
- 感測器異常事件
- 權重校準與模型更新
```

---

## 3. 第一階段 MVP 範圍

### 必做

```text
1. 讀取 20m DEM / DTM GeoTIFF
2. 產生 DEM-derived terrain features
3. 產生 TEII_20m raster
4. 讀取 GPX route，對路徑取樣
5. 產生 route risk profile
6. 讀取 CP note / waypoint，產生 SCP
7. 輸出 GeoJSON / CSV / JSON risk packets
8. 建立簡單 CLI
9. 建立 unit tests
```

### 暫不做

```text
1. 精準步道寬度
2. 即時影像 AI
3. 完整 LoRa mesh protocol
4. 無人機自動飛行
5. 事故機率模型
```

---

## 4. 資料輸入規格

### 4.1 DEM / DTM

```yaml
required:
  format: GeoTIFF
  crs: projected CRS preferred
  unit: meter
  resolution: 20m initially
```

### 4.2 GPX

```yaml
optional_but_recommended:
  format: GPX
  content:
    - track points
    - timestamp if available
    - elevation if available
```

### 4.3 CP note

```yaml
optional_but_valuable:
  format:
    - GPX waypoint name/comment
    - CSV
    - GeoJSON point
  fields:
    - lat
    - lon
    - text
    - timestamp optional
    - source optional
```

---

## 5. 地形危險感知指標

### 5.1 TEII：Terrain Error Intolerance Index

**地形失誤不容錯指數**

回答：

> 如果人在此處踩錯、滑倒、偏離路徑，後果是否快速惡化？

TEII 是地形本體指標，不因使用者提高注意力而下降。

#### 20m DEM 版 TEII

20m DEM 不追求腳邊微地形精準，而是追求大地形風險排序。

特徵：

```text
slope_macro
downhill_drop_100m
local_relief_100m
contour_density
slope_continuity
```

公式：

```text
TEII_20m =
0.25 × slope_macro
+ 0.25 × downhill_drop_100m
+ 0.20 × local_relief_100m
+ 0.15 × contour_density
+ 0.15 × slope_continuity
```

Peak gate：

```text
TEII_20m_final =
0.70 × TEII_20m
+ 0.30 × max(
    slope_macro,
    downhill_drop_100m,
    local_relief_100m,
    contour_density,
    slope_continuity
)
```

分級：

```yaml
level_1:
  range: 0-20
  meaning: 容錯高

level_2:
  range: 20-40
  meaning: 一般地形

level_3:
  range: 40-60
  meaning: 需注意

level_4:
  range: 60-80
  meaning: 低容錯

level_5:
  range: 80-100
  meaning: 極低容錯
```

---

### 5.2 WCI：Walkability Constraint Index

**步行空間受限指數**

回答：

> 使用者周遭是否缺乏足夠安全踩踏、停留、會車、修正失誤的空間？

只有 20m DEM 時，WCI_micro 不可靠。

```yaml
WCI_micro:
  status: unavailable_or_low_confidence

WCI_proxy:
  source:
    - GPX corridor dispersion
    - CP note
    - contour density
    - TEII gradient
    - local relief
```

高解析資料可用時：

```text
WCI =
0.35 × width_risk
+ 0.25 × safe_area_risk
+ 0.25 × recovery_space_risk
+ 0.15 × asymmetric_exposure_risk
```

---

### 5.3 TRI：Terrain Risk Interval / Persistence Index

**連續暴露指數**

回答：

> 高 TEII / WCI 是否連續維持一段距離，造成長時間低容錯暴露？

```text
TRI =
0.40 × continuous_high_risk_length_score
+ 0.40 × moving_avg_score
+ 0.20 × high_risk_ratio_score
```

建議預設：

```yaml
high_teii_threshold: 70
window_m:
  - 50
  - 100
  - 200
```

---

### 5.4 SRI：Surprise Risk Index

**風險突變指數**

回答：

> 使用者是否從低風險路段突然進入高風險路段？

```text
SRI =
max(0, current_TEII - previous_50m_avg_TEII)
```

標準化：

```text
SRI_score = clamp(SRI / 50 × 100, 0, 100)
```

---

### 5.5 LEC：Location Error Consequence

**定位誤差後果指數**

回答：

> GPS 誤差半徑內，是否存在高風險地形？GPS 偏幾公尺的後果是否嚴重？

```text
LEC =
p90(TEII within GPS_accuracy_radius)
- p10(TEII within GPS_accuracy_radius)
```

保守版：

```text
LEC = p90(TEII within GPS_accuracy_radius)
```

---

### 5.6 SCP：Semantic Critical Point Score

**語意危險點分數**

由登山客 CP note / waypoint / route note 產生。

類別字典：

```yaml
collapse:
  keywords:
    - 大崩壁
    - 崩塌
    - 坍方
    - 土石流
    - 崩溝
    - 落石

exposure:
  keywords:
    - 危崖
    - 斷崖
    - 瘦稜
    - 曝露
    - 兩側深谷

climbing:
  keywords:
    - 拉繩
    - 攀岩
    - 手腳並用
    - 陡上
    - 陡下

reroute:
  keywords:
    - 高繞
    - 低繞
    - 改道
    - 不可通行
    - 路基流失

valley_water:
  keywords:
    - 溪溝
    - 過溪
    - 下切
    - 溯溪
    - 瀑布
    - 濕滑

navigation:
  keywords:
    - 路跡不明
    - 易迷
    - 岔路
    - 布條少
    - 獸徑

vegetation:
  keywords:
    - 箭竹
    - 芒草
    - 咬人貓
    - 倒木
    - 藤蔓
```

SCP 計算：

```text
SCP =
hazard_keyword_weight
× severity_weight
× repeated_reports_weight
× recency_weight
× location_confidence
```

---

### 5.7 MTS：Mesh Terrain Sensing

**網狀地形感知分數**

回答：

> 多個隊伍節點是否共同觀察到同一路段通過困難？

```text
MTS =
0.25 × group_slowdown_consistency
+ 0.20 × segment_stop_density
+ 0.20 × multi_node_stumble_events
+ 0.15 × team_spread_increase
+ 0.10 × cp_confirmations
+ 0.10 × communication_degradation
```

使用方式：

```text
ObservedTrailRisk =
max(
  PretripRisk,
  0.70 × PretripRisk + 0.30 × MTS
)
```

---

### 5.8 PDS：Passage Difficulty Score

**通過困難度分數**

回答：

> 多人或同隊伍通過此路段時，實際行為是否顯示通過困難？

可由以下 proxy label 產生：

```text
相對速度下降
停留時間
心率相對上升
軌跡分散
折返率
高繞率
IMU 不穩
CP note 密度
```

---

## 6. Pretrip Risk 合成

```text
TerrainRisk =
max(
  TEII_20m_final,
  0.65 × TEII_20m_final
  + 0.20 × TRI
  + 0.10 × SRI
  + 0.05 × LEC
)
```

若有 CP note：

```text
PretripRisk =
0.80 × TerrainRisk
+ 0.20 × SCP
```

---

## 7. Route sampling 規格

### 7.1 Sample interval

```yaml
default_sample_interval_m: 20
optional_high_resolution_interval_m: 5
```

### 7.2 每個 route sample 輸出

```json
{
  "route_id": "string",
  "sample_id": "string",
  "distance_m": 1234.5,
  "lat": 24.123456,
  "lon": 121.123456,
  "elevation_m": 2450.2,
  "teii_20m": 82.5,
  "tri": 68.3,
  "sri": 42.0,
  "lec": 88.7,
  "scp": 95.0,
  "pretrip_risk": 87.0,
  "risk_level": 5,
  "hazard_types": ["collapse", "exposure", "reroute"],
  "confidence": {
    "dem_resolution": "20m",
    "teii_confidence": "medium",
    "wci_confidence": "low_or_unavailable",
    "scp_confidence": "medium"
  },
  "explanation": [
    "100m 半徑內下墜高度高",
    "等高線密集",
    "CP note 標註大崩壁需高繞"
  ]
}
```

---

## 8. GPX corridor 規格

GPX 不作為精準步道中心線，只作為 weak prior。

多 GPX 流程：

```text
Load GPX tracks
↓
Clean outliers
↓
Project to metric CRS
↓
Resample by distance
↓
Generate GPX density map via KDE
↓
Extract density ridge as probable trail centerline
↓
Compute cross-track distribution
↓
Estimate corridor width by robust percentiles
↓
Fuse with DEM / DTM terrain constraints
```

輸出：

```yaml
probable_trail_centerline:
  type: LineString

gpx_core_corridor_width:
  definition: P25-P75 cross-track spread

gpx_common_corridor_width:
  definition: P10-P90 cross-track spread

trail_width_confidence:
  range: 0-100

gpx_dispersion_score:
  range: 0-100
```

---

## 9. 現場感測節點規格

### 9.1 已採購模組對應

```yaml
Grove_IMU_9DOF:
  role:
    - stumble_event
    - fall_event
    - pole_angle
    - gait_instability
  priority: high

Grove_Ultrasonic_Ranger:
  role:
    - pole_drop_proxy
    - near_ground_discontinuity
  priority: high

Grove_GPS:
  role:
    - route_segment_lookup
    - speed
    - location_for_LTE_or_LoRa_event
    - LEC_context
  priority: high

Wio_E5_LoRaWAN:
  role:
    - low_bandwidth_event_transport
    - SOS
    - heartbeat
    - team_mesh_packet
  priority: high

LD2450_24GHz_radar:
  role:
    - presence
    - moving_targets
    - team_member_nearby
    - obstacle_motion
  priority: medium

MR60BHA2_60GHz_radar:
  role:
    - rest_state_presence
    - emergency_vital_proxy
    - camp_mode
  priority: medium_low_for_hiking

PIR:
  role:
    - camp_motion
    - low_power_wake_trigger
  priority: low_for_terrain

OLED:
  role:
    - risk_status_display
    - GPS / LoRa / battery status
  priority: medium

LED_Bar:
  role:
    - glanceable_risk_level
  priority: high

Button:
  role:
    - SOS
    - CP mark
    - confirm_hazard
    - cancel_alert
    - mode_switch
  priority: high

MOSFET:
  role:
    - vibration_motor
    - buzzer
    - power_gating
  priority: medium

Recorder:
  role:
    - fixed_voice_alert
    - simple CP voice note
  priority: medium
```

---

### 9.2 Field event types

```yaml
heartbeat:
  fields:
    - node_id
    - role
    - battery
    - motion_state

stumble_event:
  fields:
    - severity
    - accel_peak
    - gyro_peak
    - risk_context

fall_event:
  fields:
    - severity
    - no_motion_duration_s
    - orientation_change

pole_drop_event:
  fields:
    - ultrasonic_distance_cm
    - pole_angle
    - consecutive_count

button_cp_mark:
  fields:
    - button_id
    - current_location
    - risk_context

sos_event:
  fields:
    - node_id
    - location
    - battery
    - last_motion
```

### 9.3 Pole Drop Risk

```text
Pole_Drop_Risk =
distance_jump_score
+ missing_echo_score
+ pole_angle_validity
+ consecutive_detection_bonus
```

Rule v0:

```text
if ultrasonic_distance_cm > 250
and pole_angle_points_down
and consecutive_count >= 3:
    pole_drop_event = true
```

---

## 10. Team Mesh 使用場景

### 10.1 使用者角色

```yaml
solo:
  description: 獨攀者，完整 Scout 主節點

leader:
  description: 前鋒，經驗者，負責探路與前方風險回報

sweep:
  description: 後衛，經驗者，負責隊伍完整性與落後者

member:
  description: 中間隊員，僅需 Smart Pole / Light Node
```

### 10.2 推薦隊伍配置

```text
前鋒：Scout Leader Node
中間隊員：Smart Pole / Wearable Light Node
後衛：Scout Sweep Node
```

不需要每個隊員都有完整 Scout。

### 10.3 Team Risk

```text
TeamRisk =
0.40 × TerrainRisk
+ 0.25 × TeamSpreadRisk
+ 0.25 × MemberStateRisk
+ 0.10 × CommunicationRisk
```

Override：

```text
if TerrainRisk > 75 and MemberStateRisk > 70:
    TeamRisk = max(TeamRisk, 90)
```

### 10.4 Team Exposure State

```yaml
state_0:
  meaning: 全隊未進入高風險段

state_1:
  meaning: 前鋒進入高風險段

state_2:
  meaning: 部分隊員通過中

state_3:
  meaning: 全隊處於高風險段

state_4:
  meaning: 後衛通過，全隊清除
```

### 10.5 Team Mesh 封包

```json
{
  "node": "M03",
  "seq": 1842,
  "role": "member",
  "event": "heartbeat",
  "risk": 62,
  "motion": "moving",
  "battery": 71
}
```

事件封包：

```json
{
  "node": "M03",
  "event": "stumble",
  "severity": 78,
  "segment_id": "trail_12_0450m",
  "relay": ["M04", "sweep"]
}
```

---

## 11. Drone Layer 使用場景

無人機是 Airborne Scout Layer，不是一般行進每一步的必要感測器。

任務：

```text
前方路況確認
崩塌 / 高繞 / 溪溝偵察
局部 3D 重建
搜救輔助
CP note 驗證
```

Drone 指標：

```yaml
drone_path_continuity:
  range: 0-100

drone_collapse_evidence:
  range: 0-100

drone_reroute_evidence:
  range: 0-100

drone_exposure_confirmation:
  range: 0-100

drone_confidence:
  range: 0-100
```

MVP：

```text
使用者手動飛行
匯入影像 / 影片
Scout 產生現場確認報告
不做自主飛行
不做精準導航指令
```

---

## 12. 商轉與業際合作

長期方向：

```text
Terrain-risk intelligence layer
```

潛在合作：

```yaml
outdoor_navigation_apps:
  products:
    - route risk layer
    - CP prediction
    - route difficulty API

wearable_ecosystems:
  examples:
    - Garmin
    - Apple Watch
  products:
    - passage difficulty model
    - behavior proxy calibration
    - on-device warning

government_and_park_agencies:
  products:
    - trail inspection priority
    - post-disaster risk update
    - rescue intelligence

insurance_and_event_organizers:
  products:
    - route risk segmentation
    - event risk monitoring
  caution:
    - privacy
    - fairness
    - liability
```

---

## 13. 資料閉環

Scout 不應等到事故資料才訓練模型。先使用 weak labels：

```text
CP note
使用者按鈕標記
多人 GPX 分散
速度下降
停留增加
折返
高繞
IMU 踉蹌
Pole drop event
隊伍停滯
```

閉環：

```text
Pretrip prediction
↓
現場通過
↓
sensor / behavior / CP feedback
↓
ObservedDifficulty
↓
校準 TEII / WCI / TRI / SRI / LEC 權重
↓
更新模型
```

---

## 14. 建議 repo 結構

```text
scout-risk-engine/
  AGENTS.md
  README.md
  docs/
    scout-risk-engine-spec.md
    decisions/
      0001-use-20m-dem-first.md
      0002-risk-indices.md
  src/
    scout_risk/
      __init__.py
      dem/
        io.py
        terrain_features.py
        teii.py
        contours.py
      gpx/
        parser.py
        corridor.py
        sampling.py
      cp/
        parser.py
        scp.py
        dictionaries.py
      route/
        risk_profile.py
        schemas.py
      field/
        packets.py
        events.py
        pole_drop.py
      team/
        mesh_packets.py
        team_risk.py
        exposure_state.py
      fusion/
        pretrip.py
        realtime.py
      cli.py
  tests/
    test_teii.py
    test_scp.py
    test_route_sampling.py
    test_team_risk.py
  examples/
    sample_config.yaml
    sample_cp_notes.csv
```

---

## 15. Python implementation notes

Recommended libraries:

```text
rasterio
numpy
scipy
geopandas
shapely
pyproj
gpxpy
pydantic
typer
pytest
```

CLI commands:

```bash
scout-risk dem-features --dem data/dem.tif --out out/features/
scout-risk compute-teii --dem data/dem.tif --out out/teii.tif
scout-risk route-profile --dem data/dem.tif --gpx data/route.gpx --cp data/cp.csv --out out/route_risk.geojson
scout-risk parse-cp --input data/cp.csv --out out/scp.geojson
```

---

## 16. Acceptance criteria

### MVP 1

```text
Given a DEM GeoTIFF,
when compute-teii runs,
then output TEII raster with values 0-100.

Given a GPX route,
when route-profile runs,
then output sampled route GeoJSON with TEII_20m, TRI, SRI, LEC placeholders, risk_level.

Given CP notes,
when parse-cp runs,
then output hazard_types and SCP score.
```

### MVP 2

```text
Given route samples and CP notes,
when calibration-report runs,
then output CP hit rate and top-k recall.

Given sensor packets,
when event parser runs,
then identify stumble_event, pole_drop_event, button_cp_mark.

Given team packets,
when team-risk runs,
then output TeamRisk and TeamExposureState.
```

---

## 17. Safety principles

Scout must never claim:

```text
this route is safe
take exactly two steps right
ignore local conditions
```

Scout should say:

```text
此處為低容錯地形
附近定位不確定性高
前方可能有路徑中斷
請放慢並以現場路跡確認
```

High-risk + low-confidence must increase caution, not decrease it.

---

## 18. First Codex implementation request

Implement in this order:

```text
1. Create Python package structure.
2. Implement DEM reader and slope/local relief/drop features.
3. Implement TEII_20m formula.
4. Implement GPX parser and route sampling.
5. Implement CP note parser and SCP scoring.
6. Implement route risk GeoJSON output.
7. Add CLI with Typer.
8. Add unit tests with synthetic DEM arrays.
9. Add sample config and README.
```

Do not implement real-time hardware drivers yet. Stub field packet schemas only.
