"""Offline ASGI acceptance of the bounded explicit development entry."""
import hashlib
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.adapters.generation.codex_app_server import CodexRuntime
from mira.adapters.generation.codex_support.payload import canonical
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.bootstrap.development_app import _bounded_timeout, create_development_app
from mira.config.loader import ConfigurationError
from mira.config.settings import Settings
from tests.contracts.test_codex_generation import SyntheticTransport, agent, event, terminal
from tests.contracts.test_development_review_composition import SyntheticJevTransport


_FLAGS = ("apps", "plugins", "browser_use", "computer_use", "multi_agent", "shell_tool",
          "image_generation", "tool_suggest", "sleep_tool", "token_budget")


def public_runtime():
    config = {"features": dict.fromkeys(_FLAGS, False), "mcp_servers": {},
              "web_search": "disabled", "model": "gpt-6-luna", "model_provider": "openai",
              "forced_login_method": "chatgpt", "approval_policy": "never",
              "sandbox_mode": "read-only"}
    config["features"]["respect_system_proxy"] = True
    return CodexRuntime(
        # Synthetic transport factories never touch these paths.
        executable=__import__("pathlib").Path("/synthetic/codex"),
        codex_home=__import__("pathlib").Path("/synthetic/home"),
        runtime_cwd=__import__("pathlib").Path("/synthetic/run"),
        expected_config_sha256=hashlib.sha256(canonical(config)).hexdigest(),
        policy_environment_confirmed=True,
    )


def make_app(*, output_choice="allow", input_unknown=False, codex_events=None,
             authorized=True, web_root=None, **limits):
    text_output = {"effects": [
        {"kind": "subtitle", "value": "我写下一句新的话。"},
        {"kind": "pose", "value": "face_warm"},
    ]}
    codex = SyntheticTransport(events=codex_events if codex_events is not None else [
        event("item/completed", item=agent(json.dumps(text_output, ensure_ascii=False))), terminal(),
    ])

    async def codex_factory(_runtime, _limits):
        return codex

    input_jev = SyntheticJevTransport(input_unknown=input_unknown)
    output_jev = SyntheticJevTransport(output_choice=output_choice)
    app = create_development_app(
        runtime=public_runtime(), settings=Settings(), route_kind="public",
        input_transport=input_jev, output_transport=output_jev,
        authorized=authorized, decision_policy=USER_DEVELOPMENT_0_6_V1,
        codex_transport_factory=codex_factory, web_root=web_root, **limits,
    )
    return app, codex, input_jev, output_jev


def wait_ready(client, path, headers):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        result = client.get(path, headers=headers)
        if result.status_code == 200 and result.json()["phase"] in ("ready", "error", "idle"):
            return result.json()
        time.sleep(0.01)
    raise AssertionError("synthetic ASGI turn did not reach a terminal state")


def test_real_asgi_session_renders_generated_text_and_pose_without_audio():
    app, codex, input_jev, output_jev = make_app()
    with TestClient(app) as client:
        capabilities = client.get("/api/v1/voice-capabilities").json()
        assert capabilities["speech_enabled"] is False
        assert capabilities["microphone_enabled"] is False

        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
        assert created.status_code == 201
        path = "/api/v1/sessions/" + created.json()["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created.json()["session_token"]}
        request_id = str(uuid4())
        submitted = client.post(path + "/inputs", headers=headers, json={
            "request_id": request_id, "activity_seq": 1, "presentation_cutoff": 0,
            "text": "写下一句新的话，并让她露出温和的表情。",
        })
        assert submitted.status_code == 202
        result = wait_ready(client, path, headers)

        assert result["phase"] == "ready"
        assert [effect["kind"] for effect in result["active_grants"]] == ["subtitle", "pose"]
        assert result["active_grants"][0]["value"] == "我写下一句新的话。"
        assert all(effect["cue_speech_id"] is None for effect in result["active_grants"])
        assert result["audio_progress"] == []
        # The v2 coordinator asks the input question set for its stage and seal
        # snapshots; each port still stays within the explicit per-entry ceiling.
        assert len(input_jev.calls) == 2
        assert len(output_jev.calls) == 2
        assert codex.closed

        # The process admits one session and one input turn; deletion/recreation cannot
        # create more app budget because the configured instance is capped here.
        assert client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).status_code == 429
        second = client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 2, "presentation_cutoff": 0,
            "text": "再写一句。",
        })
        assert second.status_code == 429

    assert app.state.container.sessions._sessions == {}


