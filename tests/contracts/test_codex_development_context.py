"""Private approved-context admission; all transports here are synthetic."""
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from mira.adapters.generation.codex_support import types, process, protocol
from mira.adapters.generation.codex_support.payload import canonical
from tests.contracts.test_codex_generation import (RUNTIME, FLAGS, SyntheticTransport, make, collect, event,
                                   agent, terminal)

ROUTE = 'https://synthetic.invalid/approved-path'

def development():
    admission_type = getattr(types, 'ApprovedDevelopmentContext', None)
    assert admission_type is not None, 'No explicit approved development context exists'
    cfg = {'features': dict.fromkeys(FLAGS, False), 'mcp_servers': {},
           'web_search': 'disabled', 'model': 'gpt-6-luna', 'model_provider': 'openai',
           'forced_login_method': 'chatgpt', 'approval_policy': 'never', 'sandbox_mode': 'read-only',
           'orchestrator': {'mcp': {'enabled': False}}, 'cloud': {'skills': {'enabled': False}},
           'openai_base_url': ROUTE}
    environment = {'CODEX_HOME':'/synthetic/home','HTTPS_PROXY':'http://synthetic-proxy.invalid:8080',
                   'SSL_CERT_FILE':'/synthetic/approved-ca.pem','SYNTHETIC_MANAGED_POLICY_MARKER':'retained'}
    admission = admission_type(route_value_sha256=hashlib.sha256(ROUTE.encode()).hexdigest(),
                               observed_home_mode=0o755,
                               managed_environment_sha256=hashlib.sha256(canonical(environment)).hexdigest())
    runtime = replace(RUNTIME, expected_config_sha256=hashlib.sha256(canonical(cfg)).hexdigest(),
                      development_context=admission, environment=environment)
    def mutate(result): result['config'] = cfg.copy()
    return runtime, cfg, mutate

@pytest.mark.asyncio
async def test_exact_approved_development_context_accepts_structured_candidate_only():
    runtime, _, mutate = development()
    backend, transport, _ = make(SyntheticTransport(config_mutation=mutate), runtime=runtime)
    output = await collect(backend)
    assert len(output) == 1 and output[0].fixture_id.startswith('codex-origin:')
    assert transport.closed
    assert 'fixture' not in output[0].fixture_id

@pytest.mark.parametrize('drift', ['route', 'cloud', 'orchestrator', 'proxy', 'config'])
def test_development_context_drift_fails_closed(drift):
    runtime, cfg, _ = development()
    if drift == 'route': cfg['openai_base_url'] = ROUTE + '/changed'
    elif drift == 'cloud': cfg['cloud'] = {'skills': {'enabled': True}}
    elif drift == 'orchestrator': cfg['orchestrator'] = {'mcp': {'enabled': True}}
    elif drift == 'proxy': cfg['features']['respect_system_proxy'] = True
    else: cfg['notify'] = ['synthetic-command']
    with pytest.raises(types.CodexGenerationError): protocol._verify_config({'config': cfg}, runtime)

def test_development_argv_preserves_managed_proxy_and_disables_cloud_capabilities():
    runtime, _, _ = development()
    args = process._argv(runtime)
    assert args.index('--no-daemon') < args.index('app-server')
    assert 'orchestrator.mcp.enabled=false' in args
    assert 'cloud.skills.enabled=false' in args
    assert 'features.respect_system_proxy=true' not in args
    assert not any('base_url=' in value for value in args)

def test_default_profile_still_rejects_existing_custom_route():
    _, cfg, _ = development()
    cfg['features']['respect_system_proxy'] = True
    with pytest.raises(types.CodexGenerationError): protocol._verify_config({'config':cfg}, RUNTIME)

@pytest.mark.asyncio
async def test_pinned_metadata_is_discarded_without_candidate_bypass():
    events = [
        {'method':'configWarning','params':{'summary':'synthetic private warning','details':None}},
        {'method':'deprecationNotice','params':{'summary':'synthetic notice','details':None}},
        {'method':'account/rateLimits/updated','params':{'rateLimits':{}}},
        event('thread/settings/updated', threadSettings={'model':'gpt-6-luna','modelProvider':'openai',
              'cwd':'/synthetic/run','approvalPolicy':'never','approvalsReviewer':'user',
              'sandboxPolicy':{'type':'readOnly'},'collaborationMode':{'mode':'default','settings':{'model':'gpt-6-luna',
                  'reasoning_effort':'low','developer_instructions':None}}}),
        event('turn/moderationMetadata', metadata={'synthetic':'never display'}),
        event('item/completed', item=agent()), terminal()]
    backend, transport, _ = make(SyntheticTransport(events=events))
    output = await collect(backend)
    assert len(output) == 1
    assert all('synthetic private' not in e.value and 'never display' not in e.value for e in output[0].effects)

