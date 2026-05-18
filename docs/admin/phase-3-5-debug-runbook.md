# Phase 3.5 Debug Runbook

This runbook is for Scout hardware/debug/readiness tooling. It is the repeatable
path for opening the Phase 3.5 debug surface before any Raspberry Pi, Docker, or
real outbound integration work.

中文註釋：

- 這不是一般使用者 UI。
- 這不是 pre-trip planning。
- 這是 hardware/debug/readiness tooling。
- `/debug` 必須 read-only。
- debug event 不能影響 Scout safety runtime。
- outbound message 初期必須是 mock transport，不直接接真 SOS、真簡訊、真衛星。

## 1. Generate The Demo Log

From the repo root:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase35_debug_demo_loader.py --pretty
```

Default output path:

```text
/tmp/scout-phase35-ui-demo.jsonl
```

The loader only writes a deterministic fixture-backed JSONL debug log and prints
the command to start the existing server. It does not start the server, does not
connect to hardware, does not mutate Phase 1 safety state, and does not use real
outbound transport.

## 2. Start The Debug Surface

Use the `server_command` printed by the loader, or run:

```bash
SCOUT_DEBUG_API_ENABLED=1 \
SCOUT_DEBUG_LOG_PATH=/tmp/scout-phase35-ui-demo.jsonl \
SCOUT_SAFETY_ENABLED=false \
/Users/alexwang0315/scout-fusion/venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 9099
```

If port `9099` is already in use, regenerate the printed command with another
port:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase35_debug_demo_loader.py --port 9100 --pretty
```

Then open:

```text
http://127.0.0.1:9099/admin/debug
```

## 3. Verify JSON Endpoints

These endpoints must be GET-only:

```text
/debug/events
/debug/state
/debug/messages
```

Expected demo contents:

- timeline has 22 debug events;
- map highlights update when a timeline node is selected;
- L0-L4 state shows `L0->L2` around the safety transition;
- Provider tab shows degraded and recovered status;
- Incident tab shows package creation, persistence, and Phase 3 bridge result;
- Ln / Skill tab shows allowed, blocked, started, completed, and failed states;
- Outbound tab shows mock queued, sent, and mock-delivered states;
- Boundary tab remains read-only and no real outbound transport is allowed.

## 4. Troubleshooting

If the page loads but has no events:

- confirm `SCOUT_DEBUG_LOG_PATH` points to `/tmp/scout-phase35-ui-demo.jsonl`;
- rerun `phase35_debug_demo_loader.py --pretty`;
- confirm `/debug/events` returns event envelopes.

If outbound messages are empty:

- confirm `/debug/messages` returns at least one message;
- confirm the message transport is `mock`;
- confirm the boundary flags for real SOS, SMS, and satellite sends are false.

If the timeline cannot be scrolled:

- refresh `/admin/debug` after rebuilding the page;
- confirm the page includes `timeline-panel`;
- the timeline body should be the scroll container, while the map/details column
  stays visible.

## 5. Acceptance Commands

Focused Phase 3.5 checks:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_runtime_debug_event_log.py \
  tests/test_runtime_simulator.py \
  tests/test_runtime_debug_ui_demo.py \
  tests/test_mock_outbound_transport.py \
  tests/test_debug_api.py \
  tests/test_debug_api_mount.py \
  tests/test_debug_page.py \
  tests/test_phase35_debug_runbook.py \
  tests/test_phase35_runtime_readiness_check.py

/Users/alexwang0315/scout-fusion/venv/bin/python phase35_runtime_readiness_check.py --pretty
```
