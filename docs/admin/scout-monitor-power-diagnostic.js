/* DASH-050. Fixed same-origin GETs and an owned monitor-frame render replay only.
 * This is a presentation/contract regression check, never a UPS health verdict.
 */
(function (root) {
  "use strict";
  const PAGE = "/admin/dashboard/scout-monitor";
  const PAGE_URL = `${PAGE}?ui=20260914-ssh1`;
  const STATUS = `${PAGE}/api/v1/hardware-monitor/status`;
  const ERROR_CODES = Object.freeze(["communication_error", "invalid_telemetry", "stale", "missing", "unreadable"]);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const requireValue = (value, message) => { if (!value) throw new Error(message); };
  let lastReport = null;

  function text(doc, id) {
    const element = doc.getElementById(id);
    requireValue(element, `scout monitor 缺少 #${id}`);
    return (element.textContent || "").trim();
  }

  function verifyContract(payload) {
    requireValue(payload && typeof payload === "object", "status 未回傳 JSON 物件");
    const power = payload.data?.power;
    if (!payload.data) return;
    requireValue(power && typeof power === "object", "最新採樣缺少 power");
    for (const source of ["ups", "supply"]) {
      const status = power[`${source}_status`], error = power[`${source}_error_code`];
      requireValue(status == null || ["ok", "unavailable"].includes(status), `無效的 power.${source}_status`);
      requireValue(error == null || ERROR_CODES.includes(error), `無效的 power.${source}_error_code`);
      if (status === "ok") requireValue(error == null, `power.${source}_error_code 與來源狀態不一致`);
    }
    const aggregate = (power.ups_status ?? power.status) === "ok" && (power.supply_status ?? power.status) === "ok" ? "ok" : "unavailable";
    requireValue(power.status === aggregate, "power.status 未保留全體可用性語意");
  }

  function verifyRendered(doc, payload, httpStatus = 200, retainedPower = null) {
    const overall = text(doc, "hardwareOverallStatus");
    const battery = text(doc, "hardwareBatteryPercent");
    const supply = text(doc, "hardwareSupplyStatus");
    const note = text(doc, "hardwareBatteryNote");
    const power = payload?.data?.power || retainedPower;
    const freshness = payload?.freshness;
    const stale = payload?.status === "stale" || freshness?.state === "stale"
      || (finite(freshness?.age_seconds) && finite(freshness?.stale_after_seconds)
        && freshness.age_seconds > freshness.stale_after_seconds);
    const unavailable = !payload || !payload.data || (httpStatus !== 200 && !stale)
      || ["unknown", "unavailable"].includes(payload.status);
    if (stale) requireValue(overall === "資料已過期", "503／過期資料被畫成目前正常，或未標示資料已過期");
    else if (unavailable) {
      requireValue(["未知", "無法連線"].includes(overall), "無資料／斷線被畫成目前正常");
      if (overall === "無法連線") requireValue(/每 60 秒自動重試/.test(text(doc, "hardwareNoticeText")), "斷線時缺少自動重試提示");
      if (payload?.connection?.transport === "ssh") {
        requireValue(text(doc, "hardwareNoticeText").includes(payload.next_steps[0]), "SSH 與 Scout API 失聯原因未分開呈現");
      }
    }
    else {
      requireValue(freshness?.state === "fresh", "freshness 非 fresh，不能通過即時資料檢查");
      const label = {ok: "正常", warning: "警告", critical: "嚴重告警"}[payload.status];
      requireValue(label && overall === label, "整體狀態未遵循頂層 status");
    }
    const upsOk = (power?.ups_status ?? power?.status) === "ok";
    const supplyOk = (power?.supply_status ?? power?.status) === "ok";
    if (!upsOk || !finite(power?.battery_percent)) {
      requireValue(battery === "未知" || battery === "—", "UPS 不可讀／未知值被填成電池百分比");
    } else requireValue(battery === `${power.battery_percent.toFixed(1)}%`, "有效電池百分比未保留顯示");

    if (finite(power?.ext5v_v)) {
      const volts = power.ext5v_v.toFixed(2).replace(".", "\\.");
      requireValue(new RegExp(`5V\\s*[:：]?\\s*${volts}\\s*V(?:\\s|$|[·；;])`).test(supply),
        "UPS 故障時主機有效 5V 被隱藏或錯誤顯示");
    } else requireValue(!/5V\s*[:：]?\s*-?\d+(?:\.\d+)?\s*V/.test(supply), "未知／不可用的主機 5V 被補成數字");
    if (finite(power?.active_throttle_bits)) {
      if (power.active_throttle_bits === 0) requireValue(/未見供電／效能限制/.test(supply), "有效的零限制旗標被當成未知");
      else requireValue(supply.includes(`旗標 ${power.active_throttle_bits}`), "目前供電／效能限制旗標未保留顯示");
    } else requireValue(!/未見供電／效能限制/.test(supply), "未知旗標被補為零並宣稱沒有供電限制");
    if ((stale || unavailable) && finite(power?.ext5v_v)) {
      requireValue(/上次|過期/.test(supply), "失效／斷線時保留的 5V 未標明上次採樣");
    }
    const notice = text(doc, "hardwarePowerNotice");
    if (power && !upsOk) {
      requireValue(/UPS/.test(notice) && /未知|無法|失敗|過期|不可讀|缺少|未取得/.test(notice), "缺少 UPS 不可讀與電池未知說明");
      requireValue(!doc.getElementById("hardwarePowerNotice").hidden, "UPS 告警說明被隱藏");
      if (power.ups_error_code === "communication_error") requireValue(/UPS.*(?:通訊|I[²2]C).*失敗/.test(notice), "UPS 通訊失敗原因未明確呈現");
    }
    if (power?.supply_status === "unavailable") requireValue(/主機|5V|供電/.test(notice), "主機供電不可讀未與 UPS 狀態分開說明");
    if (upsOk && supplyOk) requireValue(!/通訊失敗/.test(notice), "恢復後仍殘留 UPS 通訊失敗告警");
    requireValue(note.length > 0, "電源採樣說明遺失");
    return {overall, battery, supply, note, notice};
  }

  function fixture(overrides = {}) {
    const captured = new Date().toISOString();
    return {
      status: "ok", freshness: {state: "fresh", captured_at: captured, age_seconds: 1, stale_after_seconds: 150},
      data: {captured_at: captured, status: "ok", alerts: {}, thresholds: {ups_stale_seconds: 15, battery_percent: {warning: 20, critical: 10}},
        power: {status: "ok", ups_status: "ok", supply_status: "ok", ups_error_code: null, supply_error_code: null,
          captured_at: captured, age_seconds: 1, battery_percent: 68.5, battery_power_w: -3.5, battery_voltage_mv: 8100,
          flow: "discharging", ups_vbus_power_mw: 4000, ext5v_v: 5.18, active_throttle_bits: 0, ...overrides}},
    };
  }

  function scenarios() {
    const rows = [{id: "healthy", payload: fixture()}];
    for (const code of ERROR_CODES) {
      const payload = fixture({status: "unavailable", ups_status: "unavailable", ups_error_code: code,
        battery_percent: null, battery_power_w: null, battery_voltage_mv: null, flow: null, ups_vbus_power_mw: null});
      payload.status = "warning"; payload.data.status = "warning";
      payload.data.alerts = {power_telemetry: {severity: "warning", message: "UPS 電池資料未知"}};
      rows.push({id: `ups-${code}-supply-preserved`, payload});
    }
    const poisoned = structuredClone(rows[1].payload);
    poisoned.data.power.battery_percent = 83;
    rows.push({id: "failed-ups-must-not-use-leftover-percent", payload: poisoned});
    const supplyMissing = fixture({status: "unavailable", supply_status: "unavailable", supply_error_code: "missing", ext5v_v: null, active_throttle_bits: null});
    supplyMissing.status = "warning";
    rows.push({id: "ups-readable-supply-missing", payload: supplyMissing});
    const bothMissing = structuredClone(supplyMissing);
    Object.assign(bothMissing.data.power, {ups_status: "unavailable", ups_error_code: "unreadable", battery_percent: null});
    rows.push({id: "both-unavailable", payload: bothMissing});
    const partialFlags = fixture({status: "unavailable", supply_status: "unavailable", supply_error_code: "unreadable", active_throttle_bits: null});
    partialFlags.status = "warning";
    rows.push({id: "partial-supply-retains-valid-voltage", payload: partialFlags});
    const partialVoltage = fixture({status: "unavailable", supply_status: "unavailable", supply_error_code: "unreadable", ext5v_v: null});
    partialVoltage.status = "warning";
    rows.push({id: "partial-supply-retains-valid-flags", payload: partialVoltage});
    rows.push({id: "legacy-null-source-status", payload: fixture({ups_status: null, supply_status: null})});
    const legacy = structuredClone(rows[1].payload);
    Object.assign(legacy.data.power, {ups_status: null, supply_status: null, ups_error_code: null, supply_error_code: null});
    rows.push({id: "legacy-unavailable-preserves-valid-voltage", payload: legacy});
    rows.push({id: "unknown-values-are-not-zero", payload: fixture({battery_percent: null, ext5v_v: null, active_throttle_bits: null})});
    rows.push({id: "zero-throttle-with-unknown-voltage", payload: fixture({ext5v_v: null})});
    rows.push({id: "nonzero-throttle-preserved", payload: fixture({active_throttle_bits: 5})});
    const critical = fixture({battery_percent: 9}); critical.status = "critical";
    critical.data.alerts = {battery_percent: {severity: "critical", message: "電池嚴重告警"}};
    rows.push({id: "critical-top-level-status", payload: critical});
    const stale = fixture(); stale.status = "stale";
    Object.assign(stale.freshness, {state: "stale", age_seconds: 151});
    rows.push({id: "http-503-retains-last-values", payload: stale, httpStatus: 503});
    const aged = fixture(); aged.freshness.age_seconds = 151;
    rows.push({id: "fresh-label-but-expired-age", payload: aged});
    rows.push({id: "empty-data", payload: {status: "unavailable", freshness: {state: "missing"}, data: null}});
    rows.push({id: "before-disconnect", payload: fixture()});
    rows.push({id: "disconnected-retains-not-current", payload: null, httpStatus: 0, retainedPower: fixture().data.power});
    for (const [code, step] of [
      ["ssh_unavailable", "請確認 Mac 可使用既有 scout SSH 設定連線；不需要開啟 Mac 9151。"],
      ["scout_api_unavailable", "SSH 已連通，但 Scout 的 9151 API 無法連線；請確認 Scout 上的 API 服務。"],
    ]) rows.push({id: code, httpStatus: 503, retainedPower: fixture().data.power,
      payload: {status: "unavailable", data: null, freshness: {state: "unreadable"},
        connection: {transport: "ssh", error_code: code}, next_steps: [step]}});
    rows.push({id: "recovery", payload: fixture()});
    return rows;
  }

  function runRenderScenarios(probe) {
    const rows = [];
    for (const item of scenarios()) {
      try {
        const httpStatus = item.httpStatus ?? 200;
        probe.apply({response: httpStatus ? {ok: httpStatus === 200, status: httpStatus} : null, payload: item.payload});
        rows.push({id: item.id, status: "passed", evidence: verifyRendered(probe.doc, item.payload, httpStatus, item.retainedPower)});
      } catch (error) { rows.push({id: item.id, status: "failed", detail: error.message}); }
    }
    return rows;
  }

  async function readStatus({fetch, signal}) {
    const response = await fetch(STATUS, {method: "GET", credentials: "same-origin", mode: "same-origin",
      redirect: "error", cache: "no-store", signal, headers: {Accept: "application/json"}});
    // In particular, decode HTTP 503 JSON before deciding validity.
    const payload = await response.json();
    return {payload, httpStatus: response.status, transport: response.headers?.get("X-Scout-Monitor-Transport") || null};
  }

  function openProbe({document: doc, signal, timeoutMs = 15000}) {
    return new Promise((resolve, reject) => {
      const frame = doc.createElement("iframe");
      frame.title = "scout monitor 電源分離隔離檢查"; frame.tabIndex = -1;
      frame.setAttribute("aria-hidden", "true"); frame.hidden = true;
      let timer, readyTimer;
      const close = () => {
        try { frame.contentWindow?.stopHardwarePolling?.(); }
        finally { frame.remove(); }
      };
      const finish = error => {
        clearTimeout(timer); clearTimeout(readyTimer); signal.removeEventListener("abort", abort);
        frame.onload = null; frame.onerror = null;
        if (error) { close(); reject(error); }
      };
      const abort = () => finish(new Error("scout monitor 檢查已取消"));
      frame.onload = () => {
        // The production pageshow handler resumes polling when inactive. Let
        // the initial load/pageshow pair finish before stopping the owned frame.
        readyTimer = setTimeout(() => {
          try {
            const win = frame.contentWindow;
            requireValue(win.location.origin === doc.location.origin && win.location.pathname === PAGE, "監控檢查未載入固定同源入口");
            requireValue(typeof win.stopHardwarePolling === "function" && typeof win.applyHardwareStatusResult === "function", "監控頁 render／取消輪詢介面不可讀");
            win.stopHardwarePolling();
            finish();
            resolve({doc: frame.contentDocument, apply: result => win.applyHardwareStatusResult(result), close});
          } catch (error) { finish(error); }
        }, 0);
      };
      frame.onerror = () => finish(new Error("scout monitor 檢查頁載入失敗"));
      signal.addEventListener("abort", abort, {once: true});
      timer = setTimeout(() => finish(new Error("scout monitor 檢查頁載入逾時")), timeoutMs);
      if (signal.aborted) { abort(); return; }
      frame.src = PAGE_URL; doc.body.appendChild(frame);
    });
  }

  async function run({document: doc = root.document} = {}) {
    const win = doc.defaultView, controller = new AbortController();
    const cancel = () => controller.abort();
    const timer = setTimeout(cancel, 30000);
    win.addEventListener("pagehide", cancel, {once: true});
    let probe = null;
    const report = {id: "DASH-050", status: "failed", structureStatus: "not_checked", dataStatus: "not_checked",
      evidenceMode: "same-origin-status-and-isolated-production-render", official_qualification_eligible: false,
      runtime_safety_truth: false, hardware_control_invoked: false, rows: [], probeCleanup: "pending"};
    try {
      let live = null;
      try { live = await readStatus({fetch: win.fetch.bind(win), signal: controller.signal}); }
      catch (_) { report.rows.push({id: "live-status", status: "warning", detail: "同源 status JSON 不可讀；不能判定目前電源資料"}); }
      probe = await openProbe({document: doc, signal: controller.signal});
      report.structureStatus = "passed";
      if (live) {
        try {
          verifyContract(live.payload);
          requireValue(["ssh", "http"].includes(live.transport), "後端未提供監控傳輸資訊，請確認已載入目前代理版本");
          probe.apply({response: {status: live.httpStatus, ok: live.httpStatus === 200}, payload: live.payload});
          const evidence = verifyRendered(probe.doc, live.payload, live.httpStatus);
          const fresh = live.httpStatus === 200 && live.payload.data && live.payload.freshness?.state === "fresh"
            && ["ok", "warning", "critical"].includes(live.payload.status)
            && finite(live.payload.freshness.age_seconds) && finite(live.payload.freshness.stale_after_seconds)
            && live.payload.freshness.age_seconds <= live.payload.freshness.stale_after_seconds;
          report.dataStatus = fresh ? "current" : "unavailable_or_stale";
          report.rows.push({id: "live-status", status: fresh ? "passed" : "warning", evidence,
            capturedAt: live.payload.data?.captured_at || null, httpStatus: live.httpStatus, transport: live.transport,
            detail: fresh ? "目前採樣的電源分離呈現吻合；不代表 UPS 通訊恢復" : "失效／無資料呈現已核對，但目前電源資料未驗證"});
        } catch (error) { report.rows.push({id: "live-status", status: "failed", detail: error.message}); }
      }
      report.rows.push(...runRenderScenarios(probe));
    } catch (error) { report.rows.push({id: "monitor-entry", status: "failed", detail: error.message}); }
    finally {
      cancel(); clearTimeout(timer); win.removeEventListener("pagehide", cancel);
      try { probe?.close(); report.probeCleanup = "passed"; }
      catch (_) { report.probeCleanup = "failed"; report.rows.push({id: "cleanup", status: "failed", detail: "隔離監控頁未完整清理"}); }
    }
    report.status = report.rows.some(row => row.status === "failed") ? "failed"
      : report.rows.some(row => row.status === "warning") ? "warning" : "passed";
    const failed = report.rows.filter(row => row.status !== "passed");
    report.detail = `scout monitor 電源分離：${report.rows.filter(row => row.status === "passed").length}/${report.rows.length} 檢查通過。`
      + (failed.length ? failed.map(row => `${row.id}: ${row.detail}`).join("；") : "UPS 不可讀時電池未知，主機有效 5V 與旗標獨立保留；含 503、斷線、未知與恢復重播。")
      + " 僅同源 GET 與隔離呈現檢查；不代表 UPS 通訊恢復或硬體正常。";
    lastReport = structuredClone(report);
    return report;
  }

  const api = Object.freeze({run, verifyContract, verifyRendered, scenarios, runRenderScenarios, readStatus, openProbe,
    snapshot: () => lastReport && structuredClone(lastReport)});
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ScoutMonitorPowerDiagnostic = api;
})(typeof window !== "undefined" ? window : globalThis);
