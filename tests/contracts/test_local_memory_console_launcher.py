from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import local_memory


def test_no_command_and_help_are_inert(monkeypatch, capsys):
    monkeypatch.setattr(local_memory, "_load_options", lambda *_a, **_k: pytest.fail("scope read"))
    monkeypatch.setattr(local_memory, "_create_pairing_material", lambda *_a, **_k: pytest.fail("pairing created"))
    monkeypatch.setattr(local_memory, "_prepare_frontend", lambda: pytest.fail("frontend built"))
    monkeypatch.setattr(local_memory, "_run_server", lambda *_a, **_k: pytest.fail("server started"))
    assert local_memory.main([]) == 0
    assert "usage:" in capsys.readouterr().out.lower()
    assert local_memory.main(["--help"]) == 0
    assert "usage:" in capsys.readouterr().out.lower()


def test_frontend_child_environment_reads_only_explicit_nonsecret_allowlist(monkeypatch):
    monkeypatch.setenv("PATH", "/synthetic/node-bin")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-never-inherited")
    monkeypatch.setenv("MIRA_SERVICES__CODEX__API_KEY", "synthetic-never-inherited")
    child = local_memory._child_environment()
    assert child.get("PATH") == "/synthetic/node-bin"
    assert "OPENAI_API_KEY" not in child
    assert "MIRA_SERVICES__CODEX__API_KEY" not in child


def test_check_requires_consent_before_loading_configuration(monkeypatch):
    monkeypatch.setattr(local_memory, "_load_options", lambda *_a, **_k: pytest.fail("scope read"))
    assert local_memory.main(["check", "--db", "/synthetic/memory.sqlite3",
                              "--scope-config", "/synthetic/scopes.json",
                              "--scope", "test-local"]) == 2


