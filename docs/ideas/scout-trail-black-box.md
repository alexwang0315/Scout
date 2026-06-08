# Scout Trail Black Box

## Problem Statement

How might we build a portable edge-AI safety recorder for wilderness exploration that continuously records evidence, matches movement against terrain and maps, and escalates safety actions when the user may be unable to respond?

## Recommended Direction

Scout should start as a route-mission safety black box, not a general AI assistant or an always-on raw sensor recorder. Its first job is to produce a trustworthy mission record: which planned route segment the user was on, which checkpoint or control zone they crossed, what the device sensed, how resource and communication conditions changed, what risk signals appeared, and what actions were taken.

The AI and agent layer should be treated as an extensible edge runtime. Plugins and skills can add capabilities such as IMU/PDR processing, radio signal detection, map matching, beacon/reack behavior, local summarization, or future hardware-specific integrations. Emergency escalation should remain governed by an auditable safety state machine, with AI helping interpret, summarize, and select bounded tools.

The first product scenario is wilderness exploration in changing mountain terrain, with secondary value for search-and-rescue teams. Like an aircraft recorder, the value is not only real-time assistance but post-incident traceability: better rescue response, better SOPs, and better learning after failures.

Phase 1 should be driven by a `MissionGraph`: an offline route plan enriched with checkpoints, control zones, segment requirements, diversion points, and recording policies. This keeps raw recording small during normal travel. When a user passes a checkpoint, Scout seals the prior segment into a compressed `SegmentCapsule`, emits a check-in when communication allows, resets the short raw ring buffer, and applies the next segment's policy.

Control zones should be defined by terrain and mission resources. A segment boundary may come from geography, such as forest-to-ridge transition or scree-field entry, or from safety logistics, such as daylight remaining, battery level, human pace, water/camp availability, retreat options, and expected communication quality. Scout should be able to recommend `continue`, `hold`, `rest`, `turn_back`, `divert`, or `camp` before a situation becomes an emergency.

## Key Assumptions to Validate

- [ ] Map matching remains useful in mountain terrain with noisy GPS.
      Test with recorded routes and compare raw GPS/PDR against matched paths.
- [ ] PDR/IMU can provide useful short-term continuity when GPS degrades.
      Test Apple Watch/iPhone samples across trails, turns, stops, and elevation changes.
- [ ] Risk escalation can be rule-based enough to be auditable.
      Define L0-L4 safety states and replay sample sessions through them.
- [ ] Checkpoint-driven segment sealing can reduce raw storage without losing mission meaning.
      Compare always-on raw recording against segment capsules plus short raw ring buffers.
- [ ] Resource-aware segmentation catches unsafe continuation before emergency.
      Replay low-battery, near-sunset, poor-communication, and degraded-pace fixtures.
- [ ] A second nearby device can reliably pull critical data when the user cannot respond.
      Prototype ack/reack plus incident package transfer before remote-server dependency.
- [ ] Local AI is useful for summarization and tool orchestration, but not trusted as the sole emergency authority.
      Constrain AI actions through state-machine permissions.

## MVP Scope

The MVP should prove one loop:

1. Load a planned route as a `MissionGraph`.
2. Record GPS/PDR/IMU/signal/resource observations through a small raw ring buffer.
3. Match movement to route segments, checkpoints, and control zones.
4. Seal completed route segments into compressed `SegmentCapsule` records.
5. Detect path, terrain, resource, environment, and communication risk conditions.
6. Escalate through safety levels.
7. Generate an incident package when risk crosses the configured trigger point.
8. Allow a second device or remote endpoint to retrieve check-ins, capsules, or incident packages.
9. Use local AI to summarize what happened in human-readable form.

Safety levels:

- L0 Normal: baseline recording.
- L1 Watch: uncertainty or weak signal; increase recording density.
- L2 Concern: route deviation, unsafe continuation, missed checkpoint, resource shortage, prolonged stillness, fall-like motion, or sensor disagreement; create incident package.
- L3 Distress: sustained concern state; enable beacon/reack and nearby pull.
- L4 Emergency: high-confidence distress; attempt remote alert and preserve full evidence chain.

Mission records:

- `MissionGraph`: route, checkpoints, segments, zones, requirements, diversion points, and policies.
- `Checkpoint`: terrain or decision boundary, such as ridge entry, water source, camp, retreat point, signal spot, or forest-to-open transition.
- `ControlZone`: segment context with expected risk, communication, slope, GPS reliability, and recording profile.
- `RecordingPolicy`: sampling and retention policy for each state and zone.
- `SegmentCapsule`: compressed sealed record for one completed segment.
- `GoNoGoDecision`: deterministic recommendation to continue, hold, rest, turn back, divert, or camp.

## Plugin / Skill Runtime Direction

Scout should expose internal tools as bounded capabilities:

- IMU/PDR plugin
- GPS trajectory plugin
- Map matching plugin
- Mission graph plugin
- Checkpoint manager plugin
- Resource/environment provider plugin
- Communication capability plugin
- Signal strength / radio plugin
- Incident package plugin
- Segment capsule plugin
- Ack/reack beacon plugin
- Local AI summary plugin
- Remote alert plugin

Plugins should not directly trigger emergency outcomes. They emit observations, confidence scores, proposed actions, or artifacts. The safety state machine decides which actions are allowed.

## Not Doing (and Why)

- Full autonomous rescue agent - too many unvalidated dependencies for v1.
- Raspberry Pi port first - hardware migration before data model stability will slow learning.
- Beautiful dashboard first - useful later, but not the core safety proof.
- LLM-controlled emergency escalation - unsafe and hard to audit.
- Full offline map engine - start with GPX/GeoJSON route matching or simplified map graph.
- Live weather/sunset/comms API integration - define provider interfaces and use mock fixtures first.
- All possible plugins - only build the minimum needed for the wilderness black box loop.

## Open Questions

- What is the first real test route?
- What sensors are mandatory for v1: iPhone only, Apple Watch, or both?
- What nearby transfer protocol should ack/reack use first?
- What does an incident package need to contain for rescuers?
- What false-positive rate is acceptable before triggering L3 or L4?
- Which checkpoints are mandatory decision gates instead of passive check-ins?
- Which resource constraints force `hold`, `turn_back`, `divert`, or `camp`?
- Should Scout optimize for solo explorers first or search-and-rescue team workflows first?

## First Implementation Milestone

Before porting to Raspberry Pi or other edge hardware, the first implementation milestone is to make the current Mac/iPhone/Apple Watch prototype prove the safety loop:

1. Define `MissionGraph`, `Checkpoint`, `ControlZone`, `RouteSegment`, `RecordingPolicy`, `SegmentCapsule`, `Observation`, `SafetyEvent`, `SafetyState`, `IncidentPackage`, and `GoNoGoDecision`.
2. Build a replay runner that feeds Apple Watch, GPS, PDR, and mock mission-context samples into the safety state machine.
3. Add minimal route matching using GPX/GeoJSON route data or a simplified route graph.
4. Detect checkpoint arrival and seal completed segments into `SegmentCapsule` records.
5. Implement resource-aware L0-L4 escalation and go/no-go decisions.
6. Mock environment, resource, and communication providers so future weather, sunset, modem, radio, or AT-command integrations can plug in without changing the safety state machine.
7. Let AI read incident packages and produce responder-facing summaries, without directly controlling emergency escalation.
