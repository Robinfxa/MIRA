"""Production memory factory composition uses only synthetic adapter doubles."""
from dataclasses import replace
from pathlib import Path

import pytest

from mira.bootstrap.development_memory import create_development_memory_factory
from mira.config.loader import ConfigurationError
from mira.config.memory import MemoryRecallOptions
from mira.domain.memory import MemoryScope


def options(**updates):
    configured = MemoryRecallOptions(Path("/synthetic/private/memory.sqlite3"),
        MemoryScope("synthetic-user", "mira", "synthetic-world"), "local", True)
    return replace(configured, **updates)


def test_factory_rechecks_explicit_authorization_and_limits():
    for value in (None, options(authorized_transmission=False)):
        with pytest.raises(ConfigurationError, match="memory_transmission_consent_required"):
            create_development_memory_factory(value)
    for value in (options(timeout_ms=True), options(max_packet_bytes=32769)):
        with pytest.raises(ConfigurationError, match="memory_limits_invalid"):
            create_development_memory_factory(value)


def test_factory_construction_opens_nothing(monkeypatch):
    monkeypatch.setattr(Path, "open", lambda *_a, **_k: pytest.fail("file opened"))
    factory = create_development_memory_factory(options())
    assert callable(factory)


@pytest.mark.asyncio
async def test_open_binding_transfers_reader_ownership_to_app_only(monkeypatch):
    from mira.adapters.memory import async_read
    readers = []
    class FakeReader:
        def __init__(self, path, scope):
            self.path = path; self.scope = scope; self.opens = 0; self.closes = 0
            readers.append(self)
        async def open(self):
            self.opens += 1
        async def build_packet(self, **_kwargs):
            raise AssertionError("not called")
        async def scope_revision(self, _scope):
            return 0
        async def aclose(self):
            self.closes += 1
    monkeypatch.setattr(async_read, "AsyncSQLiteMemoryReader", FakeReader)
    factory = create_development_memory_factory(options())
    assert readers == []
    binding = await factory()
    assert binding.scope == options().scope and binding.timeout_ms == 200
    assert binding.max_packet_bytes == 8192
    assert readers[0].opens == 1
    await binding.aclose()
    assert readers[0].closes == 0
    await binding.reader.aclose()
    assert readers[0].closes == 1


@pytest.mark.asyncio
async def test_reader_startup_failure_is_closed(monkeypatch):
    from mira.adapters.memory import async_read
    calls = []
    class FakeReader:
        def __init__(self, *_args):
            pass
        async def open(self):
            raise RuntimeError("synthetic_open_failure")
        async def aclose(self):
            calls.append("close")
    monkeypatch.setattr(async_read, "AsyncSQLiteMemoryReader", FakeReader)
    factory = create_development_memory_factory(options())
    with pytest.raises(RuntimeError, match="synthetic_open_failure"):
        await factory()
    assert calls == ["close"]
