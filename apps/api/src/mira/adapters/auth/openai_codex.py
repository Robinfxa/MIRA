"""MIRA-owned, opt-in Codex subscription OAuth session lifecycle.

This speaks only to the fixed auth.openai.com device/token endpoints. It never
discovers, reads, imports, or writes Codex CLI/Hermes credential stores.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import os
import socket
import ssl
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Protocol
from urllib.parse import urlsplit

import httpcore
import httpx
from pydantic import SecretStr

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_AUTH_BASE_URL = "https://auth.openai.com"
CODEX_DEVICE_CODE_URL = (
    "https://auth.openai.com/api/accounts/deviceauth/usercode"
)
CODEX_DEVICE_TOKEN_URL = (
    "https://auth.openai.com/api/accounts/deviceauth/token"
)
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device"
CODEX_DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"

REFRESH_SKEW_SECONDS = 120
DEFAULT_DEVICE_FLOW_TIMEOUT_SECONDS = 900
MAX_AUTH_RESPONSE_BYTES = 1_048_576
MAX_TOKEN_CHARS = 65_536
_STORE_VERSION = 1
_LOCK_TIMEOUT_SECONDS = 30.0
__all__ = [
    "CODEX_AUTH_BASE_URL",
    "CODEX_DEVICE_CODE_URL",
    "CODEX_DEVICE_TOKEN_URL",
    "CODEX_DEVICE_VERIFICATION_URL",
    "CODEX_OAUTH_CLIENT_ID",
    "CODEX_OAUTH_TOKEN_URL",
    "CodexAuthError",
    "CodexCredentialSource",
    "CodexOAuthCredentialSource",
    "CodexOAuthCredentials",
    "CodexSessionStore",
    "default_session_path",
]


class CodexAuthError(RuntimeError):
    """Safe, fixed-code auth error; messages never include server text or secrets."""

    def __init__(self, code: str, *, diagnostic: dict[str, object] | None = None):
        self.code = code
        self._diagnostic = diagnostic
        super().__init__(code)

    def safe_diagnostic(self) -> dict[str, object] | None:
        """Return only fixed labels and bounded integers, never exception text."""
        if self._diagnostic is None:
            return None
        return _sanitize_network_diagnostic(self._diagnostic)


def _known_exception_types() -> list[tuple[type[BaseException], str, str]]:
    # Labels are constants, never arbitrary class names or exception messages.
    known = [
        (ssl.SSLCertVerificationError, "ssl.SSLCertVerificationError", "tls_certificate"),
        (ssl.SSLError, "ssl.SSLError", "tls"),
        (socket.gaierror, "socket.gaierror", "dns"),
        (ConnectionRefusedError, "builtins.ConnectionRefusedError", "connection_refused"),
        (ConnectionResetError, "builtins.ConnectionResetError", "connection_reset"),
        (TimeoutError, "builtins.TimeoutError", "timeout"),
    ]
    names = (
        ("ProxyError", "proxy"), ("ConnectTimeout", "connect_timeout"),
        ("ReadTimeout", "read_timeout"), ("WriteTimeout", "write_timeout"),
        ("PoolTimeout", "pool_timeout"), ("ConnectError", "connect"),
        ("ReadError", "read"), ("WriteError", "write"), ("CloseError", "close"),
        ("RemoteProtocolError", "remote_protocol"),
        ("LocalProtocolError", "local_protocol"),
        ("UnsupportedProtocol", "unsupported_protocol"),
        ("DecodingError", "response_decoding"), ("RequestError", "request"),
    )
    for module, prefix in ((httpx, "httpx"), (httpcore, "httpcore")):
        for name, category in names:
            cls = getattr(module, name, None)
            if isinstance(cls, type) and issubclass(cls, BaseException):
                known.append((cls, prefix + "." + name, category))
    known.extend(((OSError, "builtins.OSError", "os_error"),
                  (ValueError, "builtins.ValueError", "value_error"),
                  (RuntimeError, "builtins.RuntimeError", "runtime_error")))
    return known


def _safe_exception_fields(error: BaseException) -> dict[str, object]:
    """Inspect bounded cause/context chains without reading args, request or text."""
    chain: list[dict[str, object]] = []
    categories: list[str] = []
    seen: set[int] = set()
    pending = [error]
    while pending and len(chain) < 16:
        item = pending.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        label, category = "unrecognized_exception", "unrecognized"
        for cls, known_label, known_category in _known_exception_types():
            if isinstance(item, cls):
                label, category = known_label, known_category
                break
        entry: dict[str, object] = {"type": label}
        if isinstance(item, OSError):
            number = item.errno
            if type(number) is int and -65535 <= number <= 65535:
                entry["errno"] = number
        if isinstance(item, ssl.SSLCertVerificationError):
            number = getattr(item, "verify_code", None)
            if type(number) is int and 0 <= number <= 65535:
                entry["ssl_verify_code"] = number
        chain.append(entry)
        if category not in categories:
            categories.append(category)
        for linked in (item.__cause__, item.__context__):
            if isinstance(linked, BaseException) and id(linked) not in seen:
                pending.append(linked)
    return {"categories": categories, "exception_chain": chain,
            "chain_truncated": bool(pending)}


def _sanitize_network_diagnostic(value: object) -> dict[str, object]:
    # Validate again at the display boundary; no caller-controlled strings escape.
    value = value if type(value) is dict else {}
    operations = {"device_code_request", "device_code_poll", "token_exchange", "token_refresh"}
    phases = {"client_initialization", "request_headers", "response_body",
              "response_reconstruction", "response_close", "client_close"}
    result: dict[str, object] = {"diagnostic": "mira_oauth_failure_v1", "category": "exception"}
    for key, allowed in (("operation", operations), ("phase", phases)):
        label = value.get(key)
        result[key] = label if type(label) is str and label in allowed else "unknown"
    status = value.get("http_status")
    if type(status) is int and 100 <= status <= 599:
        result["http_status"] = status
    metadata_labels = {
        "content_encoding": {"none", "identity", "gzip", "deflate", "br", "zstd", "multiple", "other"},
        "content_length_bucket": {"empty", "small_1_4096", "medium_4097_65536",
                                  "large_65537_1048576", "over_limit", "unknown"},
        "decoded_bytes_bucket": {"empty", "small_1_4096", "medium_4097_65536",
                                 "large_65537_1048576", "over_limit", "unknown"},
    }
    for key, allowed in metadata_labels.items():
        if key in value:
            label = value.get(key)
            result[key] = label if type(label) is str and label in allowed else "unknown"
    known = _known_exception_types()
    labels = {label for _, label, _ in known} | {"unrecognized_exception"}
    categories = {category for _, _, category in known} | {"unrecognized"}
    raw_categories = value.get("categories")
    result["categories"] = [item for item in raw_categories[:16]
                            if type(item) is str and item in categories
                            ] if type(raw_categories) is list else []
    raw_chain = value.get("exception_chain")
    chain: list[dict[str, object]] = []
    if type(raw_chain) is list:
        for entry in raw_chain[:16]:
            if type(entry) is not dict:
                continue
            label = entry.get("type")
            safe: dict[str, object] = {
                "type": label if type(label) is str and label in labels else "unrecognized_exception"
            }
            for key, minimum in (("errno", -65535), ("ssl_verify_code", 0)):
                number = entry.get(key)
                if type(number) is int and minimum <= number <= 65535:
                    safe[key] = number
            chain.append(safe)
    result["exception_chain"] = chain
    result["chain_truncated"] = value.get("chain_truncated") is True
    return result


def _safe_content_encoding(value: object) -> str:
    """Classify the encoding field; never return an arbitrary header value."""
    if value is None or value == "":
        return "none"
    if type(value) is not str or len(value) > 128:
        return "other"
    normalized = value.strip().lower()
    if normalized in {"identity", "gzip", "deflate", "br", "zstd"}:
        return normalized
    return "multiple" if "," in normalized else "other"


def _byte_count_bucket(value: object) -> str:
    if type(value) is not int or value < 0:
        return "unknown"
    if value == 0:
        return "empty"
    if value <= 4096:
        return "small_1_4096"
    if value <= 65536:
        return "medium_4097_65536"
    if value <= MAX_AUTH_RESPONSE_BYTES:
        return "large_65537_1048576"
    return "over_limit"


def _safe_content_length_bucket(value: object) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 12
            or not value.isascii() or not value.isdecimal()):
        return "unknown"
    return _byte_count_bucket(int(value))


def _auth_operation(url: str, data: dict[str, str] | None) -> str:
    if url == CODEX_DEVICE_CODE_URL:
        return "device_code_request"
    if url == CODEX_DEVICE_TOKEN_URL:
        return "device_code_poll"
    if url == CODEX_OAUTH_TOKEN_URL and data is not None:
        if data.get("grant_type") == "authorization_code":
            return "token_exchange"
        if data.get("grant_type") == "refresh_token":
            return "token_refresh"
    return "unknown"


@dataclass(frozen=True, slots=True)
class CodexOAuthCredentials:
    """Opaque in-process credentials for a selected direct subscription route."""

    access_token: SecretStr = field(repr=False)
    account_id: str | None = field(default=None, repr=False)
    residency: str | None = field(default=None, repr=False)


class CodexCredentialSource(Protocol):
    async def get_credentials(self) -> CodexOAuthCredentials: ...


@dataclass(frozen=True, slots=True)
class _Session:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float
    revision: int
    account_id: str | None = field(default=None, repr=False)
    residency: str | None = field(default=None, repr=False)


def default_session_path() -> Path:
    """Return MIRA's private app-owned location without touching it."""
    if os.name == "nt":
        root = Path.home() / "AppData" / "Local"
        return root / "MIRA" / "auth" / "openai-codex-session.json"
    if sys_platform_is_macos():
        return Path.home() / "Library" / "Application Support" / "MIRA" / "auth" / "openai-codex-session.json"
    return Path.home() / ".local" / "share" / "mira" / "auth" / "openai-codex-session.json"


