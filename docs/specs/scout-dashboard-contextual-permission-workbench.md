# Scout Dashboard Contextual Permission Workbench

Status: Candidate/shadow prototype implemented — OD-001 through OD-018 only;
not runtime authority or a production Safety system

Last updated: 2026-08-02

## 1. Objective

Define the Dashboard `Exploring for Six Axis -> Permission` page as a
**pre-trip candidate-rule workbench** that can explain how append-only field
events change the constraints for the uncompleted part of the mission.

The page must answer two different questions without conflating them:

1. What did the reviewed pre-trip candidate plan allow?
2. Given the events observed so far, what constraints apply from now onward?

The page is not the field-runtime authority surface. Ordinary Dashboard mode
may inspect, compare, replay, and simulate candidate decisions. It must not
claim that a live action was authorized, mutate Phase 1 runtime safety truth,
or call `/safety/*`.

## 2. Normative References

- `docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md`
  - Section 8: Contextual Permissioning.
  - Section 13: Risk Budget.
  - Section 16: Required Decision Output Format.
  - Section 17: `ContextualPermission` decision object.
  - Section 23: Acceptance Criteria.
- `docs/specs/scout-workspace-layout.md`
  - pre-trip permission model and candidate rules;
  - reviewed mission graph;
  - append-only on-trip runtime session event families.
- `docs/specs/scout-runtime-multi-gate-safety-reducer.md`
  - route-progress feed;
  - pace, delay, darkness, weather, environment, and physiologic gates;
  - reducer hysteresis and durable replay state.

If this document conflicts with a hard safety boundary in those sources, the
hard safety boundary wins.

## 3. Confirmed Product Decisions

### D-001 — Page purpose

The page is a pre-trip candidate-rule workbench, not a generic AI OS effect
permission page and not the production field-approval UI.

Canonical page term:

> Contextual Permission Workbench / 情境授權工作台

The short sidebar label may remain `Permission`, but the page header and truth
strip must say `Contextual Permission` so it cannot be confused with workflow,
credential, filesystem, or outbound-effect permissions.

### D-002 — Immutable baseline and forward-only adjustment

Pre-trip candidate rules and the reviewed mission graph form an immutable,
hash-bound baseline. Field events never overwrite that baseline.

An observed field event produces a derived **Forward Constraint Projection**:

> a deterministic projection, valid only after a specified event sequence,
> describing how the remaining mission differs from the reviewed baseline.

Past decisions, granted limits, and observed behavior remain traceable. Only
uncompleted plan nodes may receive derived adjustments.

### D-003 — Safety reserves are non-fungible

Time debt must not consume or disguise any of these protected reserves:

- daylight reserve;
- weather reserve;
- retreat reserve;
- slowest-member reserve;
- required recovery rest;
- mandatory safety, check-in, equipment, or regrouping actions.

Only explicitly discretionary future events may be shortened or cancelled to
repay time debt automatically.

Night travel is not a time buffer. It is a separate `CHANGE_PLAN` candidate and
may be considered only when a reviewed night-capable alternative, equipment,
team capability, route terrain, weather, communication, and runtime gate
conditions all support it. It must never be selected merely because the plan
is late.

### D-004 — Remaining Mission Projection is the primary visual object

The Dashboard workbench is remaining-plan first:

- a compact Current Decision strip stays above the fold;
- the original-versus-effective Remaining Mission Projection is the primary
  visual object;
- time-debt propagation and affected future events are directly visible;
- the map is supporting evidence and route focus, not the page hero;
- a decision-first, phone-first field-runtime surface remains separate.

### D-005 — Preserve the established Dashboard visual language

The Permission page must reuse the existing Dashboard field-instrument design
system. It must not introduce an isolated Permission theme or a second set of
shell, navigation, map, status, or evidence patterns.

Required reused primitives:

- existing five-axis truth strip: Surface, Data, Action, Verification, and
  Provenance / Readiness;
- `outdoorTabs()` for the Six Axis page switcher;
- global color, typography, spacing, border, focus, and semantic status tokens;
- field-instrument panel, panel heading, chip, table, metric, and small-note
  treatments;
- the shared Dashboard map viewport controller and Rudy+TW supporting-basemap
  policy;
- the existing evidence drawer and source-ref interaction patterns;
- the established 1120 px desktop-collapse and 760 px mobile-workbench
  breakpoints where they fit this page.

The route should use the Dashboard wide-frame layout, matching Architecture and
Navigation workbench density. Permission-specific components may have their own
semantic class names, but their visual tokens and interaction grammar must come
from the shared Dashboard system.

### D-006 — Inspect stored decisions by default; simulate only on explicit request

Selecting an action, plan node, event, or session is an inspection operation. It
filters and focuses the baseline, runtime/replay events, and last evaluated
projection already returned by the Dashboard read contract. Selection alone
must not run the permission assessor, fetch new evidence, or create an artifact.

If the operator changes a hypothetical scenario input, the workbench must show
`Inputs changed · not evaluated`. The existing Current Decision and effective
projection remain visible as the last evaluated state; they must not be silently
relabelled as the result of the changed inputs.

A new evaluation requires an explicit `Run candidate simulation` action. The
simulation must:

- use the deterministic contextual-permission assessor and forward projector;
- be bounded to the selected baseline/session plus explicitly visible scenario
  overrides;
- return `candidate_only=true`, `runtime_safety_truth=false`, and
  `writesPerformed=false` by default;
- expose its scenario hash, source lineage, missing evidence, and boundary;
- render as a comparison candidate without replacing Current Decision;
- perform no model call, upstream evidence fetch, `/safety/*` call, runtime
  authorization, outbound action, hardware control, or implicit persistence.

Candidate simulations remain ephemeral in this workbench contract. OD-006
authorizes only the explicit Mission Baseline version/review writes defined in
D-010; it does not authorize saving a runtime what-if simulation as a baseline.

### D-007 — Adjustment policy belongs to each reviewed remaining-plan node

Automatic time-debt repayment must be governed by a typed policy on each
remaining plan node, not inferred from `OutdoorAction` alone. The same action
may have different semantics: an optional photography stop may be reducible,
while a stop for injury response or team regrouping is protected.

Each adjustable plan node must expose at least:

```text
nodeId
actionId
targetDurationMinutes
minimumDurationMinutes
cancellable
priority
adjustmentPolicy: auto_reduce | protected_floor | review_only
policyReason
policySource
sourceRefs[]
```

The policies mean:

| Policy | Projector authority | Typical reviewed use |
| --- | --- | --- |
| `auto_reduce` | May reduce the target toward the minimum. It may cancel only when `cancellable=true` and the reviewed minimum is zero. | Optional photography, filming, tripod setup, observation, or discretionary stop. |
| `protected_floor` | May reduce only explicitly discretionary excess above the reviewed minimum. It must never cross the floor or automatically cancel the node. | Recovery rest, meal, hydration, rain gear, equipment action, check-in, waiting for a teammate, or regrouping. |
| `review_only` | Must not automatically shorten, cancel, reorder, or substitute the node. It may emit a separately labelled alternative for review. | Summit attempt, reroute, retreat, stream crossing, exposed terrain, team split, bivouac, or night travel. |

Action types may supply conservative authoring defaults, but the reviewed plan
node is the decision input. An override is valid only when its reviewed source
and hash lineage are present. An unreviewed or missing policy resolves to
`review_only`; it may tighten a result but must never silently make it more
permissive.

### D-008 — Safety / Emergency owns human-driven causes; Scout owns advisory analysis

Human-driven cause evidence is accepted only through a verified, typed
Safety / Emergency trigger receipt. A Dashboard control, free-text operator
note, ordinary user-trigger record, or model inference must not claim that a
person caused a hold, rest, retreat, emergency action, or resume decision.

The non-human evidence path is automatic and evidence-bound:

- weather facts enter through reviewed weather evidence and `weather_gate`;
- IMU/PDR/GNSS facts enter through privacy-safe route-progress frames and the
  resulting `pace_gate`, `delay_gate`, and `darkness_gate` events;
- Scout may analyze these normalized facts and propose how the current and
  remaining climbing rhythm should change;
- the deterministic permission assessor and forward projector validate and
  bound the proposal before it is shown.

This output is a `Scout Pace Recommendation`, not runtime safety truth or an
authorization to continue. It may recommend a slower range, hold, shortened
discretionary events, an earlier recheck, or a review-only alternative. It must
never recommend recovering schedule by exceeding the reviewed pace envelope or
spending a protected reserve.

Safety / Emergency always has precedence. A valid safety hold, required rest,
retreat, or emergency trigger suspends any incompatible pace recommendation and
forces re-projection after the trigger sequence. Contextual Permissioning may
explain the downstream effect, but it cannot weaken, dismiss, or overwrite the
Safety / Emergency state.

### D-009 — Baseline has two authoring entry modes and one canonical result

The Baseline lens supports two starting modes:

1. `human_seeded`: the operator supplies an ideal-state itinerary in natural
   language;
2. `reference_gpx_seeded`: Scout derives a first itinerary candidate from one
   selected reference route axis and its supporting GPX corpus.

These are entry modes, not incompatible artifact types. Both must converge on
the same typed, versioned `MissionBaselineCandidate`, and either mode may later
attach the other evidence class. The original seed mode and field-level source
lineage remain visible.

The human-seeded intake must support input such as:

```text
D0：台北 - 瑞穗 C0
D1：中平林道18K - 沛源石礦岔路 - 石礦鞍部 - 森林鞍C1 (273734/2589025)
D2：C1 - 崩坡絕壁 - 三岔峰營地 - 玉里山 - 清八岔C2
D3：C2 - 單攻阿桑來戛 - 巨石獵營 (275487/2583228) - 1148鞍C3
D4：C3 - 單攻異祿閣 - 腰繞至Nas-maya - 卓溪山岔 - 卓溪山 - 卓溪山產道
```

The intake pipeline must preserve the source text and hash, segment ordered
`D0...Dn` days, extract ordered place mentions, treat `C0...Cn` as operator
aliases until resolved, and recognize terms such as `單攻` only as a branch or
out-and-back candidate requiring review. Coordinate-like text is a hint with an
unconfirmed CRS until the operator or evidence contract confirms it.

`D0` logistics and transport must remain separate from on-trail mission graph
segments. Every route-critical place in `D1...Dn` must be matched to a reviewed
checkpoint, route position, or explicitly reviewed manual waypoint before a
graph-backed baseline can be review-ready. Scout must not invent geometry for
an unresolved name.

The reference-GPX-seeded path must:

- distinguish the selected route axis from supporting reference tracks;
- validate track order, endpoint continuity, resume gaps, and route direction
  before deriving days or nodes;
- produce route, checkpoint, elevation, timing, rest/camp, and branch candidates
  with source refs and hashes;
- never equate historical timestamps with the intended current itinerary;
- generate the most complete evidence-bound daily proposal possible before
  asking the operator anything; only destination ambiguity, human intent, and
  domain-authority decisions may become narrow questions;
- preserve missing overnight, water, access, branch-return, named-point, and
  timing semantics as typed gaps or pending cross-feature review. It must not
  silently fill them or transfer computable planning work to the operator.

#### Proposal-first clarification for `reference_gpx_seeded`

`Generate from Ref. GPX` is a Scout proposal command, not an empty form
generator. When the selected workspace contains a bound timing artifact and
ordered route anchors, Scout must automatically propose:

- destination-defined `D1...Dn` intervals independent of imported
  `route_days` metadata;
- one exact primary day-end target per proposed day;
- complete, partial, or unknown timing evidence per day;
- candidate-only emergency-bivy targets and route-level retreat/reversal
  handoff items when the corresponding candidate artifacts exist;
- one deterministic, compact Permission review-requirements object.

New Ref. GPX proposals use the server-owned profile
`ref_gpx_proposal_v1`. Sparse legacy fixtures may retain their existing path,
but a newly generated rich proposal must never omit proposal-first fields and
fall back to the legacy acceptance gate.

The v1 timing contract is deliberately non-imputing:

| ETA state | Allowed numeric content | Required presentation |
| --- | --- | --- |
| `complete_derived` | deterministic sums of the assigned segments' usable p50/p75 values | label as `Segment p50/p75 sum`; never an observed whole-day quantile |
| `partial_derived` | deterministic subtotal for supported segments only | label as `Supported-segment subtotal`; state that it is not a whole-day ETA and no duration was inferred |
| `unknown` | none | label as `Whole-day ETA unknown`; list the unsupported segment IDs |

A missing p75 remains missing. It becomes one day-grouped, Permission-
acknowledgeable uncertainty; the operator is never asked to invent a replacement
duration. Primary day ends are selected only on ordered timing-segment
boundaries under a versioned deterministic partition policy. Rest/camp and MCP
labels alone do not create reviewed destinations, and retreat/bivy candidates
never become primary day ends merely because they exist.

The generic reversed-route retreat candidate remains a route-level
Safety / Emergency handoff item until it has a concrete target binding and
unambiguous day applicability. Permission can acknowledge that the handoff was
shown; it cannot approve the route reversal.

#### Daily route sketch and compact review hierarchy

Every proposal-first on-trail day must render one bounded route sketch inside
its day card. This is not a second full GIS surface and must not expose the
32-layer control set. Its sole operator question is: **what physical part of
the route does this day represent?**

Each sketch uses exactly one same-origin Rudy+TW PNG as its geographic
background. The server may compose that PNG from several already prepared
local-cache tiles, but the browser receives one image file rather than a DOM
tile grid. The fixed `760 x 248` image is clipped to the same Web Mercator
bounds used by the SVG route overlay. The endpoint accepts only a finite,
route-containing bbox, performs no remote fetch and no cache write, and returns
`candidate_only=true`, `runtime_safety_truth=false`, and
`writes_performed=false` headers. If the cached image is unavailable, the card
must say `Rudy unavailable · route only`; it must not substitute an unapproved
basemap or imply that geographic context was loaded.

The sketch must use actual prepared route geometry clipped to the day's exact
`start_anchor.route_order_m` and proposed day-end `route_order_m`. It shows:

- the day's route shape, start, proposed end, and intermediate proposal anchors;
- the exact route-kilometre range and day distance;
- endpoint coordinates from the bounded route projection;
- named MCP context inside the interval and the nearest named point before and
  after it, including their along-route distance from the day boundary.

Visible overlay labels prioritize the exact day start/end, every named place,
and every `source_kind=mcp` anchor. Unnamed intermediate checkpoints remain as
markers, with at most two generic CP labels per day sketch. Named/MCP labels use
a high-contrast halo above the dimmed Rudy image so background labels do not
erase the reviewed candidate identity.

Thus a synthetic label such as `CP 100 -> CP 116` remains the immutable anchor
identity but is presented as a physical interval, for example `50.0-58.0 km`,
with its actual line shape, endpoint coordinates, and context such as
`after Gongshan / before left-traverse cliff`. A missing named point must remain
explicit; the UI must not invent a place name.

Map data comes from a separate read-only
`missionBaselineMapContext.v1` presentation projection. It is sampled to at
most 600 ordered points, hash-binds its route-geometry and timing sources, and
reports `presentation_only=true`, `candidate_only=true`,
`runtime_safety_truth=false`, and `writes_performed=false`. Coordinates are not
copied into the immutable baseline candidate or acceptance receipt. Failure to
load this optional projection leaves kilometre and CP review available with a
clear map-unavailable state; it never widens authority or silently substitutes
synthetic geometry.

Desktop lays day cards in two columns; mobile uses one column. Each map remains
visible by default, while ETA explanation, handoff prose, segment IDs, refs,
hashes, and the complete typed payload stay collapsed until requested. The
proposal header is limited to route length, day count, timing coverage, Safety
handoff count, and one short authority sentence. On the default Baseline lens,
Baseline Authoring appears before Current Decision, remaining-plan, ledger,
Safety, and simulation content. Those secondary projections live in one
collapsed `Projection details` disclosure; Replay may open it by default.

Scout conversation edits the baseline through typed proposed patches against a
specific candidate hash. It must show additions, removals, reordered nodes,
new assumptions, and unresolved items; prose conversation must not silently
rewrite the candidate. Both modes remain `candidate_only=true` and
`runtime_safety_truth=false`. Promotion from a conversation-refined candidate
to a reviewed baseline follows D-010 and the resolved OD-006 contract.

### D-010 — Baseline promotion is explicit, versioned, and human accepted

Scout conversation may make a baseline `review_ready`; it must never make the
baseline reviewed by itself. The authoring lifecycle is:

```text
source input
  -> preview
  -> generated draft
  -> explicitly saved candidate version
  -> proposed Scout patch
  -> explicitly saved next candidate version
  -> deterministic review-ready gate
  -> explicit human Accept Reviewed Baseline
```

Only these actions may write workspace state:

| Action | Write contract |
| --- | --- |
| `Save Candidate Version` | Creates a new immutable candidate version and persists the exact source/conversation refs and hashes used to generate it. |
| `Save Patch As New Version` | Requires the base candidate ref/hash and creates a new candidate version; it never edits the base version. |
| `Accept Reviewed Baseline` | Requires the exact review-ready candidate hash, explicit reviewer confirmation, and all promotion gates; appends a review decision and creates a new immutable reviewed-baseline artifact. |

Typing, source selection, `Preview Source`, `Generate Draft`, ordinary Scout
conversation, proposed patches, validation, comparison, map inspection, Replay,
Live Observer, and candidate simulation remain no-write operations.

`Accept Reviewed Baseline` requires all of the following:

- route-critical `D1...Dn` names and coordinate hints are resolved;
- the selected route axis passes order, endpoint-continuity, resume-gap, and
  direction admission;
- overnight endpoints, branch-return semantics, and day boundaries are
  reviewed;
- graph compilation succeeds without the unreviewed-candidate bypass;
- deterministic validation reports no route-critical blocker;
- the request binds the exact candidate ref/hash and includes an explicit
  confirmation plus reviewer identity/audit metadata.

For `ref_gpx_proposal_v1`, candidate save and acceptance additionally recompute
the same `baseline_permission_review.v1` requirements:

```text
required_reviewed_day_ids
required_acknowledgment_uncertainty_ids
pending_safety_handoff_item_ids
safety_handoff_required
```

The compact review request must match the exact day and uncertainty sets and the
exact handoff boolean. Omitted, duplicate, extra, unknown, stale, or cross-
candidate IDs fail closed. The review receipt records
`review_scope=permission_day_end_only`, enumerates every day-to-target
proposal/ref/hash binding, and records
`safety_handoff_scope=visibility_and_cross_feature_handoff_only`. These fields
must never be interpreted as retreat, bivy, departure, or runtime-safety
approval.

Acceptance appends to `reviews/review_decision_log.json`, writes a new immutable
reviewed artifact, and updates the selected project ref. It must not rewrite an
older candidate/reviewed artifact, call a model, compile a Final MissionGraph,
grant Departure Approval, update an active runtime session, call `/safety/*`,
or create runtime safety truth. Dependent permission/ETA artifacts whose bound
baseline hash no longer matches become visibly stale and require an explicit
rebuild or review before use.

Projection staleness must not disable Baseline Authoring. Preview, proposal
generation, candidate save/patch, and reviewed-baseline acceptance operate on
their own source and candidate hashes and remain available while the older
forward projection is fail-closed. The blocked Dashboard therefore keeps the
authoring workbench visible and labels the old Current Decision as unavailable;
it must not make the operator repair files outside the page.

