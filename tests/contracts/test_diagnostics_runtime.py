"""Offline composition/cancellation hooks, not live voice or microphone evidence."""
import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.application.diagnostic_events import (
    CancellationReason,
    DiagnosticOutcome,
    DiagnosticStage,
    DiagnosticStatus,
)
from mira.application.media_runtime import MediaOperation
from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app


class CollectDiagnostics:
    def __init__(self):
        self.events = []
        self.closed = False

    def emit(self, event):
        self.events.append(event)
        return True

    def capture(self, record):
        return False

    def status(self):
        return DiagnosticStatus()

    def close(self):
        self.closed = True


def test_http_and_generation_share_safe_request_session_turn_correlation():
    sink = CollectDiagnostics()
    app = create_app(Settings(providers={"mock_delay_ms": 0}), diagnostics=sink)
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        session_id, token = created["session"]["session_id"], created["session_token"]
        response = client.post(f"/api/v1/sessions/{session_id}/inputs",
            headers={"X-Mira-Session-Token": token}, json={"request_id": str(uuid4()),
            "activity_seq": 1, "presentation_cutoff": 0, "text": "synthetic dialogue"})
        assert response.status_code == 202
        request_id = response.headers["x-request-id"]
    assert sink.closed
    generation = [e for e in sink.events if e.stage == DiagnosticStage.GENERATION]
    assert generation and generation[0].context.request_id == request_id
    assert generation[0].context.session_id == session_id
    assert generation[0].context.turn_id
    assert any(e.stage == DiagnosticStage.HTTP and e.context.request_id == request_id for e in sink.events)
    assert "synthetic dialogue" not in repr(sink.events) and token not in repr(sink.events)


@pytest.mark.asyncio
async def test_media_stop_and_disconnect_have_separate_reasons():
    for reason in (CancellationReason.USER_STOP, CancellationReason.DISCONNECT):
        started = asyncio.Event()
        async def source():
            started.set()
            await asyncio.Event().wait()
            yield None
        sink = CollectDiagnostics()
        operation = MediaOperation(source, activity_seq=1, input_epoch=1, output_epoch=1,
                                   diagnostics=sink)
        await started.wait()
        operation.cancel(reason=reason)
        await operation.close()
        terminals = [e for e in sink.events if e.outcome == DiagnosticOutcome.CANCELLED]
        assert len(terminals) == 1 and terminals[0].cancellation_reason == reason
        assert not any(e.outcome == DiagnosticOutcome.FAILED for e in sink.events)


def test_broken_diagnostic_sink_cannot_break_http_business_path():
    class Broken(CollectDiagnostics):
        def emit(self, event):
            raise OSError("synthetic private disk detail")
        def close(self):
            raise OSError("synthetic private disk detail")
    app = create_app(Settings(), diagnostics=Broken())
    with TestClient(app) as client:
        response = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())})
        assert response.status_code == 201
        assert "synthetic private" not in response.text


def test_unknown_exception_and_domain_code_never_reach_http_output():
    from mira.domain.errors import DomainError

    app = create_app(Settings(), diagnostics=CollectDiagnostics())
    @app.get("/synthetic-error")
    async def synthetic_error():
        raise DomainError("synthetic_private_token", "synthetic-private-body")
    with TestClient(app) as client:
        response = client.get("/synthetic-error")
        assert "synthetic_private_token" not in response.text
        assert "synthetic-private-body" not in response.text


@pytest.mark.asyncio
async def test_output_review_cancellation_preserves_stop_and_timeout_cause():
    from mira.adapters.generation.mock import MockGenerationBackend
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.application.session_actor import RuntimeLimits, SessionActor
    from mira.domain.models import SessionState

    for user_stop in (True, False):
        entered = asyncio.Event()
        class HeldReview:
            async def review(self, context, candidate):
                entered.set()
                await asyncio.Event().wait()
        sink = CollectDiagnostics()
        actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), MockGenerationBackend(0),
            HeldReview(), MemoryEventJournal(20), RuntimeLimits(.05 if not user_stop else 2, 10, 30),
            diagnostics=sink)
        await actor.submit(request_id=str(uuid4()), activity_seq=1, cutoff=0, text="synthetic")
        await entered.wait()
        if user_stop:
            await actor.stop(activity_seq=2, cutoff=0)
        for task in tuple(actor._tasks):
            try:
                await task
            except asyncio.CancelledError:
                pass
        terminal = [e for e in sink.events if e.stage == DiagnosticStage.OUTPUT_REVIEW
                    and e.outcome != DiagnosticOutcome.STARTED]
        assert len(terminal) == 1
        if user_stop:
            assert terminal[0].cancellation_reason == CancellationReason.USER_STOP
        else:
            assert terminal[0].outcome == DiagnosticOutcome.FAILED and terminal[0].code == "timeout"
        await actor.close()


