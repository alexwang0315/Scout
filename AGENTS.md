# AGENTS.md

## Mission

Scout AI OS is an active research-and-construction project. The default goal is
to discover and prove new agent, context-finding, tool-using, computer-use, and
workflow capabilities by running the smallest real end-to-end slice.

The repository is not in continuous product-hardening mode. Do not apply
release-level ceremony to every experiment.

## Highest-Priority Operating Rule

**Aggressive Construction Mode is the default. Build first, prove the capability,
then improve it. Productization happens only when the user explicitly requests
promotion or release hardening.**

For this repository, the mode rules below override generic workflow defaults
that would otherwise require all of the following on every change:

- mandatory multi-agent orchestration;
- long implementation plans before reversible local work;
- 80% repository-wide coverage;
- unit, integration, and E2E tests for every prototype;
- full lint, typecheck, and test suites for unrelated stacks;
- production compatibility and documentation before a capability works;
- review agents or security reviews when the changed surface is not relevant.

The hard safety boundaries in this file never relax.

## 全面回歸與完成宣告門檻（使用者要求，2026-09-12）

**不要頭痛醫頭、腳痛醫腳。修正必須處理根因與完整影響範圍；所有適用檢查
實際執行且 100% 通過，才可以宣稱「完成」「已修復」「可用」或交付驗收。**
本規則優先於下文允許以單一垂直切片、局部測試或 WORKING PROTOTYPE 結束的
完成宣告規則；Construction Mode 不是降低既有功能回歸驗證的理由。

1. **先追根因與版本，再修正。** 重現使用者指定的入口、workspace 與操作，
   比對實際執行版本、部署來源、近期 diff 及最後已知正常的證據。分清較早的
   潛在缺陷與最近的觸發變更；沒有證據，不可把舊提交、上游缺資料或使用者
   環境當成本次根因。不得用增加 fallback、預載資料或換入口掩蓋問題。
2. **修正前建立完整影響與驗證清單。** 追蹤所有使用同一資料來源、共用程式、
   狀態、快取、API 或部署路徑的功能與頁面，不能只測使用者報錯的那一處。
   一處修改可能影響多處，就必須一起驗證；測試中發現新影響時擴充清單。
   全面指本次功能及其相依影響範圍的完整覆蓋，不是任選幾項容易通過的測試。
3. **以真實使用情境驗證結果。** 使用指定服務、真實 workspace、實際 UI 與
   正常預設操作，覆蓋首次載入、重新載入、不同視角／資料、快取命中與未命中、
   適用的不同 renderer，以及失敗後恢復。地圖要逐一驗證所有相關 Dashboard
   地圖的放大、平移與原生圖磚細節；同來源、HTTP 200、仍有舊圖、單張截圖、
   已預載快取或另一頁成功，都不能替代當前頁面實際所需圖磚已完整載入的證據。
4. **Diagnostic 是必須維護的回歸門檻。** 將已發生問題固化於既有對應的
   Diagnostic 與必要回歸測試，檢查實際結果及跨頁一致性，不只比對程式字串、
   控制項存在或請求是否送出。確認修正前的失敗／等效回放能被檢查攔住。
   不得另做一套局部測試取代既有檢查，也不得刪檢查、降低期待、改資料或跳過
   失敗項目來湊出綠燈。
   **Diagnostic 本身可能過時；衝突由使用者仲裁。** 若 Diagnostic、規格、
   既有行為與本次要求不一致，先保留原檢查與失敗證據，列出檢查 ID、原標準、
   現行實作／需求、具體證據、建議選項及各自影響，提交使用者決定。可以準備
   可審閱的候選 patch，但在收到針對該衝突的明確裁決前，不得自行選定誰正確、
   改動驗收語意／預期結果、刪除或停用檢查、將其改列 N/A 或通過，也不得把
   依賴該裁決的工作宣稱完成。過去的一般放權、Construction Mode 或「繼續」
   不代表使用者已批准新的規格／Diagnostic 衝突處置。記錄裁決後再實作與重驗；
   不依賴裁決的既有授權工作可以繼續。