The explicit projection rebuild is a second, hash-bound action after baseline
acceptance. It requires the exact currently selected
`reviewed_mission_baseline_sha256`, an idempotency key, and explicit
confirmation. The deterministic rebuild:

- verifies the immutable reviewed baseline, candidate, review receipt, exact
  reviewed day set, and every proposal-first day-end binding;
- rewrites only the derived planned-ETA binding, fail-closed
  `contextual_permission_rules.json`, bounded workbench seed, resolved-staleness
  marker, project refs, and an append-only rebuild receipt;
- leaves every adjustment policy `review_only` and unreviewed until a separate
  Permission policy review exists;
- creates a new candidate projection session identity but does not rebind or
  update an active runtime session;
- keeps departure approval, Safety / Emergency approval, runtime safety truth,
  outbound effects, and hardware control false.

A legacy reviewed baseline without exact proposal-first day-end bindings cannot
be rebuilt into a usable projection. It fails with an actionable instruction to
generate and accept a new Ref. GPX proposal; the server must not invent targets
from the old sparse artifact.

### D-011 — Night alternatives require Safety / Emergency human review

Contextual Permissioning may determine only whether a pre-reviewed night
alternative is `eligible_for_human_review`. It must never approve or authorize
night travel. The human review action belongs exclusively to a dedicated
**Emergency Human Review** interface under the existing Safety / Emergency
surface.

Night-alternative eligibility is a conjunctive gate. The only projection states
are:

```text
not_assessed
ineligible
eligible_for_human_review
```

`eligible_for_human_review` requires every gate below to pass:

| Gate | Required evidence |
| --- | --- |
| Reviewed alternative | Exact from/to route, maximum night duration, stop objective, retreat and emergency-bivy candidates, with reviewed refs/hashes. |
| Segment policy | Explicit reviewed `requires_daylight=false`; absence or a default value is insufficient. |
| Terrain / route | No unresolved geometry, exposed terrain, technical climbing, stream crossing, unstable/blocked route, off-route ambiguity, or unresolved GNSS/route correlation. |
| Lighting / power | Primary lighting for every member plus independent backup; verified runtime covers projected night duration plus `max(60 minutes, 50% of projected duration)`. |
| Navigation / resources | Offline map, loaded reviewed route, backup navigation, device power, weather protection, emergency warmth, water, and food cover the reviewed alternative and reserve. |
| Team | Every member accounted for; slowest-member pace is available; no incompatible injury, cold stress, pace collapse, separation, or Safety / Emergency hold. |
| Weather / threat | Fresh evidence, no incompatible warning, and reviewed visibility, wind, rain, and environment-threat thresholds pass. |
| Communication | Communication is available, or a reviewed blackout/check-in/overdue escalation plan covers the exact segment. |
| Runtime lineage | Project, baseline, mission graph, session, alternative, gate, and evidence hashes match the current sequence with no conflict or stale source. |

Any missing, false, stale, or conflicting gate makes the result `ineligible`.
Schedule delay may trigger this assessment but must never make a night
alternative more eligible.

The current `darkness_gate` has no positive night-travel authorization path and
must not be suppressed by this workbench. Until a reviewed runtime integration
exists, even a fully passing matrix remains a review candidate. Emergency
movement at night is a separate Safety / Emergency decision and must not be
mislabelled as an approved Contextual Permission alternative.

The dedicated Safety / Emergency review surface consumes a deterministic,
hash-bound `NightAlternativeReviewPacket`. The Permission page may show status
and a deep link to that surface, but it must contain no Approve control.

The reviewer may choose only:

```text
approve_for_runtime_consideration
reject_night_travel
select_hold_or_bivy
escalate_emergency
```

Human review cannot waive an `ineligible` hard gate. The first decision is
available only while the packet remains `eligible_for_human_review`; the other
decisions are conservative Safety / Emergency outcomes.

Every decision produces an append-only, idempotent
`SafetyEmergencyReviewReceipt` bound to the packet, reviewer, decision, source
hashes, and reviewed sequence. In the prototype/shadow slice the receipt must
declare `runtime_authorization_performed=false`. A future deterministic runtime
authority may consume the receipt only after revalidating freshness and hashes;
the UI never mutates Phase 1 or calls `/safety/*` directly.

The receipt is the only human-driven causal evidence returned to Contextual
Permissioning, consistent with D-008. A new incompatible Safety / Emergency
trigger, worsened gate outside the reviewed daily envelope, route/alternative
scope change, mission-day transition, or session/baseline mismatch invalidates
the human review. An ordinary volatile-evidence hash change or expired
freshness window invalidates the current eligibility packet and requires an
automatic rebuild; it requires new human review only when the rebuilt result no
longer fits the current day's reviewed envelope.

### D-012 — Asymmetric responsive contract: compact Permission, complete Emergency review

The mobile experience is intentionally asymmetric:

- Contextual Permissioning is a desktop-first authoring and analysis workbench.
  Its mobile surface is a complete operational **inspection and handoff** path,
  not a compressed baseline editor or candidate-simulation studio.
- Safety / Emergency is field-oriented and mobile-first. Its mobile surface
  retains the complete `night_alternative` human-review workflow, including all
  four bounded decisions, while the desktop view mirrors the same server-side
  packet, decision, and receipt.

Compact must not mean incomplete, ambiguous, or small. On mobile, every current
decision, hard blocker, stale/invalid status, protected reserve, remaining-plan
change, review status, and required next action remains reachable within at
most two deliberate taps from the relevant landing view. Secondary lineage and
raw evidence may move behind tabs or a drawer, but safety-significant state may
not be hidden only in a tooltip, hover state, color, or horizontally clipped
table.

The established `760px` breakpoint remains the mobile-workbench boundary. The
minimum mobile presentation contract is:

| Element | Requirement |
| --- | --- |
| Body and control text | At least `16px`, with at least `1.45` line height. |
| Primary decision/status | At least `22px`; short enough to scan without truncation. |
| Primary action | At least `56px` high and full-width where practical. |
| Secondary action / icon control | At least `48px × 48px`; icon-only controls require a visible or assistive label. |
| Action separation | At least `8px`; incompatible actions must not share an easy-to-mistap edge. |
| Contrast and status | Meet shared Dashboard accessible contrast; always pair color with icon and explicit text. |
| Layout | One column, no page-level horizontal scroll, respect device safe-area insets, and keep the active decision/action region visible above browser chrome where practical. |
| Loading / disabled state | Preserve the last labelled state, explain why an action is unavailable, and never replace the decision with an indefinite spinner. |

The target viewport range for focused acceptance is `360px–760px`, with a
required `390px` portrait browser proof because that width already belongs to
the Dashboard mobile verification surface. Text enlargement to `200%` must not
hide the decision label, enabled/disabled state, reason, or action consequence.

### D-013 — Every Emergency review decision uses tap-then-confirm

All four Safety / Emergency human-review decisions use the same two-step mobile
interaction:

```text
Tap decision action
  -> inspect fixed bottom confirmation sheet (no write)
  -> tap explicit Confirm action
  -> server revalidates packet and records or rejects the decision
```

The first tap only selects the proposed decision and opens the confirmation
sheet. It must not write a receipt, change Permission state, start runtime
behavior, or invoke an outbound effect. The second tap is an explicit command
bound to the selected decision, current packet id/hash, reviewed sequence, and
idempotency key.

Long-press, swipe-to-confirm, timed holding, and mandatory typed justification
are prohibited. They are slower and less dependable with gloves, cold hands,
injury, tremor, or assistive technology. No decision may be preselected, and a
tap outside the sheet must not count as confirmation.

The confirmation sheet must show, without scrolling past the Confirm action:

- the exact verb-first decision label and icon;
- the reviewed from/to alternative and current packet-validity state;
- one short consequence statement and the immediate next step;
- expiry or freshness warning when applicable;
- the explicit boundary that review is not night-travel authorization and does
  not itself send an alert or mutate Phase 1.

`Escalate emergency` records only the reviewed escalation decision and then
opens the existing Emergency Call Out flow. Any message, phone-call handoff, or
future transport authorization remains a separate, explicit action with its
own delivery state. It must never inherit confirmation from the review sheet.

After Confirm, the selected action is disabled against duplicate submission
while the current labelled state remains visible. The server revalidates before
append. Success replaces the sheet with receipt id/status and one clear next
step. A stale, expired, ineligible, mismatched, or already-decided rejection
must say `Decision not recorded`, identify the blocker, and return to a safe
review state without optimistic approval.

### D-014 — Offline review records conservative intent, never approval

Safety / Emergency must remain useful when connectivity is degraded, but the
absence of server-side revalidation narrows what the interface may claim or do.
The mobile review has these explicit connectivity states:

```text
online_revalidated
degraded_cached
offline_cached
no_cached_packet
reconnecting
sync_conflict
```

In `degraded_cached` or `offline_cached`, the last cached packet remains
inspectable with a persistent warning containing its relative age and last
validated state. `approve_for_runtime_consideration` stays visible but disabled
with `Online revalidation required`. The operator may still select:

```text
reject_night_travel
select_hold_or_bivy
escalate_emergency
```

Those actions retain the D-013 two-step confirmation, but Confirm appends only
an encrypted/device-local, append-only `OfflineEmergencyReviewIntent`. It is
not a `SafetyEmergencyReviewReceipt`, not a Safety / Emergency trigger receipt,
and not human-driven causal evidence accepted by Contextual Permissioning. The
UI labels it `Pending sync · not yet recorded by Safety / Emergency` and must
not use verified-green or approved language.

The local intent binds a generated intent/idempotency id, decision, packet
id/hash, project/session ids, reviewed sequence, baseline/mission-graph hashes,
relative cache age, device-instance ref, supersedes ref when present, and all
no-authority boundary flags. It stores no raw GPX, raw health payload, exact
coordinate, credential, or outbound destination. Changing an unsynced decision
appends a superseding intent rather than deleting history.

Saving an offline `escalate_emergency` intent immediately opens the separate
Emergency Call Out flow; opening it does not wait for sync and still grants no
message, call, transport, or delivery authorization.

When there is no cached packet, night-alternative decisions are unavailable and
the view says `No review packet available offline`. The general Emergency Call
Out entry remains available as a separate workflow, without claiming message,
call, or transport delivery.

After connectivity returns, the client submits the latest unsuperseded intent
with its idempotency key. The server rebuilds the current packet and produces
one of three deterministic results:

| Sync result | Required behavior |
| --- | --- |
| `receipt_appended` | All project/session/sequence/hash and decision preconditions still match; append a canonical receipt with `origin=offline_intent`. |
| `already_recorded` | Resolve to the existing receipt for the same idempotency key; do not append a duplicate. |
| `rejected_sync_audit` | Preserve an append-only audit result with the stale, expired, invalidated, mismatched, superseded, or conflict reason; create no review receipt. |

Sync never retroactively enables or submits
`approve_for_runtime_consideration`, never authorizes runtime behavior, and
never starts an outbound action. Permission may show a same-device
`Offline intent pending` hint, but it must not recompute human-driven forward
constraints until a canonical Safety / Emergency receipt is available.

### D-015 — Eligibility packet freshness follows the earliest required evidence

Night-alternative review has no universal fixed timeout. Every deterministic
adapter or reviewed policy that contributes a required eligibility fact must
provide `valid_until` and, when useful, `refresh_warning_at`. The packet expiry
is calculated as:

```text
packet.expires_at = min(
  required_evidence[*].valid_until,
  required_gate_policy[*].valid_until,
  reviewed_alternative.valid_until,
  applicable_segment_or_session_deadline
)
```

Only inputs actually required by the conjunctive eligibility decision enter the
minimum. Optional evidence cannot silently shorten or extend eligibility. If a
required input lacks a deterministic `valid_until`, the associated gate is
`freshness_unknown`, the packet is `ineligible`, and no default duration may be
invented by the model or UI.

The packet exposes:

```text
server_now
built_at
expires_at
freshness_state: fresh | refresh_due | expired | invalidated
expiry_driver: { gate_id, evidence_ref, valid_until, reason }
freshness_inputs[]: { gate_id, evidence_ref, valid_until, warning_at }
invalidated_by[]
```

`refresh_due` begins at the earliest declared `refresh_warning_at`; it is a
request to rebuild evidence, not an extension. At `server_now >= expires_at`,
the packet becomes `expired` and approval is unavailable until it is rebuilt.
A human review never extends evidence validity. Under D-016, the daily human
receipt has a separate mission-day scope; it may remain review-valid while the
current eligibility packet is `expired`, but it cannot support current runtime
consideration until fresh evidence revalidates inside the reviewed envelope.

The following invalidate immediately, independent of the countdown:

- a new incompatible Safety / Emergency trigger;
- route progress or active from/to alternative change;
- event-sequence, project, session, baseline, mission-graph, alternative, gate,
  or required-evidence hash change;
- a required gate becoming false, unknown, conflicting, or more severe;
- explicit packet replacement, cancellation, or supersession.

Server time and the current server-side rebuild are authoritative. Mobile and
desktop use `server_now` only to render a relative countdown; device time must
never authorize a decision. If current server time or the expiry driver cannot
be established, the UI shows `Freshness unknown`, disables approval, and
requires refresh.

Confirm always performs one final rebuild/revalidation. If the packet expires
or invalidates while the sheet is open, the decision is not recorded. The UI
closes or updates the stale sheet, identifies the expiry driver or invalidator,
and requires the operator to inspect a newly built packet rather than carrying
the previous selection forward.

### D-016 — Human review is organized and renewed by mission day

The human-review unit is one baseline mission day (`D1`, `D2`, ...), not one
entire expedition and not one receipt that remains valid for every later day.
Safety / Emergency creates a `DailyEmergencyReviewSession` for the current
`mission_day_instance_id`. The session assembles every known night-alternative
candidate for that day as an exact, separately traceable
`NightAlternativeReviewPacket`.

The daily session binds:

```text
scope_kind=mission_day
mission_day_id
mission_day_instance_id
mission_day_plan_ref/hash
scope_start_ref
scope_end_ref
planned_day_end_target_ref/hash
effective_day_end_target_ref
day_end_state
local_date
timezone
review_generation
alternative_packet_ids[]
```

Each alternative still preserves its exact from/to geometry, direction,
maximum night duration, stop objective, retreat/bivy choices, gate matrix, and
hashes. The reviewer may disposition the known alternatives during one daily
review session; Safety / Emergency appends an individual decision receipt for
each reviewed alternative and projects one daily summary:

```text
pending_day_start
not_started
in_review
partially_reviewed
reviewed
reviewed_evidence_refresh_required
re_review_required
day_closed
```

An `approve_for_runtime_consideration` receipt is no longer single-use by
attempt. Within the same mission-day instance it may satisfy the human-review
prerequisite for the same exact reviewed alternative after each fresh
deterministic revalidation. It never covers another mission day, an unlisted
alternative, or a changed route/policy envelope, and it never becomes runtime
authorization.

When the current mission day closes, every prior-day receipt becomes historical
and read-only. The next baseline day remains `pending_day_start` and requires a
new daily human review plus the D-018 start boundary before it becomes active.
Future days may show pre-trip candidates but cannot display a current reviewed
state.

Daily scope is a maximum, not a guarantee that one morning review survives all
events. A new alternative, changed geometry or direction, reviewed-policy
change, incompatible Safety / Emergency trigger, team/safety condition outside
the reviewed envelope, or project/session/baseline/mission-graph mismatch moves
the current day to `re_review_required`. Re-review creates a new
`review_generation` and append-only receipts that supersede rather than rewrite
the earlier daily review.

Routine weather, IMU/PDR/GNSS, or other automatic evidence refresh does not by
itself erase the daily human receipt. The server first rebuilds the eligibility
packet. If the new facts remain inside the exact reviewed alternative and gate
envelope, the daily review remains current; if they make the alternative
ineligible, use is blocked, and if they cross a reviewed envelope boundary the
day moves to `re_review_required`.

### D-017 — Mission-day boundaries are destination-driven, with emergency-bivy substitution

A mission day never closes because of midnight, elapsed hours, sleep/wake time,
or a calendar-date change. Every reviewed baseline day must define one exact
`planned_day_end_target_ref`, such as a reviewed campsite, junction, checkpoint,
or other named route target with map identity and geometry. Free text without a
resolved target is insufficient for daily review readiness.

The normal close condition is a deterministic, append-only
`DayEndArrivalReceipt` for that planned target. Until arrival is confirmed, the
current mission day remains open even if the team rests, sleeps, or crosses
00:00. Time, ETA, daylight, pace, weather, and movement evidence may determine
whether the target is still safely reachable, but none of them independently
changes the mission-day identity.

The day-end state vocabulary is:

```text
en_route_to_planned_day_end
planned_day_end_arrival_unconfirmed
planned_day_end_reached
day_end_at_risk
day_end_unreachable
emergency_bivy_review_required
emergency_bivy_selected
emergency_bivy_establishment_unconfirmed
emergency_bivy_established
day_closed_planned
day_closed_contingency
```

`day_end_unreachable` may originate from either:

- a typed human `cannot_reach_planned_day_end` trigger receipt emitted only by
  Safety / Emergency; or
- deterministic feasibility facts from route progress, pace/delay, darkness,
  weather, terrain/environment threat, protected reserves, and data quality.

Scout may explain those facts and recommend stopping, but its output remains a
candidate recommendation. `day_end_unreachable` must open and foreground the
Safety / Emergency **Emergency Bivy Review** flow; it must not silently choose a
camp, mutate Phase 1, authorize field behavior, or send an alert.

Emergency Bivy Review presents exact reviewed bivy/hold candidates when
available, plus current-safe-hold and escalation paths when no candidate can be
validated. Selecting `select_hold_or_bivy` uses the existing D-013 two-step
confirmation and produces a Safety / Emergency receipt bound to the selected
target, current day, session, sequence, evidence, and uncertainty.

Selecting a bivy target does not close the day. Closure requires a separate
`EmergencyBivyEstablishedReceipt` confirming that the reviewed site was
actually reached/established. At that point the system creates an immutable
`EffectiveDayEndSubstitution`:

```text
baseline_day_end_target_ref = unchanged planned target
effective_day_end_target_ref = confirmed emergency bivy target
baseline_day_end_reached = false
day_completion = contingency_closed
remaining_route_to_baseline_end = carried forward
```

The substitution never rewrites the baseline itinerary. It closes the current
mission-day instance as `day_closed_contingency`, marks its prior daily receipts
historical, carries the unfinished route and time/risk consequences into the
next Forward Constraint Projection, and requires a new daily Safety / Emergency
review before subsequent night alternatives are considered.

If neither planned-target arrival nor emergency-bivy establishment is
confirmed, the day remains open and no next-day review session may be presented
as current. `local_date` and timezone remain display/audit metadata only.

### D-018 — Shelter Hold may span calendar days without consuming mission days

Closing one mission day and starting the next are separate events. After
`day_closed_planned` or `day_closed_contingency`, the system may remain in a
calendar-neutral `ShelterHoldInterval` at the confirmed mountain hut, campsite,
emergency bivy, or other reviewed safe-hold target. The next baseline day stays
`pending_day_start`; midnight and the number of nights spent there do not start,
advance, or consume a mission day.

This supports cases such as sheltering for three calendar days during extreme
weather and departing only after conditions improve. The hold state is:

```text
not_required
hold_review_required
active
evidence_refresh_required
departure_review_candidate
ready_to_resume
closed
escalated
```

A `ShelterHoldInterval` binds:

