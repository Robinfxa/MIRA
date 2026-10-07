"""No-socket/no-credential private launch declaration and uvicorn wiring tests."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import live_provider as cli
from tests.contracts.test_live_provider_launcher import arguments, env


def private_args(tmp_path, *, origin="https://mira.local:8443", voice=False):
    directory = tmp_path / "pairing"
    directory.mkdir(mode=0o700)
    cert = tmp_path / "synthetic-cert.pem"
    key = tmp_path / "synthetic-key.pem"
    cert.write_text("synthetic certificate bytes not loaded")
    key.write_text("synthetic key bytes not loaded"); key.chmod(0o600)
    return SimpleNamespace(private_bind="192.168.20.8", device_origin=origin,
        device_pairing_dir=directory, tls_cert_file=cert, tls_key_file=key,
        allow_private_http_text=False, port=8443, voice=voice,
        memory_db=None, story_db=None, conversation_db=None,
        create_local_operator_pairing=False)


def test_http_requires_explicit_text_ack_and_cannot_enable_voice(tmp_path):
    from tools.private_device_access import device_options, PrivateDeviceError
    args = private_args(tmp_path, origin="http://mira.local:8443", voice=True)
    args.tls_cert_file = args.tls_key_file = None
    args.allow_private_http_text = True
    with pytest.raises(PrivateDeviceError, match="HTTPS"):
        device_options(args)
    args.voice = False
    assert device_options(args).policy.scheme == "http"
    args.allow_private_http_text = False
    with pytest.raises(PrivateDeviceError, match="plaintext"):
        device_options(args)


def test_https_requires_complete_existing_private_key_metadata_without_reading(tmp_path, monkeypatch):
    from tools.private_device_access import device_options, PrivateDeviceError
    args = private_args(tmp_path)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("No credential content reads"))
    monkeypatch.setattr(Path, "read_text", lambda *_: pytest.fail("No credential content reads"))
    option = device_options(args)
    assert option.policy.origin == "https://mira.local:8443"
    args.tls_key_file.chmod(0o644)
    with pytest.raises(PrivateDeviceError, match="owner-only"):
        device_options(args)
    args.tls_key_file = None
    with pytest.raises(PrivateDeviceError, match="certificate and key"):
        device_options(args)


def test_private_check_reports_declaration_without_creating_pairing_or_listening(tmp_path, monkeypatch, capsys):
    args = private_args(tmp_path)
    path = env(tmp_path)
    monkeypatch.setattr(cli, "_generation", lambda *_: pytest.fail("No providers in check"))
    command = arguments(path) + ["--port", "8443", "--private-bind", args.private_bind,
        "--device-origin", args.device_origin, "--device-pairing-dir", str(args.device_pairing_dir),
        "--tls-cert-file", str(args.tls_cert_file), "--tls-key-file", str(args.tls_key_file)]
    assert cli.main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["device_access"]["enabled"] is True
    assert result["device_access"]["pairing_files_created"] is False
    assert result["device_access"]["max_device_sessions"] == 2
    assert result["device_access"]["browser_tls_trust"] == "not_verified"
    assert list(args.device_pairing_dir.iterdir()) == []


def test_private_uvicorn_uses_exact_address_tls_and_no_proxy_trust_or_access_log(tmp_path, monkeypatch):
    from tools.private_device_access import device_options, run_private_server
    import uvicorn
    args = private_args(tmp_path)
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    app = object()
    run_private_server(app, device_options(args))
    passed = calls[0][1]
    assert calls[0][0] == (app,)
    assert passed["host"] == args.private_bind and passed["port"] == 8443
    assert passed["ssl_certfile"] == str(args.tls_cert_file)
    assert passed["ssl_keyfile"] == str(args.tls_key_file)
    assert passed["proxy_headers"] is False and passed["access_log"] is False
    assert passed["workers"] == 1


def test_direct_composition_preserves_exact_private_origin_and_two_device_capacity(settings):
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from tests.contracts.test_direct_provider_app import arguments as app_arguments
    from tests.contracts.test_private_device_access import private_settings, device_pairing
    from fastapi.testclient import TestClient
    app = create_direct_provider_app(**app_arguments(settings=private_settings(settings),
        operator_pairing=device_pairing()))
    with TestClient(app, base_url="https://mira.local:8443"):
        assert app.state.operator_pairing.expected_origins == frozenset(("https://mira.local:8443",))
        assert app.state.container is None


def test_combined_private_local_unlimited_check_keeps_service_budgets_finite(tmp_path, monkeypatch, capsys):
    args = private_args(tmp_path)
    path = env(tmp_path)
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('No provider construction'))
    command = arguments(path) + ['--local-unlimited', '--generation-requests', '3',
        '--port', '8443', '--private-bind', args.private_bind,
        '--device-origin', args.device_origin, '--device-pairing-dir', str(args.device_pairing_dir),
        '--tls-cert-file', str(args.tls_cert_file), '--tls-key-file', str(args.tls_key_file)]
    assert cli.main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['local_interaction_policy'] == 'unlimited'
    assert result['turn_limit'] is None
    assert result['generation_request_limit'] == 3
    assert result['device_access']['max_device_sessions'] == 2
    assert result['device_access']['listener_started'] is False
    assert not list(args.device_pairing_dir.iterdir())
