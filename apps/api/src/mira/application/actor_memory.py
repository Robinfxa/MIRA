"""Narrow, explicit binding for asynchronous read-only actor memory recall.

The binding is constructed by trusted application composition. It fixes the
memory scope and budgets for the actor; neither request text nor recalled
content can select a scope or invoke a mutation API.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from mira.application.memory_context import (
    ContextPacket,
    MAX_CONTEXT_REQUEST_CHARS,
    MemoryContextError,
    bounded_retrieval_query,
    valid_context_packet,
)
from mira.domain.memory import MemoryScope


class ActorMemoryReader(Protocol):
    """Async, read-only adapter seam. Concrete readers own bounded I/O."""

    async def build_packet(
        self,
        *,
        scope: MemoryScope,
        request_text: str,
        retrieval_query: str,
        timeout_ms: int,
        max_packet_bytes: int,
    ) -> ContextPacket:
        """Read one coherent scoped snapshot, including its revision guards."""
        ...

    async def scope_revision(self, scope: MemoryScope) -> int:
        """Read only the current revision for this exact server-owned scope."""
        ...

    async def aclose(self) -> None:
        """Release bounded reader resources, if any."""
        ...


class ActorMemoryBindingError(ValueError):
    """A fixed, non-content-revealing binding or packet contract failure."""


@dataclass(frozen=True, slots=True)
class SessionMemoryBinding:
    """Opt-in reader, immutable server-supplied scope, and bounded packet policy."""

    reader: ActorMemoryReader = field(repr=False, compare=False)
    scope: MemoryScope = field(repr=False)
    timeout_ms: int = 200
    max_packet_bytes: int = 32_768
    close_reader_on_actor_close: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, MemoryScope):
            raise ActorMemoryBindingError("memory_scope_invalid")
        if not all(callable(getattr(self.reader, method, None)) for method in (
            "build_packet", "scope_revision", "aclose",
        )):
            raise ActorMemoryBindingError("memory_reader_invalid")
        if (isinstance(self.timeout_ms, bool) or type(self.timeout_ms) is not int
                or not 10 <= self.timeout_ms <= 1_000):
            raise ActorMemoryBindingError("memory_timeout_invalid")
        if (isinstance(self.max_packet_bytes, bool) or type(self.max_packet_bytes) is not int
                or not 1_024 <= self.max_packet_bytes <= 32_768):
            raise ActorMemoryBindingError("memory_packet_limit_invalid")
        if type(self.close_reader_on_actor_close) is not bool:
            raise ActorMemoryBindingError("memory_ownership_invalid")

    async def build_packet(self, request_text: str) -> ContextPacket:
        """Assemble current evidence without shortening the actual request text."""
        if (type(request_text) is not str or not request_text.strip()
                or len(request_text) > MAX_CONTEXT_REQUEST_CHARS):
            raise MemoryContextError("request_text_invalid")
        retrieval_query = bounded_retrieval_query(request_text)
        async with asyncio.timeout(self.timeout_ms / 1_000 + 0.05):
            packet = await self.reader.build_packet(
                scope=self.scope,
                request_text=request_text,
                retrieval_query=retrieval_query,
                timeout_ms=self.timeout_ms,
                max_packet_bytes=self.max_packet_bytes,
            )
        if (not valid_context_packet(packet, request_text=request_text)
                or packet.max_packet_bytes != self.max_packet_bytes
                or packet.timeout_ms != self.timeout_ms
                ):
            raise ActorMemoryBindingError("memory_packet_invalid")
        return packet

    async def ensure_current(self, packet: ContextPacket) -> None:
        """Fail closed if the bound scope changed after packet assembly."""
        if type(packet) is not ContextPacket:
            raise ActorMemoryBindingError("memory_packet_invalid")
        async with asyncio.timeout(self.timeout_ms / 1_000 + 0.05):
            revision = await self.reader.scope_revision(self.scope)
        if (isinstance(revision, bool) or type(revision) is not int
                or revision < 0):
            raise ActorMemoryBindingError("memory_revision_invalid")
        if revision != packet.snapshot_revision:
            raise ActorMemoryBindingError("memory_context_stale")

    async def aclose(self) -> None:
        """Close only when trusted composition explicitly transferred ownership."""
        if self.close_reader_on_actor_close:
            await self.reader.aclose()