def test_check_never_creates_pairing_or_opens_store(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(local_memory, "_load_options", lambda *_args: calls.append("validate") or object())
    monkeypatch.setattr(local_memory, "_create_pairing_material", lambda *_a, **_k: pytest.fail("pairing created"))
    monkeypatch.setattr(local_memory, "_prepare_frontend", lambda: pytest.fail("frontend built"))
    monkeypatch.setattr(local_memory, "_run_server", lambda *_a, **_k: pytest.fail("server started"))
    result = local_memory.main(["check", "--db", "/synthetic/memory.sqlite3",
                                "--scope-config", "/synthetic/scopes.json",
                                "--scope", "test-local", "--consent-local-memory"])
    assert result == 0 and calls == ["validate"]
    assert "database contents were not opened" in capsys.readouterr().out.lower()


def test_serve_requires_distinct_write_and_pairing_consents(monkeypatch):
    monkeypatch.setattr(local_memory, "_load_options", lambda **_: object())
    monkeypatch.setattr(local_memory, "_create_pairing_material", lambda *_a, **_k: pytest.fail("pairing created"))
    monkeypatch.setattr(local_memory, "_prepare_frontend", lambda: pytest.fail("frontend built"))
    monkeypatch.setattr(local_memory, "_run_server", lambda *_a, **_k: pytest.fail("server started"))
    base = ["serve", "--db", "/synthetic/memory.sqlite3", "--scope-config",
            "/synthetic/scopes.json", "--scope", "test-local", "--consent-local-memory"]
    assert local_memory.main(base) == 2


def test_serve_creates_only_synthetic_pairing_after_explicit_consent(monkeypatch, tmp_path, capsys):
    from fastapi.testclient import TestClient

    from mira.bootstrap import local_memory_management

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    database = private / "synthetic.sqlite3"
    database.write_bytes(b"synthetic-existing-db-placeholder")
    database.chmod(0o600)
    scope_config = private / "scopes.json"
    scope_config.write_text(
        '{"version":1,"scopes":[{"name":"test-local","user_id":"synthetic-user",'
        '"character_id":"mira-test","world_id":"synthetic-world"}]}', encoding="utf-8")
    scope_config.chmod(0o600)
    generated = []
    opened = []
    served = []

    def fake_pairing_material(directory):
        generated.append(directory)
        return SimpleNamespace(path=directory / "synthetic-pairing.txt",
                               code="synthetic-code-only-0123456789abcdef")

    def fake_management_factory(_options, *, authorized_local_writes=False):
        assert authorized_local_writes is True

        async def factory():
            opened.append("open")
            raise AssertionError("store factory ran before pairing")
        return factory

    def run_server(app, *, port):
        served.append(port)
        with TestClient(app) as client:
            headers = {"host": f"127.0.0.1:{port}", "origin": f"http://127.0.0.1:{port}"}
            assert client.get("/health", headers=headers).status_code == 200
            assert client.get("/api/v1/memory-management/status", headers=headers).status_code == 401

    monkeypatch.setattr(local_memory, "_create_pairing_material", fake_pairing_material)
    monkeypatch.setattr(local_memory, "_prepare_frontend", lambda: None)
    monkeypatch.setattr(local_memory, "_run_server", run_server)
    monkeypatch.setattr(local_memory_management, "create_local_memory_management_factory",
                        fake_management_factory)
    result = local_memory.main([
        "serve", "--db", str(database), "--scope-config", str(scope_config),
        "--scope", "test-local", "--consent-local-memory",
        "--authorize-local-memory-writes", "--create-local-operator-pairing",
    ])
    assert result == 0
    assert generated == [private] and served == [8761]
    assert opened == []
    output = capsys.readouterr().out
    assert "synthetic-code-only" not in output
    assert "No provider transmission is enabled" in output


def test_direct_checkout_check_works_without_pythonpath_or_installed_mira(tmp_path):
    import json
    import os
    import subprocess
    import sys

    private = tmp_path / 'direct-private'
    private.mkdir(mode=0o700)
    database = private / 'synthetic.sqlite3'
    database.write_bytes(b'synthetic metadata only; check must not open SQLite')
    database.chmod(0o600)
    scopes = private / 'scopes.json'
    scopes.write_text(json.dumps({'version': 1, 'scopes': [{'name': 'local',
        'user_id': 'synthetic-user', 'character_id': 'mira', 'world_id': 'synthetic-world'}]}))
    scopes.chmod(0o600)
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-I', str(local_memory.ROOT / 'tools/local_memory.py'),
        'check', '--db', str(database), '--scope-config', str(scopes), '--scope', 'local',
        '--consent-local-memory'], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'Database contents were not opened' in result.stdout
    assert database.read_bytes() == b'synthetic metadata only; check must not open SQLite'
    assert sorted(p.name for p in private.iterdir()) == ['scopes.json', 'synthetic.sqlite3']


def test_direct_checkout_pairing_helper_import_has_no_pythonpath_dependency(tmp_path):
    import os
    import subprocess
    import sys

    program = '''import importlib.util,sys
from pathlib import Path
p=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location("local_entry",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from tools import operator_pairing_file
operator_pairing_file.create_pairing_material=lambda directory,checkout_root: "synthetic-only"
assert m._create_pairing_material(Path("/synthetic/private")) == "synthetic-only"
print("pairing_helper_import_ok_no_credential_created")
'''
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-I', '-c', program,
        str(local_memory.ROOT / 'tools/local_memory.py')], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'pairing_helper_import_ok_no_credential_created'


def test_fixed_consent_error_is_actionable_but_unknown_errors_are_not_echoed(monkeypatch, capsys):
    args = ['check', '--db', '/synthetic/private/memory.sqlite3',
        '--scope-config', '/synthetic/private/scopes.json', '--scope', 'local']
    assert local_memory.main(args) == 2
    assert '--consent-local-memory' in capsys.readouterr().err
    monkeypatch.setattr(local_memory, '_load_options', lambda *_: (_ for _ in ()).throw(OSError('secret-never-echo')))
    assert local_memory.main([*args, '--consent-local-memory']) == 2
    assert 'secret-never-echo' not in capsys.readouterr().err
