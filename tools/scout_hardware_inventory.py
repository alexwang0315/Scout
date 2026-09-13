"""Passive Linux hardware inventory; no scans, pairing, GPIO requests or writes."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def driver(path: Path) -> str | None:
    link = path / "driver"
    return link.resolve().name if link.is_symlink() else None


def command(args: list[str]) -> str:
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=3, env={**os.environ, "LC_ALL": "C"})
    if result.returncode:
        raise OSError(f"{args[0]} exited {result.returncode}")
    return result.stdout


def device(identifier: str, name: str, state: str = "present", *, properties=None,
           bound_driver: str | None = None, lines=None) -> dict:
    result = {"id": identifier, "name": name, "state": state, "driver": bound_driver,
              "properties": properties or {}}
    if lines is not None:
        result["lines"] = lines
    return result


def section(items: list, summary: str, notes=None, errors=None) -> dict:
    return {"status": "partial" if errors else "ok", "summary": summary,
            "items": items, "notes": notes or [], "errors": errors or []}


def parse_wifi_link(text: str) -> dict:
    if not text.strip().startswith(("Connected to ", "Not connected.")):
        raise ValueError("unrecognized Wi-Fi link response")
    result = {"connected": text.lstrip().startswith("Connected to "), "ssid": None,
              "signal_dbm": None, "frequency_mhz": None, "tx_bitrate_mbps": None}
    for key, pattern in (("ssid", r"^\s*SSID: (.*)$"),
                         ("signal_dbm", r"^\s*signal:\s*(-?[\d.]+) dBm"),
                         ("frequency_mhz", r"^\s*freq:\s*([\d.]+)"),
                         ("tx_bitrate_mbps", r"^\s*tx bitrate:\s*([\d.]+) MBit/s")):
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            result[key] = match[1] if key == "ssid" else float(match[1])
    return result


def rfkill(sys_root: Path, kind: str) -> list[dict]:
    records = []
    for path in sorted((sys_root / "class/rfkill").glob("rfkill*")):
        if read_text(path / "type") == kind:
            records.append({"name": read_text(path / "name"),
                            "soft_blocked": read_text(path / "soft") == "1",
                            "hard_blocked": read_text(path / "hard") == "1"})
    return records


def network(sys_root: Path, run=command) -> dict:
    items, errors = [], []
    address_records = json.loads(run(["ip", "-j", "address", "show"]))
    addresses = {item["ifname"]: item for item in address_records}
    radios = rfkill(sys_root, "wlan")
    for path in sorted((sys_root / "class/net").iterdir()):
        wifi = (path / "wireless").exists() or (path / "phy80211").exists()
        if not wifi and not (path / "device").exists():
            continue
        props = {"kind": "wifi" if wifi else "ethernet", "operstate": read_text(path / "operstate"),
                 "ipv4": [a["local"] for a in addresses.get(path.name, {}).get("addr_info", []) if a["family"] == "inet"],
                 "ipv6": [a["local"] for a in addresses.get(path.name, {}).get("addr_info", []) if a["family"] == "inet6" and a.get("scope") == "global"]}
        state = "connected" if props["operstate"] == "up" else "disconnected"
        if wifi:
            props["soft_blocked"] = any(r["soft_blocked"] for r in radios) if radios else None
            props["hard_blocked"] = any(r["hard_blocked"] for r in radios) if radios else None
            try:
                props.update(parse_wifi_link(run(["iw", "dev", path.name, "link"])))
                state = "connected" if props["connected"] else "disconnected"
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                errors.append(path.name + ": " + type(exc).__name__)
                props.update(ssid=None, signal_dbm=None)
            if props["soft_blocked"] or props["hard_blocked"]:
                state = "blocked"
        items.append(device(path.name, path.name, state, properties=props, bound_driver=driver(path / "device")))
    return section(items, f"{sum(d['state'] == 'connected' for d in items)} / {len(items)} 個實體網路介面已連線",
                   ["只讀取目前連線，不掃描周邊 Wi-Fi，也不讀取密碼。"], errors)


def bluetooth(sys_root: Path, run=command) -> dict:
    items, errors = [], []
    controllers = run(["bluetoothctl", "list"])
    radios = rfkill(sys_root, "bluetooth")
    for address, name in re.findall(r"^Controller ([0-9A-Fa-f:]{17}) (.+?)(?: \[default\])?$", controllers, re.MULTILINE):
        try:
            raw = run(["bluetoothctl", "show", address])
            props = {"kind": "controller", "address": address,
                     "soft_blocked": any(r["soft_blocked"] for r in radios) if radios else None,
                     "hard_blocked": any(r["hard_blocked"] for r in radios) if radios else None}
            for key in ("Powered", "Discoverable", "Pairable", "Discovering"):
                match = re.search(r"^\s*" + key + r": (yes|no)$", raw, re.MULTILINE)
                props[key.lower()] = match[1] == "yes" if match else None
            state = "powered_on" if props["powered"] is True else "powered_off" if props["powered"] is False else "unknown"
            if props["soft_blocked"] or props["hard_blocked"]:
                state = "blocked"
            items.append(device(address, name, state, properties=props))
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append("controller: " + type(exc).__name__)
            items.append(device(address, name, "unknown"))
    try:
        connected = run(["bluetoothctl", "devices", "Connected"])
        for address, name in re.findall(r"^Device ([0-9A-Fa-f:]{17}) (.+)$", connected, re.MULTILINE):
            items.append(device(address, name, "connected", properties={"kind": "connected_device", "address": address}))
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append("connected devices: " + type(exc).__name__)
    return section(items, f"{sum(d['state'] == 'connected' for d in items)} 個藍牙裝置已連線",
                   ["列出控制器與預設控制器目前的連線裝置，不開始探索或配對。"], errors)


def usb(sys_root: Path) -> dict:
    items = []
    for path in sorted((sys_root / "bus/usb/devices").iterdir()):
        if not (path / "idVendor").exists():
            continue
        props = {key: read_text(path / key) for key in ("idVendor", "idProduct", "manufacturer", "speed", "authorized")}
        props["root_hub"] = path.name.startswith("usb")
        props["interface_drivers"] = sorted({name for child in path.glob(path.name + ":*") if (name := driver(child))})
        items.append(device(path.name, read_text(path / "product") or "USB device", properties=props, bound_driver=driver(path)))
    external = sum(not item["properties"]["root_hub"] for item in items)
    return section(items, f"{external} 個外接 USB 裝置，{len(items) - external} 個根集線器",
                   ["系統枚舉資訊表示裝置存在，不代表已通過功能測試。"])


def pcie(sys_root: Path, run=command) -> dict:
    names, errors = {}, []
    try:
        for line in run(["lspci", "-Dmm"]).splitlines():
            fields = shlex.split(line)
            if len(fields) >= 4:
                names[fields[0]] = fields[1:4]
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        errors.append("PCIe names: " + type(exc).__name__)
    items = []
    for path in sorted((sys_root / "bus/pci/devices").iterdir()):
        props = {key: read_text(path / key) for key in ("vendor", "device", "class", "current_link_speed", "current_link_width")}
        label = names.get(path.name, [])
        if label:
            props.update(device_class=label[0], vendor_name=label[1])
        items.append(device(path.name, label[2] if label else f"PCIe {props['vendor']}:{props['device']}",
                            properties=props, bound_driver=driver(path)))
    return section(items, f"{len(items)} 個 PCIe 裝置／橋接器", ["顯示枚舉、驅動與協商鏈路資訊。"], errors)


def i2c(sys_root: Path, power: dict) -> dict:
    root = sys_root / "bus/i2c/devices"
    items = []
    for path in sorted(root.iterdir()):
        if re.fullmatch(r"i2c-\d+", path.name):
            items.append(device(path.name, read_text(path / "name") or path.name,
                                properties={"kind": "adapter", "device_node": "/dev/" + path.name}))
        elif re.fullmatch(r"\d+-[\da-fA-F]{4}", path.name):
            bus, address = path.name.split("-")
            items.append(device(path.name, read_text(path / "name") or path.name,
                                properties={"kind": "registered_device", "bus": bus, "address": hex(int(address, 16))},
                                bound_driver=driver(path)))
    if power.get("ups_status", power.get("status")) == "ok":
        items.append(device("ups-telemetry-1-002d", "Waveshare UPS HAT E", "observed",
                            properties={"kind": "telemetry_device", "bus": "1", "address": "0x2d",
                                        "evidence": "existing_ups_telemetry", "captured_at": power.get("captured_at")}))
    return section(items, f"{sum(d['properties']['kind'] == 'adapter' for d in items)} 條 I²C 匯流排",
                   ["未執行位址掃描；未列出的裝置不代表沒有接上。UPS 來自既有電源觀測紀錄。"])


def parse_gpio_info(text: str) -> list[dict]:
    chips, current = [], None
    for line in text.splitlines():
        match = re.match(r"(gpiochip\d+)(?: \[([^]]+)\])? - (\d+) lines:", line)
        if match:
            current = device(match[1], match[2] or match[1], properties={"line_count": int(match[3])}, lines=[])
            chips.append(current)
            continue
        match = re.match(r'\s*line\s+(\d+):\s*(?:"([^"]*)"|(unnamed))\s+(.*)', line)
        if match and current is not None:
            flags = match[4]
            direction = re.search(r"\b(input|output)\b", flags)
            consumer = re.search(r'consumer="([^"]*)"', flags)
            current["lines"].append({"offset": int(match[1]), "name": match[2] or None,
                                     "direction": direction[1] if direction else "unknown",
                                     "consumer": consumer[1] if consumer else None,
                                     "active_low": "active-low" in flags, "value": None})
    return chips


def gpio(sys_root: Path, run=command) -> dict:
    chips = parse_gpio_info(run(["gpioinfo"]))
    if not chips:
        raise ValueError("no GPIO chip metadata in gpioinfo output")
    # /dev chip numbers differ from legacy sysfs gpiochip bases; use gpiodetect labels.
    labels = {m[1]: m[2] for line in run(["gpiodetect"]).splitlines()
              if (m := re.match(r"(gpiochip\d+) \[([^]]+)\]", line))}
    for chip in chips:
        chip["name"] = labels.get(chip["id"], chip["name"])
        chip["properties"]["device_node"] = "/dev/" + chip["id"]
    return section(chips, f"{len(chips)} 個 GPIO 控制器，{sum(len(d['lines']) for d in chips)} 條線路",
                   ["只讀取方向與 consumer；未要求線路、未讀取電位、未變更輸出。"])


def serial(dev_root: Path) -> dict:
    nodes = sorted({path for pattern in ("ttyAMA*", "ttyUSB*", "ttyACM*", "serial[0-9]*") for path in dev_root.glob(pattern)})
    return section([device(path.name, path.name, properties={"device_node": str(path)}) for path in nodes],
                   f"{len(nodes)} 個 UART／序列裝置節點", ["只列出裝置節點，不開啟序列埠或讀取資料流。"])


def collect_inventory(power: dict, *, sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev"), run=command) -> dict:
    sections = {}
    collectors = {"network": lambda: network(sys_root, run), "bluetooth": lambda: bluetooth(sys_root, run),
                  "usb": lambda: usb(sys_root), "pcie": lambda: pcie(sys_root, run),
                  "i2c": lambda: i2c(sys_root, power), "gpio": lambda: gpio(sys_root, run),
                  "serial": lambda: serial(dev_root)}
    for name, collect in collectors.items():
        try:
            sections[name] = collect()
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
            sections[name] = {"status": "unavailable", "summary": "此類硬體資訊目前不可用",
                              "items": [], "notes": [], "errors": [type(exc).__name__]}
    return {"captured_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok" if all(s["status"] == "ok" for s in sections.values()) else "partial",
            "sections": sections, "read_only": True, "active_scan_performed": False,
            "gpio_value_sampling_performed": False}
