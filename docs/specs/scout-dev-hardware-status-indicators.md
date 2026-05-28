# Spec: Scout Dev Hardware Status Indicators

Date: 2026-05-27

Status: Draft for Pi 5 + Grove HAT bring-up

## Objective

Define the temporary development status indicators used during Scout Pi 5
hardware bring-up.

This document covers the Grove LED Bar v2.0 and Grove OLED Display 1.12 inch
currently attached through the Grove HAT. These indicators are diagnostic
tools for developers. They are not product HMI and they are not safety decision
sources.

中文註釋：這份文件只定義開發期診斷燈號，不是最終產品的使用者介面設計。

## Hardware Scope

Validated hardware:

- Raspberry Pi 5;
- Grove HAT connected through the 40-pin ribbon/header path;
- Grove LED Bar v2.0 on `D5` in the current bench layout;
- 4x4 matrix keypad on Grove digital ports `D16,D18,D24,D26`;
- Grove OLED Display 1.12 inch on the I2C port.

Observed facts:

- Grove HAT / 40-pin HAT body must not be hot-plugged.
- Hot-plugging the Grove HAT at the ribbon end previously rebooted the Pi.
- `vcgencmd get_throttled` reported `0x0` after later testing.
- Grove LED Bar v2.0 uses the MY9221 protocol, not single GPIO high/low.
- Current D5 LED Bar mapping:
  - data: `GPIO5`;
  - clock: `GPIO6`.
- Historical D16 LED Bar mapping that also worked:
  - data: `GPIO16`;
  - clock: `GPIO17`.
- LED Bar moved from D16 to D5 to reserve eight non-I2C/non-UART GPIO lines
  for the 4x4 matrix keypad smoke tool.
- Current keypad mapping from Grove ports:
  - `D16`: `GPIO16`, `GPIO17`;
  - `D18`: `GPIO18`, `GPIO19`;
  - `D24`: `GPIO24`, `GPIO25`;
  - `D26`: `GPIO26`, `GPIO27`;
  - default rows: `16,17,18,19`;
  - default cols: `24,25,26,27`.
- Current keypad scan mode is `active-high`; 2026-05-28 post-rewire smoke
  captured key events in `active-high`, while `active-low` captured none.
- Grove OLED scanned at `0x3c` on `/dev/i2c-1`.
- OLED SH1107G initialization path has displayed a test pattern.

## Boundary

Dev indicators may show subsystem status.

They must not:

- change Phase 1 safety decisions;
- call live `/safety/*` mutation endpoints;
- send outbound messages;
- write IncidentStore, ObservedFact, Phase 2 Brain, or review decisions;
- be treated as a source of truth for L0-L4;
- replace final product HMI design.

Required payload fields for smoke tools:

```text
phase1_safety_decision_change_allowed=false
remote_outbound_allowed=false
hardware_control_scope=diagnostic_indicator_only|diagnostic_display_only
```

## LED Bar 10-Bit Development Mapping

The LED Bar has 10 positions. During development, each LED can represent one
subsystem bit.

| LED | Development Bit | Meaning |
| ---: | --- | --- |
| 1 | runtime alive | Scout runtime process/API is alive |
| 2 | storage writable | `/data/scout` or target data root is writable |
| 3 | GNSS provider active | GNSS evidence producer active or fixture-projected |
| 4 | IMU provider active | IMU evidence producer active or fixture-projected |
| 5 | battery telemetry active | battery/fuel telemetry available |
| 6 | Bluetooth connected | BLE/phone/team link connected or scan active |
| 7 | radio scan active | Wi-Fi/BLE radio scan evidence tool active |
| 8 | voice cue engine ready | local voice cue dry-run or TTS path ready |
| 9 | runtime stream / event bus active | stream transport or event bus path active |
| 10 | safety concern present | diagnostic projection that concern exists |

Example bit payload:

```text
0x003  # runtime alive + storage writable
0x083  # runtime alive + storage writable + radio scan active
0x203  # runtime alive + storage writable + safety concern present
```

Important:

- Development bits are operator diagnostics.
- Productized lights must be redesigned under product HMI rules.
- Do not infer safety state from LED Bar state.
- Do not feed LED Bar state back into Scout runtime.

## OLED Development Display

The OLED display can show short diagnostic text during bring-up:

```text
SCOUT
I2C OK
0x3C
```

Recommended uses:

- confirm I2C bus health;
- display smoke tool status;
- display target address/driver attempts;
- show operator-facing test labels during bench bring-up.

Non-goals:

- route navigation UI;
- emergency authority;
- final product text layout;
- user-facing alert taxonomy.

## Smoke Tools

LED Bar:

```bash
python3 tools/pi_grove_led_bar_smoke.py \
  --port D5 \
  --pattern status_bits \
  --bits 0x003 \
  --output-jsonl /data/scout/providers/grove_led_bar/manual-smoke.jsonl
```

OLED:

```bash
python3 tools/pi_oled_i2c_smoke.py \
  --bus /dev/i2c-1 \
  --address 0x3c \
  --driver sh1107g \
  --message "SCOUT\nI2C OK\n0x3C" \
  --output-jsonl /data/scout/providers/oled_i2c/manual-smoke.jsonl
```

Dry-run from a workstation or non-Pi host:

```bash
python3 tools/pi_grove_led_bar_smoke.py --dry-run --port D5 --pattern status_bits --bits 0x003
python3 tools/pi_oled_i2c_smoke.py --dry-run --driver auto --address 0x3c
```

## Hardware Safety Notes

- Power off the Pi before attaching or removing the Grove HAT or 40-pin ribbon.
- Do not hot-plug the HAT body.
- Grove modules on Grove sockets may still need care; avoid moving the HAT
  connection while powered.
- Confirm power health with `vcgencmd get_throttled`.
- Confirm I2C device presence before OLED writes.
- Keep LED/OLED smoke tools host-side and diagnostic-only.

## Next Step

After smoke tools are stable, add a read-only status collector that turns Scout
runtime/provider status into the 10-bit development LED mapping. That collector
must remain diagnostic-only and must not write to `/safety/*`.
