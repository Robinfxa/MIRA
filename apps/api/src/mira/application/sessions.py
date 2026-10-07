"""Process-local session lifecycle. A single worker is required until WP05 persistence."""
import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from mira.application.ports.journal import EventJournal
from mira.application.session_actor import SessionActor
from mira.domain.errors import DomainError
from mira.domain.models import SessionState


@dataclass(frozen=True, slots=True)
class SessionLease:
    actor: SessionActor
    token: str


class SessionRegistry:
    def __init__(self, factory: Callable[[SessionState], SessionActor],
                 journal: EventJournal, max_sessions: int, *,
                 text_only_factory: Callable[[SessionState], SessionActor] | None = None) -> None:
        self._factory = factory
        self._text_only_factory = text_only_factory
        self._journal = journal
        self._max_sessions = max_sessions
        self._sessions: dict[str, SessionLease] = {}

    def create(self, client_instance_id: str, *, media_allowed: bool = True) -> tuple[SessionActor, str]:
        if len(self._sessions) >= self._max_sessions:
            raise DomainError("session_capacity", "Local session capacity reached.")
        session_id = str(uuid4())
        factory = self._factory if media_allowed else self._text_only_factory
        if factory is None:
            raise DomainError("speech_unavailable", "A text-only session factory is required.")
        actor = factory(SessionState(session_id, client_instance_id,
            response_mode="voice" if media_allowed else "text_only", response_muted=not media_allowed))
        token = secrets.token_urlsafe(32)
        self._sessions[session_id] = SessionLease(actor, token)
        return actor, token

    def get(self, session_id: str, token: str) -> SessionActor:
        lease = self._sessions.get(session_id)
        # Native tokens are ASCII. Reject hostile JSON Unicode before compare_digest,
        # which raises TypeError for non-ASCII str instead of returning a mismatch.
        if (lease is None or type(token) is not str or not token.isascii()
                or not secrets.compare_digest(lease.token, token)):
            raise DomainError("session_not_found", "Session was not found.")
        return lease.actor

    async def delete(self, session_id: str, token: str) -> None:
        actor = self.get(session_id, token)
        # Keep the capacity reservation while close flushes scoped character
        # checkpoints, so a replacement session cannot overlap its predecessor.
        try:
            await actor.close()
        finally:
            self._sessions.pop(session_id, None)
            self._journal.delete(session_id)

    async def close(self) -> None:
        await asyncio.gather(*(lease.actor.close() for lease in self._sessions.values()))
        self._sessions.clear()
