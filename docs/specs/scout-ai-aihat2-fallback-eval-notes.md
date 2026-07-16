# Scout AI AI HAT+2 Fallback Eval Notes

Last updated: 2026-07-16

## Scope

This note records the AI HAT+2 fallback evaluation work for the `user_field_100`
question set. The goal is not to prove Scout can act autonomously in the field;
it is to verify that when cloud models are unavailable, Scout can still compress
workspace evidence, synthetic field context, and deterministic tool output into
short conservative answers on the Scout AI HAT+2.

Official fallback runs must use the Scout host local AI HAT+2 runtime:

- endpoint: `http://127.0.0.1:8000/api/chat`
- model used for this run: `qwen2.5-instruct:1.5b`
- device requirement: `/dev/hailo0` present
- Hailo runtime evidence: `hailortcli scan`

## Final Batch Evidence

The validated result is a five-batch run over the 100 `user_field_100`
questions. Each batch used the Scout host AI HAT+2 endpoint, not cloud, Mac
Ollama, or generic local model serving.

Important interpretation note, added 2026-07-08: the historical batch summary
field `answered=20` means the fallback runtime produced a bounded non-empty
answer for each question in that batch. It does not mean the answer quality was
human-reviewed as correct, fluent, non-contradictory, or sufficiently grounded.
The dashboard finding `目前我無法直接回答 boss point 的數量...我們知道有 5 個 boss point`
exposed this gap: the local model did use AI HAT+2, but the quality gate failed
to detect a self-contradictory answer when deterministic context already
contained `boss_point_count=5`. Future AI HAT+2 evaluations must separately
score:

- `invoked_ai_hat_plus_2`: local Hailo/Ollama runtime was actually used.
- `non_empty_answer`: a response was produced.
- `directness`: explicit facts in context are answered directly.
- `contradiction_free`: the answer does not say it cannot answer and then give
  the answer.
- `grounded_context_use`: exact workspace values, such as counts and named refs,
  are preserved without being converted into missing-context refusals.

Only the last four, not `answered` alone, should be treated as answer quality.

Implementation note, added 2026-07-08: newer eval artifacts include
`answer_quality` per question and `answer_quality_summary` at report level.
The legacy `classification=answered` field is kept only for backward
compatibility. A question must not be counted as local LLM quality success
unless `answer_quality.classification=auto_screen_pass_requires_human_review`
and a human reviewer accepts the actual wording. Tool-derived fallback evidence
is useful as a safety net, but it must be displayed and scored separately from
the AI HAT+2 model's own answer.

Correction note, added 2026-07-09: dashboard testing found that the AI HAT+2
provider path still contained an exact-copy grounding retry prompt. That prompt
could make the local model appear to pass by copying deterministic Scout tool
evidence instead of synthesizing its own evidence-prompted short answer. The
exact-copy retry was removed from the provider path. Historical reports that
claim `answered=100` must therefore be interpreted as fallback pipeline
availability evidence only, not as proof that the local LLM independently
answered all 100 questions with acceptable quality. Future runs must report the
displayed answer, the grounding reference, and the guard status separately.

| Range | Report | Summary | Health notes |
| --- | --- | --- | --- |
| field-001..field-020 | `outputs/evals/scout_ai_aihat2_fallback_user_field_100_20260706T090214Z.json` | `answered=20` | start `temp=58.7'C`, end `temp=56.5'C` |
| field-021..field-040 | `outputs/evals/scout_ai_aihat2_fallback_user_field_100_20260706T093207Z.json` | `answered=20` | start `temp=58.7'C`, end `temp=57.1'C` |
| field-041..field-060 | `outputs/evals/scout_ai_aihat2_fallback_user_field_100_20260706T095449Z.json` | `answered=20` | start `temp=58.7'C`, end `temp=57.1'C` |
| field-061..field-080 | `outputs/evals/scout_ai_aihat2_fallback_user_field_100_20260706T103644Z.json` | `answered=20` | start `temp=60.4'C`, end `temp=57.1'C` |
| field-081..field-100 | `outputs/evals/scout_ai_aihat2_fallback_user_field_100_20260706T113109Z.json` | `answered=20` | start `temp=58.2'C`, end `temp=56.0'C` |

