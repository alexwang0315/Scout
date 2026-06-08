# Spec: Pi 5 GPIO Control Surface Boundary

這份 spec 只定義 GPIO / physical ACK / manual SOS button 的 read-only event
contract。它不是 live GPIO driver，也不是 `/safety/*` mutation endpoint。

## Boundary

- 不讀真 GPIO。
- 不控制硬體 provider。
- 不呼叫 `/safety/*` mutation。
- 不改 Phase 1 safety decision。
- 不寫 IncidentStore、ObservedFact 或 Brain。
- 不送 outbound、SOS、SMS 或 satellite。

## Step 1 Contract

`hardware_control_events.py` 只把 fixture event 投影成
`hardware_control_event_projection`。`scout_gpio_control_watcher.py` 只讀 fixture 並輸出
projection report，不開網路、不 POST、不碰 runtime。

中文註釋：手動 SOS 按鈕的真實語義很重要，但目前 slice 只允許形成 operator-reviewed
artifact。等 hardware runtime、operator policy、事件防抖與誤觸流程確認後，才能討論是否
建立 live runtime endpoint。

## Live Endpoint Decision

Decision for this milestone: no live GPIO endpoint is added.

`manual_sos_button_observed` and related events remain projection-only. They can
appear in an operator-reviewed artifact, but they cannot be converted into a
Phase 1 safety event, `/safety/*` mutation, outbound message, incident write, or
provider command by default.

To reopen this decision, the project needs a separate operator policy that
defines:

- who may arm the button path;
- debounce and accidental-press handling;
- offline confirmation wording;
- exact Phase 1 adapter semantics;
- rollback behavior when GPIO hardware is unavailable.
