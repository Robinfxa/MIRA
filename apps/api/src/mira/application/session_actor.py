"""One state writer per session. Provider waits never hold the transition lock.

This is a small application coordinator, not a general actor/FSM framework.
All transitions are synchronous while the lock is held. The in-memory journal
is deliberately nonblocking; durable state/outbox is a separate WP05 migration.
"""
import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from mira.application.compiler import compile_range
from mira.application.decision_contracts import InputDecisionStatus, ReliableUserInput
from mira.application.decision_runtime import (
    DecisionSnapshotOwner, SemanticReviewCoordinator, snapshot_matches_state, snapshot_same_branch,
)
from mira.application.diagnostic_errors import classify_failure, classify_reason, public_error_code
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticEvent, DiagnosticKind, DiagnosticOutcome,
    DiagnosticSpan, DiagnosticStage, RecordingKind, capture_model_safely, capture_text_safely,
    diagnostic_context, emit_safely, failure_diagnostic_id,
)
from mira.application.ports.diagnostics import Diagnostics
from mira.application.media_runtime import MediaOperation, MicrophoneBuffer, speech_packets
from mira.application.ports.media import SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.application.contracts import (
    AuditEvent, CandidateRange, GenerationContext, ReviewVerdict, audio_context_progress,
)
from mira.application.ports.generation import GenerationBackend
from mira.application.ports.journal import EventJournal
from mira.application.ports.review import ReviewBackend
from mira.domain import transitions
from mira.domain.errors import DomainError
from mira.domain.models import AudioProgress, AudioStatus, EffectKind, Receipt, SessionState


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    timeout_seconds: float
    max_turns: int
    max_effects: int