Observed host health across successful batches:

- Raspberry Pi thermal throttling stayed at `throttled=0x0`.
- Core voltage readings stayed in the expected `0.75V` to `0.88V` range during
  these runs.
- UPS evidence was unavailable through `/sys/class/power_supply` and `upsc`;
  the runner records this as unavailable evidence, not as a healthy UPS state.

## Fixes Made During Eval

The following failure classes were observed and fixed in the fallback eval
adapter. These fixes keep the AI HAT prompt small and reduce free-form local
model drift by giving it deterministic answer hints.

| Failure class | Example question | Root cause | Fix |
| --- | --- | --- | --- |
| Dry gully / collapse-gully route question | `這條乾溝可以走嗎？` | Router did not consistently attach terrain+risk+navigation context. | Added dry gully route terms and deterministic no-downcut hint. |
| Fitness / route hardness | `這條路線對我的體能來說會不會太硬？` | Route-readiness catchall polluted a body-resource question. | Route + energy evidence now drives the answer; route-readiness is avoided for this pattern. |
| Live navigation and weather questions | `我是不是錯過轉彎點？`, `我是不是該提前撤退？` | Missing live evidence made local fallback refuse. | Added synthetic live-navigation and weather-window context for eval mode. |
| Team and rescue handoff | `後隊是不是停太久？`, `求救訊息要包含哪些欄位？` | Small model generalized team status into vague refusal. | Added team status, pace guardian, and rescue handoff hints. |
| Coordinate vs landmark rescue reporting | `我應該報座標還是地標？` | Survival playbook was too generic. | Added explicit coordinate+landmark reporting hint. |
| Helicopter / open-area rescue question | `直升機是否有可能吊掛？` | Model treated lack of real landing-zone evidence as a refusal. | Added hoist-candidate-only hint with non-guarantee boundary. |
| Rescuer approach question | `這個地形搜救員能接近嗎？` | Terrain evidence existed but no rescue-access phrasing existed. | Added terrain rescue-access hint. |
| Injury reporting | `我滑倒受傷但位置清楚，該怎麼回報？` | Routed to team status and lost the injury-report structure. | Added injury report field checklist. |
| GPX corridor width | `哪段路的 GPX corridor 太寬或太窄？` | Post-trip/equipment missing fields distracted the answer. | Corridor width questions now avoid noisy tools and receive corridor review guidance. |
| Incident package contents | `哪些資料應該進 incident package？` | Post-trip missing fields turned a contents question into a gap answer. | Added incident package required-content checklist. |

## 2026-07-10 Dashboard Free-Generation Audit

The dashboard audit found another source of misleading quality results. The
missing-context path asked the local model to rewrite a predetermined judgment
sentence and then rewrite a predetermined `請提供...` sentence. Even though an
AI HAT inference occurred, the visible wording was mostly fixed by program
text. That two-stage rewrite path was removed. The current dashboard displays
the local model's own natural-language output separately from the deterministic
Scout grounding reference; a typed decision token or grounding reference does
not count as a model answer.

Correction added later on 2026-07-10: a subsequent typed-action experiment
still rendered `STATUS=UNKNOWN;ACTION=...` through a deterministic Chinese
sentence template. That also produced nearly identical visible answers and did
not qualify as local-model answer generation. The renderer was removed. Missing
context now attempts natural-language generation first; an action token may be
recorded only as diagnostic metadata after generation fails, and the dashboard
must label it as classification-only rather than an answer.

Dashboard verification after removing that renderer produced two distinct raw
model answers, confirming that the fixed sentence was no longer in the answer
path. Both still failed the grounding gate:

- `我是不是有高海拔不適風險？` generated Chinese text that drifted into
  `患者` / generic medical-consultation language and omitted the required
  field action.
- `我現在適合繼續上升嗎？` generated an English missing-context summary and
  selected the unrelated `REGROUP_AND_CHECK` action token.

These are model-quality failures, not successful fallback answers. The action
token remains visible for diagnosis but is not rendered into answer prose.

