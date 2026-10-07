"""Real direct ASGI recovery with synthetic HTTP/JEV/audio only, never live providers."""
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mira.adapters.diagnostics.export import export_diagnostics
from mira.adapters.diagnostics.recorder import LocalDiagnostics
from mira.adapters.generation.direct_codex_responses import (
    DirectCodexResponsesGenerationBackend, DirectResponsesError, ResponsesRoute,
)
from mira.bootstrap.character_story import ephemeral_character_factory
from mira.bootstrap.development_voice import DevelopmentVoiceLimits
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.bootstrap.providers import GoogleVoiceProviders
from tests.contracts.test_conversation_first import Wire, session, settled, submit
from tests.contracts.test_direct_codex_responses import (
    ByteStream, backend, collect, completed, event, response,
)
from tests.contracts.test_direct_provider_app import arguments
from tests.integration.test_voice_http import (
    ORIGIN, Stt, Tts, audio as microphone_audio, mic_start, speech_request,
)
from tools.live_provider import ApiCredentialSource


BAD_CANDIDATES = [
    pytest.param('{"PRIVATE_GENERATED_SECRET":', 'codex_json_invalid', 'syntax',
                 'bare_object', id='syntax'),
    pytest.param('{"PRIVATE_GENERATED_SECRET":1,"PRIVATE_GENERATED_SECRET":2}',
                 'codex_json_invalid', 'duplicate_key', 'bare_object', id='duplicate'),
    pytest.param('{"PRIVATE_GENERATED_SECRET":NaN}', 'codex_json_invalid', 'nonfinite',
                 'bare_object', id='nonfinite'),
    pytest.param('```json\n{"PRIVATE_GENERATED_SECRET":1}\n```', 'codex_json_invalid',
                 'syntax', 'markdown_fence', id='markdown'),
    pytest.param('{"effects":[{"kind":"subtitle","value":1e999}]}',
                 'candidate_value_invalid', None, None, id='overflow-effect'),
    pytest.param('{"effects":[{"kind":"subtitle","value":"synthetic"}],'
                 '"affect_proposal":{"candidate":"happy","signal":"pleasant_shared_attention",'
                 '"PRIVATE_GENERATED_SECRET":1e999}}',
                 'candidate_value_invalid', None, None, id='overflow-proposal'),
    pytest.param('{"effects":[{"kind":"subtitle","value":"\\ud800"}]}',
                 'candidate_value_invalid', None, None, id='escaped-surrogate'),
]


def complete_wire(text):
    """Match observed event counts/shapes, without claiming to recreate unseen content."""
    progress = event('response.in_progress', {'type': 'response.in_progress'})
    delta = event('response.output_text.delta', {
        'type': 'response.output_text.delta', 'output_index': 0, 'content_index': 0,
        'item_id': 'synthetic-final', 'delta': text,
    })
    item = {'id': 'synthetic-final', 'type': 'message', 'role': 'assistant',
            'phase': 'final_answer', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}
    done = event('response.output_item.done', {
        'type': 'response.output_item.done', 'output_index': 0, 'item': item,
    })
    return progress * 41 + delta + done + completed(output=[])


