# Spec: Scout Outbound Standing Grant

Date: 2026-07-11

Status: Implemented contract and deterministic runtime slice

## Objective

Allow Scout to execute repeated non-safety outbound actions after one reviewed
session or trip authorization, without asking for confirmation before every
send.

This does not give model output direct network access. The model may produce a
typed `OutboundActionIntent`; deterministic code evaluates the intent, invokes
the configured sender, and records an audit result.

## Execution Path

```text
Scout AI candidate
  -> OutboundActionIntent
  -> PermissionGate
  -> OutboundStandingGrant evaluator
  -> StandingGrantNotificationProvider
  -> configured deterministic transport
  -> summary-only audit record
```

Resident observers are not senders. GNSS, IMU/PDR, MQTT ingress, SX1303, and
LoRaWAN observers remain evidence producers. A sender consumes a separately
approved action intent.

## Grant Scope

An `OutboundStandingGrant` is immutable and contains only reviewed references:

- `session` or `trip` scope and `scope_ref`;
- issue and expiry timestamps;
- provider references;
- recipient references;
- message classes;
- optional MQTT or transport topic references;
- payload data classes;
- priorities;
- maximum successful send count.

The grant does not contain endpoint URLs, access tokens, passwords, private
keys, raw payloads, or model-generated recipients.

## Decision Rules

`allowed`:

- the grant is active and within its time window;
- scope, provider, recipient, message class, topic, data classes, and priority
  all match the grant;
- the successful-send limit has not been reached;
- the intent is not safety-related and contains no secret material.

`needs_approval`:

- no standing grant exists;
- the grant is inactive, not yet valid, or expired;
- a non-safety provider, recipient, message class, topic, data class, or
  priority is outside the reviewed envelope;
- the successful-send limit has been reached.

`blocked` without an approval bypass:

- SOS, incident alert, emergency alert, direct L4, or another safety message
  class;
- a request to mutate Phase 1 L0-L4 state or other safety truth;
- secret material in the outbound intent.

Human approval may create a different non-safety grant. It cannot convert a
safety or secret-material blocker into an AI-executable action.

## Runtime Behavior

`PermissionGate` accepts workflows declaring `external_message` only when each
outbound action carries a valid typed intent. A matching grant removes per-send
confirmation for that outbound action. A missing typed intent or grant returns
`needs_approval`.

`StandingGrantNotificationProvider` independently re-evaluates the intent at
the final transport boundary. It also checks that the configured provider,
notification recipient, and priority match the intent. Successful sends consume
the grant send count; blocked and failed sends do not. The provider recomputes
the notification payload hash and rejects a changed title, body, or priority. A
previously successful idempotency key cannot be sent again in the same provider
process.

The provider removes the full typed intent before calling the transport and
retains only summary fields such as intent id, grant id, references, data class,
and payload hash.

## Current Limits

- No persistent grant store or grant-management API is included in this slice.
- Send-count and idempotency state are process-local until a durable grant store
  is added; this slice is not yet a reboot-resistant production sender.
- No model can create, renew, widen, or activate a grant.
- No observer is converted into a sender.
- No SOS, incident-alert, or safety sender is added.
- No Scout Pi deployment configuration is changed by this slice.
- Actual live transport activation still requires reviewed provider
  configuration and secret references outside the grant artifact.

## Verification

Focused tests are in `tests/test_outbound_standing_grant.py`. They require no
network or real hardware and cover typed validation, allow/approval/block
decisions, PermissionGate integration, runtime execution through an in-memory
transport, audit output, and send-limit enforcement.