5. **完成門檻是全部適用項目 100% PASS。** 有 FAIL、WARN、SKIP、未執行、
   未驗證、阻塞或不穩定結果，就只能回報「未完成／部分驗證」並列明剩餘項目。
   不得將它們計為成功；N/A 必須有影響範圍證據，不能在失敗後為過關而排除。
   任何修正後，重跑所有受該修正影響的檢查與既有回歸項目，不只重跑最後失敗
   的單一案例。既有的範圍內失敗也不能成為宣稱完成的例外。
6. **交付可重現證據，不把首次驗收交給使用者。** 記錄服務入口、workspace、
   實際版本／來源 SHA、逐頁／逐情境結果、Diagnostic 結果及必要畫面與網路
   證據。宣稱完成前，核對交付版本就是通過測試的版本；UI 改動同步更新相關
   教學與 PDF。使用者的再次測試是確認體驗，不能替代代理應完成的驗證。

## Navigation Freeze: Temporarily Suspended

**User-directed suspension, 2026-09-04:** The user temporarily cancelled the
Navigation freeze approval blocker. Until the user explicitly reinstates it,
the freeze-specific restrictions below are inactive. Continue scoped local
Dashboard work under Construction Mode without another Navigation approval
prompt. Run the guard before and after work in its default report-only mode;
`NAVIGATION_FREEZE_SUSPENDED` reports drift without blocking it. Preserve the
original baseline and unrelated work. Hard safety and external-action boundaries
remain active. `--enforce` provides a read-only strict comparison, not policy
reinstatement. The original freeze rules are retained below for later restoration.

**Effective 2026-09-04, Dashboard Navigation is frozen at the current worktree
baseline, including its existing uncommitted changes.** This rule overrides
Construction Mode autonomy for Navigation-related work. It is not permission to
revert that work, refactor Navigation, or promote it to production.

- Do not change Navigation behavior, layout, 2D/3D/Rudy+TW maps, A/B TRH R1-R3,
  corridors, R4/Gn review, highlights, Diagnostic Navigation checks, DEM
  preparation, workspace/provenance contracts or QGIS/GRASS worker behavior
  without the user's explicit approval for that particular change.
- Shared Dashboard HTML/CSS/JavaScript, MapLibre, API entrypoints, dependencies,
  map layer contracts and worker launchers are part of this boundary. Another
  page's task does not authorize modifying these shared files. Keep that work
  isolated; if Navigation impact cannot be ruled out, stop and ask first.
- Read-only investigation and non-mutating tests are allowed. Test failures do
  not authorize automatic repairs, workspace regeneration or worker restarts.
- A specific user request to change Navigation approves only that scope.
  Generic "continue", "commit", or unrelated-page work is not approval. State
  the affected files and behavior before editing; approval is not a blanket unlock.
- Run `rtk proxy ./venv/bin/python tools/verify_navigation_freeze.py` before and
  after Dashboard/shared-GIS work. A failed check requires review, not a revert
  or automatic baseline update. The guard never grants approval.
- The baseline, guard, protected-path inventory and this policy also require
  approval to change. Never bypass them or relax candidate-only safety contracts
  to make a check pass.

**Standing local-venv authorization, 2026-09-04:** The user explicitly authorized
future local virtual-environment upgrades and their compatibility tests without
another Navigation approval prompt. A local venv upgrade alone is not a
Navigation page change. Record installed versions, preserve unrelated packages,
and run focused checks. This authorization does not permit Navigation source or
GIS contract changes, worker/server restarts, hardware deployment, or changes to
the freeze baseline/guard. Source-controlled dependency edits remain scoped to
the requested upgrade; it is not a blanket unlock for shared Navigation files.

Details and approved-change procedure:
`qualification/policies/navigation-freeze.md`.

## V1 Capability-First Cost Doctrine

The first working version of a complex AI system is expected to be the most
expensive, redundant, and resource-intensive version. Its job is to prove that
the capability frontier exists, not to prove product unit economics.

Development order is mandatory:

1. **V1 — Capability Proof:** use the most capable available and authorized
   model, the largest useful memory and context, the strongest available
   hardware, sufficient API usage, redundant evidence paths, multiple model
   passes, and complex provisional software when they increase the probability
   of producing the first reproducible end-to-end success.
