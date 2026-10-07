"""M06 Actor recall: synthetic async readers only, no live account or DB."""

import asyncio
import json
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from mira.adapters.diagnostics.recorder import DiagnosticOptions, LocalDiagnostics
from mira.adapters.journal.memory import MemoryEventJournal
from mira.application.actor_memory import ActorMemoryBindingError, SessionMemoryBinding
from mira.application.contracts import (
    CandidateRange, ContextPacket, EffectProposal, GenerationContext,
    ReviewObservation, ReviewVerdict, generation_context_data,
)
from mira.application.decision_contracts import (
    ChoiceProbability, InputDecisionObservation, InputDecisionStatus,
    PredicateObservation, ReferentObservation, SemanticValue, decision_snapshot_data,
    evidence_digest, mira26_author_policy,
)
from mira.application.decision_runtime import DecisionSnapshotOwner, SemanticReviewCoordinator
from mira.application.memory_context import (
    ContextLine, RequiredMemoryContextOverflow, bounded_retrieval_query,
    build_context_packet, valid_context_packet,
)
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.memory import MemoryEntry, MemoryKind, MemoryScope, MemorySource
from mira.domain.models import EffectKind, Phase, SessionState


SCOPE = MemoryScope("synthetic-user", "synthetic-character", "synthetic-world")
STORED_TEXT = "SYNTHETIC_STORED_MEMORY_DO_NOT_CAPTURE_7719"
CANDIDATE = CandidateRange((EffectProposal(EffectKind.POSE, "face_calm"),), "synthetic-candidate")


def valid_past_line(text=STORED_TEXT, **changes):
    return replace(ContextLine(
        text=text,
        source=MemorySource.USER_STATEMENT.value,
        role="past_candidate",
        precedence="optional_past_memory",
        trust="untrusted_quoted_evidence",
        evidence_id="entry-1",
        source_event_id="event-1",
        source_version=1,
    ), **changes)


def packet(request_text="synthetic request", *, revision=7, timeout_ms=500,
           max_packet_bytes=32_768, past_candidates=None):
    return ContextPacket(
        request_text=request_text,
        caller_boundaries=(ContextLine(
            "synthetic current boundary", "current_request_input",
            "caller_declared_current_boundary", "required_current_input",
            "untrusted_current_user_input"),),
        caller_corrections=(),
        persistent_boundaries=(ContextLine(
            "synthetic persistent boundary", "user_statement",
            "current_user_statement_boundary", "required_current_boundary",
            "untrusted_quoted_evidence", "boundary-1", "boundary-event-1", 1),),
        persistent_corrections=(),
        past_candidates=tuple(past_candidates if past_candidates is not None else (valid_past_line(),)),
        snapshot_revision=revision,
        recall_status="completed",
        timeout_ms=timeout_ms,
        max_packet_bytes=max_packet_bytes,
    )


class AsyncReader:
    def __init__(self, *, blocked_text=None, suppress_cancel=False, packet_factory=None):
        self.scope = SCOPE
        self.revision = 7
        self.calls = []
        self.revision_calls = []
        self.closed = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.blocked_text = blocked_text
        self.suppress_cancel = suppress_cancel
        self.packet_factory = packet_factory or packet

    async def build_packet(self, *, scope, request_text, retrieval_query,
                           timeout_ms, max_packet_bytes):
        assert scope == self.scope
        self.calls.append({"scope": scope, "request_text": request_text,
                           "retrieval_query": retrieval_query, "timeout_ms": timeout_ms,
                           "max_packet_bytes": max_packet_bytes})
        if self.blocked_text == request_text:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                if not self.suppress_cancel:
                    raise
                await self.release.wait()
        return self.packet_factory(request_text, revision=self.revision,
                                   timeout_ms=timeout_ms, max_packet_bytes=max_packet_bytes)

    async def scope_revision(self, scope):
        assert scope == self.scope
        self.revision_calls.append(scope)
        return self.revision

    async def aclose(self):
        self.closed += 1
        self.release.set()


class CaptureGeneration:
    def __init__(self, on_generate=None):
        self.contexts = []
        self.on_generate = on_generate

    async def generate(self, context):
        self.contexts.append(context)
        if self.on_generate is not None:
            self.on_generate()
        yield CANDIDATE


