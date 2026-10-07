"""Synthetic contracts for explicit public-route Codex metadata preparation."""
import argparse
import asyncio
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from mira.adapters.generation.codex_support import process, types
from mira.adapters.generation.codex_support.payload import canonical
from mira.adapters.generation.codex_support.preflight import MetadataOnlyTransport
from tools import prepare_runtime_admission as prepare

FLAGS = ("apps", "plugins", "browser_use", "computer_use", "multi_agent", "shell_tool",
         "image_generation", "tool_suggest", "sleep_tool", "token_budget")


def _external_temp_parent() -> Path:
    """Choose a system temp parent that stays outside the checkout."""
    repository = prepare.ROOT.resolve()
    candidates = (Path(tempfile.gettempdir()), Path("/tmp"), Path("/var/tmp"))
    for candidate in candidates:
        try:
            parent = candidate.resolve(strict=True)
        except OSError:
            continue
        if parent.is_dir() and parent != repository and repository not in parent.parents:
            return parent
    raise RuntimeError("No temporary directory outside the MIRA checkout is available")


@pytest.fixture
def private_tmp_path():
    """Own and clean synthetic private inputs outside any pytest basetemp."""
    with tempfile.TemporaryDirectory(prefix="mira-admission-test-",
                                     dir=_external_temp_parent()) as directory:
        yield Path(directory)


def _public_config():
    return {
        "features": {**dict.fromkeys(FLAGS, False), "respect_system_proxy": True},
        "mcp_servers": {}, "web_search": "disabled", "model": "gpt-6-luna",
        "model_provider": "openai", "forced_login_method": "chatgpt",
        "approval_policy": "never", "sandbox_mode": "read-only",
    }


class SyntheticMetadataTransport:
    def __init__(self, *, user_agent="codex/0.159.2 (linux)", config=None,
                 unsolicited=None):
        self.user_agent = user_agent
        self.config = config or _public_config()
        self.unsolicited = unsolicited
        self.sent = []
        self.incoming = asyncio.Queue()
        self.closed = False

    async def send(self, message):
        self.sent.append(message)
        if "id" not in message:
            return
        if self.unsolicited is not None:
            response = self.unsolicited
        elif message["method"] == "initialize":
            response = {"id": message["id"], "result": {
                "userAgent": self.user_agent, "codexHome": "/synthetic/home",
                "platformFamily": "unix", "platformOs": "linux"}}
        elif message["method"] == "config/read":
            response = {"id": message["id"], "result": {
                "config": self.config, "origins": {}, "layers": None}}
        else:
            response = {"id": message["id"], "result": {}}
        await self.incoming.put(json.dumps(response).encode() + b"\n")

    async def receive(self):
        return await self.incoming.get()

    async def close(self):
        self.closed = True


def _runtime():
    return types.CodexRuntime(Path("/synthetic/codex"), Path("/synthetic/home"),
                              Path("/synthetic/run"), policy_environment_confirmed=True)


def test_no_args_is_unarmed_and_performs_zero_setup_io(monkeypatch, capsys):
    called = False

    async def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("metadata transport must not start")

    monkeypatch.setattr(prepare, "observe_public_metadata", forbidden)
    monkeypatch.setattr(sys, "argv", ["prepare_runtime_admission.py"])
    assert prepare.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "unarmed", "metadata_probe": "not_run",
                      "admission_written": False,
                      "next": "Run --help for explicit setup options."}
    assert not called


@pytest.mark.asyncio
async def test_preflight_sends_only_initialize_initialized_and_config_read_without_claims():
    transport = SyntheticMetadataTransport()
    observed = await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert [message.get("method") for message in transport.sent] == [
        "initialize", "initialized", "config/read"]
    assert all(message.get("method") not in {
        "account/read", "account/list", "thread/start", "turn/start", "tools/list"}
        for message in transport.sent)
    assert observed.config_sha256 == __import__("hashlib").sha256(
        canonical(_public_config())).hexdigest()
    assert observed.codex_version == "0.159.2" and observed.route_kind == "public"
    assert not hasattr(observed, "account") and not hasattr(observed, "entitlement")
    assert transport.closed


