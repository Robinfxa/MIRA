"""Native bootstrap: local synthetic checks, no provider/account acceptance claim."""
import json

import pytest

from mira.config.settings import Settings
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from tools import live_provider as cli


class NativeGeneration:
    async def generate(self, context):
        raise AssertionError("native factory must use the tool-capable turn")
        yield

    def open_tool_turn(self, context, tools):
        raise AssertionError("composition must not make a request")


def env(tmp_path, text=""):
    path = tmp_path / "synthetic.env"
    path.write_text(text)
    path.chmod(0o600)
    return path


def args(path, command="check"):
    return [command, "--provider", "chatgpt_subscription", "--model", "gpt-6-luna",
            "--env-file", str(path)]


def test_default_check_needs_no_jev_configuration_or_service_calls(tmp_path, capsys, monkeypatch):
    import mira.bootstrap.development_review as reviews
    monkeypatch.setattr(reviews, "create_development_review_providers", lambda **_: pytest.fail("JEV factory"))
    monkeypatch.setattr(cli, "_generation", lambda *_: pytest.fail("model construction"))
    assert cli.main(args(env(tmp_path))) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["action_review_mode"] == "luna_tools"
    assert result["review_request_limits"]["total_max_requests"] == 0
    assert result["semantic_chunking"]["planner"] == "deterministic"
    assert result["media_tools"]["normal_chat_model_requests"] == 1
    assert result["media_tools"]["max_model_requests_per_tool_turn"] == 2
    assert result["auth_store"] == "not_loaded" and result["inference"] == "not_run"


def test_default_loader_does_not_resolve_or_validate_unused_jev_values(tmp_path):
    path = env(tmp_path, "MIRA_SERVICES__JEV__API_KEY=invalid unused secret\n"
        "TYPESAFE_API_KEY=conflicting unused secret\n"
        "MIRA_SERVICES__JEV__BASE_URL=invalid unused URL\n"
        "MIRA_SERVICES__JEV__MODEL=invalid model\n")
    settings, _ = cli._load(cli._parser().parse_args(args(path)))
    assert settings.services.jev.api_key is None


def test_default_real_factory_constructs_no_review_objects_or_transports(monkeypatch):
    import mira.bootstrap.development_review as reviews
    import mira.adapters.review.mock as fixtures
    monkeypatch.setattr(reviews, "create_development_review_providers", lambda **_: pytest.fail("JEV factory"))
    monkeypatch.setattr(fixtures, "FixtureReviewBackend", lambda *_: pytest.fail("fixture review"))
    generation = NativeGeneration()
    app = create_direct_provider_app(generation=generation, tool_generation=generation,
        model="gpt-6-luna", settings=Settings(), route="chatgpt_subscription", authorized=True)
    assert app.state.action_review_mode == "luna_tools"
    assert app.state.usage_declaration.input_jev_requests == 0
    assert app.state.usage_declaration.output_jev_requests == 0
    assert app.state.usage_declaration.boundary_jev_requests == 0


def test_native_recipient_labels_name_only_selected_route_and_explicit_voice():
    assert cli._memory_recipients("chatgpt_subscription") == ["OpenAI ChatGPT subscription backend"]
    assert cli._memory_recipients("openai_api", True) == ["OpenAI official API",
        "Google Cloud TTS (approved generated speech may contain recalled evidence)"]


@pytest.mark.asyncio
@pytest.mark.parametrize("speech", [False, True])
async def test_deterministic_caption_split_preserves_source_and_speech_cue(monkeypatch, speech):
    import asyncio
    from mira.application.semantic_chunking import DeterministicCaptionChunking, legal_boundaries
    from tests.contracts.test_semantic_chunking import Source, CONTEXT, TEXT, captions
    from mira.domain.models import EffectKind
    source = Source(speech=speech)
    monkeypatch.setattr(asyncio, "create_task", lambda *_a, **_kw: pytest.fail("no remote or timing task"))
    actual = [part async for part in DeterministicCaptionChunking(source).generate(CONTEXT)]
    assert "".join(captions(actual)) == TEXT
    assert all(part.fixture_id == source.candidate.fixture_id for part in actual)
    if speech:
        assert actual == [source.candidate]
        assert sum(e.kind is EffectKind.SPEECH for part in actual for e in part.effects) == 1
    else:
        assert 2 <= len(actual) <= 4
        assert all(part.caption_chunk.end in legal_boundaries(TEXT) for part in actual)
        assert [part.caption_chunk.index for part in actual] == list(range(len(actual)))


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["短句。", "（括号没有闭合。" * 8, "x" * 4097,
    "雨停了？\u200d后面的字符应保持原来的组合。" * 3])
async def test_deterministic_unsafe_or_overlimit_caption_is_not_arbitrarily_cut(text):
    from mira.application.semantic_chunking import DeterministicCaptionChunking
    from tests.contracts.test_semantic_chunking import Source, CONTEXT, captions
    source = Source(text)
    actual = [part async for part in DeterministicCaptionChunking(source).generate(CONTEXT)]
    assert "".join(captions(actual)) == text
    if text.startswith(("短句", "（", "x")):
        assert actual == [source.candidate]
    assert all(not value.startswith("\u200d") for value in captions(actual))