After removing the fixed rewrite path, the available Hailo-10H models were
tested against both missing-current-context questions and workspace-number
questions:

| Model | Observed result | Verdict |
| --- | --- | --- |
| `qwen2.5-instruct:1.5b` | Repeatedly converted missing altitude, symptoms, weather, or gait evidence into affirmative observations and unsafe conclusions. | FAIL |
| `qwen2.5-coder:1.5b` | Preserved uncertainty in one body-state prompt, but omitted required next steps and ignored CP/GPX risk evidence in a rain-risk prompt. | FAIL |
| `llama3.2:3b` | Mixed Chinese and English and escalated missing evidence to unrelated immediate-medical wording. | FAIL |
| `deepseek_r1_distill_qwen:1.5b` | Spent the bounded output on reasoning text and drifted to generic public-database/clinical guidance. | FAIL |
| `qwen2:1.5b` | Listed useful observations but proposed an unrelated low-altitude trip and did not preserve the field-decision context. | FAIL |

Concrete dashboard failures included:

- `我是不是有高海拔不適風險？` -> `根據目前的觀測，我有高海拔不適的風險。`
- `我現在適合繼續上升嗎？` -> the model treated missing altitude,
  symptoms, weather, and daylight as observed and answered that continuing up
  was unsuitable.

Both answers were rejected by the grounding guard and displayed as model
quality failures. The deterministic reference remained visible for debugging
but was not substituted as the model answer.

This establishes a current hardware/model limitation: none of the official
models available in this Hailo model store passed free-generation grounding for
these representative Scout field questions. A future report must not claim
100% human-acceptable local LLM quality until the displayed model wording,
not a deterministic renderer or typed token, passes review.

### Raw single-pass dashboard rerun (2026-07-10)

The dashboard now has a separate `Raw model eval` switch. In that mode each
answer has exactly one AI HAT+2 generation call, zero repair calls, and no
postprocessing or deterministic sentence renderer. The UI displays prompt and
output SHA-256 prefixes and keeps the deterministic Scout grounding reference
in a separate block.

The first ten field questions were rerun with
`hailo:qwen2.5-instruct:1.5b`: `0/10` passed the grounding guard. The raw model
invented current pace, promoted candidates to confirmed danger, reversed
terrain-score meaning, omitted required evidence, and emitted a water-volume
placeholder. The browser-derived artifact is
`outputs/evals/aihat2_raw_single_pass_batch01_20260710.json`.

Adding the registered `local-grounded-short-answer` skill improved the fitness
missing-context question to a grounded model answer, but the darkness/terrain
question still hallucinated a location and interpreted one candidate as more
suitable. This confirms that the skill and compact-evidence path can improve
some question families but does not remove the current 1.5B model ceiling.

The dashboard therefore exposes two distinct controls and semantics:

- `AI HAT+2 fallback` without raw eval: operational guarded/hybrid fallback;
- `AI HAT+2 fallback` plus `Raw model eval`: honest local-model quality test,
  where failed model text remains visible and is never replaced by the tool
  reference.

Host health during the audit remained thermally stable around `58.2'C`; the
Hailo device remained present. `get_throttled=0xd0000` had no current-state low
bits set but records historical undervoltage/throttling/soft-temperature-limit
events. UPS telemetry remained unavailable and must not be reported as healthy.

### Facts-only prompt correction (2026-07-10)

A later browser audit found that `local-grounded-short-answer` had regressed
into a precomposed-answer path. The outbound Hailo prompt contained a complete
`direct_semantics` sentence, repeated the same sentence under `REQUIRED`, and
used `temperature=0`. Two identical dashboard requests therefore produced the
same prompt hash (`2343ce0cffe0`) and output hash (`db03001e7b5f`). Hailo was
really invoked, but it was effectively being asked to copy a program-authored
answer. Those responses do not count as independent local-model answers.

The prompt contract is now `facts_only_v2`:

- no `direct_semantics` or precomposed answer is sent to the model;
- the model receives only the question, evidence facts, missing fields,
  decision boundary, and prohibited inferences;