def sys_platform_is_macos() -> bool:
    # Kept local so importing this module has no filesystem or network side effects.
    import sys

    return sys.platform == "darwin"


def _object_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _json_object(raw: bytes, error_code: str) -> dict[str, object]:
    if len(raw) > MAX_AUTH_RESPONSE_BYTES:
        raise CodexAuthError(error_code)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise CodexAuthError(error_code) from None
    if type(value) is not dict:
        raise CodexAuthError(error_code)
    return value


def _assert_outside_checkout(path: Path) -> None:
    try:
        checkout_root = Path(__file__).resolve().parents[6]
        candidate = path.resolve()
    except (OSError, IndexError):
        raise CodexAuthError("auth_store_path_invalid") from None
    if candidate.is_relative_to(checkout_root):
        raise CodexAuthError("auth_store_must_be_outside_checkout")


def _private_dir(path: Path) -> None:
    _assert_outside_checkout(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise CodexAuthError("auth_store_path_invalid")
    if os.name != "nt":
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise CodexAuthError("auth_store_directory_not_private")


@contextlib.contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """Cross-process advisory lock; lock file is owned by this MIRA auth directory."""
    _private_dir(lock_path.parent)
    if lock_path.is_symlink():
        raise CodexAuthError("auth_store_path_invalid")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise CodexAuthError("auth_store_lock_timeout") from None
                    time.sleep(0.05)
        else:
            import fcntl

            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise CodexAuthError("auth_store_lock_timeout") from None
                    time.sleep(0.05)
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_private_json(path: Path, payload: dict[str, object]) -> None:
    """Atomically write one private JSON file next to its destination."""
    _private_dir(path.parent)
    if path.is_symlink():
        raise CodexAuthError("auth_store_path_invalid")
    encoded = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
        if os.name != "nt":
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()
        raise


def _session_payload(session: _Session) -> dict[str, object]:
    return {
        "version": _STORE_VERSION,
        "state": "authenticated",
        "revision": session.revision,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at,
        "account_id": session.account_id,
        "residency": session.residency,
    }


def _read_session(path: Path) -> _Session | None:
    _assert_outside_checkout(path)
    if path.is_symlink():
        raise CodexAuthError("auth_store_path_invalid")
    if not path.exists():
        return None
    if os.name != "nt" and (path.stat().st_mode & 0o077):
        raise CodexAuthError("auth_store_file_not_private")
    try:
        raw = path.read_bytes()
    except OSError:
        raise CodexAuthError("auth_store_unreadable") from None
    if len(raw) > MAX_AUTH_RESPONSE_BYTES:
        raise CodexAuthError("auth_store_invalid")
    try:
        payload = _json_object(raw, "auth_store_invalid")
    except CodexAuthError:
        raise
    if payload.get("version") != _STORE_VERSION:
        raise CodexAuthError("auth_store_version_unsupported")
    state = payload.get("state")
    if state == "signed_out":
        return None
    if state != "authenticated":
        raise CodexAuthError("auth_store_invalid")
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expiry = payload.get("expires_at")
    revision = payload.get("revision")
    account_id = payload.get("account_id")
    residency = payload.get("residency")
    if (
        type(access) is not str
        or not access
        or len(access) > MAX_TOKEN_CHARS
        or type(refresh) is not str
        or not refresh
        or len(refresh) > MAX_TOKEN_CHARS
        or type(expiry) not in (int, float)
        or not math.isfinite(float(expiry))
        or type(revision) is not int
        or revision < 1
        or (account_id is not None and type(account_id) is not str)
        or (residency is not None and type(residency) is not str)
        or (isinstance(account_id, str) and (len(account_id) > 256 or any(ord(c) < 0x20 for c in account_id)))
        or (isinstance(residency, str) and (len(residency) > 256 or any(ord(c) < 0x20 for c in residency)))
    ):
        raise CodexAuthError("auth_store_invalid")
    return _Session(access, refresh, float(expiry), revision, account_id, residency)


def _token_fields(payload: dict[str, object]) -> tuple[str, str | None, float]:
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires = payload.get("expires_in")
    if (
        type(access) is not str
        or not access
        or len(access) > MAX_TOKEN_CHARS
        or any(ord(char) < 0x20 for char in access)
        or (refresh is not None and type(refresh) is not str)
        or (isinstance(refresh, str) and (
            not refresh or len(refresh) > MAX_TOKEN_CHARS or any(ord(char) < 0x20 for char in refresh)
        ))
        or type(expires) not in (int, float)
        or not math.isfinite(float(expires))
        or float(expires) <= 0
    ):
        raise CodexAuthError("oauth_token_response_invalid")
    return access, refresh, float(expires)


def _jwt_account_metadata(access_token: str) -> tuple[str | None, str | None]:
    """Decode optional request metadata from the Codex access-token JWT.

    This deliberately does not validate identity or the JWT signature. OpenAI's
    backend remains the token validator; these two optional values only support
    the account/residency headers described in the pinned Hermes source review.
    """
    try:
        parts = access_token.split(".")
        if len(parts) < 2 or not parts[1]:
            return None, None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        claims = _json_object(payload_bytes, "oauth_token_metadata_invalid")
        auth_claims = claims.get("https://api.openai.com/auth")
        if type(auth_claims) is not dict:
            return None, None
        account = auth_claims.get("chatgpt_account_id")
        if (
            type(account) is not str
            or not account.strip()
            or len(account) > 256
            or any(ord(char) < 0x20 for char in account)
        ):
            account_id = None
        else:
            account_id = account.strip()
        residency = auth_claims.get("chatgpt_data_residency")
        if not (isinstance(residency, str) and residency.strip()):
            residency = auth_claims.get("chatgpt_compute_residency")
        if (
            type(residency) is not str
            or not residency.strip()
            or len(residency) > 256
            or any(ord(char) < 0x20 for char in residency)
        ):
            residency_value = None
        else:
            residency_value = residency.strip()
        return account_id, residency_value
    except (CodexAuthError, ValueError, TypeError, RecursionError):
        return None, None


def _fixed_auth_url(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname == "auth.openai.com"
        and parts.port in (None, 443)
        and not parts.username
        and not parts.password
    )


def _response_payload(response: httpx.Response, code: str) -> dict[str, object]:
    if 300 <= response.status_code < 400:
        raise CodexAuthError("oauth_redirect_rejected")
    if response.status_code != 200:
        raise CodexAuthError(code)
    raw = response.content
    return _json_object(raw, code)


class CodexSessionStore:
    """MIRA's separate private store, refresh lock and device-code OAuth client."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.path = Path(path) if path is not None else default_session_path()
        self._transport = transport
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        self._backup_path = self.path.with_name(self.path.name + ".bak")

    def _client(self) -> httpx.Client:
        if self._transport is not None:
            return httpx.Client(
                transport=self._transport,
                timeout=httpx.Timeout(15.0),
                follow_redirects=False,
            )
        return httpx.Client(timeout=httpx.Timeout(15.0), follow_redirects=False)

    def _post_json(
        self, url: str, *, json_body: dict[str, object], data: dict[str, str] | None = None
    ) -> httpx.Response:
        if not _fixed_auth_url(url):
            raise CodexAuthError("oauth_endpoint_rejected")
        # Auth JSON is small; explicitly avoid optional compression negotiation.
        # A server may still compress: iter_bytes below decodes exactly once.
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if data is None:
            headers["Content-Type"] = "application/json"
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        phase = "client_initialization"
        http_status: int | None = None
        content_encoding = "none"
        content_length_bucket = "unknown"
        size = 0
        try:
            with self._client() as client:
                request_args: dict[str, object] = {"headers": headers}
                if data is None:
                    request_args["json"] = json_body
                else:
                    request_args["data"] = data
                phase = "request_headers"
                with client.stream("POST", url, **request_args) as streamed:
                    http_status = streamed.status_code
                    content_encoding = _safe_content_encoding(streamed.headers.get("content-encoding"))
                    content_length_bucket = _safe_content_length_bucket(streamed.headers.get("content-length"))
                    phase = "response_body"
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in streamed.iter_bytes():
                        size += len(chunk)
                        if size > MAX_AUTH_RESPONSE_BYTES:
                            raise CodexAuthError("oauth_response_too_large")
                        chunks.append(chunk)
                    phase = "response_reconstruction"
                    # iter_bytes has already decoded Content-Encoding. Retaining
                    # it here would decode the JSON a second time. Framing must
                    # also describe the decoded body, not the wire representation.
                    decoded_headers = streamed.headers.copy()
                    for field_name in ("content-encoding", "content-length", "transfer-encoding"):
                        decoded_headers.pop(field_name, None)
                    response = httpx.Response(
                        streamed.status_code,
                        headers=decoded_headers,
                        content=b"".join(chunks),
                        request=streamed.request,
                    )
                    phase = "response_close"
                phase = "client_close"
        except CodexAuthError:
            raise
        except (httpx.RequestError, OSError, ValueError) as exc:
            diagnostic = {
                "operation": _auth_operation(url, data), "phase": phase,
                "http_status": http_status, "content_encoding": content_encoding,
                "content_length_bucket": content_length_bucket,
                "decoded_bytes_bucket": _byte_count_bucket(size), **_safe_exception_fields(exc),
            }
            raise CodexAuthError("oauth_network_error", diagnostic=diagnostic) from None
        if 300 <= response.status_code < 400:
            raise CodexAuthError("oauth_redirect_rejected")
        return response

    def begin_device_login(
        self,
        *,
        timeout_seconds: float = DEFAULT_DEVICE_FLOW_TIMEOUT_SECONDS,
        on_user_code: Callable[[str, str], None] | None = None,
    ) -> None:
        """Run a user-started device grant and persist only after token validation.

        `on_user_code` is the CLI presentation hook. The code is held only in this
        call's memory and is never logged or included in an exception.
        """
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        start = self._post_json(
            CODEX_DEVICE_CODE_URL,
            json_body={"client_id": CODEX_OAUTH_CLIENT_ID},
        )
        start_data = _response_payload(start, "device_code_request_failed")
        device_auth_id = start_data.get("device_auth_id")
        user_code = start_data.get("user_code")
        interval_raw = start_data.get("interval")
        if type(interval_raw) is str:
            try:
                interval = float(interval_raw)
            except ValueError:
                raise CodexAuthError("device_code_response_invalid") from None
        elif type(interval_raw) in (int, float):
            interval = float(interval_raw)
        else:
            raise CodexAuthError("device_code_response_invalid")
        if (
            type(device_auth_id) is not str
            or not device_auth_id
            or len(device_auth_id) > 4096
            or any(ord(char) < 0x20 for char in device_auth_id)
            or type(user_code) is not str
            or not user_code
            or len(user_code) > 128
            or any(ord(char) < 0x20 for char in user_code)
            or not math.isfinite(interval)
            or interval < 0
        ):
            raise CodexAuthError("device_code_response_invalid")
        poll_interval = max(1.0, interval)
        if on_user_code is not None:
            on_user_code(CODEX_DEVICE_VERIFICATION_URL, user_code)
        deadline = self._monotonic() + timeout_seconds
        authorization_code: str | None = None
        code_verifier: str | None = None
        while self._monotonic() < deadline:
            self._sleep(min(poll_interval, max(0.0, deadline - self._monotonic())))
            if self._monotonic() >= deadline:
                break
            poll = self._post_json(
                CODEX_DEVICE_TOKEN_URL,
                json_body={"device_auth_id": device_auth_id, "user_code": user_code},
            )
            if poll.status_code == 200:
                poll_data = _response_payload(poll, "device_code_poll_failed")
                code = poll_data.get("authorization_code")
                verifier = poll_data.get("code_verifier")
                if (
                    type(code) is not str
                    or not code
                    or len(code) > 16_384
                    or any(ord(char) < 0x20 for char in code)
                    or type(verifier) is not str
                    or not verifier
                    or len(verifier) > 16_384
                    or any(ord(char) < 0x20 for char in verifier)
                ):
                    raise CodexAuthError("device_code_response_invalid")
                authorization_code, code_verifier = code, verifier
                break
            error_code = _oauth_error_code(poll)
            if error_code in {"deviceauth_authorization_pending", "authorization_pending"}:
                continue
            if error_code == "slow_down":
                poll_interval += 5.0
                continue
            if error_code in {"access_denied", "deviceauth_access_denied", "authorization_denied"}:
                raise CodexAuthError("device_code_denied")
            if error_code in {"expired_token", "deviceauth_expired", "authorization_expired"}:
                raise CodexAuthError("device_code_expired")
            if poll.status_code in {403, 404} and error_code is None:
                # The pinned device endpoint uses these statuses for an unapproved code.
                continue
            raise CodexAuthError("device_code_poll_failed")
        if authorization_code is None or code_verifier is None:
            raise CodexAuthError("device_code_timeout")
        exchange = self._post_json(
            CODEX_OAUTH_TOKEN_URL,
            json_body={},
            data={
                "grant_type": "authorization_code",
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "code": authorization_code,
                "code_verifier": code_verifier,
                "redirect_uri": CODEX_DEVICE_REDIRECT_URI,
            },
        )
        exchange_data = _response_payload(exchange, "oauth_exchange_failed")
        access, refresh, expires_in = _token_fields(exchange_data)
        if not refresh:
            raise CodexAuthError("oauth_token_response_invalid")
        account_id, residency = _jwt_account_metadata(access)
        self._write_session(
            _Session(access, refresh, self._clock() + expires_in, 1, account_id, residency)
        )

    async def get_credentials(self) -> CodexOAuthCredentials:
        """Return a current MIRA-owned token; refresh only this explicit session."""
        return await asyncio.to_thread(self._get_credentials_sync)

    def _get_credentials_sync(self) -> CodexOAuthCredentials:
        with _file_lock(self._lock_path):
            session = _read_session(self.path)
            if session is None:
                raise CodexAuthError("codex_subscription_login_required")
            if session.expires_at > self._clock() + REFRESH_SKEW_SECONDS:
                return _credentials(session)
            response = self._post_json(
                CODEX_OAUTH_TOKEN_URL,
                json_body={},
                data={
                    "grant_type": "refresh_token",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "refresh_token": session.refresh_token,
                },
            )
            refreshed = _response_payload(response, "oauth_refresh_failed")
            access, rotated_refresh, expires_in = _token_fields(refreshed)
            refresh = rotated_refresh or session.refresh_token
            account_id, residency = _jwt_account_metadata(access)
            updated = _Session(
                access,
                refresh,
                self._clock() + expires_in,
                session.revision + 1,
                account_id,
                residency,
            )
            self._write_session_unlocked(updated)
            return _credentials(updated)

    def status(self) -> bool:
        """Read only MIRA's active store; never refresh or discover credentials."""
        # Atomic replacement keeps the primary file complete while we read it;
        # status must not create even a lock file or touch the provider.
        return _read_session(self.path) is not None

    def sign_out(self) -> None:
        """Disable the app-owned session locally; does not revoke provider tokens."""
        with _file_lock(self._lock_path):
            current = _read_session(self.path)
            revision = (current.revision + 1) if current is not None else 1
            tombstone = {
                "version": _STORE_VERSION,
                "state": "signed_out",
                "revision": revision,
            }
            _atomic_private_json(self.path, tombstone)

    def restore_backup(self) -> None:
        """Explicitly restore a recoverable MIRA backup; never auto-fallback to it."""
        with _file_lock(self._lock_path):
            session = _read_session(self._backup_path)
            if session is None:
                raise CodexAuthError("auth_backup_unavailable")
            _atomic_private_json(self.path, _session_payload(session))

    def discard_local_session(self) -> None:
        """Permanently remove only this MIRA session and its backup from local disk."""
        with _file_lock(self._lock_path):
            for path in (self.path, self._backup_path):
                if path.is_symlink():
                    raise CodexAuthError("auth_store_path_invalid")
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()

    def _write_session(self, session: _Session) -> None:
        with _file_lock(self._lock_path):
            self._write_session_unlocked(session)

    def _write_session_unlocked(self, session: _Session) -> None:
        payload = _session_payload(session)
        # Stage the validated new token pair in the private backup first. If the
        # process stops before the main replace, an explicit restore can recover it.
        _atomic_private_json(self._backup_path, payload)
        _atomic_private_json(self.path, payload)


class CodexOAuthCredentialSource:
    """Convenience credential source for direct-provider composition.

    Construction is side-effect free. A store file is read, and an expired token
    may be refreshed, only on an explicit call to ``get_credentials``.
    """

    def __init__(
        self,
        store_path: Path | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = CodexSessionStore(
            store_path, transport=transport, clock=clock, monotonic=monotonic, sleep=sleep
        )

    async def get_credentials(self) -> CodexOAuthCredentials:
        return await self._store.get_credentials()


def _credentials(session: _Session) -> CodexOAuthCredentials:
    return CodexOAuthCredentials(
        access_token=SecretStr(session.access_token),
        account_id=session.account_id,
        residency=session.residency,
    )


def _oauth_error_code(response: httpx.Response) -> str | None:
    try:
        payload = _json_object(response.content, "oauth_error_response_invalid")
    except CodexAuthError:
        return None
    error = payload.get("error")
    if type(error) is dict:
        code = error.get("code")
    else:
        code = error
    return code if type(code) is str and len(code) <= 128 else None