@pytest.mark.asyncio
async def test_thread_settings_model_drift_remains_forbidden():
    backend, transport, _ = make(SyntheticTransport(events=[
        event('thread/settings/updated', threadSettings={'model':'other','modelProvider':'openai',
              'cwd':'/synthetic/run','approvalPolicy':'never','approvalsReviewer':'user',
              'sandboxPolicy':{'type':'readOnly'},'collaborationMode':{'mode':'default','settings':{'model':'gpt-6-luna',
                  'reasoning_effort':'low','developer_instructions':None}}})]))
    with pytest.raises(types.CodexGenerationError): await collect(backend)
    assert transport.closed


def test_development_inherits_exact_managed_environment_without_custom_overrides():
    runtime, _, _ = development()
    env = process._process_environment(runtime)
    assert env['SYNTHETIC_MANAGED_POLICY_MARKER'] == 'retained'
    assert env['CODEX_HOME'] == '/synthetic/home'
    assert env['HTTPS_PROXY'] == 'http://synthetic-proxy.invalid:8080'
    assert env['SSL_CERT_FILE'] == '/synthetic/approved-ca.pem'


def with_approved_environment(runtime, environment):
    approval = replace(runtime.development_context,
                       managed_environment_sha256=hashlib.sha256(canonical(environment)).hexdigest())
    return replace(runtime, development_context=approval, environment=environment)


def test_managed_home_defaults_to_official_home_codex_without_inserting_override():
    runtime, _, _ = development()
    environment = dict(runtime.environment)
    environment.pop('CODEX_HOME')
    environment['HOME'] = '/synthetic'
    runtime = replace(runtime, codex_home=Path('/synthetic/.codex'))
    runtime = with_approved_environment(runtime, environment)

    child_environment = process._process_environment(runtime)

    assert child_environment['HOME'] == '/synthetic'
    assert 'CODEX_HOME' not in child_environment


@pytest.mark.parametrize('home', ['', 'relative/home', '/synthetic/../synthetic'])
def test_managed_home_fallback_rejects_unsafe_or_noncanonical_home(home):
    runtime, _, _ = development()
    environment = dict(runtime.environment)
    environment.pop('CODEX_HOME')
    environment['HOME'] = home
    runtime = with_approved_environment(runtime, environment)
    with pytest.raises(types.CodexGenerationError, match='home_drift'):
        process._process_environment(runtime)


def test_managed_home_fallback_rejects_missing_home_and_mismatched_runtime_home():
    runtime, _, _ = development()
    environment = dict(runtime.environment)
    environment.pop('CODEX_HOME')
    runtime = with_approved_environment(runtime, environment)
    with pytest.raises(types.CodexGenerationError, match='home_drift'):
        process._process_environment(runtime)

    environment['HOME'] = '/synthetic'
    runtime = with_approved_environment(runtime, environment)
    with pytest.raises(types.CodexGenerationError, match='home_drift'):
        process._process_environment(runtime)


@pytest.mark.parametrize('codex_home', ['', 'relative/home'])
def test_managed_home_rejects_invalid_explicit_codex_home(codex_home):
    runtime, _, _ = development()
    runtime = with_approved_environment(runtime, dict(runtime.environment, CODEX_HOME=codex_home))
    with pytest.raises(types.CodexGenerationError, match='home_drift'):
        process._process_environment(runtime)


def test_managed_home_rejects_bad_home_even_with_explicit_override():
    runtime, _, _ = development()
    runtime = with_approved_environment(runtime, dict(runtime.environment, HOME='relative'))
    with pytest.raises(types.CodexGenerationError, match='home_drift'):
        process._process_environment(runtime)


