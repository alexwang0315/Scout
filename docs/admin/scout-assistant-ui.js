(function () {
  function text(value, fallback = "unknown") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  }

  function apiPrefix(options = {}) {
    if (typeof options.apiBase === "function") return options.apiBase();
    return options.apiBase || "";
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(`${apiPrefix(options)}${path}`, { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (response.ok) return payload;
    const detail = payload.detail || payload.error || response.statusText || "request failed";
    throw new Error(`${path} returned ${response.status}: ${Array.isArray(detail) ? JSON.stringify(detail) : detail}`);
  }

  async function postJson(path, payload, options = {}) {
    const response = await fetch(`${apiPrefix(options)}${path}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
      cache: "no-store"
    });
    const responsePayload = await response.json().catch(() => ({}));
    if (response.ok) return responsePayload;
    const detail = responsePayload.detail || responsePayload.error || response.statusText || "request failed";
    throw new Error(`${path} returned ${response.status}: ${Array.isArray(detail) ? JSON.stringify(detail) : detail}`);
  }

  function renderList(id, items, fallback = "No source refs returned.") {
    const list = document.getElementById(id);
    if (!list) return;
    list.textContent = "";
    const resolvedItems = Array.isArray(items) && items.length ? items : [fallback];
    resolvedItems.forEach(item => {
      const li = document.createElement("li");
      li.textContent = text(item, "");
      list.appendChild(li);
    });
  }

  function providerStatusLabel(status) {
    return [
      status.provider || "provider",
      status.cloud_only ? "cloud-only" : (status.local_fallback_enabled ? "cloud/local fallback" : "mock/fallback disabled"),
      status.config_loaded ? "config loaded" : "no external config"
    ].filter(Boolean).join(" | ");
  }

  function providerStatusDetail(status) {
    return [
      `class: ${text(status.provider_class)}`,
      `startup: ${text(status.startup_connection_status, "not_checked")}`,
      `token_values_exposed: ${status.token_values_exposed === true ? "true" : "false"}`
    ].join(" | ");
  }

  function renderProviderStatus(status, options = {}) {
    const statusId = options.statusId || "assistantProviderStatus";
    const detailId = options.detailId || "assistantProviderStatusDetail";
    const statusNode = document.getElementById(statusId);
    const detailNode = document.getElementById(detailId);
    if (statusNode) statusNode.textContent = providerStatusLabel(status);
    if (detailNode) detailNode.textContent = providerStatusDetail(status);
  }

  function renderProviderStatusFailure(error, options = {}) {
    const statusId = options.statusId || "assistantProviderStatus";
    const detailId = options.detailId || "assistantProviderStatusDetail";
    const statusNode = document.getElementById(statusId);
    const detailNode = document.getElementById(detailId);
    if (statusNode) statusNode.textContent = "provider status unavailable";
    if (detailNode) detailNode.textContent = text(error && error.message ? error.message : error);
  }

  function sourceItems(payload) {
    return (payload.sources || []).map(source => (
      [source.source_id, source.evidence_type, source.source_path].filter(Boolean).join(" | ")
    ));
  }

  function observabilityItems(payload) {
    const obs = payload.observability || null;
    if (!obs) return [];
    const items = [
      `provider_class: ${text(obs.provider_class, "unknown")}`,
      `latency_class: ${text(obs.latency_class, "unknown")}`,
      `context_size_chars: ${text(obs.context_size_chars, "0")}`,
      `safe_failure: ${obs.safe_failure === true ? "true" : "false"}`
    ];
    if (obs.model_profile_used) items.push(`model_profile_used: ${text(obs.model_profile_used)}`);
    if (obs.failover_reason) items.push(`failover_reason: ${text(obs.failover_reason)}`);
    if (obs.local_model_name) items.push(`local_model_name: ${text(obs.local_model_name)}`);
    return items;
  }

  function offlineFallbackItems(payload) {
    const fallback = payload.offline_fallback || null;
    if (!fallback) return [];
    return [
      `schema_version: ${text(fallback.schema_version)}`,
      `prompt_id: ${text(fallback.prompt_id)}`,
      `summary_zh: ${text(fallback.summary_zh)}`,
      `risk_signals: ${(fallback.risk_signals || []).join("; ") || "none stated"}`,
      `operator_checks: ${(fallback.operator_checks || []).join("; ") || "none stated"}`,
      `uncertainties: ${(fallback.uncertainties || []).join("; ") || "none stated"}`,
      `source_refs: ${(fallback.source_refs || []).join(", ") || "none"}`,
      `confidence: ${text(fallback.confidence)}`,
      `read_only: ${fallback.read_only === true ? "true" : "false"}`,
      `model_interpretation: ${fallback.model_interpretation === true ? "true" : "false"}`,
      `safety_authority: ${fallback.safety_authority === false ? "false" : "true"}`,
      `phase1_state_change_allowed: ${fallback.phase1_state_change_allowed === false ? "false" : "true"}`,
      `observed_fact_write_allowed: ${fallback.observed_fact_write_allowed === false ? "false" : "true"}`,
      `outbound_action_allowed: ${fallback.outbound_action_allowed === false ? "false" : "true"}`,
      `hardware_control_allowed: ${fallback.hardware_control_allowed === false ? "false" : "true"}`
    ];
  }

  function renderOfflineFallback(payload, options = {}) {
    const listId = options.listId || "assistantOfflineFallbackList";
    renderList(listId, offlineFallbackItems(payload), "No offline fallback schema returned.");
  }

  function bindQuestionControls(options) {
    const askButton = document.getElementById(options.askButtonId || "assistantAskButton");
    const questionInput = document.getElementById(options.inputId || "assistantQuestionInput");
    const promptList = document.getElementById(options.promptListId || "assistantPromptSuggestions");
    if (askButton && questionInput) {
      askButton.addEventListener("click", () => options.submit(questionInput.value));
      questionInput.addEventListener("keydown", event => {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          event.preventDefault();
          options.submit(event.currentTarget.value);
        }
      });
    }
    if (promptList) {
      promptList.addEventListener("click", event => {
        const target = event.target.closest("[data-assistant-question]");
        if (!target) return;
        options.submit(target.dataset.assistantQuestion);
      });
    }
  }

  window.ScoutAssistantUI = {
    bindQuestionControls,
    fetchJson,
    observabilityItems,
    offlineFallbackItems,
    postJson,
    providerStatusDetail,
    providerStatusLabel,
    renderList,
    renderOfflineFallback,
    renderProviderStatus,
    renderProviderStatusFailure,
    sourceItems,
    text
  };
}());
