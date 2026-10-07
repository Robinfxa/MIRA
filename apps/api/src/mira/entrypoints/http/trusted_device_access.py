"""Bounded browser ownership on an explicitly trusted LAN; not pairing or login."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
import threading
import time
from uuid import uuid4

from mira.entrypoints.http.operator_pairing import OperatorPairing


@dataclass(frozen=True, slots=True)
class _Browser:
    identity: str
    deadline: float
    origin: str


class TrustedDeviceAccess:
    def __init__(self, expected_origins: tuple[str, ...], *, session_ttl_seconds: int = 28_800, max_devices: int = 16):
        if (type(expected_origins) is not tuple or not 1 <= len(expected_origins) <= 3
                or any(not OperatorPairing._valid_origin(origin) for origin in expected_origins)
                or type(max_devices) is not int or not 1 <= max_devices <= 16
                or type(session_ttl_seconds) is not int or not 60 <= session_ttl_seconds <= 86_400):
            raise ValueError('trusted_device_configuration_invalid')
        self._origins = frozenset(expected_origins)
        self.max_devices = max_devices
        self._ttl = session_ttl_seconds
        self._app_id: str | None = None
        self._revoked = False
        self._browsers: dict[bytes, _Browser] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _digest(cookie: str | None) -> bytes | None:
        if type(cookie) is not str or not 1 <= len(cookie) <= 128 or not cookie.isascii():
            return None
        return hashlib.sha256(cookie.encode('ascii')).digest()

    def _prune(self) -> None:
        now = time.monotonic()
        self._browsers = {key: browser for key, browser in self._browsers.items() if now <= browser.deadline}

    def bind_app(self, app_id: str) -> None:
        with self._lock:
            if type(app_id) is not str or not app_id or self._app_id is not None:
                raise ValueError('trusted_device_already_bound')
            self._app_id = app_id

    def admit(self, cookie: str | None, origin: str | None, host: str | None, *, app_id: str) -> str | None:
        with self._lock:
            if (self._revoked or self._app_id != app_id or origin not in self._origins
                    or not OperatorPairing.host_matches(origin, host)):
                return None
            self._prune()
            browser = self._browsers.get(self._digest(cookie))
            if browser is not None and browser.origin == origin:
                return cookie
            if len(self._browsers) >= self.max_devices:
                return None
            issued = secrets.token_urlsafe(32)
            self._browsers[self._digest(issued)] = _Browser(uuid4().hex, time.monotonic() + self._ttl, origin)
            return issued

    def identity(self, cookie: str | None) -> str | None:
        with self._lock:
            self._prune()
            browser = self._browsers.get(self._digest(cookie))
            return browser.identity if browser is not None and not self._revoked else None

    def is_authenticated(self, cookie, origin, host, *, app_id=None, method='GET',
                         sec_fetch_site=None, referer=None) -> bool:
        with self._lock:
            browser = self._browsers.get(self._digest(cookie))
            if (self._app_id != app_id or self._revoked or self.identity(cookie) is None
                    or browser is None or not OperatorPairing.host_matches(browser.origin, host)):
                return False
            if origin:
                return origin == browser.origin
            if method.upper() not in {'GET', 'HEAD'}:
                return False
            fetch_site = sec_fetch_site.lower() if sec_fetch_site else None
            referer_origin = OperatorPairing._referer_origin(referer) if referer else None
            if fetch_site is not None and fetch_site != 'same-origin':
                return False
            if referer is not None and referer_origin != browser.origin:
                return False
            return fetch_site == 'same-origin' or referer_origin == browser.origin

    def active_identities(self) -> frozenset[str]:
        with self._lock:
            self._prune()
            return frozenset(browser.identity for browser in self._browsers.values()) if not self._revoked else frozenset()

    def revoke_device(self, cookie: str | None) -> str | None:
        with self._lock:
            browser = self._browsers.pop(self._digest(cookie), None)
            return browser.identity if browser is not None else None

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True
            self._browsers.clear()

    @property
    def session_ttl_seconds(self) -> int:
        return self._ttl

    @property
    def expected_origins(self) -> frozenset[str]:
        return self._origins