- same-model self-review receives the same facts-only brief and its own draft,
  never a reference answer;
- answer templating and deterministic prose replacement remain disabled;
- low non-zero sampling is used so repeated runs expose actual model behavior;
- dashboard trace displays `prompt-contract=facts_only_v2` and
  `answer-template=false`.

The same rain-risk question was then submitted twice through the real
dashboard. The outputs and hashes differed, proving that the fixed sentence was
removed, but both answers failed grounding. The model omitted or misread CP,
GPX, and score evidence and invented meanings such as shelter distance, GPS
score, weather score, and generic terrain advice. This is the honest
`qwen2.5-instruct:1.5b` AI HAT+2 result: model generation occurred, but answer
quality is not acceptable. The 100-question evaluation must remain blocked
until browser-visible facts-only model answers pass human review; deterministic
tool references may diagnose failures but may not raise the score.

### Fixed-answer and Hailo trace correction (2026-07-11)

A further browser-visible audit confirmed that `facts_only_v2` still injected a
complete answer from the skill example list. Generic retries also contained an
unrelated `晚出發` constraint, so keyword selection could choose the delayed
departure example for another topic. If no topic matched, the selector silently
used the first rain example. With greedy decoding this made repeated outputs
look program-authored even though the local endpoint was called.

The strict facts-only path now applies these rules:

- no skill example answer is sent to raw generation or topic retry;
- unmatched topics receive no default example;
- generic retries no longer contain unrelated topic keywords;
- the fallback brief cannot copy an unrecognized deterministic full answer;
- request-scoped raw output, attempts, selected call, and trace fields are
  cleared before every request;
- the dashboard shows the selected model attempt, all retries, prompt/output
  hashes, endpoint response status, returned model, generated token count,
  answer contract, and whether hardware execution was attested;
- `hardware-attested=false` is explicit because an Ollama-compatible response
  proves endpoint generation, not physical Hailo execution by itself.

The same Q6 question, `哪些地方下雨後會變危險？`, was rerun through the visible
Dashboard with no complete example answer and no deterministic prose
replacement:

| Model | Endpoint evidence | Result |
| --- | --- | --- |
| `qwen2.5-instruct:1.5b` | response received, non-zero `eval_count` | FAIL: omitted or contradicted CP/weather/boundary facts and repeatedly emitted `危及`. |
| `llama3.2:3b` | response received, non-zero `eval_count` | FAIL: best candidate; preserved CP 213 and candidate intent but omitted the weather gap or emitted simplified Chinese. Three calls took about 114 seconds. |
| `deepseek_r1_distill_qwen:1.5b` | response received, non-zero `eval_count` | FAIL: exposed reasoning text, used simplified Chinese, and did not complete a grounded short answer. |

`llama3.2:3b` is therefore the current best local candidate, not a passing
fallback. The old `answered=100` artifacts remain availability evidence only.
They must not be cited as 100% answer quality, and the next 100-question run must
not start until the first ten browser-visible answers pass human review without
reference-answer injection.

## 2026-07-13 Workspace-Grounded 100-Question Rerun

This rerun used a new 100-question corpus derived only from artifacts present in
the `chilai_nanhua_day1_scoutAI` workspace. It has zero exact-question overlap
with the earlier 200-question corpus. No synthetic field context was injected.

The run used Scout's Hailo Ollama service through an SSH tunnel to the
host-local endpoint, model `qwen3:1.7b`, HEF format, on
`pci/0001:01:00.0 HAILO10H`. Remote journal and `hailortcli monitor` evidence
attested hardware execution; a tunnel response alone was not treated as
hardware proof.

Two direct-eval transport defects were found before the accepted run:

- C0/C1 control characters in the message content triggered Hailo 5.3 prompt
  rendering failures.
- Nested JSON evidence briefs could be truncated inside an escape sequence by
  the Hailo renderer and become invalid JSON.

The accepted run used a bounded plain-text evidence brief with normalized
control characters. After the fix, the 100-question window produced zero new
`Failed to render prompt` journal entries.

Artifacts:

- corpus: `outputs/evals/scout_ai_workspace_grounded_100_questions_20260713.json`
- combined JSON: `outputs/evals/workspace_grounded_100_20260713_qwen3/combined_workspace_grounded_100_qwen3_aihat2.json`
- combined Markdown: `outputs/evals/workspace_grounded_100_20260713_qwen3/combined_workspace_grounded_100_qwen3_aihat2.md`

Pipeline classifications were `answered=81`,
`answered_with_missing_evidence_gap=17`, and
`weak_or_refusal_like_answer=2`. The separate automatic quality screen reported
41 pass-requires-human-review, 47 fail, and 12 needs-review. These values are
not correctness scores. Manual spot checks found fabricated reference GPX
names/counts, route-level point counts misreported as per-segment counts, and
missed boss-point evidence. Therefore this model/run does not pass the local
answer-quality gate even though all 100 requests reached the model and returned
non-empty text.

Observed health envelope during the accepted run:

- AI HAT+ 2 on-die temperature: approximately 58.2 to 61.5 C;
- Scout CPU temperature: approximately 51.8 to 57.3 C;
- Hailo NNC utilization while generating: approximately 91 to 97 percent;
- Linux RAM used: approximately 1.10 GiB of 8.06 GiB, swap 0;
- Hailo Ollama RSS: approximately 135 MiB, `NRestarts=0`;
- `get_throttled=0x50000`: no current low bits, but historical undervoltage and
  throttling occurred during this boot;
- UPS/battery telemetry: unavailable and must not be reported as healthy.

## Local Versus Cloud Token Budgets

The historical `768` workspace generation limit was designed for the AI HAT+2
local fallback, where bounded output controls latency and memory use. It must
not be inherited by an external cloud model. A 2026-07-13 OpenRouter GLM-5.2
run exposed this configuration leak: 14 first-pass cases exhausted the imposed
token budget and several nominally successful answers ended mid-sentence.

The runtime contract is now:

- local fallback default: omit `num_predict` / `max_tokens` and let the Hailo
  model stop at EOS; the dashboard AI HAT+2 profile carries no hidden `384`
  completion cap;
- cloud default: omit `max_tokens` and let the selected provider/model apply
  its native completion capability; the dashboard profile carries no hidden
  `2048` completion cap;
- Aggressive Construction Mode ignores stale `SCOUT_AI_LOCAL_MODEL_MAX_TOKENS`,
  `SCOUT_AI_WORKSPACE_MODEL_MAX_TOKENS`, profile `max_tokens` / `num_predict`,
  and `SCOUT_AI_CLOUD_MODEL_MAX_TOKENS`; these limits can only become active
  after explicitly leaving Construction Mode for Productization;
- request pacing and per-question timeout are transport controls, not output
  token limits, and must be reported separately in eval artifacts.

Cloud-model comparisons must report `finish_reason`, non-empty completed-answer
rate, provider errors, model-native tool calls, and any retries. Exact matching
against the deterministic planner's suggested tool set remains diagnostic and
is not an answer-correctness score.

## Hailo 2K Context Recovery Contract

The Hailo Model Zoo lists the precompiled `Qwen3-1.7B-Instruct` context length
as 2048 tokens. This is an external model capacity, not a Scout Construction
Mode token budget. Scout therefore keeps completion generation uncapped while
packing each Hailo request as follows:

- initial bounded synthesis: conservative `system + user <= 1200` estimated
  input tokens;
- context-full continuation: `system + user <= 900` estimated input tokens;
- complete evidence remains in the deterministic evidence ledger and verifier;
  only the model-facing projection is compacted;
- every selected tool remains represented in the compact projection, with
  lower-value facts and duplicate refs removed first;
- `/api/chat` uses Ollama-compatible NDJSON streaming;
- bounded prompts request the semantic terminator `<SCOUT_DONE>` and also send
  it as an Ollama stop sequence; independently, the streaming client stops once
  a complete bounded answer sentence has formed, so a model that omits the
  marker cannot consume the remaining context after answering;
- `num_predict` remains omitted in Aggressive Construction Mode. Semantic stop
  and input packing must not be misreported as a completion-token ceiling.

