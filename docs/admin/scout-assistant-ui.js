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

  function fullWorkflowSource(payload) {
    const sources = Array.isArray(payload?.sources) ? payload.sources : [];
    return sources.find(source => (
      source?.source_id === "assistant_skill.pretrip.full_workflow.v0"
      || source?.evidence_type === "assistant_full_workflow_summary"
    )) || null;
  }

  function workflowItems(payload) {
    const source = fullWorkflowSource(payload);
    const summary = source?.context_summary || null;
    if (!summary) return [];
    const items = [
      `artifact: ${text(summary.artifact_kind)} | answerability: ${text(summary.answerability)}`,
      `tools: selected=${text(summary.selected_tool_count, "0")} executed=${text(summary.executed_tool_count, "0")} completed=${text(summary.completed_tool_count, "0")} gaps=${text(summary.contract_gap_count, "0")} missing=${text(summary.missing_evidence_count, "0")}`
    ];
    (summary.workflow_steps || []).slice(0, 4).forEach(step => {
      items.push(`step: ${text(step.step_id)} | ${text(step.status)} | ${text(step.artifact_kind)}`);
    });
    (summary.sources || []).slice(0, 4).forEach(item => {
      const missing = Array.isArray(item.missing_fields) && item.missing_fields.length
        ? ` | missing=${item.missing_fields.join(",")}`
        : "";
      items.push(`source: ${text(item.tool_id)} | ${text(item.collection_status)}${missing}`);
    });
    (summary.missing_evidence || []).slice(0, 4).forEach(item => {
      const fields = Array.isArray(item.missing_fields) ? item.missing_fields.join(",") : "none";
      items.push(`missing: ${text(item.tool_id)} | fields=${fields}`);
    });
    const boundary = summary.boundary || {};
    const policy = summary.workflow_policy || {};
    items.push(
      `boundary: runtime_safety_truth=${boundary.runtime_safety_truth === true ? "true" : "false"} model_provider_used=${policy.model_provider_used === true ? "true" : "false"} outbound=${policy.outbound_send_performed === true ? "true" : "false"} hardware=${policy.hardware_control_performed === true ? "true" : "false"}`
    );
    return items;
  }

  function standardGapAudit(payload) {
    const source = fullWorkflowSource(payload);
    const summary = source?.context_summary || null;
    const decisionOutput = summary?.decision_output || null;
    const audit = decisionOutput?.standardGapAudit || summary?.standardGapAudit || null;
    return audit && typeof audit === "object" ? audit : null;
  }

  function standardGapAuditItems(payload) {
    const audit = standardGapAudit(payload);
    if (!audit) return [];
    const summary = audit.summary || {};
    const items = [
      `schema: ${text(audit.schema)} | runtime_safety_truth=${audit.runtimeSafetyTruth === true ? "true" : "false"}`,
      `coverage: ${text(summary.coveredStandardGroupCount, "0")}/${text(summary.standardGroupCount, "0")} groups | implementation_gap_tools=${text(summary.implementationGapToolCount, "0")} | context_review_gap_tools=${text(summary.contextOrReviewEvidenceGapToolCount, "0")} | ui_ux_validation_needed=${summary.uiUxValidationNeeded === true ? "true" : "false"}`
    ];
    const uiValidation = audit.uiUxValidation || null;
    if (uiValidation && typeof uiValidation === "object") {
      items.push(
        `ui_validation: status=${text(uiValidation.status)} | surface=${text(uiValidation.surface)} | validated=${uiValidation.validated === true ? "true" : "false"}`
      );
    }
    (audit.groups || []).slice(0, 5).forEach(group => {
      items.push(`group: ${text(group.label)} | sections=${text(group.sections)} | ${text(group.status)} | missing=${text(group.missingFieldCount, "0")}`);
    });
    (audit.inputOrEvidenceGaps || []).slice(0, 4).forEach(gap => {
      items.push(`gap: ${text(gap.toolId)} | ${text(gap.classification)} | fields=${text(gap.missingFieldCount, "0")}`);
    });
    (audit.nextSlices || []).slice(0, 3).forEach(slice => {
      items.push(`next: ${text(slice)}`);
    });
    (audit.nonGoals || []).slice(0, 2).forEach(nonGoal => {
      items.push(`boundary: ${text(nonGoal)}`);
    });
    return items;
  }

  function renderStandardGapAudit(payload, options = {}) {
    const listId = options.listId || "assistantStandardGapAuditList";
    renderList(listId, standardGapAuditItems(payload), "No standard gap audit returned.");
  }

  function renderWorkflowSummary(payload, options = {}) {
    const listId = options.listId || "assistantWorkflowList";
    renderList(listId, workflowItems(payload), "No full workflow summary returned.");
  }

  function workflowStatusItems(status) {
    const workflow = status?.assistant_workflow || null;
    if (!workflow) return [];
    const items = [
      `status: ${text(workflow.status)} | workflow_gate_ok=${workflow.workflow_gate_ok === true ? "true" : "false"} | overall_readiness_ok=${workflow.overall_readiness_ok === true ? "true" : "false"}`,
      `tools: ${text(workflow.workflow_tool_count, "0")} | checked_manifests=${text(workflow.checked_manifest_count, "0")} | missing=${text(workflow.missing_count, "0")}`,
      `boundary: runtime_safety_truth=${workflow.runtime_safety_truth === true ? "true" : "false"} candidate_evidence_is_runtime_truth=${workflow.candidate_evidence_is_runtime_truth === true ? "true" : "false"} outbound=${workflow.outbound_send_allowed === true ? "true" : "false"} hardware=${workflow.hardware_control_allowed === true ? "true" : "false"}`
    ];
    (workflow.workflow_order || []).slice(0, 8).forEach(step => {
      items.push(`workflow_step: ${text(step)}`);
    });
    (workflow.missing || []).slice(0, 4).forEach(item => {
      items.push(`missing: ${text(item)}`);
    });
    return items;
  }

  function renderWorkflowStatus(status, options = {}) {
    const listId = options.listId || "assistantWorkflowStatusList";
    renderList(listId, workflowStatusItems(status), "Workflow readiness status not loaded.");
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
    fullWorkflowSource,
    observabilityItems,
    offlineFallbackItems,
    postJson,
    providerStatusDetail,
    providerStatusLabel,
    renderList,
    renderOfflineFallback,
    renderProviderStatus,
    renderProviderStatusFailure,
    renderStandardGapAudit,
    renderWorkflowSummary,
    renderWorkflowStatus,
    sourceItems,
    standardGapAudit,
    standardGapAuditItems,
    text,
    workflowItems,
    workflowStatusItems
  };
}());