```text
hold_id
location_target_ref/hash
location_kind: planned_day_end | emergency_bivy | reviewed_safe_shelter
closed_mission_day_instance_id
pending_next_mission_day_id
cause_refs[]
safety_emergency_trigger_receipt_refs[]
weather_and_threat_evidence_refs[]
team_and_resource_state_refs[]
started_at
last_reviewed_at
calendar_elapsed_duration
status
```

`started_at`, `last_reviewed_at`, and calendar elapsed duration are audit and
resource-planning facts only. They never trigger mission-day rollover or forced
departure.

Extreme-weather, route-threat, or other automatic facts may produce a
`hold_review_required` candidate and Scout explanation. A human-reported reason
is accepted only through a Safety / Emergency trigger receipt. Starting or
continuing the actual shelter hold is recorded through Safety / Emergency; the
Dashboard does not infer it merely from stationary IMU/GNSS data.

While a hold is active:

- the closed day's baseline and effective end remain immutable;
- the next day remains pending and its candidates are preview-only;
- weather/threat, shelter suitability, team state, water/food/fuel/power/warmth,
  communication, and exit-route evidence continue to refresh;
- hold duration and resource consumption enter the next Forward Constraint
  Projection, but protected safety reserves are not automatically spent to
  preserve the old itinerary;
- no Scout recommendation may automatically resume movement, start a new day,
  or claim that the route is safe.

Improved weather may move the hold to `departure_review_candidate`, but it does
not close the hold. A separate, explicit Safety / Emergency departure review
must create a `MissionDayStartReceipt` bound to fresh weather/threat evidence,
team/resources, the departure target, next day-plan hash, session, sequence,
and reviewer. Only that receipt closes the hold, activates the pending mission
day, and opens its daily review as current. OD-014 defines the resolved
departure checklist and recommendation boundary.

If conditions worsen, supplies become insufficient, shelter becomes unsafe, or
the operator requests help, the same view offers continued hold, relocation/
emergency-bivy review, retreat review, and Emergency Call Out. None implies
verified external delivery without the separate transport receipt.

### OD-014 — Departure review uses a compact leader checklist plus Scout suggestions

Departure from Shelter Hold is an AND gate presented as a concise
`LeaderDepartureChecklist`. The first layer has exactly six rows; detailed
evidence remains expandable so the leader can review quickly without losing
traceability.

| Checklist row | Scout / deterministic inputs | Required leader input |
| --- | --- | --- |
| Weather & threats | Authorized weather observations/forecast, warnings, visibility/wind/rain, terrain/environment-threat gates, freshness and uncertainty. | Report a conflicting field observation when present; no re-entry of fetched values. |
| Route & navigation | Reviewed next segment, route/closure evidence, progress correlation, GNSS/PDR quality, offline map and device navigation readiness. | Confirm intended route/exit direction and backup navigation are understood/available. |
| Team | Available group-progress and physiologic-safety summaries without raw health data. | Confirm everyone is accounted for, warm enough, able to travel, and has no incompatible injury/separation/pace concern. |
| Equipment & power | Available battery, lighting, device, communication, and equipment telemetry with gaps shown. | Confirm physical lighting, backup power/navigation, weather protection, warmth, and critical gear check. |
| Supplies & shelter fallback | Projected water/food/fuel/power use, protected reserves, next safe shelter/retreat/bivy refs. | Confirm actual supplies and that a fallback shelter/retreat plan remains usable. |
| Communication & next-day plan | Connectivity/check-in evidence, pending day-plan hash, route targets, source freshness. | Confirm blackout/check-in/escalation plan and that the exact next-day plan is understood. |

Each row projects:

```text
row_id
source_mode: scout_auto | leader_attestation | hybrid
gate_state: pass | blocked | unknown | leader_check_required
one_line_summary
blocking_reason
freshness
fact_refs/hashes[]
leader_attestation_id
expanded_evidence_ref
```

Automatically obtainable facts are gathered through authorized weather,
threat, route-progress, device, and workspace adapters and normalized before
display. The leader does not copy or manually type those values. Missing,
stale, conflicting, or failed automatic evidence becomes `unknown` or
`blocked`; it never receives an optimistic default.

The recommendation pipeline is explicitly separated:

```text
authorized automatic sources
  -> normalized departure facts
  -> deterministic checklist gates
  -> evidence-bound Scout explanation/recommendation
```

Scout recommendation vocabulary is bounded to:

```text
continue_shelter_hold
refresh_evidence
departure_review_ready
relocate_or_escalate_review
```

Scout may say, for example, that updated weather supports opening departure
review. It must expose source/freshness/gaps and may not say `safe to go`, mark a
leader attestation, override a deterministic block, close the hold, or create a
MissionDayStartReceipt.

The final gate passes only when all automatic/hybrid rows are current and
deterministically `pass`, all required leader attestations are explicitly
checked, no incompatible Safety / Emergency trigger is active, the pending
day-plan/review hashes match, and the leader completes the D-013 two-step final
confirmation. A checkbox cannot waive `blocked` or `unknown` evidence.

### OD-015 — Leader field-conflict reports suspend Scout advice and fail closed

Every `scout_auto` and `hybrid` departure-checklist row provides a prominent
`Field condition differs` action. It is not a manual override. It is a fast
Safety / Emergency path for reporting that the leader's direct observation
conflicts with an automatic fact or the Scout suggestion derived from it.

The interaction follows the common deliberate two-step pattern without
requiring prose:

```text
tap Field condition differs (no write)
  -> optional short note + one consequence-labelled category action
  -> server revalidation
  -> append conflict receipt or report Conflict not recorded
```

The four fixed categories are:

```text
actual_condition_worse       # actual conditions are worse
source_stale_or_wrong        # source appears stale or wrong
location_or_route_mismatch   # current location/route does not match
device_reading_mismatch      # physical observation conflicts with device data
```

The second tap is the submit action itself, for example `Report actual
conditions are worse · suspend departure`; there is no additional generic
Confirm button. A short note is optional and bounded. Free text is never
required to make the conservative report.

Submission appends an idempotent, immutable
`SafetyEmergencyFieldConflictReceipt`. This receipt is a typed Safety /
Emergency trigger receipt under D-008, not a generic Dashboard note, and binds:

```text
conflict_id
idempotency_key
hold_id
pending_mission_day_id
departure_checklist_ref/hash
row_id
category
affected_fact_refs/hashes[]
optional_bounded_note
reporter_identity
reviewed_event_sequence
created_at
source
privacy
boundary
```

The receipt stores bounded refs and summaries only: no raw health payload, raw
GPX, exact coordinate history, credentials, or unnecessary private timestamp
history. Its immediate deterministic effects are:

```text
conflict_state = open
row gate = blocked               # actual worse or route/location mismatch
row gate = unknown               # stale/wrong source or device mismatch
can_confirm_departure = false
Scout suggestion = suspended
```

Independent hard blockers remain blocked regardless of category. While the
conflict is open, Scout may acknowledge it and recommend only
`continue_shelter_hold`, `refresh_evidence`, or
`relocate_or_escalate_review`; it cannot dispute the observation, restore
`departure_review_ready`, or convert the row to pass.

Later automatic refresh may display new evidence but cannot silently clear the
leader's report. Resolution requires a separate append-only
`SafetyEmergencyFieldConflictResolutionReceipt`, fresh affected evidence,
deterministic gate rebuild, and explicit Safety / Emergency leader review. Its
state is one of:

```text
open | revalidation_required | resolved_consistent | superseded | escalated
```

A resolution cannot set a row to pass by human assertion alone. If the report
said actual conditions were worse, apparently improved automatic evidence
still requires the leader to confirm that the direct field conflict no longer
exists. Earlier conflict and resolution receipts remain visible in the audit
trail.

Offline reporting creates an encrypted, device-local pending conflict intent
and immediately blocks departure on that device. Reconnect may append the
canonical receipt or a rejected sync audit after server revalidation; neither
path may enable departure automatically.

### OD-016 — Individual action sensing and target dwell close the day without a leader roll call

Scout must keep two facts separate:

```text
individual_action_state != mission_day_completion
mission_day_closed != every_person_sleeping_or_safe
```

Resting, lying down, sleeping, and resuming movement are individual activity
records. The leader is not asked to confirm that every person has stopped,
lain down, or fallen asleep. Each participating phone/wearable performs local
sensor fusion from authorized IMU/posture, PDR/cadence, and GNSS movement
signals and emits only a privacy-bounded semantic transition:

```text
route_travel
stationary_candidate
resting
lying
sleeping
resumed_movement
unknown
```

The corresponding append-only `IndividualActionTransitionReceipt` binds a
pseudonymous participant/device ref, `activity_episode_id`, prior/new state,
action kind, `started | ended | resumed | corrected` transition, confidence,
freshness, and bounded evidence hashes. A state change closes the prior personal
episode and opens the next one; for example, `route_travel -> resting` records
travel ended and rest started, while `resting -> resumed_movement` records rest
ended. Raw IMU, raw health signals, and exact private location history remain
on the device or in their authorized evidence store. `sleeping` is an activity
inference, not a medical claim. The individual may append a self-correction to
their own record; the leader does not edit it.

Mission-day closure is target-level bookkeeping and has two completion modes:

1. **Immediate on-site confirmation.** An authorized on-site participant may
   explicitly choose `Arrived · complete D_n` or, for an already reviewed and
   selected emergency bivy, `Camp established · complete D_n`. This confirms
   only the exact target/site state, not every person's posture, sleep, health,
   or safety.
2. **Automatic confirmed-arrival dwell.** A deterministic observation service
   confirms entry into the reviewed target's `arrival_zone_ref/hash` from a
   fresh, sufficiently accurate GNSS fix plus compatible route progress, then
   starts a monotonic dwell countdown. The default is `600` seconds; a reviewed
   pre-trip target policy may require a longer interval. When the interval
   completes without positive evidence of leaving the zone, continuing route
   travel, target mismatch, or separation, the service appends the day-end
   receipt automatically.

The individual activity receipts support the dwell reducer: resting, lying, or
sleeping strengthens the conclusion that route travel ended; ordinary movement
inside camp does not reset it; resumed route travel or movement out of the
reviewed zone cancels the candidate. Missing personal activity data remains
`unknown` and visible but does not force the leader to perform a per-person
sleep roll call. It also never creates a claim that the unknown person is safe.
A known unexpected separation inside the current movement group, or a continued
route-travel state for that group, blocks automatic close and opens the existing
Safety / Emergency exception path. A member assigned to another reviewed group
is not a separation contradiction.

The resulting receipt declares its confirmation mode:

```text
manual_on_site
automatic_gnss_dwell
```

For the planned target it is a `DayEndArrivalReceipt`; for an already selected
reviewed bivy it is an `EmergencyBivyEstablishedReceipt`. The automatic mode
proves target occupation and route-travel termination only; it does not prove
tent quality, shelter safety, sleep, recovery, or fitness to depart.

The mobile UI shows the target, GNSS confidence, and a visible
`Arrival confirmed · completing D_n in mm:ss` countdown with `Complete now`
and `Wrong target / still travelling` actions. Poor positioning never leaves
the workflow without an exit: the on-site confirmation remains available with
the exact selected target and uncertainty shown. A short sensor outage may
pause automatic completion, but it does not erase the confirmed-arrival event
or require the leader to attest individual behavior.

Closing the day immediately makes the prior day historical and opens or
continues the target's `ShelterHoldInterval`; the next mission day remains
`pending_day_start`. Neither manual nor automatic close starts the next day,
authorizes movement, mutates Phase 1, or performs an outbound action. An
incorrect automatic close is corrected through a separate append-only Safety /
Emergency correction receipt rather than rewriting history.

### OD-017 — Intentional movement groups own independent day and start state

An expedition may intentionally split into front/rear, summit/base, scouting,
evacuation, or other independent movement groups. Scout must not force those
groups into one team-wide arrival, Shelter Hold, or next-day-start state.

A movement group is explicit and versioned:

```text
movement_group_id
display_name
formation_kind: baseline_reviewed | field_explicit
membership_revision
participant_refs_hash
coordinator_ref
current_mission_day_id/instance
planned_or_effective_target_ref/hash
shared_dependency_refs/hashes[]
formation_receipt_ref/hash
status
```

`coordinator_ref` identifies the group's coordination contact; it does not make
that person responsible for recording every member's activity. Individual
activity receipts from OD-016 bind the membership revision active at their event
sequence and continue to belong to the individual.

Formation requires a reviewed pre-trip grouping or an explicit append-only
Safety / Emergency `MovementGroupFormationReceipt`. Distance between devices,
different pace, a stale sensor, or a model inference cannot silently create a
new movement group. Physical separation without a matching formation receipt is
`unexpected_separation` and enters the Safety / Emergency exception path.

Each movement group independently owns:

- target arrival and the 600-second arrival-dwell candidate;
- `DayEndArrivalReceipt` or `EmergencyBivyEstablishedReceipt`;
- effective day-end substitution and unfinished-route projection;
- `ShelterHoldInterval`;
- six-row departure review and `MissionDayStartReceipt`;
- current mission-day label, daily Emergency Review Session, and Scout advice.

Therefore one group may be `D3 active` while another remains `D2 · Shelter Hold`
without either record being rewritten or treated as an error. A receipt from one
group never closes, reviews, or starts another group. Only an explicit reviewed
shared dependency such as `must_regroup_before_departure`, or a Safety /
Emergency constraint scoped to multiple groups, may block them together.

The expedition-level state is a read-only roll-up:

```text
not_started
in_progress
partially_closed
all_groups_closed
unexpected_separation
cross_group_review_required
```

`partially_closed` is a normal state, not a failure. It shows each group's
current day, target, arrival/dwell, hold, next action, data freshness, and
contact state without collapsing them into a single false team status. Scout
recommendations are group-scoped; the expedition summary may explain
cross-group consequences but cannot authorize either group.

Membership changes append a new revision. Planned reunion creates a separate
`MovementGroupMergeReceipt`; it does not merge or rewrite prior individual,
day-close, hold, or start receipts. If the groups return with different active
day/route contexts, Safety / Emergency performs a reconciliation review before
creating one new merged context.

The mobile view defaults to `My movement group` with its immediate decision,
then shows an `All groups` summary one tap away. Critical unexpected-separation
or cross-group blockers remain visible from either view. Every action repeats
the affected group name so an operator cannot complete or start the wrong
group.

### OD-018 — Communication is governed by reviewed windows, not continuous heartbeats

Mountain groups are not expected to remain continuously online. Every movement
group instead carries a reviewed, route-scoped `CommunicationWindowPolicy` that
defines where blackout is expected, the next place/event where communication
should become possible, and the latest acceptable check-in window.

```text
communication_policy_id/hash
movement_group_id
membership_revision
route_scope_ref/hash
expected_blackout_segment_refs/hashes[]
next_check_in_target_ref/hash
window_open_condition
baseline_latest_check_in
effective_latest_check_in
allowed_forward_adjustment_refs/hashes[]
contact_loss_review_policy_ref/hash
verified_check_in_receipt_ref/hash
```

This is not a fixed heartbeat interval. Local network telemetry may observe
whether a bearer is available, but Scout does not require recurring outbound
pings and lack of signal inside a reviewed blackout scope is not itself an
alarm.

The group contact state is:

```text
contact_available
expected_blackout
check_in_window_open
check_in_due
contact_overdue
contact_loss_review_required
escalation_candidate
contact_restored
unknown
```

`expected_blackout` requires the current group route/progress to remain inside
the policy's reviewed blackout scope. The first layer always shows the next
check-in target/event and effective latest window. A route deviation,
unexpected silence where contact should be available, stale group progress, or
policy/hash mismatch cannot inherit the reassuring blackout label.

The baseline and effective latest check-in remain separate. A known append-only
Shelter Hold, emergency-bivy, route-change, or other reviewed forward event may
derive a new effective window only when its adjustment policy explicitly allows
it. Scout and the client cannot extend the deadline ad hoc, and a later revision
cannot retroactively relabel an already overdue interval as expected blackout.

At the effective latest window, absence of a verified check-in deterministically
creates `contact_overdue`. This is an automatic fact, not a human cause and not
an emergency declaration. It opens Safety / Emergency contact-loss review and
permits Scout to explain the evidence and recommend only:

```text
continue_expected_blackout
prepare_check_in
attempt_check_in_when_available
contact_overdue_review
escalate_contact_loss_review
```

Emergency escalation requires either a typed Safety / Emergency human trigger
or reviewed compound evidence such as contact overdue plus unexpected route
deviation, prolonged unexplained route-travel termination, missed rendezvous,
critical device/power loss, or another incompatible safety gate. Missed contact
alone never sends a message, calls for rescue, mutates Phase 1, or proves that a
group is missing.

A check-in becomes verified only through an acknowledged, hash-bound
`VerifiedGroupCheckInReceipt`. A queued message, local button tap, connection
attempt, or transport invocation is not delivery evidence. When contact returns,
new evidence may set `contact_restored`, sync pending receipts, and preserve the
prior blackout/overdue history; it does not erase an already opened review.

Local and remote knowledge remain explicit during disconnection:

```text
local_group_contact_state
remote_observed_contact_state
last_verified_check_in
```

The local device may know it is following the expected blackout plan while the
other group/base station still sees only the last verified check-in. Neither UI
may imply that local evidence was remotely received. All states and deadlines
are scoped per movement group; one group's check-in cannot satisfy another's.

## 4. Canonical Domain Terms

