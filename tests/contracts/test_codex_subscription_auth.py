from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr
from tools import provider_login

from mira.adapters.auth.openai_codex import (
    CODEX_DEVICE_CODE_URL,
    CODEX_DEVICE_REDIRECT_URI,
    CODEX_DEVICE_TOKEN_URL,
    CODEX_DEVICE_VERIFICATION_URL,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_TOKEN_URL,
    CodexAuthError,
    CodexOAuthCredentials,
    CodexSessionStore,
    _Session,
)


def _fake_store(tmp_path: Path, handler, *, clock=lambda: 1_800_000_000.0,
                monotonic=time.monotonic, sleep=lambda _: None) -> CodexSessionStore:
    return CodexSessionStore(
        tmp_path / "mira" / "auth" / "openai-codex-session.json",
        transport=httpx.MockTransport(handler),
        clock=clock,
        monotonic=monotonic,
        sleep=sleep,
    )


def _json_response(request: httpx.Request, payload: dict, status=200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


def _synthetic_jwt(auth_claims: dict[str, str]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "https://api.openai.com/auth": auth_claims,
    }).encode()).decode().rstrip("=")
    return f"{header}.{payload}.synthetic-signature"


def _approved_flow():
    seen = []
    access_token = _synthetic_jwt({
        "chatgpt_account_id": "synthetic-account-id",
        "chatgpt_data_residency": "synthetic-data-region",
    })

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url == httpx.URL(CODEX_DEVICE_CODE_URL):
            assert json.loads(request.content) == {"client_id": CODEX_OAUTH_CLIENT_ID}
            return _json_response(request, {
                "device_auth_id": "device-private-test",
                "user_code": "TEST-CODE",
                "interval": 0,
            })
        if request.url == httpx.URL(CODEX_DEVICE_TOKEN_URL):
            assert json.loads(request.content) == {
                "device_auth_id": "device-private-test", "user_code": "TEST-CODE"
            }
            return _json_response(request, {
                "authorization_code": "auth-code-private-test",
                "code_verifier": "verifier-private-test",
            })
        if request.url == httpx.URL(CODEX_OAUTH_TOKEN_URL):
            form = parse_qs(request.content.decode())
            assert form == {
                "grant_type": ["authorization_code"],
                "client_id": [CODEX_OAUTH_CLIENT_ID],
                "code": ["auth-code-private-test"],
                "code_verifier": ["verifier-private-test"],
                "redirect_uri": [CODEX_DEVICE_REDIRECT_URI],
            }
            return _json_response(request, {
                "access_token": access_token,
                "refresh_token": "synthetic-refresh-one",
                "expires_in": 3600,
            })
        raise AssertionError("unexpected URL")

    return handler, seen, access_token


def test_device_login_uses_fixed_endpoints_and_saves_only_validated_session(tmp_path):
    handler, seen, access_token = _approved_flow()
    store = _fake_store(tmp_path, handler, clock=lambda: 1_700_000_000.0)
    shown = []
    store.begin_device_login(on_user_code=lambda url, code: shown.append((url, code)))

    assert [str(req.url) for req in seen] == [
        CODEX_DEVICE_CODE_URL, CODEX_DEVICE_TOKEN_URL, CODEX_OAUTH_TOKEN_URL
    ]
    assert shown == [(CODEX_DEVICE_VERIFICATION_URL, "TEST-CODE")]
    assert store.status() is True
    state = json.loads(store.path.read_text())
    assert state["access_token"] == access_token
    assert state["refresh_token"] == "synthetic-refresh-one"
    assert state["account_id"] == "synthetic-account-id"
    assert state["residency"] == "synthetic-data-region"
    assert "TEST-CODE" not in store.path.read_text()
    assert "device-private-test" not in store.path.read_text()
    assert "auth-code-private-test" not in store.path.read_text()
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store._backup_path.stat().st_mode & 0o777 == 0o600


