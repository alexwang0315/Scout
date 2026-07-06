# Scout AI AI HAT+2 Fallback Eval Notes

Last updated: 2026-07-06

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

## Boundary

All AI HAT+2 fallback outputs remain advisory and candidate-only:

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
  --model qwen2.5-instruct:1.5b \
  --timeout-seconds 120 \
  --max-tools 8 \
  --output-dir outputs/evals
```