| Term | Meaning |
| --- | --- |
| Baseline Candidate Rules | Reviewed pre-trip candidate rules; immutable during a runtime session. |
| Mission Baseline Candidate | Versioned ideal-state itinerary candidate produced from human text or a selected reference-GPX route axis, with field-level lineage and unresolved gaps. |
| Reviewed Mission Baseline | Explicitly accepted, hash-bound baseline used to compile permission rules and mission projections; it is still not departure approval or runtime safety truth. |
| Daily Emergency Review Session | One current mission-day review workspace that collects all known exact night-alternative packets and projects daily completion/re-review state. |
| Mission Day Instance | One concrete occurrence of baseline day `D_n` within a runtime session; prevents a receipt from being reused after a restart, retreat, or later repetition of the same day label. |
| Planned Day-End Target | Reviewed, resolved campsite/junction/checkpoint/map target whose confirmed arrival normally closes the current mission day. |
| Day-End Arrival Receipt | Append-only deterministic evidence that the current mission-day instance reached its exact planned day-end target. |
| Emergency Bivy Review | Dedicated Safety / Emergency flow triggered when the planned day-end target cannot be reached safely; it reviews a hold/bivy target without automatically authorizing or establishing it. |
| Emergency Bivy Established Receipt | Append-only evidence that the reviewed emergency-bivy target was actually reached/established; required before contingency day close. |
| Effective Day-End Substitution | Append-only forward projection that preserves the missed baseline target while making a confirmed emergency bivy the current day's effective end. |
| Shelter Hold Interval | Calendar-neutral Safety / Emergency state at a confirmed safe-hold location between mission-day close and the next explicit mission-day start. |
| Mission Day Start Receipt | Explicit reviewed departure record that closes a Shelter Hold Interval and activates the next pending mission-day instance; never inferred from time alone. |
| Leader Departure Checklist | Six-row progressive-disclosure review that combines automatic facts with explicit leader attestations before a mission-day start receipt may be created. |
| Normalized Departure Fact | Typed, freshness-bound fact produced by an authorized weather/threat/route/device/workspace adapter; never a raw provider, sensor, health, or track payload. |
| Scout Departure Recommendation | Evidence-bound candidate explanation derived after deterministic checklist gates; cannot mark leader checks, override a block, or start the day. |
| Leader Attestation | Explicit human confirmation for field conditions Scout cannot establish automatically, bound to checklist/day/session hashes and recorded only at final review. |
| Safety / Emergency Field Conflict Receipt | Append-only typed trigger receipt by which a leader reports that direct field observation conflicts with an automatic fact or Scout suggestion; it suspends departure and cannot itself make a gate pass. |
| Field Conflict Resolution Receipt | Separate append-only Safety / Emergency record that resolves or escalates a field conflict only after fresh evidence, deterministic gate rebuild, and explicit leader review. |
| Individual Action Transition Receipt | Privacy-bounded append-only personal record of an inferred or self-corrected activity transition such as route travel ending, resting, lying, sleeping, or resuming movement; it is not a leader attestation or team-safety claim. |
| Arrival Dwell Candidate | Deterministic target-level state created after reviewed-zone GNSS arrival; it counts monotonic dwell toward automatic day close and is cancelled by positive exit, continued-route, target-conflict, or separation evidence. |
| Day-End Close Correction Receipt | Append-only Safety / Emergency correction for an incorrectly inferred target close; it preserves the original receipt and never silently rewrites mission history. |
| Movement Group | Explicit, versioned subset of expedition participants allowed to own an independent route/day/arrival/hold/start context; never inferred solely from physical separation. |
| Movement Group Formation Receipt | Append-only reviewed pre-trip or Safety / Emergency record that creates a movement group and binds its membership revision, target context, and shared dependencies. |
| Movement Group Merge Receipt | Append-only reconciliation record that creates a new merged movement-group context without rewriting the source groups' histories. |
| Expedition Day Roll-up | Read-only aggregation of per-group mission-day states; `partially_closed` is valid and never closes or starts a group by itself. |
| Communication Window Policy | Reviewed movement-group and route-scoped rule describing expected blackout, the next check-in target/event, the latest acceptable window, and allowed forward adjustments without requiring continuous heartbeats. |
| Verified Group Check-In Receipt | Hash-bound acknowledgement proving that a specific movement group's check-in was received; a queued or attempted message is not equivalent. |
| Contact-Loss Review | Safety / Emergency review opened by overdue or contradictory contact evidence; it is not an automatic emergency call or proof that the group is missing. |
| Night Alternative Review Packet | Deterministic Safety / Emergency projection for one exact alternative inside the current Daily Emergency Review Session, with conjunctive gate matrix, sequence, reviewed envelope, and source hashes. |
| Safety / Emergency Review Receipt | Append-only human disposition for one reviewed daily alternative; usable only within its bound mission-day instance and still candidate evidence until accepted by a future deterministic runtime authority. |
| Offline Emergency Review Intent | Encrypted, device-local, append-only conservative choice created without server revalidation; pending sync and never equivalent to a review or trigger receipt. |
| Offline Intent Sync Result | Append-only server result that either resolves an idempotent existing receipt, appends a canonical receipt after full revalidation, or records why the offline intent was rejected. |
| Expiry Driver | The required gate evidence or reviewed policy with the earliest deterministic validity deadline; it controls the current eligibility packet, not the enclosing daily human-review scope. |
| Contextual Permission Decision | One bounded `ContextualPermission` result for an action and context. |
| Scout Action Event | Append-only record of an action starting, ending, being cancelled, or exceeding its authorized duration. |
| Safety / Emergency Trigger Receipt | Typed, hash-bound receipt emitted by the Safety / Emergency path; the only accepted evidence source for a human-driven cause. |
| Time Debt | Non-negative delay attributable to completed or ongoing events relative to the active projection. |
| Protected Reserve | Safety margin that cannot be spent to preserve the original itinerary. |
| Discretionary Event | Future optional event whose duration may be shortened or cancelled. |
| Forward Constraint Projection | Derived, forward-only rules and timings effective after a specific event sequence. |
| Scout Pace Recommendation | Evidence-bound, candidate-only advice for current and remaining climbing rhythm; subordinate to Safety / Emergency and deterministic permission policy. |
| Runtime Authority | Deterministic field service allowed to own live action admission or controlled Phase 1 transitions. The Dashboard is not this authority by default. |

Avoid saying that the workbench “modifies the pre-trip rules.” It preserves the
baseline and derives a new effective projection for the remaining mission.

## 5. Required Workspace Inputs

### 5.1 Pre-trip baseline

```text
project.json
inbox/conversations/baseline_authoring/{draft_id}.jsonl
normalized/architecture/itinerary_intent.json
candidates/mission_baselines/{baseline_id}/versions/{revision_id}.json
reviews/review_decision_log.json
outputs/mission_baselines/{baseline_id}/reviewed/{review_id}.json
normalized/permissions/contextual_permission_model.json
candidates/contextual_permission_rules.json
outputs/compiled_mission_graph.reviewed.json
outputs/planned_eta.json
outputs/weather_daylight_evidence.json
```

The Mission Baseline refs are additive proposed workspace contracts. A reviewed
baseline must bind the exact candidate, route-axis, mission-graph, and source
hashes used to produce it. `contextual_permission_rules.json` must in turn bind
the reviewed baseline hash so runtime projection cannot mix rules from one
itinerary with another.

All pre-trip permission rules remain `candidate_only=true` and
`runtime_safety_truth=false`.

### 5.2 Optional runtime/replay inputs

```text
runtime/sessions/{session_id}/session_manifest.json
runtime/sessions/{session_id}/plan_refs/mission_graph_ref.json
runtime/sessions/{session_id}/events/event_index.jsonl
runtime/sessions/{session_id}/events/plan_node_events.jsonl
runtime/sessions/{session_id}/events/contextual_permission_events.jsonl
runtime/sessions/{session_id}/events/scout_action_events.jsonl
runtime/sessions/{session_id}/events/user_trigger_events.jsonl
runtime/sessions/{session_id}/team/group_progress_events.jsonl
runtime/sessions/{session_id}/reviews/mission_days/{mission_day_instance_id}/daily_review_session.json
runtime/sessions/{session_id}/reviews/night_alternative/{packet_id}.json
runtime/sessions/{session_id}/reviews/safety_emergency_review_decisions.jsonl
runtime/sessions/{session_id}/events/safety_emergency_trigger_receipts.jsonl
runtime/sessions/{session_id}/events/day_end_arrival_receipts.jsonl
runtime/sessions/{session_id}/reviews/emergency_bivy/{review_id}.json
runtime/sessions/{session_id}/events/emergency_bivy_established_receipts.jsonl
runtime/sessions/{session_id}/holds/shelter_hold_intervals.jsonl
runtime/sessions/{session_id}/events/mission_day_start_receipts.jsonl
```

Existing runtime safety reducer snapshots may be joined by stable refs and
hashes. They remain candidate/replay evidence until an explicit runtime
authority path says otherwise.

### 5.3 Accepted causal inputs

The projector may accept only these causal source classes:

| Cause domain | Accepted source | Rejected substitutes |
| --- | --- | --- |
| Human-driven | Typed Safety / Emergency trigger receipt with reducer or approved Safety / Emergency lineage | Dashboard click, free-text note, generic `user_trigger_events.jsonl` row, inferred operator intent, alert delivery receipt |
| Weather | Reviewed weather evidence plus a validated `weather_gate` event | Unattributed prose, stale forecast without gap status, model-only assertion |
| Movement / progress | Privacy-safe route-progress frame plus validated pace/delay/darkness gate events derived from IMU/PDR/GNSS | Raw IMU stream, raw track, raw GPX, exact location history, UI-computed pace |

`user_trigger_events.jsonl` may index a Safety / Emergency receipt, but the
index row is not sufficient evidence by itself. An alert approval or transport
receipt proves approval/delivery workflow state, not the human cause of a route
delay, unless a separate typed Safety / Emergency action trigger is present.

## 6. Event And Projection Model

### 6.1 Required action-event semantics

A future typed `ScoutActionEvent` contract must be able to represent:

- stable event id and monotonic session sequence;
- action id using the canonical `OutdoorAction` vocabulary;
- route, segment, CP, and map target ids without embedding raw coordinates;
- referenced permission decision id/hash;
- authorized duration;
- actual or elapsed duration;
- overrun minutes;
- explicit causal links to Safety / Emergency trigger, weather-gate, or
  movement/progress evidence, or an `unknown` gap;
- source/evidence refs and confidence;
- start, end, cancellation, and in-progress state;
- candidate/runtime authority and privacy boundaries.

The cause is not optional merely for explanation. A ten-minute weather hold may
also invalidate a weather window, while a ten-minute discretionary overrun may
only consume discretionary time. Unknown cause must fail conservative.

### 6.2 Causal join and pace-advice contract

`ScoutActionEvent` is the only event that owns authorized duration, actual or
elapsed duration, and overrun minutes. Cause evidence never adds a second copy
of the same time debt. Each causal link must expose:

```text
subjectActionEventId
causeDomain: safety_emergency | weather | movement_progress | unknown
causeCode
sourceEventId
sourceRef + sha256
sessionId
planNodeId
sequenceStart + sequenceEnd
relation: confirmed | detected | correlated | conflicting
confidence
```

The join requires explicit subject/session/node refs and compatible sequence
intervals. Timestamp proximity, labels, or model similarity are insufficient.
Multiple links may coexist, but minutes must not be apportioned between causes
unless reviewed non-overlapping intervals make that allocation deterministic.
Conflicting or unknown links keep debt single-counted and produce a visible,
conservative evidence gap.

A `ScoutPaceRecommendation` must expose at least:

```text
recommendationId
effectiveAfterSequence
appliesFromPlanNodeId
currentPaceBand?
remainingSegmentPaceBands[]
holdOrRecheckCondition?
affectedPlanNodeIds[]
triggerAndFactRefs[]
permissionDecisionRef
forwardProjectionRef
supersededBySafetyTrigger
candidate_only: true
runtime_safety_truth: false
```

Signal adapters and safety gates establish normalized facts. Scout may synthesize
an advisory candidate from them, but the deterministic assessor/projector owns
policy validation, protected floors, action limits, and rejection. A Safety /
Emergency trigger wins precedence over weather/movement advice and causes a new
forward projection after its sequence.

### 6.3 Plan-node adjustment contract

The projector resolves adjustment policy in this order:

1. reviewed, hash-bound plan-node policy;
2. reviewed baseline contextual-permission rule;
3. conservative typed action default.

If the node's declared policy conflicts with its reviewed source, or if the
source is missing, the effective policy is `review_only` and the conflict is
reported in `dataQuality`.

For `auto_reduce`, the deterministic allocator may consume only:

```text
targetDurationMinutes - minimumDurationMinutes
```

For `protected_floor`, that difference remains available only when the reviewed
node explicitly marks it as discretionary excess. The floor itself is not a
time budget. For `review_only`, available automatic repayment is always zero.

The projection must expose both declared and effective policy, the source that
won precedence, available reducible minutes, applied reduction, and remaining
unrepaid debt for every affected node.

### 6.4 Forward constraint reducer

The deterministic projector consumes:

```text
baseline rules + reviewed mission graph
              + append-only action and permission events
              + route-progress and safety-gate projection
              -> ForwardConstraintProjection
```

Minimum projection fields:

```text
artifactKind: scout_forward_constraint_projection
schemaVersion
projectId
sessionId?
baselineRulesRef + sha256
missionGraphRef + sha256
throughSequence
validAfterSequence
currentRouteContext
timeDebtMinutes
timeDebtCauses[]
protectedReserves
discretionaryBudgetMinutes
adjustments[]
remainingPlanNodes[]
currentDecision?
alternativePlanCandidates[]
dataQuality
sourceRefs[]
boundary
```

Each adjustment must expose the original value, effective value, delta, reason,
trigger event refs, and whether it was automatic or only proposed for review.

### 6.5 Deterministic invariants

1. Replaying the same ordered event set produces the same projection hash.
2. Events at or before `throughSequence` cannot be rewritten by the projection.
3. No adjustment targets a completed plan node.
4. Protected reserves never decrease as an automatic debt-repayment action.
5. Unknown, missing, stale, or conflicting required evidence cannot produce a
   reassuring permission.
6. A night-travel branch requires explicit reviewed eligibility and remains a
   candidate until the appropriate runtime authority accepts it.
7. Every effective rule is traceable to the baseline plus triggering events.
8. Human-driven cause evidence without a valid Safety / Emergency trigger
   receipt is rejected.
9. One action overrun contributes time debt once, regardless of the number of
   causal evidence links.
10. Safety / Emergency triggers supersede incompatible Scout pace advice.

## 7. Dashboard Read Contract

Recommended additive endpoint:

```text
GET /admin/pretrip/projects/{project_id}/contextual-permission-dashboard
schemaVersion=contextualPermissionDashboard.v1
```

The endpoint should compose a bounded, UI-safe projection rather than expose an
arbitrary workspace file path. It should return:

- baseline model/rules availability and hashes;
- human-review and candidate-only status;
- current or selected replay session status;
- current contextual permission decision, if one can be derived;
- latest Forward Constraint Projection;
- original-versus-effective remaining plan nodes;
- time debt and protected reserve ledger;
- alternatives, uncertainty, missing inputs, and source refs;
- explicit action and authority boundaries.

The GET must not fetch upstream data, write workspace files, run a model, call
`/safety/*`, or authorize an action.

The route must have its own Dashboard data scope. Direct navigation to
`#outdoor-permission` must load the selected project and permission projection
without depending on another page having loaded first.

### 7.1 Baseline authoring command contract

The authoring commands are additive and separate from the Dashboard GET. Exact
route names may be finalized during implementation, but the semantic boundary
is fixed:

```text
POST .../mission-baseline/preview             writesPerformed=false
POST .../mission-baseline/generate-draft      writesPerformed=false
POST .../mission-baseline/candidates           explicit candidate write
POST .../mission-baseline/patches/preview      writesPerformed=false
POST .../mission-baseline/candidates/from-patch explicit candidate write
POST .../mission-baseline/reviews/accept       explicit reviewed write
```

Every write command must be project-scoped, reject arbitrary destination paths,
use an idempotency key, bind expected source/base hashes, fail on stale-base
conflict, validate the resulting artifact before commit, and return its new ref
and hash. Save and Accept controls must state what will be written before the
operator confirms them.

The accept response must continue to declare:

```text
candidate_only=true
runtime_safety_truth=false
departure_approval_granted=false
final_mission_graph_generated=false
active_runtime_session_updated=false
safety_api_called=false
```

### 7.2 Cross-surface Emergency review contract

Permission and Safety / Emergency must use one packet/receipt contract rather
than separate browser-local state:

```text
Contextual Permission eligibility projection
  -> Open in Safety / Emergency (no approval on Permission page)
  -> server opens current DailyEmergencyReviewSession
  -> rebuilds exact NightAlternativeReviewPacket items for current D_n
  -> Safety / Emergency daily human-review interface
  -> append-only SafetyEmergencyReviewReceipt items + daily summary
  -> Safety / Emergency trigger receipt projection
  -> Contextual Permission refreshes review status and forward constraints
```

Recommended additive API semantics:

```text
GET  .../safety-emergency/mission-days/{mission_day_instance_id}/night-review
POST .../safety-emergency/mission-days/{mission_day_instance_id}/night-review/{packet_id}/decisions
GET  .../contextual-permission-dashboard   # reflects receipt/status read-only
```

The decision POST must require an idempotency key, packet id/hash, project and
session ids, mission day id/instance/generation, reviewed sequence, decision,
reviewer identity, and explicit confirmation. The server must reconstruct and
revalidate the current-day packet before writing the decision. It rejects
stale, ineligible, wrong-day, mismatched, already-decided, or invalidated
packets.

The prototype response and receipt must declare:

```text
human_review_recorded=true
runtime_authorization_performed=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
outbound_action_performed=false
```

### 7.3 Offline intent and reconnect contract

Creating an offline intent is a device-local operation and performs no request.
Its boundary metadata must declare:

```text
pending_sync=true
human_review_recorded=false
canonical_receipt_created=false
runtime_authorization_performed=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
outbound_action_performed=false
```

Recommended reconnect API semantics are additive:

```text
POST .../safety-emergency/mission-days/{mission_day_instance_id}/night-review/offline-intents/sync
GET  .../safety-emergency/mission-days/{mission_day_instance_id}/night-review/receipts
```

The sync POST accepts only conservative offline decisions, the intent and
idempotency ids, supersession lineage, bound packet/project/session/mission-day/
generation/sequence and source hashes, and device-instance metadata. It must reject
`approve_for_runtime_consideration` regardless of cached eligibility. The
server reconstructs current truth instead of trusting cached gate values.

The response returns exactly one status:

```text
receipt_appended | already_recorded | rejected_sync_audit
```

`receipt_appended` includes the new canonical receipt ref/hash.
`already_recorded` includes the existing matching receipt ref/hash.
`rejected_sync_audit` includes an append-only audit ref/hash and explicit
conflict/revalidation reasons, but no receipt. The client removes no local
history until it has durably recorded one of these server results.

### 7.4 Freshness and expiry API contract

Every packet GET/rebuild response includes authoritative `server_now`,
`built_at`, `expires_at`, `freshness_state`, `expiry_driver`, bounded
`freshness_inputs`, and `invalidated_by`. Each freshness input preserves its
gate id, evidence ref/hash, deterministic `valid_until`, and optional
`refresh_warning_at`; raw sensor/provider payloads remain server-side.

The decision POST repeats the packet id/hash and expiry known by the client for
conflict detection, but the server does not trust those values. Immediately
before append it rebuilds current truth and either returns a canonical receipt
bound to the current mission-day scope plus the exact reviewed packet snapshot,
or fails with one of:

```text
packet_expired
packet_invalidated
freshness_unknown
packet_replaced
```

When safe to disclose, a failure includes the current `expiry_driver` or
`invalidated_by`, plus a replacement packet ref/hash that still requires a new
human inspection. It must not replay the prior selected decision against that
replacement packet.

### 7.5 Daily Emergency review contract

The daily review GET returns one `DailyEmergencyReviewSession` containing the
current mission-day identity, day-plan hash, review generation, daily state,
scope refs, planned/effective day-end targets, day-end state, exact alternative
packets, current receipts, freshness summaries, and reasons an item or the day
requires re-review. Only the current mission-day instance accepts decision
POSTs; previous days are read-only and future days are candidate previews.

Every receipt includes:

```text
scope_kind=mission_day
mission_day_id
mission_day_instance_id
review_generation
mission_day_plan_ref/hash
planned_day_end_target_ref/hash
alternative_id
reviewed_envelope_hash
reviewed_packet_ref/hash
reviewed_packet_expires_at
scope_start_ref
scope_end_ref
supersedes_receipt_ref
```

`reviewed_packet_expires_at` records which evidence snapshot the human saw; it
does not define the daily receipt's scope. A rebuilt packet may reuse the daily
human-review prerequisite only when the alternative id, reviewed-envelope hash,
mission-day instance/generation, and material safety-policy state still match.
The current evidence must independently pass all gates.

The server may close the previous session only after a valid
`DayEndArrivalReceipt` for its planned target or an
`EmergencyBivyEstablishedReceipt` for a reviewed effective target. It then
keeps all receipts append-only and exposes the next baseline day as
`pending_day_start`. Calendar midnight alone is not a transition event. A
`MissionDayStartReceipt` later activates the next mission-day instance and its
daily review. A same-day material change increments `review_generation`, retains
earlier receipts for audit, and requires new decisions only for affected
alternatives; unaffected alternatives may remain reviewed when their envelope
and lineage still match.

