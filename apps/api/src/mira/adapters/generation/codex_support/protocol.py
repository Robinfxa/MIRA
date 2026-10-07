"""Private v0.159.2 state machine: no generic RPC or external-message surface."""
from __future__ import annotations

import asyncio
import hashlib

from .payload import author_instructions, canonical, output_schema, parse_effects, strict_json
from .types import (
    DISABLED_FEATURES, MODEL, PINNED_VERSION, CodexGenerationError, CodexLimits, CodexRuntime,
    CodexTransport,
)

# Reasoning contents and plan bodies are ignored immediately, never kept in a log/history.
_IGNORED_TURN_EVENTS = frozenset((
    'item/reasoning/textDelta', 'item/reasoning/summaryTextDelta',
    'item/reasoning/summaryPartAdded', 'item/plan/delta', 'turn/plan/updated',
    'thread/tokenUsage/updated',
))
_ALLOWED_ITEM_KINDS = frozenset(('agentMessage', 'userMessage', 'reasoning', 'plan',
                                'functionCallOutput'))
_REMOTE_CONTROL_STATUSES = frozenset(('disabled', 'connecting', 'connected', 'errored'))


def _require(condition: bool, code='codex_protocol_invalid'):
    if not condition:
        raise CodexGenerationError(code)


def _identifier(value):
    _require(type(value) is str and 0 < len(value) <= 160)
    return value


def _verify_thread(thread: dict, runtime: CodexRuntime):
    _require(type(thread) is dict)
    _identifier(thread.get('id'))
    _require(thread.get('cliVersion') == PINNED_VERSION, 'codex_version_drift')
    _require(thread.get('ephemeral') is True and thread.get('environments') == [],
             'codex_thread_isolation_drift')
    _require(thread.get('model') in (None, MODEL) and thread.get('modelProvider') == 'openai',
             'codex_model_drift')
    _require(thread.get('path') is None and thread.get('turns') == [],
             'codex_thread_history_drift')
    if 'cwd' in thread:
        _require(thread['cwd'] == str(runtime.runtime_cwd), 'codex_thread_isolation_drift')


class _ConfigValidationError(CodexGenerationError):
    def __init__(self, check_code: str):
        super().__init__('codex_config_drift')
        self.check_code = check_code


def _config_require(condition: bool, check_code: str) -> None:
    if not condition:
        raise _ConfigValidationError(check_code)


def _verify_config(result, runtime):
    config = result.get('config')
    _config_require(type(config) is dict, 'config_object')
    if runtime.expected_config_sha256 is not None:
        _config_require(hashlib.sha256(canonical(config)).hexdigest() == runtime.expected_config_sha256,
                 'config_digest')
    features = config.get('features')
    _config_require(type(features) is dict and all(features.get(flag) is False
                                           for flag in DISABLED_FEATURES), 'features_disabled')
    development = runtime.development_context
    _config_require(features.get('respect_system_proxy') is (None if development else True),
             'proxy_policy')
    if development is not None:
        _config_require((config.get('orchestrator') or {}).get('mcp', {}).get('enabled') is False
                 and (config.get('cloud') or {}).get('skills', {}).get('enabled') is False,
                 'managed_capabilities')
        route = config.get('openai_base_url')
        _config_require(type(route) is str and hashlib.sha256(route.encode()).hexdigest()
                 == development.route_value_sha256, 'managed_route')
    _config_require(type(config.get('mcp_servers')) is dict and not config['mcp_servers'],
             'mcp_empty')
    _config_require(config.get('web_search') == 'disabled', 'web_search_disabled')
    _config_require(config.get('model') in (None, MODEL)
             and config.get('model_provider') in (None, 'openai')
             and config.get('forced_login_method') in (None, 'chatgpt'), 'model_provider_auth')
    # Never accept caller-customized backend routes or executable hooks, even under a digest.
    _config_require(config.get('chatgpt_base_url') in (None, 'https://chatgpt.com/backend-api',
                                                       'https://chatgpt.com/backend-api/'),
             'chatgpt_route')
    fields = ('hooks', 'notify', 'model_providers', 'model_instructions_file',
              'experimental_thread_store_endpoint')
    if development is None:
        fields += ('openai_base_url',)
    for field in fields:
        _config_require(config.get(field) in (None, {}, [], ''), 'forbidden_' + field)


