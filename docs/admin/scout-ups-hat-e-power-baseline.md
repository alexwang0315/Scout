# Scout UPS HAT (E) Power Baseline

This document records manual UPS HAT (E) power soak evidence for the Scout Pi 5
field-runtime prototype. The evidence is diagnostic-only: it does not change
Phase 1 safety decisions, does not write UPS control registers, does not enable
automatic shutdown, and does not send outbound messages.

## 2026-06-03 Full Battery Low-Load Soak

Context:

- Hardware: Raspberry Pi 5, SSD, Grove HAT, OLED, LED Bar, GPS-connected bench
  layout, Waveshare UPS HAT (E).
- Power mode: external charger unplugged, UPS battery supplying Scout.
- Runtime mode: Scout runtime present, low-load/idle-ish baseline; no local AI
  inference stress.
- Sampling: 90 samples, 10 seconds between samples.
- Nominal duration: 890 seconds, about 14 minutes 50 seconds.

Evidence files on Scout Pi:

```text
/data/scout/providers/ups_hat_e/soak-20260603T053945Z.jsonl
/data/scout/providers/ups_hat_e/soak-20260603T053945Z-report.json
/data/scout/providers/ups_hat_e/latest-soak-report.json
```

Summary:

```text
battery_percent: 100% -> 99%
battery_percent_delta: -1%
battery_voltage_v_avg: 16.493V
battery_current_ma_avg: -263.5mA
battery_load_w_avg: 4.345W
battery_load_w_min: 3.963W
battery_load_w_max: 6.102W
vbus_power_w_avg: 0.0W
cpu_temp_c_avg: 47.25C
cpu_temp_c_min: 45.5C
cpu_temp_c_max: 49.9C
fan_cur_state_values: [0, 1]
throttled_values: [0x0]
low_cell_voltage_present_any: false
cell_voltage_mv_first: [4144, 4147, 4148, 4146]
cell_voltage_mv_last: [4104, 4107, 4108, 4106]
```

Interpretation:

- This is the first clean full-battery battery-side baseline.
- Current low-load Scout hardware draw is about 4.3W average, with observed
  samples ranging from about 4.0W to 6.1W.
- The Pi did not throttle during the run.
- Fan state briefly reached 1, but CPU temperature stayed below 50C.
- Cell balance looked healthy during this short soak.
- Percentage-based endurance projection is still coarse because the run only
  consumed one reported percent near the top of charge.

Conservative planning estimate:

```text
Low-load baseline: about 4-5W
Short-run observed max: about 6.1W
Planning band before longer discharge proof: 6-8W
```

Next evidence slices:

- 60-120 minute battery soak to calibrate percent drop and Wh estimate.
- GPS/OLED/LED active field soak.
- Local model inference soak.
- Docker/runtime service load soak.
- Thermal soak with enclosure/case layout finalized.
