"""Additional offline adversarial verification; not retroactive RED evidence."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from mira.adapters.generation.codex_app_server import (
    CodexGenerationError, CodexLimits, CodexRuntime,
)
from mira.adapters.generation.codex_support.process import StdioProcessTransport
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.contracts import GenerationContext, ReviewVerdict
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind
from tests.contracts.test_codex_generation import (
    CONTEXT, RUNTIME, SyntheticTransport, agent, collect, event, make, terminal,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('message', [
    {'id': 999, 'result': {}},
    event('item/completed', threadId='other', item=agent()),
    event('item/completed', turnId='other', item=agent()),
    event('item/completed', item=agent(memoryCitation={'secret': 'prior history'})),
    event('item/completed', item=agent(phase='new-phase')),
    event('item/completed', item={'id': 'x', 'type': 'functionCallOutput',
                                 'namespace': 'clock', 'name': 'sleep'}),
    event('item/completed', item={'id': 'x', 'type': 'functionCallOutput',
                                 'namespace': None, 'name': 'request_user_input'}),
    event('item/completed', item={'id': 'x', 'type': 'hookPrompt', 'fragments': []}),
    event('configWarning', message='private config path'),
    event('remoteControl/status/changed', status='connected'),
    event('account/updated', authMode='apikey'),
])
async def test_adversarial_protocol_never_yields(message):
    backend, transport, _ = make(SyntheticTransport(events=[message, terminal()]))
    with pytest.raises(CodexGenerationError):
        await collect(backend)
    assert transport.interrupted and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [False, None, [], {'type': 'systemError'}])
async def test_bad_thread_status_never_yields(status):
    backend, _, _ = make(SyntheticTransport(events=[
        event('thread/status/changed', status=status), terminal()]))
    with pytest.raises(CodexGenerationError):
        await collect(backend)


@pytest.mark.asyncio
async def test_full_config_pin_rejects_even_unrelated_drift():
    runtime = replace(RUNTIME, expected_config_sha256='0' * 64)
    backend, transport, _ = make(runtime=runtime)
    with pytest.raises(CodexGenerationError, match='codex_config_drift'):
        await collect(backend)
    assert all(m['method'] != 'thread/start' for m in transport.sent)


@pytest.mark.asyncio
async def test_defaults_null_model_provider_are_allowed_but_thread_is_exact():
    def mutate(result):
        result['config'].update(model=None, model_provider=None, forced_login_method=None)
    backend, _, _ = make(SyntheticTransport(config_mutation=mutate))
    assert len(await collect(backend)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['hooks', 'notify', 'model_providers', 'openai_base_url',
                                   'chatgpt_base_url', 'model_instructions_file'])
async def test_custom_backend_routes_and_hooks_block_before_turn(field):
    backend, transport, _ = make(SyntheticTransport(
        config_mutation=lambda result: result['config'].update({field: 'unexpected'})))
    with pytest.raises(CodexGenerationError, match='codex_config_drift'):
        await collect(backend)
    assert all(m['method'] != 'turn/start' for m in transport.sent)


@pytest.mark.asyncio
async def test_output_size_is_bounded_before_terminal_completion():
    backend, transport, _ = make(SyntheticTransport(events=[
        event('item/agentMessage/delta', itemId='item-1', delta='x' * 500), terminal()]),
        limits=replace(CodexLimits(), max_output_bytes=128))
    with pytest.raises(CodexGenerationError, match='codex_output_limit'):
        await collect(backend)
    assert transport.interrupted


@pytest.mark.asyncio
async def test_prompt_bound_blocks_before_process_and_does_not_truncate_facts():
    backend, _, factory = make(limits=replace(CodexLimits(), max_prompt_bytes=1024))
    context = replace(CONTEXT, user_inputs=('x' * 2048,))
    with pytest.raises(CodexGenerationError, match='codex_prompt_limit'):
        await collect(backend, context)
    assert factory.calls == []


@pytest.mark.asyncio
async def test_request_ids_are_monotonic_and_candidate_is_not_a_fixture():
    backend, transport, _ = make()
    candidate, = await collect(backend)
    ids = [m['id'] for m in transport.sent if 'id' in m]
    assert ids == list(range(1, len(ids) + 1))
    observation = await FixtureReviewBackend().review(CONTEXT, candidate)
    assert observation.verdict == ReviewVerdict.REJECT


@pytest.mark.asyncio
async def test_completed_snapshot_is_deduplicated_without_repeating_effects():
    backend, _, _ = make(SyntheticTransport(events=[
        event('item/completed', item=agent()), terminal(items=[agent()])]))
    candidate, = await collect(backend)
    assert len(candidate.effects) == 3


@pytest.mark.asyncio
async def test_partial_delta_cannot_be_silently_rewritten_at_completion():
    backend, _, _ = make(SyntheticTransport(events=[
        event('item/agentMessage/delta', itemId='item-1', delta='private partial text'),
        event('item/completed', item=agent()), terminal()]))
    with pytest.raises(CodexGenerationError, match='codex_output_inconsistent'):
        await collect(backend)


@pytest.mark.asyncio
async def test_multiple_agent_messages_all_enter_same_candidate():
    first = agent('{"effects":[{"kind":"speech","value":"你好。"}]}', delivery='async')
    second = agent('{"effects":[{"kind":"subtitle","value":"你好。"}]}')
    second['id'] = 'item-2'
    backend, _, _ = make(SyntheticTransport(events=[
        event('item/completed', item=first), event('item/completed', item=second), terminal()]))
    candidate, = await collect(backend)
    assert [e.kind for e in candidate.effects] == [EffectKind.SPEECH, EffectKind.SUBTITLE]


@pytest.mark.asyncio
async def test_known_plan_and_clock_output_is_ignored_and_never_transmitted():
    backend, transport, _ = make(SyntheticTransport(events=[
        event('item/completed', item={'id': 'clock', 'type': 'functionCallOutput',
                                     'name': 'curr_time', 'namespace': 'clock',
                                     'output': 'known clock value'}),
        event('item/completed', item={'id': 'plan', 'type': 'functionCallOutput',
                                     'name': 'update_plan', 'namespace': None,
                                     'output': 'known plan value'}),
        event('item/completed', item=agent()), terminal()]))
    candidate, = await collect(backend)
    assert 'known clock value' not in repr(candidate)
    assert 'known plan value' not in repr(transport.sent)


@pytest.mark.asyncio
async def test_context_rebuild_preserves_accepted_presented_and_audio_distinctions():
    accepted = Effect('a', EffectKind.SPEECH, '尚未播放。', 'da', 7, 1)
    presented = Effect('p', EffectKind.SUBTITLE, '已经显示。', 'dp', 6, 1)
    progress = AudioProgress('a', 'da', 7, 1, 1, 24000, 64, AudioStatus.RENDERED)
    context = GenerationContext('继续。', ('可靠旧输入。', '继续。'), (presented,), 7,
                                (accepted,), (progress,))
    backend, transport, _ = make()
    await collect(backend, context)
    turn = next(m for m in transport.sent if m['method'] == 'turn/start')
    facts = json.loads(turn['params']['input'][0]['text'])['facts']
    assert facts['user_inputs'] == ['可靠旧输入。', '继续。']
    assert facts['accepted_prefix'][0]['id'] == 'a'
    assert facts['presented_effects'][0]['id'] == 'p'
    assert facts['audio_progress'][0]['status'] == 'rendered'
    assert facts['output_epoch'] == 7


@pytest.mark.asyncio
async def test_synthetic_actual_process_runs_full_adapter_path(tmp_path):
    import sys
    transport_fixture = SyntheticTransport()
    replies = {}
    for method in ('initialize', 'config/read', 'account/read', 'thread/start'):
        await transport_fixture.send({'id': 1, 'method': method})
        replies[method] = json.loads(await transport_fixture.receive())['result']
    replies['turn/start'] = {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': []}}
    events = transport_fixture.events
    source = f'''import json,sys,time
replies=json.loads({json.dumps(replies)!r})
events=json.loads({json.dumps(events)!r})
for line in sys.stdin:
    message=json.loads(line)
    method=message['method']
    if method=='initialized': continue
    if method not in replies: break
    messages=[{{'id':message['id'],'result':replies[method]}}]
    if method=='turn/start': messages += events
    sys.stdout.write(''.join(json.dumps(m)+'\\n' for m in messages)); sys.stdout.flush()
'''
    created = []

    async def factory(_runtime, limits):
        transport = await StdioProcessTransport._spawn(Path(sys.executable).resolve(),
                                                       ('-c', source), tmp_path, {}, limits)
        created.append(transport)
        return transport

    backend, _, _ = make(transport_factory=factory)
    candidate, = await collect(backend)
    assert len(candidate.effects) == 3
    assert created[0]._process.returncode is not None


def test_runtime_environment_is_immutable_and_never_discovers_values(tmp_path):
    env = {'HTTPS_PROXY': 'https://approved.example', 'SSL_CERT_FILE': '/approved/ca.pem'}
    runtime = CodexRuntime(tmp_path / 'codex', tmp_path / 'home', tmp_path / 'run', env)
    env['HTTPS_PROXY'] = 'https://changed.example'
    assert runtime.environment['HTTPS_PROXY'] == 'https://approved.example'
    assert 'approved.example' not in repr(runtime)


@pytest.mark.asyncio
async def test_native_chatgpt_backend_default_is_allowed():
    backend, _, _ = make(SyntheticTransport(config_mutation=lambda result:
        result['config'].update(chatgpt_base_url='https://chatgpt.com/backend-api/')))
    assert len(await collect(backend)) == 1


@pytest.mark.asyncio
async def test_premium_thread_service_tier_cannot_silently_survive():
    backend, transport, _ = make(SyntheticTransport(
        thread_mutation=lambda result: result.update(serviceTier='priority')))
    with pytest.raises(CodexGenerationError, match='codex_thread_isolation_drift'):
        await collect(backend)
    assert all(m['method'] != 'turn/start' for m in transport.sent)