def test_unknown_input_blocks_presentation_and_reject_stops_presentation():
    app, codex, input_jev, _ = make_app(input_unknown=True)
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "写下一句新的话。",
        })
        result = wait_ready(client, path, headers)
        assert result["active_grants"] == []
        assert len(input_jev.calls) == 1
        assert codex.closed

    app, codex, _, _ = make_app(output_choice="reject")
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "写下一句新的话。",
        })
        result = wait_ready(client, path, headers)
        assert result["active_grants"] == []
        assert codex.closed


def test_http_stop_cancels_inflight_codex_and_shutdown_closes_session():
    app, codex, _, _ = make_app(codex_events=[])
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        client.post(path + "/inputs", headers=headers, json={
            "request_id": str(uuid4()), "activity_seq": 1, "presentation_cutoff": 0,
            "text": "写下一句新的话。",
        })
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not any(
                call["method"] == "turn/start" for call in codex.sent):
            time.sleep(0.01)
        assert any(call["method"] == "turn/start" for call in codex.sent)
        stopped = client.post(path + "/stop", headers=headers, json={
            "activity_seq": 2, "presentation_cutoff": 0,
        })
        assert stopped.status_code == 200
        assert stopped.json()["active_grants"] == []
        assert codex.interrupted
        assert codex.closed

    assert app.state.container.sessions._sessions == {}


def test_unarmed_or_voice_required_factory_is_rejected():
    runtime = public_runtime()
    transport = SyntheticJevTransport()
    with pytest.raises(ConfigurationError, match="explicit transmission"):
        create_development_app(runtime=runtime, settings=Settings(), route_kind="public",
            input_transport=transport, output_transport=transport, authorized=False)
    with pytest.raises(ConfigurationError, match="in-process voice factory"):
        create_development_app(runtime=runtime, settings=Settings(), route_kind="public",
            input_transport=transport, output_transport=transport, authorized=True,
            voice_required=True)


def test_usage_profiles_keep_probe_ceiling_and_allow_only_explicit_finite_application_bounds():
    # The default remains the historical probe profile, including rejection at 9.
    app, _, _, _ = make_app(codex_request_limit=8, session_turn_limit=8,
                            input_request_limit=8, output_request_limit=8)
    assert app.state.usage_declaration.profile.value == "probe"
    assert app.state.usage_declaration.codex_requests == 8
    assert app.state.usage_snapshot.codex_requests_used is None
    with pytest.raises(ConfigurationError):
        make_app(codex_request_limit=9, session_turn_limit=9)

    app, _, _, _ = make_app(
        codex_request_limit=100, session_turn_limit=100,
        input_request_limit=100, output_request_limit=100,
        usage_profile="application",
    )
    assert app.state.usage_declaration.profile.value == "application"
    assert app.state.usage_declaration.input_jev_requests == 100
    assert app.state.usage_declaration.session_turns == 100

    with pytest.raises(ConfigurationError):
        make_app(codex_request_limit=101, session_turn_limit=100,
                 usage_profile="application")
    with pytest.raises(ConfigurationError):
        make_app(codex_request_limit=100, session_turn_limit=100,
                 input_request_limit=True, usage_profile="application")
    with pytest.raises(ConfigurationError):
        make_app(codex_request_limit=100, session_turn_limit=100,
                 usage_profile=True)


