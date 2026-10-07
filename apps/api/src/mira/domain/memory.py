"""Typed, source-linked records for the opt-in local memory slice.

These objects carry evidence labels; they do not assert that a caller-supplied
label is trustworthy, and they never grant execution or permission authority.
"""

from dataclasses import dataclass
from enum import StrEnum


class MemoryDeadlineExceededError(TimeoutError):
    """A bounded recall query exceeded its explicit local time budget."""


class MemoryRevisionChangedError(RuntimeError):
    """The memory scope changed while a context snapshot was being assembled."""


def _require_id(value: str, field_name: str) -> None:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or any(ord(char) < 32 or ord(char) == 127 or char.isspace() for char in value)):
        raise ValueError(f"{field_name} must be a non-empty opaque identifier of at most 128 characters")


def _require_time(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if (type(value) is not str or not 20 <= len(value) <= 64 or "T" not in value
            or not (value.endswith("Z") or "+" in value[10:] or "-" in value[10:])):
        raise ValueError(f"{field_name} must be a bounded timestamp with an explicit timezone")


class MemorySource(StrEnum):
    """Immutable provenance class. A label alone does not prove its origin."""

    USER_STATEMENT = "user_statement"
    PRESENTATION_RECEIPT = "presentation_receipt"
    AUTHORED_BACKSTORY = "authored_backstory"
    INTERPRETATION = "interpretation"
    GENERATED_VISUALIZATION = "generated_visualization"


class MemoryMutationKind(StrEnum):
    FORGET = "forget"
    RESTORE = "restore"


class MemoryKind(StrEnum):
    BOUNDARY = "boundary"
    EPISODIC = "episodic"


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Explicit partition supplied by an internal/server-owned caller."""

    user_id: str
    character_id: str
    world_id: str

    def __post_init__(self) -> None:
        _require_id(self.user_id, "user_id")
        _require_id(self.character_id, "character_id")
        _require_id(self.world_id, "world_id")


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """Immutable evidence/projection row; source event version is mandatory."""

    id: str
    scope: MemoryScope
    source: MemorySource
    text: str
    source_event_id: str
    source_version: int
    recorded_at: str | None = None
    supersedes_id: str | None = None
    depends_on: tuple[str, ...] = ()
    kind: MemoryKind = MemoryKind.EPISODIC

    def __post_init__(self) -> None:
        _require_id(self.id, "id")
        if not isinstance(self.scope, MemoryScope):
            raise ValueError("scope must be an explicit MemoryScope")
        if not isinstance(self.source, MemorySource):
            raise ValueError("source must be a typed MemorySource")
        if not isinstance(self.kind, MemoryKind):
            raise ValueError("kind must be a typed MemoryKind")
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 16_384:
            raise ValueError("text must contain 1 to 16384 characters")
        _require_id(self.source_event_id, "source_event_id")
        if isinstance(self.source_version, bool) or not isinstance(self.source_version, int):
            raise ValueError("source_version must be a positive integer")
        if self.source_version < 1:
            raise ValueError("source_version must be a positive integer")
        _require_time(self.recorded_at, "recorded_at")
        if self.supersedes_id is not None:
            _require_id(self.supersedes_id, "supersedes_id")
            if self.supersedes_id == self.id:
                raise ValueError("an entry cannot supersede itself")
        if not isinstance(self.depends_on, tuple) or len(self.depends_on) > 8:
            raise ValueError("depends_on must be a tuple of at most 8 entry IDs")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on cannot contain duplicate entry IDs")
        for entry_id in self.depends_on:
            _require_id(entry_id, "depends_on entry ID")
            if entry_id == self.id:
                raise ValueError("an entry cannot depend on itself")


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    scope: MemoryScope
    text: str
    limit: int = 8
    max_chars: int = 4_000
    include_interpretations: bool = False
    timeout_ms: int = 200

    def __post_init__(self) -> None:
        if not isinstance(self.scope, MemoryScope):
            raise ValueError("scope must be an explicit MemoryScope")
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 256:
            raise ValueError("query text must contain 1 to 256 characters")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int):
            raise ValueError("max_chars must be an integer between 1 and 32768")
        if not 1 <= self.max_chars <= 32_768:
            raise ValueError("max_chars must be an integer between 1 and 32768")
        if not isinstance(self.include_interpretations, bool):
            raise ValueError("include_interpretations must be a boolean")
        if isinstance(self.timeout_ms, bool) or not isinstance(self.timeout_ms, int):
            raise ValueError("timeout_ms must be an integer between 10 and 1000")
        if not 10 <= self.timeout_ms <= 1_000:
            raise ValueError("timeout_ms must be an integer between 10 and 1000")


@dataclass(frozen=True, slots=True)
class MemoryMutation:
    """Append-only suppression/restoration event; text rows are never purged."""

    id: str
    scope: MemoryScope
    kind: MemoryMutationKind
    target_entry_id: str
    reverses_id: str | None
    recorded_at: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "id")
        if not isinstance(self.scope, MemoryScope):
            raise ValueError("scope must be an explicit MemoryScope")
        if not isinstance(self.kind, MemoryMutationKind):
            raise ValueError("kind must be a typed MemoryMutationKind")
        _require_id(self.target_entry_id, "target_entry_id")
        if self.reverses_id is not None:
            _require_id(self.reverses_id, "reverses_id")
        if self.kind is MemoryMutationKind.FORGET and self.reverses_id is not None:
            raise ValueError("forget events cannot reverse another mutation")
        if self.kind is MemoryMutationKind.RESTORE and self.reverses_id is None:
            raise ValueError("restore events must identify the forget event they reverse")
        _require_time(self.recorded_at, "recorded_at")


MemoryHistoryItem = MemoryEntry | MemoryMutation