def test_explicit_legacy_mode_still_requires_jev_configuration(tmp_path, capsys):
    assert cli.main(args(env(tmp_path)) + ["--action-review-mode", "legacy_jev"]) == 2
    assert "TypeSafe/JEV key" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--legacy-media-proposals"], ["--boundary-max-requests", "1"]])
def test_native_mode_refuses_accidental_legacy_review_dispatch(tmp_path, capsys, extra):
    assert cli.main(args(env(tmp_path)) + extra) == 2
    assert json.loads(capsys.readouterr().err)["stage"] == "action_review_configuration"



def test_native_archive_pairing_and_fixed_scope_stay_local_until_recall_authorized(tmp_path, monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from mira.bootstrap import development_review
    from mira.domain.memory import MemoryScope
    from mira.application.contracts import CandidateRange, EffectProposal
    from mira.domain.models import EffectKind
    from mira.entrypoints.http.operator_pairing import OperatorPairing
    from tests.contracts.test_paired_conversation_lifecycle import (
        options, seed, CODE, ORIGIN, pair, turn,
    )
    opts = options(tmp_path)
    seed(opts, "allowed", "Synthetic selected past conversation.")
    seed(replace(opts, scope=MemoryScope("other-owner", "mira", "synthetic-world")),
         "foreign", "Synthetic foreign scope must never reach a provider.")
    monkeypatch.setattr(development_review, "create_development_review_providers",
        lambda **_: pytest.fail("native archive cannot construct JEV review"))
    contexts = []
    class Generation(NativeGeneration):
        def open_tool_turn(self, context, tools):
            contexts.append(context)
            class Turn:
                async def start(self):
                    return CandidateRange((EffectProposal(EffectKind.SUBTITLE,
                        "这是受限的合成档案回复。"),), "synthetic-archive-native")
                async def continue_after_tool(self, *_):
                    pytest.fail("ordinary dialogue needs one request")
                def close(self): pass
            return Turn()
    generation = Generation()
    app = create_direct_provider_app(generation=generation, tool_generation=generation,
        model="gpt-6-luna", settings=Settings(), route="chatgpt_subscription", authorized=True,
        conversation_options=opts, operator_pairing=OperatorPairing(CODE, (ORIGIN, "http://localhost:8000")))
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert client.get("/api/v1/conversations/status").status_code == 401
        pair(client)
        state = client.get("/api/v1/conversations/status").json()
        assert state["recipients"] == "OpenAI ChatGPT 订阅服务"
        assert client.get("/api/v1/conversations/sessions").json()["sessions"] == ["allowed"]
        path = "/api/v1/conversations/selection"
        assert client.post(path, json={"session_id": "allowed", "authorize_selected_provider_and_jev": False}).status_code == 409
        assert client.post(path, json={"session_id": "foreign", "authorize_selected_provider_and_jev": True}).status_code == 409
        assert client.post(path, json={"session_id": "allowed", "authorize_selected_provider_and_jev": True, "scope": "foreign"}).status_code == 422
        assert client.post(path, json={"session_id": "allowed", "authorize_selected_provider_and_jev": True}).status_code == 200
        _, _, _, state = turn(client, "Summarize only my selected prior session.")
        assert state["sealed"] and state["presented_effects"] == []
        assert len(contexts) == 1
        packet = contexts[0].conversation_recall
        assert "Synthetic selected past conversation." in packet.context_json
        assert "foreign scope" not in packet.context_json and "other-owner" not in packet.context_json


def test_default_loader_and_serve_never_access_a_jev_credential(tmp_path, monkeypatch):
    from mira.config.service_settings import JevSettings
    from mira.bootstrap import direct_provider_app, development_app
    from tools import live_voice
    observed = {}
    original = JevSettings.__getattribute__
    def guarded(self, name):
        if name in ("api_key", "model", "base_url"):
            pytest.fail("unused JEV configuration accessed")
        return original(self, name)
    monkeypatch.setattr(JevSettings, "__getattribute__", guarded)
    monkeypatch.setattr(development_app, "jev_transport_from_settings", lambda *_: pytest.fail("JEV transport"))
    monkeypatch.setattr(cli, "_prepare_frontend", lambda: None)
    monkeypatch.setattr(cli, "_generation", lambda *_: NativeGeneration())
    monkeypatch.setattr(direct_provider_app, "create_direct_provider_app", lambda **kwargs: observed.update(kwargs) or object())
    monkeypatch.setattr(live_voice, "_run_uvicorn", lambda *_a, **_kw: None)
    assert cli.main(args(env(tmp_path), "serve") + ["--authorize-provider-data", "--story", "--loopback-only"]) == 0
    assert observed["action_review_mode"] == "luna_tools"
    assert observed["input_transport"] is None and observed["output_transport"] is None
    assert observed["tool_generation"] is observed["generation"]



def test_native_private_devices_keep_independent_histories_and_shared_finite_budget(settings):
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from mira.bootstrap.development_usage import UsageProfile
    from tests.contracts.test_private_device_access import private_settings, device_pairing, ORIGIN, CODES
    from tests.contracts.test_private_device_sessions import pair, create, headers
    from tests.contracts.test_direct_codex_responses import backend, response
    from tests.contracts.test_direct_luna_tools import wire, message
    from tests.contracts.test_conversation_first import settled
    async def handle(_):
        return response(wire([message("这是一条完整的合成回复。")]))
    generation, _, requests = backend(handle, request_limit=2)
    app = create_direct_provider_app(generation=generation, tool_generation=generation,
        model="gpt-6-luna", settings=private_settings(settings), route="chatgpt_subscription",
        authorized=True, usage_profile=UsageProfile.APPLICATION, generation_request_limit=2,
        session_turn_limit=None, operator_pairing=device_pairing())
    with TestClient(app, base_url=ORIGIN) as client:
        phone = pair(client, CODES[0]); desktop = pair(client, CODES[1])
        first = create(client, phone).json(); second = create(client, desktop).json()
        assert app.state.usage_declaration.session_turns is None
        assert app.state.usage_declaration.codex_requests == 2
        assert app.state.usage_declaration.input_jev_requests == 0
        for cookie, session, text in ((phone, first, "phone-only-input"), (desktop, second, "desktop-only-input")):
            path = "/api/v1/sessions/" + session["session"]["session_id"]
            own_headers = headers(cookie, session["session_token"])
            assert client.post(path + "/inputs", headers=own_headers, json={"request_id": str(uuid4()),
                "activity_seq": 1, "presentation_cutoff": 0, "text": text}).status_code == 202
            assert settled(client, path, own_headers)["phase"] == "ready"
        assert len(requests) == 2
        assert "phone-only-input" in requests[0].content.decode() and "desktop-only-input" not in requests[0].content.decode()
        assert "desktop-only-input" in requests[1].content.decode() and "phone-only-input" not in requests[1].content.decode()
        path = "/api/v1/sessions/" + first["session"]["session_id"]
        assert client.get(path, headers=headers(desktop, first["session_token"])).status_code == 403
        own_headers = headers(phone, first["session_token"])
        assert client.post(path + "/inputs", headers=own_headers, json={"request_id": str(uuid4()),
            "activity_seq": 2, "presentation_cutoff": 0, "text": "budget exhausted"}).status_code == 202
        assert settled(client, path, own_headers)["phase"] == "error"
        assert len(requests) == 2


def test_native_complete_text_chunks_need_one_model_request_and_real_receipts():
    from fastapi.testclient import TestClient
    from tests.contracts.test_direct_codex_responses import backend, response
    from tests.contracts.test_direct_luna_tools import wire, message
    from tests.contracts.test_semantic_chunking import TEXT
    from tests.contracts.test_conversation_first import session, submit, settled
    async def handle(_): return response(wire([message(TEXT)]))
    generation, _, requests = backend(handle, request_limit=1)
    app = create_direct_provider_app(generation=generation, tool_generation=generation,
        model="gpt-6-luna", settings=Settings(), route="chatgpt_subscription", authorized=True)
    with TestClient(app) as client:
        path, headers = session(client); submit(client, path, headers)
        state = settled(client, path, headers)
        assert state["sealed"] and state["last_error"] is None
        assert len(requests) == 1 and state["presented_effects"] == []
        chunks = state["active_grants"]
        assert len(chunks) == 4 and "".join(chunk["value"] for chunk in chunks) == TEXT
        assert [chunk["caption_chunk"]["index"] for chunk in chunks] == list(range(4))
        for sequence, chunk in enumerate(chunks, 1):
            payload = {key: chunk[key] for key in ("digest", "output_epoch", "activity_seq")}
            payload.update(effect_id=chunk["id"], presentation_seq=sequence)
            assert client.post(path + "/receipts", headers=headers, json=payload).status_code == 200
        state = client.get(path, headers=headers).json()
        assert "".join(effect["value"] for effect in state["presented_effects"]) == TEXT
        assert len(requests) == 1



@pytest.mark.parametrize("mode,expected", [("luna_tools", True), ("legacy_jev", False)])
def test_cli_generation_passes_explicit_native_character_mode(monkeypatch, mode, expected):
    from mira.adapters.generation import direct_codex_responses as module
    observed = {}
    monkeypatch.setattr(module, "DirectCodexResponsesGenerationBackend", lambda **kw: observed.update(kw) or object())
    credentials = object()
    parsed = cli._parser().parse_args(args("/synthetic/not-read.env") + ["--action-review-mode", mode])
    cli._generation(parsed, Settings(), credentials)
    assert observed["native_character_tools"] is expected
    assert observed["request_limit"] == parsed.generation_requests
    assert observed["credential_source"] is credentials
