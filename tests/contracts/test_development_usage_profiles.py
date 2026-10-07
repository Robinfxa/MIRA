"""Finite, explicit usage declarations; no provider/network calls occur here."""
import math

import pytest

from mira.bootstrap.development_usage import (
    UsageDeclaration, UsageProfile, UsageSnapshot,
)
from mira.config.loader import ConfigurationError


def declaration(profile="probe", **overrides):
    values = dict(
        profile=profile, codex_requests=1, session_turns=1,
        input_jev_requests=2, output_jev_requests=2,
        input_jev_timeout_seconds=10, output_jev_timeout_seconds=10,
    )
    values.update(overrides)
    return UsageDeclaration(**values)


def test_usage_declaration_is_typed_immutable_and_preserves_unknown_current_counts():
    limits = declaration("application", codex_requests=100, session_turns=100,
                         input_jev_requests=100, output_jev_requests=100,
                         tts_requests=100, stt_requests=100,
                         tts_max_audio_seconds=30, stt_max_stream_seconds=290)
    snapshot = UsageSnapshot(limits, active_stt_stream_seconds=120, elapsed_seconds=3.5)
    assert limits.profile is UsageProfile.APPLICATION
    assert snapshot.stt_requests_used is None
    assert snapshot.active_stt_stream_seconds == 120
    with pytest.raises((AttributeError, TypeError)):
        limits.codex_requests = 7


@pytest.mark.parametrize("values", [
    {"codex_requests": True}, {"codex_requests": 0}, {"codex_requests": 101},
    {"profile": "unknown"}, {"profile": True},
    {"session_turns": 9},
    {"input_jev_timeout_seconds": 0},
    {"input_jev_timeout_seconds": math.inf},
    {"codex_requests": 2, "session_turns": 1},
])
def test_probe_and_shared_declaration_reject_invalid_limits(values):
    with pytest.raises(ConfigurationError):
        declaration(**values)


@pytest.mark.parametrize("values", [
    {"profile": "application", "codex_requests": 101, "session_turns": 100},
    {"profile": "application", "session_turns": 101, "codex_requests": 100},
    {"profile": "application", "input_jev_requests": -1},
    {"profile": "application", "tts_requests": 10},
])
def test_application_declaration_rejects_invalid_or_partial_voice_values(values):
    with pytest.raises(ConfigurationError):
        declaration(**values)


def test_usage_snapshot_rejects_counts_or_active_stream_duration_over_declared_bound():
    limits = declaration("application", codex_requests=2, session_turns=2,
                         input_jev_requests=2, output_jev_requests=2,
                         tts_requests=2, stt_requests=2,
                         tts_max_audio_seconds=30, stt_max_stream_seconds=120)
    with pytest.raises(ConfigurationError):
        UsageSnapshot(limits, codex_requests_used=3)
    with pytest.raises(ConfigurationError):
        UsageSnapshot(limits, active_stt_stream_seconds=121)
    with pytest.raises(ConfigurationError):
        UsageSnapshot(limits, active_tts_audio_seconds=float("nan"))


@pytest.mark.parametrize('profile,maximum', [('probe', 8), ('application', 100)])
def test_preparation_limit_validation_is_idempotent_before_metadata(profile, maximum):
    from tools import prepare_runtime_admission as prepare
    args = prepare._parser().parse_args([
        '--prepare', '--usage-profile', profile,
        '--codex-requests', str(maximum), '--session-turns', str(maximum),
        '--input-jev-requests', str(maximum), '--output-jev-requests', str(maximum),
        '--input-jev-timeout-seconds', '5', '--output-jev-timeout-seconds', '5',
        '--probe-timeout-seconds', '5', '--confirm-policy-environment',
        '--authorize-codex-and-jev-content',
    ])
    prepare._require_invocation(args)
    prepare._require_invocation(args)  # main + _prepare both validate; no process is started.
    assert args.codex_requests == maximum
    assert args.input_jev_requests == maximum
    args.output_jev_requests = maximum + 1
    with pytest.raises(prepare.PreparationError, match='usage_profile_request_ceiling_invalid'):
        prepare._require_invocation(args)
    args.output_jev_requests = True
    with pytest.raises(prepare.PreparationError, match='usage_profile_request_ceiling_invalid'):
        prepare._require_invocation(args)
