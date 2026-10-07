"""One-process, one-operator pairing for explicitly enabled local memory mode.

This is a localhost pairing boundary, not host-user authentication. Anyone who
can read the one-use pairing file during its short lifetime, control the local
browser, or already run code as the same OS user can act as that operator.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import urlsplit, urlunsplit


class OperatorPairing:
    """Runtime-only one-use pairing verifier and origin-bound session cookie."""

    def __init__(self, code: str, expected_origins: tuple[str, ...], *,
                 ttl_seconds: int = 300, max_attempts: int = 5,
                 session_ttl_seconds: int = 28_800) -> None:
        if (type(code) is not str or not 32 <= len(code) <= 128
                or not code.isascii() or any(ord(c) < 0x21 or ord(c) > 0x7e for c in code)):
            raise ValueError("operator_pairing_configuration_invalid")
        if (type(expected_origins) is not tuple or not expected_origins
                or any(not self._valid_origin(value) for value in expected_origins)):
            raise ValueError("operator_pairing_configuration_invalid")
        if (type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900
                or type(max_attempts) is not int or not 1 <= max_attempts <= 10
                or type(session_ttl_seconds) is not int or not 60 <= session_ttl_seconds <= 86_400):
            raise ValueError("operator_pairing_configuration_invalid")
        self._salt = secrets.token_bytes(32)
        self._code_hash = hashlib.sha256(self._salt + code.encode("ascii")).digest()
        self._origins = frozenset(expected_origins)
        self._deadline = time.monotonic() + ttl_seconds
        self._session_ttl = session_ttl_seconds
        self._max_attempts = max_attempts
        self._attempts = 0
        self._consumed = False
        self._revoked = False
        self._session_hash: bytes | None = None
        self._session_deadline = 0.0
        self._session_origin: str | None = None
        self._session_host: str | None = None
        self._app_id: str | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _valid_origin(origin: object) -> bool:
        if type(origin) is not str or not origin or len(origin) > 255:
            return False
        try:
            parsed = urlsplit(origin)
            # Accessing .port validates malformed and out-of-range ports.
            _ = parsed.port
            return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                    and parsed.username is None and parsed.password is None
                    and parsed.path == "" and parsed.query == "" and parsed.fragment == ""
                    and parsed.netloc == parsed.netloc.lower() and not parsed.netloc.endswith(":"))
        except ValueError:
            return False

    @staticmethod
    def host_matches(origin: str, host: str) -> bool:
        if type(host) is not str or not host or len(host) > 255:
            return False
        try:
            authority = urlsplit(origin).netloc
            return hmac.compare_digest(authority.encode("ascii"), host.lower().encode("ascii"))
        except (UnicodeError, ValueError):
            return False

    def _origin_allowed(self, origin: str, host: str) -> bool:
        return (origin in self._origins and self.host_matches(origin, host))

    def bind_app(self, app_id: str) -> None:
        """Attach this capability to exactly one in-memory app instance."""
        if type(app_id) is not str or not app_id:
            raise ValueError("operator_pairing_configuration_invalid")
        with self._lock:
            if self._app_id is not None:
                raise ValueError("operator_pairing_already_bound")
            self._app_id = app_id

    def pair(self, candidate: str, origin: str, host: str, *, app_id: str | None = None) -> str | None:
        """Consume a valid pairing code once and issue a random opaque cookie."""
        with self._lock:
            if self._app_id != app_id:
                return None
            if (self._revoked or self._consumed or time.monotonic() > self._deadline
                    or self._attempts >= self._max_attempts):
                if self._attempts >= self._max_attempts:
                    self._revoked = True
                return None
            if not self._origin_allowed(origin, host):
                self._attempts += 1
                return None
            safe_candidate = candidate if type(candidate) is str and len(candidate) <= 128 and candidate.isascii() else ""
            candidate_hash = hashlib.sha256(self._salt + safe_candidate.encode("ascii")).digest()
            if not hmac.compare_digest(self._code_hash, candidate_hash):
                self._attempts += 1
                if self._attempts >= self._max_attempts:
                    self._revoked = True
                return None
            self._consumed = True
            cookie = secrets.token_urlsafe(32)
            self._session_hash = hashlib.sha256(cookie.encode("ascii")).digest()
            self._session_deadline = time.monotonic() + self._session_ttl
            self._session_origin = origin
            self._session_host = host.lower()
            # Erase the verifier as soon as the one-use code has been accepted.
            self._code_hash = bytes(len(self._code_hash))
            self._salt = bytes(len(self._salt))
            return cookie

    def is_authenticated(self, cookie: str | None, origin: str | None, host: str | None,
                         *, app_id: str | None = None, method: str = "GET",
                         sec_fetch_site: str | None = None, referer: str | None = None) -> bool:
        if not cookie or not host or len(cookie) > 128:
            return False
        with self._lock:
            if (self._app_id != app_id or self._revoked or not self._consumed or self._session_hash is None
                    or time.monotonic() > self._session_deadline or host.lower() != self._session_host):
                return False
            if origin:
                if origin != self._session_origin or not self._origin_allowed(origin, host):
                    return False
            else:
                # Same-origin browser GETs commonly omit Origin. Accept that
                # only when browser fetch metadata or Referer positively binds
                # the safe request to the already paired origin.
                if method.upper() not in {"GET", "HEAD"}:
                    return False
                fetch_site = sec_fetch_site.lower() if sec_fetch_site else None
                referer_origin = self._referer_origin(referer) if referer else None
                if fetch_site is not None and fetch_site != "same-origin":
                    return False
                if referer is not None and referer_origin != self._session_origin:
                    return False
                if fetch_site != "same-origin" and referer_origin != self._session_origin:
                    return False
                if not self._origin_allowed(self._session_origin or "", host):
                    return False
            presented = hashlib.sha256(cookie.encode("utf-8", errors="ignore")).digest()
            return hmac.compare_digest(self._session_hash, presented)

    @staticmethod
    def _referer_origin(referer: str) -> str | None:
        if type(referer) is not str or len(referer) > 1024:
            return None
        try:
            parsed = urlsplit(referer)
            _ = parsed.port
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None):
                return None
            return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        except ValueError:
            return None

    def status(self) -> dict[str, bool]:
        with self._lock:
            now = time.monotonic()
            expired = ((now > self._deadline and not self._consumed)
                       or (self._consumed and now > self._session_deadline))
            revoked = self._revoked or expired or self._attempts >= self._max_attempts
            return {"required": True, "paired": bool(self._consumed and not revoked
                    and now <= self._session_deadline), "revoked": bool(revoked)}

    @property
    def session_ttl_seconds(self) -> int:
        return self._session_ttl

    @property
    def expected_origins(self) -> frozenset[str]:
        return self._origins

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True
            self._consumed = True
            self._session_hash = None
            self._session_deadline = 0.0
            self._session_origin = None
            self._session_host = None
            self._salt = bytes(len(self._salt))
            self._code_hash = bytes(len(self._code_hash))
