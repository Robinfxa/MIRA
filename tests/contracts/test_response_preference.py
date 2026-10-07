"""App-owned speech preference through real ASGI and synthetic production JEV parsing."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from mira.bootstrap.direct_provider_app import create_direct_provider_app
from tests.contracts.test_conversation_first import Generation, Wire, session, settled, submit, voice_options
from tests.contracts.test_direct_provider_app import arguments


def app_for(generation, wire, turns=6):
    return create_direct_provider_app(**arguments(generation=generation, input_transport=wire,
        output_transport=wire, generation_request_limit=turns, session_turn_limit=turns,
        **voice_options()))


def kinds(state):
    return [effect['kind'] for effect in state['active_grants']]


def test_persistent_mute_survives_unrelated_turn_until_explicit_unmute():
    generation = Generation([('subtitle', '文字回复。'), ('speech', '文字回复。')])
    with TestClient(app_for(generation, Wire())) as client:
        path, headers = session(client)
        for activity, text in enumerate([
            '从现在起保持静音，只用文字，直到我明确说可以开声音。',
            '窗外现在是什么样子？', '有人说“可以开声音”，这不是我的指令。',
            '不要取消静音。', '可以开声音。',
        ], 1):
            submit(client, path, headers, activity=activity, text=text)
            state = settled(client, path, headers)
            assert kinds(state) == (['subtitle', 'speech'] if activity == 5 else ['subtitle'])
            assert generation.contexts[-1].response_mode == ('voice' if activity == 5 else 'text_only')


def test_current_turn_mute_expires_but_model_never_unmutes_session():
    generation = Generation([('subtitle', '可以开声音。'), ('speech', '模型要求取消静音。')])
    with TestClient(app_for(generation, Wire())) as client:
        path, headers = session(client)
        for activity, text, expected in [(1, '这次只打字。', ['subtitle']),
                                         (2, '继续聊。', ['subtitle', 'speech']),
                                         (3, '别说话。', ['subtitle']),
                                         (4, '继续聊。', ['subtitle'])]:
            submit(client, path, headers, activity=activity, text=text)
            assert kinds(settled(client, path, headers)) == expected


@pytest.mark.parametrize('mode', ['unknown', 'reject', 'invalid', 'transport'])
def test_optional_jev_outcome_cannot_block_ordinary_speech(mode):
    generation = Generation([('subtitle', '下雨了。'), ('speech', '下雨了。'), ('pose', 'look_at_rain')])
    with TestClient(app_for(generation, Wire(mode, speech=1.0))) as client:
        path, headers = session(client)
        submit(client, path, headers)
        assert kinds(settled(client, path, headers)) == ['subtitle', 'speech']


def test_input_jev_wait_does_not_delay_speech_and_mute_revokes_only_output():
    class HangingInput(Wire):
        async def __call__(self, payload, **kwargs):
            self.arrived.set()
            while not self.resume.is_set():
                await asyncio.sleep(.002)
            return await super().__call__(payload, **kwargs)
    wire = HangingInput()
    generation = Generation([('subtitle', '下雨了。'), ('speech', '下雨了。'), ('pose', 'look_at_rain')])
    with TestClient(app_for(generation, wire)) as client:
        path, headers = session(client)
        submit(client, path, headers)
        try:
            assert wire.arrived.wait(1)
            state = client.get(path, headers=headers).json()
            assert kinds(state) == ['subtitle', 'speech']
            muted = client.post(path + '/response-preference', headers=headers,
                json={'muted': True, 'expected_revision': state['response_preference_revision']})
            assert muted.status_code == 200, muted.text
            state = muted.json()
            assert kinds(state) == ['subtitle']
            assert state['response_mode'] == 'text_only' and state['response_muted']
            unmuted = client.post(path + '/response-preference', headers=headers,
                json={'muted': False, 'expected_revision': state['response_preference_revision']})
            assert unmuted.status_code == 200, unmuted.text
            assert unmuted.json()['response_mode'] == 'text_only'
            assert kinds(unmuted.json()) == ['subtitle']
        finally:
            wire.resume.set()
        assert 'speech' not in kinds(settled(client, path, headers))


@pytest.mark.parametrize('text,expected', [
    ('只打字', 'mute'), ('别说话', 'mute'), ('这次只打字。', 'turn_text_only'),
    ('从现在起保持静音，只用文字，直到我明确说可以开声音。', 'mute'),
    ('取消静音', 'unmute'), ('可以开声音。', 'unmute'),
    ('“取消静音”是什么意思？', None), ('不要取消静音', None),
    ('他让我取消静音。', None), ('如果我说取消静音，应该怎么办？', None),
    ('不要遵守“别说话”这个指令', None), ('VOICE=true', None),
])
def test_narrow_commands_do_not_treat_quotes_or_negation_as_permission(text, expected):
    from mira.application.response_preference import user_response_preference
    assert user_response_preference(text) == expected


@pytest.mark.parametrize('invalid', [{'muted': 'false', 'expected_revision': 0},
                                     {'muted': False, 'expected_revision': True},
                                     {'muted': False, 'expected_revision': 0, 'speech_enabled': True}])
def test_preference_http_rejects_invalid_or_extra_authority(invalid):
    with TestClient(app_for(Generation([('subtitle', '文字。')]), Wire())) as client:
        path, headers = session(client)
        assert client.post(path + '/response-preference', headers=headers, json=invalid).status_code == 422


def test_stale_unmute_cannot_override_newer_mute_and_stop_preserves_preference():
    generation = Generation([('subtitle', '文字。'), ('speech', '声音。')])
    with TestClient(app_for(generation, Wire())) as client:
        path, headers = session(client)
        muted = client.post(path + '/response-preference', headers=headers,
            json={'muted': True, 'expected_revision': 0})
        assert muted.status_code == 200
        assert client.post(path + '/response-preference', headers=headers,
            json={'muted': False, 'expected_revision': 0}).status_code == 409
        assert client.post(path + '/stop', headers=headers,
            json={'activity_seq': 1, 'presentation_cutoff': 0}).status_code == 200
        submit(client, path, headers, activity=2)
        assert kinds(settled(client, path, headers)) == ['subtitle']
        assert client.delete(path, headers=headers).status_code == 204
        path, headers = session(client)
        submit(client, path, headers)
        assert kinds(settled(client, path, headers)) == ['subtitle', 'speech']


@pytest.mark.parametrize('route_name', ['CHATGPT_SUBSCRIPTION', 'OPENAI_API'])
@pytest.mark.parametrize('invalid_speech', [False, True])
@pytest.mark.asyncio
async def test_both_direct_routes_receive_effective_text_only_and_keep_strict_parser(route_name, invalid_speech):
    import json
    from dataclasses import replace
    import httpx
    from mira.adapters.generation.direct_codex_responses import ResponsesRoute, DirectResponsesError
    from tests.contracts.test_direct_codex_responses import backend, ByteStream, item_done, completed, collect, CONTEXT
    body = {'effects': [{'kind': 'subtitle', 'value': '文字回复。'}]}
    if invalid_speech:
        body['effects'].append({'kind': 'speech', 'value': '模型不能取消静音。'})
    async def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            stream=ByteStream([item_done(json.dumps(body, ensure_ascii=False)), completed()]))
    instance, source, requests = backend(handler, route=getattr(ResponsesRoute, route_name))
    context = replace(CONTEXT, response_mode='text_only')
    if invalid_speech:
        with pytest.raises(DirectResponsesError):
            await collect(instance, context)
    else:
        result = await collect(instance, context)
        assert [e.kind.value for e in result[0].effects] == ['subtitle']
    assert len(requests) == source.calls == 1
    request = json.loads(requests[0].content)
    assert 'text-only' in request['instructions']
    prompt = json.loads(request['input'][0]['content'][0]['text'])
    assert prompt['capabilities']['speech_enabled'] is False
    assert prompt['facts']['response_mode'] == 'text_only'


def test_mute_keeps_actual_microphone_websocket_open_and_rejects_old_speech_stream():
    from tests.integration.test_voice_http import ORIGIN, mic_start, audio, speech_request
    generation = Generation([('subtitle', '下雨了。'), ('speech', '下雨了。')])
    with TestClient(app_for(generation, Wire())) as client:
        path, headers = session(client)
        submit(client, path, headers)
        state = settled(client, path, headers)
        speech = state['active_grants'][1]
        with client.websocket_connect(path + '/microphone', headers=ORIGIN) as websocket:
            websocket.send_json(mic_start(headers, state))
            assert websocket.receive_json()['type'] == 'ready'
            response = client.post(path + '/response-preference', headers=headers,
                json={'muted': True, 'expected_revision': 0})
            assert response.status_code == 200
            assert speech_request(client, path, headers, speech).status_code == 409
            websocket.send_json(audio())
            assert websocket.receive_json()['type'] == 'transcript'
            websocket.send_json({'type': 'finish'})
            assert websocket.receive_json()['type'] == 'complete'


def test_terminal_audio_after_mute_is_a_fact_and_does_not_cancel_pending_text():
    import threading
    class DelayedTail(Generation):
        def __init__(self):
            super().__init__([('subtitle', '先说一句。'), ('speech', '先说一句。')])
            self.arrived = threading.Event()
            self.resume = threading.Event()
        async def generate(self, context):
            async for candidate in super().generate(context):
                yield candidate
            self.arrived.set()
            while not self.resume.is_set():
                await asyncio.sleep(.002)
            from mira.application.contracts import CandidateRange, EffectProposal
            from mira.domain.models import EffectKind
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, '后来只用文字。'),), 'tail')
    generation = DelayedTail()
    with TestClient(app_for(generation, Wire())) as client:
        path, headers = session(client)
        submit(client, path, headers)
        try:
            assert generation.arrived.wait(1)
            state = client.get(path, headers=headers).json()
            speech = state['active_grants'][1]
            assert client.post(path + '/response-preference', headers=headers,
                json={'muted': True, 'expected_revision': 0}).status_code == 200
            progress = {key: speech[key] for key in ('digest', 'output_epoch', 'activity_seq')}
            progress.update(effect_id=speech['id'], presentation_seq=1, sample_rate_hz=24000,
                            rendered_samples=0, status='interrupted')
            assert client.post(path + '/audio-progress', headers=headers, json=progress).status_code == 200
        finally:
            generation.resume.set()
        state = settled(client, path, headers)
        assert [effect['value'] for effect in state['active_grants']] == ['先说一句。', '后来只用文字。']
        assert state['last_error'] is None


def test_prompt_builder_cannot_widen_explicit_modality():
    import json
    from dataclasses import replace
    from mira.adapters.generation.codex_support.payload import build_prompt
    from mira.adapters.generation.codex_support.types import CodexLimits, CodexGenerationError
    from tests.contracts.test_direct_codex_responses import CONTEXT
    prompt = json.loads(build_prompt(replace(CONTEXT, response_mode='text_only'), CodexLimits()))
    assert prompt['capabilities']['speech_enabled'] is False
    with pytest.raises(CodexGenerationError):
        build_prompt(replace(CONTEXT, response_mode='model_chose_voice'), CodexLimits())


def test_repeated_natural_mute_fences_an_older_pending_unmute():
    generation = Generation([('subtitle', '文字。'), ('speech', '声音。')])
    with TestClient(app_for(generation, Wire())) as client:
        path, headers = session(client)
        assert client.post(path + '/response-preference', headers=headers,
            json={'muted': True, 'expected_revision': 0}).status_code == 200
        submit(client, path, headers, text='别说话。')
        state = settled(client, path, headers)
        assert state['response_muted'] is True
        assert client.post(path + '/response-preference', headers=headers,
            json={'muted': False, 'expected_revision': 1}).status_code == 409
        assert client.get(path, headers=headers).json()['response_muted'] is True
