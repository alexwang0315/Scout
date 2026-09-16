"use strict";
const $ = (id) => document.getElementById(id);
const make = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
const finite = (v) => typeof v === "number" && Number.isFinite(v);
const number = (v, digits = 1) => finite(v) ? v.toFixed(digits) : "—";
const gib = (v) => finite(v) ? `${number(v / 1024 ** 3, 2)} GiB` : "—";
const date = (v) => v ? new Date(v).toLocaleString("zh-TW", {timeZone: "Asia/Taipei", hour12: false}) : "—";
const stateNames = {ok: "正常", warning: "警告", critical: "嚴重告警", stale: "資料已過期", unavailable: "資料不可用", partial: "部分可讀", offline: "連線失敗", present: "已枚舉", connected: "已連線", disconnected: "未連線", blocked: "無線已停用", powered_on: "已開啟", powered_off: "已關閉", observed: "有讀值", unknown: "未知"};
const groupNames = {network: "無線／有線網路", bluetooth: "藍牙", usb: "USB", pcie: "PCIe", i2c: "I²C", gpio: "GPIO", serial: "UART／序列埠"};
const propertyNames = {kind: "類型", operstate: "介面狀態", ipv4: "IPv4", ipv6: "IPv6", ssid: "Wi-Fi 名稱", signal_dbm: "訊號 dBm", frequency_mhz: "頻率 MHz", tx_bitrate_mbps: "傳送速率 Mbit/s", soft_blocked: "軟體停用", hard_blocked: "硬體停用", address: "位址", powered: "電源已開啟", discoverable: "允許被發現", pairable: "允許配對", discovering: "正在探索", idVendor: "廠商 ID", idProduct: "產品 ID", manufacturer: "製造商", speed: "USB 速率 Mbit/s", authorized: "系統已授權", root_hub: "根集線器", interface_drivers: "介面驅動", vendor: "廠商 ID", device: "裝置 ID", class: "分類代碼", device_class: "裝置類別", vendor_name: "製造商", current_link_speed: "PCIe 鏈路速率", current_link_width: "PCIe 鏈路寬度", bus: "匯流排", device_node: "裝置節點", evidence: "觀測來源", captured_at: "觀測時間", line_count: "線路數"};
const propertyValue = (key, v) => { if (v === null || v === undefined) return "—"; if (key === "captured_at") return date(v); if (Array.isArray(v)) return v.length ? v.join(" · ") : "無"; if (typeof v === "boolean") return v ? "是" : "否"; return String(v); };
let current = null, receivedAt = 0, controller = null, generation = 0, offline = false;

function badge(state) { return make("span", stateNames[state] || state, `badge ${state}`); }
function statusClock() {
  updateHailoFreshness();
  if (!current) return;
  const age = finite(current.freshness?.age_seconds) ? current.freshness.age_seconds + (Date.now() - receivedAt) / 1000 : null;
  const state = offline ? "offline" : finite(age) && age > current.freshness.stale_after_seconds ? "stale" : current.status;
  $("status").textContent = stateNames[state] || state;
  $("status").className = `badge ${state}`;
  $("updated").textContent = `最後採樣 ${date(current.freshness?.captured_at)}${finite(age) ? ` · ${Math.floor(age)} 秒前` : ""}`;
  $("notice").hidden = !["offline", "stale", "unavailable"].includes(state);
  $("notice").textContent = state === "offline" ? "無法連線至 Scout。以下若有數值，為最後取得的紀錄。" : state === "stale" ? "採樣已超過更新期限，以下為最後紀錄，無法代表目前硬體狀態。" : "尚未取得有效採樣，請查看監控服務是否正常執行。";
}

function metric(title, value, details, percent) {
  const box = make("article", undefined, "metric"); box.append(make("h2", title), make("div", value, "value"));
  if (finite(percent)) { const meter = make("meter"); meter.min = 0; meter.max = 100; meter.value = percent; meter.setAttribute("aria-label", `${title} ${number(percent)}%`); box.append(meter); }
  details.forEach((text) => box.append(make("small", text))); return box;
}

