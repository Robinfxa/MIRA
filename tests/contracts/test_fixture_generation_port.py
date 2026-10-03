"""The same observable port contract runs against both concrete fixture backends."""
import socket

import pytest

from mira.application.contracts import GenerationContext, ReviewVerdict
from mira.bootstrap.providers import create_providers
from mira.config.settings import ProviderSettings


@pytest.mark.parametrize("backend_name", ["mock", "replay"])
@pytest.mark.asyncio
async def test_fixture_backends_share_order_review_and_repeatability(backend_name, monkeypatch):
    def forbid_connect(*args, **kwargs):
        raise AssertionError("fixture backend attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbid_connect)
    selected = create_providers(ProviderSettings(generation=backend_name, mock_delay_ms=0))
    context = GenerationContext("看照片", ("看照片",), (), 1)
    first = [item async for item in selected.generation.generate(context)]
    second = [item async for item in selected.generation.generate(context)]
    assert first == second
    assert [item.fixture_id for item in first] == ["photo", "photo_caption"]
    for item in first:
        assert (await selected.review.review(context, item)).verdict == ReviewVerdict.ALLOW
