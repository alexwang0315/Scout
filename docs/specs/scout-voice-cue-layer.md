# Spec: Scout Voice Cue Layer

## Objective

Add a local voice cue layer for Scout without changing Phase 1 safety runtime
authority.

Scout is a wilderness safety black box / personal safety OS. Voice output is an
outbound awareness channel: it can speak Scout-generated route, body, weather,
device, team, and environment cues to the user, but it is not a new safety
evaluator and not a remote alert transport.

中文註釋：`voice cue` 是「本地提醒聲音」，不是聊天機器人回話，也不是 SOS、SMS、
satellite、remote status 的發送通道。

## Boundary

Every voice cue carries a fixed boundary:

```text
safety_decision_change_allowed=false
remote_outbound_allowed=false
hardware_control_allowed=false
```

The first implementation also keeps these closed:

- no live `/safety/*` mutation;
- no SOS trigger;
- no SMS send;
- no satellite send;
- no Bluetooth control;
- no hardware provider control;
- no IncidentStore, ObservedFact, or Brain write.

中文註釋：語音可以提醒「Scout 已經看到什麼或建議你注意什麼」，但不能自己把
L0-L4 safety level 改掉，也不能替使用者或 Scout 發出遠端求救。

## Content Semantics

Voice cue content can come from deterministic Scout evidence or a read-only
model interpretation.

Rules:

- deterministic facts and model interpretations must stay labeled separately;
- model-generated explanation must be labeled
  `read_only_model_interpretation`;
- voice playback must not turn model interpretation into observed fact;
- voice playback success or failure is only transport evidence.

中文註釋：如果 AI 的解釋被唸出來，語音內容仍然是「模型解讀」，不是 Scout 已驗證的
deterministic fact。

## Engine Direction

Primary TTS engine:

- Piper TTS.

Fallback TTS engine:

- eSpeak NG.

The first slice only builds command plans and a dry-run smoke tool. It does not
require Piper or eSpeak NG to be installed on the developer machine.

中文註釋：`Piper` 是主要本地語音引擎；`eSpeak NG` 是退路。第一版先確認 Scout 能
產生可審計的 command plan，不把音訊播放變成測試或開發機依賴。

## First Slice

Implemented scope:

- `voice_cue_models.py` defines the local voice cue contract;
- `voice_cue_policy.py` handles priority ordering, rate limiting, silence, and
  acknowledgement state;
- `voice_tts_provider.py` builds Piper and eSpeak NG command plans;
- `mock_voice_transport.py` records queue/render/play/failure state as JSONL;
- `mock_voice_transport.py` can optionally append read-only Phase 3.5
  `voice_cue_queued` and `voice_cue_state_changed` debug events;
- `tools/pi_voice_tts_smoke.py` emits a dry-run TTS command plan and optional
  JSONL record.

Out of scope:

- live safety evaluator wiring;
- server mount;
- real Bluetooth audio sink;
- phone companion TTS;
- automatic audio playback in tests;
- remote alert sending.

## Manual Dry Run

Default dry-run:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python tools/pi_voice_tts_smoke.py \
  "請停下確認方向。" \
  --engine piper \
  --output-jsonl /data/scout/providers/voice_cue/manual-smoke.jsonl
```

Fallback command-plan dry-run:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python tools/pi_voice_tts_smoke.py \
  "裝置電量偏低。" \
  --engine espeak
```

The tool only executes Piper/eSpeak/aplay when `--execute` is provided.

中文註釋：`--execute` 是明確 opt-in。沒有 `--execute` 時，工具只輸出 JSON command
plan，不播放音訊，也不要求本機已安裝 Piper 或 eSpeak NG。

## Debug Projection

When `MockVoiceTransport` is constructed with a debug log, it appends
`RuntimeDebugEvent` records for:

- `voice_cue_queued`;
- `voice_cue_state_changed`.

These events are read-only queue/state projections. They may be inspected via
`/debug/events` in the Phase 3.5 runtime debug layer, but they do not grant voice
cue code authority to call `/safety/*`, send remote outbound alerts, or control
hardware.

中文註釋：debug event 只是「語音提示佇列狀態」的觀察紀錄，不是 Phase 1 safety
runtime 的輸入，也不是遠端告警或硬體控制命令。