function renderStatus(body) {
  current = body; receivedAt = Date.now(); hailoReceivedAt = performance.now(); offline = false; statusClock();
  const d = body.data; $("metrics").setAttribute("aria-busy", "false");
  renderHailo(d?.hailo);
  if (!d) { $("metrics").replaceChildren(make("p", "目前沒有可顯示的有效採樣。", "panel muted")); $("inventory").replaceChildren(make("p", "裝置資訊不可用", "panel muted")); $("resources").textContent = "資源資訊不可用"; $("alerts").textContent = body.summary; $("alert-count").textContent = "—"; $("uptime").textContent = ""; return; }
  const rawPower = d.power || {}, upsReadable = (rawPower.ups_status || rawPower.status) === "ok";
  const power = upsReadable ? rawPower : {}, supply = rawPower;
  const powerMessages = [];
  if (!upsReadable) powerMessages.push(rawPower.ups_error_code === "communication_error" ? "UPS 通訊失敗（I²C），電池讀值未知" : "UPS 電池資料未知或不可讀");
  if (rawPower.supply_status === "unavailable") powerMessages.push("主機供電資料部分不可讀；缺失讀值維持未知");
  if (!upsReadable && finite(supply.ext5v_v)) powerMessages.push("主機 5V 供電仍有讀值，不代表 UPS 通訊已恢復");
  const mem = d.memory || {}, disk = d.disks.find((v) => v.mount === "/") || {}, temp = d.sensors.find((v) => v.name === "cpu_thermal");
  const flow = {charging: "充電中", discharging: "放電中", idle: "待機"}[power.flow] || "未知";
  $("metrics").replaceChildren(
    metric("電池", `${number(power.battery_percent, 0)}%`, [`${flow} · ${number(finite(power.battery_power_w) ? Math.abs(power.battery_power_w) : null)} W`, `5V 供電 ${number(supply.ext5v_v, 2)} V`, ...powerMessages.map((message) => `△ ${message}`)], power.battery_percent),
    metric("記憶體", `${number(mem.used_percent)}%`, [`${gib(mem.used_bytes)} / ${gib(mem.total_bytes)}`, `可用 ${gib(mem.available_bytes)} · Swap ${gib(mem.swap_used_bytes)}`], mem.used_percent),
    metric("主磁碟", `${number(disk.used_percent)}%`, [`可用 ${gib(disk.available_bytes)}`, `總量 ${gib(disk.total_bytes)}`], disk.used_percent),
    metric("CPU 溫度", `${number(temp?.temperature_c)}°C`, [`CPU 使用 ${number(d.cpu_used_percent)}%`, `負載 ${d.load_average.map((v) => number(v, 2)).join(" / ")}`]));
  $("uptime").textContent = `開機 ${Math.floor(d.uptime_seconds / 3600)} 小時 ${Math.floor(d.uptime_seconds % 3600 / 60)} 分鐘`;
  const alerts = Object.values(d.alerts); $("alert-count").textContent = `${alerts.length} 項`;
  $("alerts").replaceChildren(...(alerts.length ? alerts.map((a) => { const row = make("div", undefined, "alert-row"); row.append(badge(a.severity), make("span", a.message)); return row; }) : [make("span", "目前沒有硬體告警。", "ok")]));
  const rows = [
    ["電池電壓／電流", `${number(power.battery_voltage_mv)} mV / ${number(power.battery_current_ma)} mA`],
    ["四芯電壓", power.cell_voltage_mv ? `${power.cell_voltage_mv.join(" / ")} mV` : "—"],
    ["目前欠壓／降頻旗標", supply.active_throttle_bits ?? "未知"],
    ["本次開機歷史旗標", supply.historical_throttle_bits ?? "未知"],
    ...d.disks.map((v) => [`磁碟 ${v.mount}`, `${gib(v.used_bytes)} / ${gib(v.total_bytes)} · 可用 ${gib(v.available_bytes)} · inode ${number(v.inode_used_percent)}% · ${v.read_only ? "唯讀" : "可讀寫"}`]),
    ...d.sensors.map((v) => [`${v.name} · ${v.source.split("/").at(-1)}`, finite(v.temperature_c) ? `${number(v.temperature_c)}°C` : `${number(v.rpm, 0)} RPM`])
  ];
  const resourceList = make("dl", undefined, "properties"); rows.forEach(([key, value]) => { const row = make("div"); row.append(make("dt", key), make("dd", value)); resourceList.append(row); }); $("resources").replaceChildren(resourceList);
  renderInventory(d.inventory);
}

