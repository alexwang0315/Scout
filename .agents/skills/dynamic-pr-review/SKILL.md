---
name: dynamic-pr-review
description: Run a parallel Codex subagent workflow for PR/branch review, then synthesize actionable findings before editing.
---

When invoked, run a subagent workflow.

1. Ask Codex to compare the current branch against main.
2. Spawn one read-only explorer agent to map affected code paths.
3. Spawn one reviewer agent for correctness, security, regressions, and missing tests.
4. Spawn one test-focused agent to identify and run safe targeted tests.
5. Spawn one docs/API researcher when the change depends on framework behavior.
6. Wait for all agents.
7. Return a consolidated report:
   - blocking issues
   - evidence with file/function references
   - confidence level
   - smallest safe fix plan
8. Do not modify code until the user approves the fix plan.