class CaptureLegacyReview:
    def __init__(self):
        self.contexts = []

    async def review(self, context, candidate):
        self.contexts.append(context)
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")


class CaptureInputDecision:
    def __init__(self):
        self.snapshots = []

    async def observe(self, snapshot_value):
        self.snapshots.append(snapshot_value)
        return InputDecisionObservation(
            snapshot_value.snapshot_id, evidence_digest(snapshot_value),
            InputDecisionStatus.OBSERVED, "synthetic-input",
            tuple(PredicateObservation(key, SemanticValue.NO, 0.0) for key in (
                "speech_restriction", "capture_restriction", "display_request")),
            ReferentObservation("none", None, (
                ChoiceProbability("none", 1.0), ChoiceProbability("ambiguous", 0.0)), 1.0),
            calibration_ref="synthetic-input-only", model="synthetic-test",
        )


class CaptureOutputReview:
    def __init__(self, reader=None, *, change_revision=False):
        self.contracts = []
        self.reader = reader
        self.change_revision = change_revision

    async def review_contract(self, context, candidate, contract):
        self.contracts.append(contract)
        if self.change_revision and self.reader is not None:
            self.reader.revision += 1
        return ReviewObservation(ReviewVerdict.ALLOW, "synthetic")


class ForbiddenLegacyReview:
    async def review(self, *args):
        raise AssertionError("semantic review must not fall back to legacy review")


def create_actor(*, reader=None, memory_binding=None, generation=None, legacy_review=None,
                 input_decision=None, output_review=None, diagnostics=None, owned=False):
    if reader is not None and memory_binding is None:
        memory_binding = SessionMemoryBinding(
            reader, SCOPE, timeout_ms=800, max_packet_bytes=32_768,
            close_reader_on_actor_close=owned,
        )
    kwargs = {}
    if input_decision is not None or output_review is not None:
        assert input_decision is not None and output_review is not None
        kwargs["semantic_review"] = SemanticReviewCoordinator(input_decision, output_review)
        kwargs["decision_owner"] = DecisionSnapshotOwner(mira26_author_policy())
        legacy_review = ForbiddenLegacyReview()
    return SessionActor(
        SessionState("synthetic-session", "synthetic-character"),
        generation or CaptureGeneration(), legacy_review or CaptureLegacyReview(),
        MemoryEventJournal(64), RuntimeLimits(5.0, 16, 32),
        diagnostics=diagnostics, memory_binding=memory_binding, **kwargs,
    )


async def finish(actor_value):
    async with asyncio.timeout(4.0):
        await asyncio.gather(*tuple(actor_value._tasks), return_exceptions=True)
    return await actor_value.snapshot()


async def submit(actor_value, *, request="synthetic request", request_id="request-1", activity=1):
    return await actor_value.submit(request_id=request_id, activity_seq=activity,
                                    cutoff=0, text=request)


@pytest.mark.asyncio
async def test_default_actor_performs_no_memory_io_and_preserves_legacy_context():
    from dataclasses import asdict

    generation, review = CaptureGeneration(), CaptureLegacyReview()
    actor_value = create_actor(generation=generation, legacy_review=review)

    async def run():
        await submit(actor_value)
        await finish(actor_value)
        context = generation.contexts[0]
        expected = asdict(context)
        expected.pop("memory_packet", None)
        expected.pop("character_story", None)
        expected.pop("character_assets", None)
        expected.pop("request_context", None)
        expected.pop("visual_action_uncertain", None)
        expected.pop("photo_visible", None)
        expected.pop("photo_visibility_revision", None)
        expected.pop("memory_recall_status", None)
        expected.pop("conversation_recall", None)
        expected.pop("conversation_recall_status", None)
        expected.pop("story_image_scenes", None)
        expected.pop("story_images", None)
        expected.pop("story_image_completions", None)
        expected.pop("story_image_completion_only", None)
        expected.pop("fixed_photo", None)
        assert expected.pop("retired_user_inputs") == 0
        assert "local_history_retention" not in generation_context_data(context)
        assert context.memory_packet is None
        assert generation_context_data(context) == expected
        assert review.contexts[0].memory_packet is None
        await actor_value.close()

    await run()


