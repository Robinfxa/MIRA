"""Synthetic direct-entry/runtime contract: no provider calls or real audio devices."""
import asyncio
from dataclasses import replace

import pytest

from mira.adapters.speech.errors import SpeechProviderError
from mira.application.ports.request_budget import RequestBudgetSnapshot
from mira.bootstrap.development_voice import DevelopmentVoiceLimits, _AttemptBudget
from mira.bootstrap.development_usage import UsageProfile
from mira.config.loader import ConfigurationError
from mira.entrypoints.http.schemas import ContinuousListeningReady, ContinuousListeningRecognitionStatus
from tools import live_provider as cli


def parsed(*extra):
    return cli._parser().parse_args(['check', '--provider', 'chatgpt_subscription',
        '--model', 'gpt-6.1-sol', '--env-file', '/tmp/synthetic-unused-env', *extra])


def test_direct_defaults_are_none_for_all_subscription_models_and_voice_counts():
    args = parsed()
    assert cli._generation_request_limit(args) is cli._session_turn_limit(args) is None
    assert args.stt_requests is None
    assert args.listen_max_recognition_streams is None
    limits = cli._listening_limits(args)
    assert (limits.max_seconds, limits.max_samples, limits.max_utterances,
            limits.max_streams_per_session, limits.max_total_streams,
            limits.max_recognition_streams) == (None,) * 6
    assert (args.tts_requests, args.tts_max_seconds, args.stt_max_seconds,
            args.story_image_max_attempts) == (20, 30, 120, 1)
    args.provider = 'openai_api'
    assert cli._generation_request_limit(args) == cli._session_turn_limit(args) == 20


def test_explicit_finite_voice_options_survive_compatibility_unlimited_flag():
    args = parsed('--local-unlimited', '--stt-requests', '3', '--listen-max-seconds', '90',
        '--listen-max-utterances', '7', '--listen-max-session-starts', '2',
        '--listen-max-total-starts', '6', '--listen-max-recognition-streams', '8', '--turns', '9')
    limits = cli._listening_limits(args)
    assert (limits.max_seconds, limits.max_samples, limits.max_utterances,
            limits.max_streams_per_session, limits.max_total_streams,
            limits.max_recognition_streams) == (90, 90 * 16000, 7, 2, 6, 8)
    assert args.stt_requests == 3 and cli._session_turn_limit(args) == 9


def test_application_stt_unlimited_does_not_allow_unlimited_tts_or_probe():
    voice = DevelopmentVoiceLimits(tts_request_limit=20, stt_request_limit=None,
        tts_max_audio_seconds=30, stt_max_input_seconds=120, usage_profile=UsageProfile.APPLICATION)
    assert voice.stt_request_limit is None
    with pytest.raises(ConfigurationError):
        replace(voice, tts_request_limit=None)
    with pytest.raises(ConfigurationError):
        replace(voice, usage_profile=UsageProfile.PROBE)


@pytest.mark.asyncio
async def test_shared_unlimited_budget_counts_three_hundred_concurrent_attempts_truthfully():
    budget = _AttemptBudget(None, 'input_limit')
    await asyncio.gather(*(budget.reserve() for _ in range(300)))
    assert budget.snapshot() == RequestBudgetSnapshot(300, None)
    assert budget.snapshot().remaining is None
    finite = _AttemptBudget(2, 'input_limit')
    await finite.reserve(); await finite.reserve()
    with pytest.raises(SpeechProviderError):
        await finite.reserve()
    assert finite.snapshot().used == 2 and finite.snapshot().remaining == 0


