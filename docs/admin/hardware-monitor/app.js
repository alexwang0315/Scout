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
  current = body; receivedAt = Date.now(); offline = false; statusClock();
  const d = body.data; $("metrics").setAttribute("aria-busy", "false");
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

function chart(title, items, getter, suffix) {
  const box = make("div", undefined, "panel chart"); box.append(make("h3", title));
  const valid = items.map((v) => ({time: Date.parse(v.captured_at), value: getter(v)}));
  const values = valid.filter((v) => finite(v.value) && finite(v.time));
  if (values.length < 2) { box.append(make("p", "尚無足夠資料繪製趨勢", "muted")); return box; }
  const minTime = values[0].time, maxTime = values.at(-1).time, lo = Math.min(...values.map((v) => v.value)), hi = Math.max(...values.map((v) => v.value));
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 600 130"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${title}：${number(lo)} 至 ${number(hi)}${suffix}`);
  let segment = [], previousTime = null;
  const draw = () => { if (!segment.length) return; const line = document.createElementNS(svg.namespaceURI, "polyline"); line.setAttribute("class", "chart-line"); line.setAttribute("points", segment.join(" ")); svg.append(line); segment = []; };
  for (const point of valid) {
    if (!finite(point.value)) { draw(); previousTime = null; continue; }
    if (previousTime !== null && point.time - previousTime > 150000) draw();
    segment.push(`${10 + 580 * (point.time - minTime) / Math.max(1, maxTime - minTime)},${115 - 90 * (point.value - lo) / Math.max(1, hi - lo)}`); previousTime = point.time;
  }
  draw(); box.append(svg); const caption = make("footer"); caption.append(make("span", `${number(lo)} – ${number(hi)}${suffix}`), make("span", `${values.length} 筆有效採樣`)); box.append(caption); return box;
}

function renderHistory(body) {
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
  if (results[1].status === "fulfilled") renderHistory(results[1].value); else $("history-range").textContent = "歷史資料讀取失敗";
  if (results[2].status === "fulfilled") renderEvents(results[2].value); else $("events").textContent = "事件紀錄讀取失敗";
  $("refresh").disabled = false;
}
$("refresh").addEventListener("click", refresh);
const poll = setInterval(refresh, 60000), clock = setInterval(statusClock, 1000);
window.addEventListener("pagehide", () => { clearInterval(poll); clearInterval(clock); controller?.abort(); });
refresh();
