"""Platform-bound pins for the approved Codex CLI release."""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from pathlib import Path

import pytest

from mira.adapters.generation.codex_support import process, types
from mira.adapters.generation.codex_support.preflight import MetadataOnlyTransport
from tools import prepare_runtime_admission as prepare


LINUX_X86_64_SHA256 = "1748767b230ebfc3d4ab7e4e254920d0c0ad9691fd8c11f190e7d44511a4a92e"
MACOS_ARM64_SHA256 = "16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704"
MACOS_X86_64_SHA256 = "5acdb61ada4233af340719ddb243d5e71ea24f04afeed922644d8f1d486d4c79"


def _runtime(*, executable_sha256=None):
    kwargs = {}
    if executable_sha256 is not None:
        kwargs["executable_sha256"] = executable_sha256
    return types.CodexRuntime(
        Path("/synthetic/codex"), Path("/synthetic/home"), Path("/synthetic/run"),
        policy_environment_confirmed=True, **kwargs,
    )


@pytest.mark.parametrize(
    ("machine", "expected_digest"),
    (("arm64", MACOS_ARM64_SHA256), ("aarch64", MACOS_ARM64_SHA256),
     ("x86_64", MACOS_X86_64_SHA256), ("AMD64", MACOS_X86_64_SHA256)),
)
def test_macos_codex_runtime_selects_only_the_verified_host_architecture(
    monkeypatch, machine, expected_digest,
):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: machine)

    runtime = _runtime()

    assert runtime.executable_sha256 == expected_digest
    assert runtime.platform_family == "unix"
    assert runtime.platform_os == "macos"


def test_linux_alias_remains_the_original_verified_x86_64_pin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")

    runtime = _runtime()

    assert types.PINNED_EXECUTABLE_SHA256 == LINUX_X86_64_SHA256
    assert runtime.executable_sha256 == LINUX_X86_64_SHA256
    assert runtime.platform_family == "unix"
    assert runtime.platform_os == "linux"


@pytest.mark.parametrize("wrong_digest", (LINUX_X86_64_SHA256, "f" * 64))
def test_macos_runtime_rejects_explicit_cross_platform_or_arbitrary_digest(
    monkeypatch, wrong_digest,
):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")

    with pytest.raises(ValueError, match="codex_executable_pin_invalid"):
        _runtime(executable_sha256=wrong_digest)


@pytest.mark.parametrize(("system", "machine"),
                         (("win32", "AMD64"), ("darwin", "ppc64"),
                          ("linux", "aarch64"), ("linux-custom", "x86_64")))
def test_unpinned_os_or_architecture_fails_closed_at_runtime_construction(
    monkeypatch, system, machine,
):
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(platform, "machine", lambda: machine)

    with pytest.raises(ValueError, match="codex_platform_pin_unavailable"):
        _runtime()


def test_prepare_helper_uses_actual_macos_architecture_not_environment_override(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    executable = tmp_path / "native-codex"
    executable.write_bytes(b"synthetic native candidate")
    home = tmp_path / "home"
    cwd = tmp_path / "runtime"
    home.mkdir(mode=0o700)
    cwd.mkdir(mode=0o700)
    # This existing contract isolates host-pin selection; native digest and path
    # security checks are exercised by the dedicated discovery contracts.
    monkeypatch.setattr(prepare, "resolve_selected_executable",
                        lambda selected, *_args, **_kwargs: selected.resolve())
    args = argparse.Namespace(codex=executable, codex_home=home, runtime_cwd=cwd)

    runtime = prepare._resolve_inputs(args, {
        "PATH": "/synthetic/bin", "HOME": str(tmp_path),
        "MIRA_CODEX_PLATFORM": "linux", "MIRA_CODEX_ARCH": "x86_64",
        "MIRA_CODEX_EXECUTABLE_SHA256": LINUX_X86_64_SHA256,
    })

    assert runtime.executable_sha256 == MACOS_ARM64_SHA256
    assert runtime.platform_os == "macos"
    assert runtime.executable == executable


class _MetadataTransport:
    def __init__(self, *, platform_os="macos", platform_family="unix",
                 omit_platform=False, version="0.159.2"):
        self.platform_os = platform_os
        self.platform_family = platform_family
        self.omit_platform = omit_platform
        self.version = version
        self.sent = []
        self.responses = asyncio.Queue()
        self.closed = False

    async def send(self, message):
        self.sent.append(message)
        if "id" not in message:
            return
        if message["method"] == "initialize":
            result = {"userAgent": f"codex/{self.version} ({self.platform_os})",
                      "codexHome": "/synthetic/home"}
            if not self.omit_platform:
                result.update({"platformFamily": self.platform_family,
                               "platformOs": self.platform_os})
        else:
            result = {"config": {
                "features": {**dict.fromkeys(types.DISABLED_FEATURES, False),
                             "respect_system_proxy": True},
                "mcp_servers": {}, "web_search": "disabled", "model": "gpt-6-luna",
                "model_provider": "openai", "forced_login_method": "chatgpt",
                "approval_policy": "never", "sandbox_mode": "read-only",
            }, "origins": {}, "layers": None}
        await self.responses.put(json.dumps({"id": message["id"], "result": result}).encode()
                                 + b"\n")

    async def receive(self):
        return await self.responses.get()

    async def close(self):
        self.closed = True


@pytest.mark.parametrize(("machine", "expected_digest"),
                         (("arm64", MACOS_ARM64_SHA256),
                          ("x86_64", MACOS_X86_64_SHA256)))
@pytest.mark.asyncio
async def test_preflight_accepts_only_the_exact_host_reported_macos_platform(
    monkeypatch, machine, expected_digest,
):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: machine)
    runtime = _runtime()
    transport = _MetadataTransport()

    observed = await MetadataOnlyTransport(transport, runtime).observe(2)

    assert observed.executable_sha256 == expected_digest
    assert observed.codex_version == "0.159.2"
    assert transport.closed
    assert [message.get("method") for message in transport.sent] == [
        "initialize", "initialized", "config/read",
    ]


@pytest.mark.parametrize(
    "transport",
    (_MetadataTransport(platform_os="linux"),
     _MetadataTransport(platform_os="windows", platform_family="windows"),
     _MetadataTransport(omit_platform=True),
     _MetadataTransport(version="0.159.3")),
)
@pytest.mark.asyncio
async def test_macos_preflight_rejects_other_missing_or_wrong_platform_facts(
    monkeypatch, transport,
):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")

    with pytest.raises(types.CodexGenerationError, match="codex_preflight_profile_drift"):
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert transport.closed


def test_process_validation_rejects_runtime_reused_under_different_host_pin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    runtime = _runtime()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")

    with pytest.raises(types.CodexGenerationError, match="codex_platform_pin_drift"):
        process._validate_runtime(runtime, require_config_pin=False)
