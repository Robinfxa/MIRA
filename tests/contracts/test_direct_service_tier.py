"""Requested Fast tier contracts: synthetic HTTP, no credential storage or live service."""
import asyncio
import json
from dataclasses import asdict

import httpx
import pytest

from mira.adapters.generation.direct_codex_responses import (
    DirectCodexResponsesGenerationBackend, DirectResponsesError, ResponsesRoute,
)
from tests.contracts.test_direct_codex_responses import (
    BlockingStream, CredentialSource, collect, completed, event, item_done, response,
)
from tests.contracts.test_live_provider_launcher import env
from tools import live_provider as cli


def make_backend(handler, *, route="chatgpt_subscription", model="gpt-6-luna", **options):
    source = CredentialSource()
    calls = []

    async def handle(request):
        calls.append(request)
        return await handler(request)

    adapter = DirectCodexResponsesGenerationBackend(
        ResponsesRoute(route), model, source, admitted=True, request_limit=2,
        transport=httpx.MockTransport(handle), **options)
    return adapter, source, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("route,model,selection,expected", [
    ("chatgpt_subscription", "gpt-6-luna", None, "priority"),
    ("chatgpt_subscription", "other-model", None, None),
    ("openai_api", "gpt-6-luna", None, None),
    ("chatgpt_subscription", "gpt-6-luna", "standard", None),
    ("chatgpt_subscription", "gpt-6-luna", "fast", "priority"),
    ("openai_api", "gpt-6-luna", "standard", "default"),
    ("openai_api", "gpt-6-luna", "fast", "priority"),
])
async def test_request_tier_selection(route, model, selection, expected):
    async def handle(request):
        body = json.loads(request.content)
        assert body.get("service_tier") == expected
        assert ("service_tier" in body) == (expected is not None)
        assert "reasoning" not in body
        assert body["stream"] is True and body["store"] is False
        return response(item_done() + completed())

    options = {} if selection is None else {"service_tier": selection}
    adapter, source, calls = make_backend(handle, route=route, model=model, **options)
    assert len(await collect(adapter)) == 1
    assert len(calls) == source.calls == 1


@pytest.mark.parametrize("selection", ["priority", "auto", "flex", "", 1, True, [], {}])
def test_invalid_tier_rejected_before_io(selection):
    source = CredentialSource()
    with pytest.raises(ValueError, match="service_tier"):
        DirectCodexResponsesGenerationBackend(
            ResponsesRoute.CHATGPT_SUBSCRIPTION, "gpt-6-luna", source,
            service_tier=selection)
    assert source.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("present,value,classification,confirmed", [
    (False, None, "absent", False), (True, None, "absent", False),
    (True, "priority", "priority", True), (True, "default", "default", False),
    (True, "flex", "flex", False), (True, "scale", "scale", False),
    (True, "auto", "auto", False), (True, "fast", "fast", True),
    (True, "private-provider-value", "unknown", False),
    (True, {"secret": "private-provider-value"}, "invalid", False),
    (True, ["priority"], "invalid", False), (True, 1, "invalid", False),
])
async def test_terminal_tier_observation_is_closed_and_optional(present, value, classification, confirmed):
    reports = []
    async def handle(_):
        final = {"status": "completed", "output": None}
        if present:
            final["service_tier"] = value
        return response(item_done() + event("response.completed", {
            "type": "response.completed", "response": final}))

    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    assert len(await collect(adapter)) == 1
    assert len(reports) == len(calls) == source.calls == 1
    report = asdict(reports[0])
    assert report["requested_service_tier"] == "fast"
    assert report["request_service_tier"] == "priority"
    assert report["provider_service_tier"] == classification
    assert report["fast_confirmed"] is confirmed
    assert report["outcome"] == "completed"
    assert "private-provider-value" not in json.dumps(report)


@pytest.mark.asyncio
async def test_created_tier_is_not_final_confirmation():
    reports = []
    async def handle(_):
        return response(event("response.created", {"type": "response.created",
            "response": {"service_tier": "priority"}}) + item_done() + completed())
    adapter, _, _ = make_backend(handle, tier_observer=reports.append)
    await collect(adapter)
    assert reports[0].provider_service_tier == "absent"
    assert reports[0].fast_confirmed is False


