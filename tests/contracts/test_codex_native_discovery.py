"""Synthetic filesystem contracts for native Codex discovery; no process or network."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mira.adapters.generation.codex_support.types import CodexPlatformPin
from tools import codex_native_discovery as discovery


NATIVE_BYTES = b"synthetic pinned native executable, never run\n"
PIN = CodexPlatformPin("unix", "macos", "x86_64", hashlib.sha256(NATIVE_BYTES).hexdigest())
LAYOUT = discovery.NativeNpmLayout("macos", "x86_64", "codex-darwin-x64",
                                   "x86_64-apple-darwin")


def _native(path: Path, *, data: bytes = NATIVE_BYTES, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def _tree(root: Path, location: str = "nested") -> tuple[Path, Path]:
    package = root / "node_modules" / "@openai" / "codex"
    wrapper = package / "bin" / "codex.js"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("throw new Error('must never be executed');\n")
    wrapper.chmod(0o755)
    if location == "nested":
        native = package / "node_modules" / "@openai" / LAYOUT.package
    else:
        native = package.parent / LAYOUT.package
    native = native / "vendor" / LAYOUT.target_triple / "bin" / "codex"
    return wrapper, _native(native)


def test_nested_and_hoisted_wrapper_candidates_resolve_only_host_binary(tmp_path):
    for location in ("nested", "hoisted"):
        root = tmp_path / location
        wrapper, native = _tree(root, location)
        assert discovery.resolve_native_executable(wrapper, PIN) == native


def test_recognized_wrapper_symlink_resolves_without_running_javascript(tmp_path, monkeypatch):
    wrapper, native = _tree(tmp_path / "install")
    alias_dir = tmp_path / "bin"
    alias_dir.mkdir()
    alias = alias_dir / "codex"
    alias.symlink_to(wrapper)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subprocess forbidden"))
    assert discovery.resolve_native_executable(alias, PIN) == native


def test_symlink_cycles_escapes_and_unexpected_wrapper_layout_fail_closed(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    left, right = bin_dir / "left", bin_dir / "right"
    left.symlink_to(right)
    right.symlink_to(left)
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_wrapper_symlink_invalid"):
        discovery.resolve_native_executable(left, PIN)

    escape = bin_dir / "codex"
    escape.symlink_to(tmp_path / "unrelated" / "codex.js")
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_executable_missing"):
        discovery.resolve_native_executable(escape, PIN)

    wrapper, native = _tree(tmp_path / "symlinked-native")
    external = _native(tmp_path / "outside" / "codex")
    native.unlink()
    native.symlink_to(external)
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_native_permissions_blocked"):
        discovery.resolve_native_executable(wrapper, PIN)

    wrapper = tmp_path / "node_modules" / "@openai" / "codex" / "lib" / "codex.js"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("must never be read or run\n")
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_wrapper_layout_unexpected"):
        discovery.resolve_native_executable(wrapper, PIN)


def test_regular_native_is_digest_and_execute_bit_checked(tmp_path):
    native = _native(tmp_path / "bin" / "codex")
    assert discovery.resolve_native_executable(native, PIN) == native
    native.chmod(0o644)
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_native_permissions_blocked"):
        discovery.resolve_native_executable(native, PIN)


def test_hash_mismatch_and_unsafe_source_or_root_fail_closed(tmp_path):
    changed = _native(tmp_path / "changed" / "codex", data=b"changed bytes")
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_native_digest_mismatch"):
        discovery.resolve_native_executable(changed, PIN)

    unsafe_source = _native(tmp_path / "unsafe-source" / "codex", mode=0o777)
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_native_permissions_blocked"):
        discovery.resolve_native_executable(unsafe_source, PIN)

    wrapper, native = _tree(tmp_path / "writable-root")
    unsafe_ancestor = native.parents[5]
    unsafe_ancestor.chmod(0o777)
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_native_permissions_blocked"):
        discovery.resolve_native_executable(wrapper, PIN)


def test_wrong_platform_and_multiple_host_candidates_fail_closed(tmp_path):
    wrapper, _native_path = _tree(tmp_path / "wrong-platform", "hoisted")
    _native_path.unlink()
    arm = discovery.NativeNpmLayout("macos", "arm64", "codex-darwin-arm64",
                                    "aarch64-apple-darwin")
    wrong = (wrapper.parents[2] / arm.package / "vendor" / arm.target_triple
             / "bin" / "codex")
    _native(wrong)
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_native_platform_mismatch"):
        discovery.resolve_native_executable(wrapper, PIN)

    wrapper, _native_path = _tree(tmp_path / "ambiguous", "nested")
    package = wrapper.parents[2]
    hoisted = package / LAYOUT.package / "vendor" / LAYOUT.target_triple / "bin" / "codex"
    _native(hoisted)
    with pytest.raises(discovery.NativeDiscoveryError, match="codex_native_candidate_ambiguous"):
        discovery.resolve_native_executable(wrapper, PIN)


def test_path_lookup_uses_only_the_selected_official_wrapper(tmp_path):
    wrapper, native = _tree(tmp_path / "install")
    calls = []

    def lookup(command, *, path=None):
        calls.append((command, path))
        return str(wrapper)

    assert discovery.resolve_selected_executable(None, PIN, path_value="/synthetic/bin",
                                                  lookup=lookup) == native
    assert calls == [("codex", "/synthetic/bin")]


def test_prepare_lookup_does_not_read_auth_or_start_wrapper(tmp_path, monkeypatch):
    """Discovery receives only a selected path; no Codex home or credentials are inputs."""
    wrapper, native = _tree(tmp_path / "install")
    home = tmp_path / ".codex"
    home.mkdir(mode=0o700)
    secret = home / "auth.json"
    secret.write_text("synthetic credential sentinel")
    calls = []

    def no_subprocess(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Codex/JavaScript processes are forbidden in these tests")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    monkeypatch.setattr(subprocess, "Popen", no_subprocess)
    from mira.adapters.generation.codex_support import types
    from tools import prepare_runtime_admission as prepare

    pin = CodexPlatformPin(PIN.platform_family, PIN.platform_os, PIN.machine,
                           hashlib.sha256(NATIVE_BYTES).hexdigest())
    monkeypatch.setattr(prepare, "current_codex_platform_pin", lambda: pin)
    monkeypatch.setattr(types, "current_codex_platform_pin", lambda: pin)
    selected_bin = tmp_path / "selected-bin"
    selected_bin.mkdir()
    (selected_bin / "codex").symlink_to(wrapper)
    runtime_cwd = tmp_path / "runtime-cwd"
    runtime_cwd.mkdir(mode=0o700)
    args = prepare._parser().parse_args(["--prepare", "--codex-home", str(home),
                                         "--runtime-cwd", str(runtime_cwd)])
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path == secret:
            raise AssertionError("authentication files are outside discovery scope")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    result = prepare._resolve_inputs(args, {"PATH": str(selected_bin), "HOME": str(tmp_path)})
    assert result.executable == native
    assert original_read_text(secret) == "synthetic credential sentinel"
    assert calls == []


@pytest.mark.asyncio
async def test_prepare_error_distinguishes_found_native_blocked_by_permissions(
    tmp_path, monkeypatch, capsys,
):
    from mira.adapters.generation.codex_support import types
    from tools import prepare_runtime_admission as prepare

    wrapper, native = _tree(tmp_path / "install")
    native.chmod(0o777)
    home = tmp_path / ".codex"
    runtime_cwd = tmp_path / "runtime-cwd"
    home.mkdir(mode=0o700)
    runtime_cwd.mkdir(mode=0o700)
    pin = CodexPlatformPin(PIN.platform_family, PIN.platform_os, PIN.machine,
                           hashlib.sha256(NATIVE_BYTES).hexdigest())
    monkeypatch.setattr(prepare, "current_codex_platform_pin", lambda: pin)
    monkeypatch.setattr(types, "current_codex_platform_pin", lambda: pin)
    monkeypatch.setattr(sys, "argv", [
        "prepare_runtime_admission.py", "--prepare", "--codex", str(wrapper),
        "--codex-home", str(home), "--runtime-cwd", str(runtime_cwd),
        "--codex-requests", "1", "--session-turns", "1", "--input-jev-requests", "1",
        "--output-jev-requests", "1", "--input-jev-timeout-seconds", "5",
        "--output-jev-timeout-seconds", "5", "--probe-timeout-seconds", "5",
        "--confirm-policy-environment", "--authorize-codex-and-jev-content",
    ])

    assert await asyncio.to_thread(prepare.main) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "codex_native_permissions_blocked"
    assert "matching native Codex executable was found" in result["next"]
    assert str(tmp_path) not in json.dumps(result)