const hailoStateNames = {ok: "已讀取", partial: "部分可讀", unavailable: "無法讀取", unknown: "未知"};
const hailoExpanded = new Map();
let hailoReceivedAt = 0;
const hailoReadState = (value) => Object.hasOwn(hailoStateNames, value) ? value : "unknown";
const hailoValue = (value, unit, digits = 1) => finite(value) ? `${number(value, digits)} ${unit}` : "未知";
const hailoTimestamp = (value) => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? Date.parse(value) : NaN;

function updateHailoFreshness() {
  const panel = $("hailo-panel"), hailo = current?.data?.hailo;
  const freshness = current?.freshness;
  const elapsed = Math.max(0, (performance.now() - hailoReceivedAt) / 1000);
  const captured = hailoTimestamp(freshness?.captured_at), hailoCaptured = hailoTimestamp(hailo?.captured_at);
  const serverTime = hailoTimestamp(current?.server_time);
  const freshnessTimeKnown = finite(freshness?.age_seconds) && freshness.age_seconds >= 0 && finite(captured);
  const age = freshnessTimeKnown ? freshness.age_seconds + elapsed : null;
  // Both timestamps come from Scout. Never subtract Scout time from the Mac's
  // wall clock; Hailo's end-of-query time may legitimately follow Snapshot time.
  const ownBaseAge = finite(hailoCaptured) && freshnessTimeKnown
    ? finite(serverTime) ? (serverTime - hailoCaptured) / 1000 : freshness.age_seconds + (captured - hailoCaptured) / 1000
    : null;
  const hailoAge = finite(ownBaseAge) && ownBaseAge >= 0 ? ownBaseAge + elapsed : null;
  $("hailo-age").textContent = `Hailo 資料年齡：${finite(hailoAge) && hailoAge >= 0 ? `${Math.floor(hailoAge)} 秒` : "未知"}`;
  const stale = current?.status === "stale" || freshness?.state === "stale"
    || (finite(age) && age > 150) || (finite(hailoAge) && hailoAge > 150);
  const invalid = current && (freshness?.state !== "fresh" || !freshnessTimeKnown || (hailo && !finite(hailoAge)));
  const state = offline ? "offline" : stale ? "stale" : current?.status === "unavailable" ? "unavailable" : invalid ? "invalid" : null;
  panel.classList.toggle("hailo-old", Boolean(state));
  const notice = $("hailo-freshness"); notice.hidden = !state;
  notice.textContent = state === "offline" ? "與 Scout 斷線：以下若有 Hailo 讀值或趨勢，為最後取得的紀錄，不能代表目前運作。每 60 秒自動重試。"
    : state === "stale" ? "資料已過期：以下 Hailo 讀值與趨勢為最後紀錄，不能代表目前運作。"
      : state === "invalid" ? "資料時間未知或無效：Hailo 採樣時間或全域 freshness 無法確認有效性；以下讀值僅為收到的紀錄，不能代表目前運作。"
        : state ? "採樣不可用：保留的 Hailo 紀錄不能代表目前運作。" : "";
  const readState = hailoReadState(hailo?.status);
  const label = state === "invalid" ? "資料時間未知／無效" : state ? stateNames[state] : hailo ? hailoStateNames[readState] : current ? "等待更新" : "正在讀取";
  $("hailo-state").textContent = label; $("hailo-state").className = `badge ${state === "invalid" ? "unavailable" : state || readState}`;
  panel.querySelectorAll(".hailo-read-status").forEach((node) => {
    node.textContent = `${state ? "最後紀錄 · " : ""}${hailoStateNames[node.dataset.readState]}`;
  });
  if (offline) {
    if (!current && panel.getAttribute("aria-busy") === "true") $("hailo-devices").replaceChildren(make("p", "尚未取得 Hailo 監測資料，等待連線恢復。", "panel muted"));
    panel.setAttribute("aria-busy", "false");
  }
}