@pytest.mark.asyncio
async def test_binding_preserves_full_request_and_bounds_separate_query():
    text = "opening " + ("雨" * 8_170) + " ending marker"
    assert len(text) == 8_192
    reader = AsyncReader()
    generation = CaptureGeneration()
    actor_value = create_actor(reader=reader, generation=generation)
    await submit(actor_value, request=text)
    await finish(actor_value)

    call = reader.calls[0]
    assert call["scope"] is SCOPE
    assert call["request_text"] == text
    assert generation.contexts[0].user_text == text
    assert generation.contexts[0].memory_packet.request_text == text
    assert len(call["retrieval_query"]) <= 256
    assert "ending marker" in call["retrieval_query"]
    assert call["retrieval_query"] != text
    assert len(reader.revision_calls) >= 1
    await actor_value.close()


@pytest.mark.asyncio
async def test_invalid_or_oversize_required_memory_fails_closed_without_dropping_boundaries():
    class Store:
        recalls = 0

        def scope_revision(self, scope):
            return 7

        def current_constraints(self, scope):
            return (MemoryEntry(
                id="boundary-1", scope=scope, kind=MemoryKind.BOUNDARY,
                source=MemorySource.USER_STATEMENT, text="mandatory boundary " + "x" * 1_100,
                source_event_id="boundary-event-1", source_version=1,
            ),)

        def recall(self, query):
            self.recalls += 1
            return ()

    store = Store()
    with pytest.raises(RequiredMemoryContextOverflow):
        build_context_packet(store, SCOPE, "current request", max_packet_bytes=1_024)
    assert store.recalls == 0
    query = bounded_retrieval_query("a" * 256 + " final current question")
    assert len(query) <= 256 and "final current question" in query


@pytest.mark.asyncio
async def test_binding_rejects_forged_source_authority_and_provenance_before_generation():
    cases = (
        {"source": "authored_backstory"},
        {"source": "current_request_input"},
        {"role": "current_user_statement_boundary"},
        {"precedence": "required_current_boundary"},
        {"trust": "untrusted_current_user_input"},
        {"evidence_id": None},
        {"source_event_id": None},
        {"source_version": 0},
        {"source_version": False},
        {"source_version": None},
    )
    for change in cases:
        reader = AsyncReader(packet_factory=lambda request, revision, timeout_ms,
                             max_packet_bytes, change=change: packet(
                                 request, revision=revision, timeout_ms=timeout_ms,
                                 max_packet_bytes=max_packet_bytes,
                                 past_candidates=(valid_past_line(**change),)))
        binding = SessionMemoryBinding(reader, SCOPE, timeout_ms=800, max_packet_bytes=32_768)
        with pytest.raises(ActorMemoryBindingError):
            await binding.build_packet("synthetic request")


@pytest.mark.asyncio
async def test_same_packet_reaches_generation_and_every_semantic_snapshot():
    reader = AsyncReader()
    generation, input_backend, output_backend = (
        CaptureGeneration(), CaptureInputDecision(), CaptureOutputReview())
    actor_value = create_actor(reader=reader, generation=generation,
                               input_decision=input_backend, output_review=output_backend)
    await submit(actor_value)
    state = await finish(actor_value)

    actual_packet = generation.contexts[0].memory_packet
    assert state.sealed and actual_packet is not None
    assert all(item.context.memory_packet is actual_packet for item in input_backend.snapshots)
    assert all(item.snapshot.context.memory_packet is actual_packet for item in output_backend.contracts)
    for item in (generation_context_data(generation.contexts[0]),
                 decision_snapshot_data(input_backend.snapshots[0])):
        assert "memory_packet" not in json.dumps(item)
        assert "memory_evidence" in item if "user_text" in item else "memory_evidence" in item["context"]
    assert STORED_TEXT in json.dumps(generation_context_data(generation.contexts[0]))
    assert SCOPE.user_id not in json.dumps(generation_context_data(generation.contexts[0]))
    first_snapshot = input_backend.snapshots[0]
    changed_packet = replace(actual_packet, past_candidates=(valid_past_line("other synthetic fact"),))
    changed_snapshot = replace(first_snapshot, context=replace(
        first_snapshot.context, memory_packet=changed_packet))
    assert evidence_digest(first_snapshot) != evidence_digest(changed_snapshot)
    assert STORED_TEXT not in json.dumps([asdict(item) for item in first_snapshot.reliable_inputs])
    assert first_snapshot.context.user_text == "synthetic request"
    await actor_value.close()


