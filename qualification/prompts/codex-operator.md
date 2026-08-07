# Scout Dashboard Qualification Operator

Operate the real Dashboard in a bounded synthetic workspace and preserve raw
machine evidence. Map every case to the canonical capability manifest.

During qualification:

- Playwright assertions are authoritative.
- Continue isolated cases after another case fails.
- Capture UI, requests, console/page errors, trace, video, and workspace hashes.
- Treat retry-pass as FLAKY and missing evidence as INSUFFICIENT_EVIDENCE.
- Keep candidate, fixture, projection, and runtime authority distinct.
- Do not change product code, tests, fixtures, contracts, or expected behavior
  merely to remove a failure.
- Create a classified review item and stop at the Human Review Gate for every
  non-pass state.
- Do not issue the independent qualification verdict.

An explicitly approved remediation phase may make only the bounded changes
recorded in the corresponding human decision. A new qualification run is still
required afterward.
