from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE = "pi_wifi_prefer_networks"
HARDWARE_KIND = "field_wifi_priority_configuration"


@dataclass(frozen=True)
class AccessPointBlock:
    ssid: str
    lines: list[str]
    password: str | None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_access_point_blocks(text: str) -> list[AccessPointBlock]:
    lines = text.splitlines(keepends=True)
    access_points_index = _find_access_points_line(lines)
    if access_points_index is None:
        return []

    access_indent = _indent_width(lines[access_points_index])
    first_ap_index = _find_first_ap_line(lines, start=access_points_index + 1, access_indent=access_indent)
    if first_ap_index is None:
        return []

    ap_indent = _indent_width(lines[first_ap_index])
    blocks: list[AccessPointBlock] = []
    index = first_ap_index
    while index < len(lines):
        line = lines[index]
        if line.strip() and _indent_width(line) <= access_indent:
            break
        ssid = _parse_ssid_line(line, expected_indent=ap_indent)
        if ssid is None:
            index += 1
            continue
        block_start = index
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if next_line.strip() and _indent_width(next_line) <= access_indent:
                break
            if _parse_ssid_line(next_line, expected_indent=ap_indent) is not None:
                break
            index += 1
        block_lines = lines[block_start:index]
        blocks.append(AccessPointBlock(ssid=ssid, lines=block_lines, password=_parse_password(block_lines)))
    return blocks