### 7.6 Destination-driven day-end and emergency-bivy contract

The current-day projection adds:

```text
planned_day_end_target_ref/hash
effective_day_end_target_ref/hash
day_end_state
day_end_feasibility: reachable | at_risk | unreachable | unknown
day_end_feasibility_reasons[]
day_end_arrival_receipt_ref
emergency_bivy_review_ref
emergency_bivy_established_receipt_ref
baseline_day_end_reached
day_completion: open | planned_closed | contingency_closed
```

Recommended additive read/command semantics are:

```text
GET  .../safety-emergency/mission-days/{mission_day_instance_id}/day-end
POST .../safety-emergency/mission-days/{mission_day_instance_id}/cannot-reach-day-end
POST .../safety-emergency/mission-days/{mission_day_instance_id}/emergency-bivy/decisions
POST .../safety-emergency/mission-days/{mission_day_instance_id}/day-end/confirm
POST .../safety-emergency/mission-days/{mission_day_instance_id}/day-end/corrections
```

The human cannot-reach command must produce the typed Safety / Emergency trigger
receipt required by D-008. Automatic feasibility facts may open the same review
flow without claiming a human cause. The emergency-bivy decision command uses
the common idempotency, two-step confirmation, project/session/day/sequence/hash,
freshness, reviewer, and no-authority boundaries.

Automatic arrival and establishment receipts belong to the deterministic
observation service, not Scout or the Dashboard renderer. The explicit confirm
POST is available only in the Safety / Emergency on-site flow and binds an
authorized participant, exact target and current sequence. The Dashboard reads
and renders these records; it cannot fabricate arrival or mutate the planned
target.

### 7.7 Shelter Hold and mission-day start contract

Recommended additive semantics are:

```text
GET  .../safety-emergency/shelter-holds/current
POST .../safety-emergency/shelter-holds/{hold_id}/decisions
POST .../safety-emergency/shelter-holds/{hold_id}/departure-reviews
GET  .../safety-emergency/mission-days/pending-start
```

The read projection returns the confirmed hold target, origin day close,
pending next day, hold state, calendar elapsed duration, current automatic and
human cause refs, weather/threat/team/resource evidence summaries, freshness,
missing/conflicting facts, available conservative alternatives, and explicit
authority/effect boundaries.

Hold decisions use idempotency, reviewer confirmation, current hold/day/session/
sequence and evidence hashes. Continuing hold, relocating, retreat review, and
escalation remain separate decisions. A departure review cannot reuse an older
weather packet or the closed day's receipt; it rebuilds all required start
evidence and, if accepted, appends a `MissionDayStartReceipt` for the exact
pending day-plan hash.

The start receipt response must continue to declare no Phase 1 mutation,
`/safety/*` call, transport, outbound action, or claim that the route is safe.
It activates only the next daily review/runtime-candidate context. In offline
mode, `Resume/start next day` is disabled because start evidence cannot be
revalidated; Continue hold, conservative relocation review, and escalation may
create pending local intents under D-014.

### 7.8 Departure checklist and Scout recommendation contract

Recommended additive semantics are:

```text
GET  .../safety-emergency/shelter-holds/{hold_id}/departure-review
POST .../safety-emergency/shelter-holds/{hold_id}/departure-review/refresh-facts
POST .../safety-emergency/shelter-holds/{hold_id}/departure-review/confirm
```

The GET is bounded and read-only. It returns exactly six top-level checklist
rows, automatic fact/gate summaries, required leader attestations, active Safety
/ Emergency constraints, pending day-plan/review hashes, Scout recommendation,
freshness/gaps, and `can_confirm_departure`. It does not fetch upstream data or
run a model while rendering.

Resident authorized adapters may keep normalized facts current. The explicit
refresh POST is a fallback that invokes only allow-listed read-only evidence
adapters, persists bounded fact/source refs, reruns deterministic gates, and may
request a new candidate Scout explanation. It must not change leader
attestations, close the hold, create a start receipt, invoke hardware, or perform
an outbound action.

The final confirm POST binds:

```text
hold_id
pending_mission_day_id
pending_day_plan_ref/hash
daily_review_ref/hash
departure_checklist_ref/hash
automatic_gate_refs/hashes[]
leader_attestations[]
active_safety_state_ref/hash
reviewed_sequence
idempotency_key
reviewer_identity
explicit_confirmation
```

The server rebuilds current gates before append. Any `blocked`, `unknown`,
`leader_check_required`, stale/mismatched hash, incompatible Safety / Emergency
trigger, or changed day plan rejects the command with
`Mission day not started` plus row-level blockers. Only a fully passing command
may append `MissionDayStartReceipt`; even then all runtime/Phase 1/safety API/
transport/outbound flags remain false in the prototype.

### 7.9 Field-conflict report and resolution contract

Recommended additive Safety / Emergency semantics are:

```text
GET  .../safety-emergency/shelter-holds/{hold_id}/departure-review/field-conflicts
POST .../safety-emergency/shelter-holds/{hold_id}/departure-review/field-conflicts
POST .../safety-emergency/shelter-holds/{hold_id}/departure-review/field-conflicts/{conflict_id}/resolve
```

The report POST binds the hold, pending mission day, checklist/row, category,
affected automatic fact refs/hashes, current event sequence, reporter,
idempotency key, and optional bounded note. The server first revalidates that
the row is current and `scout_auto` or `hybrid`, then appends one
`SafetyEmergencyFieldConflictReceipt`. Duplicate retries resolve to the same
receipt; mismatched reuse fails closed.

The resolution POST binds the conflict receipt, fresh affected gate/evidence
refs and hashes, rebuilt checklist hash, resolution reason, reviewer identity,
and explicit confirmation. It may append a
`SafetyEmergencyFieldConflictResolutionReceipt` only after deterministic
revalidation. A manual assertion without current supporting evidence cannot
resolve the conflict to pass, and a report of worse field conditions requires
explicit leader confirmation that the direct conflict has ended.

The GET is read-only and returns current conflict state plus bounded receipt,
resolution, source, freshness, and blocker refs. It does not fetch providers or
run a model while rendering. Offline report intents follow D-014: they block
local departure immediately, remain pending until sync, and never become a
start or approval receipt merely because connectivity returns.

Every response retains the prototype boundary flags: no runtime authorization,
Phase 1 mutation, `/safety/*` call, transport, outbound action, or claim that
the route is safe.

### 7.10 Individual action sensing and automatic day-close contract

The read projection adds:

```text
target_ref/hash
arrival_zone_ref/hash
arrival_state: not_detected | confirmed | dwelling | cancelled | completed
arrival_confirmation_mode: none | manual_on_site | automatic_gnss_dwell
gnss_quality_summary
route_progress_ref/hash
dwell_policy_ref/hash
dwell_required_seconds
dwell_elapsed_seconds
dwell_remaining_seconds
individual_activity_summary_ref/hash
blocking_contradictions[]
day_close_receipt_ref/hash
```

The default dwell policy is exactly `600` monotonic seconds after deterministic
GNSS arrival confirmation. A reviewed target may require a longer duration;
Scout, the client, and the model cannot shorten it dynamically. Initial
confirmation requires a fresh GNSS observation whose stated uncertainty is
compatible with the reviewed arrival zone plus matching route progress. Raw
coordinates and sensor streams are not returned to the Dashboard projection.

Each participant device may produce privacy-bounded
`IndividualActionTransitionReceipt` records through the authorized local
device-ingestion boundary. Only pseudonymous state, confidence, freshness, and
evidence hashes enter the target-level reducer. The reducer treats resting,
lying, and sleeping as supporting evidence; it treats ordinary within-zone
camp movement as neutral; and it cancels automatic completion on positive
zone-exit, continued-route, target-mismatch, or unexpected same-group separation
evidence.
Unknown personal activity does not become a safety assertion and does not
create a leader checklist.

The manual confirm POST accepts exactly:

```text
mission_day_instance_id
target_ref/hash
confirmation_mode = manual_on_site
confirmation_kind = arrived | camp_established
reviewed_event_sequence
participant_identity
idempotency_key
explicit_confirmation
uncertainty_acknowledgement
```

It confirms only target arrival or occupation. It never asserts that all
participants are resting, asleep, healthy, or accounted for. Emergency-bivy
establishment requires an already selected reviewed bivy target.

The observation service appends the same canonical receipt automatically when
the dwell reaches its bound with no blocking contradiction. Automatic and
manual retries are idempotent and converge on one day-close result. A later
correction POST cannot overwrite that receipt; it appends a
`DayEndCloseCorrectionReceipt`, rebuilds the mission-day projection, and keeps
the correction lineage visible.

A resident offline observation service may finish the monotonic countdown and
record `D_n completed · pending sync` locally. Sync preserves the receipt/hash
or records a conflict audit; it never starts the next day. All outputs retain
the no-runtime-authorization, no-Phase-1-mutation, no-transport, and no-outbound
boundaries.

### 7.11 Movement-group ledger and roll-up contract

Recommended additive Safety / Emergency semantics are:

```text
GET  .../safety-emergency/movement-groups
POST .../safety-emergency/movement-groups
POST .../safety-emergency/movement-groups/{movement_group_id}/membership-revisions
POST .../safety-emergency/movement-groups/merge
GET  .../safety-emergency/movement-groups/{movement_group_id}/mission-day
```

The collection GET returns bounded current group cards plus the expedition
roll-up. It does not return raw member locations, personal sensor streams, or a
synthetic all-team decision. Every group-scoped day-end, bivy, Shelter Hold,
departure-review, daily-review, and next-day-start request/receipt additionally
binds:

```text
movement_group_id
membership_revision
participant_refs_hash
group_day_instance_id
group_target_ref/hash
shared_dependency_refs/hashes[]
```

Formation POST is accepted only from a reviewed baseline grouping or the
Safety / Emergency field-explicit flow. It binds exact pseudonymous membership,
route/target context, formation reason, coordinator, event sequence, source
hashes, reviewer/participant confirmation, and idempotency key. GNSS distance,
pace divergence, missing telemetry, or Scout output cannot invoke it.

Membership revision moves or adds participants prospectively and never changes
which revision earlier personal or group receipts referenced. Merge requires
the source group ids/revisions, current day/route/hold states, intended merged
context, shared-dependency reconciliation, explicit confirmation, and one
idempotency key. Different current contexts return
`cross_group_review_required`; the server never chooses a surviving history.

Each group evaluates target arrival, dwell, day close, Shelter Hold, departure
review, and MissionDayStartReceipt independently. A group command cannot use a
receipt from another group. Cross-group blocking is allowed only through an
explicit shared dependency or multi-group Safety / Emergency constraint whose
scope refs and hashes match every affected group.

A resident Safety / Emergency service may append a field-explicit formation or
membership revision while offline and mark it `pending_sync`; it must remain
visible and hash-bound. Sync either preserves the same canonical receipt or
records a conflict audit. Sensor-detected unexpected separation remains a
separate alert/review fact and is never converted automatically into an
intentional group.

All movement-group endpoints retain the prototype no-runtime-authorization,
no-Phase-1-mutation, no-hardware, no-transport, and no-outbound boundaries.

### 7.12 Communication-window and contact-loss contract

Recommended additive read/review semantics are:

```text
GET  .../safety-emergency/movement-groups/{movement_group_id}/communication
GET  .../safety-emergency/communication/roll-up
POST .../safety-emergency/movement-groups/{movement_group_id}/communication/revisions
POST .../safety-emergency/movement-groups/{movement_group_id}/contact-loss-reviews
```

The group GET returns the current baseline/effective window, route scope,
expected-blackout match, next check-in target/event, authoritative time,
deadline driver, local-versus-remote observation states, last verified receipt,
automatic contradictions, review state, Scout recommendation, and explicit
effect boundaries. It reads stored projections and does not ping devices, send a
message, or run a model during render.

Communication policy revisions are append-only and bind the movement-group and
membership hashes, route scope, blackout segments, target/event, baseline and
proposed effective window, allowed adjustment source, reviewer, event sequence,
and idempotency key. The server rejects retroactive revisions whose reviewed
sequence is already overdue, mismatched, or superseded. A revision cannot claim
that another group or base station received it while disconnected.

The deterministic contact reducer accepts only bounded facts from authorized
route-progress, network-availability, device/power, rendezvous, and verified
transport-receipt adapters. It produces `expected_blackout` only on a matching
reviewed route scope and produces `contact_overdue` at the authoritative
effective deadline when no valid group receipt exists. Device wall clock and
Scout text are never authoritative.

The contact-loss review POST belongs to Safety / Emergency. It binds the group,
policy/window, overdue and compound-evidence refs, current route/day/hold hashes,
reviewer, decision, sequence, and idempotency key. Human concern must enter as a
typed Safety / Emergency trigger. Automatic overdue remains distinct evidence.
The review may record continue monitoring, request check-in when available,
coordinate rendezvous review, or escalate to the separate Emergency Call Out
flow; it cannot send, call, or claim delivery itself.

`VerifiedGroupCheckInReceipt` is accepted only from an allow-listed transport
adapter with a correlated remote acknowledgement. `queued`, `attempted`,
`connected`, or local `sent` UI state is insufficient. Receipt replay is
idempotent and group-scoped. Contact restoration preserves the earlier overdue
and review trail.

The roll-up GET returns only bounded per-group states and shared blockers. During
offline operation the local projection remains explicit about what remote
observers cannot know. Every response retains no Phase 1 mutation, hardware
control, outbound action, transport invocation, or delivery claim unless a
separate future approved transport receipt proves the latter.

## 8. Page Jobs

The workbench must let an operator answer:

1. Which baseline rule applied to the selected action?
2. What actually happened in the field or replay?
3. How much time debt exists, and what caused it?
4. Which future events changed, and which protected reserves did not change?
5. What is the next bounded decision?
6. Which alternatives are available if the baseline can no longer be met?
7. What evidence is missing, stale, conflicting, or candidate-only?
8. Did the recommendation come from a Safety / Emergency trigger or from Scout
   analysis of weather and movement/progress facts?
9. What exact target ends the current mission day, can it still be reached, and
   is the system en route, in Emergency Bivy Review, or in a multi-day Shelter
   Hold awaiting an explicit next-day start?

## 9. Confirmed Information Architecture

The recommended Dashboard hierarchy is **remaining-plan first**, with a compact
current-decision strip above it:

```text
+--------------------------------------------------------------------------+
| Contextual Permission | baseline/replay/runtime-observer | freshness     |
+--------------------------------------------------------------------------+
| CURRENT DECISION: decision | limit | leave-by | reason | next step       |
+--------------------------+-----------------------------------------------+
| ACTION / CONTEXT          | REMAINING MISSION: BASELINE vs EFFECTIVE      |
| canonical action          | CP / event timeline                           |
| current CP -> next CP     | shortened / cancelled / protected / review   |
| scenario/replay selector  | time-debt propagation and alternatives        |
+--------------------------+-----------------------------------------------+
| RISK-BUDGET LEDGER        | MAP: current/next/retreat/affected nodes      |
| debt + protected reserves | candidate geometry; no implicit authorization |
+--------------------------+-----------------------------------------------+
| EVENT + EVIDENCE LEDGER: sequence, causes, hashes, missing/stale/conflict |
+--------------------------------------------------------------------------+
```

This is an admin/workbench hierarchy. A future field-runtime UI may instead be
decision-first and phone-first, but it is a separate surface.

### 9.1 Dashboard style-alignment contract

The workbench should feel like a sibling of Architecture, Weather, and
Navigation:

- use the existing dark field-instrument shell, serif panel headings, and mono
  operational metadata;
- use a wide two-column workbench at desktop size, approximately a flexible
  `1.55fr` primary projection and a bounded `0.65fr` inspector/context rail;
- stack the workbench to one column below the established desktop-collapse
  breakpoint;
- use a compact mobile view switcher below the established mobile breakpoint
  rather than shrinking the full timeline until it becomes unreadable;
- retain keyboard tab, focus-visible, evidence hint, map pan/zoom/Fit, and
  selected-item synchronization behavior;
- use shared `info`, `warn`, `bad`, and verified `ok` semantics. Candidate,
  replay, or runtime-observer data must not receive a reassuring green state
  merely because the payload loaded successfully;
- use new `permission-*` component class names only where no shared primitive
  expresses the domain object. Do not copy Architecture class names for
  unrelated Permission semantics.

The Remaining Mission Projection may borrow the Architecture page's readable,
horizontally navigable route-workbench rhythm, but its lanes must express
baseline time, effective time, time debt, protected reserve, and adjustment
status rather than route-demand metrics.

### 9.2 Action/context rail interaction states

The action/context rail must make inspection and simulation visibly different:

| State | Trigger | Required presentation |
| --- | --- | --- |
| `INSPECTING_STORED` | Select an action, plan node, event, or session | Focus the stored rule, event lineage, and evaluated projection; do not recompute. |
| `DIRTY_NOT_EVALUATED` | Change a hypothetical cause, duration, or context input | Show `Inputs changed · not evaluated`; preserve and label the last evaluated Current Decision. |
| `SIMULATING` | Explicitly activate `Run candidate simulation` | Disable duplicate submission and show the bounded scenario being evaluated. |
| `SIMULATION_READY` | Deterministic assessment completes | Show a candidate comparison with scenario hash, deltas, gaps, and `candidate_only` boundary. |
| `SIMULATION_FAILED` | Validation, evidence, or assessment fails | Keep the stored state intact and show a fail-closed, actionable error. |

`Run candidate simulation` must be unavailable when the reviewed baseline or
mission graph is missing, or when event ordering is conflicting. Missing
optional evidence may remain evaluable only if the deterministic assessor can
return a conservative result with the gap shown explicitly.

### 9.3 Context lens and Baseline authoring workbench

The top context lens is:

```text
Baseline | Replay | Live Observer
```

`Baseline` is the default. An available active runtime session produces a
visible `Open Live Observer` notice but must not switch the lens automatically.
`Replay` binds exactly one sealed session. `Live Observer` binds exactly one
active session whose project, mission-graph, and baseline hashes match. Lens
switching clears dirty simulation inputs, never merges session event streams,
and keeps the immutable Baseline comparison visible.

Within `Baseline`, the authoring selector is:

```text
Human Design | Generate from Ref. GPX
```

Both modes use the established wide-frame workbench:

```text
+--------------------------+-----------------------------------------------+
| SOURCE COMPOSER          | BASELINE DAY / ROUTE PROJECTION               |
| text or ref. GPX axis    | D0 logistics; D1-Dn nodes, branches, camps    |
| explicit Generate action | matched / ambiguous / missing / conflict      |
+--------------------------+-----------------------------------------------+
| SCOUT REVIEW CONVERSATION| MAP + VALIDATION / ASSUMPTION LEDGER          |
| hash-bound patch proposals| route axis, named points, gaps, source refs   |
+--------------------------+-----------------------------------------------+
| VERSION DIFF + REVIEW STATE + EXPLICIT CANDIDATE/REVIEW ACTIONS           |
+--------------------------------------------------------------------------+
```

Typing text or selecting a GPX performs no model call and creates no baseline.
An explicit Generate action captures the source hash, runs the bounded Scout
draft path, and then passes the result through deterministic schema, route,
continuity, source-lineage, and graph checks. The UI must keep raw source,
parsed intent, candidate projection, validation results, and reviewed baseline
as separate states.

