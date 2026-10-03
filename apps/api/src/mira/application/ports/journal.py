from typing import Protocol

from mira.application.contracts import AuditEvent


class EventJournal(Protocol):
    def append(self, event: AuditEvent) -> None:
        """Nonblocking, bounded local diagnostics only; not a durable transaction log."""
        ...

    def read(self, session_id: str) -> tuple[AuditEvent, ...]: ...
    def delete(self, session_id: str) -> None: ...
