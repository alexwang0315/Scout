---
name: scout-domain-adaptation
description: Adapt Scout AI OS to a new evidence-rich domain or repair a domain with poor answer quality. Use when Codex is asked to add a new Scout domain, convert domain documents or workspace artifacts into Scout tools and skills, improve local or cloud model grounding, investigate failed domain evals, build a new question corpus, or prove parity between a capable cloud model and a smaller local fallback. Covers evidence catalogs, typed tools, deterministic retrieval and joins, bounded context, Scout runtime skills, answer synthesis, verifiers, real-entrypoint evals, and finite failure escalation.
---

# Scout Domain Adaptation

## Overview

Build a domain capability as an evidence pipeline, not as a prompt collection.
Prove that Scout can acquire, transform, cite, and answer from the domain's real
evidence before optimizing model size, latency, or cost.

This is the Codex development skill. The corresponding Scout/Pydantic AI
planning skill is `skills/scout/domain-grounded-agent-adaptation.yaml`.

## Required Reading

Read these before changing the domain architecture:

1. `AGENTS.md`, especially Aggressive Construction Mode, the 10/10 recovery
   budget, and hard safety boundaries.
2. `docs/specs/scout-ai-domain-grounding-tuning.md` for the reusable adaptation
   contract and eval dimensions.
3. The target domain specification, current Scout tool interface, nearest
   registry manifests, planner tests, and real execution entrypoint.

Read only the relevant files. Use `rg` or `rg --files` to find the current
implementation instead of assuming a path from an older report.

## Non-Negotiable Architecture

- Let agents classify, plan, select tools, and synthesize language.
- Let deterministic runtime code validate schemas, execute tools, filter,
  aggregate, join, calculate, enforce effects, preserve provenance, and verify
  evidence.
- Treat missing, stale, conflicting, and not-applicable evidence as distinct
  states.
- Keep model-authored prose separate from deterministic fallback references.
- Never inject a reference answer or fixed prose template into raw model evals.
- Never promote model output or candidate evidence into runtime safety truth.
- Do not use a stronger model to hide a broken tool or evidence path.
- Do not start model-weight fine-tuning until the same cases succeed with a
  proven evidence trajectory and a capable authorized model.

## Workflow

### 1. Inspect and bound the work

- Inspect `git status` and preserve unrelated changes.
- Name the domain, users, entities, time scales, and decisions.
- State what remains advisory and what requires deterministic or human
  authority.
- Identify the real entrypoint: dashboard assistant, API, CLI, replay harness,
  or hardware fallback.

### 2. Build the question and success contract

- Create or select realistic questions from actual domain workflows.
- Group them into static facts, aggregates, cross-artifact joins, spatial or
  temporal facts, live state, compound reasoning, and authority decisions.
- Define expected facts, acceptable uncertainty, prohibited claims, and source
  requirements per question.
- Keep a held-out set that is not used to write topic guidance.

### 3. Inventory evidence before writing prompts

For every required fact, record:

- source path, API, or stream;
- schema, units, entity IDs, timestamps, and join keys;
- provenance and source reference;
- freshness or TTL policy;
- uncertainty and candidate-only boundary;
- behavior when the evidence is absent, stale, or contradictory.

Produce a tool-gap matrix. Do not label an evidence gap as a missing tool when
the tool exists but the artifact is absent.

### 4. Implement the smallest real vertical slice

Implement one representative question end to end:

1. Add or repair a narrow typed tool and its tolerant adapter.
2. Register the tool and expose concise result, missing evidence, freshness,
   and source refs.
3. Update planner routing so natural language can select the tool.
4. Perform exact reads, filters, joins, ranking, geometry, or calculations in
   deterministic code.
5. Add answer-priority fields to compact evidence cards.
6. Update the Scout runtime skill or answer contract without hard-coding the
   expected sentence.
7. Add synthesis and verifier coverage.
8. Run the real entrypoint or a faithful recorded replay.

Do not stop after adding a manifest or after a deterministic unit test bypasses
the AI planner.

### 5. Design the model-facing context

- Keep the complete evidence ledger outside the model context.
- Pack question-matched facts first, then units, time, uncertainty, missing
  fields, and source refs.
- Represent every selected tool while deduplicating repeated metadata.
- Respect the provider's real context window through packing and continuation,
  not by silently dropping evidence.
- Use the model for concise synthesis and bounded judgment, not database,
  arithmetic, geometry, or source-of-truth work.

### 6. Verify with the real model path

Record for every case:

- selected skills and tools;
- actual tool calls and tool outputs;
- evidence and source refs used;
- provider, model, request count, tokens, finish reason, and retries;
- model-authored answer and deterministic reference separately;
- grounding, completeness, contradiction, freshness, and language checks;
- latency, continuation, hardware attestation, temperature, memory, and power
  telemetry when hardware is involved;
- human review result.

An HTTP 200, non-empty answer, selected tool, or verifier pass is not by itself
an answer-quality success.

### 7. Diagnose failures by layer

| Symptom | Repair first |
| --- | --- |
| Correct tool is never selected | Intent classification, planner hints, skill trigger, or registry projection |
| Tool selected but no fact returned | Adapter, schema, source path, filter, freshness, or fixture |
| Facts exist but model never sees them | Evidence-card priority, packing, deduplication, or progressive disclosure |
| Model contradicts supplied facts | Answer contract, model suitability, self-review, or verifier |
| Good grounded answer is rejected | Verifier rule, normalization, citation extraction, or benchmark expectation |
| Eval passes but dashboard/API fails | Harness parity, deployed version, request profile, or real entrypoint wiring |
| Stream times out or context fills | Checkpoint trace, compact continuation, and transport recovery |

Apply the finite ladder in order: repair tool or harness, rerun with fresh 10/10
capacity, switch model, create Codex review artifact, then register a stable
`KNOWN_ISSUE`. Do not grind a case without a new repair, model, or evidence.

### 8. Compare cloud and local roles

Use the strongest authorized model to prove the first complete trajectory. Then
run the same questions, evidence, and verifier against the intended local
fallback. Compare fact retention, contradiction, language quality, completion,
latency, and hardware health. Preserve cloud escalation for cases that exceed
the demonstrated local capability; do not make cloud availability a substitute
for local evidence preparation.

### 9. Complete the domain bundle

A reusable domain implementation should include, where applicable:

- domain spec and evidence catalog;
- question corpus and expected-success contract;
- typed tools, adapters, manifests, and registry entries;
- planner/routing regression tests;
- deterministic aggregation, join, and verification paths;
- compact context projection;
- Scout runtime skill under `skills/scout/`;
- answer synthesis and verifier rules;
- real-entrypoint eval artifact with call trace;
- known issues and explicit promotion debt.

## Completion Gate

Report `WORKING PROTOTYPE` only when at least one representative question has
completed this trajectory:

```text
natural-language question
  -> AI skill/tool selection
  -> real evidence acquisition
  -> deterministic transformation or join
  -> compact context
  -> model-authored answer
  -> source/grounding verification
```

Run focused tests, lint the affected code when configured, inspect the scoped
diff, and report the actual entrypoint evidence. Use `PARTIAL PROTOTYPE` when a
meaningful portion works but a precise blocker remains. Do not claim that a new
domain is complete based only on documents, manifests, mocks, or deterministic
answers that bypass the model planner.
