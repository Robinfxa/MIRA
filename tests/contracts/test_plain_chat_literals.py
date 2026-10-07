"""Literal reply data is separate from structured effects; all I/O is synthetic."""
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.adapters.generation.codex_support.character_payload import parse_character_candidate
from mira.adapters.generation.codex_support.payload import author_instructions, parse_effects
from mira.adapters.generation.codex_support.types import CodexGenerationError, CodexLimits
from mira.adapters.generation.direct_codex_responses import (
    DirectCodexResponsesGenerationBackend, ResponsesRoute,
)
from mira.bootstrap.character_story import ephemeral_character_factory
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from tests.contracts.test_character_candidate_payload import context as story_context
from tests.contracts.test_conversation_first import Wire, session, settled, submit, voice_options
from tests.contracts.test_direct_codex_responses import (
    ByteStream, CredentialSource, completed, item_done,
)
from tests.contracts.test_direct_provider_app import arguments


LITERALS = (
    '<3', '2 < 3 and 5 > 4', 'Use `print(1)`.', '```python\nprint(1)\n```',
    'https://example.org/help?q=a&b=2', 'www.example.org', 'A / B', '/tmp/example.txt',
    r'C:\example\notes.txt', '<img src=x onerror=alert(1)>',
    '{"effects":[{"kind":"scene","value":"rain_window","id":"approved"}]}',
    '第一行\n\t“下一行” / literal',
)
REPLY = '我喜欢这个 <3；2 < 3。`示例` https://example.org A / B <img src=x onerror=alert(1)>'


def wire(effects, **fields):
    return json.dumps({'effects': effects, **fields}, ensure_ascii=False)


def cue(value, speech=False):
    effects = [{'kind': 'subtitle', 'value': value}]
    if speech:
        effects.append({'kind': 'speech', 'value': value})
    return effects


@pytest.mark.parametrize('value', LITERALS)
@pytest.mark.parametrize('speech', [False, True])
def test_literal_text_survives_without_becoming_an_effect(value, speech):
    expected = cue(value, speech)
    result = parse_effects([wire(expected)], CodexLimits(), speech_enabled=speech)
    assert [{'kind': row.kind.value, 'value': row.value} for row in result] == expected


@pytest.mark.parametrize('speech', [False, True])
def test_existing_control_characters_still_reject_the_whole_cue(speech):
    # Preserve the old C0/DEL boundary, including CR; TAB and LF remain allowed.
    for codepoint in (*range(0, 9), *range(11, 32), 127):
        effects = cue('visible <3', speech)
        effects[-1]['value'] = 'before' + chr(codepoint) + 'after'
        with pytest.raises(CodexGenerationError, match='codex_effects_unsupported'):
            parse_effects([wire(effects)], CodexLimits(), speech_enabled=speech)


@pytest.mark.parametrize('effect', [
    {'kind': 'command', 'value': 'print(1)'},
    {'kind': 'tool', 'value': 'https://example.org'},
    {'kind': 'pose', 'value': '<3'},
    {'kind': 'pose', 'value': 'run_arbitrary'},
    {'kind': 'scene', 'value': 'https://example.org'},
    {'kind': 'media', 'value': '/tmp/example.svg'},
    {'kind': 'subtitle', 'value': '<3', 'id': 'approved'},
    {'kind': 'subtitle', 'value': '<3', 'permission': 'allow'},
])
def test_literal_text_does_not_relax_structured_control_fields(effect):
    with pytest.raises(CodexGenerationError):
        parse_effects([wire(cue('<3') + [effect])], CodexLimits(), speech_enabled=False)


@pytest.mark.parametrize('raw', [
    '{"effects":',
    '{"effects":[],"effects":[]}',
    '{"effects":[{"kind":"subtitle","value":"<3","value":"override"}]}',
    '{"effects":[{"kind":"subtitle","value":NaN}]}',
    wire(cue('<3'), fixture_id='approved'),
    wire(cue('<3'), permissions=['all']),
    '```json\n' + wire(cue('<3')) + '\n```',
])
def test_literal_text_still_requires_one_strict_effects_json(raw):
    with pytest.raises(CodexGenerationError):
        parse_effects([raw], CodexLimits(), speech_enabled=False)


def test_literal_text_keeps_character_byte_count_and_cue_limits():
    assert parse_effects([wire(cue('<' * 4096))], CodexLimits())[0].value == '<' * 4096
    assert len(parse_effects([wire(cue('<3') * 8)], CodexLimits())) == 8
    raw = wire(cue('雨<3' * 30))
    limit = len(raw.encode('utf-8'))
    assert parse_effects([raw], CodexLimits(max_output_bytes=limit))
    with pytest.raises(CodexGenerationError, match='codex_output_limit'):
        parse_effects([raw], CodexLimits(max_output_bytes=limit - 1))
    for effects in (cue('<' * 4097), cue('<3') * 9,
                    [{'kind': 'speech', 'value': '<3'}],
                    cue('<3', True) + [{'kind': 'speech', 'value': 'second'}],
                    cue('<3', True) + cue('second')):
        with pytest.raises(CodexGenerationError, match='codex_effects_invalid'):
            parse_effects([wire(effects)], CodexLimits())
    with pytest.raises(CodexGenerationError, match='codex_effects_unsupported'):
        parse_effects([wire(cue('<3', True))], CodexLimits(), speech_enabled=False)