@pytest.mark.asyncio
async def test_preflight_rejects_wrong_version_custom_route_and_server_rpc():
    cases = [SyntheticMetadataTransport(user_agent="codex/0.160.0 (linux)"),
             SyntheticMetadataTransport(config={**_public_config(),
                                                "openai_base_url": "https://route.invalid"}),
             SyntheticMetadataTransport(config={**_public_config(),
                                                "openai_api_key": "secret-never-returned"}),
             SyntheticMetadataTransport(unsolicited={"method": "account/updated",
                                                     "params": {"email": "private"}})]
    for transport in cases:
        with pytest.raises(types.CodexGenerationError):
            await MetadataOnlyTransport(transport, _runtime()).observe(2)
        assert transport.closed
        assert not any(message.get("method") in {"account/read", "thread/start", "turn/start"}
                       for message in transport.sent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("envelope", "expected_category", "expected_method", "expected_code", "expected_id_match"),
    [
        ({"jsonrpc": "2.0", "id": 1, "error": {
            "code": -32000, "message": "synthetic-private-error",
            "data": {"access_token": "synthetic-secret"}}},
         "rpc_error", None, -32000, True),
        ({"jsonrpc": "2.0", "method": "account/updated",
          "params": {"email": "synthetic-private@example.invalid"}},
         "notification", "account/updated", None, None),
        ({"jsonrpc": "2.0", "id": 77, "method": "arbitrary/secret-method",
          "params": {"payload": "synthetic-secret"}},
         "server_request", "unknown", None, False),
        ({"jsonrpc": "2.0", "id": 77, "result": {"private": "synthetic-secret"}},
         "response_id_or_version_mismatch", None, None, False),
    ],
)
async def test_preflight_failure_diagnostics_are_phase_bounded_and_redacted(
    envelope, expected_category, expected_method, expected_code, expected_id_match,
):
    from mira.adapters.generation.codex_support.preflight import PreflightDiagnosticError

    transport = SyntheticMetadataTransport(unsolicited=envelope)
    with pytest.raises(PreflightDiagnosticError) as caught:
        await MetadataOnlyTransport(transport, _runtime()).observe(2)

    details = caught.value.safe_details
    assert details["phase"] == "initialize"
    assert details["envelope_category"] == expected_category
    assert details["request_id_match"] is expected_id_match
    assert details["expected_protocol_fields"] == ["jsonrpc", "id", "result"]
    assert details["expected_body_fields"] == [
        "userAgent", "codexHome", "platformFamily", "platformOs"]
    assert details["optional_body_fields"] == []
    if expected_method is not None:
        assert details["notification_method"] == expected_method
    if expected_code is not None:
        assert details["numeric_error_code"] == expected_code
    rendered = str(caught.value) + json.dumps(details)
    assert "synthetic-private-error" not in rendered
    assert "synthetic-private@example.invalid" not in rendered
    assert "synthetic-secret" not in rendered
    assert "access_token" not in rendered
    assert transport.closed


@pytest.mark.asyncio
async def test_preflight_diagnostic_identifies_config_read_error_phase_without_payload():
    from mira.adapters.generation.codex_support.preflight import PreflightDiagnosticError

    class ConfigReadErrorTransport(SyntheticMetadataTransport):
        async def send(self, message):
            if message.get("method") == "config/read":
                await self.incoming.put(json.dumps({"jsonrpc": "2.0", "id": 2,
                    "error": {"code": 1017, "message": "synthetic-config-path-detail"},
                    "secret": "synthetic-secret"}).encode() + b"\n")
                return
            await super().send(message)

    transport = ConfigReadErrorTransport()
    with pytest.raises(PreflightDiagnosticError) as caught:
        await MetadataOnlyTransport(transport, _runtime()).observe(2)

    details = caught.value.safe_details
    assert details == {
        "phase": "config/read", "envelope_category": "rpc_error",
        "request_id_match": True,
        "expected_protocol_fields": ["jsonrpc", "id", "result"],
        "expected_body_fields": ["config", "origins", "layers"],
        "optional_body_fields": ["layers"], "numeric_error_code": 1017,
    }
    assert "synthetic-config-path-detail" not in str(caught.value)
    assert "synthetic-secret" not in json.dumps(details)
    assert transport.closed


