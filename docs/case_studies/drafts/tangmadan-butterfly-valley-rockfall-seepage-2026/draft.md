# Case Study Draft: Tangmadan Shan Butterfly Valley rockfall and seepage risk, 2026

Status: draft review artifact

Boundary labels: `not_diagnosis`, `no_fault_assignment`, `not_official_sop`, `requires_human_review`

This draft captures a reported rockfall incident and a user-supplied terrain/hydrology interpretation for Scout review. It does not assign fault, diagnose injuries, prove a geologic mechanism, define official rescue procedure, or change Phase 1/2 runtime behavior.

## Source Provenance

- `src_001`: Central News Agency, "唐麻丹山蝴蝶谷步道落石意外 4死1傷", published 2026-06-28, accessed 2026-06-29, reliability `reported_fact`.
- `src_002`: Forestry and Nature Conservation Agency trail page, "唐麻丹山步道 - 山林悠遊網", accessed 2026-06-29, reliability `reported_fact`.
- `src_003`: Central News Agency, "唐麻丹山蝴蝶谷步道5/1重開 1.4K處封閉改道", published 2026-04-30, accessed 2026-06-29, reliability `reported_fact`.
- `src_004`: User-provided Google Earth satellite screenshot near Tangmadan Shan and Butterfly Valley Waterfall, accessed 2026-06-29, reliability `assumption` for route/terrain interpretation.
- `src_005`: User-provided seepage and rockfall risk interpretation, accessed 2026-06-29, reliability `assumption`.
- `src_006`: Google Earth Engine Data Catalog, "SPL4SMGP.008 SMAP L4 Global 3-hourly 9-km Surface and Root Zone Soil Moisture", accessed 2026-06-29, reliability `reported_fact`.

## Short Evidence Quotes

- `q_001`: "唐麻丹山蝴蝶谷步道上發生落石意外，共造成4死1傷。"
- `q_002`: "梨山雨量站27日累積雨量75.6毫米"
- `q_003`: "6月27日至8月30日暫停開放"
- `q_004`: "流水終年不歇"
- `q_005`: "右側邊坡不穩、時有落石"
- `q_006`: "N24°09'34.56\""
- `q_007`: "破碎岩層且有持續水跡"
- `q_008`: "快速通過、不逗留"
- `q_009`: "global 3-hourly data on surface and root-zone soil moisture"

## Reported Source Facts

- CNA reported a 2026-06-27 rockfall incident on Tangmadan Shan Butterfly Valley trail causing four deaths and one injury.
- The Forestry and Nature Conservation Agency trail page showed the Tangmadan Shan trail closed from 2026-06-27 to 2026-08-30 after the incident.
- The official trail page describes the Butterfly Valley Waterfall route as having perennial flowing water, supporting the need to distinguish current rainfall from persistent local water features.
- CNA reported same-day rainfall context from Lishan station. This does not by itself prove the accident site's local hydrology, but it is relevant antecedent-water context.
- A 2026-04-30 CNA report on the trail reopening cited earlier right-slope instability and rockfall at a related Butterfly Valley trail section that was bypassed by rerouting.
- The user-provided screenshot shows a Google Earth satellite view around Tangmadan Shan and Butterfly Valley Waterfall with red markings over steep terrain near the route. This is image context, not official GIS evidence.
- The pasted interpretation hypothesizes hidden catchment drainage, subsurface seepage, fractured rock, and antecedent-rain lag as possible reasons for water presence without obvious rain or visible upstream stream.
- The Google Earth Engine Data Catalog lists SMAP L4 surface and root-zone soil moisture collection `NASA/SMAP/SPL4SMGP/008`, which Scout can use as candidate hydrologic background rather than site-scale proof.

## User-Supplied Framing

The user highlights a key field observation: a trail segment can be wet even when there is no obvious upstream surface stream and no visible rain at the moment. The proposed explanation is hidden catchment drainage, forest-covered gullies, fractured rock, groundwater seepage, and delayed release after antecedent rain.

This framing is useful for Scout because the system should not reduce rockfall exposure prompts to "is it raining right now?" Persistent water stains, wet rock, waterfall corridors, prior rockfall reports, and official closures are distinct signals that can coexist.

## Scout Design Implications

- Taxonomy: `low_tolerance_terrain`, `terrain_feature_checkpoint_planning`, `near_route_fall_hazard`, `route_blocked_waiting`, `incident_package_for_guardian`, `field_actions`, `cold_wet_risk`, `descent_attention_risk`.
- Proposed hook: `terrain_features.seepage_rockfall_checkpoint`.
- Phase/target: `phase_4_pretrip_planning`.
- Confidence: `assumption`.
- Summary: Scout should flag routes where official sources, recent incidents, or local observations indicate wet rock faces, seepage, fractured slopes, waterfalls, or prior rockfall as terrain checkpoints requiring human review.

Additional review hooks:

- `weather_context.antecedent_rain_lag`: keep antecedent rainfall, official closure state, and persistent-water terrain separate from the user's immediate weather impression.
- `field_decision.wet_rockfall_passage`: prompt exposure minimization, no resting or photographing under wet fractured slopes, one-at-a-time passage if appropriate, or turnaround review when closures or active rockfall signs are present.
- `source_quality.satellite_hydrology_boundary`: treat satellite-image drainage and seepage interpretation as a hypothesis unless confirmed by field observation, official GIS layers, terrain models, rainfall data, or geologic mapping.
- `incident_package.rockfall_exposure_context`: package location, trail section, closure status, visible water or seepage, rainfall context, injury count, exposure zone, and official source references for approved rescue communication.
- `gee_environment.smap_l4_soil_moisture_candidate`: use GEE SMAP L4 soil moisture as route-corridor hydrologic background, clearly labeled as coarse candidate evidence and combined with terrain, geology, rainfall, closure, and field-observation evidence.

## Non-Goals

- Do not infer the exact medical cause or injury details beyond reported incident outcome.
- Do not assign legal responsibility to hikers, guides, trail managers, or agencies.
- Do not claim satellite imagery proves subsurface hydrology or a specific collapse mechanism.
- Do not convert this draft into an official SOP.
- Do not mutate Scout safety thresholds or runtime truth from this case-study material.

## Discussion Questions

1. Should Scout treat persistent water stains, seepage, waterfall corridors, and prior rockfall reports as a combined terrain checkpoint before a route is accepted?
2. How should Scout present antecedent rainfall and hidden catchment uncertainty without implying it has proven subsurface hydrology?
3. When a wet fractured slope is already on route, should Scout prompt for quick passage, one-at-a-time exposure reduction, no lingering, or turnaround review?
4. Which official layers or data sources are required before a satellite-image drainage hypothesis can become accepted Scout route evidence?
5. Should GEE SMAP L4 soil moisture appear as a route-corridor background layer, a pre-trip risk matrix factor, or both?

## Promotion Checklist

- Human reviewer confirms incident details against official or higher-confidence reports if they become available.
- Human reviewer decides whether this remains a corpus draft or becomes an accepted case study.
- Any later spec change is handled separately and explicitly; this draft does not patch Phase 1 or Phase 2.
