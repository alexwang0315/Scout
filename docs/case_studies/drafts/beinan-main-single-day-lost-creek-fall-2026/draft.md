# Case Study Draft: Beinan Main Mountain single-day lost party with creek fall, 2026

Status: draft review artifact

Boundary labels: `not_diagnosis`, `no_fault_assignment`, `not_official_sop`, `requires_human_review`

This draft captures a reported lost-subgroup and injury pattern for Scout review. It does not diagnose the injured hiker, assign fault, define official rescue procedure, or change Phase 1/2 runtime behavior.

## Source Provenance

- `src_001`: User-pasted rescue summary attributed to Kaohsiung City Fire Department Sixth Brigade, title "徹夜未眠！卑南主到玉山後四峰，跨單位一日雙線緊急救援", accessed 2026-06-25, reliability `reported_fact`. Search found a matching Facebook URL hint, but this draft treats the body as pasted source text rather than fetched official SOP.

## Short Evidence Quotes

- `q_001`: "因隊伍腳程落差，有3名山友未能在原定時間下山，加上天色昏暗不慎迷途"
- `q_002`: "在嘗試移動時其中1人不慎跌落溪谷，足部腫脹疼痛無法行走"
- `q_003`: "迷途時請「原地等待」"
- `q_004`: "於23日上午順利接觸迷途山友並進行患部評估包紮、繩索拖拉"

## Reported Source Facts

- The pasted rescue summary reports that a seven-person group challenged Beinan Main Mountain as a single-day itinerary on 2026-06-22.
- The report says pace differences left three members unable to descend by the planned time, and darkness contributed to route uncertainty.
- The report says one member fell into a creek valley while trying to move, with foot swelling and pain that prevented walking.
- The report says rescuers contacted the lost hikers on 2026-06-23 morning, assessed and bandaged the injured foot, used rope hauling, and returned all members safely to the trailhead by 17:00.

## Scout Design Implications

- Taxonomy: `lost_after_route_uncertainty`, `schedule_slip_and_retreat_gate`, `injury_at_known_location`, `team_separation_missing_member`, `condition_deterioration_on_route`, `rescue_message_v1`, `field_actions`, `pace_buffer_required`, `workload_route_matching`, `descent_attention_risk`, `low_tolerance_terrain`.
- Proposed hook: `lost_protocol.stop_and_wait`.
- Phase/target: `case_study_corpus`.
- Confidence: `assumption`.
- Summary: Scout should treat single-day itinerary delay, pace spread, darkness, and attempted movement after getting lost as a field-risk pattern that requires stop-and-wait prompts, location capture, injury/mobility status, and approved rescue communication.

Additional review hooks:

- `pretrip_readiness.single_day_workload_margin`: treat demanding one-day objectives as needing conservative turnaround margins and darkness buffer review.
- `team_state.pace_gap_split_detector`: ask whether slower members are still within voice or visual range, whether the group has split, and whether the plan has a clear regroup deadline.
- `lost_protocol.stop_and_wait`: prioritize stop-and-wait, safe-place selection, location capture, and approved rescue communication over continued movement after route uncertainty.
- `incident_package.injury_location_and_mobility`: record injury location, mobility status, pain/swelling description, fall terrain, and extraction constraints without making medical diagnosis.

## Non-Goals

- Do not infer medical severity beyond the reported inability to walk.
- Do not assign legal responsibility to teammates, guide, organizer, or injured member.
- Do not convert this draft into an official SOP.
- Do not mutate Scout safety thresholds or runtime truth from this case-study material.

## Discussion Questions

1. Should Scout field prompts prioritize stop-and-wait, location sharing, and mobility status once a subgroup is late, in darkness, or uncertain of route?
2. What pace-gap threshold should trigger regroup or turnaround review before a single-day route becomes a night search problem?
3. How should Scout ask for injury and mobility information without crossing into diagnosis or official rescue command?

## Promotion Checklist

- Human reviewer confirms source facts against official or higher-confidence reports if they become available.
- Human reviewer decides whether this remains a corpus draft or becomes an accepted case study.
- Any later spec change is handled separately and explicitly; this draft does not patch Phase 1 or Phase 2.
