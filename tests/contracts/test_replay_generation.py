"""FND02-001/004/006/007/008: observable behavior through the existing factory and port."""
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from mira.application.contracts import EffectProposal, GenerationContext, ReviewVerdict
from mira.bootstrap.providers import create_providers
from mira.config.loader import ConfigurationError, load_settings
from mira.config.settings import ProviderSettings
from mira.domain.models import EffectKind

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = GenerationContext("arbitrary input", ("arbitrary input",), (), 1)


def providers(scenario: str = "photo-tour"):
    settings = ProviderSettings.model_validate({
        "generation": "replay", "review": "fixture", "replay_scenario": scenario,
    })
    return create_providers(settings)


def test_environment_selects_replay_through_existing_loader():
    settings = load_settings(root=ROOT, environ={
        "MIRA_PROVIDERS__GENERATION": "replay",
        "MIRA_PROVIDERS__REPLAY_SCENARIO": "photo-tour",
    })
    assert settings.providers.generation == "replay"
    assert settings.providers.replay_scenario == "photo-tour"
    assert not settings.providers.allow_external_calls
    assert not settings.providers.allow_paid_api
    assert create_providers(settings.providers).generation is not None


def test_default_profile_stays_mock():
    assert load_settings(root=ROOT, environ={}).providers.generation == "mock"


@pytest.mark.asyncio
async def test_replay_yields_complete_ordered_ranges():
    selected = providers()
    actual = [item async for item in selected.generation.generate(CONTEXT)]
    assert [item.fixture_id for item in actual] == ["photo", "photo_caption"]
    assert [item.effects[0].kind for item in actual] == [EffectKind.MEDIA, EffectKind.SUBTITLE]
    for item in actual:
        assert (await selected.review.review(CONTEXT, item)).verdict == ReviewVerdict.ALLOW


@pytest.mark.asyncio
async def test_two_invocations_have_independent_cursors():
    backend = providers().generation
    first = backend.generate(CONTEXT)
    second = backend.generate(replace(CONTEXT, output_epoch=2))
    async with asyncio.timeout(1):
        assert (await anext(first)).fixture_id == "photo"
        assert (await anext(second)).fixture_id == "photo"
        assert (await anext(second)).fixture_id == "photo_caption"
        assert (await anext(first)).fixture_id == "photo_caption"
        with pytest.raises(StopAsyncIteration):
            await anext(first)
        with pytest.raises(StopAsyncIteration):
            await anext(second)


@pytest.mark.asyncio
async def test_script_failure_is_not_a_clean_end():
    stream = providers("failed-tail").generation.generate(CONTEXT)
    assert (await anext(stream)).fixture_id == "photo"
    with pytest.raises(RuntimeError, match="fixture_provider_failure"):
        await anext(stream)


@pytest.mark.asyncio
async def test_replay_does_not_relax_fixture_review():
    selected = providers()
    stream = selected.generation.generate(CONTEXT)
    try:
        known = await anext(stream)
        changed = replace(known, effects=(EffectProposal(EffectKind.SUBTITLE, "unapproved"),))
        assert (await selected.review.review(CONTEXT, changed)).verdict == ReviewVerdict.REJECT
    finally:
        await stream.aclose()


@pytest.mark.parametrize("field", ["allow_external_calls", "allow_paid_api"])
def test_replay_never_enables_external_or_paid_calls(field):
    settings = ProviderSettings.model_validate({"generation": "replay", field: True})
    with pytest.raises(ConfigurationError):
        create_providers(settings)


def test_replay_cannot_be_paired_with_unimplemented_live_review():
    settings = ProviderSettings.model_validate({"generation": "replay", "review": "jev"})
    with pytest.raises(ConfigurationError):
        create_providers(settings)