@pytest.mark.parametrize("value", [10**1000, float("inf"), float("nan"), 0, -1, True])
def test_timeout_limit_rejects_huge_or_invalid_values_before_transport(value):
    with pytest.raises(ConfigurationError):
        _bounded_timeout(value, "JEV timeout")


def test_voice_profile_drives_continuous_lease_start_cap_and_shared_stt_budget():
    from mira.bootstrap.development_voice import DevelopmentVoiceLimits, _AttemptBudget
    from mira.bootstrap.providers import GoogleVoiceProviders

    async def close():
        return None

    class _OrdinaryRecognition:
        pass

    class _ContinuousRecognition:
        max_stream_seconds = 290
        endpoint_mode = "google_vad_offsets"

        async def transcribe_events(self, packets):
            if False:
                yield None

    profile_limits = DevelopmentVoiceLimits(tts_request_limit=100, stt_request_limit=100,
        tts_max_audio_seconds=30, stt_max_input_seconds=290, usage_profile="application")
    shared_budget = _AttemptBudget(100, "input_limit")
    def voice_factory():
        return GoogleVoiceProviders(_OrdinaryRecognition(), object(), close,
            continuous_speech_recognition=_ContinuousRecognition(),
            stt_request_budget=shared_budget)
    app, _, _, _ = make_app(codex_request_limit=100, session_turn_limit=100,
        input_request_limit=100, output_request_limit=100, usage_profile="application",
        voice_required=True, voice_factory=voice_factory, voice_usage_limits=profile_limits)
    with TestClient(app):
        assert app.state.usage_declaration.stt_requests == 100
        assert app.state.container.listening_leases.limits.max_total_streams == 100
        assert app.state.container.listening_leases.limits.max_seconds == 120
        assert app.state.container.stt_request_budget is shared_budget
        capabilities = TestClient(app).get("/api/v1/voice-capabilities").json()
        assert capabilities["continuous_listening_enabled"] is True

    probe_limits = DevelopmentVoiceLimits(tts_request_limit=8, stt_request_limit=8,
        tts_max_audio_seconds=30, stt_max_input_seconds=30, usage_profile="probe")
    probe_budget = _AttemptBudget(8, "input_limit")
    probe_factory = lambda: GoogleVoiceProviders(_OrdinaryRecognition(), object(), close,
        continuous_speech_recognition=_ContinuousRecognition(), stt_request_budget=probe_budget)
    probe_app, _, _, _ = make_app(voice_required=True, voice_factory=probe_factory,
                                  voice_usage_limits=probe_limits)
    with TestClient(probe_app):
        assert probe_app.state.container.listening_leases.limits.max_total_streams == 8
        assert probe_app.state.container.listening_leases.limits.max_seconds == 30

    # A fractional policy is still usable by ordinary PTT, but this whole-second
    # lease API must not round its display/provider allowance up to one second.
    short_limits = DevelopmentVoiceLimits(tts_request_limit=1, stt_request_limit=1,
        tts_max_audio_seconds=1, stt_max_input_seconds=0.001, usage_profile="probe")
    short_factory = lambda: GoogleVoiceProviders(_OrdinaryRecognition(), object(), close,
        continuous_speech_recognition=_ContinuousRecognition(), stt_request_budget=_AttemptBudget(1, "input_limit"))
    short_app, _, _, _ = make_app(voice_required=True, voice_factory=short_factory,
                                  voice_usage_limits=short_limits)
    with TestClient(short_app) as client:
        assert short_app.state.container.microphone_enabled is True
        assert short_app.state.container.listening_leases.limits.max_seconds == 0
        assert short_app.state.container.listening_leases.limits.max_samples == 0
        assert short_app.state.usage_declaration.stt_max_stream_seconds == 0.001
        assert client.get("/api/v1/voice-capabilities").json()["continuous_listening_enabled"] is False
