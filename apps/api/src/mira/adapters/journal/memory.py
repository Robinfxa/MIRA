from collections import deque

from mira.application.contracts import AuditEvent


class MemoryEventJournal:
    """Bounded diagnostics. No raw prompts, secret config, or provider responses."""
    def __init__(self, capacity: int) -> None:
        self._events: deque[AuditEvent] = deque(maxlen=capacity)

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def read(self, session_id: str) -> tuple[AuditEvent, ...]:
        return tuple(e for e in self._events if e.session_id == session_id)

    def delete(self, session_id: str) -> None:
        self._events = deque((e for e in self._events if e.session_id != session_id),
                             maxlen=self._events.maxlen)
