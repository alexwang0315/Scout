/* DASH-050. Fixed same-origin GETs and an owned monitor-frame render replay only.
 * This is a presentation/contract regression check, never a UPS/Hailo health verdict.
 */
(function (root) {
  "use strict";
  const PAGE = "/admin/dashboard/scout-monitor";
  const PAGE_URL = `${PAGE}?ui=20260915-hailo1`;
  const STATUS = `${PAGE}/api/v1/hardware-monitor/status`;
  const ERROR_CODES = Object.freeze(["communication_error", "invalid_telemetry", "stale", "missing", "unreadable"]);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const requireValue = (value, message) => { if (!value) throw new Error(message); };
  const HAILO_METRICS = Object.freeze([
    "nnc_utilization_percent", "cpu_utilization_percent", "ram_utilization_percent",
    "ram_used_bytes", "ram_total_bytes", "temperature_c", "voltage_mv",
  ]);
  const HAILO_LABELS = Object.freeze({ok: "已讀取", partial: "部分讀取", unavailable: "無法讀取"});
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const awareTime = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    && Number.isFinite(Date.parse(value));
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
    verifyHailoContract(payload.data.hailo);
  }

  // Mirror HailoTelemetry/HailoDevice's public value and read-state invariants,
  // not hardware-health thresholds. Legacy snapshots may omit the whole field.
  function verifyHailoContract(hailo) {
    if (hailo == null) return;
    requireValue(object(hailo), "hailo 必須是物件或 null");
    requireValue(awareTime(hailo.captured_at), "hailo.captured_at 必須是含時區的真實採樣時間");
    requireValue(hailo.source === "hailortcli.monitor", "無效的 hailo.source");
    requireValue(hailo.read_only === true && hailo.sample_window_ms === 1000, "Hailo 唯讀／採樣視窗契約不符");
    const errors = (value, path) => {
      requireValue(value === undefined || Array.isArray(value) && value.every(error => typeof error === "string"), `${path} 必須是文字清單`);
      return value || [];
    };
    const sectionErrors = errors(hailo.errors, "hailo.errors");
    requireValue(Array.isArray(hailo.devices), "hailo.devices 必須是清單");
    const ids = new Set(), statuses = new Set();
    for (const device of hailo.devices) {
      requireValue(object(device), "hailo.devices 裝置不是物件");
      requireValue(typeof device.device_id === "string" && /^pci\/[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$/.test(device.device_id), "無效的 Hailo device_id");
      requireValue(!ids.has(device.device_id), "Hailo device_id 重複，不能合併裝置");
      ids.add(device.device_id);
      requireValue(typeof device.architecture === "string", "Hailo architecture 必須是文字");
      const deviceErrors = errors(device.errors, "hailo.devices.errors");
      for (const key of HAILO_METRICS) {
        const value = device[key];
        if (value == null) continue;
        requireValue(finite(value), `Hailo ${key} 必須是有限數值或 null，不可轉型補零`);
        if (key.endsWith("_percent")) requireValue(value >= 0 && value <= 100, `Hailo ${key} 超出百分比範圍`);
        else if (key.endsWith("_bytes")) requireValue(Number.isSafeInteger(value) && value >= (key === "ram_total_bytes" ? 1 : 0), `Hailo ${key} 必須是有效整數 bytes`);
        else if (key === "temperature_c") requireValue(value >= -273.15 && value !== -1, "Hailo temperature_c 無效或含未採樣 sentinel");
        else requireValue(value >= 0, "Hailo voltage_mv 不可為負");
      }
      requireValue(device.ram_used_bytes == null || device.ram_total_bytes == null
        || device.ram_used_bytes <= device.ram_total_bytes, "Hailo RAM 已用量超過總量");
      const measured = HAILO_METRICS.filter(key => device[key] != null).length;
      const expected = measured === HAILO_METRICS.length ? "ok" : measured ? "partial" : "unavailable";
      requireValue(device.status === expected && (expected !== "ok" || !deviceErrors.length), "Hailo 裝置讀取狀態與實際欄位不一致");
      statuses.add(device.status);
    }
    const expected = sectionErrors.length && !ids.size || statuses.size === 1 && statuses.has("unavailable") ? "unavailable"
      : sectionErrors.length || [...statuses].some(status => status !== "ok") ? "partial" : "ok";
    requireValue(hailo.status === expected, "Hailo 全體讀取狀態與裝置清單不一致");
  }

  function hailoSampleAge(payload, hailo, elapsedSeconds = 0) {
    if (!awareTime(hailo?.captured_at)) return null;
    const freshness = payload?.freshness, captured = Date.parse(hailo.captured_at);
    const elapsed = Math.max(0, elapsedSeconds);
    // The two captures belong to Scout. A Mac wall-clock offset must not turn a
    // current Scout observation stale (or an old Scout observation current).
    const age = finite(freshness?.age_seconds) && freshness.age_seconds >= 0 && awareTime(freshness.captured_at)
      ? freshness.age_seconds + (Date.parse(freshness.captured_at) - captured) / 1000 + elapsed
      : awareTime(payload?.server_time) ? (Date.parse(payload.server_time) - captured) / 1000 + elapsed
      : (Date.now() - captured) / 1000;
    return finite(age) && age >= -1 ? Math.max(0, age) : null;
  }

  function hailoValidity(payload, httpStatus, hailo, elapsedSeconds = 0) {
    const freshness = payload?.freshness;
    if (payload?.status === "stale" || freshness?.state === "stale"
      || finite(freshness?.age_seconds) && finite(freshness?.stale_after_seconds)
        && freshness.age_seconds + Math.max(0, elapsedSeconds) > freshness.stale_after_seconds) return "stale";
    if (httpStatus !== 200 || !payload || payload.status === "unavailable") return "unavailable";
    if (!payload.data || !["ok", "warning", "critical"].includes(payload.status)
      || freshness?.state !== "fresh" || !finite(freshness.age_seconds)
      || !finite(freshness.stale_after_seconds)) return "unknown";
    const age = hailoSampleAge(payload, hailo, elapsedSeconds);
    if (hailo && age === null) return "unknown";
    if (hailo && age > 150) return "stale";
    return "current";
  }

  function verifyHailoRendered(doc, payload, httpStatus = 200, retainedHailo = null, elapsedSeconds = 0) {
    const status = text(doc, "hardwareHailoStatus"), meta = text(doc, "hardwareHailoMeta");
    const panel = doc.getElementById("hardwareHailoPanel"), grid = doc.getElementById("hardwareHailoDevices");
    requireValue(panel && grid && !panel.hidden, "scout monitor 缺少可讀的 Hailo 區塊，可能載入舊版 UI");
    const hailo = payload?.data ? payload.data.hailo : retainedHailo;
    const validity = hailoValidity(payload, httpStatus, hailo, elapsedSeconds);
    // A transport failure carries no source anchor. Retained readings are
    // checked below, but do not invent their age from the Mac's wall clock.
    const ageSeconds = payload?.data ? hailoSampleAge(payload, hailo, elapsedSeconds) : null;
    const cards = [...grid.querySelectorAll("[data-hailo-device]")];
    requireValue(!panel.querySelector("script,img,iframe,object,embed,[onload],[onerror]"), "Hailo 內容未以安全純文字呈現");
    if (validity === "stale") requireValue(panel.dataset.state === "stale" && /資料已過期/.test(meta), "Hailo 過期資料未明確標示");
    if (validity === "unavailable") requireValue(panel.dataset.state === "unavailable" && /斷線|上次採樣/.test(meta), "Hailo 斷線保留值被當成目前資料");
    if (validity === "unknown") requireValue(panel.dataset.state === "unknown" && /未知/.test(meta), "Hailo 資料有效性未知卻通過目前資料檢查");
    if (!hailo) {
      requireValue(cards.length === 0 && /等待更新/.test(meta) && /未知/.test(status), "舊採樣／null Hailo 未顯示等待更新或殘留假裝置");
      return {status, meta, validity, deviceCount: 0, capturedAt: null, devices: []};
    }
    requireValue(status.includes(HAILO_LABELS[hailo.status]), "Hailo 區塊讀取狀態未遵循 API");
    requireValue(!/正常|故障/.test(status), "Hailo 已讀取被誤稱為硬體健康／故障");
    if (validity !== "current") requireValue(/上次採樣/.test(status), "失效的 Hailo 已讀取徽章缺少上次採樣註記");
    else requireValue(panel.dataset.state === hailo.status && !/上次採樣|資料已過期|斷線/.test(meta), "Hailo 恢復後仍保留失效狀態");
    requireValue(meta.includes(hailo.source) && /採樣視窗 1 秒/.test(meta) && /唯讀旗標 是/.test(meta), "Hailo 觀測來源／唯讀／採樣視窗未呈現");
    requireValue(cards.length === hailo.devices.length, "Hailo 裝置數量未遵循 API 清單");
    if (!cards.length) requireValue(hailo.status === "ok" ? /未列出 Hailo 裝置/.test(grid.textContent)
      : /清單無法確認/.test(grid.textContent) && !/未列出|沒有偵測到/.test(grid.textContent),
      "空 Hailo 清單未區分已讀取與讀取失敗，或虛構装置");
    const plain = element => {
      requireValue(element && element.childElementCount === 0, "Hailo 欄位遺失或未以純文字呈現");
      return element.textContent.trim();
    };
    const checkErrors = (scope, values) => {
      requireValue(scope, "Hailo 讀取錯誤區塊遺失");
      const actual = [...scope.querySelectorAll(".inventory-errors li")].map(plain);
      for (const error of values || []) requireValue(actual.includes(error), "Hailo 讀取錯誤未原樣以純文字保留");
    };
    checkErrors(doc.getElementById("hardwareHailoErrors"), hailo.errors);
    const devices = hailo.devices.map(device => {
      // Compare identifiers as data; never interpolate untrusted text into CSS.
      const matching = cards.filter(card => card.dataset.hailoDevice === device.device_id);
      requireValue(matching.length === 1, "Hailo 多裝置混合、重複或遺失");
      const card = matching[0], badge = card.querySelector(".inventory-section-status");
      requireValue(badge && badge.textContent.includes(HAILO_LABELS[device.status])
        && badge.dataset.state === (validity === "current" ? device.status : validity), "Hailo 裝置讀取狀態未保留／失效資料仍是目前已讀取");
      requireValue(plain(card.querySelector(".inventory-section-name")) === device.device_id, "Hailo 裝置名稱未以純文字保留");
      requireValue(plain(card.querySelector(".inventory-section-summary")).includes(device.architecture), "Hailo architecture 未以純文字保留");
      const metrics = {};
      for (const key of HAILO_METRICS) {
        const reading = plain(card.querySelector(`[data-hailo-metric="${key}"]`));
        metrics[key] = reading;
        if (!finite(device[key])) {
          requireValue(["未知", "—"].includes(reading), `Hailo ${key} 未知值被補零或殘留上次讀值`);
          continue;
        }
        const bytes = key.endsWith("_bytes"), percent = key.endsWith("_percent");
        const unit = bytes ? "GiB" : percent ? "%" : key === "temperature_c" ? "°C" : "mV";
        const match = /^(-?\d+(?:\.\d+)?)\s*(%|GiB|°C|mV)$/.exec(reading);
        const expected = bytes ? device[key] / 1024 ** 3 : device[key];
        const tolerance = bytes ? 0.005000001 : key === "voltage_mv" ? 0.000000001 : 0.050000001;
        requireValue(match && match[2] === unit && Math.abs(Number(match[1]) - expected) <= tolerance,
          `Hailo ${key} 數值／${unit} 單位與 API 不符`);
        if (device[key] === 0) requireValue(Number(match[1]) === 0, `Hailo ${key} 有效零讀值未保留`);
      }
      const captured = awareTime(hailo.captured_at) ? new Date(hailo.captured_at).toLocaleString("zh-TW", {timeZone: "Asia/Taipei",
        year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false}) : "未知";
      requireValue(plain(card.querySelector('[data-hailo-metric="captured_at"]')) === captured, "Hailo 時間未使用來源 captured_at／Asia/Taipei");
      requireValue(plain(card.querySelector('[data-hailo-metric="source"]')) === hailo.source, "Hailo 裝置來源遺失");
      checkErrors(card, device.errors);
      return {deviceId: device.device_id, status: device.status, metrics};
    });
    if (finite(payload?.data?.cpu_used_percent)) requireValue(text(doc, "hardwareCpuPercent") === `${payload.data.cpu_used_percent.toFixed(1)}%`, "Hailo 內部 CPU 覆蓋了主機 CPU");
    if (!awareTime(hailo.captured_at) || payload?.data && ageSeconds === null) requireValue(text(doc, "hardwareHailoAge") === "未知", "未知 Hailo 自身時間被補成目前資料年齡");
    return {status, meta, validity, ageSeconds, deviceCount: cards.length, capturedAt: hailo.captured_at, devices};
  }

  function verifyRendered(doc, payload, httpStatus = 200, retainedPower = null, retainedHailo = null) {
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
    return {overall, battery, supply, note, notice, hailo: verifyHailoRendered(doc, payload, httpStatus, retainedHailo)};
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

  function hailoFixture() {
    const payload = fixture();
    payload.data.cpu_used_percent = 33.3;
    payload.data.hailo = {
      captured_at: new Date(Date.parse(payload.freshness.captured_at) - 2000).toISOString(), status: "ok", source: "hailortcli.monitor",
      sample_window_ms: 1000, read_only: true, errors: [], devices: [{
        device_id: "pci/0001:03:00.0", architecture: "HAILO10H", status: "ok", errors: [],
        nnc_utilization_percent: 12.5, cpu_utilization_percent: 0.2, ram_utilization_percent: 1.1,
        ram_used_bytes: 82 * 1024 ** 2, ram_total_bytes: 7221 * 1024 ** 2,
        temperature_c: 46.2, voltage_mv: 802,
      }],
    };
    return payload;
  }

  function hailoScenarios() {
    const empty = {status: "unavailable", freshness: {state: "missing"}, data: null};
    const rows = [{id: "hailo-first-null-data", seed: structuredClone(empty), payload: empty},
      {id: "hailo-current-metrics-and-source-time", payload: hailoFixture()}];
    const zero = hailoFixture();
    for (const key of HAILO_METRICS.filter(key => key !== "ram_total_bytes")) zero.data.hailo.devices[0][key] = 0;
    rows.push({id: "hailo-zero-is-measured-not-failure", payload: zero});
    const partial = hailoFixture();
    partial.data.hailo.status = partial.data.hailo.devices[0].status = "partial";
    Object.assign(partial.data.hailo.devices[0], {nnc_utilization_percent: null, ram_used_bytes: null,
      temperature_c: null, errors: ["metric_unavailable"]});
    rows.push({id: "hailo-partial-null-replaces-last-values", seed: hailoFixture(), payload: partial});
    const missing = structuredClone(partial);
    for (const key of ["nnc_utilization_percent", "ram_used_bytes", "temperature_c"]) delete missing.data.hailo.devices[0][key];
    rows.push({id: "hailo-missing-metrics-remain-unknown", payload: missing});
    const unavailable = hailoFixture();
    unavailable.data.hailo.status = unavailable.data.hailo.devices[0].status = "unavailable";
    Object.assign(unavailable.data.hailo.devices[0], Object.fromEntries(HAILO_METRICS.map(key => [key, null])), {errors: ["timeout"]});
    rows.push({id: "hailo-unavailable-all-null", payload: unavailable});
    rows.push({id: "hailo-legacy-missing-waits", seed: hailoFixture(), payload: fixture()});
    const legacyNull = fixture(); legacyNull.data.hailo = null;
    rows.push({id: "hailo-legacy-null-clears-last-devices", seed: hailoFixture(), payload: legacyNull});
    const noDevices = hailoFixture(); noDevices.data.hailo.devices = [];
    rows.push({id: "hailo-empty-list-is-read-not-health", seed: hailoFixture(), payload: noDevices});
    const unreadableList = structuredClone(noDevices);
    unreadableList.data.hailo.status = "unavailable";
    unreadableList.data.hailo.errors = ["inventory_unavailable"];
    rows.push({id: "hailo-empty-unavailable-is-not-absence", seed: hailoFixture(), payload: unreadableList});
    const multi = hailoFixture();
    multi.data.hailo.devices.push({...multi.data.hailo.devices[0], device_id: "pci/0001:05:00.0",
      nnc_utilization_percent: 87.3, cpu_utilization_percent: 4.6, ram_utilization_percent: 18.75,
      ram_used_bytes: 1.5 * 1024 ** 3, ram_total_bytes: 8 * 1024 ** 3, temperature_c: 61.8, voltage_mv: 804});
    rows.push({id: "hailo-multi-device-independent-metrics", payload: multi});
    const mixed = structuredClone(multi);
    mixed.data.hailo.status = "partial";
    mixed.data.hailo.devices[0] = structuredClone(unavailable.data.hailo.devices[0]);
    rows.push({id: "hailo-multi-device-partial-is-not-all-ok", payload: mixed});
    const ownStale = hailoFixture();
    ownStale.data.hailo.captured_at = new Date(Date.parse(ownStale.freshness.captured_at) - 181000).toISOString();
    rows.push({id: "hailo-own-stale-with-fresh-host", payload: ownStale});
    const afterHost = hailoFixture(), anchor = Date.now() - 4000;
    afterHost.freshness.captured_at = afterHost.data.captured_at = new Date(anchor).toISOString();
    afterHost.freshness.age_seconds = 4;
    afterHost.data.hailo.captured_at = new Date(anchor + 2000).toISOString();
    rows.push({id: "hailo-captured-after-host-anchor", payload: afterHost});
    const future = hailoFixture();
    future.data.hailo.captured_at = new Date(Date.parse(future.freshness.captured_at) + 300000).toISOString();
    rows.push({id: "hailo-future-source-time-is-unknown", payload: future});
    const globalStale = hailoFixture(); globalStale.status = "stale";
    Object.assign(globalStale.freshness, {state: "stale", age_seconds: 151});
    rows.push({id: "hailo-global-503-retains-not-current", payload: globalStale, httpStatus: 503});
    for (const [id, payload, httpStatus] of [
      ["hailo-transport-disconnect-retains-last-values", null, 0],
      ["hailo-ssh-503-retains-last-values", {status: "unavailable", data: null, freshness: {state: "unreadable"},
        connection: {transport: "ssh", error_code: "ssh_unavailable"}, next_steps: ["請確認 scout SSH 連線；每 60 秒自動重試。"]}, 503],
    ]) {
      const seed = hailoFixture();
      rows.push({id, seed, payload, httpStatus, retainedPower: seed.data.power, retainedHailo: seed.data.hailo});
    }
    const hostile = structuredClone(partial);
    const markup = '<img src=x onerror="window.hailoInjected=true">Hailo <安全文字>';
    hostile.data.hailo.devices[0].architecture = markup;
    hostile.data.hailo.devices[0].errors = [markup]; hostile.data.hailo.errors = [markup];
    rows.push({id: "hailo-architecture-and-errors-safe-text", payload: hostile});
    rows.push({id: "hailo-recovery-clears-invalid-state", payload: hailoFixture()});
    return rows;
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
    rows.push(...hailoScenarios());
    return rows;
  }

  function runRenderScenarios(probe) {
    const rows = [];
    for (const item of scenarios()) {
      try {
        if (item.seed) {
          probe.apply({response: {ok: true, status: 200}, payload: item.seed});
          verifyRendered(probe.doc, item.seed);
        }
        const httpStatus = item.httpStatus ?? 200;
        if (item.payload) verifyContract(item.payload);
        probe.apply({response: httpStatus ? {ok: httpStatus === 200, status: httpStatus} : null, payload: item.payload});
        rows.push({id: item.id, status: "passed", capturedAt: item.payload?.data?.hailo?.captured_at || item.retainedHailo?.captured_at || item.payload?.data?.captured_at || null,
          evidence: verifyRendered(probe.doc, item.payload, httpStatus, item.retainedPower, item.retainedHailo)});
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

  function verifyCurrentHailo(doc, payload, httpStatus = 200) {
    const hailo = payload?.data?.hailo;
    verifyHailoContract(hailo);
    const evidence = verifyHailoRendered(doc, payload, httpStatus);
    const dataStatus = !hailo ? "missing_field" : evidence.validity !== "current" ? "unavailable_or_stale"
      : !hailo.devices.length ? "empty_devices"
      : hailo.status !== "ok" || hailo.devices.some(device => HAILO_METRICS.some(key => !finite(device[key]))) ? "partial_metrics" : "current";
    const detail = {
      missing_field: "目前 API 沒有新版 Hailo 資料；等待更新呈現已核對，新能力的目前資料檢查仍有缺口。",
      unavailable_or_stale: "Hailo 失效／過期呈現已核對，但目前讀值未驗證。",
      empty_devices: "目前 Hailo 清單為空，不能把空清單算成新指標已驗證。",
      partial_metrics: "Hailo 部分／未知讀值已核對；目前七項指標仍有未取得資料。",
      current: "目前 Hailo 來源時間與各裝置七項指標呈現吻合；不是推論成功或硬體健康證明。",
    }[dataStatus];
    return {id: "live-hailo-current-payload", status: dataStatus === "current" ? "passed" : "warning",
      dataStatus, detail, evidence, capturedAt: hailo?.captured_at || null, httpStatus};
  }

  function openProbe({document: doc, signal, timeoutMs = 15000}) {
    return new Promise((resolve, reject) => {
      const frame = doc.createElement("iframe");
      frame.title = "scout monitor 電源分離與 Hailo 隔離檢查"; frame.tabIndex = -1;
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
    const report = {id: "DASH-050", status: "failed", structureStatus: "not_checked", dataStatus: "not_checked", hailoDataStatus: "not_checked",
      evidenceMode: "same-origin-status-and-isolated-production-render", official_qualification_eligible: false,
      runtime_safety_truth: false, hardware_control_invoked: false, rows: [], probeCleanup: "pending"};
    try {
      let live = null;
      try { live = await readStatus({fetch: win.fetch.bind(win), signal: controller.signal}); }
      catch (_) {
        report.rows.push({id: "live-status", status: "warning", detail: "同源 status JSON 不可讀；不能判定目前電源／Hailo 資料"});
        report.hailoDataStatus = "unavailable_or_stale";
        report.rows.push({id: "live-hailo-current-payload", status: "warning", dataStatus: report.hailoDataStatus,
          detail: "目前 status JSON 不可讀，Hailo 新能力的目前資料檢查仍有缺口。"});
      }
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
        try {
          const row = verifyCurrentHailo(probe.doc, live.payload, live.httpStatus);
          report.hailoDataStatus = row.dataStatus;
          report.rows.push(row);
        } catch (error) {
          report.hailoDataStatus = "failed";
          report.rows.push({id: "live-hailo-current-payload", status: "failed", detail: error.message});
        }
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
    report.detail = `scout monitor 電源分離與 Hailo：${report.rows.filter(row => row.status === "passed").length}/${report.rows.length} 檢查通過。`
      + (failed.length ? failed.map(row => `${row.id}: ${row.detail}`).join("；") : "UPS 不可讀時電池未知，主機有效 5V 與旗標獨立保留；Hailo 含七項指標、多裝置、503、自身過期、斷線、未知與恢復重播。")
      + " 僅同源 GET 與隔離呈現檢查；不代表 UPS 通訊恢復、Hailo 推論成功或硬體正常。";
    lastReport = structuredClone(report);
    return report;
  }

  const api = Object.freeze({run, verifyContract, verifyRendered, verifyHailoContract, verifyHailoRendered, verifyCurrentHailo,
    scenarios, runRenderScenarios, readStatus, openProbe,
    snapshot: () => lastReport && structuredClone(lastReport)});
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ScoutMonitorPowerDiagnostic = api;
})(typeof window !== "undefined" ? window : globalThis);