@pytest.mark.asyncio
async def test_observer_failure_does_not_fail_content():
    def broken(_):
        raise RuntimeError("observer failure must not affect content")
    async def handle(_):
        return response(item_done() + completed())
    adapter, source, calls = make_backend(handle, tier_observer=broken)
    assert len(await collect(adapter)) == 1
    assert len(calls) == source.calls == 1


@pytest.mark.asyncio
async def test_rejected_tier_is_recoverable_without_retry():
    reports = []
    async def handle(_):
        return response(json.dumps({"error": {"param": "service_tier",
            "code": "unsupported_value", "message": "private-provider-message"}}).encode(),
            status=400, headers={"content-type": "application/json"})
    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    for count in (1, 2):
        with pytest.raises(DirectResponsesError) as raised:
            await collect(adapter)
        assert raised.value.code == "invalid_input"
        assert raised.value.reason == "service_tier_rejected"
        assert raised.value.generation_diagnostic.requested_service_tier == "fast"
        assert raised.value.generation_diagnostic.provider_service_tier == "unobserved"
        assert len(calls) == source.calls == count
    assert reports[0].outcome == "failed"
    assert reports[0].reason == "service_tier_rejected"
    assert "private-provider-message" not in json.dumps(asdict(reports[0]))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, "unauthenticated"), (403, "permission_denied"),
    (429, "quota_exhausted"), (500, "unavailable"), (400, "invalid_input")])
async def test_other_errors_keep_original_classification(status, code):
    reports = []
    async def handle(_):
        return httpx.Response(status, json={"error": {"param": "model", "message": "secret"}})
    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(adapter)
    assert raised.value.code == code
    assert raised.value.reason != "service_tier_rejected"
    assert reports[0].outcome == "failed" and not reports[0].fast_confirmed
    assert len(calls) == source.calls == 1