The authoring surface should reuse the Dashboard textarea, field, panel, chip,
map, evidence drawer, and Assistant status patterns. It must not become a
full-screen chat. The Baseline timeline/map projection stays primary; Scout
conversation remains a bounded reviewer and patch proposer.

The action row must keep no-write and write actions visually distinct:

```text
Preview Source | Generate Draft
Save Candidate Version
Preview Scout Patch | Save Patch As New Version
Accept Reviewed Baseline
```

The two Save actions use the existing operator-triggered warning treatment.
Accept uses a separate review confirmation frame showing candidate hash,
validation status, unresolved blockers, selected route axis, and the exact
workspace refs that will be appended or created. A successful Accept must show
`Reviewed baseline · not departure approved` rather than a generic green-ready
message.

For a proposal-first Ref. GPX candidate, raw JSON must not be the primary review
surface. The established workbench renders:

1. one compact proposal summary showing route length, proposed day count,
   usable/missing p75 counts, blockers, Safety / Emergency handoff count, and
   imported `route_days` as non-authoritative metadata;
2. ordered day cards showing start anchor, exact proposed day-end binding,
   complete/partial/unknown timing evidence, uncertainty IDs, and day-scoped
   emergency-bivy handoff candidates;
3. a collapsed, read-only `Typed evidence payload` disclosure;
4. one `Quick review` panel with no more than three controls:
   - confirm every exact daily endpoint;
   - acknowledge all listed Permission timing uncertainties when present;
   - acknowledge the exact Safety / Emergency handoff as still pending when
     present.

The first Accept tap only opens the existing fixed confirmation sheet. The sheet
summarizes the exact day, uncertainty, and pending handoff sets but adds no fourth
checkbox. Only the final `Accept reviewed baseline` activation sends
`explicit_confirmation=true`.

At narrow widths the same DOM becomes one column. Day-end names, refs, hashes,
and timing qualifiers wrap without truncation; review controls remain at least
44 CSS pixels high; raw typed data uses pre-wrap; and the page must not acquire
horizontal scrolling. The authority statement remains visible:

> Permission confirms exact day-end targets and listed timing-gap
> acknowledgments only. Retreat and emergency-bivy items remain pending Safety /
> Emergency review. Departure and runtime safety are unchanged.

### 9.4 Safety / Emergency dedicated human-review interface

This is a required cross-feature implementation, not a Permission-page modal.
The existing Safety / Emergency route must gain a dedicated
`Daily Emergency Review` view, with `Night Alternative` as its first review
kind. The view opens the current `DailyEmergencyReviewSession` and groups exact
alternative packets under `D_n`. The desktop Dashboard route and field-oriented
Emergency mobile surface must consume the same server session, packets, and
decision records; they must not maintain independent approval state.

The review view is decision-first and must show:

1. current mission day, daily completion/re-review status, packet status, exact
   selected route alternative, current safety state, reviewed sequence, and
   expiry/invalidation status;
2. the conjunctive gate matrix, with hard failures and missing evidence before
   supportive evidence;
3. current/next/safe-objective/retreat/bivy map targets using the shared offline
   map contract;
4. `Hold / bivy`, `Reject night travel`, `Approve for runtime consideration`,
   and `Escalate emergency` controls, enabled only for valid states;
5. packet hash, source lineage, prior decisions, and receipt in the evidence
   drawer rather than in the first emergency decision layer.

The Permission page shows only:

```text
D_n review not started | Partially reviewed | Reviewed
Reviewed · evidence refresh required | Re-review required | Day closed
Selected alternative: Ineligible | Consideration reviewed | Rejected
Hold/bivy selected | Escalated | Expired/invalidated
```

It provides `Open in Safety / Emergency` and `View review receipt` links. It
must not mirror the decision buttons or write the receipt itself.

### 9.5 Responsive presentation and mobile task contract

At desktop widths (`>=1120px`), Permission keeps the full wide-frame workbench:
compact Current Decision, primary Remaining Mission Projection, action/context
rail, risk-budget ledger, supporting map, and evidence ledger. Between the
desktop-collapse and mobile breakpoints (`761px–1119px`), these regions stack in
the same priority order without removing authoring or candidate-simulation
capability.

At mobile widths (`<=760px`), Permission uses a compact view switcher:

```text
Now | Remaining | Safety | Evidence
```

- `Now` is the default and shows decision, limit, reason, leave-by/expiry,
  confidence/gap state, and the next required action before secondary detail.
- `Remaining` shows baseline versus effective-after-event, affected future
  nodes, protected reserves, and review-only alternatives without compressing
  them into an unreadable desktop timeline.
- `Safety` shows the current Safety / Emergency state, night-review eligibility
  and receipt status, invalidation reason, and a large
  `Open in Safety / Emergency` action.
- `Evidence` shows freshness, missing/conflicting evidence, source summaries,
  and the evidence drawer entrypoint.

The map remains supporting evidence. It opens from a clearly labelled target or
Map action and must preserve selected current/next/retreat/bivy targets, but it
does not displace the `Now` decision from the first mobile screen.

Mobile Permission supports inspection, view switching, map inspection,
evidence inspection, receipt inspection, refresh, and Safety / Emergency
handoff. Baseline text/GPX authoring, baseline promotion, scenario editing, and
`Run candidate simulation` remain desktop/tablet workbench tasks. Mobile must
show these as `Continue on desktop` where their absence would otherwise be
ambiguous; it must not silently omit an active draft or pending review state.

The Safety / Emergency mobile review uses a separate decision-first switcher:

```text
Decision | Field | Gates | Evidence
```

- `Decision` is always the entry view and shows packet validity, exact
  alternative, current safety state, expiry, one-line review reason, and all
  currently valid human decisions.
- `Gates` puts hard failures and missing evidence above passing evidence and
  explains every disabled decision in plain language.
- `Field` shows destination, Shelter Hold, individual semantic activity,
  movement-group, communication-window, and departure state.
- `Evidence` shows the supporting map plus lineage, hashes, prior decisions,
  and resulting receipts. The map remains evidence, not a decision tab.

The Safety / Emergency action region remains sticky above the safe-area inset.
Primary actions are at least `56px` high, use explicit verb-first labels, and
remain visually distinct from navigation. Disabled actions remain visible with
their blocking reason; the UI must never make an ineligible night alternative
appear unavailable merely because a button disappeared. Desktop and mobile
must render the same canonical status after each receipt refresh.

### 9.6 Emergency decision confirmation sheet

On mobile, selecting any enabled human-review action opens a bottom sheet with
the selected action name as its heading. The sheet may scroll internally when
text is enlarged, but its Confirm/Cancel action row remains sticky above the
safe-area inset. The page behind it is inert until the sheet closes.

Confirmation labels must repeat the consequence; generic `Yes`, `OK`, or
`Confirm` alone are not allowed. Recommended label semantics are:

| Selected decision | Confirmation label |
| --- | --- |
| `approve_for_runtime_consideration` | `Confirm: submit for runtime consideration` |
| `reject_night_travel` | `Confirm: reject night travel` |
| `select_hold_or_bivy` | `Confirm: select hold / bivy` |
| `escalate_emergency` | `Confirm: escalate to Emergency review flow` |

The confirmation control is at least `56px` high. Cancel/Back remains at least
`48px × 48px` and must be visually distinct from Confirm. Neither color nor
button order may be the only distinction. The sheet must not auto-focus the
Confirm control; keyboard and assistive-technology focus starts on the sheet
heading and remains trapped within the sheet. Escape, Back, Cancel, or tapping
the explicit close control closes it without a write and returns focus to the
originating decision.

During submission, the sheet keeps the selected decision, consequence, and
packet state visible; it changes the Confirm label to a bounded
`Checking current evidence…` state and blocks duplicate activation. It must not
optimistically update Permission or show a success color before the server
returns the append-only receipt. Desktop uses the same two-step semantic
interaction in a dialog or side sheet and sends the same command payload.

### 9.7 Offline and reconnect presentation

Offline/degraded review keeps a non-dismissible connectivity banner above the
Decision view:

```text
Offline · cached packet · last validated {relative age}
Approval unavailable until online revalidation
```

The cached packet uses warning/unknown semantics, never verified-green.
`Approve for runtime consideration` remains visible and disabled with its
blocking explanation. Hold/bivy, Reject, and Escalate retain their large action
controls when a cached packet exists.

For an offline conservative choice, the confirmation sheet changes its final
label to `Save offline intent: {decision}` and states that Safety / Emergency
has not recorded it yet. Success closes the sheet into a persistent
`Pending sync` card containing the decision, relative creation age, packet ref,
and `Change decision` action. Changing it appends a superseding local intent;
the UI keeps the lineage available under Evidence.

During reconnect, the current decision and pending card remain visible beneath
`Revalidating before sync…`. The result presentation is explicit:

- `Recorded by Safety / Emergency` with canonical receipt ref;
- `Already recorded` with the resolved receipt ref; or
- `Not recorded after sync` with conflict reasons and `Review current packet`.

No result silently turns into approval. The same-device Permission mobile view
may mirror `Offline intent pending`, but only `Recorded by Safety / Emergency`
may enter its human-cause receipt path.

### 9.8 Freshness countdown and invalidation presentation

The Decision view places one freshness strip directly below packet status:

```text
Fresh · expires in {relative duration} · limited by {expiry_driver.gate_id}
Refresh due · expires in {relative duration} · refresh {gate/evidence}
Expired · decision unavailable · refresh packet
Invalidated · {plain-language cause} · review current packet
Freshness unknown · approval unavailable
```

The countdown is based on the last authoritative `server_now` offset and never
on device time as an authorization source. It updates visually, disables
approval when it reaches zero, and remains subordinate to server confirmation.
Assistive technology announces transitions such as `refresh_due`, `expired`,
or `invalidated`, not every countdown tick.

`expiry_driver` is visible by name on Decision and highlighted in the Gates
view. A `Refresh packet` control rebuilds the entire packet; it does not refresh
only the displayed countdown. If a replacement changes hashes or eligibility,
the confirmation sheet closes, clears the selected decision, and returns focus
to the new packet summary.

Permission shows the same eligibility-packet freshness and daily receipt-scope
state in its Safety tab and review-status chip. An expired evidence snapshot or
invalidated daily receipt remains inspectable in Evidence, but neither can
display `Approved for runtime consideration` as current. Offline mode keeps the
cached countdown for orientation only and prefixes it with
`Cached · not revalidated`.

### 9.9 Daily review presentation

Safety / Emergency places the current mission-day identity above the Decision
tabs:

```text
D2 · Daily Emergency Review
Day ends at: 清八岔 C2 · en route
2 of 3 alternatives reviewed · current evidence fresh
```

Only the current mission day is actionable. Previous days open read-only receipt
history; future days show pre-trip candidate rules and `Review when day starts`,
never a current approved/reviewed badge.

The Decision view lists the day's exact alternatives as large cards with
from/to, direction, maximum night duration, current eligibility, human
disposition, expiry driver, and next step. `Review today's alternatives` starts
a guided sequence but never bulk-confirms them: every enabled decision still
uses its own D-013 confirmation sheet and receipt.

The daily header distinguishes:

```text
Review not started
Partially reviewed
Reviewed · current evidence fresh
Reviewed · refresh evidence before consideration
Re-review required · {material change}
Day closed · receipts are history
```

An ordinary evidence refresh may change an alternative card to `Refresh
required` or `Currently ineligible` without erasing its daily human disposition.
If rebuilt facts remain inside the reviewed envelope, the card returns to
current without another human action. A new/unlisted alternative or envelope
change adds a visible `Review required` item and prevents the daily summary from
claiming full completion.

Permission's `Now` and `Safety` views show the same `D_n` daily state, reviewed
count, planned/effective day-end target, arrival/feasibility state, current
selected-alternative state, and link into that day's review. Calendar date and
clock may appear as metadata but never as a progress bar or automatic rollover.
After a verified planned-target arrival or emergency-bivy establishment, the UI
archives the prior day, clears any open confirmation selection, and presents
the next day as `Pending start`. Only a `MissionDayStartReceipt` makes that
day's review current.

### 9.10 Day-end and Emergency Bivy presentation

The current mission-day header always shows one resolved destination-first
statement:

```text
Planned day end: {target name} · {target kind}
State: En route | Arrival unconfirmed | Reached
```

The target name opens the shared map focused on its reviewed target geometry.
The UI must not say `day complete` from ETA, midnight, a long rest, stopped
movement, or a date change.

When feasibility becomes `at_risk`, Permission and Safety / Emergency show the
reasons and a large `Review day-end feasibility` action. When it becomes
`unreachable`, the first layer changes to:

```text
Cannot safely reach planned day end
Emergency bivy review required
```

Safety / Emergency also provides a large `Cannot reach today's planned end`
human-trigger action. It uses two-step confirmation, emits the typed trigger
receipt, and opens Emergency Bivy Review. Automatically detected unreachable
facts open the same review view but remain labelled `Scout/deterministic
feasibility · not a human report`.

Emergency Bivy Review lists candidate cards with target name, route relation,
terrain/threat gaps, water/weather/warmth/resource evidence, distance, map
focus, data quality, and `candidate_only` state. `Select hold / bivy` records the
reviewed selection but the daily header remains:

```text
Emergency bivy selected · establishment unconfirmed
Baseline day end not reached
```

Only an `EmergencyBivyEstablishedReceipt` changes the header to
`Day closed at emergency bivy`. The baseline and effective targets must then be
shown side by side, with the unfinished route carried into Remaining Mission.
This contingency close uses warning semantics rather than normal-completion
green and immediately exposes `Prepare next daily review`. The receipt may come
from an explicit on-site participant confirmation or the deterministic GNSS
arrival-dwell path defined by OD-016; neither mode attests that everyone is
asleep or safe.

### 9.11 Multi-day Shelter Hold presentation

When a hold is active, Safety / Emergency replaces the ordinary day-start card
with a persistent first-layer state:

```text
SHELTER HOLD ACTIVE
At: {confirmed hut / camp / bivy target}
Next mission day: D3 · pending start
Calendar hold: 3 days · audit only, no mission-day rollover
Reason: {extreme weather / threat / reviewed human cause}
```

The mobile `Decision` view prioritizes current shelter safety, weather/threat
trend, team condition, water/food/fuel/power/warmth, communication, and the next
required review. Map and Evidence remain secondary tabs. The UI provides large
controls for `Continue shelter hold`, `Review departure readiness`,
`Relocate / emergency bivy`, and `Escalate emergency` when their preconditions
permit them.

There is no countdown that forces departure and no calendar-day progress bar.
Elapsed time is shown only because resources and downstream itinerary pressure
change. Each evidence refresh updates `Hold remains required`, `Refresh
required`, or `Departure review candidate`; it never starts the next day.

`Review departure readiness` opens a decision-first sheet showing fresh
weather/threat, route, team, equipment, resource reserve, communication, and
pending day-plan evidence. A Scout message may say `Conditions improved ·
departure review available`, but only the resulting Safety / Emergency
`MissionDayStartReceipt` changes the header to:

```text
Shelter hold closed
D3 activated · Daily Emergency Review required/current
```

If departure review fails or expires, the hold stays active with the exact
blocker. Offline mode keeps Resume disabled and clearly distinguishes a locally
queued conservative intent from a server-recorded hold/start receipt.

### 9.12 Compact leader departure checklist

`Review departure readiness` opens a full-width mobile sheet with this first
layer:

```text
DEPARTURE REVIEW · D3
Scout suggestion: Continue shelter hold · weather warning remains
2 pass · 2 leader checks · 1 blocked · 1 unknown

Weather & threats              BLOCKED       Auto
Route & navigation             PASS          Hybrid
Team                           CHECK          Leader
Equipment & power              CHECK          Hybrid
Supplies & shelter fallback    PASS          Hybrid
Communication & next-day plan  UNKNOWN       Hybrid
```

There are never more than six top-level rows. Every row uses text plus icon and
source-mode badge, one short reason, and a large expand control for source,
freshness, uncertainty, thresholds, and evidence refs. Automatic values are
read-only; the leader is never asked to retype weather, route progress, battery,
or other available facts.

Only explicit field attestations render checkboxes. Each label states what the
leader is confirming, uses at least a `48px × 48px` target, and defaults
unchecked whenever checklist/day hashes change. Expanding or acknowledging an
automatic row does not convert it to pass.

The Scout recommendation card remains visually separate from the deterministic
gate summary and begins with `Scout suggestion`. It shows source age and gaps
and never receives the verified-green treatment used for a completed human
review. Missing weather or other automatic evidence renders
`Refresh evidence`, not a departure suggestion.

The sticky final action is:

```text
Continue shelter hold
Confirm departure and start D3
```

`Confirm departure` remains visible but disabled with the first blocker until
all six rows and required attestations pass. When enabled, it opens the common
two-step consequence sheet showing the exact pending day, route start, plan
hash, remaining risks, and that the command records a start receipt rather than
declaring the route safe.

### 9.13 Field-condition conflict reporting

Every Auto or Hybrid checklist row includes a large `現場狀況不同` control next
to its evidence expansion. The first tap opens a bottom sheet; it performs no
write and preserves the originating row context. The sheet offers four large,
consequence-labelled submit actions:

```text
實際狀況更差 · 暫停出發
資料過期或錯誤 · 重新驗證
定位／路線不符 · 暫停出發
設備讀值不符 · 重新驗證
```

Each action has at least a `56px` height; all other controls meet the shared
`48px × 48px` target. An optional short-note field is available but never
required. Choosing one category is the second deliberate action and submits
the report directly; the UI does not add a third generic Confirm step.

After a successful report, the row shows `領隊回報衝突 · 尚未解除`, the Scout
card shows `暫停 · 以現場衝突為優先`, and `Confirm departure and start D_n`
stays disabled. The first layer offers only conservative next steps such as
`更新資料`, `繼續修整`, `進入 Safety / Emergency review`, and `升級
Emergency`. A later automatic refresh may appear beside the old evidence but
cannot remove the conflict banner or restore departure readiness.

Resolution presents the original field report and the new evidence side by
side, identifies any remaining uncertainty, and requires explicit Safety /
Emergency leader confirmation before appending the resolution receipt. Desktop
and mobile use the same canonical conflict state. Focus returns to the
originating row after cancel or submit; status is announced without relying on
color. The `390px` portrait and `200%` text proofs must keep every category,
optional note, current blocker, and conservative next action readable and
operable without page-level horizontal scrolling.

### 9.14 Individual action state and arrival-dwell completion

Individual activity appears as a compact privacy-safe activity strip, not as a
leader checklist:

```text
Personal activity records
3 route-travel ended · 1 moving inside camp · 1 unknown
No claim that everyone is asleep or safe
```

An individual opens only their own timeline of semantic transitions and may
choose `Correct my activity state`. Broad Dashboard views expose counts,
freshness, contradictions, and pseudonymous refs only. They do not expose raw
IMU/health streams or ask the leader to mark each person resting, lying, or
sleeping.

After deterministic target entry, the first-layer day-end card becomes:

```text
GPS ARRIVAL CONFIRMED · {exact target}
Completing D2 in 09:43
Route travel ended · ordinary camp movement allowed

[Complete now]
[Wrong target / still travelling]
```

The countdown uses the shared `22px` primary-state and `56px` action treatment,
survives navigation away from the sheet, and exposes the reviewed target,
arrival-zone ref, GNSS confidence, dwell rule, supporting personal-state
summary, and any contradiction. It never counts down from midnight, ETA, sleep,
or stationary state alone.