def test_device_login_honors_pending_and_slow_down_without_logging_or_retry(tmp_path):
    polls = 0
    waits = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.url == httpx.URL(CODEX_DEVICE_CODE_URL):
            return _json_response(request, {
                "device_auth_id": "device", "user_code": "ONLY-IN-CLI", "interval": 2
            })
        if request.url == httpx.URL(CODEX_DEVICE_TOKEN_URL):
            polls += 1
            if polls == 1:
                return _json_response(request, {"error": {"code": "slow_down"}}, 429)
            if polls == 2:
                return _json_response(request, {"error": {"code": "deviceauth_authorization_pending"}}, 403)
            return _json_response(request, {"authorization_code": "code", "code_verifier": "verifier"})
        if request.url == httpx.URL(CODEX_OAUTH_TOKEN_URL):
            return _json_response(request, {
                "access_token": "access", "refresh_token": "refresh", "expires_in": 300
            })
        raise AssertionError("unexpected URL")

    store = _fake_store(tmp_path, handler, sleep=waits.append)
    store.begin_device_login(on_user_code=lambda _url, _code: None)
    assert polls == 3
    assert waits == [2.0, 7.0, 7.0]
    assert "ONLY-IN-CLI" not in store.path.read_text()
    assert "deviceauth_authorization_pending" not in store.path.read_text()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, {"error": {"code": "deviceauth_access_denied"}}, "device_code_denied"),
        (400, {"error": {"code": "deviceauth_expired"}}, "device_code_expired"),
        (500, {"error": {"code": "server_failure"}}, "device_code_poll_failed"),
    ],
)
def test_denied_expired_and_unknown_poll_errors_fail_closed(tmp_path, status, body, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(CODEX_DEVICE_CODE_URL):
            return _json_response(request, {
                "device_auth_id": "device", "user_code": "TEST", "interval": 1
            })
        if request.url == httpx.URL(CODEX_DEVICE_TOKEN_URL):
            return _json_response(request, body, status)
        raise AssertionError("no token exchange after a failed poll")

    store = _fake_store(tmp_path, handler)
    with pytest.raises(CodexAuthError) as caught:
        store.begin_device_login()
    assert caught.value.code == expected
    assert not store.path.exists()


def test_device_flow_timeout_and_cancel_leave_no_session_or_device_code(tmp_path):
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(CODEX_DEVICE_CODE_URL):
            return _json_response(request, {
                "device_auth_id": "device", "user_code": "SECRET-CODE", "interval": 1
            })
        raise AssertionError("timeout must happen before polling")

    elapsed = [0.0]
    timeout_store = _fake_store(
        tmp_path / "timeout",
        timeout_handler,
        monotonic=lambda: elapsed[0],
        sleep=lambda delay: elapsed.__setitem__(0, elapsed[0] + delay),
    )
    with pytest.raises(CodexAuthError, match="device_code_timeout"):
        timeout_store.begin_device_login(timeout_seconds=0.001)
    assert not timeout_store.path.exists()

    def cancel_sleep(_delay):
        raise KeyboardInterrupt

    cancel_store = _fake_store(tmp_path / "cancel", timeout_handler, sleep=cancel_sleep)
    with pytest.raises(KeyboardInterrupt):
        cancel_store.begin_device_login()
    assert not cancel_store.path.exists()


def test_login_rejects_redirect_without_following_or_sending_any_secret_elsewhere(tmp_path):
    seen_hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        if request.url == httpx.URL(CODEX_DEVICE_CODE_URL):
            return _json_response(request, {
                "device_auth_id": "device", "user_code": "TEST", "interval": 1
            })
        if request.url == httpx.URL(CODEX_DEVICE_TOKEN_URL):
            return _json_response(request, {
                "authorization_code": "synthetic-code", "code_verifier": "synthetic-verifier"
            })
        if request.url == httpx.URL(CODEX_OAUTH_TOKEN_URL):
            assert b"synthetic-code" in request.content
            assert b"synthetic-verifier" in request.content
            return httpx.Response(
                302,
                headers={"Location": "https://attacker.invalid/collect"},
                request=request,
            )
        raise AssertionError("unexpected URL")

    store = _fake_store(tmp_path, handler)
    with pytest.raises(CodexAuthError) as caught:
        store.begin_device_login()
    assert caught.value.code == "oauth_redirect_rejected"
    assert seen_hosts == ["auth.openai.com", "auth.openai.com", "auth.openai.com"]
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_expired_refresh_rotates_tokens_and_persists_before_return(tmp_path):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == httpx.URL(CODEX_OAUTH_TOKEN_URL)
        assert parse_qs(request.content.decode()) == {
            "grant_type": ["refresh_token"],
            "client_id": [CODEX_OAUTH_CLIENT_ID],
            "refresh_token": ["old-refresh"],
        }
        return _json_response(request, {
            "access_token": _synthetic_jwt({
                "chatgpt_account_id": "refreshed-account-id",
                "chatgpt_compute_residency": "synthetic-compute-region",
            }),
            "refresh_token": "rotated-refresh",
            "expires_in": 7200,
        })

    store = _fake_store(tmp_path, handler, clock=lambda: 1_700_000_000.0)
    store._write_session(_Session("old-access", "old-refresh", 1_699_999_000, 1))
    credentials = await store.get_credentials()
    assert credentials.access_token == SecretStr(json.loads(store.path.read_text())["access_token"])
    assert credentials.account_id == "refreshed-account-id"
    assert credentials.residency == "synthetic-compute-region"
    assert repr(credentials) == "CodexOAuthCredentials()"
    state = json.loads(store.path.read_text())
    backup = json.loads(store._backup_path.read_text())
    assert state["account_id"] == "refreshed-account-id"
    assert state["residency"] == "synthetic-compute-region"
    assert state["refresh_token"] == "rotated-refresh"
    assert state["expires_at"] == 1_700_007_200.0
    assert backup == state
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_concurrent_expired_calls_share_single_cross_process_refresh(tmp_path):
    lock = threading.Lock()
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        with lock:
            request_count += 1
        time.sleep(0.05)
        return _json_response(request, {
            "access_token": "fresh-access", "refresh_token": "fresh-refresh", "expires_in": 3600
        })

    store = _fake_store(tmp_path, handler, clock=lambda: 1_700_000_000.0)
    store._write_session(_Session("old-access", "old-refresh", 1_699_999_000, 1))

    first, second = await asyncio.gather(store.get_credentials(), store.get_credentials())
    assert request_count == 1
    assert first.access_token == second.access_token == SecretStr("fresh-access")
    assert json.loads(store.path.read_text())["refresh_token"] == "fresh-refresh"


@pytest.mark.asyncio
async def test_signout_waits_for_inflight_refresh_and_cannot_be_resurrected(tmp_path):
    refresh_started = threading.Event()
    finish_refresh = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(CODEX_OAUTH_TOKEN_URL)
        refresh_started.set()
        assert finish_refresh.wait(2), "refresh test barrier was not released"
        return _json_response(request, {
            "access_token": "late-access", "refresh_token": "late-refresh", "expires_in": 3600
        })

    store = _fake_store(tmp_path, handler, clock=lambda: 1_700_000_000.0)
    store._write_session(_Session("old-access", "old-refresh", 1_699_999_000, 1))

    lookup = asyncio.create_task(store.get_credentials())
    assert await asyncio.to_thread(refresh_started.wait, 1)
    logout_requested = threading.Event()

    def logout():
        logout_requested.set()
        store.sign_out()

    signout = asyncio.create_task(asyncio.to_thread(logout))
    assert await asyncio.to_thread(logout_requested.wait, 1)
    finish_refresh.set()
    await lookup
    await signout
    assert store.status() is False
    assert json.loads(store.path.read_text())["state"] == "signed_out"


@pytest.mark.asyncio
async def test_bad_refresh_does_not_start_another_grant_or_false_auth_state(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(401, json={"error": "invalid_grant"}, request=request)

    store = _fake_store(tmp_path, handler, clock=lambda: 1_700_000_000.0)
    store._write_session(_Session("expired-access", "refresh", 1_699_999_000, 1))
    with pytest.raises(CodexAuthError) as caught:
        await store.get_credentials()
    assert caught.value.code == "oauth_refresh_failed"
    assert calls == [CODEX_OAUTH_TOKEN_URL]
    assert store.status() is True
    assert json.loads(store.path.read_text())["refresh_token"] == "refresh"


@pytest.mark.asyncio
async def test_invalid_store_permissions_and_recoverable_local_signout(tmp_path):
    store = _fake_store(tmp_path, lambda _request: pytest.fail("no request"))
    assert store.status() is False
    store._write_session(_Session("secret-access-value", "secret-refresh-value", 1.0, 1))
    assert store.status() is True
    store.sign_out()
    assert store.status() is False
    with pytest.raises(CodexAuthError, match="codex_subscription_login_required"):
        await store.get_credentials()
    assert store._backup_path.exists()
    store.restore_backup()
    assert store.status() is True
    store.discard_local_session()
    assert not store.path.exists()
    assert not store._backup_path.exists()

    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json")
    os.chmod(store.path, 0o600)
    with pytest.raises(CodexAuthError, match="auth_store_invalid"):
        store.status()
    if os.name != "nt":
        store.path.write_text(json.dumps({"version": 1, "state": "authenticated"}))
        os.chmod(store.path, 0o644)
        with pytest.raises(CodexAuthError, match="auth_store_file_not_private"):
            store.status()


def test_store_refuses_checkout_paths_before_creating_anything():
    checkout = Path(__file__).resolve().parents[2]
    target = checkout / "not-created" / "openai-codex-session.json"
    store = CodexSessionStore(target, transport=httpx.MockTransport(
        lambda _request: pytest.fail("no request")
    ))
    with pytest.raises(CodexAuthError, match="auth_store_must_be_outside_checkout"):
        store.status()
    assert not target.parent.exists()


def test_auth_errors_and_credential_repr_do_not_disclose_token_values():
    bundle = CodexOAuthCredentials(SecretStr("never-print-this"), "account-private", "region-private")
    assert "never-print-this" not in repr(bundle)
    assert "account-private" not in repr(bundle)
    assert "region-private" not in repr(bundle)
    error = CodexAuthError("oauth_refresh_failed")
    assert "never-print-this" not in str(error)


def test_cli_store_override_is_read_only_and_error_codes_are_allowlisted(tmp_path, capsys):
    store_path = tmp_path / "custom-mira-session.json"
    assert provider_login.main(["--auth-store", str(store_path), "status"]) == 0
    output = capsys.readouterr().out
    assert "signed out" in output
    assert "does not verify provider validity" in output
    assert not store_path.exists()
    assert not (tmp_path / "custom-mira-session.json.lock").exists()
    assert provider_login._safe_auth_error_code(CodexAuthError("device_code_denied")) == "device_code_denied"
    assert provider_login._safe_auth_error_code(CodexAuthError("sensitive-remote-value")) == "auth_operation_failed"