If a stream reports context/cache exhaustion, ends with `done=false`, or stalls
without progress, the runtime stores its partial output as trace evidence and
starts a new request with a compact continuation package. The continuation
contains the question, bounded evidence cards, missing-evidence state, and the
partial draft, and asks for one complete independently readable answer. It may
use the attempt's normal 10-request capacity. An unfinished partial response is
never shown as the answer. A model that emits `<SCOUT_DONE>` before any answer
text also enters continuation, but is counted as `empty_semantic_stop` rather
than external context exhaustion. That fresh continuation disables the repeated
marker contract and uses client-side semantic completion: once a complete
bounded sentence is streamed, the client stops reading and sends it through the
same grounding verifier. This avoids both a deterministic empty-marker loop and
an unbounded natural completion without reintroducing a token ceiling.

Eval artifacts expose `streaming`, `semantic_stop`, `semantic_completion`,
`input_pack_estimated_tokens`, `context_full_recovery_count`, and any external
limit reason. Provider hard limits are checkpoint/continuation events; they are
not Scout reasoning failures.

### 2026-07-15 AI HAT+2 workspace 100 proof

The repaired `qwen3:1.7b` Hailo replay completed all 100 workspace-grounded
questions through the real bounded runtime:

- tool selection: 100/100;
- completed and grounded answers: 100/100;
- model requests: 123;
- deterministic tool calls: 142;
- model input/output usage: 103,324 / 5,000 tokens;
- continuations: 8, including 3 actual context-full recoveries;
- Scout temperature: 54.3-62.0 C with `get_throttled=0x0`;
- UPS: 94% throughout, 16.722-16.728 V battery, no active alerts.

Canonical artifacts on the Scout host:

- `eval-results/final-100-quality-repaired-20260715/canonical-100/scout_ai_aihat2_workspace_100_canonical.json`
- `eval-results/final-100-quality-repaired-20260715/canonical-100/scout_ai_aihat2_workspace_100_canonical.md`

The score is a runtime/grounding result, not a claim of perfect language
quality. Five answers remain `KNOWN_MODEL_QUALITY_ISSUE`: cases 050, 070, and
082-084 repeatedly substitute or insert visually similar Chinese glyphs. Their
tool evidence and numeric facts are grounded, but the local 1.7B model's
wording should be reviewed or upgraded before treating those answers as a
language-quality baseline.

Official references:

- Hailo Model Zoo GenAI model table:
  `https://github.com/hailo-ai/hailo_model_zoo_genai/blob/main/docs/MODELS.rst`
- Ollama streaming API contract:
  `https://github.com/ollama/ollama/blob/main/docs/api.md`

### 2026-07-16 Pydantic AI 2.10 canonical fallback replay

The Scout hardware runtime was upgraded to `pydantic-ai-slim==2.10.0` and
`pydantic-evals==2.10.0`, then the configured dashboard fallback model
`qwen3:1.7b` was replayed against all 100 `user_field_100` questions using the
real Hailo endpoint and the current `chilai_nanhua_day1` workspace.

- endpoint: `http://127.0.0.1:8000/api/chat`;
- hardware attestation: Hailo PCIe device plus HEF model metadata;
- all 100 records: `used_ai_hat_plus_2=true`;
- answer classification: 90 answered, 2 answered with missing-evidence gaps,
  2 weak/refusal-like, and 6 no-answer;
- answer quality screen: 39 pass requiring human review, 1 needs review,
  54 fail, and 6 no-answer;
- missing tools: 0 cases;
- cases with missing evidence: 22;
- mean/median/p95 model latency: 62.3/60.0/180.0 seconds;
- run duration: 6,438.7 seconds;
- temperature: 57.6-59.3 C, `get_throttled=0x0`;
- memory remained stable with no swap use.

Canonical Mac and Scout artifact names:

- `outputs/evals/scout_ai_aihat2_fallback_user_field_100_20260716T041951Z.json`
- `outputs/evals/scout_ai_aihat2_fallback_user_field_100_20260716T041951Z.md`