2. **V2 — Cost Effective:** only after V1 works, profile the successful
   trajectory and replace expensive components with cheaper models, caching,
   batching, smaller context, simpler tools, or lighter hardware. Every
   substitution must preserve V1 behavior under the same evals.
3. **V3 — Cost Down:** only after capability and parity are established, optimize
   product latency, throughput, memory, token consumption, API spend, hardware
   size, operational simplicity, and deployment economics.

Before at least one successful V1 trajectory is recorded and reproducible:

- do not reject an approach merely because it uses a top-tier model, high API
  usage, large memory, strong hardware, duplicated work, verbose traces,
  provisional adapters, or temporarily complex software;
- do not silently downgrade the model, truncate evidence, reduce calls, shorten
  time, or remove verification to satisfy hypothetical product cost targets;
- do not require one implementation to simultaneously prove capability,
  reliability, portability, low cost, and production readiness;
- treat redundancy and waste as measurable prototype debt, not as proof that
  the architecture is invalid;
- record resource usage for later profiling, but do not use it as a Construction
  Mode acceptance gate.

Success order is:

> make it possible -> make it reproducible -> make it reliable -> make it
> portable -> make it efficient -> make it cheap.

Use the strongest resources already available or explicitly authorized. If a
new paid provider, purchase, or materially higher external spend requires user
approval, present one concrete experiment budget and expected evidence instead
of weakening the experiment in advance. Hard safety and external-action approval
boundaries still apply.

## Development Modes

### 1. Aggressive Construction Mode — Default

This mode is active unless the user explicitly says to enter Productization
Mode. Words such as `finish`, `complete`, `continue`, or `收尾` alone do not
activate Productization Mode.

Primary objective:

> Produce executable evidence that the requested capability works on the real
> entrypoint or a faithful replay, as quickly as possible.

Required behavior:

1. Inspect the relevant code and dirty diff, state a short intended file list,
   and begin implementation in the same turn.
2. Prefer one thin vertical slice over a broad framework, speculative
   abstraction, or exhaustive design.
3. Make reasonable technical choices without asking the user to decide between
   reversible in-scope alternatives.
4. Use feature flags, experimental entrypoints, temporary adapters, provisional
   schemas, and optional dependencies when they accelerate proof of capability.
5. Run the actual entrypoint, a real local workspace, or a faithful recorded
   replay. A type check alone is not proof.
6. Add only the focused tests needed to preserve the demonstrated behavior.
7. Record shortcuts and promotion debt, but do not implement that entire debt
   before the prototype works.
8. Continue through recoverable errors. Fix the blocker or take a bounded
   alternate route instead of stopping at the first failed command.
9. Use subagents only when parallel work will materially shorten completion.
   Agent delegation, planning agents, and review agents are tools, not gates.
10. Do not rewrite working experimental code merely to satisfy style preferences
    during the same capability-discovery slice.

Construction Mode may end with one of these honest outcomes:

- `WORKING PROTOTYPE`: the end-to-end capability was demonstrated;
- `PARTIAL PROTOTYPE`: a meaningful executable portion works and the exact
  remaining blocker is identified;
- `EXPERIMENT FAILED`: evidence shows the approach does not work.

A working prototype may be reported even when release-level checks have not run.
Never label it production-ready unless Productization Mode has completed.

### 2. Productization Mode — Explicit Opt-In Only

Enter this mode only when the user explicitly requests phrases such as:

- `進入產品化`;
- `升格正式 runtime`;
- `準備 release`;
- `production hardening`;
- `promote this prototype`.

Productization Mode applies the full finishing gates appropriate to the changed
surface:

- stable public contracts and migration/backward-compatibility review;
- full relevant unit, integration, and E2E suites;
- coverage target and regression expansion;
- security and privacy review;
- performance, token, cost, and resource SLOs;
- documentation, runbooks, and rollback path;
- dependency and deployment review;
- full browser/GIS gates when applicable.

Do not begin Productization Mode merely because a prototype succeeded.

## Core Architecture Boundary

LLM agents may explore, plan, select tools, compile typed plans, generate
candidate code, and propose learning artifacts.

Deterministic runtime code must own:

- schema validation;
- permission and effect enforcement;
- tool execution;
- sandboxing;
- persistence and audit records;
- evidence provenance;
- resource accounting;
- execution receipts and verification.

