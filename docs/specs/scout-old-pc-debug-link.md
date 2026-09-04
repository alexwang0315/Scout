# Scout Old PC Debug Link

## Goal

Use the old PC to prove itself. If it can boot Ubuntu, start the debug agent,
and deliver a bounded report to Scout over a local USB-backed link, Scout records
the machine as usable for headless helper/debug work. If no report arrives inside
the watchdog window, stop buying additional display, RJ45, capture, or adapter
hardware just to keep qualifying that old PC.

This is evidence-only hardware triage. The report and receipt are not Phase 1
runtime safety truth and do not authorize hardware control, provider control,
outbound messages, or Scout runtime mutation.

## Preferred Physical Topology

```text
Old PC booted into Ubuntu
  runs tools/scout_old_pc_debug_agent.py
  USB host port
        |
        | data-capable USB cable
        |
  Scout / Raspberry Pi USB-C OTG port
  exposes USB gadget Ethernet and listens for debug reports
```

The old PC remains the USB host. Scout acts as the USB gadget Ethernet device.
This direction avoids depending on x86 desktop USB ports supporting device mode.

## Scout-Side Ingest

Start the Scout old-PC debug ingest service on the USB gadget address:

```bash
SCOUT_OLD_PC_DEBUG_EVIDENCE_DIR=/data/scout/admin/ingress/old_pc_debug \
./venv/bin/python -m uvicorn 'scout.hardware.old_pc_debug_link:create_old_pc_debug_app' \
  --factory \
  --host 10.55.0.1 \
  --port 8765
```

The endpoint is:

```text
http://10.55.0.1:8765/hardware/old-pc-debug/reports
```

## Old-PC Agent Command

On the old PC Ubuntu boot:

```bash
python3 tools/scout_old_pc_debug_agent.py \
  --subject-ref old-pc-candidate \
  --transport usb_gadget_ethernet \
  --ingest-url http://10.55.0.1:8765/hardware/old-pc-debug/reports
```

The agent intentionally avoids environment variables and raw logs. It samples
bounded read-only signals: boot reachability, agent execution, Linux network
sysfs, DRM/display sysfs, root filesystem capacity, and thermal zones.

## One-Shot Watchdog Decision

- `USABLE_HEADLESS`: Ubuntu booted, the debug agent ran, and Scout received the
  report. Missing RJ45 or display output does not block the headless USB debug
  role.
- `USABLE_WITH_LIMITS`: The machine self-reported, but a degraded boot, storage,
  or thermal signal remains.
- `RETIRE`: No report reached Scout inside the watchdog window, or a critical
  post-boot storage/thermal condition was reported.
- `INCONCLUSIVE`: Required self-proof fields are unknown. Rerun the same local
  link trial once; retire if it remains inconclusive.

## Mac Loopback Smoke

Before using real USB, validate the Scout ingest and receipt path on the Mac:

```bash
./venv/bin/python tools/scout_old_pc_debug_loopback_smoke.py \
  --evidence-dir artifacts/old-pc-debug-link/mac-loopback-smoke \
  --timeout-seconds 5
```

Expected result: `status=passed`, `disposition=USABLE_HEADLESS`, a latest
receipt JSON, a receipt JSONL, and a latest watchdog JSON under the evidence
directory.