function renderHailo(hailo) {
  const devices = $("hailo-devices");
  devices.querySelectorAll("details[data-key]").forEach((node) => hailoExpanded.set(node.dataset.key, node.open));
  const focusedKey = devices.contains(document.activeElement) && document.activeElement.tagName === "SUMMARY" ? document.activeElement.parentElement.dataset.key : null;
  $("hailo-panel").setAttribute("aria-busy", "false");
  $("hailo-errors").replaceChildren();
  if (!hailo) {
    $("hailo-meta").textContent = "尚無 Hailo 採樣時間／來源";
    devices.replaceChildren(make("p", current?.data ? "此筆舊版採樣尚無 Hailo 遙測，等待下一次更新。" : "目前沒有可顯示的 Hailo 採樣，等待更新。", "panel muted"));
    updateHailoFreshness(); return;
  }
  const sampleTime = finite(hailoTimestamp(hailo.captured_at)) ? date(hailo.captured_at) : "未知";
  const windowText = finite(hailo.sample_window_ms) ? `${number(hailo.sample_window_ms / 1000)} 秒` : "未知";
  $("hailo-meta").textContent = `Hailo 最後採樣 ${sampleTime}（Asia/Taipei） · 來源 ${hailo.source ?? "未知"} · 觀測窗口 ${windowText} · 唯讀 ${hailo.read_only === true ? "是" : "未知"}`;
  for (const error of hailo.errors || []) $("hailo-errors").append(make("p", `Hailo 讀取限制：${error}`, "notes warning"));
  const rows = (hailo.devices || []).map((device, index) => {
    const id = device.device_id ?? "未知裝置 ID";
    const key = JSON.stringify(["hailo", device.device_id ?? index]);
    const block = make("details", undefined, "device-group hailo-device");
    block.dataset.key = key; block.dataset.deviceId = id; block.dataset.hailoDevice = id;
    block.open = hailoExpanded.has(key) ? hailoExpanded.get(key) : true;
    const readState = hailoReadState(device.status), readBadge = make("span", hailoStateNames[readState], `badge hailo-read-status ${readState}`);
    readBadge.dataset.readState = readState;
    const summary = make("summary"); summary.append(make("h3", id), make("span", device.architecture ?? "未知架構", "group-summary"), readBadge); block.append(summary);
    const content = make("div", undefined, "group-body"), properties = make("dl", undefined, "properties hailo-properties");
    const metrics = [
      ["nnc_utilization_percent", "AI 核心使用率（NNC）", hailoValue(device.nnc_utilization_percent, "%")],
      ["cpu_utilization_percent", "Hailo 內部 CPU 使用率", hailoValue(device.cpu_utilization_percent, "%")],
      ["ram_utilization_percent", "Hailo 專用記憶體使用率", hailoValue(device.ram_utilization_percent, "%")],
      ["ram_used_bytes", "Hailo 專用記憶體已用", finite(device.ram_used_bytes) ? gib(device.ram_used_bytes) : "未知"],
      ["ram_total_bytes", "Hailo 專用記憶體總量", finite(device.ram_total_bytes) ? gib(device.ram_total_bytes) : "未知"],
      ["temperature_c", "Hailo 晶片溫度", hailoValue(device.temperature_c, "°C")],
      ["voltage_mv", "Hailo 晶片電壓（非功耗）", hailoValue(device.voltage_mv, "mV", 0)]
    ];
    for (const [key, label, value] of metrics) {
      const row = make("div"), reading = make("dd", value); reading.dataset.metric = key; reading.dataset.hailoMetric = key;
      row.append(make("dt", label), reading); properties.append(row);
    }
    content.append(properties);
    for (const error of device.errors || []) content.append(make("p", `讀取限制：${error}`, "notes warning"));
    block.append(content); return block;
  });
  devices.replaceChildren(...(rows.length ? rows : [make("p", hailo.status === "unavailable" ? "Hailo 遙測無法讀取，無法確認裝置清單。" : hailo.status === "partial" ? "尚未取得 Hailo 裝置，部分資料不可讀。" : "本次沒有偵測到 Hailo 裝置。", "panel muted")]));
  if (focusedKey !== null) rows.find((node) => node.dataset.key === focusedKey)?.firstElementChild.focus({preventScroll: true});
  updateHailoFreshness();
}