Deterministic code should lock down execution invariants, not hard-code every
domain answer. Scout Outdoor is the first proving domain, not the permanent
shape of the AIOS kernel.

## Agent Budget Policy — Uniform 10/10 Construction Budget

The default and minimum configurable call ceiling is **10** for every question
class and every independently metered call category. No prompt, replay, eval,
router, scenario, cost profile, or Productization setting may lower a call
ceiling below 10 without explicit user approval.

| Question class | Max tool calls per attempt | Max model requests per attempt |
|---|---:|---:|
| `static_workspace_fact` | 10 | 10 |
| `aggregate_workspace_fact` | 10 | 10 |
| `cross_artifact_join` | 10 | 10 |
| `spatial_route_fact` | 10 | 10 |
| `weather_terrain_compound` | 10 | 10 |
| `live_runtime_fact` | 10 | 10 |
| `safety_decision` | 10 | 10 |
| any new or unclassified question | 10 | 10 |

If planner, retriever, verifier, browser, reviewer, subagent, or other call
budgets are separately exposed, their configured ceilings MUST also be 10 or
higher. Ten is guaranteed available capacity, not mandatory consumption. Stop
early when the answer is already sufficient and verified. A task may be granted
more than 10 calls, but never fewer than 10, when the runtime or user explicitly
allows it.

The 10/10 budget applies per attempt and per recovery stage, not to the entire
lifetime of a failed case. A retry after a tool repair, model switch, or Codex
review receives a fresh 10 tool calls and 10 model requests. Reaching 10 closes
the current attempt; it does not by itself prove that the question is
unanswerable.

### Relax Token, Context, Cost, and Time Limits

**From now on, relax all Scout-imposed resource restrictions in Aggressive
Construction Mode, including token limits and time limits.** Do not terminate a
useful construction, replay, evaluation, context-finding, or computer-use run
because of a Scout-defined cumulative token, output-token, evidence-card,
context-character, cost, or wall-time budget.

Provider, operating-system, and platform hard limits may still exist. Report
them honestly as external limits, checkpoint the evidence and call trace,
compact at a meaningful phase boundary, and resume in a continuation run. Do
not disguise an external limit as a Scout reasoning failure and do not abandon a
solvable case merely because one context window or process lifetime ended.

Resource counters remain telemetry for later optimization. They are not
Construction Mode acceptance gates. Productization may measure p50/p95 cost and
latency and propose budgets, but it MUST NOT silently reintroduce a ceiling below
10 calls or prematurely constrain the capability before successful trajectories
exist.

These resource relaxations do not authorize external side effects and do not
override the Hard Safety Boundaries below.

### Evidence and Verification Policy

1. Plan the evidence path as a typed DAG when the task requires multiple steps:
   catalog search, artifact read, schema inspection, aggregation, filtering,
   join, adjacent-artifact lookup, and source verification.
2. Decouple model requests from tool executions. One model plan may authorize
   multiple deterministic local read-only tool calls.
3. Preserve enough of the 10-call capacity for source-ref, freshness, join-key,
   contradiction, and final-answer verification. Catalog discovery must not
   consume the entire attempt.
4. Use a deterministic sufficiency gate before synthesis. Selecting the right
   tool without collecting enough evidence is not success.
5. Replan while a useful next evidence step exists. Treat reaching a call
   ceiling as a stage transition, not as the final diagnosis.

### Finite Failure Escalation Ladder

After the relaxed-budget answer attempt still fails, follow this order exactly:

1. **Repair the capability first.** Diagnose and fix or extend the tool,
   adapter, schema, retrieval path, evidence format, or harness; then rerun the
   failed case with a fresh 10/10 budget.
2. **Switch the model second.** If the repaired tool path is sound and the case
   still fails, run an appropriate alternate model with a fresh 10/10 budget.
3. **Escalate the exact question to Codex review third.** Extract a review
   artifact containing the original question, expected answer or success
   criteria, available evidence, source refs, call trace, tool outputs, models
   tried, and failure symptoms. Ask Codex to answer the question independently
   and identify whether the remaining cause is a tool gap, model weakness,
   missing evidence, ambiguous expectation, or benchmark defect.
