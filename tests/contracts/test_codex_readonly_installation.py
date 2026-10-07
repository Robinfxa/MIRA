"""Offline guard contracts for the explicitly approved managed Codex install."""
import hashlib
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from mira.adapters.generation.codex_support import process, types
from mira.adapters.generation.codex_support.payload import canonical


def _runtime(tmp_path: Path, *, approval_path: str | None = None):
    executable = tmp_path / 'opt' / 'codex' / 'bin' / 'codex'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'synthetic pinned executable')
    executable.chmod(0o755)
    home = tmp_path / 'home'
    home.mkdir()
    home.chmod(0o755)
    cwd = tmp_path / 'run'
    cwd.mkdir()
    cwd.chmod(0o700)
    environment = {'CODEX_HOME': str(home), 'HTTPS_PROXY': 'http://proxy.invalid:8080',
                   'SSL_CERT_FILE': '/approved/ca.pem'}
    foreign_uid = os.getuid() + 10000
    install = types.ReadonlyInstallationApproval(
        executable_path=approval_path or str(executable),
        verified_uid=foreign_uid, verified_mode=0o755)
    context = types.ApprovedDevelopmentContext(
        route_value_sha256='a' * 64, observed_home_mode=0o755,
        managed_environment_sha256=hashlib.sha256(canonical(environment)).hexdigest(),
        readonly_installation=install)
    runtime = types.CodexRuntime(
        executable, home, cwd, environment=environment, expected_config_sha256='b' * 64,
        policy_environment_confirmed=True, development_context=context)
    return runtime, executable, foreign_uid


def _fake_install_metadata(monkeypatch, executable: Path, foreign_uid: int, *,
                           parent_uid: int | None = None, executable_mode: int = 0o755,
                           parent_mode: int = 0o755, writable: tuple[Path, ...] = (),
                           writable_mount: tuple[Path, ...] = (),
                           readonly_mount: bool = True):
    original_stat = Path.stat
    original_lstat = Path.lstat
    install_metadata = {
        executable: (foreign_uid, executable_mode, stat_mode_file()),
        executable.parent: (foreign_uid if parent_uid is None else parent_uid,
                            parent_mode, stat_mode_dir()),
    }

    def metadata(path, original):
        result = original(path)
        if path == Path('/tmp'):
            return SimpleNamespace(st_uid=0, st_mode=stat_mode_dir() | 0o755)
        if path in install_metadata:
            owner, permissions, kind = install_metadata[path]
            return SimpleNamespace(st_uid=owner, st_mode=kind | permissions)
        return result

    monkeypatch.setattr(Path, 'stat', lambda self, *args, **kwargs:
                        metadata(self, original_stat))
    monkeypatch.setattr(Path, 'lstat', lambda self, *args, **kwargs:
                        metadata(self, original_lstat))
    monkeypatch.setattr(process.os, 'access', lambda path, mode: Path(path) in writable)
    readonly_flag = getattr(os, 'ST_RDONLY', 1)
    def fake_statvfs(path):
        readonly = readonly_mount and Path(path) not in writable_mount
        return SimpleNamespace(f_flag=readonly_flag if readonly else 0)
    monkeypatch.setattr(process.os, 'statvfs', fake_statvfs)
    # Treat the synthetic bytes as the already hash-verified pinned official binary.
    class PinnedDigest:
        def update(self, _chunk):
            pass

        def hexdigest(self):
            return types.PINNED_EXECUTABLE_SHA256

    monkeypatch.setattr(process, 'hashlib', SimpleNamespace(sha256=PinnedDigest))


def stat_mode_file():
    import stat
    return stat.S_IFREG


def stat_mode_dir():
    import stat
    return stat.S_IFDIR


def test_readonly_approval_is_immutable_and_bound_to_valid_path_uid_and_mode(tmp_path):
    runtime, executable, foreign_uid = _runtime(tmp_path)
    approval = runtime.development_context.readonly_installation
    assert approval.executable_path == str(executable)
    assert approval.verified_uid == foreign_uid
    assert approval.verified_mode == 0o755
    with pytest.raises(FrozenInstanceError):
        approval.verified_uid = 0

    invalid = [
        {'executable_path': 'relative/codex', 'verified_uid': foreign_uid,
         'verified_mode': 0o755},
        {'executable_path': str(executable.parent / '..' / 'codex'),
         'verified_uid': foreign_uid, 'verified_mode': 0o755},
        {'executable_path': str(executable), 'verified_uid': True, 'verified_mode': 0o755},
        {'executable_path': str(executable), 'verified_uid': foreign_uid,
         'verified_mode': 0o775},
        {'executable_path': str(executable), 'verified_uid': foreign_uid,
         'verified_mode': 0o644},
    ]
    for kwargs in invalid:
        with pytest.raises(ValueError, match='readonly_installation_approval_invalid'):
            types.ReadonlyInstallationApproval(**kwargs)