class SessionActor:
    def __init__(self, state: SessionState, generation: GenerationBackend,
                 review: ReviewBackend, journal: EventJournal, limits: RuntimeLimits, *,
                 speech_synthesis: SpeechSynthesisBackend | None = None,
                 speech_recognition: SpeechRecognitionBackend | None = None,
                 diagnostics: Diagnostics | None = None,
                 semantic_review: SemanticReviewCoordinator | None = None,
                 decision_owner: DecisionSnapshotOwner | None = None) -> None:
        if (semantic_review is None) != (decision_owner is None):
            raise ValueError("semantic_composition_requires_owner_and_review")
        self._semantic_review = semantic_review
        self._decision_owner = decision_owner
        self._decision_inputs: tuple[ReliableUserInput, ...] = ()
        # One provider wait per session; cancelled pending turns never enter the call.
        self._semantic_lock = asyncio.Lock()
        self._state = state
        self._diagnostics = diagnostics
        self._diagnostic_spans: dict[asyncio.Task, DiagnosticSpan] = {}
        self._generation = generation
        self._review = review
        self._journal = journal
        self._limits = limits
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._request_fingerprints: dict[str, tuple[int, int, str, str]] = {}
        self._closed = False
        self._speech_synthesis = speech_synthesis
        self._speech_recognition = speech_recognition
        self._media_operations: set[MediaOperation] = set()
        self._speech_started: set[str] = set()
        self._microphone_started: set[str] = set()

    def _commit(self, state: SessionState, kind: str) -> None:
        if state is self._state:
            return
        self._state = state
        try:
            self._journal.append(AuditEvent(
                sequence=state.revision, session_id=state.session_id, kind=kind,
                state_revision=state.revision, output_epoch=state.output_epoch,
                occurred_at=datetime.now(UTC).isoformat(),
            ))
        except Exception:
            pass
        emit_safely(self._diagnostics, DiagnosticEvent(DiagnosticStage.SESSION,
            DiagnosticOutcome.SUCCEEDED, diagnostic_context(session_id=state.session_id,
                turn_id=str(state.output_epoch)), kind=DiagnosticKind.STATE_CHANGED))

    async def snapshot(self) -> SessionState:
        async with self._lock:
            return self._state

    def _cancel_tasks(self, reason: CancellationReason = CancellationReason.UNKNOWN) -> None:
        for task in tuple(self._tasks):
            if span := self._diagnostic_spans.get(task):
                span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED, reason=reason)
            task.cancel()
        self._cancel_media(reason)

    def _cancel_media(self, reason: CancellationReason = CancellationReason.UNKNOWN) -> None:
        for operation in tuple(self._media_operations):
            operation.cancel(reason)

    async def submit(self, *, request_id: str, activity_seq: int,
                     cutoff: int, text: str,
                     source: Literal["text", "asr_final"] = "text") -> SessionState:
        if source not in ("text", "asr_final"):
            raise DomainError("invalid_input", "Only reliable text or final ASR may start a turn.")
        async with self._lock:
            if self._closed:
                raise DomainError("session_closed", "Session has closed.")
            fingerprint = (activity_seq, cutoff, text, source)
            previous = self._request_fingerprints.get(request_id)
            if previous is not None:
                if previous != fingerprint:
                    raise DomainError("request_conflict", "Request ID was reused with different data.")
                return self._state
            try:
                state = transitions.begin_input(self._state, activity_seq=activity_seq,
                    cutoff=cutoff, request_id=request_id, text=text)
            except DomainError as error:
                if error.code == "history_pending":
                    # A rejected new turn still removes authority from a current old
                    # branch, but does not consume the caller's request/activity ID.
                    revoked = transitions.revoke_for_history_pending(self._state, cutoff=cutoff)
                    if revoked is not self._state:
                        self._cancel_tasks(CancellationReason.SUPERSEDED)
                        self._commit(revoked, "history_pending_revoked")
                raise
            if len(self._request_fingerprints) >= self._limits.max_turns:
                raise DomainError("session_capacity", "Foundation turn budget reached; create a new session.")
            # Cancellation-resistant providers are not allowed to create an unbounded task set.
            if len(self._tasks) >= 4:
                raise DomainError("busy", "Previous work is still terminating.")
            self._cancel_tasks(CancellationReason.SUPERSEDED)
            self._request_fingerprints[request_id] = fingerprint
            self._decision_inputs += (ReliableUserInput(request_id, text, source),)
            self._commit(state, "input_committed")
            capture_text_safely(self._diagnostics, RecordingKind.DIALOGUE, text,
                diagnostic_context(session_id=state.session_id, turn_id=str(state.output_epoch)))
            context = GenerationContext(text, state.user_inputs, state.presented_effects,
                                        state.output_epoch, audio_progress=audio_context_progress(state.audio_progress))
            task = asyncio.create_task(self._generate(context, activity_seq))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return state

    async def stop(self, *, activity_seq: int, cutoff: int) -> SessionState:
        async with self._lock:
            state = transitions.stop(self._state, activity_seq=activity_seq, cutoff=cutoff)
            if state is not self._state:
                self._cancel_tasks(CancellationReason.USER_STOP)
                self._commit(state, "stopped")
            return self._state

    async def receipt(self, receipt: Receipt) -> SessionState:
        async with self._lock:
            self._commit(transitions.record_receipt(self._state, receipt), "receipt_recorded")
            return self._state

    async def audio_progress(self, progress: AudioProgress) -> SessionState:
        async with self._lock:
            if self._closed:
                raise DomainError("session_closed", "Session has closed.")
            previous = self._state
            context = diagnostic_context(session_id=previous.session_id,
                turn_id=str(progress.output_epoch), effect_id=progress.effect_id)
            self._commit(transitions.record_audio_progress(previous, progress,
                diagnostic_id=failure_diagnostic_id(context)), "audio_progress_recorded")
            if (self._state is not previous and progress.output_epoch == previous.output_epoch
                    and previous.request_id is not None
                    and progress.status in {AudioStatus.INTERRUPTED, AudioStatus.FAILED}):
                interrupted = progress.status == AudioStatus.INTERRUPTED
                # The report proves interruption, not which local action caused it.
                # Dependent work stops because this transition revoked its permit.
                emit_safely(self._diagnostics, DiagnosticEvent(DiagnosticStage.PLAYBACK,
                    DiagnosticOutcome.CANCELLED if interrupted else DiagnosticOutcome.FAILED,
                    context, code=DiagnosticCode.CANCELLED if interrupted else DiagnosticCode.UNKNOWN,
                    cancellation_reason=CancellationReason.UNKNOWN if interrupted else None))
                self._cancel_tasks(CancellationReason.PERMIT_REVOKED)
            elif progress.status != AudioStatus.RENDERED:
                for operation in tuple(self._media_operations):
                    if operation.effect is not None and operation.effect.id == progress.effect_id:
                        operation.cancel(CancellationReason.PERMIT_REVOKED)
            return self._state

    def _media_capacity(self) -> None:
        if self._closed:
            raise DomainError("session_closed", "Session has closed.")
        if len(self._media_operations) >= 4:
            raise DomainError("busy", "Previous media work is still terminating.")

    def _track_media(self, operation: MediaOperation) -> MediaOperation:
        self._media_operations.add(operation)
        return operation

    def close_media(self, operation: MediaOperation,
                    reason: CancellationReason = CancellationReason.UNKNOWN) -> Coroutine:
        # Establish revocation and ownership before the caller can be cancelled
        # at its next await. Capacity includes an uncooperative socket child too.
        operation.cancel(reason)
        def reap(task) -> None:
            if not task.cancelled():
                task.exception()
            if all(owned.done() for owned in operation.tasks):
                self._media_operations.discard(operation)
        for task in operation.tasks:
            if task.done():
                reap(task)
            else:
                task.add_done_callback(reap)
        return operation.close(reason)

    async def open_speech(self, *, effect_id: str, digest: str, output_epoch: int,
                          activity_seq: int) -> MediaOperation:
        async with self._lock:
            self._media_capacity()
            effect = next((e for e in self._state.active_grants if e.id == effect_id), None)
            if effect is None or effect.kind != EffectKind.SPEECH:
                raise DomainError("speech_not_granted", "There is no current speech grant.")
            if (effect.digest, effect.output_epoch, effect.activity_seq) != (
                    digest, output_epoch, activity_seq):
                raise DomainError("receipt_mismatch", "Speech origin differs from the current grant.")
            if self._speech_synthesis is None:
                raise DomainError("speech_unavailable", "No speech synthesis provider is injected.")
            if effect.id in self._speech_started or any(
                    p.effect_id == effect.id and p.status != AudioStatus.RENDERED
                    for p in self._state.audio_progress):
                raise DomainError("speech_consumed", "This speech grant has already been consumed.")
            if any(op.effect is not None and not op.cancelled.is_set() for op in self._media_operations):
                raise DomainError("busy", "The session voice slot is already in use.")
            self._speech_started.add(effect.id)
            backend = self._speech_synthesis
            return self._track_media(MediaOperation(lambda: speech_packets(backend, effect),
                activity_seq=activity_seq, input_epoch=self._state.input_epoch,
                output_epoch=output_epoch, effect=effect, diagnostics=self._diagnostics,
                diagnostic_context=diagnostic_context(session_id=self._state.session_id,
                    turn_id=str(output_epoch), effect_id=effect.id)))

    async def open_microphone(self, *, stream_id: str, activity_seq: int,
                              input_epoch: int, buffer: MicrophoneBuffer) -> MediaOperation:
        async with self._lock:
            self._media_capacity()
            if (activity_seq, input_epoch) != (self._state.activity_seq, self._state.input_epoch):
                raise DomainError("stale_activity", "Microphone origin is no longer current.")
            if self._speech_recognition is None:
                raise DomainError("microphone_unavailable", "No speech recognition provider is injected.")
            if stream_id in self._microphone_started:
                raise DomainError("stream_consumed", "Microphone stream identity has already been used.")
            if len(self._microphone_started) >= self._limits.max_turns:
                raise DomainError("session_capacity", "Microphone stream budget reached.")
            if any(op.effect is None and not op.cancelled.is_set() for op in self._media_operations):
                raise DomainError("busy", "A microphone stream is already open.")
            self._microphone_started.add(stream_id)
            backend = self._speech_recognition
            return self._track_media(MediaOperation(lambda: backend.transcribe(buffer.packets()),
                activity_seq=activity_seq, input_epoch=input_epoch,
                output_epoch=self._state.output_epoch, diagnostics=self._diagnostics,
                discard_input=buffer.clear,
                diagnostic_context=diagnostic_context(session_id=self._state.session_id,
                    turn_id=str(self._state.output_epoch), effect_id=stream_id)))

    async def validate_media(self, operation: MediaOperation) -> None:
        async with self._lock:
            state = self._state
            if (self._closed or operation.cancelled.is_set()
                    or (operation.activity_seq, operation.input_epoch, operation.output_epoch)
                    != (state.activity_seq, state.input_epoch, state.output_epoch)
                    or (operation.effect is not None and (
                        operation.effect not in state.active_grants or any(
                            p.effect_id == operation.effect.id and p.status != AudioStatus.RENDERED
                            for p in state.audio_progress)))):
                operation.cancel(CancellationReason.PERMIT_REVOKED)
                raise DomainError("media_cancelled", "Media authority has been revoked.")

    async def media_failed(self, operation: MediaOperation, code: str) -> None:
        async with self._lock:
            if operation.effect is not None and operation.output_epoch == self._state.output_epoch:
                self._commit(transitions.fail(self._state, output_epoch=operation.output_epoch,
                                              code=public_error_code(code),
                                              diagnostic_id=operation.diagnostic_id), "media_failed")
                self._cancel_media(CancellationReason.PERMIT_REVOKED)

    async def _semantic_candidate(self, context: GenerationContext, activity_seq: int,
                                  candidate: CandidateRange, generation_span: DiagnosticSpan, *,
                                  scope: Literal["stage", "seal"] = "stage") -> bool:
        """Review and apply one pending range, or seal, with both post-await lock checks.

        Receipt/audio changes refresh the pending candidate instead of dropping the
        turn. Supersede/Stop invalidates the branch immediately, including a provider
        that suppresses cancellation. The enclosing generation timeout bounds retries.
        """
        assert self._semantic_review is not None and self._decision_owner is not None
        async with self._semantic_lock:
            while True:
                async with self._lock:
                    if (self._closed or self._state.request_id is None
                            or (self._state.output_epoch, self._state.activity_seq)
                            != (context.output_epoch, activity_seq)):
                        return False
                    snapshot = self._decision_owner.snapshot(self._state, self._decision_inputs)
                    if snapshot is None:
                        raise DomainError("review_not_allowed", "Reliable decision facts are incomplete.")
                input_span = DiagnosticSpan(self._diagnostics, DiagnosticStage.INPUT_REVIEW,
                                            generation_span.context)
                try:
                    input_observation = await self._semantic_review.observe(snapshot)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                except asyncio.CancelledError:
                    input_span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED,
                        reason=generation_span.cancellation_reason or CancellationReason.UNKNOWN)
                    raise
                except Exception as error:
                    input_span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code)
                    raise
                input_span.finish(DiagnosticOutcome.SUCCEEDED if (
                    input_observation.status == InputDecisionStatus.OBSERVED) else DiagnosticOutcome.FAILED,
                    code=None if input_observation.status == InputDecisionStatus.OBSERVED else (
                        classify_reason(input_observation.reason_code).code))
                async with self._lock:
                    if self._closed or not snapshot_same_branch(self._state, snapshot):
                        return False
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    if not snapshot_matches_state(self._state, snapshot):
                        continue
                review_span = DiagnosticSpan(self._diagnostics, DiagnosticStage.OUTPUT_REVIEW,
                                             generation_span.context)
                try:
                    observation = await self._semantic_review.review(
                        snapshot, candidate, input_observation, scope=scope)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                except asyncio.CancelledError:
                    review_span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED,
                        reason=generation_span.cancellation_reason or CancellationReason.UNKNOWN)
                    raise
                except Exception as error:
                    review_span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code)
                    raise
                review_span.finish(DiagnosticOutcome.SUCCEEDED if (
                    observation.verdict == ReviewVerdict.ALLOW) else DiagnosticOutcome.FAILED,
                    code=None if observation.verdict == ReviewVerdict.ALLOW else (
                        DiagnosticCode.BLOCKED if observation.verdict == ReviewVerdict.REJECT
                        else classify_reason(observation.reason_code).code))
                async with self._lock:
                    if self._closed or not snapshot_same_branch(self._state, snapshot):
                        return False
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    if not snapshot_matches_state(self._state, snapshot):
                        continue
                    if observation.verdict != ReviewVerdict.ALLOW:
                        raise DomainError("review_not_allowed", "Candidate did not pass review.")
                    if scope == "seal":
                        self._commit(transitions.seal(self._state, output_epoch=context.output_epoch),
                                     "plan_sealed")
                    else:
                        effects = compile_range(candidate, epoch=context.output_epoch,
                                                activity=activity_seq)
                        if len(self._state.issued_effects) + len(effects) > self._limits.max_effects:
                            raise DomainError("effect_capacity", "Foundation effect budget reached.")
                        self._commit(transitions.accept_range(self._state,
                            output_epoch=context.output_epoch, effects=effects), "range_accepted")
                    return True

    async def _generate(self, context: GenerationContext, activity_seq: int) -> None:
        span = DiagnosticSpan(self._diagnostics, DiagnosticStage.GENERATION,
            diagnostic_context(session_id=self._state.session_id, turn_id=str(context.output_epoch)))
        task = asyncio.current_task()
        self._diagnostic_spans[task] = span
        review_span = None
        capture_model_safely(self._diagnostics, RecordingKind.MODEL_INPUT, context, span.context)
        try:
            async with asyncio.timeout(self._limits.timeout_seconds):
                count = 0
                async for candidate in self._generation.generate(context):
                    # Captured before semantic review, so rejected candidates can be reproduced.
                    capture_model_safely(self._diagnostics, RecordingKind.MODEL_OUTPUT, candidate, span.context)
                    if self._semantic_review is not None:
                        if not await self._semantic_candidate(context, activity_seq, candidate, span):
                            return
                        count += 1
                        last_candidate = candidate
                        continue
                    async with self._lock:
                        if self._closed or self._state.output_epoch != context.output_epoch:
                            return
                        review_context = replace(context, accepted_prefix=self._state.active_grants,
                                                 presented_effects=self._state.presented_effects,
                                                 audio_progress=audio_context_progress(self._state.audio_progress))
                    review_span = DiagnosticSpan(self._diagnostics, DiagnosticStage.OUTPUT_REVIEW,
                        span.context)
                    try:
                        observation = await self._review.review(review_context, candidate)
                    except asyncio.CancelledError:
                        # Outer timeout/explicit-cancel boundary knows the actual cause.
                        raise
                    except Exception as review_error:
                        review_span.finish(DiagnosticOutcome.FAILED,
                                           code=classify_failure(review_error).code)
                        raise
                    else:
                        review_span.finish(DiagnosticOutcome.SUCCEEDED if (
                            observation.verdict == ReviewVerdict.ALLOW) else DiagnosticOutcome.FAILED,
                            code=None if observation.verdict == ReviewVerdict.ALLOW else (
                                DiagnosticCode.BLOCKED if observation.verdict == ReviewVerdict.REJECT
                                else classify_reason(observation.reason_code).code))
                    if observation.verdict != ReviewVerdict.ALLOW:
                        raise DomainError("review_not_allowed", "Candidate did not pass review.")
                    effects = compile_range(candidate, epoch=context.output_epoch, activity=activity_seq)
                    async with self._lock:
                        if self._closed or self._state.output_epoch != context.output_epoch:
                            return
                        if len(self._state.issued_effects) + len(effects) > self._limits.max_effects:
                            raise DomainError("effect_capacity", "Foundation effect budget reached.")
                        self._commit(transitions.accept_range(
                            self._state, output_epoch=context.output_epoch, effects=effects
                        ), "range_accepted")
                        count += 1
                if not count:
                    raise DomainError("empty_generation", "Provider returned no complete range.")
                if self._semantic_review is not None:
                    if not await self._semantic_candidate(context, activity_seq, last_candidate,
                                                          span, scope="seal"):
                        return
                else:
                    async with self._lock:
                        self._commit(transitions.seal(self._state, output_epoch=context.output_epoch),
                                     "plan_sealed")
            span.finish(DiagnosticOutcome.SUCCEEDED)
        except asyncio.CancelledError:
            # Local stop owns invalidation. Cancellation is not natural PlanEnd.
            reason = span.cancellation_reason or CancellationReason.UNKNOWN
            if review_span is not None:
                review_span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED, reason=reason)
            span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED, reason=reason)
            raise
        except Exception as error:
            if review_span is not None:
                review_span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code)
            span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code)
            code = public_error_code(error.code) if isinstance(error, DomainError) else (
                "generation_timeout" if isinstance(error, TimeoutError) else "generation_failed"
            )
            async with self._lock:
                failed = transitions.fail(self._state, output_epoch=context.output_epoch, code=code,
                                          diagnostic_id=failure_diagnostic_id(span.context))
                if failed is not self._state:
                    self._commit(failed, "generation_failed")
                    self._cancel_media(CancellationReason.PERMIT_REVOKED)
        finally:
            self._diagnostic_spans.pop(task, None)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            self._cancel_tasks(CancellationReason.SESSION_CLOSED)
            tasks = tuple(self._tasks)
            media = tuple(self._media_operations)
            # Synchronous close_media registers reaping even if shutdown's next
            # await is cancelled while generation is still terminating.
            media_cleanup = asyncio.gather(*(self.close_media(operation,
                CancellationReason.SESSION_CLOSED) for operation in media)) if media else None
        try:
            if tasks:
                await asyncio.wait(tasks, timeout=1.0)
        finally:
            if media_cleanup is not None:
                await media_cleanup