## Scout Machine Activation Status

Status as of 2026-05-21: the voice cue layer is active for Scout machine
development smoke tests on `scout.local`.

This is a host-side development activation, not a Phase 1 live safety runtime
integration. The Scout live runtime container was not restarted or modified for
this activation.

中文註釋：這裡的「開通」是指 Scout 機器可以在 host-side smoke 目錄用 Piper 產生語音，
並透過藍牙喇叭播放；不是把語音提示接進 Phase 1 safety evaluator，也不是讓語音層
取得 SOS、遠端 outbound 或 hardware provider control 權限。

Activated paths and components:

```text
host smoke root: /home/alexwang0315/scout-voice-cue-smoke
voice cue data root: /data/scout/providers/voice_cue
Piper package: piper-tts==1.4.2
Piper binary: /home/alexwang0315/scout-voice-cue-smoke/venv/bin/piper
Piper voice model: /data/scout/providers/voice_cue/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx
Piper voice config: /data/scout/providers/voice_cue/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx.json
Bluetooth audio bridge: bluez-alsa-utils
Bluetooth bridge services: bluealsa, bluealsa-aplay
Bluetooth speaker: LS-S01
Bluetooth speaker MAC: 34:D2:CF:30:6F:2C
Bluetooth profile: A2DP Audio Sink
BlueALSA PCM: bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa
Autoconnect service: scout-ls-s01-autoconnect.service
Autoconnect script: /usr/local/sbin/scout-connect-ls-s01.sh
Autoconnect log: /data/scout/providers/voice_cue/ls-s01-autoconnect.log
Successful playback evidence: /data/scout/providers/voice_cue/ls-s01-execute-20260521T040935Z
```

Known successful smoke command shape:

```bash
ssh scout 'cd ~/scout-voice-cue-smoke && \
  venv/bin/python tools/pi_voice_tts_smoke.py \
    "Scout 藍牙喇叭測試：LS-S01 已連線，請停下確認方向。" \
    --engine piper \
    --piper-binary /home/alexwang0315/scout-voice-cue-smoke/venv/bin/piper \
    --piper-model /data/scout/providers/voice_cue/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx \
    --playback-command "aplay -D bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa" \
    --audio-file /data/scout/providers/voice_cue/manual-smoke.wav \
    --output-jsonl /data/scout/providers/voice_cue/manual-smoke.jsonl \
    --execute'
```

The successful playback result must still carry:

```text
safety_decision_change_allowed=false
remote_outbound_allowed=false
hardware_control_allowed=false
execution_failed=false
```

The `scout-ls-s01-autoconnect.service` only reconnects the development audio
sink after boot. It must not be treated as Scout runtime hardware-provider
control, and it must not call `/safety/*` mutation endpoints.

## Next Slice: Fixture-backed Debug Demo

Planned/implemented CLI:

```text
tools/voice_cue_debug_demo.py
```

The demo dry-runs the full local debug projection path:

```text
fixture VoiceCue -> VoiceCuePolicy -> MockVoiceTransport -> RuntimeDebugEvent JSONL
```

Required boundary:

- fixture-backed only;
- read-only dry run;
- no live `/safety/*` call;
- no safety decision mutation;
- no audio playback;
- no remote outbound send;
- no SOS, SMS, or satellite send;
- no hardware provider control.

Expected output is append-only JSONL containing mock transport state and
read-only `RuntimeDebugEvent` records that can be inspected by the Phase 3.5
debug layer. The CLI is a developer/operator visibility demo, not a runtime
integration and not a deployment prerequisite.

中文註釋：`voice_cue_debug_demo.py` 是「fixture-backed 語音提示 debug demo」，
用固定 fixture 驗證 VoiceCue 到 policy、mock transport、RuntimeDebugEvent/JSONL 的
投影路徑。它不播放聲音、不打 `/safety/*`、不送遠端 outbound、不控制硬體，也不把語音
提示變成 Phase 1 safety runtime 的輸入。

## Future Transports

Future slices may add:

- local speaker playback on the Scout node;
- Bluetooth audio sink;
- phone companion TTS;
- haptic or display fallback;
- admin/debug visibility for voice cue queue state.

Those transports must keep the same boundary unless a later spec explicitly
changes the product authority model.