@pytest.mark.asyncio
async def test_cancel_keeps_no_extra_calls():
    reports = []
    stream = BlockingStream(item_done())
    async def handle(_):
        return response(None, stream=stream)
    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    task = asyncio.create_task(collect(adapter))
    await asyncio.wait_for(stream.entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed and len(calls) == source.calls == 1
    assert reports[0].outcome == "cancelled" and not reports[0].fast_confirmed


@pytest.mark.parametrize("route,model,selection,requested,wire", [
    ("chatgpt_subscription", "gpt-6-luna", None, "fast", "priority"),
    ("chatgpt_subscription", "gpt-6-luna", "standard", "standard", "omitted"),
    ("chatgpt_subscription", "other-model", None, "unspecified", "omitted"),
    ("openai_api", "gpt-6-luna", None, "unspecified", "omitted"),
])
def test_check_declares_requested_tier_without_auth(tmp_path, monkeypatch, capsys,
        route, model, selection, requested, wire):
    monkeypatch.setattr(cli, "_generation", lambda *_: pytest.fail("auth must not load"))
    args = ["check", "--provider", route, "--model", model, "--env-file", str(env(tmp_path))]
    if selection:
        args += ["--service-tier", selection]
    assert cli.main(args) == 0
    report = json.loads(capsys.readouterr().out)["service_tier"]
    assert report["requested"] == requested and report["wire_value"] == wire
    assert report["provider_confirmation"] == "not_run"
    assert report["subscription_fast_usage_multiplier"] == (2.5 if route == "chatgpt_subscription" and requested == "fast" else None)


def test_cli_passes_selection_and_safe_observer(tmp_path, monkeypatch, capsys):
    from mira.adapters.generation import direct_codex_responses as module
    from mira.application.generation_diagnostics import SafeServiceTierDiagnostic
    args = cli._parser().parse_args(["check", "--provider", "chatgpt_subscription",
        "--model", "gpt-6-luna", "--service-tier", "standard", "--env-file", str(env(tmp_path))])
    settings, _ = cli._load(args)
    captured = {}
    def capture(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(module, "DirectCodexResponsesGenerationBackend", capture)
    cli._generation(args, settings)
    assert captured["service_tier"] == "standard"
    captured["tier_observer"](SafeServiceTierDiagnostic("standard", "omitted", "absent", "completed"))
    report = json.loads(capsys.readouterr().err)["service_tier"]
    assert report["requested_service_tier"] == "standard" and report["fast_confirmed"] is False


@pytest.mark.asyncio
async def test_sse_tier_rejection_is_visible_without_retry():
    reports = []
    async def handle(_):
        return response(event("response.failed", {"type": "response.failed", "response": {
            "status": "failed", "error": {"param": "service_tier", "message": "PRIVATE"}}}))
    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(adapter)
    assert raised.value.reason == "service_tier_rejected"
    assert reports[0].outcome == "failed" and not reports[0].fast_confirmed
    assert len(calls) == source.calls == 1


@pytest.mark.asyncio
async def test_transport_timeout_has_no_retry_or_false_confirmation():
    reports = []
    async def handle(_):
        raise httpx.ReadTimeout("PRIVATE timeout details")
    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(adapter)
    assert raised.value.code == "timeout"
    assert reports[0].outcome == "failed" and not reports[0].fast_confirmed
    assert len(calls) == source.calls == 1
    assert "PRIVATE" not in json.dumps(asdict(reports[0]))


@pytest.mark.asyncio
async def test_tier_error_diagnostic_roundtrips_and_legacy_fields_remain_optional():
    from mira.adapters.diagnostics.privacy import validate_event_record
    from tests.contracts.test_direct_generation_diagnostics import actor_failure
    async def handle(_):
        return response(b'{"error":{"param":"service_tier","message":"PRIVATE"}}',
            status=400, headers={"content-type": "application/json"})
    adapter, _, _ = make_backend(handle)
    record = await actor_failure(adapter)
    tier = record["generation_diagnostic"]
    assert tier["requested_service_tier"] == "fast"
    assert tier["request_service_tier"] == "priority"
    assert tier["provider_service_tier"] == "unobserved"
    for name in ("requested_service_tier", "request_service_tier", "provider_service_tier"):
        del tier[name]
    restored = validate_event_record(record)["generation_diagnostic"]
    assert restored["requested_service_tier"] == "unspecified"
    assert restored["provider_service_tier"] == "unobserved"


@pytest.mark.parametrize("field,value", [("requested_service_tier", "PRIVATE"),
    ("request_service_tier", "PRIVATE"), ("provider_service_tier", "PRIVATE")])
def test_tier_diagnostic_rejects_unbounded_fields(field, value):
    from mira.application.generation_diagnostics import SafeGenerationDiagnostic
    with pytest.raises(ValueError):
        SafeGenerationDiagnostic("transport", "other", **{field: value})


def test_cli_invalid_tier_fails_before_config_read(monkeypatch):
    monkeypatch.setattr(cli, "_load", lambda *_: pytest.fail("no config read"))
    with pytest.raises(SystemExit) as raised:
        cli.main(["check", "--provider", "chatgpt_subscription", "--model", "gpt-6-luna",
                  "--env-file", "/synthetic/mira.env", "--service-tier", "priority"])
    assert raised.value.code == 2


def test_cli_recovery_is_actionable_and_unconfirmed_success_is_honest(capsys):
    from mira.application.generation_diagnostics import SafeServiceTierDiagnostic
    cli._report_service_tier(SafeServiceTierDiagnostic("fast", "priority", "unobserved",
        "failed", "service_tier_rejected"))
    failure = json.loads(capsys.readouterr().err)["service_tier"]
    assert "--service-tier standard" in failure["recovery"]
    cli._report_service_tier(SafeServiceTierDiagnostic("fast", "priority", "default", "completed"))
    success = json.loads(capsys.readouterr().err)["service_tier"]
    assert not success["fast_confirmed"] and "did not confirm" in success["notice"]


@pytest.mark.asyncio
async def test_top_level_sse_tier_rejection_is_actionable():
    reports = []
    async def handle(_):
        return response(event("error", {"type": "error", "code": "unsupported_service_tier",
            "message": "PRIVATE"}))
    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(adapter)
    assert raised.value.reason == "service_tier_rejected"
    assert len(calls) == source.calls == 1


@pytest.mark.asyncio
async def test_tier_observation_resets_for_each_request():
    reports = []
    async def handle(_):
        if not reports:
            return response(item_done() + event("response.completed", {"type": "response.completed",
                "response": {"status": "completed", "output": None, "service_tier": "priority"}}))
        return response(item_done() + completed())
    adapter, source, calls = make_backend(handle, tier_observer=reports.append)
    await collect(adapter)
    await collect(adapter)
    assert reports[0].fast_confirmed and not reports[1].fast_confirmed
    assert reports[1].provider_service_tier == "absent"
    assert len(calls) == source.calls == 2