def test_managed_home_fallback_rejects_symlinked_home(tmp_path):
    target = tmp_path / 'actual-home'
    target.mkdir()
    alias = tmp_path / 'home-link'
    alias.symlink_to(target, target_is_directory=True)
    runtime, _, _ = development()
    environment = dict(runtime.environment)
    environment.pop('CODEX_HOME')
    environment['HOME'] = str(alias)
    runtime = replace(runtime, codex_home=target / '.codex')
    runtime = with_approved_environment(runtime, environment)

    with pytest.raises(types.CodexGenerationError, match='home_drift'):
        process._process_environment(runtime)

@pytest.mark.parametrize('key', ['CODEX_API_KEY','OPENAI_API_KEY','OPENAI_BASE_URL',
                                 'CODEX_ACCESS_TOKEN','CODEX_REFRESH_TOKEN_URL_OVERRIDE','TYPESAFE_API_KEY'])
def test_development_auth_or_route_override_is_rejected(key):
    runtime, _, _ = development()
    runtime = with_approved_environment(runtime, dict(runtime.environment, **{key:'synthetic-forbidden'}))
    with pytest.raises(types.CodexGenerationError, match='environment_drift'):
        process._process_environment(runtime)

def test_development_home_binding_cannot_be_substituted():
    runtime, _, _ = development()
    runtime = with_approved_environment(runtime, dict(runtime.environment, CODEX_HOME='/synthetic/different-home'))
    with pytest.raises(types.CodexGenerationError, match='home_drift'):
        process._process_environment(runtime)

def test_development_admission_cannot_contain_environment_overrides():
    runtime, _, _ = development()
    with pytest.raises(ValueError, match='development_approval_invalid'):
        replace(runtime, environment={'HTTPS_PROXY':'http://synthetic-override.invalid'})

@pytest.mark.parametrize('mode', [0o777,0o775,True,-1])
def test_development_approval_rejects_untrusted_or_invalid_home_modes(mode):
    development()
    with pytest.raises(ValueError):
        types.ApprovedDevelopmentContext(route_value_sha256='0'*64, observed_home_mode=mode,
                                        managed_environment_sha256='0'*64)

@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('threadId','wrong-thread'),('turnId','wrong-turn')])
async def test_moderation_metadata_identity_drift_fails_closed(field, value):
    message = event('turn/moderationMetadata', metadata={'untrusted':'ignored'})
    message['params'][field] = value
    backend, transport, _ = make(SyntheticTransport(events=[message]))
    with pytest.raises(types.CodexGenerationError): await collect(backend)
    assert transport.closed


@pytest.mark.parametrize('key', ['OPENAI_API_KEY','OPENAI_BASE_URL','CODEX_ACCESS_TOKEN'])
def test_present_empty_auth_or_route_override_is_still_rejected(key):
    runtime, _, _ = development()
    runtime = with_approved_environment(runtime, dict(runtime.environment, **{key:''}))
    with pytest.raises(types.CodexGenerationError, match='environment_drift'):
        process._process_environment(runtime)

@pytest.mark.asyncio
async def test_thread_start_network_access_expansion_is_rejected():
    def mutate(result): result['sandbox']['networkAccess'] = True
    backend, transport, _ = make(SyntheticTransport(thread_mutation=mutate))
    with pytest.raises(types.CodexGenerationError, match='isolation_drift'):
        await collect(backend)
    assert not transport.turn_started.is_set()

@pytest.mark.asyncio
async def test_thread_settings_network_access_expansion_is_rejected():
    settings = {'model':'gpt-6-luna','modelProvider':'openai','cwd':'/synthetic/run',
                'approvalPolicy':'never','approvalsReviewer':'user',
                'sandboxPolicy':{'type':'readOnly','networkAccess':True},'collaborationMode':{'mode':'default','settings':{'model':'gpt-6-luna',
                  'reasoning_effort':'low','developer_instructions':None}}}
    backend, transport, _ = make(SyntheticTransport(events=[
        event('thread/settings/updated', threadSettings=settings),
        event('item/completed', item=agent()), terminal()]))
    with pytest.raises(types.CodexGenerationError, match='isolation_drift'):
        await collect(backend)
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['empty','plan','model','instructions','effort'])
async def test_collaboration_mode_context_drift_is_rejected(problem):
    mode = {'mode':'default','settings':{'model':'gpt-6-luna',
            'reasoning_effort':'low','developer_instructions':None}}
    if problem == 'empty': mode = {}
    elif problem == 'plan': mode['mode'] = 'plan'
    elif problem == 'model': mode['settings']['model'] = 'other'
    elif problem == 'instructions': mode['settings']['developer_instructions'] = 'Synthetic injected instructions'
    else: mode['settings']['reasoning_effort'] = 'high'
    settings = {'model':'gpt-6-luna','modelProvider':'openai','cwd':'/synthetic/run',
                'approvalPolicy':'never','approvalsReviewer':'user',
                'sandboxPolicy':{'type':'readOnly'},'collaborationMode':mode}
    backend, transport, _ = make(SyntheticTransport(events=[
        event('thread/settings/updated', threadSettings=settings),
        event('item/completed', item=agent()), terminal()]))
    with pytest.raises(types.CodexGenerationError, match='isolation_drift'):
        await collect(backend)
    assert transport.closed


