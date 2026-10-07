"""Read-only, conservative discovery of one physical private LAN IPv4 address.

Discovery is advisory: the launcher must still verify its actual bind. Unknown OS
metadata fails closed and must not disable the launcher's existing loopback mode.
No probes, routes, credentials, SSIDs or hardware identifiers are retained.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import selectors
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_COMMAND_TIMEOUT = 2.0
_MAX_OUTPUT = 65536
_MAX_INTERFACES = 256
_MAX_CANDIDATES = 32
_PRIVATE_IPV4 = tuple(ipaddress.IPv4Network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_VIRTUAL_PREFIXES = ("tun", "utun", "tap", "wg", "tailscale", "docker", "veth",
                     "virbr", "bridge", "br-", "vmnet", "vboxnet", "awdl", "llw", "ppp",
                     "ipsec", "zt")


@dataclass(frozen=True, slots=True)
class LanSelection:
    address: str | None
    reason: Literal["selected", "none", "ambiguous", "unsupported"]
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LanInterface:
    """Small normalized OS record; physical/active require corroborating metadata."""

    name: str
    kind: str
    active: bool
    physical: bool
    addresses: tuple[str, ...]


def select_lan_address(interface_records: Iterable[LanInterface]) -> LanSelection:
    """Choose only one eligible interface/address pair; never rank adapters."""
    pairs: set[tuple[str, str]] = set()
    for index, record in enumerate(interface_records):
        if index >= _MAX_INTERFACES:
            return LanSelection(None, "unsupported")
        if (not record.active or not record.physical or record.kind not in {"wifi", "ethernet"}
                or not _physical_name(record.name)):
            continue
        for address in record.addresses:
            try:
                parsed = ipaddress.IPv4Address(address)
            except ipaddress.AddressValueError:
                continue
            if any(parsed in network for network in _PRIVATE_IPV4):
                pairs.add((record.name, str(parsed)))
                if len(pairs) > _MAX_CANDIDATES:
                    return LanSelection(None, "unsupported")
    candidates = tuple(sorted({address for _, address in pairs}, key=ipaddress.IPv4Address))
    if not pairs:
        return LanSelection(None, "none")
    if len(pairs) != 1:
        return LanSelection(None, "ambiguous", candidates)
    return LanSelection(candidates[0], "selected", candidates)


def discover_lan_address(
    *, platform_name: str | None = None,
    runner: Callable[[tuple[str, ...]], str] | None = None,
    sysfs_root: Path | None = None,
) -> LanSelection:
    """Read macOS/Linux metadata; injectable dependencies keep fixtures offline.

    Windows and unsupported/failing metadata return ``unsupported``. Explicit
    private-address validation belongs to the caller and need not call discovery.
    """
    platform_name = platform_name if platform_name is not None else sys.platform
    run = runner if runner is not None else _bounded_run
    try:
        if platform_name == "darwin":
            ports = _command_text(run, ("/usr/sbin/networksetup", "-listallhardwareports"))
            links = _command_text(run, ("/sbin/ifconfig", "-a"))
            records = _macos_interfaces(ports, links)
        elif platform_name == "linux":
            links = _command_text(run, ("ip", "-j", "-d", "address", "show"))
            root = sysfs_root if sysfs_root is not None else Path("/sys/class/net")
            records = _linux_interfaces(links, root)
        else:
            return LanSelection(None, "unsupported")
        return select_lan_address(records)
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError):
        # Neither command output nor exception details leave this boundary.
        return LanSelection(None, "unsupported")


def _physical_name(name: str) -> bool:
    return (bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", name)) and name != "lo"
            and not name.lower().startswith(_VIRTUAL_PREFIXES))


def _command_text(run: Callable[[tuple[str, ...]], str], command: tuple[str, ...]) -> str:
    output = run(command)
    if not isinstance(output, str) or len(output.encode("utf-8")) > _MAX_OUTPUT:
        raise ValueError("lan_metadata_unavailable")
    return output


def _bounded_run(command: tuple[str, ...]) -> str:
    """Fixed read-only commands only, with a wall timeout and hard stdout cap."""
    deadline = time.monotonic() + _COMMAND_TIMEOUT
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,
                               env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
    assert process.stdout is not None
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("lan_metadata_unavailable")
                chunk = os.read(process.stdout.fileno(), min(4096, _MAX_OUTPUT + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > _MAX_OUTPUT:
                    raise ValueError("lan_metadata_unavailable")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining) != 0:
            raise ValueError("lan_metadata_unavailable")
        return output.decode("utf-8", errors="strict")
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
        process.stdout.close()


def _macos_interfaces(ports: str, links: str) -> tuple[LanInterface, ...]:
    hardware: dict[str, str] = {}
    port = ""
    saw_port = False
    for line in ports.splitlines():
        if line.startswith("Hardware Port: "):
            saw_port = True
            port = line.removeprefix("Hardware Port: ").strip()
        elif line.startswith("Device: "):
            name = line.removeprefix("Device: ").strip()
            if not re.fullmatch(r"en[0-9]+", name):
                continue
            if port in {"Wi-Fi", "AirPort"}:
                kind = "wifi"
            elif ("Ethernet" in port or re.fullmatch(r"USB [0-9/]+ LAN", port)) and not any(
                    value in port for value in ("Bridge", "VLAN", "Bluetooth", "VPN")):
                kind = "ethernet"
            else:
                continue
            if name in hardware:
                raise ValueError("lan_metadata_unavailable")
            hardware[name] = kind
    blocks = re.split(r"(?m)^(?=[A-Za-z0-9_.-]+: flags=)", links)
    records = []
    saw_link = False
    for block in blocks:
        header = re.match(r"([A-Za-z0-9_.-]+): flags=[^<\n]*<([^>\n]+)>", block)
        if header is None:
            continue
        saw_link = True
        name, flags_text = header.groups()
        if name not in hardware:
            continue
        flags = set(flags_text.split(","))
        active = ({"UP", "RUNNING"} <= flags and not {"LOOPBACK", "POINTOPOINT"} & flags
                  and re.search(r"(?m)^\s*status: active\s*$", block) is not None)
        addresses = tuple(re.findall(r"(?m)^\s+inet ([^\s]+)", block))
        records.append(LanInterface(name, hardware[name], active, True, addresses))
    if not saw_port or not saw_link:
        raise ValueError("lan_metadata_unavailable")
    return tuple(records)


def _linux_interfaces(links: str, root: Path) -> tuple[LanInterface, ...]:
    data = json.loads(links)
    if not isinstance(data, list) or len(data) > _MAX_INTERFACES or not root.is_dir():
        raise ValueError("lan_metadata_unavailable")
    records = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("lan_metadata_unavailable")
        name = item.get("ifname")
        if not isinstance(name, str) or not _physical_name(name):
            continue
        flags = item.get("flags", [])
        linkinfo = item.get("linkinfo", {})
        addresses = item.get("addr_info", [])
        if (not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags)
                or not isinstance(linkinfo, dict) or not isinstance(addresses, list)
                or not all(isinstance(address, dict) for address in addresses)):
            raise ValueError("lan_metadata_unavailable")
        if (item.get("link_type") != "ether" or item.get("operstate") != "UP"
                or not {"UP", "LOWER_UP"} <= set(flags)
                or {"LOOPBACK", "POINTOPOINT"} & set(flags)
                or linkinfo.get("info_kind")):
            continue
        adapter = (root / name).resolve(strict=True)
        if "virtual" in adapter.parts or not (adapter / "device").is_dir():
            continue
        with (adapter / "type").open(encoding="ascii") as metadata:
            if metadata.read(16).strip() != "1":
                continue
        kind = "wifi" if (adapter / "wireless").is_dir() else "ethernet"
        usable = tuple(address["local"] for address in addresses
                       if address.get("family") == "inet" and address.get("scope") == "global"
                       and isinstance(address.get("local"), str)
                       and not address.get("tentative") and not address.get("dadfailed"))
        records.append(LanInterface(name, kind, True, True, usable))
    return tuple(records)
