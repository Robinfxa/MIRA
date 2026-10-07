"""Synthetic OS metadata only; these tests never inspect the host's LAN."""
import importlib
import json
import socket
import subprocess
import sys
import time
from dataclasses import FrozenInstanceError

import pytest

from tools import lan_discovery
from tools.lan_discovery import LanInterface, discover_lan_address, select_lan_address


def interface(name="wlan0", addresses=("192.168.20.8",), **updates):
    values = dict(name=name, kind="wifi", active=True, physical=True, addresses=addresses)
    return LanInterface(**(values | updates))


def test_unique_wifi_is_selected_with_only_address_in_result():
    result = select_lan_address([interface()])
    assert (result.address, result.reason, result.candidates) == (
        "192.168.20.8", "selected", ("192.168.20.8",))
    with pytest.raises(FrozenInstanceError):
        result.address = "10.0.0.1"


def test_ethernet_and_wifi_are_ambiguous_regardless_of_input_order():
    records = [interface(), interface("eth0", ("10.1.0.4",), kind="ethernet")]
    result = select_lan_address(records)
    assert result == select_lan_address(reversed(records))
    assert result.address is None and result.reason == "ambiguous"
    assert result.candidates == ("10.1.0.4", "192.168.20.8")


def test_same_address_on_two_physical_interfaces_is_still_ambiguous():
    result = select_lan_address([interface(), interface("eth0", kind="ethernet")])
    assert result.reason == "ambiguous" and result.address is None


def test_multiple_addresses_on_one_interface_are_ambiguous():
    result = select_lan_address([interface(addresses=("192.168.20.8", "192.168.20.9"))])
    assert result.reason == "ambiguous" and result.address is None


@pytest.mark.parametrize("updates", [
    {"name": "utun1", "kind": "tunnel", "physical": False},
    {"name": "tun0", "physical": False},
    {"name": "docker0", "physical": False},
    {"name": "lo", "kind": "loopback", "physical": False},
    {"active": False}, {"kind": "unknown"}, {"physical": False},
])
def test_nonphysical_inactive_unknown_or_vpn_interfaces_are_excluded(updates):
    assert select_lan_address([interface(**updates)]).reason == "none"


@pytest.mark.parametrize("address", [
    "127.0.0.1", "0.0.0.0", "8.8.8.8", "169.254.1.8", "100.64.0.1",
    "192.0.2.8", "198.18.0.1", "224.0.0.1", "::", "::1", "fe80::1%en0",
    "fd12:3456::1", "fd12:3456::1%en0", "192.168.1.1/24", "localhost", "bad",
])
def test_only_rfc1918_ipv4_is_automatically_selected(address):
    assert select_lan_address([interface(addresses=(address,))]).reason == "none"


def hardware_ports(*ports):
    return "\n\n".join(f"Hardware Port: {kind}\nDevice: {name}\n" for kind, name in ports)


def ifconfig(name="en0", address="192.168.20.8", status="active", flags="UP,RUNNING"):
    return (f"{name}: flags=8863<{flags}> mtu 1500\n"
            f"\tinet {address} netmask 0xffffff00 broadcast 192.168.20.255\n"
            f"\tstatus: {status}\n")


class FakeRunner:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    def __call__(self, command):
        self.calls.append(command)
        value = next(self.values)
        if isinstance(value, BaseException):
            raise value
        return value


def test_macos_wifi_is_confirmed_by_hardware_and_active_link():
    runner = FakeRunner([hardware_ports(("Wi-Fi", "en0")), ifconfig()])
    result = discover_lan_address(platform_name="darwin", runner=runner)
    assert result.address == "192.168.20.8"
    assert runner.calls == [("/usr/sbin/networksetup", "-listallhardwareports"),
                            ("/sbin/ifconfig", "-a")]


def test_macos_vpn_and_virtual_links_are_not_selected_next_to_wifi():
    runner = FakeRunner([
        hardware_ports(("Wi-Fi", "en0"), ("Thunderbolt Bridge", "bridge0")),
        ifconfig() + ifconfig("utun0", "10.8.0.2", flags="UP,RUNNING,POINTOPOINT")
        + ifconfig("bridge0", "10.9.0.1")])
    assert discover_lan_address(platform_name="darwin", runner=runner).address == "192.168.20.8"


def test_macos_two_physical_adapters_are_ambiguous():
    runner = FakeRunner([hardware_ports(("Wi-Fi", "en0"), ("USB Ethernet", "en5")),
                         ifconfig() + ifconfig("en5", "10.1.0.4")])
    assert discover_lan_address(platform_name="darwin", runner=runner).reason == "ambiguous"


@pytest.mark.parametrize("body", [ifconfig(status="inactive"),
                                    ifconfig(flags="UP,POINTOPOINT,RUNNING"),
                                    ifconfig(flags="RUNNING"), ifconfig("utun0")])
def test_macos_unconfirmed_or_inactive_link_is_not_selected(body):
    runner = FakeRunner([hardware_ports(("Wi-Fi", "en0")), body])
    assert discover_lan_address(platform_name="darwin", runner=runner).reason == "none"


def linux_record(name="wlan0", address="192.168.20.8", **changes):
    return {"ifname": name, "link_type": "ether", "flags": ["UP", "LOWER_UP"],
            "operstate": "UP", "addr_info": [{"family": "inet", "local": address,
                                              "scope": "global"}], **changes}


def sysfs_adapter(root, name, wifi=False):
    adapter = root / name
    (adapter / "device").mkdir(parents=True)
    (adapter / "type").write_text("1\n")
    if wifi:
        (adapter / "wireless").mkdir()