The six no-answer cases (`field-005`, `field-046`, `field-055`, `field-059`,
`field-080`, and `field-089`) ended in the 180-second external transport
boundary. Their model metadata records `TimeoutError`, but the continuation
count is zero. This is a known recovery-path defect: context/cache exhaustion
is continued, while an interrupted streaming transport timeout is not yet
converted into a continuation attempt. Do not report this replay as 100%
answerable or quality-passing.

An additional diagnostic replay used the non-canonical
`qwen2.5-coder:1.5b` HEF model. It completed faster but only 31 answers passed
the automatic quality screen. Its artifacts end in `20260716T023024Z`; they are
comparison evidence, not the configured fallback baseline.

### Why the newer local answers improved

The improvement is primarily an evidence-pipeline result, not a Pydantic AI
version effect and not proof that the local model learned the Scout domain in
its weights.

1. Tool coverage reached zero missing-tool cases. The runtime can now obtain
   route, checkpoint, risk, weather, device, team, and current-context evidence
   instead of asking the model to infer absent facts.
2. Deterministic code performs retrieval, filtering, aggregation, spatial
   matching, joins, ranking, freshness checks, and source-reference handling.
   The local model receives a small set of answer-ready facts rather than raw
   workspace files.
3. The model-facing evidence is packed into a high-density bounded brief. This
   preserves the most relevant values and source refs while staying within the
   external 2K Hailo context window.
4. `qwen3:1.7b` is a better fit than the coder-oriented 1.5B comparison model
   for short Traditional Chinese synthesis and instruction following.
5. The answer skill requires a direct conclusion, concrete evidence, explicit
   unknowns, and a bounded next step. The grounding verifier rejects answers
   that contradict or discard the selected evidence.
6. The eval now separates transport success, non-empty output, grounding,
   completeness, language quality, and human acceptance. Earlier `answered`
   counts hid weak or copied answers.

The two July results answer different questions and must not be merged into one
score. The 2026-07-15 workspace-grounded corpus proved that a small local model
can synthesize well-prepared workspace facts. The 2026-07-16 `user_field_100`
run includes more live-state and safety questions, exposed 22 evidence gaps,
and found a timeout-continuation defect. That difference is evidence that
corpus grounding and runtime evidence availability dominate the score.

The reusable method is specified in
`docs/specs/scout-ai-domain-grounding-tuning.md`. Codex development uses
`.agents/skills/scout-domain-adaptation/SKILL.md`; Scout/Pydantic AI planning
and audit use `skills/scout/domain-grounded-agent-adaptation.yaml`.

## Boundary

All AI HAT+2 fallback outputs remain advisory and candidate-only:

- they do not mutate Phase 1 runtime or safety truth;
- a grounded answer is not automatically a correct safety decision;
- an automatic quality pass still requires human review before becoming a
  language-quality baseline;
- missing live evidence remains unknown and must not be converted into a safe
  or unsafe observation.

- no `/safety/*` writes
- no Phase 1 runtime safety truth mutation
- no outbound SOS,留守通知, or external message sending
- no hardware control
- no generated code execution

The fallback path is allowed to answer with conservative short guidance from
compact evidence. It is not allowed to turn synthetic eval context into real
field truth.

## Regression Commands

Local checks:

```bash
./venv/bin/python -m pytest tests/test_scout_ai_question_eval.py -q
./venv/bin/ruff check tools/scout_ai_aihat2_fallback_eval.py scout_ai_question_eval.py tests/test_scout_ai_question_eval.py
```

Scout host checks:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
  /home/alexwang0315/scout-ai-os-hardware-current/.venv/bin/python \
  -m pytest tests/test_scout_ai_question_eval.py -q
```

Example AI HAT+2 batch:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
  /home/alexwang0315/scout-ai-os-hardware-current/.venv/bin/python \
  tools/scout_ai_aihat2_fallback_eval.py \
  --source-set user_field_100 \
  --case-offset 80 \
  --max-cases 20 \
  --workspace-root /home/alexwang0315/scout-fusion/workspaces \
  --project-id chilai_nanhua_day1 \
  --model qwen3:1.7b \
  --timeout-seconds 120 \
  --max-tools 8 \
  --output-dir outputs/evals
```
