[Title] Transfer Scout Skill: <skill_name> to Codex • schema vX.Y.Z • risk <Low/Med/High>

## Summary
- What: <一句話說清楚這個 Skill 做什麼>
- Why: <商業/安全/穩定性理由>
- Scope: <同步影響的服務/工作流/資料表/儀表板>

## Artifacts
- Pydantic Schemas: /skills/<name>/schemas.py  (schema_version=X.Y.Z)
- Examples: /skills/<name>/examples/{valid.json, edge.json, invalid.json}
- API Contract: /docs/<name>-api.md
- Telemetry Spec: /observability/<name>-events.md
- Tests: `make test` ✅

## Release Controls
- Changelog: /CHANGELOG.md (this PR entry)
- Compatibility: works with <downstream>=≥A.B.C ; breaks <legacy>=<X>
- Rollout Plan: <灰度比例/時間表> • Kill-Switch: <flag/path> • Rollback: `make rollback`

## Operations
- Risk Class: <L/M/H> (matrix link)
- Permissions: <IAM role/secret refs> (no hardcoded secrets)
- Data Rules: retention=<N days>, redaction=<rule>, encryption=at-rest+in-flight
- SLO/SLA: P95 <ms>, success-rate > <99.x%>, fallback=<strategy>
- Monitoring: <dashboard link>, alerts=<rules>

## Human-in-the-Loop
- Pauses when: <low-confidence<th>, <write-to-prod>, <policy-trigger>
- Approver Group: <@scout-ops-reviewers>

## On-call & Escalation
- Primary: @name (TZ, phone) • Secondary: @name
- PagerDuty: <service> • SLA: P1 15m/1h, P2 1h/4h

## Checkboxes
- [ ] PII scan passed
- [ ] Security review ✅
- [ ] Threat model updated
- [ ] Data export boundaries verified
- [ ] Docs published & linked
- [ ] Codex label applied: `scout-governance/v1`

## Notes
- Known Risks / Mitigations:
- Post-merge Tasks:
