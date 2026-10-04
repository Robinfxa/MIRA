#!/usr/bin/env python3
"""Build and safely recombine a MIRA split-source delivery using only stdlib."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import unicodedata
import zipfile
from typing import Any

FORMAT = "mira-split-source-v1"
ARCHIVE_ROOT = "MIRA"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024  # strict less-than
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
ALLOWED_MODES = {0o644, 0o755}
DELIVERY_PREFIX = "MIRA-20261004-1659-"
ARCHIVE_FILES = {
    "code": DELIVERY_PREFIX + "code-source-incomplete-without-assets.zip",
    "assets-01": DELIVERY_PREFIX + "assets-01-of-02.zip",
    "assets-02": DELIVERY_PREFIX + "assets-02-of-02.zip",
}
SIDECAR = DELIVERY_PREFIX + "split-source-manifest.json"
CHECKSUMS = DELIVERY_PREFIX + "SHA256SUMS.txt"
START_HERE = DELIVERY_PREFIX + "START-HERE.txt"
ASSET_MANIFEST_REL = "apps/web/public/scene/mira_manifest.json"
RESTORE_HELPER = DELIVERY_PREFIX + "restore.py"
ASSET_CHUNK_SIZE = 6
ASSET_COUNT = 12
HEX256 = re.compile(r"^[0-9a-f]{64}$")


class DeliveryError(ValueError):
    """Input or archive did not satisfy the split-delivery contract."""


def fail(message: str) -> None:
    raise DeliveryError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _path_parts(name: str) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        fail(f"unsafe relative path: {name!r}")
    p = PurePosixPath(name)
    parts = p.parts
    if p.is_absolute() or not parts or str(p) != name:
        fail(f"absolute or non-canonical path: {name!r}")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        fail(f"unsafe path component: {name!r}")
    return parts


def _collision_key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _check_unique_paths(names: list[str], where: str) -> None:
    exact: set[str] = set()
    folded: dict[str, str] = {}
    for name in names:
        _path_parts(name)
        if name in exact:
            fail(f"duplicate path in {where}: {name}")
        exact.add(name)
        key = _collision_key(name)
        previous = folded.get(key)
        if previous is not None and previous != name:
            fail(f"case/Unicode path collision in {where}: {previous!r} and {name!r}")
        folded[key] = name


def _validate_file_row(name: str, row: Any) -> dict[str, Any]:
    _path_parts(name)
    if not isinstance(row, dict):
        fail(f"invalid file record: {name}")
    size = row.get("bytes")
    digest = row.get("sha256")
    mode = row.get("mode")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_MEMBER_BYTES:
        fail(f"invalid or oversized file length: {name}")
    if not isinstance(digest, str) or not HEX256.fullmatch(digest):
        fail(f"invalid SHA256 for: {name}")
    if mode not in ("0644", "0755"):
        fail(f"disallowed mode for {name}: {mode!r}")
    return {"bytes": size, "sha256": digest, "mode": mode}


def _read_json(path: Path, label: str) -> tuple[bytes, Any]:
    if path.is_symlink() or not path.is_file():
        fail(f"{label} is not a regular file: {path}")
    raw = path.read_bytes()
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        fail(f"invalid {label} JSON: {exc}")
    return raw, obj


def _projection_files(manifest: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        fail("projection manifest must contain a files object")
    raw_files = manifest["files"]
    names = list(raw_files)
    _check_unique_paths(names, "projection manifest")
    files = {name: _validate_file_row(name, raw_files[name]) for name in names}
    total = sum(row["bytes"] for row in files.values())
    if total > MAX_TOTAL_BYTES:
        fail(f"projection exceeds the {MAX_TOTAL_BYTES}-byte uncompressed safety cap")
    return files


def _validate_release(summary: Any) -> None:
    if not isinstance(summary, dict):
        fail("release summary must be a JSON object")
    if summary.get("status") != "passed":
        fail("release summary is not passed")
    for key in ("not_run", "changed_paths"):
        value = summary.get(key)
        if value is not None and value != []:
            fail(f"release summary has {key}: {value!r}")
    changed = summary.get("changed_during_run")
    if changed not in (None, False, []):
        fail(f"release summary reports source drift: {changed!r}")
    before = summary.get("source_before_digest")
    after = summary.get("source_after_digest")
    if before is not None and after is not None and before != after:
        fail("release source-before and source-after digests differ")
    lanes = summary.get("lanes")
    selected = summary.get("selected_lanes")
    if not isinstance(lanes, list) or not lanes:
        fail("release summary has no lane results")
    lane_rows: dict[str, Any] = {}
    for lane in lanes:
        if not isinstance(lane, dict) or not isinstance(lane.get("name"), str):
            fail("release summary contains a malformed lane")
        name = lane["name"]
        if name in lane_rows:
            fail(f"duplicate release lane: {name}")
        lane_rows[name] = lane
        if lane.get("status") != "passed" or lane.get("exit_code") not in (None, 0):
            fail(f"release lane did not pass: {name}")
    if selected is not None:
        if not isinstance(selected, list) or not selected:
            fail("selected_lanes must be a non-empty list")
        if set(selected) != set(lane_rows):
            fail("release lane results do not exactly cover selected_lanes")


def _stage_inventory(root: Path) -> tuple[set[str], set[str]]:
    if root.is_symlink() or not root.is_dir():
        fail(f"source root is not a real directory: {root}")
    files: set[str] = set()
    dirs: set[str] = set()
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        safe_dirs: list[str] = []
        for dirname in dirnames:
            child = current_path / dirname
            rel = child.relative_to(root).as_posix()
            _path_parts(rel)
            try:
                mode = child.lstat().st_mode
            except OSError as exc:
                fail(f"cannot inspect source directory {rel}: {exc}")
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                fail(f"source tree contains a symlink or non-directory: {rel}")
            dirs.add(rel)
            safe_dirs.append(dirname)
        dirnames[:] = safe_dirs
        for filename in filenames:
            child = current_path / filename
            rel = child.relative_to(root).as_posix()
            _path_parts(rel)
            try:
                mode = child.lstat().st_mode
            except OSError as exc:
                fail(f"cannot inspect source file {rel}: {exc}")
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                fail(f"source tree contains a symlink or non-regular file: {rel}")
            files.add(rel)
    return files, dirs


def _expected_dirs(files: dict[str, dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for name in files:
        parts = _path_parts(name)
        for i in range(1, len(parts)):
            result.add("/".join(parts[:i]))
    _check_unique_paths(sorted(result), "manifest directories")
    return result


def _read_stage_files(root: Path, files: dict[str, dict[str, Any]]) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        fail(f"source root is not a real directory: {root}")
    data: dict[str, bytes] = {}
    for name, row in files.items():
        parts = _path_parts(name)
        path = root
        try:
            for part in parts[:-1]:
                path = path / part
                parent_stat = path.lstat()
                if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
                    fail(f"projected source parent is a symlink or non-directory: {name}")
            path = path / parts[-1]
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                fail(f"source path changed type: {name}")
            if stat.S_IMODE(before.st_mode) != int(row["mode"], 8):
                fail(f"source mode differs from projection manifest: {name}")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            try:
                opened = os.fstat(fd)
                if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    fail(f"source path changed while opening: {name}")
                chunks = []
                count = 0
                while True:
                    block = os.read(fd, 1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > row["bytes"]:
                        fail(f"source grew while being read: {name}")
                    chunks.append(block)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            current = path.lstat()
        except OSError as exc:
            fail(f"cannot safely read source file {name}: {exc}")
        value = b"".join(chunks)
        if stat.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            fail(f"source path changed while reading: {name}")
        if (after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns
                or count != row["bytes"] or sha256_bytes(value) != row["sha256"]):
            fail(f"source size/hash/mode does not match projection manifest: {name}")
        data[name] = value
    return data


def _assets_from_manifest(asset_manifest: Any) -> tuple[list[str], dict[str, str]]:
    if not isinstance(asset_manifest, dict):
        fail("asset manifest must be a JSON object")
    refs: list[tuple[str, str]] = []
    for group in ("base", "expressionVariants", "actionVariants"):
        value = asset_manifest.get(group)
        if group == "base":
            records = [value]
        elif isinstance(value, dict):
            records = []
            def collect(node: Any) -> None:
                if isinstance(node, dict):
                    if "src" in node:
                        records.append(node)
                    else:
                        for child in node.values():
                            collect(child)
            collect(value)
        else:
            fail(f"asset manifest lacks {group}")
        for record in records:
            if not isinstance(record, dict):
                fail(f"malformed asset record in {group}")
            src = record.get("src")
            digest = record.get("sha256")
            if not isinstance(src, str) or not isinstance(digest, str) or not HEX256.fullmatch(digest):
                fail(f"asset reference lacks a safe src and SHA256 in {group}")
            _path_parts(src)
            if len(PurePosixPath(src).parts) != 1 or not src.lower().endswith(".png"):
                fail(f"asset src must be a PNG basename: {src!r}")
            refs.append((src, digest))
    names = [f"apps/web/public/scene/{src}" for src, _ in refs]
    _check_unique_paths(names, "asset manifest")
    if len(names) != ASSET_COUNT:
        fail(f"asset manifest must declare exactly {ASSET_COUNT} PNGs, found {len(names)}")
    digest_by_path = {f"apps/web/public/scene/{src}": digest for src, digest in refs}
    return sorted(names), digest_by_path


def _zipinfo(member_name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(member_name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.file_size = 0
    return info


def _write_archive(path: Path, paths: list[str], data: dict[str, bytes], files: dict[str, dict[str, Any]]) -> None:
    with zipfile.ZipFile(path, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        for rel in sorted(paths):
            row = files[rel]
            archive.writestr(_zipinfo(f"{ARCHIVE_ROOT}/{rel}", int(row["mode"], 8)), data[rel], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _zip_member_mode(info: zipfile.ZipInfo, archive_name: str) -> int:
    if info.is_dir():
        fail(f"directory entry is not allowed in {archive_name}: {info.filename}")
    if info.flag_bits & 0x1:
        fail(f"encrypted ZIP member is not allowed: {info.filename}")
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        fail(f"unsupported ZIP compression for {info.filename}")
    kind = stat.S_IFMT(info.external_attr >> 16)
    mode = stat.S_IMODE(info.external_attr >> 16)
    if kind != stat.S_IFREG:
        fail(f"non-regular ZIP member is not allowed: {info.filename}")
    if mode not in ALLOWED_MODES:
        fail(f"disallowed ZIP mode for {info.filename}: {mode:04o}")
    return mode


def _validate_archive_name(name: str) -> str:
    _path_parts(name)
    prefix = f"{ARCHIVE_ROOT}/"
    if not name.startswith(prefix) or name == prefix:
        fail(f"ZIP member must use the shared {prefix} path: {name!r}")
    rel = name[len(prefix):]
    _path_parts(rel)
    return rel


def _stream_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, expected_bytes: int) -> bytes:
    if info.file_size != expected_bytes:
        fail(f"ZIP member length differs from manifest: {info.filename}")
    if info.file_size > MAX_MEMBER_BYTES:
        fail(f"oversized ZIP member: {info.filename}")
    h = hashlib.sha256()
    out = bytearray()
    seen = 0
    try:
        with archive.open(info, "r") as member:
            while True:
                block = member.read(1024 * 1024)
                if not block:
                    break
                seen += len(block)
                if seen > expected_bytes or seen > MAX_MEMBER_BYTES:
                    fail(f"ZIP member expanded beyond its declared bound: {info.filename}")
                h.update(block)
                out.extend(block)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        fail(f"cannot read ZIP member {info.filename}: {exc}")
    if seen != expected_bytes:
        fail(f"truncated ZIP member: {info.filename}")
    return bytes(out)


def _verify_output_archive(path: Path, paths: list[str], data: dict[str, bytes], files: dict[str, dict[str, Any]]) -> None:
    if path.stat().st_size >= MAX_ARCHIVE_BYTES:
        fail(f"archive exceeds strict 20 MiB limit: {path.name}")
    expected = {f"{ARCHIVE_ROOT}/{rel}": rel for rel in paths}
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        _check_unique_paths(names, path.name)
        if set(names) != set(expected) or len(names) != len(expected):
            fail(f"archive members differ from expected source paths: {path.name}")
        for info in infos:
            rel = _validate_archive_name(info.filename)
            mode = _zip_member_mode(info, path.name)
            if rel not in files or mode != int(files[rel]["mode"], 8):
                fail(f"archive member mode/path mismatch: {info.filename}")
            got = _stream_member(archive, info, files[rel]["bytes"])
            if got != data[rel] or sha256_bytes(got) != files[rel]["sha256"]:
                fail(f"archive roundtrip byte/hash mismatch: {info.filename}")


def _atomic_json(path: Path, obj: Any) -> None:
    temp = path.with_name(path.name + ".tmp")
    payload = (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with temp.open("xb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def build_delivery(source_root: Path, projection_manifest_path: Path, release_summary_path: Path,
                   asset_manifest_path: Path, output_dir: Path,
                   delivery_notes_path: Path | None = None) -> dict[str, Any]:
    projection_raw, projection = _read_json(projection_manifest_path, "projection manifest")
    release_raw, release = _read_json(release_summary_path, "release summary")
    asset_raw, asset_manifest = _read_json(asset_manifest_path, "asset manifest")
    notes_raw = None
    if delivery_notes_path is not None:
        if delivery_notes_path.is_symlink() or not delivery_notes_path.is_file():
            fail(f"delivery notes are not a regular file: {delivery_notes_path}")
        notes_raw = delivery_notes_path.read_bytes()
        if len(notes_raw) > 100_000:
            fail("delivery notes exceed the 100,000-byte limit")
        try:
            notes_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"delivery notes must be UTF-8 text: {exc}")
    if projection.get("format") != "mira-public-projection-v1":
        fail("projection manifest has an unsupported format")
    capture_digest = projection.get("capture_manifest_sha256")
    if not isinstance(capture_digest, str) or not HEX256.fullmatch(capture_digest):
        fail("projection manifest is not bound to a valid capture SHA256")
    projection_files = _projection_files(projection)
    if len(projection_files) != 929 or projection.get("source_file_count") != 929:
        fail("pairing capture must project exactly 929 files")
    capture_path = source_root / "capture-manifest.json"
    capture_raw, capture_manifest = _read_json(capture_path, "source capture manifest")
    if sha256_bytes(capture_raw) != capture_digest:
        fail("source capture manifest does not match the projection binding")
    capture_files = _projection_files(capture_manifest)
    if capture_files != projection_files:
        fail("projection file table differs from the frozen source capture")
    files = projection_files
    _validate_release(release)
    assets, asset_sha = _assets_from_manifest(asset_manifest)
    missing_assets = sorted(set(assets) - set(files))
    if missing_assets:
        fail(f"asset manifest paths are missing from public projection: {missing_assets}")
    for path, digest in asset_sha.items():
        if files[path]["sha256"] != digest:
            fail(f"PNG hash differs from apps/web/public/scene/mira_manifest.json: {path}")
    if output_dir.exists() or output_dir.is_symlink():
        fail(f"output directory must not already exist: {output_dir}")
    if not output_dir.parent.is_dir():
        fail(f"output parent directory must already exist: {output_dir.parent}")
    data = _read_stage_files(source_root, files)
    code_paths = sorted(set(files) - set(assets))
    asset_paths = sorted(assets)
    groups = {
        "code": code_paths,
        "assets-01": asset_paths[:ASSET_CHUNK_SIZE],
        "assets-02": asset_paths[ASSET_CHUNK_SIZE:],
    }
    if len(groups["assets-01"]) != ASSET_CHUNK_SIZE or len(groups["assets-02"]) != ASSET_CHUNK_SIZE:
        fail("asset split is not exactly two groups of six")
    output_dir.mkdir(mode=0o700)
    try:
        archive_rows: dict[str, dict[str, Any]] = {}
        for key, members in groups.items():
            path = output_dir / ARCHIVE_FILES[key]
            _write_archive(path, members, data, files)
            _verify_output_archive(path, members, data, files)
            archive_rows[key] = {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "members": [f"{ARCHIVE_ROOT}/{rel}" for rel in members],
            }
        # Re-read input evidence and stage after packaging so changed inputs fail closed.
        if sha256_file(projection_manifest_path) != sha256_bytes(projection_raw):
            fail("projection manifest changed during packaging")
        if sha256_file(release_summary_path) != sha256_bytes(release_raw):
            fail("release summary changed during packaging")
        if sha256_file(asset_manifest_path) != sha256_bytes(asset_raw):
            fail("asset manifest changed during packaging")
        if delivery_notes_path is not None and sha256_file(delivery_notes_path) != sha256_bytes(notes_raw):
            fail("delivery notes changed during packaging")
        _read_stage_files(source_root, files)
        manifest = {
            "format": FORMAT,
            "archive_root": ARCHIVE_ROOT,
            "delivery_status": "complete only when all three archives are present",
            "code_only_notice": "The code archive is intentionally incomplete without both asset archives.",
            "source_projection_sha256": sha256_bytes(projection_raw),
            "source_capture_manifest_sha256": capture_digest,
            "release_summary_sha256": sha256_bytes(release_raw),
            "asset_manifest_sha256": sha256_bytes(asset_raw),
            "asset_paths": assets,
            "archive_files": ARCHIVE_FILES,
            "archives": archive_rows,
            "files": {
                name: {**files[name], "archive": key}
                for key, members in groups.items()
                for name in members
            },
            "file_count": len(files),
        }
        if notes_raw is not None:
            (output_dir / START_HERE).write_bytes(notes_raw)
            manifest["delivery_notes"] = {
                "filename": START_HERE,
                "bytes": len(notes_raw),
                "sha256": sha256_bytes(notes_raw),
            }
        _atomic_json(output_dir / SIDECAR, manifest)
        lines = [f"{archive_rows[key]['sha256']}  {archive_rows[key]['filename']}" for key in ARCHIVE_FILES]
        lines.append(f"{sha256_file(output_dir / SIDECAR)}  {SIDECAR}")
        if notes_raw is not None:
            lines.append(f"{sha256_file(output_dir / START_HERE)}  {START_HERE}")
        (output_dir / CHECKSUMS).write_text("\n".join(lines) + "\n", encoding="ascii")
        return manifest
    except Exception:
        raise


def _delivery_manifest(path: Path) -> dict[str, Any]:
    raw, manifest = _read_json(path, "split delivery manifest")
    del raw
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("archive_root") != ARCHIVE_ROOT:
        fail("unsupported split delivery manifest")
    capture_digest = manifest.get("source_capture_manifest_sha256")
    if not isinstance(capture_digest, str) or not HEX256.fullmatch(capture_digest):
        fail("manifest is not bound to a valid source capture SHA256")
    if manifest.get("delivery_status") != "complete only when all three archives are present":
        fail("manifest does not identify a complete three-archive delivery")
    if manifest.get("archive_files") != ARCHIVE_FILES:
        fail("archive filename contract differs")
    files = manifest.get("files")
    archives = manifest.get("archives")
    if not isinstance(files, dict) or not isinstance(archives, dict) or set(archives) != set(ARCHIVE_FILES):
        fail("manifest must describe every source file and all three archives")
    names = list(files)
    _check_unique_paths(names, "split delivery manifest")
    if (not isinstance(manifest.get("file_count"), int) or isinstance(manifest.get("file_count"), bool)
            or manifest.get("file_count") != len(files) or len(files) != 929):
        fail("manifest must describe exactly 929 source files")
    for digest_key in ("source_projection_sha256", "release_summary_sha256", "asset_manifest_sha256"):
        digest_value = manifest.get(digest_key)
        if not isinstance(digest_value, str) or not HEX256.fullmatch(digest_value):
            fail(f"manifest lacks a valid {digest_key}")
    total = 0
    normalized: dict[str, dict[str, Any]] = {}
    for name in names:
        row = files[name]
        if not isinstance(row, dict):
            fail(f"invalid manifest record: {name}")
        base = _validate_file_row(name, row)
        archive = row.get("archive")
        if archive not in ARCHIVE_FILES:
            fail(f"invalid archive assignment for {name}")
        normalized[name] = {**base, "archive": archive}
        total += base["bytes"]
    if total > MAX_TOTAL_BYTES:
        fail("manifest exceeds total uncompressed safety cap")
    asset_paths = manifest.get("asset_paths")
    if not isinstance(asset_paths, list) or len(asset_paths) != ASSET_COUNT:
        fail(f"manifest must list exactly {ASSET_COUNT} asset paths")
    _check_unique_paths(asset_paths, "asset paths")
    if any(p not in normalized or normalized[p]["archive"] not in ("assets-01", "assets-02") or not p.lower().endswith(".png") for p in asset_paths):
        fail("manifest asset_paths do not match PNG file assignments")
    if len([p for p in asset_paths if normalized[p]["archive"] == "assets-01"]) != ASSET_CHUNK_SIZE:
        fail("first asset archive does not contain six PNGs")
    if len([p for p in asset_paths if normalized[p]["archive"] == "assets-02"]) != ASSET_CHUNK_SIZE:
        fail("second asset archive does not contain six PNGs")
    if any(normalized[p]["archive"] != "code" for p in normalized if p not in set(asset_paths)):
        fail("non-image file assigned to asset archive")
    for key, filename in ARCHIVE_FILES.items():
        row = archives.get(key)
        if not isinstance(row, dict) or row.get("filename") != filename:
            fail(f"archive record missing or wrong filename for {key}")
        size, digest = row.get("bytes"), row.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size >= MAX_ARCHIVE_BYTES:
            fail(f"archive violates strict 20 MiB size limit: {filename}")
        if not isinstance(digest, str) or not HEX256.fullmatch(digest):
            fail(f"invalid archive SHA256 for {filename}")
        members = row.get("members")
        expected = sorted(f"{ARCHIVE_ROOT}/{name}" for name, file_row in normalized.items() if file_row["archive"] == key)
        if members != expected:
            fail(f"archive member list differs from manifest for {key}")
    notes = manifest.get("delivery_notes")
    if notes is None:
        fail("complete seven-file delivery requires START-HERE notes")
    if notes is not None:
        if (not isinstance(notes, dict) or notes.get("filename") != START_HERE
                or not isinstance(notes.get("bytes"), int) or isinstance(notes.get("bytes"), bool)
                or notes["bytes"] < 0 or notes["bytes"] > 100_000
                or not isinstance(notes.get("sha256"), str) or not HEX256.fullmatch(notes["sha256"])):
            fail("invalid delivery notes record")
    return {"files": normalized, "archives": archives, "asset_paths": asset_paths, "notes": notes}


def _verify_complete_delivery_files(delivery_dir: Path) -> None:
    # Inspect only the seven required paths. Finder metadata and unrelated sibling
    # files/directories are never listed, opened, or traversed.
    expected = set(ARCHIVE_FILES.values()) | {SIDECAR, CHECKSUMS, START_HERE, RESTORE_HELPER}
    for filename in expected:
        path = delivery_dir / filename
        try:
            mode = path.lstat().st_mode
        except OSError:
            fail(f"required delivery file is missing: {filename}")
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            fail(f"required delivery file is not a regular file: {filename}")
    sums_path = delivery_dir / CHECKSUMS
    try:
        lines = sums_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        fail(f"checksum file is unreadable: {exc}")
    seen: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match:
            fail("checksum file contains a malformed row")
        digest, filename = match.groups()
        if filename in seen:
            fail("checksum file contains duplicate filenames")
        seen[filename] = digest
    checksum_targets = expected - {CHECKSUMS}
    if set(seen) != checksum_targets:
        fail("checksum file does not cover every required non-checksum file")
    for filename, digest in seen.items():
        path = delivery_dir / filename
        try:
            mode = path.lstat().st_mode
        except OSError:
            fail(f"required delivery file is missing: {filename}")
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or sha256_file(path) != digest:
            fail(f"checksum mismatch or non-regular required file: {filename}")


def restore_delivery(delivery_dir: Path, target: Path) -> dict[str, Any]:
    if delivery_dir.is_symlink() or not delivery_dir.is_dir():
        fail(f"delivery directory is not a real directory: {delivery_dir}")
    _verify_complete_delivery_files(delivery_dir)
    sidecar_path = delivery_dir / SIDECAR
    manifest = _delivery_manifest(sidecar_path)
    notes = manifest["notes"]
    if notes is not None:
        notes_path = delivery_dir / notes["filename"]
        if notes_path.is_symlink() or not notes_path.is_file() or notes_path.stat().st_size != notes["bytes"] or sha256_file(notes_path) != notes["sha256"]:
            fail("delivery notes are missing or fail their size/SHA256 check")
    if target.exists() or target.is_symlink():
        fail(f"restore target already exists: {target}")
    if not target.parent.is_dir():
        fail(f"restore target parent directory must already exist: {target.parent}")

    payloads: dict[str, bytes] = {}
    for key, archive_row in manifest["archives"].items():
        path = delivery_dir / archive_row["filename"]
        if path.is_symlink() or not path.is_file():
            fail(f"delivery archive is missing or not a regular file: {path.name}")
        if path.stat().st_size != archive_row["bytes"] or path.stat().st_size >= MAX_ARCHIVE_BYTES:
            fail(f"archive size does not match manifest or exceeds limit: {path.name}")
        if sha256_file(path) != archive_row["sha256"]:
            fail(f"archive SHA256 mismatch: {path.name}")
        expected = {name: row for name, row in manifest["files"].items() if row["archive"] == key}
        payload_names: set[str] = set()
        folded: set[str] = set()
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                if len(infos) != len(expected):
                    fail(f"unexpected ZIP entry count: {path.name}")
                for info in infos:
                    rel = _validate_archive_name(info.filename)
                    _zip_member_mode(info, path.name)
                    key_fold = _collision_key(rel)
                    if rel in payload_names or key_fold in folded:
                        fail(f"duplicate/case-colliding ZIP member: {info.filename}")
                    payload_names.add(rel)
                    folded.add(key_fold)
                    if rel not in expected:
                        fail(f"unexpected ZIP member: {info.filename}")
                    row = expected[rel]
                    mode = stat.S_IMODE(info.external_attr >> 16)
                    if mode != int(row["mode"], 8):
                        fail(f"ZIP member mode mismatch: {info.filename}")
                    content = _stream_member(archive, info, row["bytes"])
                    if sha256_bytes(content) != row["sha256"]:
                        fail(f"source file SHA256 mismatch: {info.filename}")
                    payloads[rel] = content
        except zipfile.BadZipFile as exc:
            fail(f"invalid ZIP archive {path.name}: {exc}")
        if payload_names != set(expected):
            fail(f"missing ZIP members: {path.name}")
    if set(payloads) != set(manifest["files"]):
        fail("recomposed paths do not exactly match the split manifest")

    target.mkdir(mode=0o700)
    try:
        for rel in sorted(payloads):
            output = target.joinpath(*_path_parts(rel))
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as f:
                f.write(payloads[rel])
            os.chmod(output, int(manifest["files"][rel]["mode"], 8))
        # Verify exact file and implied directory sets, bytes, hashes and modes.
        actual_files, actual_dirs = _stage_inventory(target)
        if actual_files != set(manifest["files"]) or actual_dirs != _expected_dirs(manifest["files"]):
            fail("restored tree does not exactly match manifest paths")
        for rel in actual_files:
            path = target.joinpath(*_path_parts(rel))
            row = manifest["files"][rel]
            if path.stat().st_size != row["bytes"] or stat.S_IMODE(path.stat().st_mode) != int(row["mode"], 8) or sha256_file(path) != row["sha256"]:
                fail(f"restored file verification failed: {rel}")
    except Exception:
        raise
    return {"target": str(target), "restored_files": len(payloads), "verified": True}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare or safely restore a three-ZIP MIRA source delivery")
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("pack", help="package an already reviewed immutable public projection")
    pack.add_argument("--source-root", required=True, type=Path)
    pack.add_argument("--projection-manifest", required=True, type=Path)
    pack.add_argument("--release-summary", required=True, type=Path)
    pack.add_argument("--asset-manifest", type=Path)
    pack.add_argument("--delivery-notes", type=Path, help="optional UTF-8 START-HERE text copied beside the archives")
    pack.add_argument("--output-dir", required=True, type=Path)
    restore = sub.add_parser("restore", help="verify all three archives and restore to a new target")
    restore.add_argument("--delivery-dir", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "pack":
            asset_path = args.asset_manifest or (args.source_root / ASSET_MANIFEST_REL)
            result = build_delivery(args.source_root, args.projection_manifest, args.release_summary, asset_path, args.output_dir, args.delivery_notes)
            print(json.dumps({
                "delivery_status": result["delivery_status"],
                "archives": {key: {"filename": row["filename"], "bytes": row["bytes"], "sha256": row["sha256"], "members": len(row["members"])} for key, row in result["archives"].items()},
                "manifest": str(args.output_dir / SIDECAR),
                "code_only_notice": result["code_only_notice"],
            }, ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps(restore_delivery(args.delivery_dir, args.target), ensure_ascii=False, sort_keys=True))
        return 0
    except (DeliveryError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"split delivery error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
