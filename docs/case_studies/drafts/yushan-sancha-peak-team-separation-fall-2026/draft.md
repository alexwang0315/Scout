# Case Study Draft: Yushan Sancha Peak team separation fall, 2026

Status: draft review artifact

Boundary labels: `not_diagnosis`, `no_fault_assignment`, `not_official_sop`, `requires_human_review`

This draft captures a reported team-separation pattern for Scout review. It does not assign fault, diagnose the deceased climber, define official rescue procedure, or change Phase 1/2 runtime behavior.

## Source Provenance

- `src_001`: Central News Agency, "玉山三叉峰山難 女子獨自離隊失聯墜亡", published 2026-06-23, accessed 2026-06-24, reliability `reported_fact`.
- `src_002`: Mirror Media, "玉山三叉峰傳憾事！57歲女山友疑體力不支 墜百米山谷身亡", published 2026-06-23, accessed 2026-06-24, reliability `reported_fact`.
- `src_003`: User-provided pasted text, accessed 2026-06-24, reliability `assumption` for design framing.
- `src_004`: User-pasted rescue summary attributed to Kaohsiung City Fire Department Sixth Brigade, accessed 2026-06-25, reliability `reported_fact`. Search found a matching Facebook URL hint, but this draft treats the body as pasted source text rather than fetched official SOP.

## Short Evidence Quotes

- `q_001`: "徐女昨天下午2時許疑體力不支，在玉山三叉峰向同行者告知要自行返回圓峰山屋"
- `q_002`: "其他山友發現徐女未回山屋後，隨即請求救援。"
- `q_003`: "在圓峰山屋附近一處約100公尺深的谷地發現徐女"
- `q_004`: "隊伍必須照顧最弱的隊員。強的人有更大的責任，不是更大的權利。"
- `q_005`: "大家在玉山南峰登山口（四叉路口）停下稍作休息"
- `q_006`: "天色全黑，伴隨著濃霧，能見度極差、視線嚴重受阻"
- `q_007`: "團體行動時切勿獨自脫隊先行！"

## Reported Source Facts

- A seven-person group was reported to be climbing in the Yushan rear four peaks area on 2026-06-22.
- Reports say a 57-year-old woman felt physically unwell or lacked strength and told teammates she would return to Yuanfeng Hut alone.
- The rescue-summary text adds that the team paused near the Yushan South Peak trailhead four-way intersection while returning from Lushan toward Yuanfeng Hut.
- Reports say teammates later did not find her at Yuanfeng Hut and requested rescue; the rescue-summary text says the guide searched and reported the incident.
- The rescue-summary text reports dark and foggy conditions with poor visibility during the night search.
- Reports say rescuers later found her deceased in a valley or steep-slope area near Yuanfeng Hut. Exact terrain interpretation and official findings require human review.
- The rescue-summary text says the body was packed and carried to Yuanfeng Hut, then hoisted by National Airborne Service Corps helicopter on 2026-06-24.

## User-Supplied Framing

The user frames this as a classic team-separation case: the weakest or deteriorating member must not be allowed to become isolated without an escort, reliable communication, and an explicit team decision. The user also highlights a social pressure pattern: a tired member may say "you go first" or "I can return alone" to avoid losing face or feeling like a burden.

This framing is useful for Scout design because the system can ask decision-quality questions before a group accepts separation. It must remain advisory and review-only.

## Scout Design Implications

- Taxonomy: `team_separation_missing_member`, `condition_deterioration_on_route`, `schedule_slip_and_retreat_gate`, `pace_buffer_required`, `pretrip_fitness_readiness`, `attention_decline_from_fatigue`, `rescue_message_v1`, `field_actions`, `near_route_fall_hazard`, `descent_attention_risk`, `low_tolerance_terrain`.
- Proposed hook: `team_state.separation_guard`.
- Phase/target: `phase_4_pretrip_planning`.
- Confidence: `assumption`.
- Summary: Scout should treat a weak, tired, or symptomatic teammate requesting solo return as a team-separation risk that requires human review, companion assignment, contact confirmation, or whole-team retreat planning.

Additional review hooks:

- `pretrip_readiness.pace_and_load_match`: surface route workload, pace buffer, pack-load tolerance, offline map readiness, and satellite messenger availability as planning prompts.
- `field_decision.assisted_return_checkpoint`: ask whether the returning member has an escort, confirmed route, communication method, last-known point, and check-in deadline.
- `incident_package.missing_member_last_known_point`: help humans package last-known point, intended destination, separation time, communication status, observed condition, weather, visibility, and search constraints for approved rescue communication.
- `retreat_gate.darkness_fog_visibility_margin`: keep darkness, fog, and visibility as review factors for late-day separation and retreat decisions, while leaving actual go/no-go authority to humans.

## Non-Goals

- Do not infer medical cause.
- Do not assign legal responsibility to teammates, guide, organizer, or the deceased climber.
- Do not convert this draft into an official SOP.
- Do not mutate Scout safety thresholds or runtime truth from this case-study material.

## Discussion Questions

1. Should Scout pre-trip and field prompts flag solo return by a tired or unwell teammate as a team-separation checkpoint requiring explicit human decision review?
2. What is the minimum evidence Scout should ask a team to record before any planned separation: escort, route, communication, last-known point, deadline, weather, and visibility?
3. How should Scout phrase help-seeking prompts so a tired team member can ask for assistance without framing it as failure or blame?
4. Should a dark/fog/poor-visibility condition automatically escalate a planned solo return to a whole-team retreat or escort-required review prompt?

## Promotion Checklist

- Human reviewer confirms source facts against official or higher-confidence reports if they become available.
- Human reviewer decides whether this remains a corpus draft or becomes an accepted case study.
- Any later spec change is handled separately and explicitly; this draft does not patch Phase 1 or Phase 2.