@pytest.mark.asyncio
async def test_preflight_rejects_disallowed_rpc_before_transport_send():
    transport = SyntheticMetadataTransport()
    client = MetadataOnlyTransport(transport, _runtime())
    with pytest.raises(types.CodexGenerationError, match="rpc_forbidden"):
        await client._request(3, "account/read", {"refreshToken": False})
    assert transport.sent == []
    await client.close()


def test_environment_rejects_api_key_presence_and_proxy_userinfo_without_echoing_values():
    class SecretMapping(dict):
        def __getitem__(self, key):
            if key == "OPENAI_API_KEY":
                raise AssertionError("secret value must never be read")
            return super().__getitem__(key)

    with pytest.raises(prepare.PreparationError, match="override_present") as caught:
        prepare._public_environment(SecretMapping(OPENAI_API_KEY="synthetic-secret"))
    assert "synthetic-secret" not in str(caught.value)
    with pytest.raises(prepare.PreparationError, match="proxy_userinfo"):
        prepare._public_environment({"HTTPS_PROXY": "http://user:secret@proxy.invalid:3128"})


def test_private_writer_creates_exact_mode_no_overwrite_and_rejects_symlink_parent(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    target = private / "admission.json"
    document = {"authorized": True, "route_kind": "public"}
    with pytest.raises(prepare.PreparationError, match="content_authorization_required"):
        prepare.write_admission(target, document, repo_root=tmp_path / "repo")
    assert not target.exists()
    prepare.write_admission(target, document, content_authorized=True,
                            repo_root=tmp_path / "repo")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert json.loads(target.read_text()) == document
    with pytest.raises(prepare.PreparationError, match="already_exists"):
        prepare.write_admission(target, document, content_authorized=True,
                                repo_root=tmp_path / "repo")
    symlink = tmp_path / "linked"
    symlink.symlink_to(private, target_is_directory=True)
    with pytest.raises(prepare.PreparationError, match="parent_missing_or_unsafe"):
        prepare.write_admission(symlink / "other.json", document, content_authorized=True,
                                repo_root=tmp_path / "repo")


def test_policy_confirmation_alone_cannot_probe_or_write(monkeypatch, tmp_path, capsys):
    called = False

    async def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("content authorization is required before metadata traffic")

    monkeypatch.setattr(prepare, "observe_public_metadata", forbidden)
    monkeypatch.setattr(sys, "argv", ["prepare_runtime_admission.py", "--prepare",
        "--confirm-policy-environment", "--codex-requests", "1", "--session-turns", "1",
        "--input-jev-requests", "1", "--output-jev-requests", "1",
        "--input-jev-timeout-seconds", "5", "--output-jev-timeout-seconds", "5",
        "--probe-timeout-seconds", "5", "--write-admission", str(tmp_path / "no.json")])
    assert prepare.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked" and not result["admission_written"]
    assert not called and not (tmp_path / "no.json").exists()


@pytest.mark.asyncio
async def test_explicit_content_ack_writes_reader_compatible_public_declaration(monkeypatch, private_tmp_path):
    executable = private_tmp_path / "codex"
    executable.write_text("synthetic pinned executable placeholder")
    executable.chmod(0o700)
    codex_home = private_tmp_path / "home"
    runtime_cwd = private_tmp_path / "run"
    codex_home.mkdir(mode=0o700)
    runtime_cwd.mkdir(mode=0o700)
    codex_home.chmod(0o700)
    runtime_cwd.chmod(0o700)
    output_parent = private_tmp_path / "output"
    output_parent.mkdir(mode=0o700)
    output_parent.chmod(0o700)
    output = output_parent / "admission.json"
    args = prepare._parser().parse_args(["--prepare", "--codex", str(executable),
        "--codex-home", str(codex_home), "--runtime-cwd", str(runtime_cwd),
        "--codex-requests", "2", "--session-turns", "2", "--input-jev-requests", "3",
        "--output-jev-requests", "3", "--input-jev-timeout-seconds", "10",
        "--output-jev-timeout-seconds", "10", "--probe-timeout-seconds", "10",
        "--confirm-policy-environment", "--authorize-codex-and-jev-content",
        "--write-admission", str(output)])
    observed_config_hash = "a" * 64

    async def synthetic_observation(runtime, **kwargs):
        assert runtime.expected_config_sha256 is None and runtime.development_context is None
        return type("Observation", (), {"config_sha256": observed_config_hash,
            "executable_sha256": types.PINNED_EXECUTABLE_SHA256,
            "environment_sha256": "b" * 64, "startup_notifications": ()})()

    monkeypatch.setattr(prepare, "observe_public_metadata", synthetic_observation)
    # This contract tests admission serialization, not native file discovery.
    monkeypatch.setattr(prepare, "resolve_selected_executable",
                        lambda selected, *_args, **_kwargs: selected.resolve())
    result = await prepare._prepare(args, {
        "PATH": "/synthetic/bin", "HOME": str(private_tmp_path)})
    assert result["inference_verified"] == "not_run"
    assert result["account_entitlement"] == "not_assessed"
    assert result["quota_or_dollar_cap"] == "not_assessed"
    assert result["dialogue_sent_during_preparation"] is False
    assert result["content_authorized_for_live_text_entry"] is True
    assert "dialogue and relevant prior application context" in result["content_flow"]
    assert "Codex/OpenAI and TypeSafe/JEV" in result["content_flow"]
    assert "generated candidate to TypeSafe/JEV" in result["content_flow"]
    assert result["jev_billable"] is True and result["request_ceilings_are_dollar_caps"] is False
    assert result["usage_profile"] == "probe"
    assert result["request_ceilings_scope"] == (
        "per_app_invocation_in_memory; restart_starts_fresh_allowance")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    document = json.loads(output.read_text())
    assert set(document) == {"authorized", "route_kind", "usage_profile", "runtime", "limits"}
    assert document["usage_profile"] == "probe"
    assert document["route_kind"] == "public" and document["authorized"] is True
    assert document["runtime"]["development_context"] is None
    assert document["runtime"]["expected_config_sha256"] == observed_config_hash
    assert "CODEX_HOME" not in document["runtime"]["environment"]
    assert document["limits"] == {"codex_requests": 2, "session_turns": 2,
        "input_jev_requests": 3, "output_jev_requests": 3,
        "input_jev_timeout_seconds": 10, "output_jev_timeout_seconds": 10}
    from tools.live_dev import _read_admission
    admission = _read_admission(output)
    assert admission.authorized is True and admission.route_kind == "public"
    assert admission.runtime.expected_config_sha256 == observed_config_hash
    assert admission.runtime.development_context is None
    assert admission.limits.codex_requests == 2 and admission.limits.session_turns == 2
    assert admission.limits.input_jev_requests == 3 and admission.limits.output_jev_requests == 3
    assert admission.usage_profile == "probe"

    application_output = output_parent / "application-admission.json"
    application_args = prepare._parser().parse_args(["--prepare", "--usage-profile", "application",
        "--codex", str(executable), "--codex-home", str(codex_home),
        "--runtime-cwd", str(runtime_cwd), "--codex-requests", "100",
        "--session-turns", "100", "--input-jev-requests", "100",
        "--output-jev-requests", "100", "--input-jev-timeout-seconds", "10",
        "--output-jev-timeout-seconds", "10", "--probe-timeout-seconds", "10",
        "--confirm-policy-environment", "--authorize-codex-and-jev-content",
        "--write-admission", str(application_output)])
    application_result = await prepare._prepare(application_args, {
        "PATH": "/synthetic/bin", "HOME": str(private_tmp_path)})
    assert application_result["usage_profile"] == "application"
    application_document = json.loads(application_output.read_text())
    assert application_document["usage_profile"] == "application"
    assert application_document["limits"]["codex_requests"] == 100
    assert application_document["limits"]["session_turns"] == 100
    application_admission = _read_admission(application_output)
    assert application_admission.usage_profile == "application"
    assert application_admission.limits.input_jev_requests == 100


def test_application_profile_ceiling_validation_precedes_metadata_io(monkeypatch, capsys):
    called = []

    async def forbidden(*_args, **_kwargs):
        called.append("metadata")
        raise AssertionError("invalid profile ceiling must reject before metadata traffic")

    monkeypatch.setattr(prepare, "observe_public_metadata", forbidden)
    monkeypatch.setattr(sys, "argv", ["prepare_runtime_admission.py", "--prepare",
        "--usage-profile", "application", "--codex-requests", "101", "--session-turns", "100",
        "--input-jev-requests", "100", "--output-jev-requests", "100",
        "--input-jev-timeout-seconds", "10", "--output-jev-timeout-seconds", "10",
        "--probe-timeout-seconds", "10", "--confirm-policy-environment",
        "--authorize-codex-and-jev-content"])
    assert prepare.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked"
    assert result["reason"] == "usage_profile_request_ceiling_invalid"
    assert called == []


class StartupNoticeTransport(SyntheticMetadataTransport):
    def __init__(self, notices, **kwargs):
        super().__init__(**kwargs)
        self.notices = notices

    async def send(self, message):
        if message.get('method') == 'config/read':
            for notice in self.notices:
                await self.incoming.put(json.dumps(notice).encode() + b'\n')
        await super().send(message)


def _startup_notice(method='configWarning', **extra):
    return {'method': method, 'params': {'summary': 'synthetic local warning', 'details': None}, **extra}


@pytest.mark.asyncio
async def test_pinned_startup_warnings_are_discarded_before_mandatory_config_check():
    warning = _startup_notice(emittedAtMs=1791130000000)
    warning['params'].update(path='/synthetic/private/config.toml',
        range={'start': {'line': 1, 'column': 2}, 'end': {'line': 1, 'column': 4}})
    transport = StartupNoticeTransport([warning, _startup_notice('deprecationNotice')])
    observed = await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert observed.startup_notifications == (('configWarning', 1), ('deprecationNotice', 1))
    assert observed.config_sha256 == __import__('hashlib').sha256(canonical(_public_config())).hexdigest()
    assert [item.get('method') for item in transport.sent] == ['initialize', 'initialized', 'config/read']
    assert transport.closed
    assert 'synthetic local warning' not in repr(observed)
    assert '/synthetic/private' not in repr(observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["disabled", "connecting", "connected", "errored"])
@pytest.mark.parametrize("environment_id", ["omit", None, "synthetic-env"])
async def test_remote_control_startup_status_is_schema_validated_and_passively_discarded(
    status, environment_id,
):
    params = {"status": status, "serverName": "synthetic-host",
              "installationId": "synthetic-installation"}
    if environment_id != "omit":
        params["environmentId"] = environment_id
    notice = {"method": "remoteControl/status/changed", "params": params,
              "emittedAtMs": 1791130000000}
    transport = StartupNoticeTransport([notice])

    observed = await MetadataOnlyTransport(transport, _runtime()).observe(2)

    assert observed.startup_notifications == (("remoteControl/status/changed", 1),)
    assert observed.config_sha256 == __import__('hashlib').sha256(canonical(_public_config())).hexdigest()
    assert [item.get("method") for item in transport.sent] == ["initialize", "initialized", "config/read"]
    assert transport.closed
    assert "synthetic-host" not in repr(observed)
    assert "synthetic-installation" not in repr(observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"status": "unknown", "serverName": "h", "installationId": "i"},
    {"status": "connected", "serverName": "h", "installationId": "i", "environmentId": 3},
    {"status": "connected", "serverName": "h", "installationId": "i", "extra": "secret"},
    {"status": "connected", "installationId": "i"},
    {"status": "connected", "serverName": [], "installationId": "i"},
])
async def test_remote_control_startup_status_rejects_unpinned_schema(params):
    transport = StartupNoticeTransport([{
        "method": "remoteControl/status/changed", "params": params,
    }])
    with pytest.raises(types.CodexGenerationError, match="preflight_notification_invalid") as caught:
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert caught.value.safe_details["phase"] == "config/read"
    assert caught.value.safe_details["notification_method"] == "remoteControl/status/changed"
    assert transport.closed
    assert not any(item.get("method") in {"account/read", "thread/start", "turn/start"}
                   for item in transport.sent)


