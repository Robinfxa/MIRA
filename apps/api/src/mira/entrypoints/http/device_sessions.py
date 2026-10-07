"""Browser ownership for two ephemeral sessions; provider runtime remains shared."""
import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import HTTPException
from mira.domain.errors import DomainError


@dataclass(frozen=True, slots=True)
class _OwnedSession:
    session_id: str
    token: str = field(repr=False)


class DeviceSessions:
    def __init__(self):
        self._sessions: dict[str, _OwnedSession] = {}
        self._lock = asyncio.Lock()

    def allows_path(self, identity: str | None, path: str) -> bool:
        prefix = "/api/v1/sessions/"
        if not path.startswith(prefix):
            return True
        try:
            session_id = str(UUID(path[len(prefix):].split("/", 1)[0]))
        except ValueError:
            return False
        owned = self._sessions.get(identity)
        return owned is not None and owned.session_id == session_id

    async def create(self, identity, client_instance_id, container, pairing, *, media_allowed=True):
        async with self._lock:
            if identity not in pairing.active_identities():
                raise HTTPException(status_code=401, detail="operator_authorization_required")
            previous = self._sessions.get(identity)
            if previous is not None:
                # Refresh/new tab replaces only this browser's ephemeral session.
                # Reserve its slot until cleanup finishes; another device is untouched.
                try:
                    await self._close(previous, container)
                finally:
                    self._sessions.pop(identity, None)
                if identity not in pairing.active_identities():
                    raise HTTPException(status_code=401, detail="operator_authorization_required")
            actor, token = container.sessions.create(client_instance_id, media_allowed=media_allowed)
            state = await actor.snapshot()
            owned = _OwnedSession(state.session_id, token)
            self._sessions[identity] = owned
            if identity not in pairing.active_identities():
                try:
                    await self._close(owned, container)
                finally:
                    self._sessions.pop(identity, None)
                raise HTTPException(status_code=401, detail="operator_authorization_required")
            return actor, token

    async def _close(self, owned, container):
        container.reviewed_audio.cancel_session(owned.session_id)
        try:
            await container.listening_leases.close_session(owned.session_id)
        finally:
            try:
                await container.sessions.delete(owned.session_id, owned.token)
            except DomainError as error:
                if error.code != "session_not_found":
                    raise

    async def close_owner(self, identity, container):
        if container is None:
            return
        async with self._lock:
            owned = self._sessions.get(identity)
            if owned is not None:
                try:
                    await self._close(owned, container)
                finally:
                    self._sessions.pop(identity, None)

    async def delete(self, identity, session_id, token, container):
        async with self._lock:
            owned = self._sessions.get(identity)
            if owned is None or owned.session_id != session_id:
                raise HTTPException(status_code=403, detail="device_session_denied")
            container.sessions.get(session_id, token)
            try:
                await self._close(owned, container)
            finally:
                self._sessions.pop(identity, None)

    async def sweep(self, container, pairing):
        for identity in tuple(self._sessions):
            if identity not in pairing.active_identities():
                await self.close_owner(identity, container)