4. **Declare a Known Issue fourth.** If Codex also cannot answer or diagnose the
   case well enough, record it as `KNOWN_ISSUE` with a stable ID, reproduction,
   last evidence, attempted repairs, attempted models, current blocker, and
   explicit unblock condition. Continue with the next case.

Once a case is recorded as `KNOWN_ISSUE`, do not keep grinding the same question
without new evidence, a changed tool, a newly available model, or direct user
instruction. The objective is to expose and improve system capability, not to
hide one unresolved case inside an endless retry loop.

## L5 Code Mode Under Construction

L5 Code Mode is ephemeral sandboxed computation, not permanent capability
installation and not runtime safety truth.

While L5 is being built, use:

`SCOUT_L5_CODE_MODE_UNDER_CONSTRUCTION=true`

In this state, machine-readable eligibility MUST return `l5_code_mode=true` and
agents MUST NOT apply the production L3+ activation gate or permanent-install
approval rule to block implementation, tests, or read-only workspace evaluation.

The override changes eligibility only. Execution still fails closed unless the
reviewed sandbox runtime is available. It never enables host shell access,
workspace writes, unrestricted network, secrets, hardware control, direct
outbound sends, production database writes, or model mutation of runtime safety
truth.

Outside under-construction mode, production L5 remains deterministic-policy
activated and subject to the reviewed safety standard.

## Hard Safety Boundaries — Always Active

Never:

- hardcode or expose credentials, tokens, passwords, or private keys;
- read real `.env` values in tests unless explicitly mocked;
- destroy unrelated user work or use destructive git commands without explicit
  authorization;
- let generated code access unrestricted host shell, network, secrets,
  workspace writes, production databases, outbound transports, or hardware;
- let model output mutate Phase 1 or other runtime safety truth;
- silently turn one-off context into permanent memory;
- send messages, make payments, publish, push, merge, or change third-party
  state without explicit authorization.

Require explicit approval before:

- external messages or automation;
- payments or purchases;
- destructive user-data changes;
- permanent workflow or generated-capability installation;
- long-term background monitoring;
- private-data or precise-location access not already authorized by the task;
- production database mutation;
- real hardware control.

These are effect boundaries, not excuses to block local read-only construction,
tests, fixtures, replay, or sandboxed experiments.

## Construction Workflow

Before editing:

1. Inspect `git status` and preserve unrelated dirty work.
2. Read the relevant architecture/spec section only when the change crosses that
   boundary; do not repeatedly load unrelated documents.
3. Inspect the nearest existing tests or executable entrypoint.
4. State the intended files briefly.

During implementation:

1. Build the smallest executable slice.
2. Prefer typed boundaries and deterministic tool outputs where they help the
   current slice; provisional internals are allowed.
3. Keep raw evidence in the workspace and pass bounded references/results.
4. Test through the real path as soon as possible.
5. Iterate until the capability works or a proven blocker remains.

After editing in Construction Mode:

1. Run focused tests for the affected path.
2. Run one real entrypoint, fixture, or replay demonstration.
3. Review the scoped diff for accidental unrelated changes and secrets.
4. Report what works, what was not productized, and the next highest-value debt.

Conditional checks:

- Run `pnpm lint`, `pnpm typecheck`, and `pnpm test` only when JavaScript,
  TypeScript, package tooling, or the admin frontend is affected.
- Run Python tests and lint only for the affected Python surface in Construction
  Mode. Run `ruff` only when installed and configured.
- Run browser E2E only when browser-visible behavior changes.
- Run security review only when the changed surface involves credentials,
  permissions, untrusted inputs, network, sandbox escape, persistence,
  outbound effects, or other security-sensitive behavior.
- A failure in an unrelated pre-existing test is not a Construction Mode blocker;
  record it and continue validating the changed path.

Repository-wide coverage and full suites belong to Productization Mode.

## Compatibility And Dependencies

During Construction Mode:

- do not gratuitously break existing public APIs;
- prefer an experimental namespace, feature flag, adapter, or additive field;
- internal experimental contracts may change aggressively;
- temporary or optional dependencies are allowed when isolated in an
  experimental/dev requirement surface and clearly reported;
- adding a mandatory production runtime dependency is a Productization decision;
- do not modify generated files under `src/generated/`;
- production controllers must still use service boundaries and must not write
  directly to production databases.