`Complete now` is available to an authorized on-site participant, not only the
leader, and confirms only `Arrived` or `Camp established` at the exact selected
target. `Wrong target / still travelling` cancels the automatic candidate and
records why without changing the baseline target. Unexpected separation within
that movement group, target mismatch, continued route travel, or zone exit stops
the countdown and links to Safety / Emergency; an unknown personal sensor state
remains visible without creating a per-person leader attestation.

After automatic or manual close, the card shows the receipt mode and:

```text
D2 completed at {target}
Shelter Hold active
D3 pending start
```

Offline completion adds `Pending sync` without hiding the local result. A
`Day-end identification wrong` action opens the append-only correction flow.
At `390px` and `200%` text, the countdown, target, evidence status, both actions,
personal-state disclaimer, completion mode, and pending-next-day state remain
readable without horizontal scrolling.

### 9.15 Movement-group day and start presentation

When more than one reviewed movement group exists, the mobile first layer uses
a two-option switcher:

```text
My group | All groups
```

`My group` remains the landing view and keeps the current decision, exact target,
arrival/dwell state, Shelter Hold, checklist blocker, and next action above the
fold. Every receipt and action label repeats the group name, for example
`Complete Summit group D2` or `Start Base group D3`.

`All groups` is a compact vertical card list rather than a comparison table:

```text
EXPEDITION · PARTIALLY CLOSED

Summit group   D3 active          Next: ridge segment
Base group     D2 Shelter Hold    Next: review weather
Rear group     D2 en route        Next: arrive at C2
```

Each card shows planned-versus-unexpected group status, current mission day,
target, arrival/hold/start state, data freshness, bounded contact state, first
blocker, and one primary next action. It never combines receipts into one team
green badge. Other-group raw personal activity and exact coordinates remain
hidden; authorized users may open bounded group evidence.

Planned grouping uses neutral information treatment. `Unexpected separation`
uses Safety / Emergency warning semantics and stays pinned above both views; it
cannot be dismissed by naming the detected cluster as a new group. An explicit
shared regroup dependency appears on every affected group card and explains why
otherwise-ready next-day start is blocked.

Reunion shows `Review group merge`; the confirmation sheet compares source
group days, targets, holds, pending actions, membership revisions, and the new
merged context. It creates a merge receipt and preserves all prior cards in
history. At `390px` and `200%` text, group switching, every status/action label,
unexpected-separation warning, and merge consequences remain readable and
operable without horizontal page scrolling.

### 9.16 Communication-window and contact-loss presentation

Each movement-group card shows one plain-language contact state, never a generic
continuous-online green dot:

```text
EXPECTED BLACKOUT
Scope: {reviewed route segment}
Next check-in: {target or event}
Latest window: {effective deadline}
Last verified receipt: {relative age}
```

The card keeps Baseline and Effective window values separate and names the
event/receipt that changed the effective value. It also states whether the view
is local or remote, for example `Local device state · not known to base` or
`Remote view · last verified check-in only`.

When the communication window opens, the first layer changes to `Check-in due`
and exposes the next available check-in action/handoff without claiming that a
tap sends anything. At the authoritative deadline it changes to:

```text
CONTACT OVERDUE · REVIEW REQUIRED
No verified check-in receipt
This is not yet an emergency declaration
```

The view shows route-scope match, progress freshness, last receipt, device/power
status, rendezvous state, and any compound escalation evidence. Scout advice is
visually separate and bounded to the OD-018 vocabulary. The primary actions are
`Continue monitoring`, `Review rendezvous`, `Open contact-loss review`, and,
only when eligible, `Open Emergency Call Out`; none imply transmission.

Expected blackout uses neutral information treatment. Overdue uses warning
semantics; compound escalation or a Safety / Emergency trigger uses critical
semantics. State always includes text and icon, never color alone. Contact
restoration shows the new verified receipt while preserving `Previously
overdue` history.

`All groups` displays each group's contact state and next window without a
false all-team online badge. At `390px` and `200%` text, group identity, local/
remote viewpoint, next target, deadline, last verified receipt, overdue reason,
bounded actions, and no-delivery warning remain readable without horizontal
page scrolling.

## 10. Required Visual Semantics

- Always show `Baseline` and `Effective after event N` as separate values.
- Show consumed discretionary time as a delta, not by silently replacing the
  baseline duration.
- Give protected reserves a distinct visual treatment and never render them as
  spendable progress bars.
- Show an adjustment-policy badge on every remaining-plan node. Render
  `auto_reduce` as reducible range, `protected_floor` with a fixed floor marker,
  and `review_only` as a separate review-required alternative rather than an
  automatic delta.
- Render `GO`, `CONDITIONAL_GO`, `CHANGE_PLAN`, `DELAY`, `NO_GO`, and
  `ESCALATE` from the canonical decision vocabulary.
- Render the Section 16 first layer above the fold: decision, limit, reason,
  and next step.
- Keep uncertainty, residual risk, conditions, alternatives, cost, and source
  refs in an expandable second layer.
- Use route/segment/CP target ids to focus the supporting map. Generic sampled
  checkpoints are not permission evidence.
- Never use static example numbers in an operational-looking state.
- Missing artifacts, no runtime session, stale evidence, and conflicting event
  order must each have a distinct, fail-closed empty state.
- Candidate, replay, runtime-observer, and runtime-authority states must never
  share an ambiguous green status.
- Keep Safety / Emergency trigger state visually separate from Scout advice.
  The trigger is a locked, higher-priority constraint; the recommendation is a
  candidate explanation/projection and must never appear to override it.
- Show weather and movement/progress fact badges with source lineage. Do not
  expose raw IMU, raw track, raw GPX, exact coordinates, or precise timestamps.

## 11. Canonical Action Vocabulary

The page must get supported action ids from the typed model/projection. Display
labels may be translated, but ids must not use UI-only aliases such as `team`
or `rain`.

The spec and implementation must reconcile the current vocabulary drift around
`tripod` and `wait_teammate` before the API is declared stable.

## 12. Implementation Slices

### Slice 0 — Baseline authoring capability `[x] candidate/shadow`

- Add typed itinerary-intent, Mission Baseline candidate, patch, validation,
  and reviewed-baseline contracts.
- Implement deterministic capture/segmentation for `D0...Dn`, unresolved-name
  handling, coordinate-CRS confirmation, and source hashing.
- Reuse GPX import and route-axis evidence, adding continuity/order admission
  before automatic itinerary generation.
- Add an explicit, hash-bound Scout generation/conversation path that produces
  proposed patches only.
- Prove one human-seeded draft and one reference-GPX-seeded draft converge to
  the same candidate schema without becoming runtime truth.

### Slice A — Typed replay capability `[x] candidate/shadow`

- Add typed action-event and Forward Constraint Projection models.
- Implement a deterministic forward projector.
- Prove one replay: a six-minute rest permission, sixteen-minute observed rest,
  ten-minute debt, discretionary future contraction, protected reserves held,
  and a fail-closed alternative when debt cannot be repaid.

### Slice B — Read-only Dashboard projection `[x] candidate/shadow`

- Add the bounded GET contract.
- Resolve refs from the selected project/session only.
- Validate artifact kind, schema, hash lineage, sequence, data quality, privacy,
  and candidate/runtime boundaries.
- Add missing, stale, conflict, and baseline-only states.

### Slice C — Workbench UI `[x] candidate/shadow`

- Replace the static selector and hard-coded budget bars.
- Add a dedicated permission data scope.
- Render current decision, remaining-plan comparison, budget ledger, map focus,
  and event/evidence ledger.
- Keep all ordinary Dashboard controls read-only or simulation-only.

### Slice D — Shadow runtime integration `[x] candidate/shadow`

- Feed replay action events into the existing delay/darkness/reducer path.
- Persist append-only session artifacts and deterministic projection hashes.
- Demonstrate weather-caused and operator-caused overruns with different causal
  evidence but the same forward-only invariant.

### Future slice — Runtime authority `[ ] out of scope`

- Connect resident observers and explicit authority mode.
- Keep field approval and emergency interaction separate from the full Admin
  workbench.
- Apply Productization Mode safety, privacy, hardware, transport, and field UX
  gates before any production claim.

### Cross-feature slice — Safety / Emergency daily review `[x] candidate/shadow`

- Extend the existing Safety / Emergency Dashboard route with the dedicated
  Daily Emergency Review view; do not create an unrelated top-level product.
- Add the same review kind to the field-oriented Emergency mobile surface.
- Implement one current mission-day session, exact per-alternative packet
  projection, server-side revalidation, append-only review receipts and daily
  summary, idempotency/stale-packet rejection, generation, and invalidation.
- Return the typed Safety / Emergency trigger receipt to the Permission read
  projection and recompute forward constraints without duplicating time debt.
- Prove approve-for-consideration, reject, hold/bivy, escalate, stale packet,
  hash mismatch, new-trigger invalidation, daily rollover, prior/future-day
  read-only/preview state, inside-envelope refresh, same-day re-review, and
  no-authority boundary cases.
- Add resolved planned-day-end targets, deterministic feasibility/arrival
  receipts, the human cannot-reach trigger, Emergency Bivy Review, establishment
  receipt, immutable effective-end substitution, and carried-forward remainder.
- Prove no midnight/rest/date rollover, no day close on selection alone,
  planned close, contingency close, unconfirmed arrival/establishment, and
  baseline-target preservation.
- Add on-device individual activity transition receipts, self-correction,
  privacy-safe aggregation, reviewed arrival-zone GNSS confirmation, and the
  monotonic 600-second automatic day-close dwell.
- Prove that manual on-site and automatic GNSS-dwell paths converge on one
  idempotent day-close result; ordinary camp movement does not reset it,
  positive exit/continued-route/unexpected same-group separation evidence does,
  and no leader sleep roll call or team-safety claim is created.
- Add explicit movement-group formation/membership/merge receipts, per-group
  day/arrival/hold/start state, shared-dependency scoping, and the read-only
  expedition roll-up.
- Prove front/rear and summit/base fixtures can diverge across mission-day
  states without blocking one another, while unexpected separation remains a
  Safety / Emergency exception and never becomes an inferred group.
- Add per-group Communication Window Policy, route-scoped expected blackout,
  authoritative overdue reduction, local-versus-remote knowledge, verified
  check-in receipt, and contact-loss review.
- Prove known blackout does not require heartbeats or trigger an alarm, overdue
  remains distinct from emergency escalation, policy cannot be extended
  retroactively, and transport attempts never impersonate acknowledgement.
- Add calendar-neutral Shelter Hold intervals, current shelter/resource review,
  pending next-day state, departure review, and MissionDayStartReceipt.
- Prove a three-calendar-day extreme-weather hold consumes no mission-day label,
  cannot auto-resume, keeps offline Resume disabled, and activates the next day
  only after a fresh explicit departure review.
- Implement the six-row Leader Departure Checklist, allow-listed automatic fact
  adapters, deterministic gate result, separate Scout recommendation, leader
  attestations, and hash-bound final confirmation.
- Prove automatic weather prefill and refresh, missing/stale/conflicting fact
  failure, no manual re-entry of available data, no Scout checkbox/override, and
  compact `390px` progressive disclosure.
- Add `Field condition differs` to every Auto/Hybrid row, with four fixed
  categories, optional short note, typed Safety / Emergency conflict receipt,
  fail-closed row state, and suspended Scout suggestion.
- Prove that automatic refresh cannot silently clear a leader conflict, that
  resolution requires fresh evidence plus a separate receipt, and that an
  offline conflict intent blocks local departure without becoming approval.
- Keep the prototype candidate/shadow-only until a separately reviewed runtime
  authority consumes the receipt.

### Implemented evidence surface

- `scout_contextual_permission_workbench.py` owns the typed, server-reduced,
  append-only aggregate, baseline/rules binding, day/group state, offline sync,
  and no-authority receipts.
- `scout_contextual_permission_workbench_api.py` exposes the bounded Permission
  read model and shared Safety / Emergency command surface.
- `docs/admin/scout-dashboard-v0.1.html` renders the established Dashboard
  visual language for Permission and the dedicated Daily Emergency Review.
- `pretrip_contextual_permission_collection.py` emits candidate-only Section 8
  rules; runtime use requires a separately reviewed, baseline-bound v2 rules
  artifact.
- Focused model, API, state-command, Dashboard, and collection tests are the
  executable acceptance surface. Browser evidence uses the same local API
  entrypoint and selected-project fixture.

## 13. Focused Acceptance Criteria

1. Direct Permission navigation loads the selected project projection.
2. The page contains no hard-coded operational budget values.
3. The baseline rules and graph are hash-bound and never overwritten.
4. A completed/observed event changes only future plan nodes.
5. Protected reserves cannot be spent by the automatic projector.
6. Negative daylight margin does not automatically produce night travel.
7. Missing required evidence produces a conservative decision and visible gap.
8. Current decision output matches `ContextualPermission` and Section 16.
9. Every adjustment links to baseline and event evidence refs.
10. Map focus uses actual affected target ids.
11. Candidate/replay/runtime-observer/authority states remain visibly distinct.
12. Focused model, projector, endpoint, Dashboard, and browser tests pass on a
    real fixture or faithful replay.
13. The page reuses the Dashboard truth strip, Six Axis tabs, wide-frame shell,
    shared status tokens, map controller, evidence interaction, focus treatment,
    and responsive breakpoint grammar without adding a parallel visual theme.
14. Action identity alone never authorizes contraction; each affected plan node
    exposes a reviewed effective adjustment policy and lineage.
15. `auto_reduce` cannot cross its minimum, `protected_floor` cannot consume its
    floor, and `review_only` never produces an automatic plan mutation.
16. A generic Dashboard/operator input cannot become human-driven cause
    evidence; only a verified Safety / Emergency trigger receipt is accepted.
17. Weather and IMU/PDR/GNSS paths expose normalized facts and lineage, not raw
    private payloads, and each action overrun is counted once.
18. An incompatible Scout pace recommendation is suspended when a later Safety /
    Emergency trigger is present.
19. Human text and reference GPX both produce the same Mission Baseline schema
    with original seed mode and field-level lineage retained.
20. Text-only unresolved route names, unknown coordinate CRS, GPX continuity
    failures, and unreviewed branch semantics cannot become a graph-backed
    review-ready baseline.
21. Historical GPX timestamps do not silently define current day splits or
    camp timing, and Scout conversation applies only visible hash-bound patches.
22. Baseline, Replay, and Live Observer never mix sessions or switch modes
    implicitly; Baseline remains the immutable comparison.
23. Preview, generation, conversation, patch proposal, validation, Replay, Live
    Observer, and simulation report `writesPerformed=false`.
24. Saving a candidate or accepted patch creates a new immutable version bound
    to its base/source hashes; stale-base and reused-idempotency conflicts fail.
25. Reviewed baseline acceptance requires explicit human confirmation and all
    route-critical gates, while still declaring no departure approval, Final
    MissionGraph, active-runtime update, safety call, or runtime truth.
26. Accepting a new baseline marks mismatched dependent permission/ETA artifacts
    stale instead of silently reusing them.
27. Night-alternative eligibility is an AND gate and exposes only
    `not_assessed`, `ineligible`, or `eligible_for_human_review`; delay never
    increases eligibility.
28. The Permission page has no night-travel approval control and links to the
    dedicated Safety / Emergency review view.
29. Safety / Emergency rejects approval of ineligible, stale, mismatched, or
    invalidated packets and writes one idempotent append-only receipt per valid
    decision.
30. The desktop and mobile Emergency review surfaces share one packet/receipt
    source of truth, and prototype receipts declare no runtime authorization,
    Phase 1 mutation, safety API call, or outbound action.
31. A later incompatible Safety / Emergency trigger or material day/route/
    envelope/sequence change invalidates the affected daily review before
    Permission can use it; ordinary evidence refresh first rebuilds eligibility.
32. At `<=760px`, Permission defaults to `Now` and exposes `Now`, `Remaining`,
    `Safety`, and `Evidence` without page-level horizontal scrolling.
33. Mobile Permission retains complete inspection, map/evidence/receipt review,
    refresh, and Safety / Emergency handoff; desktop-only authoring, promotion,
    and simulation tasks are explicitly labelled `Continue on desktop`.
34. Safety-significant mobile state and the required next action are reachable
    within two deliberate taps and never depend only on hover, color, or hidden
    clipped content.
35. Mobile body/control text is at least `16px`, the primary decision is at
    least `22px`, primary actions are at least `56px` high, and all remaining
    controls have at least a `48px × 48px` touch target.
36. The Safety / Emergency mobile entry view is `Decision` and retains all four
    bounded review decisions, with every disabled action remaining visible and
    explaining its blocker.
37. A focused `390px` portrait browser proof and `200%` text enlargement show
    no hidden decision, truncated action consequence, overlapping controls, or
    inaccessible status.
38. Desktop and mobile render the same canonical packet/receipt state after a
    decision, invalidation, expiry, or refresh.
39. The first tap on any Emergency review decision only opens its confirmation
    sheet and performs no write, runtime action, safety call, or outbound action.
40. All four decisions require a second explicit, consequence-labelled Confirm
    action; no generic confirmation, long-press, swipe, timed hold, preselection,
    or mandatory typed justification is used.
41. The confirmation sheet shows the selected decision, exact alternative,
    packet validity, consequence, next step, expiry/freshness, and no-authority
    boundary while keeping Confirm/Cancel reachable above the safe area.
42. Confirm revalidates the current packet server-side before append and blocks
    duplicate activation with the same idempotency contract as the API.
43. A rejected confirmation says `Decision not recorded`, shows the exact stale,
    expired, ineligible, mismatched, or already-decided blocker, and does not
    optimistically update Permission.
44. Confirming `escalate_emergency` records the review decision and opens the
    separate Emergency Call Out flow without inheriting outbound approval or
    claiming delivery.
45. Keyboard, Back, Escape, Cancel, screen-reader focus, and `200%` text paths
    can enter and leave the confirmation sheet without accidental submission or
    losing the originating decision context.
46. Offline/degraded mode keeps the cached packet inspectable under a persistent
    warning showing relative age and last validation state, never verified-green.
47. Offline `approve_for_runtime_consideration` remains visible, disabled, and
    labelled `Online revalidation required`.
48. Offline Hold/bivy, Reject, and Escalate use two-step confirmation and create
    only a privacy-bounded, append-only `OfflineEmergencyReviewIntent` with
    `pending_sync=true` and every authority/effect flag false.
49. With no cached packet, no night-alternative decision is available; the
    separate general Emergency Call Out entry remains visible without a delivery
    claim.
50. Reconnect sync rebuilds current server truth and returns only
    `receipt_appended`, `already_recorded`, or `rejected_sync_audit`; it never
    accepts an offline approval or silently drops local history.
51. A changed offline choice appends supersession lineage, and sync is
    idempotent across retries without creating duplicate receipts.
52. Permission may display `Offline intent pending` locally but cannot accept it
    as human-driven evidence or recompute forward constraints before a canonical
    Safety / Emergency receipt exists.
53. Packet expiry is the earliest deterministic `valid_until` among every
    required eligibility input and applicable reviewed policy/session deadline;
    no model or UI invents a fixed default timeout.
54. A required input without `valid_until` produces `freshness_unknown`, makes
    the packet ineligible, and disables approval.
55. Packet and decision responses expose authoritative `server_now`,
    `expires_at`, `freshness_state`, `expiry_driver`, bounded freshness inputs,
    and invalidation causes without leaking raw provider or sensor payloads.
