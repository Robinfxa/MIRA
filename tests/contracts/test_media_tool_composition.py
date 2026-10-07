"""Composition only: synthetic adapters, no credentials or provider requests."""
from dataclasses import replace
import pytest

from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.bootstrap.providers import Providers
from mira.bootstrap.story_image_provider import StoryImageOptions, describe_story_images
from mira.config.settings import Settings
from mira.config.loader import ConfigurationError


class Generation:
    async def generate(self, context):
        if False:
            yield None

    def open_tool_turn(self, context, tools):
        raise AssertionError('composition must not open a provider turn')


class Review:
    async def __call__(self, payload):
        raise AssertionError('composition must not dispatch review')


def arguments(**changes):
    result = dict(settings=Settings(), generation=Generation(), route='chatgpt_subscription',
        model='gpt-6-luna', action_review_mode='legacy_jev', input_transport=Review(), output_transport=Review(), authorized=True)
    result.update(changes)
    return result


def test_tool_provider_injection_is_explicit_and_legacy_default_stays_absent():
    legacy = Providers(Generation(), Review())
    assert legacy.tool_generation is None and legacy.tool_caption_chunker is None
    tool = Generation()
    assert Providers(Generation(), Review(), tool_generation=tool).tool_generation is tool
    with pytest.raises(ConfigurationError):
        Providers(Generation(), Review(), tool_generation=object())


def test_two_request_tool_turn_preserves_declared_total_and_caption_planner(monkeypatch):
    import mira.bootstrap.direct_provider_app as module
    actual = module.create_app
    captured = {}
    def capture(*args, **kwargs):
        captured.update(kwargs)
        return actual(*args, **kwargs)
    monkeypatch.setattr(module, 'create_app', capture)
    tool = Generation()
    app = create_direct_provider_app(**arguments(tool_generation=tool,
        generation_request_limit=2, session_turn_limit=1, boundary_request_limit=1))
    assert captured['providers'].tool_generation is tool
    assert callable(captured['providers'].tool_caption_chunker.expand)
    assert app.state.usage_declaration.codex_requests == 2
    assert app.state.usage_declaration.session_turns == 1
    with pytest.raises(ConfigurationError):
        create_direct_provider_app(**arguments(generation_request_limit=2, session_turn_limit=1))


def test_custom_fiction_consent_is_visible_and_does_not_enable_images():
    options = StoryImageOptions(enabled=True, provider='chatgpt_subscription',
        image_model='gpt-image-2', review_model='gpt-6-luna', quality='auto',
        authorize_data_to_openai=True, authorize_subscription_usage=True,
        review_max_output_tokens=None, authorize_custom_brief=True)
    current = describe_story_images(options=options, story_enabled=True)
    assert current['data_scope'] == 'released_fiction_and_bounded_custom_brief'
    assert current['private_memory_transmitted'] is False
    assert describe_story_images(options=replace(options, authorize_custom_brief=False),
        story_enabled=True)['data_scope'] == 'released_fiction_catalog_only'
    assert describe_story_images(options=replace(options, enabled=False),
        story_enabled=True)['status'] == 'unavailable'


def test_cli_exposes_custom_brief_consent_and_explicit_legacy_mode():
    from tools.live_provider import _parser, _story_image_options
    args = _parser().parse_args(['check', '--provider', 'chatgpt_subscription',
        '--model', 'gpt-6-luna', '--env-file', '/synthetic/not-read.env',
        '--story-images', '--authorize-story-image-custom-brief'])
    assert args.legacy_media_proposals is False
    assert _story_image_options(args).authorize_custom_brief is True
    from tools.live_provider import EntryError
    args.legacy_media_proposals = True
    with pytest.raises(EntryError):
        _story_image_options(args)


@pytest.mark.asyncio
async def test_existing_caption_planner_can_expand_one_complete_tool_result():
    from mira.application.semantic_chunking import SemanticChunkingGeneration
    from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
    from mira.domain.models import EffectKind
    class Boundary:
        async def choose(self, request):
            raise RuntimeError('bounded fallback keeps original tail')
    planner = SemanticChunkingGeneration(Generation(), Boundary())
    text = '第一句说明可见的结果。第二句解释当前画面。第三句保留完整的结尾。'
    candidate = CandidateRange((EffectProposal(EffectKind.SUBTITLE, text),), 'synthetic-tool-result')
    context = GenerationContext('请解释这幅虚构画面。', ('请解释这幅虚构画面。',), (), 1)
    pieces = [piece async for piece in planner.expand(context, candidate)]
    assert len(pieces) >= 2
    assert ''.join(effect.value for piece in pieces for effect in piece.effects) == text


@pytest.mark.asyncio
async def test_tool_wire_keeps_roleplay_names_separate_from_true_asset_source():
    import json
    from tests.contracts.test_direct_luna_tools import definitions, result, tool, wire, message
    from tests.contracts.test_direct_codex_responses import backend, CONTEXT, response
    from mira.bootstrap.character_assets import renderer_readiness
    requests = []
    async def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        payload = json.loads(body['input'][-1]['content'][0]['text'])
        contract = payload['media_dialogue_contract']
        assert contract['schema'] == 'mira.media-tool-dialogue.v1'
        assert contract['use_natural_inworld_names'] is True
        assert contract['direct_source_questions'] == 'answer_actual_provenance'
        assert payload['facts']['authored_visual_events']['trip_photo']['provenance'] == 'authored_illustration'
        assert 'photo_dialogue_contract' not in payload  # no legacy media-effect instruction
        return response(wire([tool()]) if len(requests) == 1 else wire([message()]))
    generator, _, _ = backend(handle, request_limit=2)
    context = replace(CONTEXT, character_assets=renderer_readiness('code-native-review'))
    turn = generator.open_tool_turn(context, definitions())
    call = await turn.start()
    await turn.continue_after_tool(result(call.call_id), context)
    assert len(requests) == 2


@pytest.mark.parametrize('current_kind,allowed', [('generated', True), ('fixed', False), ('unknown', False)])
def test_fixed_photo_deduplication_compares_actual_target(current_kind, allowed):
    from uuid import uuid4
    from mira.application.authored_visual_events import filter_visual_events
    from mira.application.compiler import compile_generated_media, compile_range
    from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
    from mira.bootstrap.character_assets import renderer_readiness
    from mira.domain.models import EffectKind, Receipt, SessionState
    proposal = CandidateRange((EffectProposal(EffectKind.MEDIA, 'trip_photo'),), 'synthetic-request')
    current = (compile_generated_media(str(uuid4()), 'a' * 64, epoch=1, activity=1)
        if current_kind == 'generated' else compile_range(proposal, epoch=1, activity=1)[0])
    presented = () if current_kind == 'unknown' else (current,)
    receipts = (() if current_kind == 'unknown' else
        (Receipt(current.id, current.digest, current.output_epoch, current.activity_seq, 1),))
    state = SessionState(str(uuid4()), str(uuid4()), output_epoch=2, activity_seq=2,
        photo_visible=True, issued_effects=presented, receipts=receipts)
    context = GenerationContext('请再看灯塔那张。', ('请再看灯塔那张。',), presented, 2,
        photo_visible=True, character_assets=renderer_readiness('code-native-review'))
    assert bool(filter_visual_events(context, proposal, state).effects) is allowed
    dismissed = replace(state, photo_dismissed_through_activity=2)
    assert not filter_visual_events(context, proposal, dismissed).effects
