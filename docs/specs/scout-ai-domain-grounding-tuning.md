# Scout AI Domain Grounding and Adaptation

Last updated: 2026-07-16

## Purpose

This specification records the reusable method that improved Scout AI's local
AI HAT+2 answers and defines how the same AI OS core should be adapted to a new
domain. It applies to outdoor safety, equipment maintenance, logistics,
industrial inspection, or another evidence-rich domain.

This is domain adaptation through tools, evidence contracts, skills, and evals.
It is not model-weight fine-tuning. A model may later be fine-tuned, but weight
training must not compensate for missing evidence access or a broken tool path.

The two skill surfaces are:

- Codex development workflow:
  `.agents/skills/scout-domain-adaptation/SKILL.md`
- Scout/Pydantic AI planning and audit contract:
  `skills/scout/domain-grounded-agent-adaptation.yaml`

Use the Codex skill to implement a new domain in the repository. Use the Scout
skill when Scout AI must produce a structured adaptation plan or review an eval
failure. The Scout manifest does not grant code generation, installation, or
runtime writes.

## Proven Causal Chain

The working pattern is:

```text
question family
  -> typed tool plan
  -> deterministic retrieval/filter/join/aggregation
  -> provenance and freshness checks
  -> answer-priority evidence cards
  -> compact model-facing context
  -> model-authored synthesis
  -> grounding/completeness verifier
  -> answer, recovery, or finite failure escalation
```

The major quality gains came from this chain, not from prompt wording alone:

| Lever | Why it matters |
| --- | --- |
| Domain question families | Prevents a generic summary from hijacking a count, spatial, timeline, or compound-risk query. |
| Narrow typed tools | Gives deterministic access to facts and keeps tool semantics auditable. |
| Deterministic evidence DAG | Performs exact operations that a small model should not improvise: filtering, joins, ranking, distance, freshness, and contradiction checks. |
| Answer-priority fields | Preserves the value, unit, entity, time, and source ref that must survive compaction. |
| Bounded context packing | Fits the local model's real context window while retaining every selected tool and the highest-value facts. |
| Model synthesis only | Uses the LLM for language and bounded judgment instead of treating it as a database or geometry engine. |
| Independent verifier | Detects contradictions, missing required facts, invented values, stale evidence, and incomplete sentences. |
| Honest eval taxonomy | Separates endpoint invocation, non-empty output, grounding, completeness, language quality, latency, and human acceptance. |

Pydantic AI supplies the agent/tool runtime and tracing surface. Upgrading it can
fix compatibility or execution defects, but a version upgrade by itself does
not make answers grounded.

## Required Adaptation Artifacts

Every new domain must produce these bounded artifacts before claiming a usable
agent:

1. `domain_boundary`: what the domain covers, excludes, and which decisions
   require a deterministic or human authority.
2. `question_corpus`: realistic questions grouped by query type and risk.
3. `evidence_catalog`: source, schema, owner, freshness, provenance, join keys,
   and missing-data semantics.
4. `tool_gap_matrix`: question family to existing tool, missing tool, adapter,
   or evidence gap.
5. `deterministic_evidence_dag`: retrieval, read, inspect, filter, aggregate,
   join, rank, verify, and source-reference steps.
6. `compact_context_contract`: answer-priority fields, packing order, source
   refs, missing evidence, and external context-window limit.
7. `model_roles`: cloud capability proof, local fallback, reviewer, and any
   model-specific limitations.
8. `verifier_contract`: required facts, forbidden inferences, freshness,
   contradiction, language, and completion checks.
9. `eval_matrix`: per-question trace, tools, evidence, output, grounding,
   quality, latency, hardware health, and human decision.
10. `known_issues`: stable IDs, reproduction, attempted repairs and models,
    blocker, and explicit unblock condition.

## Adaptation Workflow

### 1. Define the domain and decision boundary

Name the entities, time scales, user roles, and decisions. Separate advisory
answers from effects or authoritative truth. Do not begin with prompts.

### 2. Build a realistic question corpus

Collect how domain users actually ask questions. Include static facts,
aggregates, cross-artifact joins, spatial or temporal facts, live state,
compound reasoning, and safety/authority decisions where applicable. Keep a
held-out set that is not used to write topic guidance.

### 3. Inventory evidence before tools

