# Scout AI current architecture

This diagram describes the verified candidate-only integration boundary. It is
not an authority graph: deterministic Scout policy owns execution, provenance,
permission, safety, mission state, and hardware effects.

```mermaid
flowchart LR
    user["User / voice / API"] --> entry["Dashboard or Answer Gateway"]
    device["Pi sensors / device observers"] --> evidence

    subgraph control["Scout answer reliability kernel — deterministic owner"]
        entry --> contract["QuestionContract compiler\nintent / criticality / authority\nrequired evidence dimensions"]
        contract --> evidence["Workspace / evidence compiler\nWorkspaceQueryService\nretrieval / freshness / provenance"]
        evidence --> mser["MSER compiler + SufficiencyCertificate\nmissing / stale / conflict / ambiguous\nMSERAnswerVerifier"]
        mser --> policy["Deterministic Jev Runtime Compiler\nallowlisted tools / policy / audit receipt"]
        policy --> synth["Structured synthesis\nScout Model Gateway"]
        synth --> verifier["Claim verifier / recovery\nUNKNOWN / conflict / candidate answer"]
        verifier --> audit["Audit + provenance ledger\nsource refs / hashes / model trace"]
    end

    subgraph candidate["Candidate intelligence — never runtime safety truth"]
        jev["Jev Decision Plane\nOpenRouter Decisions endpoint\nroute / evidence triage / escalation"]
        praison["PraisonAI via MCP\nonly MSER InformationNeed\nresearch / decomposition candidates"]
        max["Modular/MAX backend\nonly sufficient MSER + synthesis failure\npreflight-gated model recovery"]
    end

    contract -. "bounded compact contract\nno paths / raw GPX / coordinates" .-> jev
    jev -. "candidate typed decision\nno SQL / GIS args / authority" .-> policy
    mser -. "InformationNeed only" .-> praison
    praison -. "validated candidate evidence" .-> evidence
    mser -. "sufficient + synthesis failure" .-> max
    max -. "structured candidate output" .-> synth

    subgraph deterministic["Deterministic runtime execution"]
        db["Read-only DB / workspace tools"]
        gis["QGIS / GIS spatial worker\ncandidate spatial outputs"]
        refresh["Freshness / source refresh\nallowlisted and auditable"]
        reducers["Permission / safety / mission reducers\noperational authority"]
    end

    policy --> db
    policy --> gis
    policy --> refresh
    policy --> reducers
    db --> evidence
    gis --> evidence
    refresh --> evidence
    reducers --> audit

    subgraph runtimes["Inference backends"]
        local["LOCAL_FAST / HAILO / Pi CPU"]
        cloud["Cloud reasoning / research"]
    end
    synth --> local
    synth --> cloud
    local --> audit
    cloud --> audit

    verifier --> output["Dashboard candidate answer / report"]
    audit --> output
    audit --> device_out["Pi display / observer telemetry\nread-only candidate presentation"]

    classDef deterministic fill:#dbeafe,stroke:#1d4ed8,color:#0f172a;
    classDef candidateNode fill:#fef3c7,stroke:#b45309,color:#451a03,stroke-dasharray: 5 5;
    classDef effect fill:#fee2e2,stroke:#b91c1c,color:#450a0a;
    classDef outputNode fill:#dcfce7,stroke:#15803d,color:#052e16;
    class contract,evidence,mser,policy,synth,verifier,audit,db,gis,refresh,local,cloud deterministic;
    class jev,praison,max candidateNode;
    class reducers effect;
    class output,device_out outputNode;
```

## Boundary legend

| Surface | Candidate-only | Runtime safety truth | Authority |
| --- | --- | --- | --- |
| Jev | `true` | `false` | typed routing suggestion only |
| PraisonAI / MCP response | `true` | `false` | untrusted evidence until contract validation and MSER reprojection |
| MAX output | `true` | `false` | model backend; no direct tool or state authority |
| QGIS / terrain / risk artifacts | `true` | `false` | spatial hypothesis or evidence candidate |
| MSER certificate, deterministic reducers, provenance ledger | candidate envelope retained | never promoted by model output | Scout deterministic runtime |
| permission, safety, mission, notification, hardware control | not model-generated | owned by existing deterministic policy | external effects require explicit runtime authority |

## Routing invariants

1. Static and aggregate questions use the deterministic fast lane; Jev is not
   called.
2. Spatial, cross-artifact, ambiguous, and recovery cases may make one batched
   Jev request. Its output is compiled through the deterministic contract and
   cannot become SQL, GIS arguments, permission changes, safety truth, or a
   hardware command.
3. MSER is the hard evidence gate. Jev cannot turn missing, stale, contradictory,
   or ambiguous evidence into `SUFFICIENT`.
4. PraisonAI is available only when MSER emits an `InformationNeed`; its MCP
   response is candidate evidence and must be reprojected through MSER.
5. MAX is available only when MSER is sufficient, deterministic synthesis or
   structured output has failed, the selected model is allowed, and MAX preflight
   is ready. Otherwise the route fails closed to human review or an evidence gap.
6. Every generated artifact retains `candidate_only=true` and
   `runtime_safety_truth=false`; provenance, hashes, freshness, and authority
   are deterministic fields.
