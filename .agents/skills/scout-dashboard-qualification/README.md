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
    "qualification:seed": "node scripts/qualification/seed.mjs",
    "test:e2e:qualification": "playwright test tests/e2e/qualification",
    "qualification:bundle": "node scripts/qualification/build-evidence.mjs",
    "qualification:verify-evidence": "node scripts/qualification/verify-evidence.mjs",
    "qualification:gpt-review": "node scripts/qualification/run-gpt-review.mjs",
    "qualification:enforce-verdict": "node scripts/qualification/enforce-verdict.mjs",
    "qualification:check": "node scripts/qualification/run-on-demand.mjs --scope auto",
    "qualification:check:full": "node scripts/qualification/run-on-demand.mjs --scope full",
    "qualification:check:smoke": "node scripts/qualification/run-on-demand.mjs --scope smoke"
  }
}
```

## Recommended first use

Start with Bootstrap mode and select four representative slices when available:

- Trip Intake validation
- Mission Baseline Save/Accept
- Debug provenance
- Emergency sandbox receipt semantics

Do not claim full Dashboard coverage until every active capability in the manifest has passed deterministic and independent review.


## Human Review Gate

Version 1.2 is read-only by default during qualification. Failed or uncertain items are classified and written to `review-items.json`; Codex must not automatically patch them. The user chooses `APPROVE_FIX`, `REJECT_FIX`, `DEFER`, `KNOWN_ISSUE`, `SPEC_CHANGE`, or `REQUEST_MORE_EVIDENCE`.

Severity uses 1–5 with 5 most severe, and every issue is independently tagged by abstraction level, system layer, defect nature, impact scope, reproducibility, confidence, user/data/authority effect, and fix risk.


## On-demand regression

When no mode is specified, the Skill defaults to an on-demand, read-only regression check. It inspects committed and uncommitted changes, reruns the relevant browser suite and global Scout invariants, then compares the result with the most recent hash-verified `QUALIFIED` evidence packet.

The report highlights newly broken capabilities, new flakiness, lost evidence, semantic drift, and newly added capabilities. A failed run creates classified review items and stops at the Human Review Gate; it never repairs the repository automatically.