For every required fact, record the source path or API, schema, units, time,
freshness, provenance, uncertainty, and join keys. Define `missing`, `stale`,
`conflicting`, and `not_applicable` separately.

### 4. Implement narrow typed tools

Prefer one clear semantic operation per tool. Tool outputs must expose status,
concise results, missing evidence, source refs, and actionable next reads. Do
not create a catch-all tool that returns a large workspace dump.

### 5. Build deterministic evidence plans

Let the planner choose the evidence path, but let deterministic code execute
exact reads, schema inspection, calculations, joins, spatial matching,
freshness checks, and source verification. Preserve the uniform 10/10 recovery
budget defined in `AGENTS.md`.

### 6. Pack answer-ready context

Project complete evidence into compact cards. Preserve question-matched facts,
units, entity IDs, timestamps, uncertainty, missing fields, and source refs.
Deduplicate repeated metadata before truncating relevant facts. The full
evidence ledger remains outside the model context.

### 7. Add a domain answer skill

Describe how to answer from facts, not what fixed sentence to emit. Add topic
guidance only after a repeatable failure class is observed. Never inject a
reference answer, deterministic prose template, or hidden exact-copy retry into
a raw model-quality eval.

### 8. Verify independently

Check that the answer directly addresses the question, preserves required
facts, cites available source refs, represents unknowns honestly, avoids
contradictions, and finishes cleanly. Keep deterministic fallback evidence
separate from model-authored prose in both UI and scoring.

### 9. Prove capability, then reduce cost

First use the strongest authorized model to prove the evidence/tool trajectory.
Then test smaller local models with the same corpus and verifier. A local model
passes only when it preserves the proven behavior; faster non-empty output is
not parity.

### 10. Apply the finite failure ladder

For each failed question:

1. repair the tool, adapter, schema, retrieval path, evidence card, or harness;
2. rerun with a fresh 10/10 budget;
3. switch model if the evidence path is sound;
4. create a Codex review artifact if it still fails;
5. register a `KNOWN_ISSUE` and continue when no new evidence or repair exists.

## Eval Dimensions

Report these dimensions separately:

- route/skill/tool selection correctness;
- tool execution and source-reference validity;
- evidence sufficiency and freshness;
- model endpoint and hardware attestation;
- directness and required-fact retention;
- contradiction and hallucination rate;
- missing-evidence honesty;
- language quality and sentence completion;
- latency, retries, continuation, temperature, memory, and power telemetry;
- human acceptance.

Do not use `answered`, `HTTP 200`, tool selection, or verifier pass alone as a
quality score.

## Anti-Patterns

- Prompt-only domain adaptation with no evidence catalog.
- Giving the model raw files and asking it to discover schemas repeatedly.
- Hard-coded domain answers disguised as a skill or fallback.
- Reference-answer injection during raw model evaluation.
- Treating a high-risk candidate as a confirmed live hazard.
- Treating missing evidence as safe, unsafe, zero, or false.
- Counting deterministic fallback prose as the local model's answer.
- Using a cloud model to hide a broken local tool path.
- Reducing context, calls, or verification before a reproducible capability
  trajectory exists.

## Outdoor-to-New-Domain Mapping Example

| Outdoor Scout concept | Generic domain equivalent |
| --- | --- |
| Route / CP / segment | Process / checkpoint / stage |
| Sensor snapshot | Current machine, service, or operational telemetry |
| Weather and terrain evidence | External conditions and operating envelope |
| Risk score candidate | Review-priority candidate, not authoritative truth |
| Workspace source ref | Record, document, event, or database provenance |
| Total info entry | Bounded current-state context envelope |
| Local field short answer | Offline or degraded-mode domain response |

The mapping changes vocabulary and evidence adapters. It does not change the
core contract: deterministic evidence operations, compact grounded context,
model-authored synthesis, independent verification, and honest failure
escalation.

## Current Promotion Debt

- Streaming transport timeouts do not yet enter the context-full continuation
  path in the 2026-07-16 fallback replay.
- Automatic quality screens remain conservative and are not a replacement for
  human wording review.
- Local 1.7B language quality still has known Chinese glyph and phrasing errors.
- UPS/power evidence must be reported as unavailable when the relevant hardware
  telemetry is absent.

These are bounded defects. They do not invalidate the reusable domain
adaptation architecture.
