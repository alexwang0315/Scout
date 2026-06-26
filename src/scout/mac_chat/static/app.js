(function () {
  const state = {
    config: null,
    surface: "pretrip",
    busy: false,
    lastPayload: null
  };

  const els = {
    serverState: document.getElementById("serverState"),
    fallbackState: document.getElementById("fallbackState"),
    serverUrl: document.getElementById("serverUrl"),
    serverLatency: document.getElementById("serverLatency"),
    capabilityCount: document.getElementById("capabilityCount"),
    uiBridgeState: document.getElementById("uiBridgeState"),
    fallbackMode: document.getElementById("fallbackMode"),
    boundaryList: document.getElementById("boundaryList"),
    refreshButton: document.getElementById("refreshButton"),
    clearButton: document.getElementById("clearButton"),
    promptList: document.getElementById("promptList"),
    chatStatus: document.getElementById("chatStatus"),
    messages: document.getElementById("messages"),
    chatForm: document.getElementById("chatForm"),
    messageInput: document.getElementById("messageInput"),
    sendButton: document.getElementById("sendButton"),
    routeList: document.getElementById("routeList"),
    permissionList: document.getElementById("permissionList"),
    actionList: document.getElementById("actionList"),
    rawJson: document.getElementById("rawJson")
  };

  function text(value) {
    return value === null || value === undefined || value === "" ? "--" : String(value);
  }

  function setBusy(value) {
    state.busy = value;
    els.sendButton.disabled = value;
    els.refreshButton.disabled = value;
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Accept": "application/json",
        ...(options.body ? {"Content-Type": "application/json"} : {}),
        ...(options.headers || {})
      }
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
    }
    return payload;
  }

  function renderBoundary(boundary) {
    if (!boundary) return;
    const rows = Object.entries(boundary).map(([key, value]) => (
      `<li>${escapeHtml(key)}: ${escapeHtml(value)}</li>`
    ));
    els.boundaryList.innerHTML = rows.join("");
  }

  async function loadConfig() {
    state.config = await fetchJson("/api/config");
    state.surface = state.config.default_surface || "pretrip";
    els.serverUrl.textContent = state.config.target_url;
    updateFallbackIndicator(state.config);
    renderBoundary(state.config.boundary);
    updateSegments();
  }

  async function refreshServer() {
    setBusy(true);
    try {
      const payload = await fetchJson("/api/server");
      els.serverUrl.textContent = payload.target_url;
      els.serverLatency.textContent = payload.latency_ms === null ? "--" : `${payload.latency_ms} ms`;
      els.capabilityCount.textContent = payload.connected ? payload.capability_count : "--";
      els.uiBridgeState.textContent = payload.ui_action_capability_present
        ? "present"
        : (payload.local_fallback_enabled && payload.local_fallback_available ? "fallback" : "missing");
      els.serverState.textContent = payload.connected ? "server online" : "server offline";
      els.serverState.className = `state-pill ${payload.connected ? "ok" : "bad"}`;
      updateFallbackIndicator(payload);
      els.chatStatus.textContent = payload.connected
        ? "Scout hardware server connected."
        : (
            payload.local_fallback_enabled && payload.local_fallback_available
              ? "Scout hardware server unavailable. Mac local fallback is enabled."
              : (payload.error || "Scout hardware server unavailable.")
          );
      if (payload.boundary) renderBoundary(payload.boundary);
    } catch (error) {
      els.serverState.textContent = "server offline";
      els.serverState.className = "state-pill bad";
      updateFallbackIndicator(state.config || {});
      els.chatStatus.textContent = error.message;
    } finally {
      setBusy(false);
    }
  }

  function updateFallbackIndicator(payload = {}) {
    const enabled = Boolean(payload.local_fallback_enabled || (state.config && state.config.local_fallback_enabled));
    const available = payload.local_fallback_available === undefined
      ? enabled
      : Boolean(payload.local_fallback_available);
    const used = payload.response_source === "mac_local_pydantic_ai_v2";
    const model = payload.response && payload.response.local_fallback
      ? payload.response.local_fallback.model
      : null;

    if (!enabled) {
      els.fallbackState.textContent = "fallback off";
      els.fallbackState.className = "state-pill";
      els.fallbackMode.textContent = "disabled";
      return;
    }

    if (!available) {
      els.fallbackState.textContent = "fallback error";
      els.fallbackState.className = "state-pill bad";
      els.fallbackMode.textContent = "enabled / unavailable";
      return;
    }

    els.fallbackState.textContent = used ? "fallback used" : "fallback on";
    els.fallbackState.className = `state-pill ${used ? "warn" : "ok"}`;
    els.fallbackMode.textContent = model ? `enabled / ${model}` : "enabled / ready";
  }

  function updateSegments() {
    document.querySelectorAll("[data-surface]").forEach((button) => {
      const active = button.dataset.surface === state.surface;
      button.classList.toggle("active", active);
      button.setAttribute("aria-checked", active ? "true" : "false");
    });
  }

  function appendMessage(role, body, options = {}) {
    const article = document.createElement("article");
    article.className = `message ${role}${options.error ? " error" : ""}`;

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = options.meta || (role === "user" ? "You" : "Scout AI server");

    const content = document.createElement("div");
    content.className = "message-body";
    if (typeof body === "string") {
      const paragraph = document.createElement("p");
      paragraph.textContent = body;
      content.appendChild(paragraph);
    } else {
      content.appendChild(body);
    }

    article.append(meta, content);
    els.messages.appendChild(article);
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function summaryNode(payload) {
    const summary = payload.summary || {};
    const response = payload.response || {};
    const route = response.route || {};
    const wrapper = document.createElement("div");
    wrapper.className = "message-summary";

    const title = document.createElement("strong");
    title.textContent = summary.title || response.status || "Scout response";

    const body = document.createElement("p");
    body.textContent = summary.body || response.message || payload.error || "No message returned.";

    const line = document.createElement("div");
    line.className = "status-line";
    const items = [
      payload.response_source,
      response.status,
      route.route_class,
      route.tool_id,
      payload.latency_ms !== undefined ? `${payload.latency_ms} ms` : null
    ].filter(Boolean);
    line.textContent = items.join(" / ");

    wrapper.append(title, body, line);
    return wrapper;
  }

  async function submitMessage() {
    const message = els.messageInput.value.trim();
    if (!message || state.busy) return;

    appendMessage("user", message, {meta: `You / ${state.surface}`});
    els.chatStatus.textContent = state.config && state.config.local_fallback_enabled
      ? "Sending to Scout hardware server. Mac local fallback will answer if hardware is unavailable."
      : "Sending to Scout hardware server.";
    setBusy(true);

    try {
      const payload = await fetchJson("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          message,
          surface: state.surface,
          user_id: "mac-chat-user",
          active_context: {
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "local"
          }
        })
      });
      state.lastPayload = payload;
      updateFallbackIndicator(payload);
      appendMessage("assistant", summaryNode(payload), {error: !payload.ok});
      renderDetail(payload);
      els.chatStatus.textContent = payload.response_source === "mac_local_pydantic_ai_v2"
        ? "Response received from Mac local fallback."
        : (payload.ok ? "Response received." : "Scout server returned an error.");
    } catch (error) {
      appendMessage("assistant", error.message, {error: true});
      els.chatStatus.textContent = error.message;
    } finally {
      setBusy(false);
    }
  }

  function renderDetail(payload) {
    const response = payload.response || {};
    const route = response.route || {};
    const permission = route.permission || response.permission || {};
    const actionPlan = response.ui_action_plan || {};
    const action = Array.isArray(actionPlan.actions) && actionPlan.actions.length
      ? actionPlan.actions[0]
      : null;

    renderList(els.routeList, [
      ["status", response.status],
      ["route_class", route.route_class],
      ["tool_id", route.tool_id],
      ["workflow_id", response.workflow_id],
      ["response_source", payload.response_source],
      ["fallback_model", response.local_fallback && response.local_fallback.model],
      ["remote_error", payload.remote_error],
      ["server", payload.target_url]
    ]);
    renderList(els.permissionList, [
      ["allowed", permission.allowed],
      ["requires_approval", permission.requires_user_approval],
      ["reason", permission.reason],
      ["message", permission.user_message]
    ]);
    if (action) {
      renderList(els.actionList, [
        ["kind", action.action_kind],
        ["label", action.label],
        ["preset", action.preset_id],
        ["target", action.target_ref],
        ["confirmation", action.requires_confirmation],
        ["session_only", action.session_only],
        ["visible_layers", Array.isArray(action.visible_layers) ? action.visible_layers.join(", ") : action.visible_layers]
      ]);
    } else {
      renderList(els.actionList, [["action", "none"]]);
    }
    els.rawJson.textContent = JSON.stringify(payload, null, 2);
  }

  function renderList(element, pairs) {
    const rows = pairs
      .filter(([, value]) => value !== undefined && value !== null && value !== "")
      .map(([key, value]) => `<li>${escapeHtml(key)}: ${escapeHtml(text(value))}</li>`);
    element.innerHTML = rows.length ? rows.join("") : "<li>None.</li>";
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function clearConversation() {
    els.messages.innerHTML = "";
    appendMessage("assistant", "Ready.");
    renderList(els.routeList, [["route", "No request yet."]]);
    renderList(els.permissionList, [["permission", "No decision yet."]]);
    renderList(els.actionList, [["action", "No action plan yet."]]);
    els.rawJson.textContent = "{}";
  }

  document.querySelectorAll("[data-surface]").forEach((button) => {
    button.addEventListener("click", () => {
      state.surface = button.dataset.surface;
      updateSegments();
    });
  });

  els.promptList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-prompt]");
    if (!button) return;
    els.messageInput.value = button.dataset.prompt;
    els.messageInput.focus();
  });

  els.refreshButton.addEventListener("click", refreshServer);
  els.clearButton.addEventListener("click", clearConversation);
  els.chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage();
  });
  els.messageInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      submitMessage();
    }
  });

  loadConfig()
    .then(refreshServer)
    .catch((error) => {
      els.serverState.textContent = "error";
      els.serverState.className = "state-pill bad";
      els.chatStatus.textContent = error.message;
    });
}());