@pytest.mark.asyncio
async def test_provider_domain_error_code_never_enters_public_session_state():
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.adapters.review.mock import FixtureReviewBackend
    from mira.application.session_actor import RuntimeLimits, SessionActor
    from mira.domain.errors import DomainError
    from mira.domain.models import SessionState
    from mira.entrypoints.http.mappers import session_view

    class BrokenGeneration:
        async def generate(self, context):
            raise DomainError("sk-synthetic-upstream-private-token", "synthetic private body")
            yield None
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), BrokenGeneration(),
        FixtureReviewBackend(), MemoryEventJournal(20), RuntimeLimits(1, 10, 30))
    await actor.submit(request_id=str(uuid4()), activity_seq=1, cutoff=0, text="synthetic")
    await asyncio.gather(*tuple(actor._tasks))
    snapshot = session_view(await actor.snapshot()).model_dump_json()
    assert "synthetic-upstream-private-token" not in snapshot
    await actor.close()


def test_public_diagnostics_status_is_actual_runtime_state(tmp_path):
    from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics

    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    app = create_app(Settings(), diagnostics=sink)
    with TestClient(app) as client:
        before = client.get("/api/v1/diagnostics-status")
        assert before.status_code == 200 and not before.json()["recording_active"]
        sink.set_recording(True, consent=True)
        active = client.get("/api/v1/diagnostics-status").json()
        assert active["recording_active"] and "开发录制" in active["notice"]
        assert "root" not in active and "secret" not in active and "directory" not in active
        sink.set_recording(False)
        assert not client.get("/api/v1/diagnostics-status").json()["recording_active"]


def test_runtime_opt_in_records_dialogue_model_content_but_never_session_token(tmp_path):
    import json
    import time
    from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics

    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    sink.set_recording(True, consent=True)
    app = create_app(Settings(providers={"mock_delay_ms": 0}), diagnostics=sink)
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = f'/api/v1/sessions/{created["session"]["session_id"]}'
        token = created["session_token"]
        headers = {"X-Mira-Session-Token": token}
        response = client.post(path + "/inputs", headers=headers, json={"request_id": str(uuid4()),
            "activity_seq": 1, "presentation_cutoff": 0, "text": "synthetic dialogue " + token})
        assert response.status_code == 202
        for _ in range(100):
            if client.get(path, headers=headers).json()["sealed"]:
                break
            time.sleep(.005)
        sink.flush()
        records = [json.loads(line) for file in (tmp_path / "raw").glob("raw-*.jsonl")
                   for line in file.read_text().splitlines()]
        assert {"dialogue", "model_input", "model_output"} <= {r["kind"] for r in records}
        assert token not in json.dumps(records)


def test_loader_requires_explicit_raw_consent_and_private_bounded_settings():
    from pathlib import Path
    from mira.config.loader import ConfigurationError, load_settings

    root = Path(__file__).resolve().parents[2]
    assert not load_settings(root=root, environ={}).diagnostics.development_recording
    for env in [
        {"MIRA_DIAGNOSTICS__DEVELOPMENT_RECORDING": "true"},
        {"MIRA_DIAGNOSTICS__DIRECTORY": "../private"},
        {"MIRA_DIAGNOSTICS__RAW_MAX_FILES": "5"},
        {"MIRA_DIAGNOSTICS__RAW_RETENTION_SECONDS": "86401"},
        {"MIRA_DIAGNOSTICS__RETENTION_SECONDS": "nan"},
    ]:
        with pytest.raises(ConfigurationError):
            load_settings(root=root, environ=env)
    configured = load_settings(root=root, environ={"MIRA_DIAGNOSTICS__DEVELOPMENT_RECORDING": "true",
        "MIRA_DIAGNOSTICS__RECORDING_CONSENT": "true"})
    assert configured.diagnostics.development_recording
