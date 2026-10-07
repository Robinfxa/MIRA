"""Offline local declaration, final advertisement, process budget and privacy evidence."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from mira.bootstrap.story_image_provider import StoryImageOptions, _ProcessImageAdmission
from mira.application.generation_tool_execution import tool_definitions
from tests.contracts.test_image_tool_capability_projection import fixture
from tests.contracts.test_story_image_options import args
from tools import live_provider as cli


def runtime_fixture():
    from mira.application.story_images import StoryImageAdmission, StoryImageRuntime
    from mira.domain.models import SessionState
    context, _ = fixture()
    state = SessionState('synthetic-session', 'synthetic-client', activity_seq=1,
        output_epoch=1, request_id='synthetic-request')
    options = StoryImageOptions(enabled=True, provider='chatgpt_subscription',
        image_model='gpt-image-2', review_model='gpt-6-luna', quality='auto',
        authorize_data_to_openai=True, authorize_subscription_usage=True,
        authorize_custom_brief=True, review_max_output_tokens=None)
    gate = _ProcessImageAdmission(options)
    runtime = StoryImageRuntime(object(), object(), object(), StoryImageAdmission(
        'synthetic-only', True, max_attempts=1, max_total_bytes=8_388_608,
        authorized_custom_brief=True), operation_admission=gate)
    return context, state, runtime, gate


@pytest.mark.parametrize('omitted', [None, 'story_images', 'image_data', 'subscription_usage', 'custom_brief'])
def test_startup_records_explicit_image_opt_ins_without_enabling_or_qualifying(omitted):
    from tests.contracts.test_story_image_options import ForbiddenSettings
    flags = {'story_images': '--story-images',
        'image_data': '--authorize-story-image-data-to-openai',
        'subscription_usage': '--authorize-story-image-subscription-usage',
        'custom_brief': '--authorize-story-image-custom-brief'}
    chosen = [flag for name, flag in flags.items() if name != omitted]
    # A custom brief without its feature is deliberately invalid, not auto-enabled.
    parsed = cli._parser().parse_args(['check', '--provider', 'chatgpt_subscription',
        '--model', 'gpt-6-luna', '--env-file', '/synthetic/not-read.env', '--story', *chosen])
    before = vars(parsed).copy()
    declaration = cli._story_image_declaration(parsed, ForbiddenSettings())
    assert declaration.get('startup_requested') == {
        'story': True, **{name: name != omitted for name in flags}, 'api_spend': False}
    assert vars(parsed) == before
    assert declaration['live_verified'] is False and declaration['inference'] == 'not_run'
    assert declaration['readiness']['account_access'] == 'not_checked'
    assert declaration['readiness']['provider_observation'] == 'not_observed'
    assert declaration['readiness']['generation_tool'] == ('configured' if omitted is None else 'absent')
    if omitted is None:
        assert declaration['subscription_entitlement'] == 'not_checked'
        assert declaration['subscription_quota_consumption'] == 'unknown'
        assert declaration['max_attempts_per_process'] == declaration['max_reviews_per_process'] == 1
        assert declaration['automatic_retries'] == 0 and declaration['automatic_fallback'] is False


def test_documented_subscription_voice_image_command_checks_without_jev_or_provider(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    import shlex
    guide = (Path(__file__).resolve().parents[2] / 'docs/development/STORY_IMAGE_OPTIONS.md').read_text()
    sample = guide.split('<!-- subscription-voice-story-image-start -->', 1)[1].split('```sh\n', 1)[1].split('```', 1)[0]
    command = shlex.split(sample.replace('\\\n', ' '))
    assert command[:3] == ['PYTHONPATH=apps/api/src', '.venv/bin/python', 'tools/live_provider.py']
    argv = command[3:]
    assert argv[0] == 'serve'
    parsed = cli._parser().parse_args(argv)
    assert parsed.action_review_mode == 'luna_tools'
    assert parsed.voice and parsed.authorize_google_voice_data_and_spend and parsed.authorize_provider_data
    assert parsed.story_image_max_attempts == 1 and parsed.story_image_review_model == 'gpt-6-luna'
    assert not parsed.authorize_api_billing and not parsed.authorize_story_image_api_spend

    # Materialize only synthetic metadata inputs. The ADC contents must never be read.
    env = tmp_path / 'synthetic.env'
    env.write_text('MIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\n'
        'MIRA_SERVICES__SPEECH__TTS_VOICE=Kore\n')
    env.chmod(0o600)
    adc = tmp_path / 'synthetic-adc.json'
    adc.write_text('not credentials; must not be parsed')
    adc.chmod(0o600)
    argv[0] = 'check'
    argv[argv.index('--env-file') + 1] = str(env)
    argv[argv.index('--adc-file') + 1] = str(adc)
    for name in ('_serve', '_generation', '_voice_factory', '_subscription_credentials'):
        monkeypatch.setattr(cli, name, lambda *a, **kw: pytest.fail('declaration check must not allocate providers'))
    assert cli.main(argv) == 0
    rendered = capsys.readouterr().out
    result = json.loads(rendered)
    image = result['story_images']
    assert result['auth_store'] == 'not_loaded' and result['inference'] == 'not_run'
    assert result['live_ready'] is False and result['voice_declared'] is True
    assert image['startup_requested'] == {'story': True, 'story_images': True,
        'image_data': True, 'subscription_usage': True, 'custom_brief': True, 'api_spend': False}
    assert image['readiness']['state'] == 'enabled' and image['live_verified'] is False
    assert image['readiness']['provider_observation'] == 'not_observed'
    assert image['max_attempts_per_process'] == image['max_reviews_per_process'] == 1
    assert image['automatic_retries'] == 0 and image['automatic_fallback'] is False
    assert image['subscription_entitlement'] == 'not_checked'
    assert 'synthetic' not in rendered and str(tmp_path) not in rendered


def readiness(runtime, context, state, **overrides):
    from mira.application import image_readiness
    return image_readiness.image_tool_readiness(context, state, runtime,
        review_available=overrides.get('review_available', True), image_task_count=0, max_effects=64)


@pytest.mark.parametrize('extra,expected,reason', [
    ([], 'disabled', 'feature_disabled'),
    (['--story', '--story-images'], 'missing_consent', 'consent_required'),
    (['--story', '--story-images', '--authorize-story-image-data-to-openai',
      '--authorize-story-image-subscription-usage'], 'missing_consent', 'custom_brief_consent'),
    (['--story', '--story-images', '--authorize-story-image-data-to-openai',
      '--authorize-story-image-subscription-usage', '--authorize-story-image-custom-brief'], 'enabled', 'configured'),
    (['--story', '--story-images', '--authorize-story-image-data-to-openai',
      '--authorize-story-image-subscription-usage', '--action-review-mode', 'legacy_jev',
      '--legacy-media-proposals'], 'legacy_catalog_only', 'legacy_mode'),
    (['--story', '--story-images', '--authorize-story-image-data-to-openai',
      '--authorize-story-image-subscription-usage', '--authorize-story-image-custom-brief',
      '--generation-requests', '1'], 'budget_exhausted', 'dialogue_budget'),
])
def test_operator_check_reports_custom_tool_readiness_without_probe(tmp_path, capsys, monkeypatch, extra, expected, reason):
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('must not allocate provider'))
    monkeypatch.setattr(cli, '_subscription_credentials', lambda *_: pytest.fail('must not read auth'))
    cli.main(args(tmp_path, *extra))
    report = json.loads(capsys.readouterr().out)['story_images']
    assert 'readiness' in report, 'check must name actual custom-brief tool readiness'
    value = report['readiness']
    assert value['state'] == expected and value['reason'] == reason
    assert value['scope'] == 'configuration_only' and value['account_access'] == 'not_checked'
    assert value['provider_observation'] == 'not_observed'
    assert value['generation_tool'] == ('configured' if expected == 'enabled' else 'absent')
    assert 'synthetic' not in json.dumps(value) and str(tmp_path) not in json.dumps(value)


def test_process_budget_exhaustion_after_new_session_removes_only_generated_tool():
    context, state, runtime, gate = runtime_fixture()
    request = SimpleNamespace(request_id='already-spent', max_output_bytes=1024)
    gate.reserve(request); gate.release(request.request_id)
    definitions = tool_definitions(context, state, runtime,
        review_available=True, image_task_count=0, max_effects=64)
    assert [d.name for d in definitions] == ['show_photo'], 'process budget must constrain advertised tools'
    value = readiness(runtime, context, state)
    assert value.state == 'budget_exhausted' and value.reason == 'process_budget'
    assert value.image_attempts == 0 and value.process_remaining_jobs == 0


def test_busy_process_removes_generation_without_reserving_or_spending():
    context, state, runtime, gate = runtime_fixture()
    gate.reserve(SimpleNamespace(request_id='in-flight', max_output_bytes=1024))
    value = readiness(runtime, context, state)
    assert value.state == 'held' and value.reason == 'process_busy'
    assert [d.name for d in tool_definitions(context, state, runtime,
        review_available=True, image_task_count=0, max_effects=64)] == ['show_photo']
    assert gate.attempts == 1 and runtime.attempts == 0


@pytest.mark.parametrize('case,state_name,reason', [
    ('enabled', 'enabled', 'ready'), ('disabled', 'disabled', 'runtime_disabled'),
    ('custom', 'missing_consent', 'custom_brief_consent'),
    ('attempts', 'budget_exhausted', 'image_attempts'),
    ('bytes', 'budget_exhausted', 'image_bytes'),
    ('review', 'held', 'review_unavailable'), ('story', 'held', 'story_unavailable'),
])
def test_local_readiness_is_current_and_content_free(case, state_name, reason):
    context, state, runtime, gate = runtime_fixture()
    if case == 'disabled': runtime = None
    elif case == 'custom': runtime.admission = replace(runtime.admission, authorized_custom_brief=False)
    elif case == 'attempts': runtime.attempts = 1
    elif case == 'bytes': runtime.used_bytes = 1
    elif case == 'story': context = replace(context, character_story=None)
    value = readiness(runtime, context, state, review_available=case != 'review')
    assert value.state == state_name and value.reason == reason
    assert value.provider_observation == 'not_observed'


class Sink:
    def __init__(self): self.events = []
    def emit(self, event): self.events.append(event)


def observed(sink):
    return [e.image_readiness for e in sink.events if getattr(e, 'image_readiness', None) is not None]


@pytest.mark.asyncio
@pytest.mark.parametrize('request_limit,expected', [(1, 'absent'), (2, 'advertised')])
async def test_actor_export_observes_final_serialized_tools_after_dialogue_budget(request_limit, expected):
    from tests.contracts.test_direct_codex_responses import backend, response
    from tests.contracts.test_direct_luna_tools import message, wire
    from tests.contracts.test_luna_tool_actor import actor, submit
    from tests.contracts.test_development_review_composition import finish
    from mira.bootstrap.character_story import ephemeral_character_factory
    from mira.domain.models import SessionState
    context, state, runtime, gate = runtime_fixture()
    bodies = []
    async def handle(request):
        bodies.append(json.loads(request.content))
        return response(wire([message()]))
    generator, _, _ = backend(handle, request_limit=request_limit)
    character = ephemeral_character_factory(readiness=context.character_assets)(SessionState('s', 'c'))
    value, _, _, _ = actor(None, tools=generator, runtime=runtime, character=character)
    sink = Sink(); value._diagnostics = sink
    try:
        await submit(value); final = await finish(value)
        rows = [v for v in observed(sink) if v.phase == 'request']
        assert len(rows) == 1, 'record final serialized tool availability, not just offered definitions'
        assert rows[0].generation_tool == expected
        assert rows[0].fixed_photo_tool == expected
        assert ('generate_story_image' in [d['name'] for d in bodies[0]['tools']]) == (expected == 'advertised')
        assert rows[0].reason == ('dialogue_budget' if request_limit == 1 else 'ready')
        assert final.last_error is None and gate.attempts == runtime.attempts == 0
    finally: await value.close()


@pytest.mark.asyncio
async def test_continuation_reports_no_tools_with_current_phase_and_keeps_fixed_photo_success():
    from tests.contracts.test_direct_codex_responses import backend, response
    from tests.contracts.test_direct_luna_tools import message, tool, wire
    from tests.contracts.test_luna_tool_actor import actor, submit, wait_state
    from tests.contracts.test_authored_photo_events import receipt
    from tests.contracts.test_development_review_composition import finish
    from mira.domain.models import EffectKind
    bodies = []
    async def handle(request):
        bodies.append(json.loads(request.content))
        return response(wire([tool()]) if len(bodies) == 1 else wire([message()]))
    generator, _, _ = backend(handle, request_limit=2)
    value, _, _, _ = actor(None, tools=generator, result_wait=1)
    sink = Sink(); value._diagnostics = sink
    try:
        await submit(value)
        state = await wait_state(value, lambda s:s.fixed_photo.state == 'granted')
        photo = next(e for e in state.active_grants if e.kind is EffectKind.MEDIA)
        await value.receipt(receipt(photo, 1)); final = await finish(value)
        rows = [v for v in observed(sink) if v.phase in ('request', 'continuation')]
        assert len(rows) == 2, 'initial and continuation advertisement are distinct observations'
        assert rows[0].fixed_photo_tool == 'advertised'
        assert rows[1].reason == 'continuation' and rows[1].generation_tool == rows[1].fixed_photo_tool == 'absent'
        assert bodies[1]['tools'] == [] and final.fixed_photo.state == 'presented'
        assert final.last_error is None and len(bodies) == 2
    finally: await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_stage', ['generation', 'review', 'local_decode'])
async def test_provider_failure_is_observed_separately_and_never_guessed_from_local_failure(failed_stage):
    from tests.contracts.test_luna_tool_actor import image_actor, submit, wait_state
    value, turn, images, vision, _, _ = image_actor(fail=failed_stage == 'generation')
    sink = Sink(); value._diagnostics = sink
    async def fail(*_): raise ValueError('PRIVATE_PROVIDER_ERROR https://private.invalid/key')
    def decode_fail(*_): raise ValueError('PRIVATE_LOCAL_ERROR')
    if failed_stage == 'review': vision.review = fail
    elif failed_stage == 'local_decode': value._story_images.decoder.canonicalize = decode_fail
    try:
        await submit(value)
        await wait_state(value, lambda s:s.story_image.state == 'failed')
        rows = [v for v in observed(sink) if v.phase == 'operation']
        assert rows, 'observed operation status must survive diagnostic export'
        result = rows[-1]
        assert result.provider_observation == ('generation_returned' if failed_stage == 'local_decode' else failed_stage+'_error')
        assert (result.state == 'provider_error') == (failed_stage != 'local_decode')
        assert 'PRIVATE' not in json.dumps([v.__repr__() for v in rows])
    finally: await value.close()


@pytest.mark.asyncio
async def test_stale_readiness_callback_cannot_reappear_after_stop_or_close():
    from tests.contracts.test_luna_tool_actor import actor, ToolTurn, submit, wait_state
    class ObservedTurn(ToolTurn):
        def observe_tool_advertisement(self, observer): self.observer = observer
        async def start(self):
            result = await super().start()
            self.observer(('show_photo',), False)
            return result
    turn = ObservedTurn(start_gate=True, ignore_cancel=True)
    value, _, _, _ = actor(turn)
    sink = Sink(); value._diagnostics = sink
    try:
        await submit(value); await asyncio.wait_for(turn.started.wait(), 1)
        assert hasattr(turn, 'observer'), 'current Actor must bind the optional local observer'
        await value.stop(activity_seq=2, cutoff=0)
        count = len(observed(sink))
        turn.observer(('show_photo',), False)
        assert len(observed(sink)) == count
        turn.release.set()
        await asyncio.gather(*tuple(value._tasks), return_exceptions=True)
        await value.close(); turn.observer(('show_photo',), False)
        assert len(observed(sink)) == count
    finally: turn.release.set(); await value.close()


def test_export_roundtrip_rejects_private_metadata_and_retains_old_events(tmp_path):
    import zipfile
    from mira.application.diagnostic_events import DiagnosticEvent, DiagnosticStage, DiagnosticOutcome
    from mira.adapters.diagnostics.privacy import encode_event, validate_event_record
    from mira.adapters.diagnostics.export import export_diagnostics
    context, state, runtime, gate = runtime_fixture()
    assert hasattr(DiagnosticStage, 'IMAGE_READINESS'), 'typed image stage is required'
    event = DiagnosticEvent(DiagnosticStage.IMAGE_READINESS, DiagnosticOutcome.SUCCEEDED,
        image_readiness=readiness(runtime, context, state))
    row = encode_event(event, 1000)
    assert validate_event_record(json.loads(json.dumps(row))) == row
    old = encode_event(DiagnosticEvent(DiagnosticStage.HTTP, DiagnosticOutcome.SUCCEEDED), 999)
    root = tmp_path / 'logs'; (root / 'events').mkdir(parents=True)
    (root / 'events' / 'events-synthetic.jsonl').write_text(json.dumps(row)+'\n'+json.dumps(old)+'\n')
    report = export_diagnostics(root, tmp_path / 'export.zip')
    assert report['skipped_records'] == 0 and report['event_count'] == 2
    with zipfile.ZipFile(tmp_path / 'export.zip') as bundle: data = bundle.read('events.jsonl')
    assert '请生成'.encode() not in data and b'prompt' not in data and b'brief' not in data
    for field, bad in [('reason','PRIVATE_TEXT'), ('state','PRIVATE_TEXT'), ('provider_observation','PRIVATE_TEXT'),
                       ('generation_tool','arbitrary_tool'), ('image_attempts',True), ('process_remaining_jobs',5),
                       ('prompt','PRIVATE_TEXT'), ('digest','a'*64)]:
        invalid = json.loads(json.dumps(row)); invalid['image_readiness'][field] = bad
        with pytest.raises((ValueError, TypeError)): validate_event_record(invalid)


@pytest.mark.asyncio
async def test_broken_optional_observer_and_sink_cannot_change_fixed_photo_grants():
    from tests.contracts.test_luna_tool_actor import actor, ToolTurn, submit, wait_state
    class BrokenTurn(ToolTurn):
        def observe_tool_advertisement(self, _): raise ValueError('PRIVATE_OBSERVER_ERROR')
    class BrokenSink:
        def emit(self, _): raise ValueError('PRIVATE_SINK_ERROR')
    value, _, _, _ = actor(BrokenTurn())
    value._diagnostics = BrokenSink()
    try:
        await submit(value)
        state = await wait_state(value, lambda s:s.fixed_photo.state == 'granted')
        assert state.last_error is None and any(e.value == 'trip_photo' for e in state.active_grants)
    finally: await value.close()


def test_invalid_optional_process_observation_does_not_hide_fixed_photo():
    context, state, runtime, gate = runtime_fixture()
    def broken(): raise ValueError('PRIVATE_GATE_ERROR')
    gate.readiness = broken
    definitions = tool_definitions(context,state,runtime,review_available=True,image_task_count=0,max_effects=64)
    assert 'show_photo' in [d.name for d in definitions]
    assert readiness(runtime,context,state).process_remaining_jobs is None


@pytest.mark.asyncio
async def test_direct_observer_is_discarded_on_close_and_cannot_change_requests():
    from tests.contracts.test_direct_codex_responses import backend, response
    from tests.contracts.test_direct_luna_tools import message, wire
    context, definitions = fixture()
    async def handle(_): return response(wire([message()]))
    generator, _, requests = backend(handle, request_limit=2)
    turn = generator.open_tool_turn(context, definitions)
    def broken(*_): raise ValueError('PRIVATE_OBSERVER_ERROR')
    assert callable(getattr(turn, 'observe_tool_advertisement', None))
    turn.observe_tool_advertisement(broken)
    await turn.start()
    assert len(requests) == 1 and generator._reserved == 0
    assert turn._tool_advertisement_observer is None and turn._context is None


@pytest.mark.asyncio
async def test_replaced_input_drops_old_task_readiness_without_hiding_new_turn():
    from tests.contracts.test_luna_tool_actor import actor, Tools, ToolTurn, submit
    from tests.contracts.test_development_review_composition import finish
    class ObservedTurn(ToolTurn):
        def observe_tool_advertisement(self, observer): self.observer = observer
        async def start(self):
            result = await super().start()
            self.observer(('show_photo',), False)
            return result
    first = ObservedTurn(start_gate=True, ignore_cancel=True)
    second = ObservedTurn()
    value, _, _, _ = actor(first, tools=Tools(first,second))
    sink = Sink(); value._diagnostics = sink
    try:
        await submit(value); await asyncio.wait_for(first.started.wait(),1)
        await submit(value,2); await asyncio.wait_for(second.started.wait(),1)
        first.release.set(); await finish(value)
        requests = [v for v in observed(sink) if v.phase == 'request']
        assert len(requests) == 1 and requests[0].activity_seq == 2
        assert requests[0].fixed_photo_tool == 'advertised'
    finally: first.release.set(); await value.close()
