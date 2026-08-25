# Scout Praison Live Web Qualification

Date: 2026-08-25
Mode: Aggressive Construction Mode
Outcome: WORKING PROTOTYPE

## Experiment

- Experiment ID: `SCOUT-PRAISON-WEB-001`
- Hypothesis: the MCP-isolated Praison Research specialist can execute bounded
  live web search and fetch while preserving Scout candidate-only authority.
- Baseline: Research analyzed only task-bound Workspace evidence and conflicts;
  the service rejected `deep_research` and had no network toolset.
- Decision: `ACCEPT` as an experimental candidate-intelligence path.

## Implemented Path

```text
Scout Core
  -> IntelligenceRequest(task_type=deep_research)
  -> CapabilityGrant(web.search, web.fetch)
  -> scout_deep_research_candidate MCP tool
  -> isolated Praison AgentTeam
  -> Research specialist
  -> bounded live search
  -> domain-scoped public-page fetch
  -> typed WebEvidenceProvenance
  -> IntelligenceResponse(candidate_only=true)
  -> PydanticContractGateway
```

Terrain routing is unchanged: pure terrain still uses Terrain plus deterministic
QGIS ingestion and skips Research unless bound conflict evidence exists.

## Authority And Security

- `WebResearchScope` requires a non-empty server-owned domain allowlist.
- `deep_research` requires both `web.search` and `web.fetch` grants.
- Search plus configured fetches must fit the task-bound tool-call budget.
- URL credentials, non-HTTP schemes, localhost, private IP literals, private DNS
  resolution, blocked domains, and out-of-scope redirects fail closed.
- External page excerpts are explicitly marked untrusted and prompt-injection
  content is treated as data, never as a tool request.
- URL, query, rank, provider, fetch time, status, media type, byte count,
  truncation, and content hash are preserved as typed provenance.
- Every finding and evidence record remains `candidate_only=true` and
  `runtime_safety_truth=false`.
- Search/fetch failure produces typed uncertainty and no invented finding.

## Live Evidence

### Official Pydantic Documentation

- Request ID: `3a1c7a46-77d3-4438-84ef-a69191c41999`
- Elapsed: 9060 ms
- Result: PASS
- Agent path: `praisonai.orchestrator -> deterministic router -> research`
- Tools: `web.search`, `web.fetch`, `web.fetch`
- Evidence count: 2
- Finding count: 2
- Core validation: accepted candidate
- Sources: Pydantic AI changelog and Pydantic validation changelog

### Scout-Domain Official Source

- Request ID: `9ad85e02-1714-4208-a949-8b88e9f35be4`
- Allowed domain: `cwa.gov.tw`
- Elapsed: 11337 ms
- Result: PASS
- Tools: `web.search`, `web.fetch`, `web.fetch`
- Evidence count: 2
- Finding count: 2
- Core validation: accepted candidate
- Sources: CWA CODiS and the CWA station information surface
- Uncertainties: none reported by this acquisition run

The source summaries are search-derived candidate descriptions. They are not a
weather observation, route fact, reviewed baseline, or runtime safety fact.

## Automated Qualification

- Isolated Python 3.12 environment
- `praisonaiagents==1.7.0`
- `pydantic-ai-slim==2.33.0`
- Focused contracts, MCP, Praison, web security, background queue, model gateway,
  edge resource, and runtime qualification tests: 132 passed
- Real MCP process and real Praison AgentTeam were exercised; no Praison tests
  were skipped in the isolated environment.
- Lazy-loading the live web backends reduced clean MCP server import time from
  about 4.4 seconds to about 1.4 seconds on this host.

## Remaining Promotion Debt

- The working path uses deterministic query/fetch orchestration and Praison
  AgentTeam delegation. Model-generated query decomposition and synthesis remain
  a separate qualification, not an implied success.
- Search ranking can return topically adjacent official pages; relevance must be
  evaluated separately from transport and authority correctness.
- DNS is checked before each request and redirect, but production promotion
  should use a network sandbox or egress proxy that pins destinations and blocks
  private address ranges at the transport layer.
- This mode is explicit and experimental; the default Scout runtime is not
  silently given network access.