@pytest.mark.asyncio
async def test_remote_control_startup_status_obeys_shared_count_and_byte_limits():
    status = {"method": "remoteControl/status/changed", "params": {
        "status": "disabled", "serverName": "h", "installationId": "i",
        "environmentId": None}}
    transport = StartupNoticeTransport([_startup_notice()] * 15 + [status] * 2)
    with pytest.raises(types.CodexGenerationError, match="preflight_notification_limit"):
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert transport.closed

    oversized = {"method": "remoteControl/status/changed", "params": {
        "status": "disabled", "serverName": "x" * 33_000, "installationId": "i",
        "environmentId": None}}
    transport = StartupNoticeTransport([oversized])
    with pytest.raises(types.CodexGenerationError, match="preflight_notification_limit"):
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert transport.closed


@pytest.mark.asyncio
async def test_startup_warning_never_overrides_unsafe_effective_configuration():
    transport = StartupNoticeTransport([_startup_notice()], config={**_public_config(), 'web_search': 'live'})
    with pytest.raises(types.CodexGenerationError, match='codex_config_drift') as caught:
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert caught.value.safe_details['startup_notifications'] == {'configWarning': 1}
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'id': 42}, {'error': {'code': -1}}, {'result': {}}, {'jsonrpc': '1.0'},
    {'emittedAtMs': True}, {'emittedAtMs': 2**63}, {'emittedAtMs': 1.5},
    {'params': {'summary': 42}}, {'params': {'summary': 'x', 'details': {}}},
    {'params': {'summary': 'x', 'path': []}},
    {'params': {'summary': 'x', 'range': {'start': {'line': 0, 'column': 1}, 'end': {'line': 1, 'column': 2}}}},
    {'params': {'summary': 'x', 'range': {'start': {'line': True, 'column': 1}, 'end': {'line': 1, 'column': 2}}}},
    {'params': {'summary': 'x', 'range': {'start': {'line': 1, 'column': 1}}}},
    {'params': {'summary': 'x', 'arbitrary': 'synthetic-secret'}},
    {'method': 'unknown/notification'}, {'method': 'account/updated'},
    {'method': 'turn/started'}, {'method': 'deprecationNotice', 'params': {'summary': 'x', 'path': '/synthetic/private'}},
])
async def test_startup_notifications_fail_closed_on_requests_unknown_and_schema_changes(change):
    transport = StartupNoticeTransport([{**_startup_notice(), **change}])
    with pytest.raises(types.CodexGenerationError) as caught:
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert transport.closed
    assert 'synthetic-secret' not in str(caught.value) + json.dumps(getattr(caught.value, 'safe_details', {}))
    assert not any(item.get('method') in {'account/read', 'thread/start', 'turn/start'} for item in transport.sent)


@pytest.mark.asyncio
async def test_startup_notification_count_and_byte_budgets_are_exact_and_global():
    for notices, expected in [
        ([_startup_notice()] * 16, None),
        ([_startup_notice()] * 17, 'notification_limit'),
        ([{'method': 'configWarning', 'params': {'summary': 'x' * 33000}}], 'notification_limit'),
        ([{'method': 'configWarning', 'params': {'summary': 'x' * 24000}}] * 6, 'notification_limit'),
    ]:
        transport = StartupNoticeTransport(notices)
        if expected is None:
            observed = await MetadataOnlyTransport(transport, _runtime()).observe(2)
            assert observed.startup_notifications == (('configWarning', 16),)
        else:
            with pytest.raises(types.CodexGenerationError, match=expected):
                await MetadataOnlyTransport(transport, _runtime()).observe(2)
        assert transport.closed


@pytest.mark.asyncio
async def test_warning_before_initialize_response_remains_forbidden():
    transport = SyntheticMetadataTransport(unsolicited=_startup_notice())
    with pytest.raises(types.CodexGenerationError, match='preflight_notification'):
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert transport.closed and len(transport.sent) == 1


@pytest.mark.asyncio
async def test_accepted_warning_does_not_extend_deadline_or_mask_rpc_error():
    class NoResult(StartupNoticeTransport):
        async def send(self, message):
            if message.get('method') == 'config/read':
                self.sent.append(message)
                await self.incoming.put(json.dumps(_startup_notice()).encode() + b'\n')
                return
            await super().send(message)
    transport = NoResult([])
    with pytest.raises(types.CodexGenerationError, match='preflight_timeout') as caught:
        await MetadataOnlyTransport(transport, _runtime()).observe(.01)
    assert caught.value.safe_details['startup_notifications'] == {'configWarning': 1}
    assert transport.closed
    transport = StartupNoticeTransport([_startup_notice(), {'id': 2, 'error': {
        'code': -32600, 'message': 'synthetic-private-error'}}])
    with pytest.raises(types.CodexGenerationError, match='preflight_rpc_error') as caught:
        await MetadataOnlyTransport(transport, _runtime()).observe(2)
    assert caught.value.safe_details['numeric_error_code'] == -32600
    assert caught.value.safe_details['startup_notifications'] == {'configWarning': 1}
    assert 'synthetic-private-error' not in json.dumps(caught.value.safe_details)
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("body,check,field,kind,empty", [
 ({"config":_public_config(),"origins":{},"layers":None,"PRIVATE-FIELD-NAME":"PRIVATE-VALUE"},"config_body_fields",None,None,None),
 ({"config":_public_config(),"origins":[],"layers":None},"origins_type","origins","array",True),
 ({"config":_public_config(),"origins":{},"layers":"PRIVATE-VALUE"},"layers_type","layers","string",False),
 ({"config":None,"origins":{},"layers":None},"config_type","config","null",True),
 ({"config":{**_public_config(),"api_key":"PRIVATE-VALUE"},"origins":{}},"unsafe_config_field","api_key","string",False),
 ({"config":{**_public_config(),"nested":{"developer_instructions":"PRIVATE-VALUE"}},"origins":{}},"unsafe_config_field","developer_instructions","string",False),
 ({"config":{**_public_config(),"mcp_servers":{"PRIVATE-FIELD-NAME":{}}},"origins":{}},"mcp_empty",None,None,None),
 ({"config":{**_public_config(),"features":{**_public_config()["features"],"shell_tool":True}},"origins":{}},"features_disabled",None,None,None),
])
async def test_config_rejection_reports_exact_safe_check_without_values(body,check,field,kind,empty):
    from mira.adapters.generation.codex_support.preflight import PreflightDiagnosticError
    class Body(SyntheticMetadataTransport):
        async def send(self,message):
            if message.get("method")=="config/read":
                self.sent.append(message)
                await self.incoming.put(json.dumps({"id":2,"result":body}).encode()+b"\n")
            else:
                await super().send(message)
    transport=Body()
    with pytest.raises(PreflightDiagnosticError) as caught:
        await MetadataOnlyTransport(transport,_runtime()).observe(2)
    details=caught.value.safe_details
    assert details["phase"]=="config/read" and details["check_code"]==check
    if field is not None:
        assert details["field"]==field and details["value_kind"]==kind and details["value_empty"] is empty
    rendered=json.dumps(details)
    assert "PRIVATE-FIELD-NAME" not in rendered and "PRIVATE-VALUE" not in rendered
    assert transport.closed and [m["method"] for m in transport.sent]==["initialize","initialized","config/read"]


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [None, "", {}, []])
async def test_inactive_optional_instruction_and_credential_values_do_not_block_metadata(empty):
    from mira.adapters.generation.codex_support.preflight import _UNSAFE_CONFIG_KEYS
    config={**_public_config(), **{key:empty for key in _UNSAFE_CONFIG_KEYS}}
    transport=SyntheticMetadataTransport(config=config)
    observed=await MetadataOnlyTransport(transport,_runtime()).observe(2)
    assert observed.config_sha256==__import__('hashlib').sha256(canonical(config)).hexdigest()
    assert transport.closed and [x['method'] for x in transport.sent]==['initialize','initialized','config/read']

@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", [" ", "PRIVATE-VALUE", {"nested":"PRIVATE-VALUE"}, ["PRIVATE-VALUE"], False, 0])
async def test_nonempty_or_malformed_instruction_and_credential_values_remain_rejected(unsafe):
    from mira.adapters.generation.codex_support.preflight import _UNSAFE_CONFIG_KEYS, PreflightDiagnosticError
    for field in _UNSAFE_CONFIG_KEYS:
        transport=SyntheticMetadataTransport(config={**_public_config(), 'neutral':[{field:unsafe}]})
        with pytest.raises(PreflightDiagnosticError) as caught:
            await MetadataOnlyTransport(transport,_runtime()).observe(2)
        assert caught.value.safe_details['check_code']=='unsafe_config_field'
        assert caught.value.safe_details['field']==field
        assert 'PRIVATE-VALUE' not in json.dumps(caught.value.safe_details)
        assert transport.closed
