# Scout AI NMEA Live Navigation Probe

- artifact_kind: `scout_ai_nmea_live_navigation_probe`
- artifact_version: `scout_ai_nmea_live_navigation_probe.v0`
- question: 我現在是不是離主路太近但站在危險邊緣？
- project_root: `tests/fixtures/pretrip/projects/chilai_nanhua_day1`
- allowed_corridor_m: `30.0`
- boundary: read-only; no `/safety/*`; no Phase 1 L0-L4 mutation; no outbound send

## Summary

| Scenario | Expected Classification | Route Distance | Risk | Assistant Verdict |
| --- | --- | ---: | --- | --- |
| normal_inside_corridor_low_risk | `normal_inside_corridor_low_risk` | 0.00 m | 0.19 / low | Scout AI read-only deterministic skill result: 目前不像是站在危險邊緣：這組 NMEA fix 落在 route corridor 內，且附近 candidate risk 不是高風險。 Scenario=normal_inside_corridor_low_risk; route_distance=0.0 m; allowed_corridor=30.0 m; inside_corridor=true; risk_score=0.19; risk_bucket=low; hdop=0.8; satellites=4。這是 read-only NMEA scenario probe：candidate-only，不是 runtime safety truth，沒有呼叫 /safety/*、沒有改 Phase 1 L0-L4、沒有發送 outbound。 |
| off_route_high_risk_candidate | `off_route_high_risk_candidate` | 45.03 m | 79.58 / high | Scout AI read-only deterministic skill result: 是，這組 NMEA fix 支持「已偏離主路且靠近高風險邊緣」的候選判斷。 Scenario=off_route_high_risk_candidate; route_distance=45.030 m; allowed_corridor=30.0 m; inside_corridor=false; risk_score=79.58; risk_bucket=high; hdop=0.8; satellites=4。這是 read-only NMEA scenario probe：candidate-only，不是 runtime safety truth，沒有呼叫 /safety/*、沒有改 Phase 1 L0-L4、沒有發送 outbound。 |

## NMEA Packets

### normal_inside_corridor_low_risk

```text
$GPGGA,010203.00,2402.40995,N,12117.13580,E,1,04,0.8,1280.5,M,0.0,M,,*60
$GPRMC,010203.00,A,2402.40995,N,12117.13580,E,1.20,45.0,070626,,,A*57
$GPGSV,1,1,04,01,45,083,42,02,17,308,38,03,28,123,36,04,67,210,41*7B
```

Parsed GNSS fix:

```json
{
  "altitude_m": 1280.5,
  "checksum_valid": true,
  "course_deg": 45.0,
  "gnss_time_utc": "2026-06-07T01:02:03.00Z",
  "hdop": 0.8,
  "lat": 24.04016583,
  "lon": 121.28559667,
  "quality": 1,
  "satellites": 4,
  "speed_mps": 0.617,
  "valid": true
}
```

### off_route_high_risk_candidate

```text
$GPGGA,010203.00,2403.06428,N,12113.23854,E,1,04,0.8,1280.5,M,0.0,M,,*6B
$GPRMC,010203.00,A,2403.06428,N,12113.23854,E,1.20,45.0,070626,,,A*5C
$GPGSV,1,1,04,01,45,083,42,02,17,308,38,03,28,123,36,04,67,210,41*7B
```

Parsed GNSS fix:

```json
{
  "altitude_m": 1280.5,
  "checksum_valid": true,
  "course_deg": 45.0,
  "gnss_time_utc": "2026-06-07T01:02:03.00Z",
  "hdop": 0.8,
  "lat": 24.05107133,
  "lon": 121.22064233,
  "quality": 1,
  "satellites": 4,
  "speed_mps": 0.617,
  "valid": true
}
```
