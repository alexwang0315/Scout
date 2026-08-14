# Scout Dashboard Qualification Skill

## Installation

Copy this directory into one of the locations recognized by your Codex environment, for example:

```text
.codex/skills/scout-dashboard-qualification/
```

or retain it in the repository and instruct Codex to load:

```text
scout-dashboard-qualification-skill/SKILL.md
```

## Invocation examples

```text
Use the scout-dashboard-qualification skill in On-demand regression mode. Check the current Scout worktree against the last trusted qualified baseline and do not modify code.
```

```text
Use the scout-dashboard-qualification skill in Feature qualification mode for the current PR.
```

```text
Use scout-dashboard-qualification in Bootstrap mode. Build only the smallest working vertical slice and stop before broad regression expansion.
```

```text
Use scout-dashboard-qualification in Review only mode against artifacts/qualification/<sha>. Do not modify code.
```

## Suggested repository command aliases

```json
{
  "scripts": {
    "qualification:validate-manifest": "node scripts/qualification/validate-manifest.mjs",
    "qualification:fixture-harness": "node scripts/qualification/run-browser.mjs --fixture-harness",
    "test:e2e:qualification": "playwright test tests/e2e/qualification --grep @live-runtime",
    "qualification:bundle": "node scripts/qualification/build-evidence.mjs",
    "qualification:verify-evidence": "node scripts/qualification/verify-evidence.mjs",
    "qualification:enforce-verdict": "node scripts/qualification/enforce-verdict.mjs",
    "qualification:check": "node scripts/qualification/run-on-demand.mjs --scope auto",
    "qualification:check:full": "node scripts/qualification/run-on-demand.mjs --scope full",
    "qualification:check:smoke": "node scripts/qualification/run-on-demand.mjs --scope smoke"
  }
}
```

`qualification:check*` requires an explicit real runtime URL and project ID, for example through `SCOUT_QUALIFICATION_RUNTIME_URL` and `SCOUT_QUALIFICATION_PROJECT_ID`. GPT Pro review is performed through the Codex in-app browser and is not an npm/API command.

## Recommended first use

Start with Bootstrap mode and select four representative slices when available:

- Trip Intake validation
- Mission Baseline Save/Accept
- Debug provenance
- Emergency sandbox receipt semantics

Do not claim full Dashboard coverage until every active capability in the manifest has passed deterministic and independent review.


## Live-runtime, operation, visual, and review gates

Version 1.5 accepts official evidence only from browser operations against an already-running real runtime Dashboard whose exact URL, port, project, and continuity are recorded. Synthetic and fixture runners are harness-development tools only and cannot produce an official verdict or trusted baseline. The Python qualification-contract suite validates the harness; its test count is never Dashboard feature coverage.

Full qualification reconciles all 23 Dashboard routes, inventories and operates every visible interactive control in the main document and embedded frames, performs six gestures on all nine map surfaces, operates embedded-map directional pan buttons, toggles every exposed canonical and Weather layer plus layer presets and CWA display controls, and captures before/after visual evidence. A disabled-only control or single-value selector is unexercised until a real executable runtime state is supplied. Blur, low-resolution raster scaling, broken imagery, clipping, overflow, occlusion, overlap, blank rendering, unmapped controls, or operations without visible state change are blocking. GPT Pro must inspect every bound screenshot rather than accepting paths or machine scores as visual proof. Screenshot magic bytes must match the filename extension and declared MIME. Evidence roots use an explicitly declared UTF-8 relative-path sort and `{sha256}  {path}\n` line format.

Persistent or outbound controls require a separately authorized reversible real QA runtime/project. Without that authority they remain `EFFECT_AUTHORIZATION_REQUIRED`, and the run cannot claim complete qualification.

Failed or uncertain observations are first written to `candidate-findings.json`. The sealed packet must then be reviewed through `$gpt-pro-collaboration` in the Codex in-app browser. Only reviewed findings may become `review-items.json` entries. Codex then presents every reviewed item to the user and stops. The user chooses `APPROVE_FIX`, `REJECT_FIX`, `DEFER`, `KNOWN_ISSUE`, `SPEC_CHANGE`, or `REQUEST_MORE_EVIDENCE`; only `APPROVE_FIX` permits repair and only `SPEC_CHANGE` permits specification additions or changes.

Severity uses 1–5 with 5 most severe, and every issue is independently tagged by abstraction level, system layer, defect nature, impact scope, reproducibility, confidence, user/data/authority effect, and fix risk.


## On-demand regression

When no mode is specified, the Skill defaults to an on-demand, read-only regression check. It inspects committed and uncommitted changes, reruns the relevant browser suite and global Scout invariants, then compares the result with the most recent hash-verified `QUALIFIED` evidence packet.

The report highlights newly broken capabilities, new flakiness, lost evidence, semantic drift, and newly added capabilities. A failed run creates candidate findings, receives GPT Pro review, then creates classified review items and stops at the Human Review Gate; it never repairs the repository or adds specifications automatically.