@pytest.mark.parametrize('development_mode', [False, True])
def test_exact_official_chatgpt_default_without_trailing_slash_is_supported(development_mode):
    runtime, cfg, _ = development()
    cfg['chatgpt_base_url'] = 'https://chatgpt.com/backend-api'
    if development_mode:
        runtime = replace(runtime, expected_config_sha256=hashlib.sha256(canonical(cfg)).hexdigest())
    else:
        runtime = RUNTIME
        cfg.pop('openai_base_url')
        cfg['features']['respect_system_proxy'] = True
    protocol._verify_config({'config':cfg}, runtime)

@pytest.mark.parametrize('url', ['https://chatgpt.com/backend-api/other',
    'https://chatgpt.com/backend-api?override=1','https://chatgpt.com.example.invalid/backend-api'])
def test_chatgpt_default_spelling_does_not_allow_arbitrary_route(url):
    runtime, cfg, _ = development()
    cfg['chatgpt_base_url'] = url
    runtime = replace(runtime, expected_config_sha256=hashlib.sha256(canonical(cfg)).hexdigest())
    with pytest.raises(types.CodexGenerationError): protocol._verify_config({'config':cfg}, runtime)


def unloaded_terminal(items=None, view='notLoaded'):
    value = terminal(items=items)
    value['params']['turn']['itemsView'] = view
    return value

@pytest.mark.asyncio
async def test_not_loaded_terminal_uses_only_already_completed_streamed_output():
    backend, transport, _ = make(SyntheticTransport(events=[
        event('item/started', item=agent('')),
        event('item/agentMessage/delta', itemId='item-1', delta=agent()['text']),
        event('item/completed', item=agent()), unloaded_terminal()]))
    output = await collect(backend)
    assert len(output) == 1 and transport.closed

@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['no_completed_output','unfinished_delta','unexpected_snapshot','unknown_view'])
async def test_sparse_or_partial_terminal_never_invents_completed_output(problem):
    events = [event('item/completed', item=agent()), unloaded_terminal()]
    if problem == 'no_completed_output': events = [unloaded_terminal()]
    elif problem == 'unfinished_delta': events = [
        event('item/agentMessage/delta', itemId='item-1', delta=agent()['text']), unloaded_terminal()]
    elif problem == 'unexpected_snapshot': events[-1] = unloaded_terminal(items=[agent()])
    else: events[-1] = unloaded_terminal(view='unrecognized')
    backend, transport, _ = make(SyntheticTransport(events=events))
    with pytest.raises(types.CodexGenerationError): await collect(backend)
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('summary_items', [[], [agent('summary is not a new output source')]])
async def test_summary_terminal_uses_completed_events_not_display_summary(summary_items):
    backend, transport, _ = make(SyntheticTransport(events=[
        event('item/completed', item=agent()), unloaded_terminal(items=summary_items, view='summary')]))
    output = await collect(backend)
    assert len(output) == 1
    assert output[0].effects[0].value == '我们一起听雨。'
    assert transport.closed

@pytest.mark.asyncio
@pytest.mark.parametrize('summary_item', [dict(agent(), id='unseen-item'),
                                         dict(agent(), type='unknown-capability')])
async def test_summary_cannot_introduce_unseen_or_changed_item(summary_item):
    backend, transport, _ = make(SyntheticTransport(events=[
        event('item/completed', item=agent()), unloaded_terminal(items=[summary_item], view='summary')]))
    with pytest.raises(types.CodexGenerationError): await collect(backend)
    assert transport.closed
