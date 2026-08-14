# Scout Dashboard Qualification Operator

Connect to an already-running real Scout runtime Dashboard and preserve raw
machine evidence. Resolve and record its exact URL, port, real project ID, and
runtime continuity. Never start, seed, replace, or stop the runtime. Map every
case to the canonical capability manifest.

During qualification:

- Playwright assertions are authoritative.
- Continue isolated cases after another case fails.
- Capture UI, requests, console/page errors, trace, video, and workspace hashes.
- Record material browser actions and test the rendered runtime UI; API, fixture,
  unit, or screenshot-only evidence cannot replace browser operation.
- Treat qualification contract tests as harness checks only; never report their
  count as Dashboard functions tested.
- Reconcile and open every contracted route on desktop and large-mobile, scroll
  the full rendered page, and inventory every visible interactive control in
  the main document and every rendered embedded frame.
- Operate each control with before/after UI and screenshot evidence. Any
  unmapped, unexercised, missing, no-state-change, no-visual-change, or
  effect-authorization-required control blocks complete qualification.
- Exercise Fit, zoom in/out, mouse pan, keyboard pan, and rectangle zoom on all
  nine map surfaces. Operate embedded-map directional pan buttons, every layer
  preset, and every CWA product/window/timeline/opacity/play control. Toggle
  every exposed canonical and Weather layer off/on and verify that enabled
  render groups contain visible content.
- Machine-check and preserve blur, sharpness, raster resolution, broken image,
  clipping, readability, overflow, occlusion, overlap, and blank-state evidence.
- Detect each screenshot's media type from magic bytes, require its extension and
  declared MIME to match, and reject the packet before sealing on any mismatch.
- Treat retry-pass as FLAKY and missing evidence as INSUFFICIENT_EVIDENCE.
- Keep candidate, fixture, projection, and runtime authority distinct.
- Do not change product code, tests, fixtures, contracts, or expected behavior
  merely to remove a failure.
- Record every non-pass state as an unconfirmed candidate finding. Seal and hash
  the live-runtime evidence before review.
- Declare evidence-root canonicalization explicitly as UTF-8 lexicographic
  relative-path ordering with exact `{sha256}  {path}\n` lines.
- Hand the sealed packet to `$gpt-pro-collaboration` through the Codex in-app
  browser. Direct API/model review is not accepted.
- Require GPT Pro to inspect every hash-bound screenshot; filenames, counts, or
  pixel metrics alone are not independent visual confirmation.
- Create a classified review item only after GPT Pro's finding-level review,
  then present every reviewed item to the user and stop at the Human Review Gate.
- Do not issue the independent qualification verdict.

A missing, restarted, synthetic, fixture-backed, temporary, or runner-started
Dashboard is `INSUFFICIENT_EVIDENCE`. Never silently assume port 9099.

An explicitly approved remediation phase may make only the bounded changes
recorded in the corresponding human decision. Only `APPROVE_FIX` permits repair
and only `SPEC_CHANGE` permits specification additions or changes. A new live
runtime qualification round is still required afterward.