def test_wire_keeps_large_accounting_count_with_null_remaining():
    uid = '12345678-1234-4234-8234-123456789012'
    ready = ContinuousListeningReady(lease_id=uid, max_seconds=None, max_samples=None,
        max_utterances=None, max_streams_per_session=None, max_total_streams=None,
        max_recognition_streams=None, session_lease_starts_used=300, total_lease_starts_used=600,
        stt_requests_used=999, stt_requests_remaining=None,
        endpoint_mode='google_vad_offsets_natural', manual_commit_required=False)
    assert ready.stt_requests_used == 999 and ready.stt_requests_remaining is None
    event = ContinuousListeningRecognitionStatus(lease_id=uid, stream_index=301,
        state='listening', stt_requests_used=999, stt_requests_remaining=None)
    assert event.stt_requests_used == 999


def test_cli_check_exposes_actual_unlimited_voice_defaults_without_constructing_services(tmp_path, monkeypatch, capsys):
    import json
    env = tmp_path / 'synthetic.env'
    env.write_text('MIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\nMIRA_SERVICES__SPEECH__TTS_VOICE=Kore\n')
    env.chmod(0o600)
    adc = tmp_path / 'synthetic-adc.json'; adc.write_text('{}'); adc.chmod(0o600)
    monkeypatch.setattr(cli, '_voice_factory', lambda *_: pytest.fail('No provider construction'))
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('No model request'))
    assert cli.main(['check', '--provider', 'chatgpt_subscription', '--model', 'gpt-6.1-sol',
        '--env-file', str(env), '--voice', '--adc-file', str(adc)]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['generation_request_limit'] is value['turn_limit'] is None
    voice = value['continuous_listening']
    assert all(voice[key] is None for key in ('max_lease_seconds', 'max_utterances_per_lease',
        'max_session_starts', 'max_total_starts', 'max_recognition_streams_per_lease', 'stt_requests_per_process'))
    assert voice['max_recognition_rpc_seconds'] == 120


@pytest.mark.parametrize('finite', [False, True])
def test_real_factory_keeps_shared_stt_declaration_and_nullable_lease_consistent(monkeypatch, finite):
    from fastapi.testclient import TestClient
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from tests.contracts.test_development_voice_composition import make_factory
    from tests.contracts.test_direct_provider_app import arguments
    voice_limits = DevelopmentVoiceLimits(tts_request_limit=20, stt_request_limit=3 if finite else None,
        tts_max_audio_seconds=30, stt_max_input_seconds=120, usage_profile=UsageProfile.APPLICATION)
    factory, calls, _, _, _ = make_factory(monkeypatch, voice_limits=voice_limits)
    args = parsed(*(['--listen-max-seconds', '200', '--listen-max-utterances', '3', '--listen-max-recognition-streams', '7'] if finite else []))
    app = create_direct_provider_app(**arguments(usage_profile=UsageProfile.APPLICATION,
        generation_request_limit=None, session_turn_limit=None, voice_required=True,
        local_listening_limits=cli._listening_limits(args), voice_usage_limits=voice_limits, voice_factory=factory))
    assert calls == []
    with TestClient(app):
        assert len(calls) == 1
        container = app.state.container
        limits = container.listening_leases.limits
        assert limits.max_seconds == (200 if finite else None)
        assert limits.max_utterances == (3 if finite else None)
        assert limits.max_recognition_streams == (7 if finite else None)
        assert limits.max_streams_per_session is limits.max_total_streams is None
        assert container.stt_request_budget.snapshot().used == 0
        assert container.stt_request_budget.snapshot().remaining == (3 if finite else None)
        assert app.state.usage_declaration.stt_requests == (3 if finite else None)
        assert app.state.usage_declaration.tts_requests == 20


def test_null_stt_declaration_cannot_hide_a_finite_composed_budget():
    from types import SimpleNamespace
    from mira.entrypoints.http.continuous_listening_routes import _usage_budget
    from mira.domain.errors import DomainError
    budget = _AttemptBudget(3, 'input_limit')
    state = SimpleNamespace(container=SimpleNamespace(stt_request_budget=budget),
        usage_declaration=SimpleNamespace(stt_requests=None, stt_max_stream_seconds=120))
    with pytest.raises(DomainError, match='does not match'):
        _usage_budget(SimpleNamespace(app=SimpleNamespace(state=state)))