function renderHailoHistory(body) {
  const items = body.items || [], container = $("hailo-trends"), label = $("hailo-history-state");
  if (body.status === "unavailable") { label.textContent = "Hailo 歷史資料不可用"; container.replaceChildren(make("p", body.summary ?? "歷史讀取失敗", "panel muted")); return; }
  const ids = new Set(items.flatMap((item) => (item.hailo?.devices || []).map((device) => device.device_id)).filter((id) => id !== null && id !== undefined));
  const times = items.map((item) => item.hailo?.captured_at).filter((time) => finite(hailoTimestamp(time)));
  label.textContent = times.length ? `${date(times[0])} — ${date(times.at(-1))}（Asia/Taipei）${body.status === "partial" ? " · 部分紀錄不可用" : ""}` : `尚無 Hailo 歷史採樣${body.status === "partial" ? " · 部分紀錄不可用" : ""}`;
  const charts = [...ids].flatMap((id) => [
    ["nnc_utilization_percent", "AI 核心使用率（NNC）", "%"], ["temperature_c", "晶片溫度", "°C"]
  ].map(([key, title, unit]) => {
    const box = chart(`${id} · ${title}`, items, (item) => item.hailo?.devices?.find((device) => device.device_id === id)?.[key], unit, (item) => finite(hailoTimestamp(item.hailo?.captured_at)) ? item.hailo.captured_at : null);
    // A real isolated sample is a point, never a line over the missing interval.
    box.querySelectorAll("polyline").forEach((line) => {
      const points = line.getAttribute("points"); if (points.includes(" ")) return;
      const [x, y] = points.split(","), dot = document.createElementNS(line.namespaceURI, "circle");
      dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", "3");
      dot.setAttribute("class", "hailo-chart-point"); line.parentNode.append(dot);
    });
    box.dataset.deviceId = id; box.dataset.metric = key; return box;
  }));
  container.replaceChildren(...(charts.length ? charts : [make("p", "尚無 Hailo 裝置趨勢資料。", "panel muted")]));
}

function gpioTable(lines) {
  const wrap = make("div", undefined, "table-scroll"), table = make("table"), head = make("thead"), row = make("tr");
  ["線路", "名稱", "方向", "使用者", "Active low", "電位"].forEach((v) => {const th = make("th", v); th.scope = "col"; row.append(th);}); head.append(row); table.append(head);
  const body = make("tbody"); lines.forEach((line) => { const r = make("tr"); [line.offset, line.name || "—", {input: "輸入", output: "輸出", unknown: "未知"}[line.direction], line.consumer || "未被要求", line.active_low ? "是" : "否", "未採樣"].forEach((v) => r.append(make("td", String(v)))); body.append(r); });
  table.append(body); wrap.append(table); return wrap;
}

function renderInventory(inventory) {
  const expanded = new Set([...$("inventory").querySelectorAll("details[open]")].map((v) => v.dataset.key));
  const nodes = []; if (!inventory) { $("inventory").replaceChildren(make("p", "此筆舊版採樣尚無裝置清單，等待下一次更新。", "panel muted")); return; }
  for (const [key, group] of Object.entries(inventory.sections)) {
    const block = make("details", undefined, "device-group"); block.dataset.key = key; block.open = expanded.has(key) || ["network", "bluetooth"].includes(key);
    const summary = make("summary"), groupBadge = badge(group.status); if (group.status === "ok") groupBadge.textContent = "已讀取"; summary.append(make("h3", groupNames[key] || key), make("span", group.summary, "group-summary"), groupBadge); block.append(summary);
    const content = make("div", undefined, "group-body");
    if (!group.items.length) content.append(make("p", group.status === "unavailable" ? "目前無法讀取此類硬體資訊。" : "目前沒有偵測到裝置。", "muted"));
    for (const item of group.items) {
      const row = make("div", undefined, "device"), title = make("div", undefined, "device-title"); title.append(make("strong", item.name), make("span", item.id, "device-id"), badge(item.state)); row.append(title);
      const properties = make("dl", undefined, "properties");
      for (const [p, v] of Object.entries({...item.properties, ...(item.driver ? {driver: item.driver} : {})})) {
        if (["connected", "kind"].includes(p)) continue;
        const entry = make("div"); entry.append(make("dt", p === "driver" ? "驅動程式" : propertyNames[p] || p), make("dd", propertyValue(p, v))); properties.append(entry);
      }
      row.append(properties);
      if (item.lines?.length) { const lines = make("details", undefined, "line-details"); lines.dataset.key = item.id; lines.open = expanded.has(item.id); lines.append(make("summary", `${item.lines.length} 條 GPIO 線路詳情`), gpioTable(item.lines)); row.append(lines); }
      content.append(row);
    }
    group.notes.forEach((note) => content.append(make("p", note, "notes")));
    group.errors.forEach((error) => content.append(make("p", `讀取限制：${error}`, "notes warning")));
    block.append(content); nodes.push(block);
  }
  $("inventory").replaceChildren(...nodes);
}

