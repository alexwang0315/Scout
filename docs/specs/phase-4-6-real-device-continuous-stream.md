# Spec: Phase 4.6 Real Device Continuous Stream

Date: 2026-05-21

## Objective

Phase 4.6 moves Scout from signed sample stream admission to real Apple Watch /
mobile continuous stream readiness.

中文註釋：這個 milestone 的目標是讓真裝置連續串流有明確身份、簽章、排序、
重送、限流與 operator control 語意。它不是 field mission 自動出發，也不是
SOS / SMS / satellite / incident bridge live send 的啟用。

Success means a real Apple Watch or mobile client can use the existing
`/runtime/streams/*` surface with a versioned contract that is testable before
any long field run:

- device identity is explicit and bound to `source_id`, `source_kind`,
  `device_id`, token scope, and HMAC secret ref;
- each payload is signed with HMAC-SHA256 and verified before runtime
  processing;
- sequence and dedupe behavior is deterministic per `source_id + device_id`;
- cadence above 10 Hz is backpressured before `SafetyRuntimeSession.observe`;
- offline retry keeps bounded queue state and falls back to latest point after
  retry exhaustion;
- operator pause/resume applies to Scout server-side admission, not device
  hardware;
- status and evidence artifacts remain summary-only and do not expose secrets
  or raw payloads.

## Non-Goals

- no automatic SOS send;
- no SMS send;
- no satellite send;
- no incident bridge opt-in or remote notification send;
- no assistant safety mutation;
- no Phase 2 Brain writeback;
- no hardware driver invocation;
- no raw Apple Watch/mobile payload storage in committed docs or summary
  artifacts;
- no broad rewrite of Phase 1 route-progress or safety state behavior.

## Device Identity

`RuntimeStreamDeviceIdentity` / 串流裝置身份 is the durable identity Scout uses
to decide whether an envelope belongs to an allowed real source.

Minimum fields:

- `source_id`: versioned stream source, such as
  `runtime_source.apple_watch.v0`;
- `source_kind`: `apple_watch` or `mobile_phone`;
- `device_id`: stable per-device id chosen by the client provisioning flow;
- `display_name`: operator-readable name, not a secret;
- `credential_ref`: metadata-only reference to the scoped token/HMAC material;
- `token_scope`: must be `runtime:observation:write`;
- `hmac_secret_ref`: secret reference such as env/file/keychain path, never the
  secret value;
- `enabled`: disabled identities reject admission before runtime processing.

中文註釋：`device_id` 只能當識別，不能單獨當信任來源。Scout 必須同時檢查
device identity、限定用途 token scope、payload hash 與 HMAC signature。

## Token / HMAC

The first real-device trust model remains
`device_id_scoped_token_hmac_signature`.

- token scope is fixed to `runtime:observation:write`;
- the HMAC secret is resolved outside committed artifacts;
- HMAC-SHA256 signs device id, source id, transport, sequence number,
  observed timestamp, and payload SHA-256;
- signature verification happens before sequence, dedupe, cadence, or runtime
  observation conversion;
- summary responses may expose `credential_ref`, `token_scope`, and
  `signature_algorithm`, but never token or secret values.

## Sequence / Dedupe

Ordering is per `source_id + device_id`.

- sequence numbers must be monotonic for that stream;
- dedupe key is `source_id + device_id + sequence_no + payload_sha256`;
- duplicate dedupe keys reject with `rejected_duplicate`;
- older or equal sequence numbers reject with `rejected_sequence`;
- rejected duplicate/out-of-order payloads do not call
  `SafetyRuntimeSession.observe`.

## 10 Hz Backpressure

The maximum accepted cadence is 10 Hz.

- `max_hz=10.0`;
- `min_interval_ms=100`;
- observations below the interval are marked `queued_backpressure`;
- backpressured observations update queue summaries only and are not forwarded
  into Phase 1 processing in that request;
- status surfaces expose queue depth and counters without raw payloads.

## Offline Retry

Real clients may temporarily lose connectivity.

- disconnected submissions are recorded as `queued_disconnected`;
- retry attempts are bounded by the policy limit, currently five attempts;
- retry metadata is summary-only;
- the device client owns local raw-payload buffering until it reconnects;
- Scout server summaries must not persist raw queued payloads.

## Latest-Point Fallback

After retry exhaustion, Scout retains only the latest point reference for the
stream.

- status becomes `latest_point_retained`;
- stale queued keys for the same `source_id + device_id` are dropped;
- the retained record is a dedupe key / hash reference, not lat/lon payload;
- the fallback is meant to restore situational continuity, not reconstruct the
  full missed track.

## Operator Pause / Resume

Operator controls are server-side admission controls.

- `pause` rejects new HTTP push/WebSocket observations with
  `runtime_stream_paused`;
- `resume` allows new observations after the control state returns to
  `observing`;
- `end` is terminal for the server-side stream;
- `drain-queue` clears disconnected/backpressure/latest-retained summaries but
  preserves dedupe history;
- none of these commands stop Apple Watch/mobile sensor collection or command
  hardware drivers.

中文註釋：`pause` 不是遙控手錶停止感測。它只表示 Scout server 暫停接收進
safety runtime 的路徑；真裝置可以繼續本機收集、排隊，等 operator resume 後再依
retry/backpressure policy 嘗試送出。

## Risk Boundary

- All live action requires an evidence directory.
- All new hardware/live behavior requires focused tests.
- Secret values and raw payloads must not be written to repo docs, status
  summaries, or telemetry snapshots.
- Assistant output cannot pause, resume, drain, end, or mutate safety state.
- Continuous stream work must stay on `/runtime/streams/*`; direct
  `/safety/observations` remains lower-level signed admission after handoff.
- Incident bridge remains opt-in-required and disabled.

## Parallel Slices

- Slice A: device identity registry and admission binding
  - Files: `runtime_stream_device_identity.py`, `runtime_input_admission.py`,
    focused tests.
  - Boundary: metadata-only, no secret loading, no network.
- Slice B: real-device client harness
  - Files: a Watch/mobile HTTP-push test client or fixture harness.
  - Boundary: dry-run by default; live send only with explicit operator flag.
- Slice C: cadence/offline soak evidence
  - Files: admin smoke doc and bounded runner.
  - Boundary: evidence directory required; no remote notifications.
- Slice D: operator pause/resume real-device smoke
  - Files: admin smoke doc and focused test helper.
  - Boundary: final status must be restored to `observing`.
- Slice E: load/thermal report
  - Files: admin evidence doc.
  - Boundary: read-only status sampling plus explicit test observations only.

## Minimal Slice

The first implementation slice is Slice A plus one response-contract hardening:

- add a metadata-only device identity registry;
- make runtime input admission optionally check identity binding after source
  policy and before sequence/dedupe/cadence;
- include identity match metadata in admission summaries;
- enrich pause/end rejection details with server-side device semantics;
- verify with focused unit/API tests.