class Session:
    def __init__(self, transport: CodexTransport, runtime: CodexRuntime, limits: CodexLimits,
                 *, speech_enabled: bool = True, memory_enabled: bool = False):
        if type(speech_enabled) is not bool or type(memory_enabled) is not bool:
            raise CodexGenerationError('codex_capability_invalid')
        self.transport, self.runtime, self.limits = transport, runtime, limits
        self.speech_enabled = speech_enabled
        self.memory_enabled = memory_enabled
        self.thread_id = None
        self.turn_id = None
        self._request_id = 0
        self._events = 0
        self._wire_bytes = 0
        self._items: dict[str, str] = {}
        self._open_messages: dict[str, str] = {}
        self._messages: dict[str, str] = {}
        self.completed = False
        self._approved_initial_effort = None

    def _bind_thread(self, value):
        value = _identifier(value)
        _require(self.thread_id in (None, value), 'codex_thread_mismatch')
        self.thread_id = value

    def _bind_turn(self, value):
        value = _identifier(value)
        _require(self.turn_id in (None, value), 'codex_turn_mismatch')
        self.turn_id = value

    async def _read(self):
        raw = await self.transport.receive()
        _require(type(raw) is bytes and raw.endswith(b'\n'), 'codex_transport_invalid')
        self._wire_bytes += len(raw)
        self._events += 1
        _require(len(raw) <= self.limits.max_line_bytes, 'codex_line_limit')
        _require(self._wire_bytes <= self.limits.max_wire_bytes, 'codex_wire_limit')
        _require(self._events <= self.limits.max_events, 'codex_event_limit')
        message = strict_json(raw)
        _require(type(message) is dict)
        _require(set(message) <= {'jsonrpc', 'id', 'method', 'params', 'result', 'error',
                                  'emittedAtMs'})
        _require(message.get('jsonrpc', '2.0') == '2.0')
        if 'method' in message and 'id' in message:
            raise CodexGenerationError('codex_server_request_forbidden')
        return message

    async def _request(self, method, params):
        # Only internal call sites choose these methods and construct params.
        _require(method in ('initialize', 'config/read', 'account/read', 'thread/start',
                             'turn/start'))
        self._request_id += 1
        rid = self._request_id
        await self.transport.send({'id': rid, 'method': method, 'params': params})
        while True:
            message = await self._read()
            if 'method' in message:
                self._notification(message)
                del message
                continue
            _require(type(message.get('id')) is int and message['id'] == rid,
                     'codex_request_id_mismatch')
            _require('error' not in message, 'codex_rpc_failed')
            result = message.get('result')
            _require(type(result) is dict)
            return result

    async def start(self):
        result = await self._request('initialize', {
            'clientInfo': {'name': 'mira_generation', 'version': '1.0'},
            'capabilities': {'experimentalApi': True},
        })
        _require(result.get('codexHome') == str(self.runtime.codex_home), 'codex_home_drift')
        _require(type(result.get('userAgent')) is str and bool(result['userAgent']))
        await self.transport.send({'method': 'initialized'})
        config_result = await self._request('config/read', {'includeLayers': False})
        _verify_config(config_result, self.runtime)
        self._approved_initial_effort = config_result['config'].get('model_reasoning_effort')
        del config_result
        account = (await self._request('account/read', {'refreshToken': False})).get('account')
        _require(type(account) is dict and account.get('type') == 'chatgpt',
                 'codex_subscription_required')
        # Do not retain account identity, email, plan or routing data.
        del account
        result = await self._request('thread/start', {
            'ephemeral': True, 'environments': [], 'dynamicTools': [],
            'selectedCapabilityRoots': [], 'runtimeWorkspaceRoots': [],
            'cwd': str(self.runtime.runtime_cwd), 'model': MODEL,
            'allowProviderModelFallback': False, 'approvalPolicy': 'never',
            'approvalsReviewer': 'user', 'sandbox': 'read-only',
            'baseInstructions': author_instructions(speech_enabled=self.speech_enabled,
                                                    memory_enabled=self.memory_enabled),
            'developerInstructions': '',
            'experimentalRawEvents': False, 'serviceTier': 'default',
        })
        _require(result.get('model') == MODEL and result.get('modelProvider') == 'openai',
                 'codex_model_drift')
        _require(result.get('cwd') == str(self.runtime.runtime_cwd)
                 and result.get('approvalPolicy') == 'never'
                 and result.get('approvalsReviewer') == 'user'
                 and result.get('sandbox', {}).get('type') == 'readOnly'
                 and result['sandbox'].get('networkAccess', False) is False
                 and result.get('instructionSources') == []
                 and result.get('runtimeWorkspaceRoots') == []
                 and result.get('serviceTier') in (None, 'default'), 'codex_thread_isolation_drift')
        _verify_thread(result.get('thread'), self.runtime)
        self._bind_thread(result['thread']['id'])

    async def run(self, prompt):
        result = await self._request('turn/start', {
            'threadId': self.thread_id, 'input': [{'type': 'text', 'text': prompt}],
            'environments': [], 'runtimeWorkspaceRoots': [], 'model': MODEL,
            'effort': 'low', 'summary': 'none', 'serviceTierForTurn': 'default',
            'outputSchema': output_schema(speech_enabled=self.speech_enabled),
        })
        turn = result.get('turn')
        _require(type(turn) is dict)
        self._bind_turn(turn.get('id'))
        _require(turn.get('status') == 'inProgress', 'codex_turn_start_failed')
        _require(turn.get('items') == [])
        while not self.completed:
            message = await self._read()
            _require('method' in message, 'codex_unsolicited_response')
            self._notification(message)
            del message
        _require(not self._open_messages, 'codex_incomplete_output')
        return parse_effects(list(self._messages.values()), self.limits,
                             speech_enabled=self.speech_enabled)

    def _turn_identity(self, params):
        _require(self.thread_id is not None and params.get('threadId') == self.thread_id,
                 'codex_thread_mismatch')
        _require(self.turn_id is not None and params.get('turnId') == self.turn_id,
                 'codex_turn_mismatch')

    def _output_bound(self):
        _require(sum(len(t.encode('utf-8')) for t in
                     (*self._messages.values(), *self._open_messages.values()))
                 <= self.limits.max_output_bytes, 'codex_output_limit')

    def _item(self, item, *, complete, snapshot=False):
        _require(type(item) is dict)
        kind, item_id = item.get('type'), _identifier(item.get('id'))
        _require(kind in _ALLOWED_ITEM_KINDS, 'codex_item_forbidden')
        _require(self._items.get(item_id, kind) == kind, 'codex_item_changed')
        self._items[item_id] = kind  # Keep identity/type only for non-output items.
        if kind == 'functionCallOutput':
            _require((item.get('namespace'), item.get('name')) in
                     ((None, 'update_plan'), ('clock', 'curr_time')), 'codex_tool_forbidden')
        if kind != 'agentMessage':
            return
        _require(set(item) <= {'id', 'type', 'text', 'phase', 'delivery', 'questions',
                               'memoryCitation'}, 'codex_agent_message_invalid')
        _require(item.get('delivery') in (None, 'async')
                 and item.get('phase') in (None, 'commentary', 'final_answer'),
                 'codex_agent_message_invalid')
        _require(item.get('questions') in (None, []), 'codex_user_input_forbidden')
        _require(item.get('memoryCitation') is None, 'codex_hidden_history_forbidden')
        text = item.get('text')
        _require(type(text) is str, 'codex_agent_message_invalid')
        if item_id in self._messages:
            _require(snapshot and complete and self._messages[item_id] == text,
                     'codex_item_duplicate')
            return
        if complete:
            partial = self._open_messages.pop(item_id, '')
            _require(not partial or text == partial, 'codex_output_inconsistent')
            self._messages[item_id] = text
        else:
            _require(item_id not in self._open_messages, 'codex_item_duplicate')
            self._open_messages[item_id] = text
        self._output_bound()

    def _notification(self, message):
        method, params = message.get('method'), message.get('params')
        _require(type(method) is str and type(params) is dict)
        _require(not ({'result', 'error', 'id'} & set(message)))
        if method in ('configWarning', 'deprecationNotice'):
            allowed = ({'summary', 'details', 'path', 'range'} if method == 'configWarning'
                       else {'summary', 'details'})
            _require(set(params) <= allowed and type(params.get('summary')) is str)
            _require(params.get('details') is None or type(params['details']) is str)
            return  # Diagnostic bodies are never retained, rendered or logged.
        if method == 'account/rateLimits/updated':
            _require(set(params) == {'rateLimits'} and type(params['rateLimits']) is dict)
            return
        if method == 'turn/moderationMetadata':
            _require(set(params) == {'threadId', 'turnId', 'metadata'})
            self._turn_identity(params)
            return  # Opaque vendor metadata is not application review approval.
        if method == 'thread/settings/updated':
            _require(set(params) <= {'threadId', 'threadSettings', 'turnId'})
            _require(params.get('threadId') == self.thread_id, 'codex_thread_mismatch')
            if 'turnId' in params:
                _require(params['turnId'] == self.turn_id, 'codex_turn_mismatch')
            settings = params.get('threadSettings')
            _require(type(settings) is dict
                     and settings.get('model') == MODEL
                     and settings.get('modelProvider') == 'openai'
                     and settings.get('cwd') == str(self.runtime.runtime_cwd)
                     and settings.get('approvalPolicy') == 'never'
                     and settings.get('approvalsReviewer') == 'user'
                     and type(settings.get('sandboxPolicy')) is dict
                     and settings['sandboxPolicy'].get('type') == 'readOnly'
                     and settings['sandboxPolicy'].get('networkAccess', False) is False
                     and settings.get('serviceTier') in (None, 'default'),
                     'codex_thread_isolation_drift')
            mode = settings.get('collaborationMode')
            _require(type(mode) is dict and set(mode) == {'mode', 'settings'}
                     and mode.get('mode') == 'default', 'codex_thread_isolation_drift')
            nested = mode.get('settings')
            allowed_efforts = ((None, 'low') if self.turn_id is not None
                               else (None, 'low', self._approved_initial_effort))
            _require(type(nested) is dict
                     and set(nested) <= {'model', 'reasoning_effort', 'developer_instructions'}
                     and nested.get('model') == MODEL
                     and nested.get('developer_instructions') in (None, '')
                     and nested.get('reasoning_effort') in allowed_efforts,
                     'codex_thread_isolation_drift')
            return
        if method == 'account/updated':
            _require(params.get('authMode') == 'chatgpt', 'codex_subscription_required')
            return
        if method == 'remoteControl/status/changed':
            # Pinned v0.159.2 status notifications are informational only. Validate the
            # envelope/body but discard all identity/status values and never issue RC RPCs.
            _require(set(message) <= {'jsonrpc', 'method', 'params', 'emittedAtMs'}
                     and message.get('jsonrpc', '2.0') == '2.0',
                     'codex_remote_control_notification_invalid')
            stamp = message.get('emittedAtMs')
            _require(stamp is None or type(stamp) is int and -(2**63) <= stamp < 2**63,
                     'codex_remote_control_notification_invalid')
            _require(set(params) <= {'status', 'serverName', 'installationId', 'environmentId'}
                     and {'status', 'serverName', 'installationId'} <= set(params)
                     and type(params.get('status')) is str
                     and params['status'] in _REMOTE_CONTROL_STATUSES
                     and type(params.get('serverName')) is str
                     and type(params.get('installationId')) is str
                     and ('environmentId' not in params or params['environmentId'] is None
                          or type(params['environmentId']) is str),
                     'codex_remote_control_notification_invalid')
            return
        if method == 'warning':
            _require(type(params.get('message')) is str)
            _require(params.get('threadId') in (None, self.thread_id), 'codex_thread_mismatch')
            return  # No raw warning body is retained or forwarded.
        if method == 'thread/started':
            thread = params.get('thread')
            _verify_thread(thread, self.runtime)
            self._bind_thread(thread['id'])
            return
        if method == 'thread/status/changed':
            _require(params.get('threadId') == self.thread_id, 'codex_thread_mismatch')
            status = params.get('status')
            _require(type(status) is dict and status.get('type') in ('idle', 'active'),
                     'codex_thread_status_invalid')
            return
        if method == 'turn/started':
            _require(params.get('threadId') == self.thread_id, 'codex_thread_mismatch')
            turn = params.get('turn')
            _require(type(turn) is dict and turn.get('status') == 'inProgress')
            self._bind_turn(turn.get('id'))
            return
        if method == 'turn/completed':
            _require(params.get('threadId') == self.thread_id, 'codex_thread_mismatch')
            turn = params.get('turn')
            _require(type(turn) is dict and turn.get('id') == self.turn_id,
                     'codex_turn_mismatch')
            _require(turn.get('status') == 'completed' and turn.get('error') is None,
                     'codex_turn_not_completed')
            view = turn.get('itemsView', 'full')
            _require(view in ('full', 'notLoaded', 'summary'), 'codex_incomplete_output')
            items = turn.get('items')
            _require(type(items) is list)
            if view in ('notLoaded', 'summary'):
                # Sparse terminal payloads are not a new authoritative output source.
                # Every candidate must already have completed in the live item stream.
                _require(bool(self._messages) and not self._open_messages,
                         'codex_incomplete_output')
                if view == 'notLoaded':
                    _require(not items, 'codex_incomplete_output')
                else:
                    for item in items:
                        _require(type(item) is dict, 'codex_incomplete_output')
                        item_id = _identifier(item.get('id'))
                        _require(item.get('type') == self._items.get(item_id)
                                 and (item.get('type') != 'agentMessage'
                                      or item_id in self._messages), 'codex_incomplete_output')
                        # Display-summary text is deliberately ignored, never substituted.
            else:
                for item in items:
                    self._item(item, complete=True, snapshot=True)
            self.completed = True
            return
        if method in _IGNORED_TURN_EVENTS:
            self._turn_identity(params)
            return
        if method in ('item/started', 'item/completed'):
            self._turn_identity(params)
            self._item(params.get('item'), complete=method == 'item/completed')
            return
        if method == 'item/agentMessage/delta':
            self._turn_identity(params)
            item_id = _identifier(params.get('itemId'))
            _require(item_id not in self._messages, 'codex_item_duplicate')
            _require(self._items.get(item_id, 'agentMessage') == 'agentMessage')
            delta = params.get('delta')
            _require(type(delta) is str)
            self._items[item_id] = 'agentMessage'
            self._open_messages[item_id] = self._open_messages.get(item_id, '') + delta
            self._output_bound()
            return
        raise CodexGenerationError('codex_event_forbidden')

    async def interrupt(self):
        if self.thread_id is None or self.turn_id is None or self.completed:
            return
        self._request_id += 1
        await self.transport.send({'id': self._request_id, 'method': 'turn/interrupt',
                                   'params': {'threadId': self.thread_id, 'turnId': self.turn_id}})
        # Drain only to observe matching terminal; never interpret late output as candidates.
        for _ in range(self.limits.max_events):
            try:
                message = strict_json(await self.transport.receive())
            except CodexGenerationError:
                return
            if (type(message) is dict and message.get('method') == 'turn/completed'
                    and type(message.get('params')) is dict):
                params = message['params']
                turn = params.get('turn')
                if (params.get('threadId') == self.thread_id and type(turn) is dict
                        and turn.get('id') == self.turn_id
                        and turn.get('status') in ('interrupted', 'failed', 'completed')):
                    return

    def discard(self):
        self._open_messages.clear()
        self._messages.clear()
        self._items.clear()