@pytest.mark.parametrize('mode', ['text', 'voice-allowed', 'voice-uncertain'])
@pytest.mark.parametrize('bad,reason,json_kind,shape', BAD_CANDIDATES)
def test_completed_invalid_candidate_then_new_turn_recovers_independent_text_and_voice(
        tmp_path, monkeypatch, mode, bad, reason, json_kind, shape):
    # Bind this recorder absolutely without changing process cwd: other tests may
    # still have non-blocking diagnostic workers draining their own relative paths.
    def create_diagnostics(options, **kwargs):
        return LocalDiagnostics(replace(options, root=tmp_path / Path(options.root)), **kwargs)
    monkeypatch.setattr('mira.bootstrap.container.LocalDiagnostics', create_diagnostics)
    voice = mode != 'text'
    spoken = voice  # Optional JEV uncertainty cannot gate ordinary speech.
    tts, stt = Tts(), Stt()
    review = Wire(speech=.5 if mode == 'voice-uncertain' else 0.0)
    requests, streams = [], []
    good_effects = [{'kind': 'subtitle', 'value': '我们接着聊，今天想聊什么？'}]
    if voice:
        good_effects.append({'kind': 'speech', 'value': '我们接着聊，今天想聊什么？'})
    good = json.dumps({'effects': good_effects}, ensure_ascii=False)

    async def handler(request):
        document = json.loads(request.content)
        requests.append(document)
        assert request.url.host == 'chatgpt.com'
        assert set(document) == {'model', 'instructions', 'input', 'store', 'stream', 'service_tier'}
        assert document['service_tier'] == 'priority'
        assert 'Return only one JSON object with effects.' in document['instructions']
        assert 'Speak in first person as Mira' in document['instructions']
        assert ('explicitly text-only' in document['instructions']) is (not voice)
        wire = complete_wire(bad if len(requests) == 1 else good)
        stream = ByteStream([wire[i:i + 7] for i in range(0, len(wire), 7)])
        streams.append(stream)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

    async def close_voice():
        pass

    async def forbid_subprocess(*_args, **_kwargs):
        raise AssertionError('Direct generation must not start a native subprocess')

    monkeypatch.setattr('asyncio.create_subprocess_exec', forbid_subprocess)
    generation = DirectCodexResponsesGenerationBackend(
        ResponsesRoute.CHATGPT_SUBSCRIPTION, 'gpt-6-luna',
        ApiCredentialSource(SecretStr('synthetic-direct-token')), admitted=True,
        request_limit=2, speech_enabled=voice, transport=httpx.MockTransport(handler))
    options = (dict(voice_required=True,
                    voice_factory=lambda: GoogleVoiceProviders(stt, tts, close_voice),
                    voice_usage_limits=DevelopmentVoiceLimits(1, 1, 10, 10)) if voice else {})
    app = create_direct_provider_app(**arguments(
        generation=generation, input_transport=review, output_transport=review,
        generation_request_limit=2, session_turn_limit=2,
        character_factory=ephemeral_character_factory(), **options))
    with TestClient(app) as client:
        path, headers = session(client)
        submit(client, path, headers, text='PRIVATE_USER_FAILED_TURN')
        first = settled(client, path, headers)
        assert first['last_error'] == 'invalid_response'
        assert first['active_grants'] == []
        assert len(requests) == 1 and streams[0].closed
        assert review.calls == [] and tts.calls == []

        next_text = '我们继续聊。'
        if voice:
            with client.websocket_connect(path + '/microphone', headers=ORIGIN) as ws:
                ws.send_json(mic_start(headers, first))
                assert ws.receive_json()['type'] == 'ready'
                ws.send_json(microphone_audio())
                assert ws.receive_json()['type'] == 'transcript'
                ws.send_json({'type': 'finish'})
                transcript = ws.receive_json()
                assert transcript['type'] == 'complete' and transcript['had_final'] is True
                next_text = transcript['text']
                assert next_text == '你好'
            assert stt.closed.is_set() and len(stt.packets) == 1
            assert len(requests) == 1  # Recognition alone does not submit a new turn.
        submit(client, path, headers, activity=2, text=next_text)
        second = settled(client, path, headers)
        assert second['sealed'] and second['last_error'] is None
        assert [g['kind'] for g in second['active_grants']] == (
            ['subtitle', 'speech'] if spoken else ['subtitle'])
        subtitle = second['active_grants'][0]
        assert subtitle['value'] == good_effects[0]['value']
        assert subtitle['cue_speech_id'] is None
        receipt = {key: subtitle[key] for key in ('digest', 'output_epoch', 'activity_seq')}
        receipt.update(effect_id=subtitle['id'], presentation_seq=1)
        assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
        if spoken:
            audio = speech_request(client, path, headers, second['active_grants'][1])
            assert audio.status_code == 200
            assert json.loads(audio.text.splitlines()[-1])['type'] == 'complete'
            assert len(tts.calls) == 1 and tts.calls[0][0] == good_effects[1]['value']
        else:
            assert tts.calls == []
        assert review.calls == []
        assert all('contract' not in call[0]['state'] for call in review.calls)
        assert len(requests) == 2 and all(stream.closed for stream in streams)
        next_facts = json.loads(requests[1]['input'][0]['content'][0]['text'])['facts']
        assert next_facts['user_inputs'] == ['PRIVATE_USER_FAILED_TURN', next_text]
        assert next_facts['presented_effects'] == []
        assert 'PRIVATE_GENERATED_SECRET' not in json.dumps(next_facts)
        assert client.delete(path, headers=headers).status_code in (200, 204)
    assert not app.state.container.sessions._sessions
    assert app.state.container.diagnostics.flush()
    target = tmp_path / 'diagnostics.zip'
    manifest = export_diagnostics(tmp_path / 'var' / 'diagnostics', target)
    assert manifest['raw_count'] == 0
    with zipfile.ZipFile(target) as bundle:
        encoded = bundle.read('events.jsonl')
        assert b'PRIVATE_' not in b''.join(bundle.read(name) for name in bundle.namelist())
    records = [json.loads(line) for line in encoded.splitlines()]
    failures = [r for r in records if r['stage'] == 'generation' and r['outcome'] == 'failed']
    assert len(failures) == 1
    diag = failures[0]['generation_diagnostic']
    assert failures[0]['code'] == 'invalid_response'
    assert diag['phase'] == 'validation' and diag['reason'] == reason
    assert diag['http_status'] == 200 and diag['terminal_status'] == 'completed'
    assert diag['event_count'] == 44 and diag['completed_message_count'] == 1
    assert diag['delta_message_count'] == 1 and diag['snapshot_output_kind'] == 'empty'
    assert diag['json_failure_kind'] == json_kind and diag['wrapper_shape'] == shape
    assert len([r for r in records if r['stage'] == 'generation'
                and r['outcome'] == 'succeeded']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,phase,reason', [
    ('network', 'transport', 'transport'),
    ('sse-json', 'sse', 'json_shape'),
    ('sse-utf8', 'sse', 'utf8'),
])
async def test_candidate_validation_boundary_does_not_relabel_network_or_sse(failure, phase, reason):
    async def handler(request):
        if failure == 'network':
            raise httpx.ConnectError('PRIVATE_NETWORK_SECRET', request=request)
        body = (b'event: response.completed\ndata: PRIVATE_SSE_SECRET\n\n' if failure == 'sse-json'
                else b'event: response.completed\ndata: \xffPRIVATE_SSE_SECRET\n\n')
        return response(body)
    instance, source, requests = backend(handler)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    error = raised.value
    assert error.code == ('unavailable' if failure == 'network' else 'invalid_response')
    assert error.stage == phase and error.reason == reason
    assert error.generation_diagnostic.json_failure_kind is None
    assert error.generation_diagnostic.wrapper_shape is None
    assert len(requests) == source.calls == 1
    assert 'PRIVATE' not in repr(error) + repr(error.generation_diagnostic)