@pytest.mark.asyncio
async def test_late_read_after_stop_is_discarded_even_if_reader_suppresses_cancel():
    reader = AsyncReader(blocked_text="synthetic request", suppress_cancel=True)
    generation, review = CaptureGeneration(), CaptureLegacyReview()
    actor_value = create_actor(reader=reader, generation=generation, legacy_review=review)
    await submit(actor_value)
    await reader.entered.wait()
    stopped = await actor_value.stop(activity_seq=2, cutoff=0)
    reader.release.set()
    state = await finish(actor_value)

    assert state == stopped and state.phase == Phase.STOPPED
    assert state.user_inputs == ("synthetic request",) and not state.issued_effects
    assert generation.contexts == [] and review.contexts == []
    await actor_value.close()


@pytest.mark.asyncio
async def test_late_read_after_new_input_cannot_replace_newer_packet():
    reader = AsyncReader(blocked_text="older request", suppress_cancel=True)
    generation, review = CaptureGeneration(), CaptureLegacyReview()
    actor_value = create_actor(reader=reader, generation=generation, legacy_review=review)
    await submit(actor_value, request="older request", request_id="old", activity=1)
    await reader.entered.wait()
    await submit(actor_value, request="newer request", request_id="new", activity=2)
    reader.release.set()
    state = await finish(actor_value)

    assert state.request_id == "new" and state.sealed
    assert len(generation.contexts) == 1 and generation.contexts[0].user_text == "newer request"
    assert generation.contexts[0].memory_packet.request_text == "newer request"
    assert review.contexts[0].memory_packet is generation.contexts[0].memory_packet
    await actor_value.close()


@pytest.mark.asyncio
async def test_actor_closes_only_an_owned_reader():
    shared_reader = AsyncReader()
    shared_actor = create_actor(reader=shared_reader, owned=False)
    await shared_actor.close()
    assert shared_reader.closed == 0

    owned_reader = AsyncReader()
    owned_actor = create_actor(reader=owned_reader, owned=True)
    await owned_actor.close()
    assert owned_reader.closed == 1


@pytest.mark.asyncio
async def test_close_during_pending_read_discards_late_packet_and_closes_owned_reader():
    reader = AsyncReader(blocked_text="synthetic request", suppress_cancel=True)
    binding = SessionMemoryBinding(reader, SCOPE, timeout_ms=1_000,
                                   max_packet_bytes=32_768,
                                   close_reader_on_actor_close=True)
    generation = CaptureGeneration()
    actor_value = create_actor(memory_binding=binding, generation=generation)
    await submit(actor_value)
    await reader.entered.wait()
    await actor_value.close()
    state = await finish(actor_value)

    assert state.phase == Phase.THINKING and state.request_id == "request-1"
    assert not state.issued_effects and generation.contexts == []
    assert reader.closed == 1


@pytest.mark.asyncio
async def test_revision_change_during_generation_blocks_review_and_grant():
    reader = AsyncReader()
    generation = CaptureGeneration(on_generate=lambda: setattr(reader, "revision", 8))
    review = CaptureLegacyReview()
    actor_value = create_actor(reader=reader, generation=generation, legacy_review=review)
    await submit(actor_value)
    state = await finish(actor_value)

    assert state.phase == Phase.ERROR and state.last_error == "memory_context_stale"
    assert not state.issued_effects and review.contexts == []
    await actor_value.close()


@pytest.mark.asyncio
async def test_revision_change_during_output_review_blocks_new_grant():
    reader = AsyncReader()
    input_backend = CaptureInputDecision()
    output_backend = CaptureOutputReview(reader, change_revision=True)
    generation = CaptureGeneration()
    actor_value = create_actor(reader=reader, generation=generation,
                               input_decision=input_backend, output_review=output_backend)
    await submit(actor_value)
    state = await finish(actor_value)

    assert state.phase == Phase.ERROR and state.last_error == "memory_context_stale"
    assert not state.issued_effects and len(output_backend.contracts) == 1
    assert input_backend.snapshots[0].context.memory_packet is generation.contexts[0].memory_packet
    await actor_value.close()


