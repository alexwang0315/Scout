// Test-only ownership evidence for DASH-050's intentionally cancelled initial
// reads. Never exempt the visible monitor, an unknown frame, or all ERR_ABORTEDs.
const PROBE_TITLE = "scout monitor 電源分離與 Hailo 隔離檢查";
const PROBE_PATH = "/admin/dashboard/scout-monitor?ui=20260915-hailo1";
const PHASE = "existing-dash-050";
const READS = new Set(["status", "history?limit=60", "events?limit=50"]
  .map(endpoint => `/admin/dashboard/scout-monitor/api/v1/hardware-monitor/${endpoint}`));

function verifiedProbe(probe, baseUrl) {
  return probe?.newFrame === true && probe.directChild === true
    && probe.url === new URL(PROBE_PATH, baseUrl).href
    && probe.title === PROBE_TITLE && probe.hidden === true
    && probe.ariaHidden === "true" && probe.tabIndex === -1;
}

async function observeDiagnosticProbes(page, baseUrl) {
  let active = false, existing = new Set();
  const probes = [];
  await page.exposeBinding("__scoutSmokeProbeObserved", ({ frame }, metadata) => {
    if (!active) return;
    const probe = { ...metadata, frame, newFrame: !existing.has(frame),
      directChild: frame.parentFrame() === page.mainFrame() };
    if (verifiedProbe(probe, baseUrl) && !probes.some(item => item.frame === frame)) probes.push(probe);
  });
  // Read the frame element before the production onload cancels polling and
  // removes it. The binding retains Playwright Frame identity after detachment.
  // No fetch, AbortController, polling function, or Diagnostic code is replaced.
  await page.addInitScript(({ title, probeUrl }) => {
    const element = window.frameElement;
    if (element?.title === title && location.href === probeUrl) {
      window.__scoutSmokeProbeObserved({ url: location.href, title: element.title,
        hidden: element.hidden, ariaHidden: element.getAttribute("aria-hidden"), tabIndex: element.tabIndex })
        .catch(() => {}); // Lost observer evidence fails closed: no exemption.
    }
  }, { title: PROBE_TITLE, probeUrl: new URL(PROBE_PATH, baseUrl).href });
  return {
    begin() { existing = new Set(page.frames()); active = true; },
    finish() {
      active = false;
      return probes.map(probe => ({ ...probe, detached: probe.frame.isDetached() }));
    },
  };
}

function classifyDiagnosticProbeFailures(failures, { baseUrl, probes, report }) {
  const probe = probes.length === 1 && verifiedProbe(probes[0], baseUrl) ? probes[0] : null;
  const cleaned = report?.id === "DASH-050" && report.status === "passed"
    && report.structureStatus === "passed" && report.probeCleanup === "passed" && probe?.detached === true;
  const permitted = failure => {
    let url;
    try { url = new URL(failure.url); } catch (_) { return false; }
    return cleaned && failure.frame === probe.frame && failure.startedPhase === PHASE && failure.phase === PHASE
      && failure.error === "net::ERR_ABORTED" && failure.method === "GET"
      && url.origin === new URL(baseUrl).origin && !url.hash && READS.has(url.pathname + url.search);
  };
  const expectedCancelledRequests = [], failedResponses = [];
  for (const failure of failures) {
    const { frame, ...evidence } = failure;
    evidence.frameScope = probe && frame === probe.frame ? "diagnostic-owned-probe" : "ordinary-or-unverified";
    // More than one cancelled initial read of a route is not this known case.
    if (permitted(failure) && failures.filter(item => permitted(item) && item.url === failure.url).length === 1) {
      expectedCancelledRequests.push({ ...evidence, classification: "expected_cancelled",
        reason: "DASH-050 owned hidden probe initial GET; successful report, cleanup and frame detachment verified" });
    } else failedResponses.push(evidence);
  }
  return { expectedCancelledRequests, failedResponses,
    probeEvidence: probes.map(({ frame, ...evidence }) => evidence) };
}

module.exports = { observeDiagnosticProbes, classifyDiagnosticProbeFailures };
