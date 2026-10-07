"""Resolve the pinned native Codex binary behind the known official npm shim.

This module is intentionally filesystem-only. It never reads or evaluates the
JavaScript wrapper, invokes npm, searches outside the two package-relative native
locations, or touches Codex home contents.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mira.adapters.generation.codex_support.types import CodexPlatformPin

MAX_SYMLINK_HOPS = 8
MAX_HASH_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NativeNpmLayout:
    platform_os: str
    machine: str
    package: str
    target_triple: str


# Only the two macOS npm layouts are currently admitted by this resolver.
# Official0.159.2 also defines Linux optional packages, but their npm native
# artifact identity has not been admitted here; Linux direct pinned paths remain
# supported. Do not confuse this bounded support list with vendor availability.
# Source: openai/codex rust-v0.159.2 codex-cli/bin/codex.js, lines13-20 and73-87.
_NPM_LAYOUTS = (
    NativeNpmLayout("macos", "arm64", "codex-darwin-arm64", "aarch64-apple-darwin"),
    NativeNpmLayout("macos", "x86_64", "codex-darwin-x64", "x86_64-apple-darwin"),
)


class NativeDiscoveryError(ValueError):
    """Fixed reason code only; selected paths and file contents stay private."""


def _layout_for_pin(pin: CodexPlatformPin) -> NativeNpmLayout | None:
    return next((item for item in _NPM_LAYOUTS
                 if (item.platform_os, item.machine) == (pin.platform_os, pin.machine)), None)


def _absolute(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise NativeDiscoveryError("codex_executable_path_invalid")
    return path


def _parts(path: Path) -> tuple[os.stat_result, ...]:
    """lstat every component; never traverse a symlink while inspecting it."""
    path = _absolute(path)
    current = Path(path.anchor)
    result: list[os.stat_result] = []
    try:
        result.append(current.lstat())
        for part in path.parts[1:]:
            current = current / part
            item = current.lstat()
            result.append(item)
    except (OSError, ValueError, RuntimeError):
        raise NativeDiscoveryError("codex_executable_missing") from None
    return tuple(result)


def _check_directory_chain(path: Path, *, allow_leaf: bool = False) -> None:
    """Keep the same owner, symlink, set-id, and writable-ancestor boundary as process.py."""
    metadata = _parts(path)
    current = Path(path.anchor)
    uid = os.getuid()
    for index, info in enumerate(metadata):
        leaf = index == len(metadata) - 1
        if stat.S_ISLNK(info.st_mode):
            raise NativeDiscoveryError("codex_native_permissions_blocked")
        if leaf and allow_leaf:
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, uid):
            raise NativeDiscoveryError("codex_native_permissions_blocked")
        if info.st_mode & (stat.S_ISUID | stat.S_ISGID):
            raise NativeDiscoveryError("codex_native_permissions_blocked")
        safe_system_temp = (info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
                            and current in (Path("/tmp"), Path("/var/tmp")))
        if info.st_mode & 0o022 and not safe_system_temp:
            raise NativeDiscoveryError("codex_native_permissions_blocked")
        if not leaf:
            current = current / path.parts[index + 1]


def _wrapper_root(path: Path) -> Path | None:
    """Return the one exact official npm wrapper package root, if present."""
    parts = path.parts
    roots: list[Path] = []
    for index in range(1, len(parts) - 4):
        if parts[index:index + 5] == ("node_modules", "@openai", "codex", "bin", "codex.js"):
            roots.append(Path(parts[0]).joinpath(*parts[1:index + 3]))
    if len(roots) > 1:
        raise NativeDiscoveryError("codex_wrapper_layout_unexpected")
    return roots[0] if roots else None


def _native_layout(path: Path) -> NativeNpmLayout | None:
    parts = path.parts
    found: list[NativeNpmLayout] = []
    for layout in _NPM_LAYOUTS:
        suffix = ("node_modules", "@openai", layout.package, "vendor",
                  layout.target_triple, "bin", "codex")
        for index in range(1, len(parts) - len(suffix) + 1):
            if parts[index:index + len(suffix)] == suffix:
                found.append(layout)
                break
    if len(found) > 1:
        raise NativeDiscoveryError("codex_native_layout_unexpected")
    return found[0] if found else None


def _resolve_selected(path: Path) -> tuple[Path, bool]:
    """Resolve only bounded leaf-symlink chains, validating every parent lexically."""
    selected = _absolute(path)
    _check_directory_chain(selected.parent)
    current = selected
    seen: set[Path] = set()
    followed = False
    for _ in range(MAX_SYMLINK_HOPS + 1):
        if current in seen:
            raise NativeDiscoveryError("codex_wrapper_symlink_invalid")
        seen.add(current)
        try:
            info = current.lstat()
        except (OSError, ValueError):
            raise NativeDiscoveryError("codex_executable_missing") from None
        if stat.S_ISLNK(info.st_mode):
            followed = True
            if len(seen) > MAX_SYMLINK_HOPS:
                raise NativeDiscoveryError("codex_wrapper_symlink_invalid")
            try:
                target = os.readlink(current)
            except (OSError, ValueError):
                raise NativeDiscoveryError("codex_wrapper_symlink_invalid") from None
            next_path = Path(target)
            if not next_path.is_absolute():
                next_path = current.parent / next_path
            try:
                current = Path(os.path.abspath(next_path))
            except (OSError, ValueError):
                raise NativeDiscoveryError("codex_wrapper_symlink_invalid") from None
            if ".." in current.parts:
                raise NativeDiscoveryError("codex_wrapper_symlink_invalid")
            _check_directory_chain(current.parent)
            continue
        if not stat.S_ISREG(info.st_mode):
            raise NativeDiscoveryError("codex_executable_not_regular")
        if followed and _wrapper_root(current) is None:
            raise NativeDiscoveryError("codex_wrapper_symlink_unrecognized")
        return current, followed
    raise NativeDiscoveryError("codex_wrapper_symlink_invalid")


def _candidate_paths(root: Path, layout: NativeNpmLayout) -> tuple[Path, Path]:
    suffix = Path("vendor") / layout.target_triple / "bin" / "codex"
    return (
        root / "node_modules" / "@openai" / layout.package / suffix,
        root.parent / layout.package / suffix,
    )


def _existing_candidate(path: Path) -> bool:
    """Check existence without following any path symlink; missing is not unsafe."""
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            raise NativeDiscoveryError("codex_native_permissions_blocked") from None
        if stat.S_ISLNK(info.st_mode):
            raise NativeDiscoveryError("codex_native_permissions_blocked")
        if index < len(path.parts[1:]) - 1 and not stat.S_ISDIR(info.st_mode):
            raise NativeDiscoveryError("codex_native_layout_unexpected")
    return True


def _verify_native(path: Path, pin: CodexPlatformPin,
                   *, digest_file: Callable[[Path], str] | None = None) -> Path:
    """Enforce canonical path, host layout, file permissions and exact pinned bytes."""
    path = _absolute(path)
    parts = _parts(path)
    current = Path(path.anchor)
    uid = os.getuid()
    for index, info in enumerate(parts):
        leaf = index == len(parts) - 1
        if stat.S_ISLNK(info.st_mode):
            raise NativeDiscoveryError("codex_native_permissions_blocked")
        if leaf:
            if not stat.S_ISREG(info.st_mode):
                raise NativeDiscoveryError("codex_executable_not_regular")
            if (info.st_uid not in (0, uid) or info.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID)
                    or not info.st_mode & 0o111 or not os.access(path, os.X_OK)):
                raise NativeDiscoveryError("codex_native_permissions_blocked")
        else:
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, uid):
                raise NativeDiscoveryError("codex_native_permissions_blocked")
            if info.st_mode & (stat.S_ISUID | stat.S_ISGID):
                raise NativeDiscoveryError("codex_native_permissions_blocked")
            safe_system_temp = (info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
                                and current in (Path("/tmp"), Path("/var/tmp")))
            if info.st_mode & 0o022 and not safe_system_temp:
                raise NativeDiscoveryError("codex_native_permissions_blocked")
            current = current / path.parts[index + 1]
    try:
        size = parts[-1].st_size
        if size < 0 or size > MAX_HASH_BYTES:
            raise NativeDiscoveryError("codex_native_digest_unavailable")
        if digest_file is None:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            try:
                opened = os.fstat(fd)
                if (not stat.S_ISREG(opened.st_mode) or opened.st_size != size
                        or opened.st_mode & (stat.S_ISUID | stat.S_ISGID)):
                    raise NativeDiscoveryError("codex_native_permissions_blocked")
                digest = hashlib.sha256()
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                actual = digest.hexdigest()
            finally:
                os.close(fd)
        else:
            actual = digest_file(path)
    except NativeDiscoveryError:
        raise
    except (OSError, ValueError, TypeError):
        raise NativeDiscoveryError("codex_native_digest_unavailable") from None
    if actual != pin.executable_sha256:
        raise NativeDiscoveryError("codex_native_digest_mismatch")
    return path


def resolve_native_executable(selected: Path, pin: CodexPlatformPin) -> Path:
    """Resolve a selected native path or known official npm wrapper to its pinned host binary."""
    if not isinstance(selected, Path) or type(pin) is not CodexPlatformPin:
        raise NativeDiscoveryError("codex_executable_path_invalid")
    resolved, followed = _resolve_selected(selected)
    wrapper_root = _wrapper_root(resolved)
    native_layout = _native_layout(resolved)

    if wrapper_root is not None:
        layout = _layout_for_pin(pin)
        if layout is None:
            # A recognized wrapper exists, but this resolver has not admitted an
            # npm-native layout for this host. Never guess another architecture.
            raise NativeDiscoveryError("codex_native_platform_layout_unavailable")
        candidates = _candidate_paths(wrapper_root, layout)
        present = [candidate for candidate in dict.fromkeys(candidates)
                   if _existing_candidate(candidate)]
        if len(present) > 1:
            raise NativeDiscoveryError("codex_native_candidate_ambiguous")
        if not present:
            other_present = False
            for other in _NPM_LAYOUTS:
                if other == layout:
                    continue
                if any(_existing_candidate(candidate)
                       for candidate in _candidate_paths(wrapper_root, other)):
                    other_present = True
            if other_present:
                raise NativeDiscoveryError("codex_native_platform_mismatch")
            raise NativeDiscoveryError("codex_native_candidate_missing")
        native = present[0]
        candidate_layout = _native_layout(native)
        if candidate_layout != layout:
            raise NativeDiscoveryError("codex_native_platform_mismatch")
        return _verify_native(native, pin)

    if followed:
        raise NativeDiscoveryError("codex_wrapper_symlink_unrecognized")
    if resolved.name == "codex.js":
        raise NativeDiscoveryError("codex_wrapper_layout_unexpected")
    if native_layout is not None:
        requested = _layout_for_pin(pin)
        if native_layout != requested:
            raise NativeDiscoveryError("codex_native_platform_mismatch")
    return _verify_native(resolved, pin)


def resolve_selected_executable(selected: Path | None, pin: CodexPlatformPin,
                               *, path_value: str | None = None,
                               lookup: Callable[..., str | None] | None = None) -> Path:
    """Resolve explicit --codex or the normal `codex` PATH lookup."""
    if selected is None:
        if lookup is None:
            import shutil
            lookup = shutil.which
        found = lookup("codex", path=path_value)
        if not found:
            raise NativeDiscoveryError("codex_executable_not_found")
        selected = Path(found)
        if not selected.is_absolute():
            selected = Path(os.path.abspath(selected))
    return resolve_native_executable(selected, pin)
