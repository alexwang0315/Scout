# Scout AI EXP-Only Praison Evidence-Gap Hookup

## Experiment Packet

- Experiment ID: `SCOUT-AI-EXP-PRAISON-GAP-HOOKUP-001`
- Date: `2026-09-01`
- Mode: `WORKING PROTOTYPE`
- Decision: `ACCEPT_EXPERIMENTAL`
- Authority: `candidate_only=true`, `runtime_safety_truth=false`

## Hypothesis

An EXP question with no deterministic field answer can send a request-bound,
route-aware research question through the MCP-isolated Praison Research
specialist, then inject only a Pydantic-gateway-accepted candidate evidence card
into the existing answer evaluator. The intelligence result must never supply a
decision, permission, or runtime safety truth.

## Implementation

The feature remains disabled by default. It runs only when all of the following
are true:

1. `--exp-praison-intelligence` is explicitly enabled;
2. the question force is `EXP`;
3. deterministic Scout tools produced no non-empty `field_answer`;
4. the MCP response passes the Pydantic Contract Gateway;
5. the response contains both findings and evidence;
6. the local evaluator allowlist accepts the candidate card.

The deterministic Workspace projection now prefixes the research question with
its bounded route name. For the Chilai Nanhua Workspace, the generic question
was changed from:

```text
沿途有沒有古道、警備道或舊產業道路？
```

to the request-bound search question:

```text
路線「奇萊南華」：沿途有沒有古道、警備道或舊產業道路？
```

The exact route-aware research question is included in the Workspace input hash.
Changing the route name therefore changes the request binding instead of
silently reusing an earlier result. No model is permitted to choose or rewrite
the route binding.

## Live Evidence

### Fail-Closed Baseline

The earlier `EXP-071` run reached the real Praison service and called
`web.search`, but returned zero findings and zero evidence. The bridge recorded
`status=degraded`, injected no card, and the deterministic answer remained
UNKNOWN. This proves the no-evidence path fails closed.

### Route-Bound Live Web

A real MCP/Praison live-web request for `EXP-016` used this path:

```text
Pydantic IntelligenceRequest
  -> stdio MCP
  -> Praison orchestrator
  -> deterministic Praison router
  -> Research specialist
  -> web.search
  -> web.fetch x2
  -> Pydantic Contract Gateway
```

Observed result:

- request ID: `3d0a2492-8d89-4198-b3b0-0975c0768e15`;
- gateway status: `ok`;
- remote validation: `accepted_candidate`;
- findings/evidence: `2/2`;
- sources: two bounded `hiking.biji.co` pages;
- output hash:
  `a19bb1261e96fa149063160ec3e09d1635e06daeeac3e210855ed02bc570308c`;
- candidate decision: `null`;
- permission field: absent;
- candidate-only: `true`;
- runtime safety truth: `false`.

The two candidate records mention the Nenggao Crossing Trail and the Tunyuan
industrial road. They are route-relevant but remain unreviewed web evidence and
do not prove that every historical-road category in the question exists.

### Evaluator Composition

A faithful evaluator replay used the real MCP/Praison bridge and an in-process
model stub only for final response synthesis. The evaluator observed:

- `local_injection_status=accepted_candidate`;
- the allowlisted candidate tool in `selected_tools` and the model evidence
  cards;
- `candidate_mser_reprojection=false`;
- final `decision=null` for the factual-context question;
- final verifier `PASS`;
- no authoritative state mutation.

The in-process synthesis stub isolates evidence composition from provider
availability. It is not a claim about OpenRouter model quality.

## Rejection Qualification

Focused tests reject candidate cards that attempt any of the following:

- `candidate_only=false`;
- `runtime_safety_truth=true`;
- a non-null runtime decision;
- a permission result;
- executable instructions from external intelligence;
- a non-allowlisted tool ID;
- injection outside EXP;
- injection beyond the ten-tool budget.

The receipt schema itself now fixes the authority flags as `Literal[True]` and
`Literal[False]`. Injected cards also require
`untrusted_intelligence_output=true` and
`external_instructions_executable=false`.

## Known Limits

- The configured OpenRouter key remains intentionally commented, so a fresh
  OpenRouter final-synthesis run was not performed. No credential setting was
  changed for this experiment.
- Search transport success is not topical sufficiency. `EXP-067` found a
  route-adjacent seasonal page that did not directly answer the cloud-sea
  question; it is retained as evidence that relevance needs a separate gate.
- One live fetch followed a site redirect to a less-specific canonical URL.
  Redirect/source identity should be made explicit before production promotion.
- Query decomposition is deterministic route binding, not model-generated
  research planning.
- The feature remains experimental and has no production Dashboard activation.

## Verification

- Main Scout focused suite: `199 passed, 6 skipped`. The six skips are the
  optional real-Praison cases in the main environment.
- Isolated PraisonAI 1.7.0 suite: `44 passed` with no skips.
- Scoped Ruff: PASS.
- `git diff --check`: PASS.
- Live route-bound MCP/Praison request: PASS.
- Faithful evaluator composition with the live bridge: PASS.

## Rollback

Disable `--exp-praison-intelligence` or remove the EXP bridge and its evaluator
hook. The existing Pydantic Agent, deterministic tools, MSER, reducers,
permission, mission, route, safety, notification, and hardware paths require no
state or schema rollback.
