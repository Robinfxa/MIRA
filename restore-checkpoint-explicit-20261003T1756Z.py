"""Bounded MIRA checkpoint verification and staged restore (standard library only).

Hashes prove consistency with the supplied manifest, not its source authenticity.
Choose a private output parent without competing writers. No archive code is run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import struct
import sys
import tempfile
import unicodedata
import zipfile

MAX_ARCHIVE = 128 * 1024 * 1024
MAX_MANIFEST = 8 * 1024 * 1024
MAX_MEMBER = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_DIRECTORY = 8 * 1024 * 1024
SHA = re.compile(r'[a-f0-9]{64}')
RESERVED = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$', 'clock$',
            *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10)),
            *(f'com{i}' for i in '¹²³'), *(f'lpt{i}' for i in '¹²³')}


class RestoreError(ValueError):
    """A fixed safe error category, never raw archive content."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RestoreError(code)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_manifest_key')
        result[key] = value
    return result


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(65536), b''):
            result.update(part)
    return result.hexdigest()


def relative_path(value: object) -> str:
    require(type(value) is str and 0 < len(value) <= 2048, 'invalid_member_path')
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value), 'invalid_member_path')
    require(not any(char in value for char in '\\:<>"|?*'), 'invalid_member_path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and not PureWindowsPath(value).drive
            and str(path) == value, 'invalid_member_path')
    require(bool(path.parts), 'invalid_member_path')
    require(len(path.parts) <= 64, 'path_depth_bound')
    require(all(part not in {'', '.', '..'} and not part.endswith((' ', '.'))
                and part.split('.', 1)[0].rstrip(' ').casefold() not in RESERVED for part in path.parts),
            'invalid_member_path')
    try:
        require(all(len(part.encode('utf-8')) <= 255 for part in path.parts), 'invalid_member_path')
    except UnicodeError:
        raise RestoreError('invalid_member_path') from None
    return value


def bounded_zip32_directory(path: Path, expected_count: int) -> None:
    """Preflight actual ZIP32 directory records before ZipFile allocates entries.

    MIRA checkpoints need neither ZIP64, multidisk nor self-extracting layouts.
    Unsupported layouts fail closed instead of enlarging this restore format.
    """
    size = path.stat().st_size
    with path.open('rb') as stream:
        require(stream.read(4) == b'PK\x03\x04', 'unsupported_zip_layout')
        tail_size = min(size, 22 + 65535)
        stream.seek(size - tail_size)
        tail = stream.read(tail_size)
        offset = tail.rfind(b'PK\x05\x06')
        require(offset >= 0 and offset + 22 <= len(tail), 'invalid_zip_directory')
        header = struct.unpack('<4s4H2LH', tail[offset:offset + 22])
        _, disk, directory_disk, disk_count, count, directory_size, directory_offset, comment_size = header
        eocd = size - tail_size + offset
        require(offset + 22 + comment_size == len(tail), 'invalid_zip_directory')
        require(disk == directory_disk == 0 and disk_count == count, 'unsupported_zip_layout')
        require(0 < count == expected_count <= MAX_MEMBERS and count != 65535,
                'zip_member_count_bound')
        require(0 < directory_size <= MAX_DIRECTORY and directory_offset != 0xffffffff
                and directory_offset + directory_size == eocd, 'zip_directory_bound')
        if eocd >= 20:
            stream.seek(eocd - 20)
            require(stream.read(4) != b'PK\x06\x07', 'unsupported_zip64')
        stream.seek(directory_offset)
        end, observed = directory_offset + directory_size, 0
        while stream.tell() < end:
            record = stream.read(46)
            require(len(record) == 46 and record[:4] == b'PK\x01\x02', 'invalid_zip_directory')
            name_size, extra_size, member_comment_size, member_disk = struct.unpack_from('<4H', record, 28)
            local_offset = struct.unpack_from('<L', record, 42)[0]
            require(member_disk == 0 and local_offset != 0xffffffff
                    and (observed != 0 or local_offset == 0), 'unsupported_zip_layout')
            observed += 1
            require(observed <= expected_count and observed <= MAX_MEMBERS,
                    'zip_member_count_bound')
            require(0 < name_size <= 4096 and stream.tell() + name_size + extra_size + member_comment_size <= end,
                    'zip_directory_bound')
            stream.seek(name_size + extra_size + member_comment_size, os.SEEK_CUR)
        require(stream.tell() == end and observed == count, 'zip_member_count_mismatch')


def load_manifest(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), 'manifest_not_regular')
    require(path.stat().st_size <= MAX_MANIFEST, 'manifest_too_large')
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(RestoreError('nonfinite_manifest')))
    except (UnicodeError, json.JSONDecodeError):
        raise RestoreError('invalid_manifest_json') from None
    require(type(value) is dict, 'invalid_manifest')
    return value


