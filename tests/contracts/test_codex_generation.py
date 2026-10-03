"""Synthetic pinned app-server fixtures; never starts a real Codex process."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from mira.adapters.generation.codex_app_server import (
    CodexAppServerGenerationBackend, CodexGenerationError, CodexLimits, CodexRuntime,
)
from mira.application.contracts import GenerationContext
from mira.domain.models import EffectKind

FLAGS = ('apps', 'plugins', 'browser_use', 'computer_use', 'multi_agent', 'shell_tool',
         'image_generation', 'tool_suggest', 'sleep_tool', 'token_budget')
RUNTIME = CodexRuntime(Path('/synthetic/codex'), Path('/synthetic/home'), Path('/synthetic/run'))
CONTEXT = GenerationContext('请陪我听雨。', ('请陪我听雨。',), (), 7)
OUTPUT = {'effects': [{'kind': 'speech', 'value': '我们一起听雨。'},
                      {'kind': 'subtitle', 'value': '雨声很轻。'},
                      {'kind': 'pose', 'value': 'look_at_rain'}]}


def event(method, **params):
    return {'method': method, 'params': {'threadId': 'thread-1', 'turnId': 'turn-1', **params}}


def agent(text=None, **extra):
    return {'id': 'item-1', 'type': 'agentMessage',
            'text': json.dumps(OUTPUT, ensure_ascii=False) if text is None else text, **extra}


def terminal(status='completed', items=None):
    return event('turn/completed', turn={'id': 'turn-1', 'items': items or [],
                                       'status': status, 'error': None})


class SyntheticTransport:
    def __init__(self, *, events=None, config_mutation=None, thread_mutation=None,
                 initialize_mutation=None, account_type='chatgpt'):
        self.events = events if events is not None else [
            event('item/started', item=agent('')),
            event('item/agentMessage/delta', itemId='item-1', delta=agent()['text']),
            event('item/completed', item=agent()), terminal(),
        ]
        self.queue = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.interrupted = False
        self.turn_started = asyncio.Event()
        self.config_mutation = config_mutation
        self.thread_mutation = thread_mutation
        self.initialize_mutation = initialize_mutation
        self.account_type = account_type

    def emit(self, message):
        self.queue.put_nowait(json.dumps(message).encode() + b'\n')

    async def send(self, message):
        self.sent.append(message)
        method, rid = message['method'], message.get('id')
        if method == 'initialized':
            return
        if method == 'initialize':
            result = {'userAgent': 'codex/0.159.2 (linux)', 'codexHome': '/synthetic/home',
                      'platformFamily': 'unix', 'platformOs': 'linux'}
            if self.initialize_mutation:
                self.initialize_mutation(result)
        elif method == 'config/read':
            result = {'config': {'features': dict.fromkeys(FLAGS, False), 'mcp_servers': {},
                                 'web_search': 'disabled', 'model': 'gpt-6-luna',
                                 'model_provider': 'openai', 'forced_login_method': 'chatgpt',
                                 'approval_policy': 'never', 'sandbox_mode': 'read-only'},
                      'origins': {}, 'layers': None}
            result['config']['features']['respect_system_proxy'] = True
            if self.config_mutation:
                self.config_mutation(result)
        elif method == 'account/read':
            result = {'account': {'type': self.account_type}, 'requiresOpenaiAuth': True}
        elif method == 'thread/start':
            result = {'model': 'gpt-6-luna', 'modelProvider': 'openai',
                      'cwd': '/synthetic/run', 'approvalPolicy': 'never',
                      'approvalsReviewer': 'user', 'sandbox': {'type': 'readOnly'},
                      'instructionSources': [], 'runtimeWorkspaceRoots': [],
                      'thread': {'id': 'thread-1', 'cliVersion': '0.159.2', 'ephemeral': True,
                                 'environments': [], 'model': 'gpt-6-luna',
                                 'modelProvider': 'openai', 'turns': [], 'path': None}}
            if self.thread_mutation:
                self.thread_mutation(result)
        elif method == 'turn/start':
            result = {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': []}}
            self.emit({'id': rid, 'result': result})
            self.turn_started.set()
            for message in self.events:
                self.emit(message)
            return
        elif method == 'turn/interrupt':
            self.interrupted = True
            self.emit({'id': rid, 'result': {}})
            self.emit(terminal('interrupted'))
            return
        else:
            raise AssertionError(f'Unexpected outbound method {method}')
        self.emit({'id': rid, 'result': result})

    async def receive(self):
        return await self.queue.get()

    async def close(self):
        self.closed = True


class Factory:
    def __init__(self, transport):
        self.transport = transport
        self.calls = []

    async def __call__(self, runtime, limits):
        self.calls.append((runtime, limits))
        return self.transport


def make(transport=None, **kw):
    transport = transport or SyntheticTransport()
    factory = Factory(transport)
    defaults = dict(runtime=RUNTIME, admitted=True, request_limit=1,
                    transport_factory=factory)
    defaults.update(kw)
    return CodexAppServerGenerationBackend(**defaults), transport, factory


async def collect(backend, context=CONTEXT):
    return [item async for item in backend.generate(context)]


@pytest.mark.asyncio
async def test_default_off_never_starts_transport():
    backend, _, factory = make(admitted=False)
    with pytest.raises(CodexGenerationError, match='codex_not_admitted'):
        await collect(backend)
    assert not factory.calls


@pytest.mark.asyncio
async def test_zero_budget_never_starts_transport():
    backend, _, factory = make(request_limit=0)
    with pytest.raises(CodexGenerationError, match='codex_budget_exhausted'):
        await collect(backend)
    assert not factory.calls


@pytest.mark.asyncio
async def test_complete_output_has_distinct_effects_and_local_origin():
    backend, transport, _ = make()
    result = await collect(backend)
    assert len(result) == 1
    assert [e.kind for e in result[0].effects] == [EffectKind.SPEECH, EffectKind.SUBTITLE,
                                                EffectKind.POSE]
    assert result[0].fixture_id.startswith('codex-origin:')
    assert result[0].fixture_id not in ('hello', 'camera', 'quiet')
    assert transport.closed
    calls = {m['method']: m.get('params') for m in transport.sent}
    assert calls['initialize']['capabilities']['experimentalApi'] is True
    assert calls['config/read'] == {'includeLayers': False}
    thread = calls['thread/start']
    assert thread['model'] == 'gpt-6-luna'
    assert thread['allowProviderModelFallback'] is False
    assert thread['ephemeral'] is True
    for key in ('environments', 'dynamicTools', 'selectedCapabilityRoots'):
        assert thread[key] == []
    turn = calls['turn/start']
    assert turn['environments'] == []
    assert turn['effort'] == 'low'
    assert turn['outputSchema']['additionalProperties'] is False
    assert '请陪我听雨。' in turn['input'][0]['text']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['failed', 'interrupted', 'inProgress', 'cancelled'])
async def test_noncompleted_terminal_never_yields(status):
    backend, transport, _ = make(SyntheticTransport(events=[
        event('item/completed', item=agent()), terminal(status)]))
    with pytest.raises(CodexGenerationError):
        await collect(backend)
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    '{"effects":', '{"effects":[],"effects":[]}',
    '{"effects":[{"kind":"media","value":"trip_photo"}]}',
    '{"effects":[{"kind":"pose","value":"run_arbitrary"}]}',
    '{"effects":[{"kind":"scene","value":"https://example.org"}]}',
    '{"effects":[{"kind":"speech","value":"hello","id":"approved"}]}',
    '{"effects":[{"kind":"speech","value":"```run()```"}]}',
    '{"effects":[{"kind":"speech","value":"file:///private/data"}]}',
    '{"effects":[],"fixture_id":"hello"}',
])
async def test_malformed_or_unsupported_effects_never_yield(body):
    backend, transport, _ = make(SyntheticTransport(events=[
        event('item/completed', item=agent(body)), terminal()]))
    with pytest.raises(CodexGenerationError):
        await collect(backend)
    assert transport.closed


@pytest.mark.asyncio
async def test_async_delivery_is_candidate_never_external_message():
    backend, _, _ = make(SyntheticTransport(events=[
        event('item/started', item=agent(delivery='async')),
        event('item/completed', item=agent(delivery='async')), terminal()]))
    result = await collect(backend)
    assert len(result) == 1
    assert result[0].effects[0].kind == EffectKind.SPEECH


@pytest.mark.asyncio
@pytest.mark.parametrize('forbidden', [
    event('item/completed', item=agent(delivery='async', questions=[{'id': 'q'}])),
    {'id': 987, 'method': 'item/tool/requestUserInput', 'params': {}},
    {'id': 988, 'method': 'item/commandExecution/requestApproval', 'params': {}},
    event('item/completed', item={'type': 'commandExecution', 'id': 'x'}),
    event('item/completed', item={'type': 'dynamicToolCall', 'id': 'x'}),
    event('model/rerouted', toModel='expensive'),
    event('surprise/event'), event('error', message='private provider failure'),
])
async def test_requests_tools_unknown_events_and_reroutes_fail_closed(forbidden):
    backend, transport, _ = make(SyntheticTransport(events=[forbidden,
        event('item/completed', item=agent()), terminal()]))
    with pytest.raises(CodexGenerationError) as caught:
        await collect(backend)
    assert 'private provider failure' not in str(caught.value)
    assert transport.interrupted
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    lambda r: r['config']['features'].update(apps=True),
    lambda r: r['config']['features'].pop('shell_tool'),
    lambda r: r['config'].update(mcp_servers={'unsafe': {}}),
    lambda r: r['config'].update(web_search='cached'),
    lambda r: r['config'].update(model_provider='other'),
])
async def test_config_drift_blocks_before_model_turn(mutation):
    backend, transport, _ = make(SyntheticTransport(config_mutation=mutation))
    with pytest.raises(CodexGenerationError):
        await collect(backend)
    assert all(m['method'] != 'turn/start' for m in transport.sent)
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    lambda r: r.update(model='gpt-more-expensive'),
    lambda r: r['thread'].update(cliVersion='0.160.0'),
    lambda r: r['thread'].update(environments=[{'id': 'shell'}]),
    lambda r: r.update(instructionSources=['/workspace/AGENTS.md']),
])
async def test_thread_drift_blocks_before_model_turn(mutation):
    backend, transport, _ = make(SyntheticTransport(thread_mutation=mutation))
    with pytest.raises(CodexGenerationError):
        await collect(backend)
    assert all(m['method'] != 'turn/start' for m in transport.sent)


@pytest.mark.asyncio
async def test_api_key_account_is_never_a_subscription_success():
    backend, transport, _ = make(SyntheticTransport(account_type='apiKey'))
    with pytest.raises(CodexGenerationError):
        await collect(backend)
    assert all(m['method'] != 'turn/start' for m in transport.sent)


@pytest.mark.asyncio
async def test_budget_reserved_before_concurrent_requests_and_no_retry():
    backend, transport, factory = make(SyntheticTransport(events=[]))
    first = asyncio.create_task(collect(backend))
    await asyncio.wait_for(transport.turn_started.wait(), 1)
    with pytest.raises(CodexGenerationError, match='codex_budget_exhausted'):
        await collect(backend)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert len(factory.calls) == 1
    assert transport.interrupted and transport.closed


@pytest.mark.asyncio
async def test_total_turn_deadline_interrupts_and_closes():
    backend, transport, _ = make(SyntheticTransport(events=[]),
                                limits=replace(CodexLimits(), turn_seconds=0.01))
    with pytest.raises(CodexGenerationError, match='codex_timeout'):
        await collect(backend)
    assert transport.interrupted and transport.closed


@pytest.mark.asyncio
async def test_reasoning_and_plan_are_ignored_without_retaining_them():
    backend, _, _ = make(SyntheticTransport(events=[
        event('item/started', item={'id': 'r', 'type': 'reasoning'}),
        event('item/reasoning/textDelta', itemId='r', delta='secret reasoning'),
        event('item/completed', item={'id': 'r', 'type': 'reasoning',
                                     'content': ['secret reasoning']}),
        event('turn/plan/updated', plan=[]),
        event('item/completed', item=agent()), terminal()]))
    result = await collect(backend)
    assert len(result) == 1
    assert 'secret reasoning' not in repr(result)
    assert 'secret reasoning' not in repr(backend)


@pytest.mark.asyncio
async def test_delta_without_completed_item_never_becomes_candidate():
    backend, _, _ = make(SyntheticTransport(events=[
        event('item/agentMessage/delta', itemId='item-1', delta=agent()['text']), terminal()]))
    with pytest.raises(CodexGenerationError):
        await collect(backend)