def test_exact_managed_readonly_install_passes_offline_validation(tmp_path, monkeypatch):
    runtime, executable, foreign_uid = _runtime(tmp_path)
    _fake_install_metadata(monkeypatch, executable, foreign_uid)
    process._validate_runtime(runtime)


@pytest.mark.parametrize('failure', [
    'wrong_owner', 'wrong_mode', 'target_group_write', 'parent_group_write',
    'read_write_mount', 'current_user_writable', 'wrong_path', 'foreign_parent',
    'writable_foreign_parent', 'parent_world_write',
])
def test_readonly_install_rejects_each_metadata_drift(tmp_path, monkeypatch, failure):
    runtime, executable, foreign_uid = _runtime(tmp_path)
    parent_uid = foreign_uid
    executable_mode = 0o755
    parent_mode = 0o755
    writable = ()
    writable_mount = ()
    readonly_mount = True
    if failure == 'wrong_owner':
        foreign_uid += 1
    elif failure == 'wrong_mode':
        executable_mode = 0o555
    elif failure == 'target_group_write':
        # The approval itself is an immutable observation and still says 0755.
        executable_mode = 0o775
    elif failure == 'parent_group_write':
        parent_mode = 0o775
    elif failure == 'read_write_mount':
        readonly_mount = False
    elif failure == 'current_user_writable':
        writable = (executable,)
    elif failure == 'wrong_path':
        other = executable.parent / 'other-codex'
        approval = types.ReadonlyInstallationApproval(str(other), foreign_uid, 0o755)
        context = replace(runtime.development_context, readonly_installation=approval)
        runtime = replace(runtime, development_context=context)
    elif failure == 'foreign_parent':
        parent_uid = foreign_uid + 1
    elif failure == 'writable_foreign_parent':
        writable = (executable.parent,)
    elif failure == 'parent_world_write':
        parent_mode = 0o757

    _fake_install_metadata(monkeypatch, executable, foreign_uid,
                           parent_uid=parent_uid, executable_mode=executable_mode,
                           parent_mode=parent_mode, writable=writable,
                           writable_mount=writable_mount, readonly_mount=readonly_mount)
    with pytest.raises(types.CodexGenerationError, match='codex_runtime_permissions'):
        process._validate_runtime(runtime)


def test_readonly_install_rejects_symlink_in_executable_path(tmp_path, monkeypatch):
    runtime, executable, foreign_uid = _runtime(tmp_path)
    real_opt = executable.parents[2]
    link = tmp_path / 'linked-opt'
    link.symlink_to(real_opt, target_is_directory=True)
    linked_executable = link / 'codex' / 'bin' / 'codex'
    approval = types.ReadonlyInstallationApproval(str(linked_executable), foreign_uid, 0o755)
    context = replace(runtime.development_context, readonly_installation=approval)
    runtime = replace(runtime, executable=linked_executable, development_context=context)
    _fake_install_metadata(monkeypatch, linked_executable, foreign_uid)
    with pytest.raises(types.CodexGenerationError, match='codex_runtime_symlink'):
        process._validate_runtime(runtime)


@pytest.mark.asyncio
async def test_optional_exception_does_not_change_default_or_public_preflight_admission(tmp_path,
                                                                                       monkeypatch):
    runtime, executable, foreign_uid = _runtime(tmp_path)
    plain = types.CodexRuntime(executable, runtime.codex_home, runtime.runtime_cwd,
                               expected_config_sha256='b' * 64,
                               policy_environment_confirmed=True)
    _fake_install_metadata(monkeypatch, executable, foreign_uid)
    with pytest.raises(types.CodexGenerationError, match='codex_runtime_permissions'):
        process._validate_runtime(plain)
    # The public metadata route remains categorically separate from a managed context.
    with pytest.raises(types.CodexGenerationError, match='codex_preflight_route_unsupported'):
        await process.open_stdio_preflight(runtime, types.CodexLimits())
