# Assistant model switch: DeepSeek V4 Flash 0731

Date: 2026-09-11. Status: working configuration, verified through the installed runtime.

The user requested `deepseek/deepseek-v4-flash-0731`. The Dashboard cloud profile
now selects `openrouter:deepseek/deepseek-v4-flash-0731` through its existing
OpenRouter endpoint and credential reference. The actual response model ID was
`deepseek/deepseek-v4-flash-0731`. The model is listed in the
[OpenRouter catalog](https://openrouter.ai/deepseek/deepseek-v4-flash-0731).

The active configuration is `/data/scout/config/assistant-models.json`; the
tracked Dashboard example is `configs/assistant-models.dashboard-aihat2.json`.
The live previous model was `openrouter:openai/gpt-5.6-sol`. The tracked example
previously selected `deepseek/deepseek-v3.2`.

## Activation and rollback evidence

The live configuration included a GPT-5.6 Sol promotion manifest binding. Its
manifest explicitly identifies `deepseek/deepseek-v4-flash-0731` as the rollback
model. Applying only a model-name change initially failed the installed
runtime's manifest binding validation; the original configuration was restored
while the rollback configuration was prepared.

For this user-requested rollback target, the active configuration changes the
cloud model and removes the Sol-specific `production_promotion_manifest_path`
and `production_promotion_manifest_sha256` references. The original manifest and
its validation code remain unchanged. This does not transfer Sol's qualification
results to DeepSeek or claim a new production qualification.

The original configuration is backed up at:

```text
/data/scout/config/model-switch-backups/assistant-models.before-deepseek-v4-flash-0731.20260911T005954Z.json
```

Original configuration SHA-256:
`037a16d02cb4afdbca1a988b7eabe18478d82fa7c961634e65d8f4bb60d3a06e`.
Final configuration SHA-256:
`aaf07ec46692ceb8f62dcf81638a0f84ae781fe752a0cea7b0cddb0965fd4248`.

To restore Sol, restore the complete backed-up configuration, including its
matching promotion references, and reload `scout-pi-phase4-admin`. Changing just
the model name does not restore that prior qualification binding.

Only `scout-pi-phase4-admin` was restarted. Its published port is `9110`.
Other containers were not restarted. Existing local fallback, endpoint,
credential reference, startup-connect behavior and call budgets were preserved.
The local model remains `hailo:qwen3:1.7b`.

## Verification

- Installed runtime configuration loader: PASS for the rollback candidate.
- `GET /health`: `status=ok`, `runtime_profile=pi-phase4-admin-preview`.
- Authenticated `GET /assistant/status`: `config_loaded=true`,
  `provider_class=PydanticAIAssistantProvider`, requested cloud model loaded,
  local fallback enabled.
- Installed Scout runner connectivity: `MODEL_SWITCH_OK`, one model request,
  284 input tokens and 26 output tokens; observed requested model ID.
- Synthetic read-only tool and typed output: PASS, one fixture-tool execution,
  two model requests, 965 input tokens and 122 output tokens; observed requested
  model ID, with no fallback.
- `./venv/bin/python -m pytest -q tests/test_assistant_model_config.py`:
  9 passed. Config normalization, preserved fallback and minimum 10/10 call
  capacity were also checked locally.

Initial cloud checks failed because the container had no external DNS servers.
Restarting that container refreshed its Docker resolver from the host's current
DNS configuration; resolution and the live model checks then succeeded. No
resolver configuration or network topology was edited. The first tool-smoke
reporter assumed `usage()` instead of the installed runtime's `usage` property;
the reporter was corrected and the complete check passed on rerun.

Navigation freeze verification was unavailable: this checkout contains neither
`tools/verify_navigation_freeze.py` nor an installed `rtk` command. No Navigation
source, map contract or GIS preparation code was edited. The 32-layer gate and
browser layout tests were not applicable. Full workspace/model qualification
and repository-wide suites were not run for this configuration change.
