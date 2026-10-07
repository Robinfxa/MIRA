#!/usr/bin/env python3
"""Offline, read-only Codex CLI setup diagnostics.

The program deliberately does not consult PATH or environment variables. It never
starts Codex, reads Codex configuration/authentication files, invokes npm, or
contacts a network service. With no explicit path arguments it is inert.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CODEX_VERSION = "0.159.2"
MAX_HASH_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class PlatformPin:
    key: str
    os_name: str
    arch: str
    digest: str
    target_triple: str
    npm_package: str | None


PINS = (
    PlatformPin(
        "macos-arm64", "macos", "arm64",
        "16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704",
        "aarch64-apple-darwin", "codex-darwin-arm64",
    ),
    PlatformPin(
        "macos-x86_64", "macos", "x86_64",
        "5acdb61ada4233af340719ddb243d5e71ea24f04afeed922644d8f1d486d4c79",
        "x86_64-apple-darwin", "codex-darwin-x64",
    ),
    PlatformPin(
        "linux-x86_64", "linux", "x86_64",
        "1748767b230ebfc3d4ab7e4e254920d0c0ad9691fd8c11f190e7d44511a4a92e",
        "x86_64-unknown-linux-gnu", None,
    ),
)

_PIN_BY_KEY = {pin.key: pin for pin in PINS}
_PIN_BY_DIGEST = {pin.digest: pin for pin in PINS}
_MACHINE_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
}

_BLOCKING_CATEGORIES = frozenset({
    "executable_missing", "executable_not_regular",
    "executable_group_or_world_writable", "executable_foreign_owner",
    "executable_setuid_or_setgid", "symlink_in_executable_path",
    "selected_executable_symlink", "executable_hash_unavailable",
    "executable_too_large_to_hash", "official_hash_not_recognized",
    "platform_pin_mismatch", "supported_platform_pin_unavailable",
    "npm_native_layout_platform_mismatch", "npm_native_candidate_missing",
    "npm_native_candidate_unverified", "javascript_wrapper_detected",
    "install_ancestor_group_or_world_writable", "install_ancestor_foreign_owner",
    "install_ancestor_not_directory", "directory_missing", "path_not_directory",
    "directory_not_private", "directory_group_or_world_writable",
    "directory_foreign_owner", "directory_ancestor_group_or_world_writable",
    "directory_ancestor_foreign_owner", "directory_ancestor_not_directory",
    "symlink_in_path", "path_not_canonical_absolute",
})

_LAUNCH_BLOCKING_CATEGORIES = frozenset({
    "executable_not_executable", "directory_not_user_searchable",
})

_INFORMATIONAL_CATEGORIES = frozenset({
    "executable_owner_writable", "install_ancestor_owner_writable",
    "directory_ancestor_owner_writable", "root_sticky_system_temp_exception",
    "official_native_verified", "executable_not_selected",
    "runtime_cwd_emptiness_not_checked", "no_explicit_paths_supplied",
    "codex_home_development_context_not_inspected", "directory_owner_write_unavailable",
})


def _platform_key(system: str, machine: str) -> str | None:
    os_name = {"darwin": "macos", "macos": "macos", "linux": "linux"}.get(
        system.lower()
    )
    arch = _MACHINE_ALIASES.get(machine.lower())
    if os_name is None or arch is None:
        return None
    key = f"{os_name}-{arch}"
    return key if key in _PIN_BY_KEY else None


def _absolute_lexical_path(value: str | os.PathLike[str]) -> Path:
    # abspath normalizes dot components without following symlinks.
    return Path(os.path.abspath(os.fspath(value)))


def _is_canonical_absolute_path(value: str | os.PathLike[str]) -> bool:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        return False
    _components, has_symlink, _missing = _component_stats(path)
    return not has_symlink


def _component_stats(path: Path) -> tuple[list[tuple[Path, os.stat_result]], bool, bool]:
    """Return existing lexical components and whether one is a symlink/missing."""
    absolute = _absolute_lexical_path(path)
    current = Path(absolute.anchor)
    found: list[tuple[Path, os.stat_result]] = []
    has_symlink = False
    missing = False
    try:
        found.append((current, current.lstat()))
    except (OSError, ValueError):
        return found, has_symlink, True
    for component in absolute.parts[1:]:
        current = current / component
        try:
            info = current.lstat()
        except (OSError, ValueError):
            missing = True
            break
        found.append((current, info))
        if stat.S_ISLNK(info.st_mode):
            has_symlink = True
    return found, has_symlink, missing


def _current_user_has_permissions(info: os.stat_result, required: int) -> bool:
    """Approximate effective Unix DAC permissions from stat metadata."""
    mode = stat.S_IMODE(info.st_mode)
    uid = os.getuid()
    gids = set(os.getgroups()) if hasattr(os, "getgroups") else set()
    gids.add(os.getegid() if hasattr(os, "getegid") else os.getgid())
    needed = required >> 6
    if info.st_uid == uid:
        permissions = mode >> 6
    elif info.st_gid in gids:
        permissions = mode >> 3
    else:
        permissions = mode
    return permissions & needed == needed


def _safe_system_temp_component(component: Path, info: os.stat_result) -> bool:
    return (
        component in (Path("/tmp"), Path("/var/tmp"))
        and info.st_uid == 0
        and bool(info.st_mode & stat.S_ISVTX)
    )


def _ancestor_categories(path: Path, *, role: str) -> list[str]:
    components, _has_symlink, _missing = _component_stats(path)
    reasons: list[str] = []
    uid = os.getuid()
    for component, info in components[:-1]:
        if stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISDIR(info.st_mode):
            reasons.append(f"{role}_ancestor_not_directory")
            continue
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid not in (0, uid):
            reasons.append(f"{role}_ancestor_foreign_owner")
        if _safe_system_temp_component(component, info):
            reasons.append("root_sticky_system_temp_exception")
            continue
        if mode & 0o022:
            reasons.append(f"{role}_ancestor_group_or_world_writable")
        if info.st_uid == uid and mode & stat.S_IWUSR:
            # The default MIRA guard permits current-user-owned writable parents.
            reasons.append(f"{role}_ancestor_owner_writable")
    return list(dict.fromkeys(reasons))


def _category_fields(
    categories: Iterable[str], *, conditional_categories: Iterable[str] = ()
) -> dict[str, list[str]]:
    unique = list(dict.fromkeys(categories))
    conditional = set(conditional_categories)
    return {
        "categories": unique,
        "blocking_categories": [
            c for c in unique if c in _BLOCKING_CATEGORIES and c not in conditional
        ],
        "launch_blocking_categories": [
            c for c in unique if c in _LAUNCH_BLOCKING_CATEGORIES
        ],
        "conditional_categories": [c for c in unique if c in conditional],
        "informational_categories": [c for c in unique if c in _INFORMATIONAL_CATEGORIES],
    }


def _known_native_layout(path: Path) -> PlatformPin | None:
    parts = _absolute_lexical_path(path).parts
    for index in range(2, len(parts) - 4):
        package = parts[index]
        pin = next((item for item in PINS if item.npm_package == package), None)
        if pin is None or parts[index - 2:index] != ("node_modules", "@openai"):
            continue
        if parts[index + 1:index + 5] == ("vendor", pin.target_triple, "bin", "codex"):
            return pin
    return None


def _known_wrapper_package_roots(path: Path) -> list[Path]:
    """Recognize only the known @openai/codex/bin/codex.js wrapper shape."""
    selected = _absolute_lexical_path(path)
    if selected.name != "codex.js":
        return []
    roots: list[Path] = []
    candidates = [selected]
    try:
        resolved = path.resolve(strict=False)
        if resolved not in candidates:
            candidates.append(resolved)
    except (OSError, RuntimeError):
        pass
    for candidate in candidates:
        parts = candidate.parts
        for index in range(1, len(parts) - 4):
            if parts[index:index + 3] != ("node_modules", "@openai", "codex"):
                continue
            if parts[index + 3:index + 5] != ("bin", "codex.js"):
                continue
            root = Path(parts[0]).joinpath(*parts[1:index + 3])
            if root not in roots:
                roots.append(root)
    return roots


def _wrapper_native_candidates(roots: Iterable[Path]) -> list[tuple[Path, PlatformPin]]:
    found: list[tuple[Path, PlatformPin]] = []
    for root in roots:
        for pin in PINS:
            if pin.npm_package is None:
                continue
            suffix = Path("vendor") / pin.target_triple / "bin" / "codex"
            options = (
                root / "node_modules" / "@openai" / pin.npm_package / suffix,
                root.parent / pin.npm_package / suffix,
            )
            for option in options:
                absolute = _absolute_lexical_path(option)
                if not any(existing == absolute for existing, _ in found):
                    found.append((absolute, pin))
    return found


def _file_digest(path: Path, size: int) -> str | None:
    if size > MAX_HASH_BYTES:
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError):
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size or size > MAX_HASH_BYTES:
            return None
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _inspect_native_file(path: Path, pin: PlatformPin | None, host_key: str | None) -> dict:
    categories: list[str] = []
    components, has_symlink, missing = _component_stats(path)
    if missing or not components or len(components) < len(_absolute_lexical_path(path).parts):
        return {
            "role": "official_npm_native_candidate" if pin else "explicit_executable",
            "native_established": False,
            "version_established": False,
            "version": None,
            **_category_fields(["executable_missing"]),
        }

    leaf = components[-1][1]
    if has_symlink:
        categories.append("symlink_in_executable_path")
    if not stat.S_ISREG(leaf.st_mode):
        categories.append("executable_not_regular")
        return {
            "role": "official_npm_native_candidate" if pin else "explicit_executable",
            "native_established": False,
            "version_established": False,
            "version": None,
            **_category_fields(categories),
        }

    uid = os.getuid()
    mode = stat.S_IMODE(leaf.st_mode)
    if leaf.st_uid not in (0, uid):
        categories.append("executable_foreign_owner")
    if mode & 0o022:
        categories.append("executable_group_or_world_writable")
    if leaf.st_mode & (stat.S_ISUID | stat.S_ISGID):
        categories.append("executable_setuid_or_setgid")
    if leaf.st_uid == uid and mode & stat.S_IWUSR:
        categories.append("executable_owner_writable")
    if not _current_user_has_permissions(leaf, stat.S_IXUSR):
        categories.append("executable_not_executable")
    categories.extend(_ancestor_categories(path, role="install"))

    digest = None if has_symlink else _file_digest(path, leaf.st_size)
    if leaf.st_size > MAX_HASH_BYTES:
        categories.append("executable_too_large_to_hash")
    elif digest is None and not has_symlink:
        categories.append("executable_hash_unavailable")

    pinned = _PIN_BY_DIGEST.get(digest or "")
    native_established = bool(pinned and host_key and pinned.key == host_key)
    if digest and pinned is None:
        categories.append("official_hash_not_recognized")
    elif pinned and not native_established:
        categories.append("platform_pin_mismatch")
    if pin and host_key and pin.key != host_key:
        categories.append("npm_native_layout_platform_mismatch")
        native_established = False
    if host_key is None:
        categories.append("supported_platform_pin_unavailable")
        native_established = False
    if native_established:
        categories.append("official_native_verified")
    return {
        "role": "official_npm_native_candidate" if pin else (
            "verified_native" if native_established else "explicit_executable"
        ),
        "native_established": native_established,
        "version_established": native_established,
        "version": CODEX_VERSION if native_established else None,
        **_category_fields(categories),
    }


def _inspect_directory(value: str, role: str) -> dict:
    path = _absolute_lexical_path(value)
    components, has_symlink, missing = _component_stats(path)
    categories: list[str] = []
    conditional_categories: list[str] = []
    if not _is_canonical_absolute_path(value):
        categories.append("path_not_canonical_absolute")
    if missing or not components or len(components) < len(path.parts):
        categories.append("directory_missing")
    else:
        leaf = components[-1][1]
        if has_symlink:
            categories.append("symlink_in_path")
        if not stat.S_ISDIR(leaf.st_mode):
            if not stat.S_ISLNK(leaf.st_mode):
                categories.append("path_not_directory")
        else:
            mode = stat.S_IMODE(leaf.st_mode)
            if leaf.st_uid != os.getuid():
                categories.append("directory_foreign_owner")
            if mode & 0o077:
                categories.append("directory_not_private")
                if role == "codex_home" and not mode & 0o022:
                    categories.append("codex_home_development_context_not_inspected")
            if mode & 0o022:
                categories.append("directory_group_or_world_writable")
            if not _current_user_has_permissions(leaf, stat.S_IXUSR):
                categories.append("directory_not_user_searchable")
            if not _current_user_has_permissions(leaf, stat.S_IWUSR):
                categories.append("directory_owner_write_unavailable")
            categories.extend(_ancestor_categories(path, role="directory"))

    result = {
        "role": role,
        "inspected": True,
        "contents_inspected": False,
        **_category_fields(categories, conditional_categories=conditional_categories),
    }
    if role == "runtime_working_directory":
        result["emptiness_checked"] = False
        fields = _category_fields(result["categories"] + ["runtime_cwd_emptiness_not_checked"])
        result.update(fields)
    return result


def diagnose(
    executable: str | None,
    codex_home: str | None = None,
    runtime_cwd: str | None = None,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> dict:
    """Inspect only explicitly supplied paths and host metadata."""
    system = system or platform.system()
    machine = machine or platform.machine()
    host_key = _platform_key(system, machine)
    result = {
        "inspected": True,
        "process_started": False,
        "network_used": False,
        "authentication_inspected": False,
        "platform": host_key or "unsupported",
    }

    if executable is None:
        native = {
            "role": "not_selected",
            "native_established": False,
            "version_established": False,
            "version": None,
            **_category_fields(["executable_not_selected"]),
        }
    else:
        executable_path = _absolute_lexical_path(executable)
        selected_path_canonical = _is_canonical_absolute_path(executable)
        selected_wrapper_roots = _known_wrapper_package_roots(executable_path)
        selected_layout = _known_native_layout(executable_path)
        selected_components, selected_symlink, selected_missing = _component_stats(executable_path)

        if selected_layout is not None:
            native = _inspect_native_file(executable_path, selected_layout, host_key)
            native["selected_role"] = "known_npm_native"
        elif selected_wrapper_roots:
            categories = ["javascript_wrapper_detected"]
            if selected_symlink:
                categories.append("selected_executable_symlink")
            if selected_missing or not selected_components:
                categories.append("executable_missing")
            candidates = _wrapper_native_candidates(selected_wrapper_roots)
            present: list[tuple[Path, PlatformPin]] = []
            for candidate, pin in candidates:
                parts, _linked, absent = _component_stats(candidate)
                if parts and not absent and len(parts) == len(candidate.parts):
                    present.append((candidate, pin))
            if host_key:
                present.sort(key=lambda item: item[1].key != host_key)
            if present:
                candidate_path, candidate_pin = present[0]
                native = _inspect_native_file(candidate_path, candidate_pin, host_key)
                native["selected_role"] = "javascript_wrapper"
                native.update(_category_fields(categories + native["categories"]))
                if not native["native_established"]:
                    native.update(_category_fields(
                        native["categories"] + ["npm_native_candidate_unverified"]
                    ))
            else:
                categories.append(
                    "supported_platform_pin_unavailable" if host_key is None
                    else "npm_native_candidate_missing"
                )
                native = {
                    "role": "javascript_wrapper",
                    "selected_role": "javascript_wrapper",
                    "native_established": False,
                    "version_established": False,
                    "version": None,
                    **_category_fields(categories),
                }
        else:
            native = _inspect_native_file(executable_path, None, host_key)
            native["selected_role"] = "explicit_path"
            if selected_symlink and "selected_executable_symlink" not in native["categories"]:
                updated_categories = native["categories"] + ["selected_executable_symlink"]
                native.update(_category_fields(updated_categories))

    native["selected_path_is_native"] = (
        native["native_established"] and native.get("selected_role") != "javascript_wrapper"
    )
    if executable is not None and not selected_path_canonical:
        native.update(_category_fields(native["categories"] + ["path_not_canonical_absolute"]))
    result["native"] = native
    result["codex_home"] = (
        _inspect_directory(codex_home, "codex_home") if codex_home is not None
        else {
            "role": "codex_home", "inspected": False, "contents_inspected": False,
            **_category_fields([]),
        }
    )
    result["runtime_cwd"] = (
        _inspect_directory(runtime_cwd, "runtime_working_directory")
        if runtime_cwd is not None
        else {
            "role": "runtime_working_directory", "inspected": False,
            "contents_inspected": False, "emptiness_checked": False,
            **_category_fields(["runtime_cwd_emptiness_not_checked"]),
        }
    )

    copy_blockers = {
        "executable_group_or_world_writable", "executable_foreign_owner",
        "install_ancestor_group_or_world_writable", "install_ancestor_foreign_owner",
    }
    recommendations: list[str] = []
    if native.get("selected_role") == "javascript_wrapper":
        recommendations.append(
            "Select the recognized native executable directly using its package-layout path. "
            "No wrapper was run."
        )
    if native["native_established"] and copy_blockers.intersection(
        native["blocking_categories"]
    ):
        recommendations.append(
            "If the install tree is blocked by your policy, consider a separately reviewed "
            "private copy of only the verified native executable. Keep Codex home and "
            "authentication data separate. No copy was made."
        )
    result["recommendations"] = recommendations
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline, read-only Codex CLI setup diagnostic. No paths are inferred."
    )
    parser.add_argument("--executable", help="explicit Codex executable or npm wrapper path")
    parser.add_argument("--codex-home", help="explicit Codex home directory to stat only")
    parser.add_argument("--runtime-cwd", help="explicit runtime working directory to stat only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not any((args.executable, args.codex_home, args.runtime_cwd)):
        print(json.dumps({
            "inspected": False,
            "process_started": False,
            "network_used": False,
            "categories": ["no_explicit_paths_supplied"],
            "blocking_categories": [],
            "launch_blocking_categories": [],
            "conditional_categories": [],
            "informational_categories": ["no_explicit_paths_supplied"],
            "next_step": "Pass --executable and, if useful, --codex-home and --runtime-cwd.",
        }, indent=2))
        return 0
    print(json.dumps(diagnose(args.executable, args.codex_home, args.runtime_cwd), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
