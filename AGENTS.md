# AGENTS.md

## Project

This repository is being extended with the Scout AI OS MVP: an adaptive
workflow agent runtime that compiles user requests into typed workflows,
searches and installs capabilities, executes approved workflows through
deterministic runtime services, and stores reviewable learning artifacts.

## Current Phase

Implementation now covers Phase 0 through Phase 9 from
`docs/specs/SCOUT_AI_OS_MVP_SPEC.md`.

Implemented MVP scope:

- repository inspection;
- project scaffold;
- package config;
- planning and architecture docs;
- Pydantic schema contracts;
- SQLite database initialization;
- deterministic workflow, capability metadata, learning, and memory stores;
- permission gate rules;
- local notification gateway;
- manual/time runtime tick;
- typed provider-backed agent facades with deterministic no-LLM provider;
- generated capability sandbox verification;
- FastAPI routes;
- learning artifact approval flow;
- focused importability, schema, persistence, runtime, agent, sandbox, API,
  learning, and docs tests.

Still not allowed in this MVP:

- autonomous self-modification of Scout core code;
- generated capability installation outside approval and sandbox checks;
- generated code network access by default;
- unrestricted shell execution;
- external message sending without approval;
- production database modification tools;
- payment automation;
- model output mutating runtime safety truth.

## Core Principle

LLM agents may plan, compile specs, generate candidate code, and propose
learning artifacts.

Deterministic runtime code must:

- validate schemas;
- enforce permissions;
- execute workflows;
- run sandbox tests;
- persist state;
- record audit events.

Generated code must never be installed or executed outside sandbox without
validation and permission checks.

## MVP Constraints

- Python 3.12+
- Pydantic v2
- Pydantic AI
- FastAPI
- SQLite WAL
- pytest
- Raspberry Pi compatible
- Avoid heavy infrastructure
- Avoid Kubernetes
- Avoid heavyweight vector DB
- Avoid Temporal in MVP
- Avoid browser automation in MVP except as an interface stub

## Safety Rules

Always require approval for:

- long-term background monitoring;
- location access;
- reading private data;
- sending messages to other people;
- payments;
- deleting or modifying user data;
- installing permanent workflows;
- installing generated code;
- networked scraping or external automation.

Never:

- hardcode secrets;
- read `.env` values in tests unless explicitly mocked;
- allow generated code unrestricted shell access;
- allow generated code production database writes;
- allow generated code network access by default;
- silently convert one-off details into permanent memory;
- allow model output to mutate runtime safety truth.

## Testing

Before considering a phase complete, run focused tests for the changed scaffold.
Run `ruff check .` only after ruff is installed and configured for this repo.

## Project instructions

### Non-negotiable requirements

- MUST preserve backward compatibility for the public API.
- MUST NOT add production dependencies.
- MUST NOT modify generated files under `src/generated/`.
- MUST use the repository service layer; controllers may not access the DB
  directly.

### Required workflow

Before editing:

1. Read `docs/architecture.md`.
2. Inspect existing tests for the affected module.
3. State the planned files to modify.

After editing:

1. Run `pnpm lint`.
2. Run `pnpm typecheck`.
3. Run `pnpm test`.
4. Review `git diff` against all requirements below.

### Acceptance criteria

- Existing public tests pass.
- New behavior has regression tests.
- No unrelated files are changed.
- No API response field is removed or renamed.

### Completion rule

Do not claim completion when any required check fails.
Report each requirement as `PASS`, `FAIL`, or `NOT APPLICABLE`, with evidence.

## Scout Map / Import Layer Regression Gate

Any task that changes GPX import, map preparation, Scout GIS evidence, admin
map rendering, layer controls, route projection, terrain/risk outputs,
Rudy/Rudy+TW/OCR, Boss/MCP/mileage evidence, or the three admin surfaces
(`/admin/pretrip`, `/admin/debug`, `/admin`) must treat the Scout layer contract
as a required gate, not an optional smoke check.

Before editing those areas, enumerate the 30 Scout layers explicitly:

1. `imagery`
2. `rudy`
3. `rudy-twmap`
4. `relief`
5. `geology`
6. `topo-5k`
7. `forest`
8. `osm`
9. `terrain`
10. `corridors`
11. `overpass`
12. `route`
13. `completed-track`
14. `reference-tracks`
15. `retreat`
16. `segments`
17. `risk-ribbon`
18. `risk-heatmap`
19. `risk-delta`
20. `soil-moisture`
21. `antecedent-rain`
22. `risk-score`
23. `checkpoints`
24. `pois`
25. `hazards`
26. `route-notes`
27. `mcp`
28. `boss-points`
29. `events`
30. `weather-api`

The machine-readable source of truth is `scout_layer_contract.py`. Keep
`admin_map_layers.py`, `pretrip_layer_preparation.py`, and these static admin
pages aligned with that contract:

- `docs/admin/phase4-pretrip-planning.html`
- `docs/admin/phase-3-5-runtime-debug.html`
- `docs/admin/phase1-after-action.html`

Run this deterministic gate before claiming a Scout map/import/admin GIS task
is complete:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py --repo-root .
```

When a real workspace is involved, run the same gate against the workspace
after GPX import and map preparation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
  --repo-root . \
  --project-root /path/to/workspace \
  --require-workspace
```

For browser-visible Scout admin work, also run the Playwright smoke check when
the browser runtime is available. It must toggle every expected layer control
on each admin surface and confirm the matching `data-layer-group` exists:

```bash
node tools/admin_ui_visual_smoke.js --python ./venv/bin/python
```

Do not claim completion if any layer is unchecked, missing, unordered, hidden by
an unrelated regression, missing a source/provenance ref when the workspace
requires it, or failing browser toggle behavior. Report every layer as `PASS`
or `FAIL` after verification.

## Style

- Prefer small, typed modules.
- Use Pydantic models for contracts.
- Keep agents thin and typed.
- Keep runtime deterministic.
- Keep services testable through interfaces.
- Add TODO comments only for intentional MVP stubs.

## Architecture Boundaries

Agents:

- workflow_compiler
- execution_planner
- code_builder
- learner

Services:

- workflow_store
- capability_registry
- permission_gate
- sandbox_runner
- notification_gateway
- memory_store
- docs_search

Runtime:

- scheduler
- executor
- triggers
- actions

Schemas:

- workflow
- capability
- learning
- permissions
- runtime

## graphify

- **graphify** (`~/.Codex/skills/graphify/SKILL.md`) - any input to knowledge
  graph.
- Trigger: `/graphify`
- When the user types `/graphify`, invoke the Skill tool with
  `skill: "graphify"` before doing anything else.
