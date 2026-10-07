"""Public natural-listening limits are declared without provider/auth access."""
import json

import pytest

from tools import live_provider as cli


def _args(tmp_path):
    env = tmp_path / 'synthetic.env'
    env.write_text('MIRA_SERVICES__JEV__API_KEY=synthetic-jev\n'
        'MIRA_SERVICES__JEV__MODEL=jev-1.13.0\n'
        'MIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\n'
        'MIRA_SERVICES__SPEECH__TTS_VOICE=Kore\n')
    env.chmod(0o600)
    adc = tmp_path / 'synthetic-adc.json'
    adc.write_text('must not be parsed by check')
    adc.chmod(0o600)
    return ['check', '--provider', 'chatgpt_subscription', '--model', 'explicit-model',
        '--env-file', str(env), '--voice', '--adc-file', str(adc),
        '--stt-requests', '4', '--tts-requests', '4', '--stt-max-seconds', '60']


def test_check_exposes_effective_endpoint_limits_without_resources(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_voice_factory', lambda *_: pytest.fail('no provider allocation'))
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no model or auth lookup'))
    assert cli.main(_args(tmp_path) + ['--listen-silence-ms', '900', '--listen-grace-seconds', '0.8',
        '--listen-drain-seconds', '3', '--listen-max-recognition-streams', '6']) == 0
    rendered = capsys.readouterr().out
    settings = json.loads(rendered)['continuous_listening']
    assert settings == {
        'client_silence_ms': 900, 'natural_grace_seconds': 0.8, 'drain_timeout_seconds': 3.0,
        'max_recognition_streams_per_lease': 6, 'stt_requests_per_process': 4,
        'max_lease_seconds': None, 'max_utterances_per_lease': None,
        'max_session_starts': None, 'max_total_starts': None, 'max_recognition_rpc_seconds': 60, 'grace_is_heuristic': True,
        'microphone_requires_user_start': True, 'limits_are_dollar_caps': False,
        'provider_quality_validation': 'not_run',
    }
    assert 'synthetic' not in rendered


@pytest.mark.parametrize('flag,value', [
    ('--listen-silence-ms', '249'), ('--listen-silence-ms', '2001'),
    ('--listen-grace-seconds', '0.249'), ('--listen-grace-seconds', '2.001'),
    ('--listen-grace-seconds', 'nan'), ('--listen-drain-seconds', '0.09'),
    ('--listen-drain-seconds', '5.01'), ('--listen-drain-seconds', 'inf'),
    ('--listen-max-recognition-streams', '0'), ('--listen-max-recognition-streams', '33'),
    ('--listen-max-seconds', '0'), ('--listen-max-seconds', '291'),
    ('--listen-max-utterances', '0'), ('--listen-max-utterances', '33'),
    ('--listen-max-session-starts', '0'), ('--listen-max-session-starts', '17'),
    ('--listen-max-total-starts', '0'), ('--listen-max-total-starts', '101'),
])
def test_invalid_endpoint_limit_fails_before_private_file_access(tmp_path, monkeypatch, capsys, flag, value):
    args = _args(tmp_path)
    monkeypatch.setattr(cli, '_private_file', lambda *_: pytest.fail('invalid public limits before files'))
    assert cli.main(args + [flag, value]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error['stage'] == 'continuous_settings'
    assert error['invalid_field'] == flag[2:].replace('-', '_')
    assert 'synthetic' not in json.dumps(error)


def test_endpoint_timing_stays_finite_while_stream_count_defaults_unlimited(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_voice_factory', lambda *_: pytest.fail('no provider allocation'))
    assert cli.main(_args(tmp_path)) == 0
    settings = json.loads(capsys.readouterr().out)['continuous_listening']
    assert settings['client_silence_ms'] == 700
    assert settings['natural_grace_seconds'] == 0.65
    assert settings['drain_timeout_seconds'] == 2.0
    assert settings['max_recognition_streams_per_lease'] is None
    assert settings['stt_requests_per_process'] == 4


def test_direct_application_passes_endpoint_policy_without_expanding_shared_budget():
    from fastapi.testclient import TestClient
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from mira.bootstrap.development_usage import UsageProfile
    from mira.bootstrap.development_voice import DevelopmentVoiceLimits
    from mira.bootstrap.providers import GoogleVoiceProviders
    from mira.config.settings import Settings

    calls = []
    class Generation:
        async def generate(self, *_):
            raise AssertionError('configuration must not generate')
            yield
    class Recognition:
        async def transcribe(self, *_):
            raise AssertionError('configuration must not recognize')
            yield
        async def transcribe_events(self, *_):
            raise AssertionError('configuration must not start a stream')
            yield
    class Speech:
        async def synthesize(self, *_):
            raise AssertionError('configuration must not synthesize')
            yield
    async def review(*_):
        raise AssertionError('configuration must not review')
    async def close():
        calls.append('closed')
    recognition = Recognition()
    bundle = GoogleVoiceProviders(recognition, Speech(), close,
        continuous_speech_recognition=recognition)
    limits = DevelopmentVoiceLimits(stt_request_limit=4, tts_request_limit=4,
        stt_max_input_seconds=60, tts_max_audio_seconds=10,
        usage_profile=UsageProfile.APPLICATION)
    app = create_direct_provider_app(settings=Settings(), generation=Generation(),
        route='chatgpt_subscription', model='explicit-model', authorized=True, action_review_mode='legacy_jev',
        input_transport=review, output_transport=review, usage_profile=UsageProfile.APPLICATION,
        voice_factory=lambda: bundle, voice_usage_limits=limits, voice_required=True,
        client_silence_ms=900, natural_grace_seconds=0.8, drain_timeout_seconds=3.0, max_recognition_streams=6)
    with TestClient(app):
        actual = app.state.container.listening_leases.limits
        assert actual.client_silence_ms == 900
        assert actual.natural_grace_seconds == 0.8
        assert actual.drain_timeout_seconds == 3.0
        assert actual.max_recognition_streams == 6
        assert actual.max_total_streams is None
        assert actual.max_seconds is None and actual.max_samples is None
        assert app.state.usage_declaration.stt_requests == 4
    assert calls == ['closed']


@pytest.mark.parametrize("value", [True, False, 249, 2001, 700.0, float("inf"), "700"])
def test_silence_budget_rejects_non_integer_or_outside_bound(value):
    from mira.bootstrap.direct_provider_app import validate_natural_listening_options
    from mira.config.loader import ConfigurationError
    with pytest.raises(ConfigurationError, match="listen_silence_ms"):
        validate_natural_listening_options(client_silence_ms=value)


@pytest.mark.parametrize("value", [250, 700, 2000])
def test_silence_boundary_values_do_not_change_stream_budget(value):
    from mira.bootstrap.direct_provider_app import validate_natural_listening_options
    limits = validate_natural_listening_options(client_silence_ms=value)
    assert limits["client_silence_ms"] == value
    assert limits["max_recognition_streams"] is None


def test_unlimited_local_lease_keeps_selected_rpc_and_provider_budgets_finite(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_voice_factory', lambda *_: pytest.fail('no provider allocation'))
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('no model or auth lookup'))
    assert cli.main(_args(tmp_path) + ['--local-unlimited', '--generation-requests', '3']) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['local_interaction_policy'] == 'unlimited' and value['turn_limit'] is None
    assert value['generation_request_limit'] == 3
    limits = value['continuous_listening']
    assert limits['max_lease_seconds'] is None
    assert limits['max_recognition_streams_per_lease'] is None
    assert limits['max_recognition_rpc_seconds'] == 60
    assert limits['stt_requests_per_process'] == 4