function chart(title, items, getter, suffix, capturedAt = (item) => item.captured_at) {
  const box = make("div", undefined, "panel chart"); box.append(make("h3", title));
  const valid = items.map((v) => ({time: Date.parse(capturedAt(v)), value: getter(v)}));
  const values = valid.filter((v) => finite(v.value) && finite(v.time));
  if (values.length < 2) { box.append(make("p", "尚無足夠資料繪製趨勢", "muted")); return box; }
  const minTime = values[0].time, maxTime = values.at(-1).time, lo = Math.min(...values.map((v) => v.value)), hi = Math.max(...values.map((v) => v.value));
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 600 130"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${title}：${number(lo)} 至 ${number(hi)}${suffix}`);
  let segment = [], previousTime = null;
  const draw = () => { if (!segment.length) return; const line = document.createElementNS(svg.namespaceURI, "polyline"); line.setAttribute("class", "chart-line"); line.setAttribute("points", segment.join(" ")); svg.append(line); segment = []; };
  for (const point of valid) {
    if (!finite(point.value) || !finite(point.time)) { draw(); previousTime = null; continue; }
    if (previousTime !== null && (point.time - previousTime > 150000 || point.time <= previousTime)) draw();
    segment.push(`${10 + 580 * (point.time - minTime) / Math.max(1, maxTime - minTime)},${115 - 90 * (point.value - lo) / Math.max(1, hi - lo)}`); previousTime = point.time;
  }
  draw(); box.append(svg); const caption = make("footer"); caption.append(make("span", `${number(lo)} – ${number(hi)}${suffix}`), make("span", `${values.length} 筆有效採樣`)); box.append(caption); return box;
}

function renderHistory(body) {
  renderHailoHistory(body);
  if (body.status === "unavailable") { $("history-range").textContent = "歷史資料不可用"; $("history").replaceChildren(make("p", body.summary, "panel warning")); return; }
  const items = body.items || [];
  $("history-range").textContent = items.length ? `${date(items[0].captured_at)} — ${date(items.at(-1).captured_at)}${body.status === "partial" ? " · 部分紀錄不可用" : ""}` : "尚無歷史紀錄";
  $("history").replaceChildren(chart("電池電量", items, (v) => (v.power?.ups_status || v.power?.status) === "ok" ? v.power.battery_percent : null, "%"), chart("記憶體使用率", items, (v) => v.memory?.used_percent, "%"));
}

function renderEvents(body) {
  if (body.status === "unavailable") { $("events").replaceChildren(make("p", body.summary, "warning")); return; }
  const nodes = (body.items || []).slice().reverse().flatMap((item) => item.events.map((message) => { const row = make("div", undefined, "event"), time = make("time", date(item.captured_at)); time.dateTime = item.captured_at; row.append(time, make("span", message)); return row; }));
  $("events").replaceChildren(...(nodes.length ? nodes : [make("p", "目前沒有狀態變更事件。", "muted")]));
}

async function refresh() {
  controller?.abort(); controller = new AbortController(); const local = controller, ticket = ++generation;
  const timeout = setTimeout(() => local.abort(), 8000); $("refresh").disabled = true;
  const get = async (path) => { const response = await fetch(`/api/v1/hardware-monitor/${path}`, {signal: local.signal, cache: "no-store"}); const body = await response.json(); if (!body.schema_version) throw Error("Invalid monitor response"); return body; };
  const results = await Promise.allSettled([get("status"), get("history?limit=60"), get("events?limit=50")]);
  clearTimeout(timeout); if (ticket !== generation) return;
  if (results[0].status === "fulfilled") renderStatus(results[0].value);
  else { offline = true; if (current) statusClock(); else { $("status").textContent = "連線失敗"; $("status").className = "badge offline"; $("notice").hidden = false; $("notice").textContent = "無法取得 Scout 監控資料，請確認連線後重新讀取。"; $("metrics").setAttribute("aria-busy", "false"); $("metrics").textContent = "尚未取得監控結果"; } }
  updateHailoFreshness();
  if (results[1].status === "fulfilled") renderHistory(results[1].value); else { $("history-range").textContent = "歷史資料讀取失敗"; $("hailo-history-state").textContent = "Hailo 歷史讀取失敗；以下若有趨勢，為上次取得的歷史紀錄。"; }
  if (results[2].status === "fulfilled") renderEvents(results[2].value); else $("events").textContent = "事件紀錄讀取失敗";
  $("refresh").disabled = false;
}
$("refresh").addEventListener("click", refresh);
const poll = setInterval(refresh, 60000), clock = setInterval(statusClock, 1000);
window.addEventListener("pagehide", () => { clearInterval(poll); clearInterval(clock); controller?.abort(); });
refresh();