def reorder_access_points(text: str, preferred_ssids: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    access_points_index = _find_access_points_line(lines)
    if access_points_index is None:
        return text

    access_indent = _indent_width(lines[access_points_index])
    first_ap_index = _find_first_ap_line(lines, start=access_points_index + 1, access_indent=access_indent)
    if first_ap_index is None:
        return text

    ap_indent = _indent_width(lines[first_ap_index])
    block_ranges: list[tuple[str, int, int]] = []
    index = first_ap_index
    while index < len(lines):
        line = lines[index]
        if line.strip() and _indent_width(line) <= access_indent:
            break
        ssid = _parse_ssid_line(line, expected_indent=ap_indent)
        if ssid is None:
            index += 1
            continue
        block_start = index
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if next_line.strip() and _indent_width(next_line) <= access_indent:
                break
            if _parse_ssid_line(next_line, expected_indent=ap_indent) is not None:
                break
            index += 1
        block_ranges.append((ssid, block_start, index))

    if not block_ranges:
        return text

    block_end = block_ranges[-1][2]
    rank = {ssid: position for position, ssid in enumerate(preferred_ssids)}
    ordered_ranges = sorted(
        enumerate(block_ranges),
        key=lambda item: (rank.get(item[1][0], len(rank) + item[0]), item[0]),
    )
    reordered: list[str] = []
    for _, (_, start, end) in ordered_ranges:
        reordered.extend(lines[start:end])
    return "".join(lines[: first_ap_index] + reordered + lines[block_end:])


def build_plan(
    *,
    access_points: list[AccessPointBlock],
    primary_ssid: str,
    fallback_ssids: list[str],
    primary_priority: int,
    fallback_priority: int,
) -> list[dict[str, Any]]:
    known = {access_point.ssid: access_point for access_point in access_points}
    ordered_ssids = [primary_ssid] + [ssid for ssid in fallback_ssids if ssid != primary_ssid]
    plan: list[dict[str, Any]] = []
    for index, ssid in enumerate(ordered_ssids):
        access_point = known.get(ssid)
        if access_point is None:
            plan.append(
                {
                    "ssid": ssid,
                    "connection_name": connection_name_for_ssid(ssid),
                    "priority": primary_priority if index == 0 else fallback_priority - index,
                    "password_available": False,
                    "action": "missing_from_network_config",
                }
            )
            continue
        plan.append(
            {
                "ssid": ssid,
                "connection_name": connection_name_for_ssid(ssid),
                "priority": primary_priority if index == 0 else fallback_priority - index,
                "password_available": access_point.password is not None,
                "action": "create_or_update_nm_profile",
            }
        )
    return plan


def connection_name_for_ssid(ssid: str) -> str:
    cleaned = re.sub(r"\s+", "-", ssid.strip())
    return f"scout-wifi-{cleaned}"


def apply_preferences(
    *,
    network_config: Path,
    primary_ssid: str,
    fallback_ssids: list[str],
    primary_priority: int,
    fallback_priority: int,
    switch_if_visible: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise PermissionError("applying Wi-Fi preferences requires sudo/root")

    original = network_config.read_text(encoding="utf-8")
    access_points = parse_access_point_blocks(original)
    known = {access_point.ssid: access_point for access_point in access_points}
    preferred_ssids = [primary_ssid] + [ssid for ssid in fallback_ssids if ssid != primary_ssid]
    updated = reorder_access_points(original, preferred_ssids)
    network_config.write_text(updated, encoding="utf-8")

    actions: list[dict[str, Any]] = []
    for index, ssid in enumerate(preferred_ssids):
        access_point = known.get(ssid)
        priority = primary_priority if index == 0 else fallback_priority - index
        if access_point is None:
            actions.append({"ssid": ssid, "status": "missing_from_network_config"})
            continue
        if not access_point.password:
            actions.append({"ssid": ssid, "status": "missing_password"})
            continue
        connection_name = connection_name_for_ssid(ssid)
        _ensure_nm_wifi_profile(
            connection_name=connection_name,
            ssid=ssid,
            password=access_point.password,
            priority=priority,
            timeout_seconds=timeout_seconds,
        )
        actions.append({"ssid": ssid, "connection_name": connection_name, "priority": priority, "status": "ok"})

    _lower_non_primary_wifi_profiles(
        primary_ssid=primary_ssid,
        fallback_ssids=fallback_ssids,
        primary_priority=primary_priority,
        fallback_priority=fallback_priority,
        timeout_seconds=timeout_seconds,
    )

    switch_status = "not_requested"
    if switch_if_visible:
        if _ssid_visible(primary_ssid=primary_ssid, timeout_seconds=timeout_seconds):
            _run_nmcli(["connection", "up", connection_name_for_ssid(primary_ssid)], timeout_seconds=timeout_seconds)
            switch_status = "switched_to_primary"
        else:
            switch_status = "primary_not_visible"

    return {
        "actions": actions,
        "network_config_reordered": updated != original,
        "switch_status": switch_status,
    }


def build_payload(
    *,
    network_config: Path,
    primary_ssid: str,
    fallback_ssids: list[str],
    plan: list[dict[str, Any]],
    applied: bool,
    apply_result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": utc_now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "network_config": str(network_config),
        "primary_ssid": primary_ssid,
        "fallback_ssids": fallback_ssids,
        "plan": plan,
        "applied": applied,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "wifi_boot_preference_configuration_only",
    }
    if apply_result is not None:
        payload["apply_result"] = apply_result
    if error is not None:
        payload["error"] = error
    return payload


def _ensure_nm_wifi_profile(
    *,
    connection_name: str,
    ssid: str,
    password: str,
    priority: int,
    timeout_seconds: float,
) -> None:
    if not _connection_exists(connection_name, timeout_seconds=timeout_seconds):
        _run_nmcli(
            [
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                "wlan0",
                "con-name",
                connection_name,
                "ssid",
                ssid,
            ],
            timeout_seconds=timeout_seconds,
        )
    _run_nmcli(
        [
            "connection",
            "modify",
            connection_name,
            "connection.autoconnect",
            "yes",
            "connection.autoconnect-priority",
            str(priority),
            "ipv4.method",
            "auto",
            "ipv6.method",
            "auto",
            "802-11-wireless.mode",
            "infrastructure",
            "wifi-sec.key-mgmt",
            "wpa-psk",
            "wifi-sec.psk",
            password,
        ],
        timeout_seconds=timeout_seconds,
    )


def _lower_non_primary_wifi_profiles(
    *,
    primary_ssid: str,
    fallback_ssids: list[str],
    primary_priority: int,
    fallback_priority: int,
    timeout_seconds: float,
) -> None:
    completed = _run_nmcli(
        ["-t", "-f", "NAME,TYPE,802-11-wireless.ssid", "connection", "show"],
        timeout_seconds=timeout_seconds,
    )
    fallback_rank = {ssid: index for index, ssid in enumerate(fallback_ssids)}
    for raw_line in completed.stdout.splitlines():
        fields = _split_nmcli_t(raw_line)
        if len(fields) < 3:
            continue
        name, connection_type, ssid = fields[:3]
        if connection_type != "802-11-wireless":
            continue
        if name.startswith("scout-wifi-"):
            continue
        if ssid == primary_ssid:
            priority = primary_priority
        elif ssid in fallback_rank:
            priority = fallback_priority - fallback_rank[ssid]
        else:
            priority = fallback_priority - 50
        _run_nmcli(
            ["connection", "modify", name, "connection.autoconnect", "yes", "connection.autoconnect-priority", str(priority)],
            timeout_seconds=timeout_seconds,
        )


def _connection_exists(connection_name: str, *, timeout_seconds: float) -> bool:
    completed = subprocess.run(
        ["nmcli", "-t", "-f", "NAME", "connection", "show"],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return connection_name in [_nmcli_unescape(line) for line in completed.stdout.splitlines()]


def _ssid_visible(*, primary_ssid: str, timeout_seconds: float) -> bool:
    completed = _run_nmcli(
        ["-t", "-f", "SSID", "dev", "wifi", "list", "--rescan", "yes"],
        timeout_seconds=timeout_seconds,
    )
    return primary_ssid in [_nmcli_unescape(line) for line in completed.stdout.splitlines()]


def _run_nmcli(args: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["nmcli", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _find_access_points_line(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == "access-points:":
            return index
    return None


def _find_first_ap_line(lines: list[str], *, start: int, access_indent: int) -> int | None:
    for index in range(start, len(lines)):
        line = lines[index]
        if line.strip() and _indent_width(line) <= access_indent:
            return None
        if _parse_ssid_line(line, expected_indent=None) is not None:
            return index
    return None


def _parse_ssid_line(line: str, *, expected_indent: int | None) -> str | None:
    if expected_indent is not None and _indent_width(line) != expected_indent:
        return None
    stripped = line.strip()
    if not stripped or not stripped.endswith(":") or stripped.startswith(("password:", "auth:", "key-management:")):
        return None
    value = stripped[:-1].strip()
    if not value:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value


def _parse_password(block_lines: list[str]) -> str | None:
    for line in block_lines[1:]:
        stripped = line.strip()
        if not stripped.startswith("password:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value
    return None


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_nmcli_t(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == ":":
            fields.append("".join(current))
            current = []
            continue
        current.append(char)
    fields.append("".join(current))
    return fields


def _nmcli_unescape(value: str) -> str:
    return value.replace(r"\:", ":").replace(r"\\", "\\")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefer Scout's stable Wi-Fi over field hotspots.")
    parser.add_argument("--network-config", type=Path, default=Path("/boot/firmware/network-config"))
    parser.add_argument("--primary-ssid", default="ASUS_5G")
    parser.add_argument("--fallback-ssid", action="append", default=[])
    parser.add_argument("--primary-priority", type=int, default=100)
    parser.add_argument("--fallback-priority", type=int, default=-20)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--switch-if-visible", action="store_true")
    args = parser.parse_args(argv)

    try:
        text = args.network_config.read_text(encoding="utf-8")
        access_points = parse_access_point_blocks(text)
        configured_ssids = [access_point.ssid for access_point in access_points]
        fallback_ssids = args.fallback_ssid or [ssid for ssid in configured_ssids if ssid != args.primary_ssid]
        plan = build_plan(
            access_points=access_points,
            primary_ssid=args.primary_ssid,
            fallback_ssids=fallback_ssids,
            primary_priority=args.primary_priority,
            fallback_priority=args.fallback_priority,
        )
        apply_result = None
        if args.apply:
            apply_result = apply_preferences(
                network_config=args.network_config,
                primary_ssid=args.primary_ssid,
                fallback_ssids=fallback_ssids,
                primary_priority=args.primary_priority,
                fallback_priority=args.fallback_priority,
                switch_if_visible=args.switch_if_visible,
                timeout_seconds=args.timeout_seconds,
            )
        payload = build_payload(
            network_config=args.network_config,
            primary_ssid=args.primary_ssid,
            fallback_ssids=fallback_ssids,
            plan=plan,
            applied=args.apply,
            apply_result=apply_result,
        )
    except Exception as exc:
        payload = build_payload(
            network_config=args.network_config,
            primary_ssid=args.primary_ssid,
            fallback_ssids=args.fallback_ssid,
            plan=[],
            applied=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