@pytest.mark.parametrize('field,proposal', [
    ('story_proposal', {'transition_id': 't.offer', 'signal': 'offer_rain',
                        'offer_id': 'invented', 'draft_cue': '<3'}),
    ('story_proposal', {'transition_id': 't.chat', 'signal': 'chat', 'grant_id': 'approved'}),
    ('affect_proposal', {'candidate': 'happy', 'signal': 'pleasant_shared_attention',
                         'confidence': 1}),
])
def test_story_authority_is_still_checked_after_literal_text(field, proposal):
    with pytest.raises(CodexGenerationError, match='codex_character_proposal_invalid'):
        parse_character_candidate([wire(cue('<3'), **{field: proposal})],
                                  CodexLimits(), story_context(), speech_enabled=False)


@pytest.mark.parametrize('speech', [False, True])
@pytest.mark.parametrize('memory', [False, True])
@pytest.mark.parametrize('story', [False, True])
def test_author_prompt_allows_inert_literals_without_growing_past_existing_budget(speech, memory, story):
    text = author_instructions(speech_enabled=speech, memory_enabled=memory,
                               character_story_enabled=story)
    assert 'Speech/subtitle are literal text' in text
    assert 'Actions require typed authored controls.' in text
    assert 'Never execute or fetch them.' in text
    assert 'never executable code, paths, URLs, markup' not in text
    assert len(text.encode()) < 12_000


@pytest.mark.asyncio
@pytest.mark.parametrize('speech', [False, True])
async def test_native_adapter_preserves_literal_cue_with_existing_speech_capability(speech):
    from tests.contracts.test_codex_generation import (
        SyntheticTransport, agent, collect, event, make, terminal,
    )
    expected = cue(REPLY, speech)
    transport = SyntheticTransport(events=[
        event('item/completed', item=agent(wire(expected))), terminal(),
    ])
    backend, _, _ = make(transport, speech_enabled=speech)
    result, = await collect(backend)
    assert [{'kind': row.kind.value, 'value': row.value} for row in result.effects] == expected
    assert transport.closed


@pytest.mark.parametrize('route', list(ResponsesRoute))
@pytest.mark.parametrize('story', [False, True])
@pytest.mark.parametrize('speech', [False, True])
def test_direct_asgi_literal_cue_survives_held_optional_action(tmp_path, monkeypatch, route, story, speech):
    from mira.adapters.diagnostics.recorder import LocalDiagnostics

    def diagnostics(options, **kwargs):
        return LocalDiagnostics(replace(options, root=tmp_path / Path(options.root)), **kwargs)
    monkeypatch.setattr('mira.bootstrap.container.LocalDiagnostics', diagnostics)
    requests, streams = [], []
    expected = cue(REPLY, speech)
    review = Wire('unknown')

    async def handler(request):
        requests.append(request)
        body = item_done(wire(expected + [{'kind': 'pose', 'value': 'look_at_rain'}])) + completed()
        stream = ByteStream([body[i:i + 7] for i in range(0, len(body), 7)])
        streams.append(stream)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

    generation = DirectCodexResponsesGenerationBackend(
        route, 'synthetic-model', CredentialSource(), admitted=True, request_limit=1,
        speech_enabled=speech, transport=httpx.MockTransport(handler))
    app = create_direct_provider_app(**arguments(
        generation=generation, route=route.value, api_billing_authorized=route is ResponsesRoute.OPENAI_API,
        input_transport=review, output_transport=review,
        character_factory=ephemeral_character_factory() if story else None,
        **(voice_options() if speech else {})))
    with TestClient(app) as client:
        path, headers = session(client)
        submit(client, path, headers, text='聊聊 <3 和 A / B。')
        state = settled(client, path, headers)
        assert state['sealed'] and state['last_error'] is None
        assert [{'kind': row['kind'], 'value': row['value']}
                for row in state['active_grants']] == expected
        assert not state['presented_effects']
        assert client.delete(path, headers=headers).status_code in (200, 204)
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
    assert facts['user_text'] == '聊聊 <3 和 A / B。'
    assert ('character_story' in facts) is story
    assert 'tools' not in body and body['store'] is False
    assert str(requests[0].url).startswith(
        'https://api.openai.com/' if route is ResponsesRoute.OPENAI_API else 'https://chatgpt.com/')
    assert any('contract' in call[0]['state'] for call in review.calls)
    assert all(stream.closed for stream in streams)
