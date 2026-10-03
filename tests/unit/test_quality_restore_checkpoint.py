"""Restore validation must not disappear under Python optimization."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = Path(os.environ.get('MIRA_RESTORE_HELPER', ROOT / 'tools/restore_checkpoint.py'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture(root, rows=(('a.txt', b'hello'),)):
    archive = root / 'input.zip'
    members = []
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Duplicate name:', category=UserWarning)
        with zipfile.ZipFile(archive, 'w') as stream:
            for name, data in rows:
                info = zipfile.ZipInfo('snapshot/' + name)
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                stream.writestr(info, data)
                members.append({'path': name, 'bytes': len(data), 'sha256': digest(data), 'mode': '100644'})
    manifest = {'archive_prefix': 'snapshot/', 'archive': {'sha256': digest(archive.read_bytes())}, 'members': members}
    return archive, manifest


def run(root, manifest, mode='normal'):
    path = root / 'manifest.json'
    path.write_text(json.dumps(manifest))
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONIOENCODING': 'utf-8'}
    flags = []
    if mode == 'flag':
        flags = ['-O']
    elif mode == 'environment':
        env['PYTHONOPTIMIZE'] = '1'
    return subprocess.run([sys.executable, *flags, str(HELPER), str(root / 'input.zip'), str(path), str(root / 'output')],
                          env=env, capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize('mode', ['normal', 'flag', 'environment'])
def test_valid_restore_preserves_hashes_and_modes(tmp_path, mode):
    _, manifest = fixture(tmp_path)
    result = run(tmp_path, manifest, mode)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'output/a.txt').read_bytes() == b'hello'
    if os.name == 'posix':
        assert (tmp_path / 'output/a.txt').stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize('mode', ['normal', 'flag', 'environment'])
@pytest.mark.parametrize('problem', ['archive_hash', 'member_hash', 'member_size'])
def test_corrupt_integrity_never_creates_final_destination(tmp_path, mode, problem):
    _, manifest = fixture(tmp_path)
    if problem == 'archive_hash':
        manifest['archive']['sha256'] = '0' * 64
    elif problem == 'member_hash':
        manifest['members'][0]['sha256'] = '0' * 64
    else:
        manifest['members'][0]['bytes'] += 1
    result = run(tmp_path, manifest, mode)
    assert result.returncode != 0
    assert not (tmp_path / 'output').exists()
    assert 'Verified and restored' not in result.stdout


@pytest.mark.parametrize('mode', ['normal', 'flag', 'environment'])
def test_traversal_cannot_change_owned_sibling_sentinel(tmp_path, mode):
    sentinel = tmp_path / 'sibling.txt'
    sentinel.write_bytes(b'untouched')
    _, manifest = fixture(tmp_path, (('../sibling.txt', b'changed'),))
    result = run(tmp_path, manifest, mode)
    assert result.returncode != 0
    assert sentinel.read_bytes() == b'untouched'
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('rows', [(('a', b'one'), ('a/b', b'two')), (('A.txt', b'one'), ('a.txt', b'two')),
                                  (('a.txt', b'one'), ('a.txt', b'two')), (('C:escape', b'x'),),
                                  (('folder\\escape', b'x'),), (('name. ', b'x'),)])
def test_ambiguous_or_nonportable_member_paths_fail_before_final_output(tmp_path, rows):
    _, manifest = fixture(tmp_path, rows)
    result = run(tmp_path, manifest, 'flag')
    assert result.returncode != 0
    assert not (tmp_path / 'output').exists()


def test_second_member_integrity_failure_leaves_no_partial_final_directory(tmp_path):
    _, manifest = fixture(tmp_path, (('a', b'one'), ('b', b'two')))
    manifest['members'][1]['sha256'] = '0' * 64
    result = run(tmp_path, manifest, 'flag')
    assert result.returncode != 0
    assert not (tmp_path / 'output').exists()
    assert not list(tmp_path.glob('.output.restore-*'))


@pytest.mark.parametrize('mode', ['normal', 'flag', 'environment'])
def test_existing_destination_is_never_modified(tmp_path, mode):
    _, manifest = fixture(tmp_path)
    (tmp_path / 'output').mkdir()
    (tmp_path / 'output/keep').write_bytes(b'keep')
    result = run(tmp_path, manifest, mode)
    assert result.returncode != 0
    assert sorted(p.name for p in (tmp_path / 'output').iterdir()) == ['keep']
    assert (tmp_path / 'output/keep').read_bytes() == b'keep'


@pytest.mark.parametrize('name', ['COM¹', 'COM².txt', 'LPT³', 'CONIN$', 'CONOUT$', 'con .txt',
                                   'bad?.txt', 'folder/clock$'])
def test_windows_device_and_forbidden_names_fail_closed_on_every_host(tmp_path, name):
    _, manifest = fixture(tmp_path, ((name, b'x'),))
    result = run(tmp_path, manifest, 'flag')
    assert result.returncode != 0
    assert not (tmp_path / 'output').exists()


def load_helper():
    import importlib.util
    spec = importlib.util.spec_from_file_location('restore_safety_under_test', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_directory_count_is_bounded_before_zipfile_allocation(tmp_path, monkeypatch):
    import struct
    archive, manifest = fixture(tmp_path, (('a', b'one'), ('b', b'two')))
    data = bytearray(archive.read_bytes())
    end = data.rfind(b'PK\x05\x06')
    struct.pack_into('<HH', data, end + 8, 1, 1)  # lie about count, keep two actual records
    archive.write_bytes(data)
    manifest['archive']['sha256'] = digest(data)
    manifest['members'] = manifest['members'][:1]
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(manifest))
    helper = load_helper()
    def forbidden(*args, **kwargs):
        raise RuntimeError('ZipFile allocated before the directory was bounded')
    monkeypatch.setattr(helper.zipfile, 'ZipFile', forbidden)
    with pytest.raises(helper.RestoreError, match='zip_member_count'):
        helper.restore(archive, path, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_directory_byte_cap_precedes_zipfile_allocation(tmp_path, monkeypatch):
    archive, manifest = fixture(tmp_path)
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(manifest))
    helper = load_helper()
    monkeypatch.setattr(helper, 'MAX_DIRECTORY', 1, raising=False)
    def forbidden(*args, **kwargs):
        raise RuntimeError('ZipFile allocated before the directory was bounded')
    monkeypatch.setattr(helper.zipfile, 'ZipFile', forbidden)
    with pytest.raises(helper.RestoreError, match='zip_directory_bound'):
        helper.restore(archive, path, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_dot_path_is_rejected_during_path_validation():
    helper = load_helper()
    with pytest.raises(helper.RestoreError, match='invalid_member_path'):
        helper.relative_path('.')


@pytest.mark.parametrize('mode', ['normal', 'flag', 'environment'])
@pytest.mark.parametrize('problem', ['rebased_sfx', 'cen_disk_start'])
def test_unsupported_zip_layout_is_rejected_before_output(tmp_path, mode, problem):
    import struct
    archive, manifest = fixture(tmp_path)
    data = bytearray(archive.read_bytes())
    cen = data.find(b'PK\x01\x02')
    if problem == 'rebased_sfx':
        stub = b'MZ synthetic non-executable test stub\x00'
        end = data.rfind(b'PK\x05\x06')
        struct.pack_into('<L', data, cen + 42, len(stub))
        struct.pack_into('<L', data, end + 16, cen + len(stub))
        data = bytearray(stub) + data
    else:
        struct.pack_into('<H', data, cen + 34, 1)
    archive.write_bytes(data)
    manifest['archive']['sha256'] = digest(data)
    result = run(tmp_path, manifest, mode)
    assert result.returncode != 0
    assert not (tmp_path / 'output').exists()
    assert not list(tmp_path.glob('.output.restore-*'))