def test_linux_requires_physical_sysfs_evidence_and_active_ip_metadata(tmp_path):
    sysfs_adapter(tmp_path, "wlan0", wifi=True)
    runner = FakeRunner([json.dumps([linux_record(), linux_record("tun0", "10.8.0.2")])])
    result = discover_lan_address(platform_name="linux", runner=runner, sysfs_root=tmp_path)
    assert result.address == "192.168.20.8"
    assert runner.calls == [("ip", "-j", "-d", "address", "show")]


@pytest.mark.parametrize("changes", [
    {"operstate": "DOWN"}, {"flags": ["UP"]}, {"flags": ["UP", "LOWER_UP", "POINTOPOINT"]},
    {"linkinfo": {"info_kind": "wireguard"}}, {"link_type": "loopback"},
])
def test_linux_rejects_inactive_or_virtual_metadata_even_with_device_entry(tmp_path, changes):
    sysfs_adapter(tmp_path, "wlan0", wifi=True)
    runner = FakeRunner([json.dumps([linux_record(**changes)])])
    assert discover_lan_address(platform_name="linux", runner=runner,
                                sysfs_root=tmp_path).reason == "none"


def test_linux_virtual_symlink_is_excluded(tmp_path):
    virtual = tmp_path / "devices" / "virtual" / "net"
    sysfs_adapter(virtual, "eth0")
    root = tmp_path / "class" / "net"
    root.mkdir(parents=True)
    (root / "eth0").symlink_to(virtual / "eth0", target_is_directory=True)
    runner = FakeRunner([json.dumps([linux_record("eth0")])])
    assert discover_lan_address(platform_name="linux", runner=runner,
                                sysfs_root=root).reason == "none"


@pytest.mark.parametrize("problem", [
    FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired("synthetic", 2),
    subprocess.CalledProcessError(1, "synthetic"), ValueError("invalid fixture"),
])
def test_command_failures_return_bounded_unsupported_reason(problem):
    result = discover_lan_address(platform_name="darwin", runner=FakeRunner([problem]))
    assert (result.address, result.reason, result.candidates) == (None, "unsupported", ())


@pytest.mark.parametrize("output", ["not json", "{}", "x" * 65537])
def test_linux_malformed_or_oversized_output_is_unsupported(tmp_path, output):
    assert discover_lan_address(platform_name="linux", runner=FakeRunner([output]),
                                sysfs_root=tmp_path).reason == "unsupported"


def test_unsupported_platform_does_not_run_a_command():
    runner = FakeRunner([])
    assert discover_lan_address(platform_name="win32", runner=runner).reason == "unsupported"
    assert runner.calls == []


def test_import_performs_no_process_or_socket_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("import must not inspect network or start processes")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    importlib.reload(lan_discovery)


def test_macos_vpn_only_never_becomes_an_automatic_candidate():
    runner = FakeRunner([hardware_ports(("Wi-Fi", "en0")),
                         ifconfig(status="inactive") + ifconfig("utun0", "10.8.0.2")])
    assert discover_lan_address(platform_name="darwin", runner=runner).reason == "none"


def test_macos_known_usb_lan_hardware_label_is_supported():
    runner = FakeRunner([hardware_ports(("USB 10/100/1000 LAN", "en5")), ifconfig("en5")])
    assert discover_lan_address(platform_name="darwin", runner=runner).address == "192.168.20.8"


def test_linux_ethernet_and_wifi_are_ambiguous(tmp_path):
    sysfs_adapter(tmp_path, "wlan0", wifi=True)
    sysfs_adapter(tmp_path, "eth0")
    runner = FakeRunner([json.dumps([linux_record(), linux_record("eth0", "10.1.0.4")])])
    result = discover_lan_address(platform_name="linux", runner=runner, sysfs_root=tmp_path)
    assert result.address is None and result.reason == "ambiguous"


def test_command_runner_returns_stdout_without_inheriting_credentials(monkeypatch):
    monkeypatch.setenv("MIRA_SYNTHETIC_SECRET", "fixture-only")
    result = lan_discovery._bounded_run((sys.executable, "-c",
        "import os; print(os.environ.get('MIRA_SYNTHETIC_SECRET', 'absent'))"))
    assert result == "absent\n"


def test_command_runner_terminates_oversized_stdout():
    with pytest.raises(ValueError, match="^lan_metadata_unavailable$"):
        lan_discovery._bounded_run((sys.executable, "-c", "print('x' * 1000000)"))


def test_command_runner_terminates_timeout(monkeypatch):
    monkeypatch.setattr(lan_discovery, "_COMMAND_TIMEOUT", 0.05)
    started = time.monotonic()
    with pytest.raises(ValueError, match="^lan_metadata_unavailable$"):
        lan_discovery._bounded_run((sys.executable, "-c", "import time; time.sleep(5)"))
    assert time.monotonic() - started < 2


def test_command_runner_rejects_nonzero_exit_without_exposing_stderr():
    with pytest.raises(ValueError, match="^lan_metadata_unavailable$"):
        lan_discovery._bounded_run((sys.executable, "-c",
            "import sys; print('synthetic private detail', file=sys.stderr); sys.exit(3)"))


def test_unusually_many_candidates_produces_bounded_unsupported_result():
    result = select_lan_address([interface(addresses=tuple(f"10.0.0.{i}" for i in range(1, 35)))])
    assert result.reason == "unsupported" and result.address is None and result.candidates == ()