def restore(archive: Path, manifest_path: Path, destination: Path) -> int:
    require(archive.is_file() and not archive.is_symlink(), 'archive_not_regular')
    require(archive.stat().st_size <= MAX_ARCHIVE, 'archive_too_large')
    manifest = load_manifest(manifest_path)
    outer = manifest.get('archive')
    require(type(outer) is dict and type(outer.get('sha256')) is str
            and SHA.fullmatch(outer['sha256']) is not None, 'invalid_archive_digest')
    require(file_digest(archive) == outer['sha256'], 'archive_hash_mismatch')
    if 'bytes' in outer:
        require(type(outer['bytes']) is int and outer['bytes'] == archive.stat().st_size,
                'archive_size_mismatch')
    prefix = manifest.get('archive_prefix')
    require(type(prefix) is str and prefix.endswith('/'), 'invalid_archive_prefix')
    relative_path(prefix[:-1])
    rows = manifest.get('members')
    require(type(rows) is list and 0 < len(rows) <= MAX_MEMBERS, 'invalid_member_count')
    expected, canonical_names = {}, set()
    total = 0
    for row in rows:
        require(type(row) is dict, 'invalid_member')
        name = relative_path(row.get('path'))
        normalized = unicodedata.normalize('NFC', name).casefold()
        require(normalized not in canonical_names, 'duplicate_or_ambiguous_member')
        canonical_names.add(normalized)
        require(type(row.get('bytes')) is int and 0 <= row['bytes'] <= MAX_MEMBER, 'invalid_member_size')
        require(type(row.get('sha256')) is str and SHA.fullmatch(row['sha256']) is not None,
                'invalid_member_digest')
        require(type(row.get('mode')) is str and re.fullmatch(r'100[0-7]{3}', row['mode']) is not None,
                'invalid_member_mode')
        total += row['bytes']
        require(total <= MAX_TOTAL, 'total_size_bound')
        expected[prefix + name] = row
    for name in canonical_names:
        require(not any(parent.as_posix() in canonical_names for parent in PurePosixPath(name).parents
                        if parent.as_posix() != '.'), 'file_directory_conflict')
    destination = destination.absolute()
    require(not os.path.lexists(destination), 'destination_exists')
    parent = destination.parent.resolve(strict=True)
    require(parent.is_dir(), 'destination_parent_missing')
    destination = parent / destination.name
    bounded_zip32_directory(archive, len(expected))
    stage = None
    try:
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            names = [info.filename for info in infos]
            require(len(names) == len(set(names)) == len(expected) and set(names) == set(expected),
                    'archive_member_mismatch')
            for info in infos:
                row = expected[info.filename]
                mode = info.external_attr >> 16
                require(stat.S_ISREG(mode) and f'{mode:06o}' == row['mode'], 'stored_mode_mismatch')
                require(not info.is_dir() and not (info.flag_bits & 1), 'unsupported_member_type')
                require(info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}, 'unsupported_compression')
                require(info.file_size == row['bytes'], 'stored_size_mismatch')
            # Final destination is not created until every staged member passes all checks.
            stage = Path(tempfile.mkdtemp(prefix=f'.{destination.name}.restore-', dir=parent))
            for info in infos:
                row = expected[info.filename]
                target = stage / row['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                digest, count = hashlib.sha256(), 0
                with zipped.open(info) as source, target.open('xb') as sink:
                    for part in iter(lambda: source.read(65536), b''):
                        count += len(part)
                        require(count <= row['bytes'] and count <= MAX_MEMBER, 'member_size_mismatch')
                        digest.update(part)
                        sink.write(part)
                require(count == row['bytes'] and digest.hexdigest() == row['sha256'], 'member_hash_mismatch')
                require(file_digest(target) == row['sha256'], 'restored_hash_mismatch')
                target.chmod(stat.S_IMODE(int(row['mode'], 8)))
                if os.name == 'posix':
                    require(f'{target.stat().st_mode:06o}' == row['mode'], 'restored_mode_mismatch')
            require(not os.path.lexists(destination), 'destination_exists')
            stage.rename(destination)
            stage = None
        return len(expected)
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    try:
        count = restore(args.archive, args.manifest, args.destination)
    except RestoreError as error:
        print(f'Restore refused: {error}', file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        print('Restore refused: archive or filesystem operation failed; final output not committed.', file=sys.stderr)
        return 2
    print(f'Verified and restored {count} files using explicit integrity/path checks and staged output. '
          'Stored modes checked; restored modes checked on Unix. Manifest authenticity must be verified separately.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