56. Expiring an eligibility packet blocks current consideration but does not
    erase a still-valid daily human disposition; completing review never extends
    evidence validity, and fresh evidence must pass again before use.
57. New incompatible triggers, mission-day/route/alternative envelope changes,
    policy or stable-lineage hashes, gate threshold breaches, replacement,
    cancellation, or supersession invalidate the applicable daily review.
    Volatile-evidence changes invalidate/rebuild the current eligibility packet
    and require human re-review only when they cross the reviewed envelope.
58. Device time is presentation-only; missing current server time or expiry
    driver shows `Freshness unknown` and disables approval.
59. Confirmation revalidates once more and records no decision when expiry or
    invalidation occurs while the sheet is open; a replacement packet requires
    a new human inspection and selection.
60. Decision, Gates, Permission Safety, receipt, offline-cache, `200%` text, and
    assistive-technology views render the same freshness state, countdown basis,
    expiry driver, and explicit next action without announcing every timer tick.
61. Safety / Emergency creates one current `DailyEmergencyReviewSession` for a
    concrete mission-day instance and groups every known exact alternative under
    it without bulk-approving them.
62. Each reviewed alternative receives its own append-only receipt bound to
    mission day, review generation, exact envelope, packet snapshot, and source
    lineage; the daily summary derives from those records.
63. A current-day receipt covers neither the whole expedition nor any future
    day, unlisted branch, changed geometry/direction, or changed policy envelope.
64. At destination-driven day close, prior receipts become read-only history and
    the next day stays `pending_day_start`; only a MissionDayStartReceipt makes
    its daily review current, even when route and personnel are unchanged.
65. A reviewed same-day alternative may satisfy the human prerequisite across
    repeated fresh deterministic checks; it is not a single-use attempt receipt
    and never replaces current gate eligibility or runtime authority.
66. Routine automatic evidence refresh within the reviewed envelope does not
    force another human action; an out-of-envelope fact, new alternative, or
    material Safety / Emergency change moves affected items to re-review.
67. Same-day re-review increments `review_generation` and appends superseding
    receipts without rewriting the earlier daily audit trail.
68. Desktop, mobile, and Permission show the same `D_n`, daily reviewed count,
    current evidence state, affected alternatives, and day-closed transition.
69. Every reviewed baseline mission day has one resolved
    `planned_day_end_target_ref/hash`; unresolved free text cannot close a day.
70. Midnight, calendar-date change, elapsed duration, long rest, sleep, or
    stationary movement never closes or starts a mission day.
71. Normal day close requires a valid `DayEndArrivalReceipt` for the exact
    planned target; an arrival candidate or selected map point is insufficient.
72. A human cannot-reach report is accepted only from a typed Safety / Emergency
    trigger receipt, while automatic feasibility facts preserve their distinct
    weather/movement/terrain lineage.
73. `day_end_unreachable` foregrounds Emergency Bivy Review and conservative
    forward constraints without automatically choosing a site, mutating Phase 1,
    controlling hardware, or sending an alert.
74. Selecting hold/bivy does not close the day; contingency close requires an
    `EmergencyBivyEstablishedReceipt` for the reviewed effective target.
75. Effective day-end substitution preserves the baseline target as missed,
    records `baseline_day_end_reached=false`, and carries unfinished route/time/
    risk consequences forward.
76. Without planned-target arrival or bivy establishment, the current day stays
    open and no next day may appear current.
77. Closing a day archives its receipts but leaves the next baseline day
    `pending_day_start`; closure and next-day start are separate events.
78. A Shelter Hold may span multiple calendar dates without consuming or
    incrementing a mission-day label, including a three-day extreme-weather hold.
79. Active hold refreshes weather/threat, shelter, team, resource,
    communication, and exit-route evidence while treating elapsed calendar time
    only as audit/resource pressure.
80. Improved weather produces at most a departure-review candidate; Scout,
    clocks, or sensors cannot automatically close the hold or start movement.
81. Only a fresh, explicit Safety / Emergency `MissionDayStartReceipt` closes
    the hold and activates the exact pending day-plan hash and daily review.
82. Offline Resume/start remains disabled; conservative Continue hold,
    relocation review, and escalation can create pending intents without
    pretending that departure was recorded.
83. Mobile and desktop show the same planned/effective day-end, feasibility,
    arrival/establishment, Shelter Hold, pending-day, and start-receipt states
    with large controls and explicit blockers.
84. Departure review exposes exactly six top-level checklist rows with
    progressive evidence disclosure rather than a long ungrouped form.
85. Every row declares `scout_auto`, `leader_attestation`, or `hybrid` source
    mode and one of pass, blocked, unknown, or leader-check-required.
86. Authorized weather/threat/route/device/workspace facts prefill automatically
    with source, freshness, uncertainty, and gaps; the leader does not re-enter
    available values or raw payloads.
87. Missing, stale, failed, or conflicting automatic facts fail to unknown/
    blocked and cannot receive an optimistic default or leader checkbox waiver.
88. Scout recommendation is produced only after normalized facts and
    deterministic gates, uses the bounded recommendation vocabulary, and cannot
    say `safe to go`, mark attestations, close the hold, or start the day.
89. Only field facts Scout cannot establish require concise leader
    attestations, and checklist/day hash change clears those checks.
90. Final departure is an AND gate: six current rows, all leader attestations,
    no incompatible Safety / Emergency trigger, matching day/review hashes, and
    two-step leader confirmation must all pass.
91. The final server command rebuilds current gates and reports
    `Mission day not started` with row blockers on any mismatch; UI state cannot
    manufacture a start receipt.
92. Automatic fact refresh never modifies leader attestations, performs an
    outbound effect, or changes runtime/Phase 1 truth.
93. At `390px` and `200%` text, the summary, six row states, expand controls,
    required checkboxes, first blocker, Scout-suggestion boundary, and sticky
    final action remain readable and operable.
94. A three-day extreme-weather fixture changes from Continue hold to Departure
    review ready only after fresh automatic evidence; the pending day activates
    only after the complete leader checklist and MissionDayStartReceipt.
95. Every `scout_auto` and `hybrid` departure-checklist row exposes a prominent
    `Field condition differs` action; leader-only rows do not impersonate an
    automatic-fact conflict path.
96. Reporting uses one no-write opening tap and one consequence-labelled submit
    category; the four fixed categories are complete, the short note is
    optional, and no generic third confirmation is added.
97. A valid report appends one idempotent, privacy-bounded
    `SafetyEmergencyFieldConflictReceipt` with checklist, row, fact, sequence,
    reporter, and source lineage while retaining all no-authority flags.
98. An open conflict immediately makes the row blocked or unknown, sets
    `can_confirm_departure=false`, disables mission-day start, and suspends any
    `departure_review_ready` Scout suggestion.
99. Later automatic evidence may be shown but cannot silently clear the field
    conflict, hide its audit banner, or restore a pass state.
100. Resolution requires fresh affected evidence, deterministic gate rebuild,
    explicit Safety / Emergency leader review, and a separate append-only
    resolution receipt; manual assertion alone cannot force pass.
101. An offline field-conflict intent is encrypted and pending, blocks local
    departure immediately, syncs idempotently, and never enables departure on
    append or rejection.
102. Permission, Safety / Emergency desktop, and Safety / Emergency mobile show
    the same open/resolved/escalated conflict, blocker, receipts, and next step.
103. At `390px` and `200%` text, the four conflict categories, optional note,
    receipt state, conservative actions, focus flow, and screen-reader status
    remain usable without horizontal page scrolling.
104. Resting, lying, sleeping, resumed movement, and unknown are recorded as
    privacy-bounded per-individual activity transitions; the leader cannot edit
    or attest those personal records for the group.
105. Raw IMU, PDR, health, and exact private location streams remain outside the
    Dashboard projection; group views expose only semantic state counts,
    confidence/freshness, contradictions, and bounded refs.
106. Manual `Arrived` or `Camp established` confirmation is available to an
    authorized on-site participant and confirms only the exact target/site, not
    that every participant is resting, asleep, healthy, or safe.
107. Automatic close starts only after fresh GNSS confirms the reviewed arrival
    zone with matching route progress and then completes the deterministic
    600-second monotonic dwell; clock date, ETA, sleep, or stationary state alone
    cannot start it.
108. Resting/lying/sleeping support route-travel termination and normal in-camp
    movement is neutral, while positive zone exit, continued route travel,
    target mismatch, or unexpected separation within that movement group
    cancels or blocks automatic close.
109. Missing individual activity remains visibly unknown without forcing a
    leader sleep roll call or allowing the UI to claim that person is safe.
110. Manual and automatic modes converge idempotently on one
    `DayEndArrivalReceipt` or selected-target
    `EmergencyBivyEstablishedReceipt`, with `confirmation_mode` and evidence
    lineage visible.
111. Day close immediately activates/continues Shelter Hold and leaves the next
    day `pending_day_start`; it never starts movement, mutates Phase 1, or
    performs an outbound action.
112. Mobile shows exact target, GNSS confidence, dwell countdown, `Complete now`,
    and `Wrong target / still travelling` without a per-person leader checklist.
113. A resident offline observation service may show
    `D_n completed · pending sync`; synchronization cannot start the next day or
    silently discard a conflicting receipt.
114. A wrong automatic close is corrected by an append-only
    `DayEndCloseCorrectionReceipt`; the original close and correction lineage
    remain auditable.
115. Focused fixtures prove planned-target manual close, automatic 600-second
    close, selected-bivy close, in-camp movement, route resumption, zone exit,
    member separation, missing personal data, offline sync, and correction.
116. A movement group exists only from a reviewed baseline definition or an
    append-only Safety / Emergency formation receipt; device distance, pace,
    missing data, or Scout inference cannot create one.
117. Every group has a versioned membership hash and independently owns its
    current day, target, arrival/dwell, day-close, Shelter Hold, departure
    review, daily review, and MissionDayStartReceipt state.
118. Personal activity and all group receipts bind the membership revision
    current at their event sequence and cannot be reused by another group.
119. One group's planned or contingency close and next-day start do not close,
    start, invalidate, or block another group; the expedition roll-up may remain
    normally `partially_closed`.
120. Cross-group blocking requires an explicit reviewed shared dependency or a
    multi-group Safety / Emergency constraint with matching scoped hashes.
121. Unexpected physical separation without a formation receipt remains a
    prominent Safety / Emergency exception and cannot be relabelled
    automatically as an intentional group.
122. Mobile defaults to `My group`, keeps `All groups` one tap away, repeats the
    affected group on every action, and never collapses group receipts into one
    misleading all-team status.
123. Membership changes and reunion append revision/merge receipts; different
    day or route contexts require reconciliation and prior histories are never
    rewritten.
124. Offline group formation or membership revision remains hash-bound and
    pending sync, while sync conflict cannot silently discard it or create a
    runtime/outbound effect.
125. Focused fixtures prove two planned groups at different day/hold/start
    states, explicit shared regroup blocking, unexpected separation, membership
    revision, merge reconciliation, offline sync, and mobile `390px`/`200%`
    rendering.
126. Every movement group has a reviewed route-scoped Communication Window
    Policy; no fixed heartbeat, continuous online state, or recurring outbound
    ping is required.
127. `expected_blackout` is available only while group progress matches the
    reviewed blackout scope and the policy/window hashes are current; route
    deviation or unexpected silence cannot inherit that label.
128. The first layer exposes the next check-in target/event, baseline and
    effective latest windows, the adjustment receipt, and last verified group
    check-in.
129. Only reviewed append-only forward events may derive an allowed effective
    window; Scout/client changes and retroactive revisions after overdue are
    rejected.
130. At the authoritative effective deadline, absence of a verified receipt
    deterministically creates `contact_overdue` and opens review without
    declaring an emergency or human cause.
131. Emergency escalation requires a typed Safety / Emergency trigger or
    reviewed compound evidence; missed contact alone never calls, sends,
    mutates Phase 1, or proves a group is missing.
132. A check-in becomes verified only through an allow-listed, correlated remote
    acknowledgement; queued, attempted, connected, or local-send state cannot
    satisfy the window.
133. Local and remote observed contact states remain separate during blackout,
    and neither surface claims that unsynchronized local evidence was received.
134. Contact restoration and synchronization preserve prior expected-blackout,
    overdue, review, and receipt history rather than erasing it.
135. Communication and check-in receipts are movement-group scoped; one group
    cannot satisfy or revise another group's window.
136. Mobile and desktop show the same group, route scope, viewpoint, next target,
    deadline driver, last receipt, overdue/compound state, and bounded actions
    without a false all-team online badge.
137. Focused fixtures prove expected blackout, check-in due, on-time verified
    receipt, overdue without escalation, compound escalation candidate,
    retroactive-revision rejection, transport-attempt rejection, restored
    contact, and `390px`/`200%` rendering.

## 14. Resolved Decision Record

The scoped Permission / Contextual Permissioning discussion ends at OD-018.
OD-001 through OD-018 are resolved; there is no active decision queue for this
feature. Physical inventory ownership, allocation, custody, and inter-group
resource transfer belong to a separate expedition logistics/resource-management
specification and must not be pulled into this workbench.

| ID | Status | Decision |
| --- | --- | --- |
| OD-001 | RESOLVED | Remaining Mission Projection is primary; Current Decision is the top summary; Map is supporting evidence. |
| OD-002 | RESOLVED | Selection only inspects stored/evaluated state. Changed scenario inputs become dirty and require an explicit, ephemeral, deterministic `Run candidate simulation`; its result is candidate-only and cannot replace Current Decision. |
| OD-003 | RESOLVED | Classify each reviewed remaining-plan node as `auto_reduce`, `protected_floor`, or `review_only`; action types provide only conservative defaults, and missing or unreviewed policy fails to `review_only`. |
| OD-004 | RESOLVED | Human-driven causes require a verified Safety / Emergency trigger receipt. Weather and IMU/PDR/GNSS enter as normalized automatic facts; one action event owns debt, explicit causal links preserve provenance, and Scout emits only safety-subordinate pace recommendations. |
| OD-005 | RESOLVED | Baseline is the default lens; Replay and Live Observer bind one matching session and require explicit entry. Baseline supports human-seeded text and reference-GPX-seeded generation, both converging on one typed, versioned candidate with visible provenance. |
| OD-006 | RESOLVED | Preview, generation, conversation, validation, Replay, Live Observer, and simulation are no-write. Explicit Save creates immutable candidate versions; explicit human Accept creates a hash-bound reviewed baseline only after deterministic promotion gates, without departure/runtime authority. |
| OD-007 | RESOLVED | Night eligibility is a conjunctive, fail-closed gate that can only produce `eligible_for_human_review`. Human review exists exclusively in a dedicated Safety / Emergency interface and returns a hash-bound receipt; Permission never approves night travel. |
| OD-008 | RESOLVED | Use an asymmetric responsive contract: Permission remains a desktop-first authoring/simulation workbench with a complete compact mobile inspection and handoff path; Safety / Emergency remains mobile-first with the full human-review workflow. Mobile uses large, clear type and controls, decision-first information, no horizontal page scroll, and shared desktop/mobile packet state. |
| OD-009 | RESOLVED | Every decision uses two deliberate taps: select an action, inspect a fixed bottom confirmation sheet, then activate a consequence-labelled Confirm control. Long-press, swipe, timed hold, preselection, and mandatory text are prohibited. The server revalidates before append; escalation opens a separate Emergency Call Out flow and does not inherit outbound approval. |
| OD-010 | RESOLVED | Offline/degraded mode may inspect a labelled cached packet and record conservative Hold/bivy, Reject, or Escalate choices as encrypted device-local pending intents. Approval is disabled. Reconnect rebuilds server truth and appends or resolves a canonical receipt only after validation; conflicts produce an audit result, never retroactive approval. |
| OD-011 | RESOLVED | Current eligibility-packet expiry derives from the earliest `valid_until` among all required gate evidence and reviewed policy/session deadlines. Human review never extends evidence freshness. Server time is authoritative; material trigger, route/envelope, lineage, or gate changes invalidate review, while ordinary evidence refresh first rebuilds eligibility under OD-012's daily scope. |
| OD-012 | RESOLVED | Human review is organized by current mission day rather than one segment attempt or the whole expedition. Each `D_n` has one Daily Emergency Review Session containing exact alternative packets and per-alternative receipts. Those receipts may satisfy the human prerequisite across fresh checks within the same day/envelope, but never cross into another day or replace current eligibility. |
| OD-013 | RESOLVED | Mission-day close is destination-driven, never clock-driven. Confirmed arrival at the reviewed planned day-end target closes normally; an unreachable target triggers Emergency Bivy Review and only confirmed establishment at the reviewed bivy closes contingently. The next day remains pending during any multi-calendar-day Shelter Hold and starts only through a separate reviewed receipt. |
| OD-014 | RESOLVED | Departure review is a concise six-row AND-gate checklist: Weather/threats, Route/navigation, Team, Equipment/power, Supplies/shelter fallback, and Communication/next-day plan. Authorized automatic facts prefill read-only states and an evidence-bound Scout suggestion; only field attestations require leader checks. All rows, hashes, Safety state, and final two-step confirmation must pass. |
| OD-015 | RESOLVED | Every Auto/Hybrid departure row provides a two-step `Field condition differs` path with four fixed categories and optional short note. It creates a typed Safety / Emergency trigger receipt, blocks/unknowns the row, suspends Scout advice, and requires fresh evidence plus a separate resolution receipt; automatic refresh cannot silently clear it. |
| OD-016 | RESOLVED | Day end can close immediately through an authorized on-site `Arrived` / `Camp established` confirmation or automatically after reviewed-zone GNSS arrival plus a deterministic 600-second dwell. Individual devices record route-travel, rest, lying, sleep, and resumed movement themselves; the leader never performs a per-person sleep roll call. Positive exit, continued-route, target-mismatch, or unexpected same-group separation evidence blocks auto-close, while the next day remains pending after closure. |
| OD-017 | RESOLVED | Explicit, versioned movement groups independently own arrival, day close, Shelter Hold, daily review, and next-day start. The expedition view is a read-only roll-up where `partially_closed` is normal; one group never blocks another unless a reviewed shared dependency or scoped Safety / Emergency constraint says so. Unexpected separation remains an exception and is never inferred into a group. |
| OD-018 | RESOLVED | Each movement group uses a reviewed route/target Communication Window Policy rather than continuous heartbeats. Matching known blackout is neutral; missing the authoritative latest check-in creates automatic `contact_overdue` review, while emergency escalation requires a Safety / Emergency trigger or reviewed compound evidence. Only acknowledged group-scoped receipts prove check-in, and local versus remote knowledge never collapses. |

## 15. Explicit Non-Goals For The First Slice

- No production field authorization.
- No automatic night-travel authorization.
- No in-place or silent mutation of an existing pre-trip candidate or reviewed
  baseline. Any future authoring write must create an explicit, versioned,
  hash-bound artifact under the OD-006 contract.
- No mutation of runtime safety truth.
- No `/safety/*` calls.
- No outbound message or hardware control.
- No physical inventory ledger, equipment custody, per-group resource
  allocation, or inter-group transfer workflow. Permission may consume an
  existing bounded resource-readiness summary as evidence but does not own or
  edit the underlying logistics truth.
- No raw health payload, raw GPX, exact location history, or exact private
  timestamps in the Dashboard projection.
- No model-generated decision substituting for deterministic policy output.
