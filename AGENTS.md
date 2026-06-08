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
