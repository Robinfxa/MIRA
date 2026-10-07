"""Session-level microphone leases with bounded resources, independent of reply turns.

A lease owns one finite PCM queue and at most one recognition stream at a time. It is never registered
as an ordinary SessionActor MediaOperation, since those are intentionally bound to
turn activity/input/output epochs. User Stop, lease replacement, disconnect and
session teardown revoke it explicitly through the registry.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Literal
from uuid import UUID, uuid5

from mira.application.ports.continuous_speech import (
    ContinuousRecognitionEvent, ContinuousSpeechActivity, ContinuousSpeechRecognitionBackend,
    ContinuousTranscriptResult,
    ContinuousRecognitionStarted,
)
from mira.application.ports.request_budget import RequestBudget
from mira.application.ports.media import AudioPacket
from mira.application.ports.diagnostics import Diagnostics
from mira.application.diagnostic_errors import classify_failure
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticOutcome, DiagnosticSpan, DiagnosticStage,
    diagnostic_context, failure_diagnostic_id,
)
from mira.application.media_runtime import media_error
from mira.domain.errors import DomainError

SAMPLE_RATE_HZ = 16_000
MAX_CHUNK_BYTES = 12_000
MAX_TEXT_CHARS = 2_000
MAX_REVISION_COUNT = 10_000
# 20ms browser frames need more than eight slots during ordinary RPC startup.
# Bound queued PCM to two seconds (64,000 bytes), independently of packet count.
QUEUE_CAPACITY = 200
MAX_QUEUED_SAMPLES = SAMPLE_RATE_HZ * 2
OUTPUT_CAPACITY = 32
# Provider event offsets are not guaranteed to be byte-for-byte identical. Bound the
# acceptable delay between the last final result and VAD END instead of requiring equality.
MAX_FINAL_TO_END_SECONDS = 3.0
_CANCELLATION_REASONS = {
    "user_stop": CancellationReason.USER_STOP,
    "disconnect": CancellationReason.DISCONNECT,
    "replaced": CancellationReason.SUPERSEDED,
    "session_closed": CancellationReason.SESSION_CLOSED,
    "permission_lost": CancellationReason.PERMIT_REVOKED,
}
_DECLARED_LIMIT_REASONS = frozenset({"max_duration", "max_samples", "utterance_limit", "service_budget_exhausted"})


@dataclass(frozen=True, slots=True)
class ListeningLimits:
    # ``max_seconds == max_samples == 0`` is an explicit disabled state. It is used
    # when an admitted STT policy allows a positive sub-second call (for ordinary
    # PTT) but cannot safely authorize the minimum one-second continuous lease.
    max_seconds: int | None = None
    max_samples: int | None = None
    max_utterances: int | None = None
    max_streams_per_session: int | None = None
    max_total_streams: int | None = None
    queue_capacity: int = QUEUE_CAPACITY
    output_capacity: int = OUTPUT_CAPACITY
    max_final_to_end_seconds: float = MAX_FINAL_TO_END_SECONDS
    natural_grace_seconds: float = 0.65
    client_silence_ms: int = 700
    drain_timeout_seconds: float = 2.0
    max_recognition_streams: int | None = None

    def __post_init__(self) -> None:
        unlimited = self.max_seconds is None and self.max_samples is None
        disabled = self.max_seconds == 0 and self.max_samples == 0
        enabled = (type(self.max_seconds) is int and 1 <= self.max_seconds <= 290
                   and type(self.max_samples) is int and
                   1 <= self.max_samples <= SAMPLE_RATE_HZ * self.max_seconds)
        def bounded(value, upper):
            return value is None or (type(value) is int and 1 <= value <= upper)
        if (not (unlimited or disabled or enabled)
                or not bounded(self.max_utterances, 32)
                or not bounded(self.max_streams_per_session, 16)
                or not bounded(self.max_total_streams, 100)
                or type(self.queue_capacity) is not int or not 1 <= self.queue_capacity <= QUEUE_CAPACITY
                or type(self.output_capacity) is not int or not 1 <= self.output_capacity <= 128
                or type(self.max_final_to_end_seconds) not in (int, float)
                or not 0.1 <= self.max_final_to_end_seconds <= 10
                or type(self.natural_grace_seconds) not in (int, float)
                or not 0.25 <= self.natural_grace_seconds <= 2.0
                or type(self.client_silence_ms) is not int or not 250 <= self.client_silence_ms <= 2_000
                or type(self.drain_timeout_seconds) not in (int, float)
                or not 0.1 <= self.drain_timeout_seconds <= 5.0
                or not bounded(self.max_recognition_streams, 32)):
            raise ValueError("continuous_listening_limits_invalid")


@dataclass(frozen=True, slots=True)
class ListeningEvent:
    type: Literal["transcript", "stopped", "endpoint_pending", "utterance_ready", "utterance_revision", "recognition_status", "endpoint_status"]
    lease_id: str
    revision: int | None = None
    text: str | None = None
    is_final: bool | None = None
    endpoint: str | None = None
    reason: str | None = None
    diagnostic_id: str | None = None
    utterance_id: str | None = None
    commit_id: str | None = None
    begin_offset_samples: int | None = None
    end_offset_samples: int | None = None
    final_offset_samples: int | None = None
    submission_state: str | None = None
    endpoint_basis: str | None = None
    source_end_sample: int | None = None
    endpoint_id: str | None = None
    endpoint_state: str | None = None
    client_endpoint_id: str | None = None
    stream_index: int | None = None
    recognition_state: str | None = None
    stt_requests_used: int | None = None
    stt_requests_remaining: int | None = None


@dataclass(frozen=True, slots=True)
class _FinalResult:
    text: str
    offset: int | None
    revision: int
    activity_index: int
    start_offset: int | None = None
    source_end_sample: int = 0
    heuristic_activity: bool = False


@dataclass(slots=True)
class _SettledUtterance:
    utterance_id: str
    commit_id: str
    text: str
    final_offset: int | None
    endpoint_basis: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingEnd:
    offset: int
    activity_index: int
    begin_offset: int


@dataclass(slots=True)
class _ActivityInterval:
    index: int
    begin_offset: int
    end_offset: int | None = None
    source_end_sample: int = 0


@dataclass(slots=True)
class _UtteranceBinding:
    lease_id: str
    text: str
    segment_seq: int
    status: Literal["pending", "reserved", "accepted", "revoked"] = "pending"
    request_id: str | None = None
    delivered: bool = False


@dataclass(frozen=True, slots=True)
class ListeningCommitResult:
    lease_id: str
    commit_id: str
    segment_seq: int
    revision: int
    text: str
    utterance_id: str | None = None


@dataclass(frozen=True, slots=True)
class ListeningHoldResult:
    lease_id: str
    utterance_id: str
    revision: int
    text: str
    activity_index: int


@dataclass(slots=True)
class _ClientEndpoint:
    endpoint_id: str
    source_end_sample: int
    state: str = "queued"
    queued_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class _RecognitionSegment:
    index: int
    stop_requests: asyncio.Event = field(default_factory=asyncio.Event)
    base_sample: int | None = None
    last_sample: int | None = None
    first_activity_index: int = 0
    draining: bool = False
    client_endpoint: _ClientEndpoint | None = None
    endpoint_changed: asyncio.Event = field(default_factory=asyncio.Event)
    progress: asyncio.Event = field(default_factory=asyncio.Event)
    first_revision: int = 0
    max_samples: int | None = None
    duration_rollover: bool = False
    on_duration: Callable[[], Awaitable[None]] | None = None


class ListeningAudioBuffer:
    """Finite, paced PCM16 stream with separate pending-sample and packet bounds."""
    def __init__(self, lease_id: str, *, limits: ListeningLimits):
        self.lease_id = lease_id
        self._queue: asyncio.Queue[AudioPacket | None] = asyncio.Queue(maxsize=limits.queue_capacity)
        self._limits = limits
        self._queued_samples = 0
        self._queued_packets = 0
        self._carry: AudioPacket | None = None
        self._samples = 0
        self._sequence = 0
        self._started = time.monotonic()
        self._finished = False
        self._closed = False

    @property
    def samples(self) -> int:
        return self._samples

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started

    @property
    def remaining_seconds(self) -> float | None:
        return (None if self._limits.max_seconds is None else
                max(0.0, self._limits.max_seconds - self.elapsed_seconds))

    def push(self, *, lease_id: str, sequence: int, first_sample: int, pcm: bytes) -> None:
        if self._closed or self._finished:
            raise DomainError("media_cancelled", "Listening lease is no longer active.")
        if lease_id != self.lease_id:
            raise DomainError("stale_stream", "Audio belongs to another listening lease.")
        if type(sequence) is not int or sequence != self._sequence + 1:
            raise DomainError("invalid_input", "Audio chunks must be sequential.")
        if type(first_sample) is not int or first_sample != self._samples:
            raise DomainError("invalid_input", "Audio samples must be contiguous.")
        if (not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > MAX_CHUNK_BYTES
                or (first_sample == 0 and pcm[:4] == b"RIFF" and pcm[8:12] == b"WAVE")):
            raise DomainError("invalid_audio", "Expected bounded headerless PCM16 audio.")
        samples = len(pcm) // 2
        elapsed = self.elapsed_seconds
        if ((self._limits.max_samples is not None and self._samples + samples > self._limits.max_samples)
                or (self._limits.max_seconds is not None and
                    self._samples + samples > SAMPLE_RATE_HZ * self._limits.max_seconds)):
            raise DomainError("input_limit", "Listening lease reached its sample budget.")
        if self._samples + samples > SAMPLE_RATE_HZ * (elapsed + 1.0):
            raise DomainError("input_limit", "Audio exceeds the listening pace limit.")
        if self._queued_samples + samples > MAX_QUEUED_SAMPLES:
            raise DomainError("input_limit", "Listening audio queue is full.")
        if self._queued_packets >= self._limits.queue_capacity:
            raise DomainError("input_limit", "Listening audio queue is full.")
        try:
            self._queue.put_nowait(AudioPacket(self.lease_id, self._samples, SAMPLE_RATE_HZ, pcm))
        except asyncio.QueueFull:
            raise DomainError("input_limit", "Listening audio queue is full.") from None
        self._queued_samples += samples
        self._queued_packets += 1
        self._samples += samples
        self._sequence = sequence

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if not self._queue.full():
            self._queue.put_nowait(None)

    def clear(self) -> None:
        self._closed = True
        self._finished = True
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queued_samples = 0
        self._queued_packets = 0
        self._carry = None

    async def packets(self):
        while True:
            if self._closed:
                return
            if self._finished and self._queue.empty():
                return
            packet = await self._queue.get()
            if packet is None:
                return
            self._queued_samples -= len(packet.pcm) // 2
            self._queued_packets -= 1
            yield packet

    async def _fetch_segment_packet(self, segment: _RecognitionSegment) -> bool:
        if self._finished and self._queue.empty():
            return False
        get = asyncio.create_task(self._queue.get())
        stop = asyncio.create_task(segment.stop_requests.wait())
        retained = False
        try:
            await asyncio.wait((get, stop), return_when=asyncio.FIRST_COMPLETED)
            if get.done() and not get.cancelled():
                packet = get.result()
                retained = True
                if packet is not None and not self._closed:
                    self._carry = packet
                return packet is not None
            return False
        finally:
            for task in (get, stop):
                if not task.done():
                    task.cancel()
            await asyncio.gather(get, stop, return_exceptions=True)
            # Cancellation/half-close can win after Queue.get removed a packet.
            # Keep that exact item for the next segment; counts include it until yield.
            if not retained and get.done() and not get.cancelled():
                packet = get.result()
                if packet is not None and not self._closed:
                    self._carry = packet

    async def segment_packets(self, segment: _RecognitionSegment):
        """Request half-close leaves later PCM in the same bounded global buffer."""
        while not self._closed and not segment.stop_requests.is_set():
            endpoint = segment.client_endpoint
            if (endpoint is not None and endpoint.state == "queued"
                    and (segment.last_sample or 0) >= endpoint.source_end_sample):
                # Never send PCM beyond the exact acknowledged client frontier.
                await segment.endpoint_changed.wait()
                segment.endpoint_changed.clear()
                continue
            if self._carry is None and not await self._fetch_segment_packet(segment):
                return
            if self._closed or segment.stop_requests.is_set():
                return
            packet, self._carry = self._carry, None
            if packet is None:
                return
            samples = len(packet.pcm) // 2
            consumed = 0 if segment.base_sample is None else packet.first_sample - segment.base_sample
            available = samples if segment.max_samples is None else segment.max_samples - consumed
            if available < samples:
                self._carry = AudioPacket(packet.stream_id, packet.first_sample + available,
                    packet.sample_rate_hz, packet.pcm[available * 2:])
                packet = replace(packet, pcm=packet.pcm[:available * 2])
                samples = available
            else:
                self._queued_packets -= 1
            self._queued_samples -= samples
            if segment.base_sample is None:
                segment.base_sample = packet.first_sample
            segment.last_sample = packet.first_sample + samples
            segment.progress.set()
            if samples:
                yield AudioPacket(packet.stream_id, packet.first_sample - segment.base_sample,
                                  packet.sample_rate_hz, packet.pcm)
            if segment.max_samples is not None and segment.last_sample - segment.base_sample >= segment.max_samples:
                segment.duration_rollover = True
                if segment.on_duration is not None:
                    await segment.on_duration()
                else:
                    segment.draining = True
                    segment.stop_requests.set()
                return


class ListeningLease:
    """One local lease; finite provider streams and explicit transcript commits."""
    def __init__(self, session_id: str, lease_id: str, *, limits: ListeningLimits,
                 diagnostics: Diagnostics | None = None,
                 natural_mode: bool = False, client_endpointing: bool = False, registry: "ContinuousListeningRegistry | None" = None):
        self.session_id, self.lease_id, self.limits = session_id, lease_id, limits
        self._diagnostics_sink = diagnostics
        self._diagnostic_context = diagnostic_context(session_id=session_id)
        self._diagnostic_span: DiagnosticSpan | None = None
        self.audio = ListeningAudioBuffer(lease_id, limits=limits)
        self.active = True
        self.reason: str | None = None
        self.started_at = time.monotonic()
        self.events: asyncio.Queue[ListeningEvent] = asyncio.Queue(maxsize=limits.output_capacity)
        self._revision = 0
        self._revision_window_start = 0
        self._activity_index = 0
        self._in_activity = False
        self._intervals: deque[_ActivityInterval] = deque(maxlen=16)
        self._ends: deque[_PendingEnd] = deque(maxlen=16)
        self._finals: deque[_FinalResult] = deque(maxlen=32)
        self._seen_offsets: set[tuple[int, int, str]] = set()
        self._recognized_chars = 0
        self._commit_count = 0
        self._commit_results: dict[str, ListeningCommitResult] = {}
        self._state_lock = asyncio.Lock()
        self._recognition_task: asyncio.Task | None = None
        self._terminal_sent = False
        self._stable_transcript = ""
        self._interim_transcript = ""
        self._latest_preview = ""
        self._last_preview_event: ListeningEvent | None = None
        self._terminal_preview: ListeningEvent | None = None
        self._late_revision_events: dict[str, ListeningEvent] = {}
        self._terminal_corrections: tuple[ListeningEvent, ...] = ()
        self._endpoint_hint_by_activity: dict[int, str] = {}
        self.natural_mode = natural_mode
        self.client_endpointing = client_endpointing
        self._registry = registry
        self._latest_final_offset: int | None = 0
        self._offsets_ordered = True
        self._provider_batch_complete = True
        self._has_pending_interim = False
        self._last_committed_revision = 0
        self._consumed_final_revisions: set[int] = set()
        self._natural_notice: tuple[str, int] | None = None
        self._settled_activities: dict[int, _SettledUtterance] = {}
        self._manual_activities: set[int] = set()
        self._grace_anchor = time.monotonic()
        self._grace_task: asyncio.Task | None = None
        self._segment: _RecognitionSegment | None = None
        self._segment_sealed = False
        self._resume_after_commit = asyncio.Event()
        self._drain_task: asyncio.Task | None = None
        self._request_budget: RequestBudget | None = None
        self._stream_conflicting_offsets = False
        self._announced_activities: set[int] = set()
        self._last_assignment_heuristic = False
        self._held_activities: set[int] = set()
        self._hold_results: dict[str, ListeningHoldResult] = {}
        self._client_endpoints: dict[str, _ClientEndpoint] = {}
        self._client_endpoint_task: asyncio.Task | None = None
        self._client_endpoint_activity: int | None = None
        self.recognition_stream_seconds: float = 120.0

    @property
    def diagnostic_id(self) -> str | None:
        return (failure_diagnostic_id(self._diagnostic_context)
                if self._diagnostic_span is not None else None)

    @property
    def active_duration_seconds(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def stable_text(self) -> str:
        return self._stable_transcript.strip()

    @property
    def terminal_preview(self) -> ListeningEvent | None:
        """Last observed preview retained at provider completion, never a new result."""
        return self._terminal_preview

    @property
    def terminal_previews(self) -> tuple[ListeningEvent, ...]:
        values = self._terminal_corrections
        if self._terminal_preview is not None:
            values += (self._terminal_preview,)
        return tuple(sorted(values, key=lambda event: event.revision))

    def constrain_audio_limits(self, *, max_seconds: int, max_samples: int) -> None:
        if self.audio.samples or self._recognition_task is not None:
            raise DomainError("invalid_input", "Listening limits must be fixed before recognition.")
        self.limits = replace(self.limits,
            max_seconds=max_seconds if self.limits.max_seconds is None else min(self.limits.max_seconds, max_seconds),
            max_samples=max_samples if self.limits.max_samples is None else min(self.limits.max_samples, max_samples))
        self.audio._limits = self.limits

    async def emit(self, event: ListeningEvent) -> bool:
        if not self.active and event.type != "stopped":
            return False
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            self.stop("output_limit")
            await self._emit_stopped("output_limit")
            return False
        return True

    async def recognize(self, backend: ContinuousSpeechRecognitionBackend,
                        *, is_current,
                        register_utterance: Callable[["ListeningLease", str, str, int], Awaitable[None]],
                        request_budget: RequestBudget | None = None) -> None:
        """Consume one provider stream. It never creates an Actor input or generation turn."""
        stream = None
        error = None
        cancelled = False
        cleanup_failed = False
        span = None
        try:
            if not self.active or not is_current(self):
                return
            span = DiagnosticSpan(self._diagnostics_sink, DiagnosticStage.STT,
                                  self._diagnostic_context)
            self._diagnostic_span = span
            self._request_budget = request_budget
            stream = self._segmented_events(backend) if (self.natural_mode or self.limits.max_seconds is None) else backend.transcribe_events(self.audio.packets())
            while self.active and is_current(self):
                try:
                    event = await anext(stream)
                except StopAsyncIteration:
                    break
                if not self.active or not is_current(self):
                    return
                if isinstance(event, ContinuousTranscriptResult):
                    await self._on_transcript(event)
                    span.observe(DiagnosticStage.STT_FIRST_REVISION)
                    if event.is_final:
                        span.observe(DiagnosticStage.STT_FIRST_FINAL_REVISION)
                elif isinstance(event, ContinuousSpeechActivity):
                    await self._on_activity(event)
                elif isinstance(event, ContinuousRecognitionStarted):
                    # Compatibility manual mode does not add new public wire events.
                    pass
                else:
                    raise DomainError("invalid_response", "Invalid continuous recognition event.")
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as failure:
            try:
                error = media_error(failure)  # Existing fixed safe codes only; never exception text.
            except Exception:
                error = DomainError("unavailable", "Recognition did not complete.")
            reason = ('service_budget_exhausted' if self.limits.max_seconds is None
                and error.code == 'input_limit' and request_budget is not None
                and request_budget.snapshot().remaining == 0 else error.code)
            self.stop(reason, retain_preview=True)
            await self._emit_stopped(reason)
        else:
            if self.active and is_current(self):
                self.stop("provider_stream_ended", retain_preview=True)
                await self._emit_stopped("provider_stream_ended")
        finally:
            if stream is not None:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    try:
                        await close()
                    except Exception:
                        cleanup_failed = True
            if span is not None:
                reason = _CANCELLATION_REASONS.get(self.reason)
                if reason is not None:
                    outcome, code = DiagnosticOutcome.CANCELLED, DiagnosticCode.CANCELLED
                elif error is not None:
                    outcome, code = DiagnosticOutcome.FAILED, classify_failure(error).code
                elif self.reason in _DECLARED_LIMIT_REASONS:
                    outcome, code = DiagnosticOutcome.SUCCEEDED, DiagnosticCode.LIMIT_REACHED
                elif cancelled:
                    outcome, code = DiagnosticOutcome.CANCELLED, DiagnosticCode.CANCELLED
                    reason = CancellationReason.UNKNOWN
                elif cleanup_failed:
                    outcome, code = DiagnosticOutcome.FAILED, DiagnosticCode.UNAVAILABLE
                else:
                    outcome, code = DiagnosticOutcome.SUCCEEDED, None
                # These server times start at the recognition consumer, not network dispatch.
                span.observe(DiagnosticStage.STT_STREAM_END,
                             DiagnosticOutcome.FAILED if cleanup_failed else outcome)
                span.finish(outcome, code=code, reason=reason)

    async def _recognition_status(self, state: str,
                                  admission: ContinuousRecognitionStarted | None = None) -> None:
        if self._segment is None:
            return
        snapshot = self._request_budget.snapshot() if self._request_budget is not None else None
        await self.emit(ListeningEvent(type="recognition_status", lease_id=self.lease_id,
            stream_index=self._segment.index, recognition_state=state,
            stt_requests_used=admission.requests_used if admission else snapshot.used if snapshot else None,
            stt_requests_remaining=admission.requests_remaining if admission else snapshot.remaining if snapshot else None))

    async def _segmented_events(self, backend: ContinuousSpeechRecognitionBackend):
        index = 0
        while self.active:
            if self.audio.remaining_seconds is not None and self.audio.remaining_seconds <= 0:
                await self._recognition_status("limit")
                self.stop("max_duration", retain_preview=True)
                await self._emit_stopped("max_duration")
                return
            if (self.limits.max_recognition_streams is not None and index >= self.limits.max_recognition_streams) or (
                    self._request_budget is not None and self._request_budget.snapshot().remaining == 0):
                await self._recognition_status("limit")
                reason = ('service_budget_exhausted' if self.limits.max_seconds is None
                    and self._request_budget is not None and self._request_budget.snapshot().remaining == 0
                    else 'input_limit')
                self.stop(reason, retain_preview=True)
                await self._emit_stopped(reason)
                return
            index += 1
            seconds = min(self.recognition_stream_seconds, getattr(backend, "max_stream_seconds", 120.0))
            if not 0 < seconds <= 290:
                raise DomainError("invalid_input", "Recognition requires a finite provider stream duration.")
            segment = _RecognitionSegment(index, first_activity_index=self._activity_index,
                first_revision=self._revision, max_samples=int(seconds * SAMPLE_RATE_HZ), on_duration=self._begin_drain)
            self._segment, self._segment_sealed = segment, False
            self._client_endpoint_activity = None
            self._stream_conflicting_offsets = False
            await self._recognition_status("opening")
            stream = backend.transcribe_events(self.audio.segment_packets(segment))
            observed = False
            duration_task = asyncio.create_task(self._stream_duration_deadline(segment, seconds))
            try:
                async for event in stream:
                    if not self.active or self._segment is not segment:
                        return
                    if isinstance(event, ContinuousRecognitionStarted):
                        await self._recognition_status("opening", event)
                        continue
                    base = segment.base_sample
                    if base is None:
                        raise DomainError("invalid_response", "Recognition produced a result before audio.")
                    if not observed:
                        observed = True
                        if index > 1:
                            pending = self._pending_finals()
                            self._offsets_ordered = all(
                                (item.offset is not None and item.activity_index)
                                or item.activity_index in self._held_activities for item in pending)
                            self._latest_final_offset = base
                        await self._recognition_status("listening")
                    if isinstance(event, ContinuousTranscriptResult):
                        offset = event.result_end_offset_samples
                        yield replace(event, result_end_offset_samples=None if offset is None else base + offset)
                    elif isinstance(event, ContinuousSpeechActivity):
                        yield replace(event, speech_event_offset_samples=base + event.speech_event_offset_samples)
                    else:
                        raise DomainError("invalid_response", "Invalid recognition event.")
            finally:
                if duration_task is not None:
                    duration_task.cancel()
                    await asyncio.gather(duration_task, return_exceptions=True)
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
            if not self.active or not segment.draining:
                return
            if self._drain_task is not None:
                self._drain_task.cancel()
                self._drain_task = None
            self._segment_sealed = True
            if segment.duration_rollover:
                # A duration boundary never asserts that a person finished speaking.
                # Keep every final/draft, close old callbacks, then renew once.
                if segment.base_sample is None or segment.last_sample == segment.base_sample:
                    self.stop("incomplete_stream", retain_preview=True)
                    await self._emit_stopped("incomplete_stream")
                    return
                self._in_activity = False
                await self._recognition_status("completed")
                self._segment_sealed = False
                self._retire_bookkeeping()
                continue
            if segment.client_endpoint is not None:
                self._settle_client_endpoint(segment)
                segment.client_endpoint.state = "completed"
                await self._emit_client_endpoint(segment.client_endpoint)
            await self._recognition_status("completed")
            if self.natural_candidate() is None:
                self.stop("incomplete_stream", retain_preview=True)
                await self._emit_stopped("incomplete_stream")
                return
            self._resume_after_commit.clear()
            await self._emit_endpoint_hints()
            await self._recognition_status("awaiting_commit")
            # Capture remains bounded while the exact sealed snapshot is consumed.
            # Do not mix a new RPC's BEGIN/finals into a still-pending old snapshot.
            await self._resume_after_commit.wait()
            self._segment_sealed = False
            self._retire_bookkeeping()

    async def _stream_duration_deadline(self, segment, seconds):
        # No service request exists until first PCM. Empty leases do not consume calls.
        await segment.progress.wait()
        await asyncio.sleep(seconds)
        if self.active and self._segment is segment and not segment.draining:
            segment.duration_rollover = True
            await self._begin_drain()

    def _retire_bookkeeping(self):
        if self.limits.max_utterances is not None:
            return
        # Per-RPC callbacks are closed before rotation. Pending finals are retained.
        oldest = max(0, self._activity_index - 32)
        for mapping in (self._settled_activities, self._endpoint_hint_by_activity):
            for key in tuple(mapping):
                if key < oldest:
                    mapping.pop(key)
        for values in (self._manual_activities, self._announced_activities):
            values.intersection_update(range(oldest, self._activity_index + 1))
        revisions = {item.revision for item in self._finals}
        self._consumed_final_revisions.intersection_update(revisions)
        for mapping in (self._late_revision_events, self._client_endpoints):
            for key in tuple(mapping)[:-64]:
                mapping.pop(key)
        if self._segment is not None:
            self._seen_offsets = {key for key in self._seen_offsets if key[0] >= self._segment.index - 1}

    async def _emit_client_endpoint(self, endpoint: _ClientEndpoint) -> ListeningEvent:
        event = ListeningEvent(type="endpoint_status", lease_id=self.lease_id,
            endpoint_id=endpoint.endpoint_id, source_end_sample=endpoint.source_end_sample,
            endpoint_state=endpoint.state)
        await self.emit(event)
        return event

    async def request_client_endpoint(self, *, endpoint_id: str,
                                      source_end_sample: int) -> None:
        """Client quiet is UI intent, never proof of speech or a finalized transcript."""
        async with self._state_lock:
            if (not self.natural_mode or not self.active or self._registry is None
                    or not self._registry.is_current(self)):
                raise DomainError("media_cancelled", "Natural listening is not active.")
            try:
                UUID(endpoint_id)
            except (ValueError, TypeError):
                raise DomainError("invalid_input", "Invalid endpoint identity.") from None
            previous = self._client_endpoints.get(endpoint_id)
            if previous is not None:
                if previous.source_end_sample != source_end_sample:
                    raise DomainError("request_conflict", "Endpoint identity changed its audio frontier.")
                await self._emit_client_endpoint(previous)
                return
            segment = self._segment
            if (type(source_end_sample) is not int or source_end_sample <= 0
                    or source_end_sample != self.audio.samples or segment is None
                    or (segment.base_sample is not None and source_end_sample <= segment.base_sample)
                    or segment.draining or self._segment_sealed
                    or len(self._client_endpoints) >= MAX_REVISION_COUNT):
                raise DomainError("invalid_input", "Endpoint must match the current sent audio frontier.")
            if segment.client_endpoint is not None:
                segment.client_endpoint.state = "cancelled"
                await self._emit_client_endpoint(segment.client_endpoint)
                if self._client_endpoint_task is not None:
                    self._client_endpoint_task.cancel()
            endpoint = _ClientEndpoint(endpoint_id, source_end_sample)
            self._client_endpoints[endpoint_id] = endpoint
            segment.client_endpoint = endpoint
            segment.endpoint_changed.set()
            await self._emit_client_endpoint(endpoint)
            self._client_endpoint_task = asyncio.create_task(self._drain_client_frontier(segment, endpoint))

    async def cancel_client_endpoint(self, *, endpoint_id: str) -> None:
        async with self._state_lock:
            if not self.active or self._registry is None or not self._registry.is_current(self):
                raise DomainError("media_cancelled", "Listening lease was revoked.")
            endpoint = self._client_endpoints.get(endpoint_id)
            if endpoint is None:
                raise DomainError("request_conflict", "Unknown endpoint identity.")
            segment = self._segment
            if (endpoint.state == "queued" and segment is not None
                    and segment.client_endpoint is endpoint and not segment.draining):
                endpoint.state = "cancelled"
                segment.client_endpoint = None
                segment.endpoint_changed.set()
                if self._client_endpoint_task is not None:
                    self._client_endpoint_task.cancel()
            # Half-close cannot be reversed. The caller retains/holds that exact
            # finalized candidate if speech resumed after the close began.
            await self._emit_client_endpoint(endpoint)

    async def _drain_client_frontier(self, segment: _RecognitionSegment,
                                     endpoint: _ClientEndpoint) -> None:
        try:
            async with asyncio.timeout(self.limits.drain_timeout_seconds):
                while (self.active and self._segment is segment
                       and segment.client_endpoint is endpoint and endpoint.state == "queued"):
                    if (segment.last_sample or 0) >= endpoint.source_end_sample:
                        endpoint.state = "draining"
                        await self._emit_client_endpoint(endpoint)
                        await self._begin_drain()
                        return
                    segment.progress.clear()
                    await segment.progress.wait()
        except TimeoutError:
            if self.active and self._segment is segment and segment.client_endpoint is endpoint:
                self.stop("timeout", retain_preview=True)
                await self._emit_stopped("timeout")

    def _settle_client_endpoint(self, segment: _RecognitionSegment) -> None:
        endpoint = segment.client_endpoint
        if endpoint is None or segment.last_sample != endpoint.source_end_sample:
            return
        selected = [item for item in self._pending_finals()
                    if item.activity_index not in self._held_activities]
        text = "".join(item.text for item in selected).strip()
        # Explicit non-speech labels and punctuation do not become conversational inputs.
        if (not selected or not any(char.isalnum() for char in text)
                or text.casefold() in {"[noise]", "[silence]", "[music]", "(noise)", "(silence)"}):
            return
        self._activity_index += 1
        activity = self._activity_index
        self._client_endpoint_activity = activity
        self._in_activity = False
        start = segment.base_sample or 0
        if selected:
            start = min(start, min(item.start_offset or 0 for item in selected))
        # Exclude previously settled activities in this RPC from the new source interval.
        for interval in self._intervals:
            if interval.index in self._settled_activities and interval.end_offset is not None:
                start = max(start, interval.end_offset)
        self._intervals.append(_ActivityInterval(activity, start, endpoint.source_end_sample,
                                                 endpoint.source_end_sample))
        revisions = {item.revision for item in selected}
        self._finals = deque((replace(item, activity_index=activity)
                            if item.revision in revisions else item for item in self._finals), maxlen=32)

    async def _begin_drain(self) -> None:
        segment = self._segment
        if segment is None or segment.draining or not self.active:
            return
        segment.draining = True
        segment.stop_requests.set()
        segment.endpoint_changed.set()
        await self._recognition_status("draining")
        self._drain_task = asyncio.create_task(self._drain_deadline(segment))

    async def _drain_deadline(self, segment: _RecognitionSegment) -> None:
        endpoint = segment.client_endpoint
        timeout = (self.limits.drain_timeout_seconds if endpoint is None else max(0.0,
            endpoint.queued_at + self.limits.drain_timeout_seconds - time.monotonic()))
        await asyncio.sleep(timeout)
        if self.active and self._segment is segment and not self._segment_sealed:
            if self._diagnostic_span is not None:
                self._diagnostic_span.finish(DiagnosticOutcome.FAILED, code=DiagnosticCode.TIMEOUT)
            self.stop("timeout", retain_preview=True)
            await self._emit_stopped("timeout")

    async def _on_transcript(self, event: ContinuousTranscriptResult) -> None:
        if (not isinstance(event.text, str) or len(event.text) > MAX_TEXT_CHARS
                or type(event.is_final) is not bool
                or type(event.provider_batch_complete) is not bool
                or type(event.has_pending_interim) is not bool
                or (event.result_end_offset_samples is not None and (
                    type(event.result_end_offset_samples) is not int
                    or event.result_end_offset_samples < 0
                    or (self.limits.max_samples is not None and event.result_end_offset_samples > self.limits.max_samples)))):
            raise DomainError("invalid_response", "Invalid continuous transcript result.")
        async with self._state_lock:
            self._provider_batch_complete = event.provider_batch_complete
            offset = event.result_end_offset_samples
            seen_key = None if offset is None else (self._segment.index if self._segment else 0, offset, event.text)
            if event.is_final and seen_key is not None and seen_key in self._seen_offsets:
                # A repeated final is not a revision of the newer interim suffix.
                # Offset identity matters: the same words spoken later remain new text.
                if event.has_pending_interim:
                    self._has_pending_interim = True
                return
            if len(self._seen_offsets) >= MAX_REVISION_COUNT:
                raise DomainError("input_limit", "Current recognition result capacity reached.")
            self._revision += 1
            self._grace_anchor = time.monotonic()
            if self._revision - (self._revision_window_start if self.limits.max_utterances is None else 0) > MAX_REVISION_COUNT:
                raise DomainError("input_limit", "Listening revision budget reached.")
            if event.is_final:
                self._has_pending_interim = event.has_pending_interim
                self._recognized_chars += len(event.text)
                if (self.limits.max_utterances is not None and
                        self._recognized_chars > MAX_TEXT_CHARS * self.limits.max_utterances):
                    raise DomainError("input_limit", "Listening transcript budget reached.")
                previous_offset = self._latest_final_offset
                activity = self._result_activity(offset, previous_offset)
                if offset is None or previous_offset is None or offset <= previous_offset:
                    self._offsets_ordered = False
                if offset is not None and previous_offset is not None and offset <= previous_offset:
                    self._stream_conflicting_offsets = True
                self._latest_final_offset = offset
                settled = self._settled_activities.get(activity)
                if self.natural_mode and settled is not None:
                    if len(settled.text) + len(event.text) > MAX_TEXT_CHARS:
                        raise DomainError("input_limit", "Utterance correction reached its text budget.")
                    settled.text += event.text
                    if seen_key is not None:
                        self._seen_offsets.add(seen_key)
                    state = await self._registry.invalidate_utterance(
                        self.session_id, settled.commit_id) if self._registry else "pending"
                    correction = ListeningEvent(type="utterance_revision", lease_id=self.lease_id,
                        revision=self._revision, text=settled.text, is_final=True,
                        utterance_id=settled.utterance_id, commit_id=settled.commit_id,
                        submission_state=state, reason="late_result_after_submission")
                    self._late_revision_events[settled.utterance_id] = correction
                    await self.emit(correction)
                    return
                if len(self._stable_transcript) + len(event.text) > MAX_TEXT_CHARS:
                    raise DomainError("input_limit", "Current transcript reached its text budget.")
                self._stable_transcript += event.text
                if seen_key is not None:
                    self._seen_offsets.add(seen_key)
                if (self.natural_mode and len(self._finals) == self._finals.maxlen
                        and self._finals[0] in self._pending_finals()):
                    raise DomainError("input_limit", "Pending activity history reached its bounded limit.")
                self._finals.append(_FinalResult(event.text, offset, self._revision,
                    activity, previous_offset, self.audio.samples, self._last_assignment_heuristic))
                self._interim_transcript = ""
                missing_offset = offset is None
            else:
                self._has_pending_interim = True
                self._interim_transcript = event.text
                missing_offset = False
            self._latest_preview = self._stable_transcript + self._interim_transcript
            if len(self._latest_preview) > MAX_TEXT_CHARS:
                raise DomainError("input_limit", "Current transcript reached its text budget.")
            revision, preview = self._revision, self._latest_preview
            preview_event = ListeningEvent(type="transcript", lease_id=self.lease_id,
                revision=revision, text=preview, is_final=event.is_final)
            self._last_preview_event = preview_event
        await self.emit(preview_event)
        if missing_offset:
            await self.emit(ListeningEvent(type="endpoint_pending", lease_id=self.lease_id,
                revision=revision, text=preview, is_final=True, reason="missing_result_offset"))
        else:
            await self._emit_endpoint_hints()
        self._schedule_endpoint()

    def _result_activity(self, offset: int | None, previous: int | None) -> int:
        self._last_assignment_heuristic = False
        if (self._segment_sealed and self._client_endpoint_activity is not None
                and self._client_endpoint_activity in self._settled_activities):
            # Any callback still associated with this already-sealed RPC belongs
            # to its submitted snapshot, even when Google omitted all offsets.
            return self._client_endpoint_activity
        if offset is None:
            if self.natural_mode and self._single_unsettled_stream_activity():
                return self._activity_index
            return 0
        intervals = tuple(self._intervals)
        if self._segment is not None:
            # An RPC's offsets are rebased into the lease clock, but that does not
            # grant its orphan results membership in a previous RPC's activity.
            intervals = tuple(item for item in intervals
                              if item.index > self._segment.first_activity_index)
        owner = next((item for item in reversed(intervals) if item.begin_offset < offset), None)
        if owner is None:
            return 0
        # A late piece beyond END still belongs to this activity until a newer
        # BEGIN covers its offset. A result spanning multiple activities cannot
        # be split into words safely from end offsets alone.
        if previous is not None:
            touched = [item for item in intervals if item.begin_offset < offset
                and (item.end_offset is None or item.end_offset > previous)]
            if len(touched) > 1:
                older = touched[:-1]
                if (touched[-1] is owner and all(item.index in self._announced_activities
                        and item.end_offset is not None and item.end_offset <= owner.begin_offset
                        for item in older)):
                    # VAD/final grace can leave an offset gap through silence. A new
                    # activity may own its later final, but retain the heuristic label
                    # rather than silently upgrading that attribution to offset proof.
                    self._last_assignment_heuristic = True
                else:
                    return 0
        return owner.index

    def _single_unsettled_stream_activity(self) -> bool:
        segment = self._segment
        if segment is None or self._activity_index <= segment.first_activity_index:
            return False
        intervals = [item for item in self._intervals if item.index > segment.first_activity_index]
        if not intervals or intervals[-1].index != self._activity_index:
            return False
        for interval in intervals[:-1]:
            settled = self._settled_activities.get(interval.index)
            if (settled is None or settled.endpoint_basis != "offset_coverage"
                    or settled.final_offset is None or interval.end_offset is None
                    or settled.final_offset < interval.end_offset):
                return False
        return True

    def natural_candidate(self) -> ListeningEvent | None:
        if self.client_endpointing and not (
                self._segment_sealed and self._client_endpoint_activity is not None):
            return None
        if (not self.natural_mode or not self.active or self._in_activity
                or self._has_pending_interim or not self._provider_batch_complete
                or self._interim_transcript):
            return None
        segment = self._segment
        if segment is not None and segment.draining and not self._segment_sealed:
            return None
        interval = self._intervals[-1] if self._intervals else None
        if (interval is None or interval.end_offset is None
                or interval.index in self._settled_activities
                or interval.index in self._manual_activities
                or interval.index in self._held_activities):
            return None
        pending = self._pending_finals()
        finals = [item for item in pending if item.activity_index == interval.index]
        text = "".join(item.text for item in finals).strip()
        source_end = max(interval.source_end_sample,
                         finals[-1].source_end_sample if finals else 0)
        if (not text or not finals or any(item.activity_index == 0 for item in pending)
                or "".join(item.text for item in pending).strip() != self.stable_text
                or pending[-len(finals):] != finals):
            return None
        final = finals[-1].offset
        if (self._segment_sealed and segment is not None
                and self._client_endpoint_activity == interval.index):
            source_end = segment.last_sample or 0
            if not interval.begin_offset < source_end <= self.audio.samples:
                return None
            # A completed RPC gives a stable snapshot. Provider offsets are optional
            # and cannot establish any stronger human-speech finality.
            if final is not None and not interval.begin_offset <= final <= source_end:
                final = None
            basis = "client_silence_finalized"
        elif self._segment_sealed and segment is not None:
            source_end = segment.last_sample or 0
            if (self._stream_conflicting_offsets
                    or not self._single_unsettled_stream_activity()
                    or not interval.end_offset <= source_end <= self.audio.samples):
                return None
            basis = "stream_finalized"
        elif (not self._offsets_ordered or final is None
                or not interval.begin_offset <= final <= source_end
                or not interval.end_offset <= source_end <= self.audio.samples):
            return None
        elif final >= interval.end_offset and not any(item.heuristic_activity for item in finals):
            basis = "offset_coverage"
            source_end = final
        elif time.monotonic() - self._grace_anchor >= self.limits.natural_grace_seconds:
            # Configured VAD/final grace is a latency heuristic, not offset proof.
            basis = "vad_final_grace"
            source_end = max(final, interval.end_offset)
        else:
            return None
        token = str(uuid5(UUID(self.lease_id), f"activity:{interval.index}"))
        return ListeningEvent(type="utterance_ready", lease_id=self.lease_id,
            revision=self._revision, text=text, is_final=True, utterance_id=token,
            begin_offset_samples=interval.begin_offset, end_offset_samples=interval.end_offset,
            final_offset_samples=final, endpoint_basis=basis,
            source_end_sample=source_end,
            client_endpoint_id=(segment.client_endpoint.endpoint_id
                if basis == "client_silence_finalized" and segment is not None
                and segment.client_endpoint is not None else None))

    def _pending_finals(self) -> list[_FinalResult]:
        return [item for item in self._finals if item.revision > self._last_committed_revision
                and item.revision not in self._consumed_final_revisions]

    def _schedule_endpoint(self) -> None:
        task = self._grace_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._grace_task = None
        if (not self.natural_mode or self.client_endpointing or not self.active or self._in_activity
                or self._recognition_task is None or not self._intervals
                or self._intervals[-1].end_offset is None
                or self._activity_index in self._settled_activities
                or self._activity_index in self._manual_activities
                or self._activity_index in self._held_activities
                or (self._segment is not None
                    and self._activity_index <= self._segment.first_activity_index)):
            return
        if self.natural_candidate() is not None:
            return
        self._grace_task = asyncio.create_task(self._after_grace(self._activity_index, self._revision))

    async def _after_grace(self, activity_index: int, revision: int) -> None:
        delay = max(0.0, self._grace_anchor + self.limits.natural_grace_seconds - time.monotonic())
        await asyncio.sleep(delay)
        if (not self.active or self._in_activity or self._activity_index != activity_index
                or self._revision != revision or (self._registry is not None
                    and not self._registry.is_current(self))):
            return
        if self._segment is not None and self._segment.client_endpoint is not None:
            # The client frontier owns this half-close; VAD grace must not close it early.
            return
        if self.natural_candidate() is not None:
            await self._emit_endpoint_hints()
        else:
            await self._begin_drain()

    async def _on_activity(self, event: ContinuousSpeechActivity) -> None:
        if (event.kind not in ("begin", "end") or type(event.speech_event_offset_samples) is not int
                or event.speech_event_offset_samples < 0
                or (self.limits.max_samples is not None and event.speech_event_offset_samples > self.limits.max_samples)):
            raise DomainError("invalid_response", "Invalid speech activity event.")
        if self.client_endpointing:
            # Local quiet owns the boundary in this explicitly selected mode.
            # Missing/repeated provider BEGIN or END is advisory, not a submission gate.
            return
        if event.kind == "begin":
            if self._in_activity:
                raise DomainError("invalid_response", "Repeated speech activity BEGIN without END.")
            if self._intervals and event.speech_event_offset_samples < (
                    self._intervals[-1].end_offset or self._intervals[-1].begin_offset):
                self._offsets_ordered = False
                self._stream_conflicting_offsets = True
            self._activity_index += 1
            self._in_activity = True
            self._grace_anchor = time.monotonic()
            self._schedule_endpoint()
            self._intervals.append(_ActivityInterval(self._activity_index,
                event.speech_event_offset_samples))
            return
        if not self._in_activity:
            # Orphan END has no manual-input or commit authority.
            return
        interval = next((item for item in reversed(self._intervals)
                         if item.index == self._activity_index), None)
        if interval is None or event.speech_event_offset_samples < interval.begin_offset:
            raise DomainError("invalid_response", "Speech activity offsets moved backwards.")
        interval.end_offset = event.speech_event_offset_samples
        interval.source_end_sample = self.audio.samples
        self._ends.append(_PendingEnd(event.speech_event_offset_samples,
                                      self._activity_index, interval.begin_offset))
        self._in_activity = False
        self._grace_anchor = time.monotonic()
        await self._emit_endpoint_hints()
        self._schedule_endpoint()

    async def _emit_endpoint_hints(self) -> None:
        """Emit only a UI hint. It never creates a committable input or an Actor turn."""
        threshold = int(self.limits.max_final_to_end_seconds * SAMPLE_RATE_HZ)
        async with self._state_lock:
            candidate = self.natural_candidate()
            if candidate is not None:
                identity = (candidate.utterance_id, candidate.revision)
                if identity != self._natural_notice:
                    self._natural_notice = identity
                    self._announced_activities.intersection_update(item.index for item in self._intervals)
                    self._announced_activities.add(self._activity_index)
                    await self.emit(candidate)
                return
            pending = self._stable_transcript.strip()
            revision = self._revision
            ends = tuple(self._ends)
            finals = tuple(self._finals)
        if not pending:
            return
        for end in ends:
            covered = [result for result in finals
                if result.offset is not None
                and end.begin_offset <= result.offset <= end.offset]
            if not covered:
                continue
            latest = max(covered, key=lambda result: (result.offset, result.revision))
            if end.offset - latest.offset > threshold:
                continue
            if self._endpoint_hint_by_activity.get(end.activity_index) == pending:
                continue
            self._endpoint_hint_by_activity[end.activity_index] = pending
            await self.emit(ListeningEvent(type="endpoint_pending", lease_id=self.lease_id,
                revision=revision, text=pending, is_final=True,
                reason="unmatched_activity_end"))

    async def manual_commit(self, *, commit_id: str, revision: int,
                            registry: "ContinuousListeningRegistry",
                            utterance_id: str | None = None) -> ListeningCommitResult:
        if not re.fullmatch(r"[A-Fa-f0-9-]{36}", commit_id):
            raise DomainError("invalid_input", "Invalid listening commit identity.")
        async with self._state_lock:
            prior = self._commit_results.get(commit_id)
            if prior is not None:
                if prior.revision == revision and prior.utterance_id == utterance_id:
                    return prior
                raise DomainError("request_conflict", "Commit identity was reused with different data.")
            if not self.active or not registry.is_current(self):
                raise DomainError("media_cancelled", "Listening lease was revoked.")
            if type(revision) is not int or revision != self._revision:
                raise DomainError("transcript_stale", "Transcript changed before the manual commit.")
            candidate = self.natural_candidate() if utterance_id is not None else None
            if utterance_id is not None and (candidate is None or candidate.utterance_id != utterance_id):
                raise DomainError("transcript_stale", "Natural utterance changed before the commit.")
            text = candidate.text if candidate is not None else self._stable_transcript.strip()
            if not text:
                raise DomainError("transcript_empty", "No stable final transcript is ready to send.")
            if self.limits.max_utterances is not None and self._commit_count >= self.limits.max_utterances:
                raise DomainError("session_capacity", "Listening commit budget reached.")
            segment_seq = self._commit_count + 1
            await registry.register_utterance(self, commit_id, text, segment_seq)
            result = ListeningCommitResult(self.lease_id, commit_id, segment_seq, revision, text, utterance_id)
            self._commit_results[commit_id] = result
            self._commit_count += 1
            self._revision_window_start = self._revision
            if self.limits.max_utterances is None:
                for old in tuple(self._commit_results)[:-64]:
                    self._commit_results.pop(old)
            if candidate is not None:
                selected = [item for item in self._pending_finals()
                            if item.activity_index == self._activity_index]
                raw = "".join(item.text for item in selected)
                self._stable_transcript = self._stable_transcript[:-len(raw)]
                self._consumed_final_revisions.update(item.revision for item in selected)
                self._settled_activities[self._activity_index] = _SettledUtterance(
                    utterance_id, commit_id, text, candidate.final_offset_samples, candidate.endpoint_basis)
            else:
                self._last_committed_revision = revision
                self._consumed_final_revisions.clear()
                if self.limits.max_utterances is None:
                    self._hold_results.clear()
                    self._held_activities.clear()
                self._stable_transcript = ""
                if self.natural_mode:
                    self._manual_activities.add(self._activity_index)
            self._latest_preview = self._stable_transcript + self._interim_transcript
            self._revision += 1
            next_revision = self._revision
            preview = self._latest_preview
            preview_event = ListeningEvent(type="transcript", lease_id=self.lease_id,
                revision=next_revision, text=preview, is_final=False,
                commit_id=commit_id, utterance_id=utterance_id)
            self._last_preview_event = preview_event
            if self._segment_sealed:
                self._resume_after_commit.set()
            exhausted = self.limits.max_utterances is not None and self._commit_count >= self.limits.max_utterances
            if exhausted:
                # The commit snapshot is returned directly to the client before the
                # WebSocket drains this visible finite lease-stop event.
                self.stop("utterance_limit")
        self._retire_bookkeeping()
        await self.emit(preview_event)
        if exhausted:
            await self._emit_stopped("utterance_limit")
        return result

    async def hold_candidate(self, *, utterance_id: str, revision: int) -> ListeningHoldResult:
        """Retain a sealed candidate without input authority or deleting any text."""
        async with self._state_lock:
            if not self.active or self._registry is None or not self._registry.is_current(self):
                raise DomainError("media_cancelled", "Listening lease was revoked.")
            prior = self._hold_results.get(utterance_id)
            if prior is not None:
                if prior.revision == revision:
                    return prior
                raise DomainError("request_conflict", "Held utterance identity was reused with another revision.")
            if type(revision) is not int or revision != self._revision:
                raise DomainError("transcript_stale", "Utterance changed before the hold.")
            candidate = self.natural_candidate()
            if (candidate is None or candidate.endpoint_basis not in {"stream_finalized", "client_silence_finalized"}
                    or not self._segment_sealed):
                raise DomainError("transcript_stale", "Sealed utterance is no longer available to hold.")
            if candidate.utterance_id != utterance_id:
                raise DomainError("request_conflict", "Hold belongs to another utterance.")
            if len(self._hold_results) >= (self.limits.max_utterances or 32):
                raise DomainError("session_capacity", "Retained utterance limit reached.")
            result = ListeningHoldResult(self.lease_id, utterance_id, revision,
                                         candidate.text, self._activity_index)
            self._hold_results[utterance_id] = result
            self._held_activities.add(self._activity_index)
            return result

    def release_held_candidate(self, result: ListeningHoldResult) -> None:
        """Called only after the success frame is sent; replay cannot reopen twice."""
        if (self.active and self._segment_sealed and self._registry is not None
                and self._registry.is_current(self)
                and self._hold_results.get(result.utterance_id) == result
                and result.activity_index == self._activity_index):
            self._resume_after_commit.set()

    def stop(self, reason: str = "user_stop", *, retain_preview: bool = False) -> None:
        retain_preview = retain_preview or reason in {
            "max_duration", "max_samples", "queue_limit", "output_limit", "utterance_limit"}
        if reason in _CANCELLATION_REASONS or reason == "invalid_input":
            # A later explicit Stop/replacement also fences an unsent EOF snapshot.
            self._terminal_preview = None
            self._terminal_corrections = ()
            retain_preview = False
        if not self.active:
            return
        self.active = False
        self.reason = reason
        # Only the recognition consumer opts into bounded terminal settlement.
        # No extra audio is consumed, no provider callback is awaited or retried.
        self._terminal_preview = self._last_preview_event if retain_preview else None
        self._terminal_corrections = tuple(self._late_revision_events.values()) if retain_preview else ()
        if self._grace_task is not None and self._grace_task is not asyncio.current_task():
            self._grace_task.cancel()
        if self._client_endpoint_task is not None and self._client_endpoint_task is not asyncio.current_task():
            self._client_endpoint_task.cancel()
        if self._drain_task is not None and self._drain_task is not asyncio.current_task():
            self._drain_task.cancel()
        self._resume_after_commit.set()
        if self._segment is not None:
            self._segment.stop_requests.set()
            self._segment.endpoint_changed.set()
        # Record the observed local stop immediately; provider cleanup may lag or fail.
        if self._diagnostic_span is not None:
            cancel_reason = _CANCELLATION_REASONS.get(reason)
            if cancel_reason is not None:
                self._diagnostic_span.finish(DiagnosticOutcome.CANCELLED,
                    code=DiagnosticCode.CANCELLED, reason=cancel_reason)
            elif reason in _DECLARED_LIMIT_REASONS:
                self._diagnostic_span.finish(DiagnosticOutcome.SUCCEEDED,
                    code=DiagnosticCode.LIMIT_REACHED)
        self.audio.clear()
        task = self._recognition_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        while not self.events.empty():
            try:
                self.events.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _emit_stopped(self, reason: str) -> None:
        if self._terminal_sent:
            return
        self._terminal_sent = True
        try:
            self.events.put_nowait(ListeningEvent(type="stopped", lease_id=self.lease_id,
                                                   reason=reason, diagnostic_id=self.diagnostic_id))
        except asyncio.QueueFull:
            pass

    async def aclose(self, reason: str = "session_closed") -> None:
        self.stop(reason)
        task = self._recognition_task
        if task is not None:
            await asyncio.wait({task}, timeout=.25)


class ContinuousListeningRegistry:
    """One active lease per session plus bounded one-use input authority."""
    def __init__(self, *, limits: ListeningLimits | None = None,
                 diagnostics: Diagnostics | None = None):
        self.limits = limits or ListeningLimits()
        self._diagnostics = diagnostics
        self._lock = asyncio.Lock()
        self._active: dict[str, ListeningLease] = {}
        self._lease_count: dict[str, int] = {}
        self._utterances: dict[tuple[str, str], _UtteranceBinding] = {}
        self._used_lease_ids: dict[tuple[str, str], None] = {}
        self._total_leases = 0
        self._closed = False

    async def start(self, session_id: str, lease_id: str, *, natural_mode: bool = False,
                    client_endpointing: bool = False) -> ListeningLease:
        if not isinstance(session_id, str) or not session_id or not re.fullmatch(
                r"[A-Fa-f0-9-]{36}", lease_id):
            raise DomainError("invalid_input", "Invalid listening lease identity.")
        replaced = None
        async with self._lock:
            if self._closed:
                raise DomainError("session_closed", "Listening service has closed.")
            if (self.limits.max_streams_per_session is not None and
                    self._lease_count.get(session_id, 0) >= self.limits.max_streams_per_session):
                raise DomainError("session_capacity", "Listening lease request budget reached.")
            if self.limits.max_total_streams is not None and self._total_leases >= self.limits.max_total_streams:
                raise DomainError("session_capacity", "Application STT lease budget reached.")
            key = (session_id, lease_id)
            if key in self._used_lease_ids:
                raise DomainError("stream_consumed", "Listening lease identity has already been used.")
            replaced = self._active.get(session_id)
            lease = ListeningLease(session_id, lease_id, limits=self.limits, diagnostics=self._diagnostics,
                natural_mode=natural_mode, client_endpointing=client_endpointing, registry=self)
            self._active[session_id] = lease
            self._used_lease_ids[key] = None
            if self.limits.max_streams_per_session is None:
                old = [item for item in self._used_lease_ids if item[0] == session_id]
                for item in old[:-128]:
                    self._used_lease_ids.pop(item, None)
            self._lease_count[session_id] = self._lease_count.get(session_id, 0) + 1
            self._total_leases += 1
        if replaced is not None:
            await self.stop_lease(replaced, "replaced")
        return lease

    def is_current(self, lease: ListeningLease) -> bool:
        return lease.active and self._active.get(lease.session_id) is lease

    async def current(self, session_id: str) -> ListeningLease | None:
        async with self._lock:
            return self._active.get(session_id)

    def lease_starts_for_session(self, session_id: str) -> int:
        return self._lease_count.get(session_id, 0)

    @property
    def total_lease_starts(self) -> int:
        return self._total_leases

    async def stop_session(self, session_id: str, reason: str = "user_stop") -> None:
        async with self._lock:
            lease = self._active.pop(session_id, None)
        if lease is not None:
            await self._stop(lease, reason)

    async def stop_lease(self, lease: ListeningLease, reason: str = "user_stop") -> None:
        async with self._lock:
            if (self._active.get(lease.session_id) is lease and reason not in {
                    "max_duration", "max_samples", "queue_limit", "output_limit", "utterance_limit"}):
                self._active.pop(lease.session_id, None)
            # A finite terminal lease is inactive, but remains reachable until
            # replacement/Stop/Close can fence an outstanding terminal writer.
        await self._stop(lease, reason)

    async def _stop(self, lease: ListeningLease, reason: str) -> None:
        revoke = reason in {"user_stop", "permission_lost", "replaced", "disconnect",
                            "session_closed", "invalid_input"}
        async with self._lock:
            if revoke:
                for (session_id, _commit_id), binding in self._utterances.items():
                    if session_id == lease.session_id and binding.lease_id == lease.lease_id:
                        if binding.status in ("pending", "reserved"):
                            binding.status = "revoked"
        lease.stop(reason)
        await lease._emit_stopped(reason)

    async def register_utterance(self, lease: ListeningLease, utterance_id: str,
                                 text: str, segment_seq: int) -> None:
        if not self.is_current(lease):
            raise DomainError("media_cancelled", "Listening lease was revoked.")
        if (not re.fullmatch(r"[A-Fa-f0-9-]{36}", utterance_id) or not text
                or len(text) > MAX_TEXT_CHARS or type(segment_seq) is not int or segment_seq < 1):
            raise DomainError("invalid_input", "Invalid listening utterance.")
        async with self._lock:
            if not self.is_current(lease):
                raise DomainError("media_cancelled", "Listening lease was revoked.")
            key = (lease.session_id, utterance_id)
            existing = self._utterances.get(key)
            if existing is not None:
                if (existing.lease_id, existing.text, existing.segment_seq) == (
                        lease.lease_id, text.strip(), segment_seq):
                    return
                raise DomainError("request_conflict", "Listening commit identity was reused.")
            session_records = sum(1 for (sid, _), binding in self._utterances.items()
                                  if sid == lease.session_id and binding.status != "revoked")
            if self.limits.max_streams_per_session is None or self.limits.max_utterances is None:
                # Retire only settled authority. Pending/reserved snapshots may never be lost.
                records = [key for key in self._utterances if key[0] == lease.session_id]
                for old in tuple(records):
                    if len(records) < 128:
                        break
                    if self._utterances[old].status in {"accepted", "revoked"}:
                        self._utterances.pop(old)
                        records.remove(old)
                if len(records) >= 128:
                    raise DomainError("busy", "Pending listening input capacity reached.")
            elif session_records >= self.limits.max_streams_per_session * self.limits.max_utterances:
                raise DomainError("session_capacity", "Listening input budget reached.")
            self._utterances[key] = _UtteranceBinding(lease.lease_id, text.strip(), segment_seq)

    async def mark_delivered(self, session_id: str, lease_id: str, commit_id: str) -> bool:
        async with self._lock:
            binding = self._utterances.get((session_id, commit_id))
            if (binding is None or binding.lease_id != lease_id or binding.status == "revoked"):
                return False
            if binding.status in {"reserved", "accepted"}:
                return binding.delivered
            binding.delivered = True
            return True

    async def invalidate_utterance(self, session_id: str, commit_id: str) -> str:
        """Revoke a stale pending snapshot; never claim to undo accepted Actor input."""
        async with self._lock:
            binding = self._utterances.get((session_id, commit_id))
            if binding is None:
                return "unknown"
            state = binding.status
            if state in {"pending", "reserved"}:
                binding.status = "revoked"
            return state

    async def mark_accepted(self, session_id: str, utterance_id: str, request_id: str,
                            text: str) -> None:
        """Record that Actor.submit committed this exact input; Stop cannot undo it."""
        async with self._lock:
            binding = self._utterances.get((session_id, utterance_id))
            if (binding is None or binding.text != text.strip()
                    or binding.request_id != request_id
                    or binding.status not in ("reserved", "revoked", "accepted")):
                raise DomainError("request_conflict", "Listening input was not reserved.")
            binding.status = "accepted"

    async def validate_submission(self, session_id: str, utterance_id: str, request_id: str,
                                  text: str) -> bool:
        """Bind explicit UI commit to one standard input request, idempotent on exact retry."""
        async with self._lock:
            binding = self._utterances.get((session_id, utterance_id))
            if binding is None or binding.text != text.strip():
                raise DomainError("request_conflict", "Listening transcript does not match its lease.")
            if binding.status == "accepted":
                if binding.request_id == request_id:
                    return True
                raise DomainError("request_conflict", "Listening commit was already consumed.")
            if binding.status == "revoked":
                raise DomainError("request_conflict", "Listening commit was revoked by Stop.")
            if not binding.delivered:
                raise DomainError("request_conflict", "Listening commit has not been delivered.")
            if binding.status == "reserved":
                if binding.request_id == request_id:
                    return True
                raise DomainError("request_conflict", "Listening commit is reserved for another request.")
            binding.request_id = request_id
            binding.status = "reserved"
            return True

    async def close_session(self, session_id: str) -> None:
        await self.stop_session(session_id, "session_closed")
        async with self._lock:
            self._lease_count.pop(session_id, None)
            self._used_lease_ids = {key: None for key in self._used_lease_ids if key[0] != session_id}
            for key in [key for key in self._utterances if key[0] == session_id]:
                self._utterances.pop(key, None)

    async def aclose(self) -> None:
        async with self._lock:
            self._closed = True
            leases = tuple(self._active.values())
            self._active.clear()
        for lease in leases:
            await self._stop(lease, "session_closed")
        async with self._lock:
            self._lease_count.clear()
            self._used_lease_ids.clear()
            self._utterances.clear()
            self._total_leases = 0
