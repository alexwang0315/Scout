# Scout Provider Control Status Auth Smoke

Date: 2026-05-21

Target: `scout.local`

Runtime URL: `http://scout.local:9099`

Deployment evidence:
`/data/scout/deployments/live-provider-control-auth-20260521T003333Z`

Smoke evidence:
`/data/scout/deployments/provider-control-status-auth-smoke-20260521T003406Z`

## Scope

This smoke verifies that the hardware provider control status endpoint requires
operator bearer-token authorization.

中文註釋：`GET /providers/control/status` 是硬體控制面的只讀 status，但它仍揭露
control policy refs，所以 milestone 收尾時把它與 hardware provider action route
一致化：需要 operator token，不暴露 token 值，不呼叫任何硬體 driver。

## Result

- `artifact_kind=scout_provider_control_status_auth_smoke`;
- `status=passed`;
- `repo_commit=7c95fd6f`;
- `health_status=ok`;
- `runtime_profile=pi-field-live`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `unauthorized_status_code=401`;
- `unauthorized_reason=hardware_control_auth_required`;
- `authorized_status_code=200`;
- `provider_control_status=enabled`;
- `provider_control_allowed_actions=[read_provider_status]`;
- `operator_authorization_required=true`;
- `token_value_exposed=false`;
- `stream_control_status=observing`;
- `secret_values_embedded=false`;
- `new_observations_sent=false`;
- `stream_control_mutation_performed=false`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `phase2_writeback_performed=false`.

## Boundary

Performed:

- one unauthorized provider-control status request;
- one authorized provider-control status request;
- one health check;
- one read-only runtime stream status check.

Not performed:

- no provider control action;
- no hardware driver invocation;
- no stream control mutation;
- no new observation;
- no remote provider send;
- no Telegram send;
- no SOS send;
- no SMS send;
- no satellite send;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation;
- no raw secret value written to committed docs.
