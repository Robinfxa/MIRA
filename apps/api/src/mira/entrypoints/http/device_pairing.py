"""Two independent ephemeral device capabilities for one private service.

No account, shared password, durable grant or provider credential is created.
The operator transfers each short-lived one-use code manually to one browser.
"""
from __future__ import annotations

import hashlib
import threading
from uuid import uuid4

from mira.entrypoints.http.operator_pairing import OperatorPairing


class DevicePairing:
    def __init__(self, codes: tuple[str, str], expected_origins: tuple[str, ...], **limits):
        if (type(codes) is not tuple or len(codes) != 2
                or any(type(code) is not str for code in codes) or len(set(codes)) != 2):
            raise ValueError("device_pairing_requires_two_independent_codes")
        self._devices = tuple(OperatorPairing(code, expected_origins, **limits) for code in codes)
        self._identities = tuple(uuid4().hex for _ in codes)
        self._cookies: dict[bytes, int] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _digest(cookie: str | None) -> bytes | None:
        if type(cookie) is not str or not 1 <= len(cookie) <= 128 or not cookie.isascii():
            return None
        return hashlib.sha256(cookie.encode("ascii")).digest()

    def _index(self, cookie: str | None) -> int | None:
        return self._cookies.get(self._digest(cookie))

    def bind_app(self, app_id: str) -> None:
        with self._lock:
            for device in self._devices:
                device.bind_app(app_id)

    def pair(self, candidate: str, origin: str, host: str, *, app_id: str | None = None) -> str | None:
        with self._lock:
            for index, device in enumerate(self._devices):
                cookie = device.pair(candidate, origin, host, app_id=app_id)
                if cookie is not None:
                    self._cookies[self._digest(cookie)] = index
                    return cookie
        return None

    def identity(self, cookie: str | None) -> str | None:
        with self._lock:
            index = self._index(cookie)
            if index is None or not self._devices[index].status()["paired"]:
                return None
            return self._identities[index]

    def is_authenticated(self, cookie, origin, host, **context) -> bool:
        with self._lock:
            index = self._index(cookie)
            return index is not None and self._devices[index].is_authenticated(cookie, origin, host, **context)

    def status(self, cookie: str | None = None) -> dict[str, bool]:
        with self._lock:
            index = self._index(cookie)
            if index is not None:
                return self._devices[index].status()
            states = tuple(device.status() for device in self._devices)
            return {"required": True, "paired": any(state["paired"] for state in states),
                    "revoked": all(state["revoked"] for state in states)}

    def active_identities(self) -> frozenset[str]:
        with self._lock:
            return frozenset(identity for identity, device in zip(self._identities, self._devices)
                             if device.status()["paired"])

    def revoke_device(self, cookie: str | None) -> str | None:
        with self._lock:
            index = self._index(cookie)
            if index is None:
                return None
            self._devices[index].revoke()
            return self._identities[index]

    def revoke(self) -> None:
        with self._lock:
            for device in self._devices:
                device.revoke()

    @property
    def session_ttl_seconds(self) -> int:
        return self._devices[0].session_ttl_seconds

    @property
    def expected_origins(self) -> frozenset[str]:
        return self._devices[0].expected_origins