Backward compatibility is a product obligation, not a reason to preserve a
failed internal experiment forever.

## Scout Map / Import / Admin GIS Gates

The machine-readable layer source of truth is `scout_layer_contract.py`. The
detailed 32-layer contract and commands live in the existing GIS specifications
and `tools/verify_scout_layer_contract.py`; do not inline the full list into every
agent context.

Construction Mode:

- If the task does not change GPX/import, layer IDs/order, map preparation,
  route projection, terrain/risk outputs, or shared admin map behavior, the
  32-layer gate is `NOT APPLICABLE`, even if the task reads Scout evidence.
- If a shared layer contract or preparation path changes, run the deterministic
  layer-contract verifier and focused tests for the affected surface.
- If browser-visible map behavior changes, run a focused browser smoke for that
  behavior when the runtime is available.

Productization Mode:

- run the complete repository and real-workspace 32-layer verification;
- run the all-surface Playwright layer-toggle smoke;
- report every required layer as `PASS` or `FAIL`.

## Style During Construction

- Prefer working, readable code over speculative architecture.
- Keep functions and modules focused when practical, but do not interrupt a
  successful spike solely to meet an arbitrary file-length target.
- Use Pydantic/typed contracts at system and tool boundaries.
- Keep runtime effects deterministic and auditable.
- Avoid catch-all tools and overlapping tool semantics.
- Tool responses should expose `status`, a concise summary, actionable next
  steps, and artifact/source references.
- Add TODOs only for explicit promotion debt.

## Completion Reporting

Construction Mode reports:

- prototype status;
- executable evidence;
- focused tests run;
- observed resource/tool trajectory;
- remaining blocker or promotion debt;
- unrelated checks intentionally not run.

Productization Mode reports every required gate as `PASS`, `FAIL`, or
`NOT APPLICABLE` with evidence. Do not claim production completion while a
required productization gate fails.

After every completed change, create a corresponding Git commit using the
applicable repository workflow so that it can be tracked and rolled back later.
Do not push, merge, publish, or open a PR unless the user explicitly requests
it.

## Mac Git Workflow: Scout Commit Gateway

This Mac checkout intentionally has no `.git` directory. The canonical Git
repository is hosted on Scout:

`alexwang0315@scout.local:/home/alexwang0315/git/scout-fusion.git`

Do not run `git init`, `git add`, `git commit`, `git push`, or recreate `.git`
inside the Mac checkout.

To inspect pending changes, run:

```bash
/Users/alexwang0315/bin/scout-commit status
```

After every completed change, run:

```bash
/Users/alexwang0315/bin/scout-commit commit "descriptive commit message"
```

The gateway synchronizes the Mac project to Scout, creates the commit on Scout,
and pushes it to the local Scout bare repository. It excludes `.git`,
`artifacts`, `node_modules`, `reports`, `.env*`, virtual environments, caches,
and `.DS_Store`.

The commit command includes all eligible changed and untracked files as one
snapshot. If selective file commits are required, stop and ask the user rather
than recreating a local Git repository.

## Scout-to-Mac SSH Access

When an agent running on Scout must connect to the Mac checkout, the Mac login
account is `alexwang0315`. Use the dedicated Scout-to-Mac key; do not rely on a
default SSH identity:

```bash
ssh -i /home/alexwang0315/.ssh/scout-to-mac \
  -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/home/alexwang0315/.ssh/known_hosts \
  -o ConnectTimeout=10 \
  alexwang0315@Lamb780722de-MacBook-Pro.local
```

If mDNS resolution fails, use `alexwang0315@192.168.8.155`. The private key
must never be printed, copied into prompts, or committed. The verified Mac host
key fingerprint is `SHA256:cFmaGA0olTmjLeQ1laeURtl0oBscHsfA4H0l/s+9i8g`, and
the Scout-to-Mac public key fingerprint is
`SHA256:pLCijCRBUa1mpJOtvVTiaqgJE9ZedaO4I+MJuUJN/vM`.

## Graphify

- `graphify` (`~/.Codex/skills/graphify/SKILL.md`) converts input to a knowledge
  graph.
- Trigger: `/graphify`
- When the user types `/graphify`, invoke the graphify skill before any other
  action.