@pytest.mark.asyncio
async def test_revision_change_during_input_review_blocks_output_review_and_grant():
    reader = AsyncReader()

    class MutatingInput(CaptureInputDecision):
        async def observe(self, snapshot_value):
            result = await super().observe(snapshot_value)
            reader.revision += 1
            return result

    input_backend = MutatingInput()
    output_backend = CaptureOutputReview()
    actor_value = create_actor(reader=reader, generation=CaptureGeneration(),
                               input_decision=input_backend, output_review=output_backend)
    await submit(actor_value)
    state = await finish(actor_value)

    assert state.phase == Phase.ERROR and state.last_error == "memory_context_stale"
    assert not state.issued_effects and output_backend.contracts == []
    await actor_value.close()


@pytest.mark.asyncio
async def test_generation_capture_excludes_stored_memory_text(tmp_path):
    sink = LocalDiagnostics(DiagnosticOptions(tmp_path), worker=False)
    assert sink.set_recording(True, consent=True)
    reader = AsyncReader(packet_factory=lambda request, revision, timeout_ms, max_packet_bytes:
                         packet(request, revision=revision, timeout_ms=timeout_ms,
                                max_packet_bytes=max_packet_bytes,
                                past_candidates=(valid_past_line(STORED_TEXT),)))
    generation = CaptureGeneration()
    actor_value = create_actor(reader=reader, generation=generation, diagnostics=sink)
    await submit(actor_value)
    await finish(actor_value)
    await actor_value.close()
    assert sink.flush()

    records = [json.loads(line) for file in (tmp_path / "raw").glob("raw-*.jsonl")
               for line in file.read_text().splitlines()]
    assert [record["kind"] for record in records] == ["dialogue"]
    assert STORED_TEXT not in json.dumps(records)
    sink.close()


@pytest.mark.asyncio
async def test_memory_reader_failure_uses_stable_nonrevealing_error():
    secret_error = "ValueError(" + STORED_TEXT + ")"

    class BrokenReader(AsyncReader):
        async def build_packet(self, **kwargs):
            raise ValueError(secret_error)

    reader = BrokenReader()
    actor_value = create_actor(reader=reader)
    await submit(actor_value)
    state = await finish(actor_value)

    assert state.phase == Phase.ERROR and state.last_error == "memory_unavailable"
    assert STORED_TEXT not in repr(state)
    assert SessionActor._memory_domain_error(ValueError(secret_error)).code == "memory_unavailable"
    await actor_value.close()


def test_memory_packet_and_context_objects_are_immutable_and_legacy_digest_is_unchanged():
    from dataclasses import asdict
    from hashlib import sha256

    current = GenerationContext("query", ("query",), (), 1)
    old_projection = asdict(current)
    old_projection.pop("memory_packet", None)
    old_projection.pop("character_story", None)
    old_projection.pop("character_assets", None)
    old_projection.pop("request_context", None)
    old_projection.pop("visual_action_uncertain", None)
    old_projection.pop("response_mode", None)
    old_projection.pop("photo_visible", None)
    old_projection.pop("photo_visibility_revision", None)
    old_projection.pop("memory_recall_status", None)
    old_projection.pop("conversation_recall", None)
    old_projection.pop("conversation_recall_status", None)
    old_projection.pop("story_image_scenes", None)
    old_projection.pop("story_images", None)
    old_projection.pop("story_image_completions", None)
    old_projection.pop("story_image_completion_only", None)
    old_projection.pop("fixed_photo", None)
    assert old_projection.pop("retired_user_inputs") == 0
    assert "local_history_retention" not in generation_context_data(current)
    assert generation_context_data(current) == old_projection
    assert evidence_digest(current) == sha256(json.dumps(
        old_projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()
    value = packet()
    assert valid_context_packet(value)
    with pytest.raises(FrozenInstanceError):
        value.snapshot_revision = 9


def test_retired_history_projection_is_explicit_without_fabricating_full_recall():
    context = GenerationContext("current", ("current",), (), 1, retired_user_inputs=17)
    data = generation_context_data(context)
    assert "retired_user_inputs" not in data
    assert data["local_history_retention"] == {
        "omitted_user_inputs": 17,
        "scope": "recent_retained_exact_facts_only",
        "rule": "Earlier local inputs and presentation details may have expired; never claim complete recall or invent omitted facts.",
    }
    assert data["user_inputs"] == ("current",)
