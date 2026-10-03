"""Bounded per-operation media plumbing. SessionActor remains the only authority.

No provider selection, persistence, transcript-to-turn conversion or authorization
lives here. Cancellation discards buffered output independently of provider cooperation.
"""
import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Generic, TypeVar

from mira.application.diagnostic_errors import classify_failure
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticContext, DiagnosticOutcome, DiagnosticSpan,
    DiagnosticStage, failure_diagnostic_id,
)
from mira.application.ports.diagnostics import Diagnostics
from mira.application.ports.media import AudioPacket, SpeechSynthesisBackend, TranscriptRevision
from mira.domain.errors import DomainError
from mira.domain.models import Effect

MediaValue = TypeVar("MediaValue", AudioPacket, TranscriptRevision)
MAX_PCM_BYTES = 12000
MAX_OUTPUT_SAMPLES = 24000 * 300
MAX_INPUT_SECONDS = 60
_SAFE_CODES = frozenset({"invalid_input", "input_limit", "output_limit", "invalid_response",
                        "response_limit", "invalid_audio", "unsupported_audio", "empty_audio",
                        "incomplete_stream", "blocked", "unauthenticated", "permission_denied",
                        "quota_exhausted", "timeout", "unavailable", "media_cancelled"})


def media_error(error: Exception) -> DomainError:
    code = str(getattr(error, "code", "unavailable"))
    if isinstance(error, TimeoutError):
        code = "timeout"
    if code not in _SAFE_CODES:
        code = "unavailable"
    return DomainError(code, "Media operation did not complete.")


async def close_iterator(stream) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()


class MediaOperation(Generic[MediaValue]):
    """One bounded producer with cancellation-aware reads and best-effort teardown."""
    def __init__(self, source: Callable[[], AsyncIterator[MediaValue]], *, activity_seq: int,
                 input_epoch: int, output_epoch: int, effect: Effect | None = None,
                 diagnostics: Diagnostics | None = None,
                 diagnostic_context: DiagnosticContext = DiagnosticContext(),
                 discard_input: Callable[[], None] | None = None):
        self.activity_seq, self.input_epoch, self.output_epoch = activity_seq, input_epoch, output_epoch
        self.effect = effect
        self.cancelled = asyncio.Event()
        self.done = asyncio.Event()
        self._queue: asyncio.Queue[MediaValue] = asyncio.Queue(maxsize=4)
        self._error: DomainError | None = None
        self._diagnostics = DiagnosticSpan(diagnostics,
            DiagnosticStage.TTS if effect is not None else DiagnosticStage.STT, diagnostic_context)
        self._cancel_reason = CancellationReason.UNKNOWN
        self._discard_input = discard_input
        self._consumers: tuple[asyncio.Task, ...] = ()
        self.task = asyncio.create_task(self._run(source))

    @property
    def diagnostic_id(self) -> str | None:
        return failure_diagnostic_id(self._diagnostics.context)

    @property
    def tasks(self) -> tuple[asyncio.Task, ...]:
        return (self.task, *self._consumers)

    def own_consumers(self, *tasks: asyncio.Task) -> None:
        """Keep this microphone's socket children alive through bounded teardown."""
        if self._consumers:
            raise RuntimeError("Media consumers are already owned.")
        self._consumers = tasks

    def cancel(self, reason: CancellationReason = CancellationReason.UNKNOWN) -> None:
        already_cancelled = self.cancelled.is_set()
        if not self.cancelled.is_set() and not self.done.is_set():
            self._cancel_reason = reason
            self._diagnostics.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED,
                                     reason=reason)
        self.cancelled.set()
        if self._discard_input is not None:
            self._discard_input()
        while not self._queue.empty():
            self._queue.get_nowait()
        # Repeated close/Stop must not interrupt an iterator's aclose cleanup.
        if not already_cancelled and not self.task.done():
            self.task.cancel()

    async def _run(self, source: Callable[[], AsyncIterator[MediaValue]]) -> None:
        stream = None
        try:
            async with asyncio.timeout(90):
                stream = source()
                async for value in stream:
                    if self.cancelled.is_set() or asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    await self._queue.put(value)
        except asyncio.CancelledError:
            self.cancelled.set()
        except Exception as error:
            self._error = media_error(error)
        finally:
            if stream is not None:
                try:
                    await close_iterator(stream)
                except Exception as error:
                    self._error = self._error or media_error(error)
            if self.cancelled.is_set():
                self._diagnostics.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED,
                                         reason=self._cancel_reason)
            elif self._error is not None:
                self._diagnostics.finish(DiagnosticOutcome.FAILED,
                                         code=classify_failure(self._error).code)
            else:
                self._diagnostics.finish(DiagnosticOutcome.SUCCEEDED)
            self.done.set()

    async def values(self) -> AsyncIterator[MediaValue]:
        while True:
            if self.cancelled.is_set():
                raise DomainError("media_cancelled", "Media operation was cancelled.")
            if self.done.is_set() and self._queue.empty():
                if self._error is not None:
                    raise self._error
                return
            item = asyncio.create_task(self._queue.get())
            done = asyncio.create_task(self.done.wait())
            cancelled = asyncio.create_task(self.cancelled.wait())
            try:
                await asyncio.wait((item, done, cancelled), return_when=asyncio.FIRST_COMPLETED)
                if self.cancelled.is_set():
                    raise DomainError("media_cancelled", "Media operation was cancelled.")
                if item.done():
                    yield item.result()
            finally:
                for task in (item, done, cancelled):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(item, done, cancelled, return_exceptions=True)

    async def close(self, reason: CancellationReason = CancellationReason.UNKNOWN) -> None:
        self.cancel(reason)
        # A broken cancellation-resistant provider cannot block local revocation.
        # wait does not propagate outer cancellation to children or iterator cleanup.
        await asyncio.wait(self.tasks, timeout=.25)


async def speech_packets(backend: SpeechSynthesisBackend, effect: Effect) -> AsyncIterator[AudioPacket]:
    stream = backend.synthesize(effect.value, effect.id)
    cursor = 0
    try:
        async for packet in stream:
            if (not isinstance(packet, AudioPacket) or packet.stream_id != effect.id
                    or type(packet.first_sample) is not int or packet.first_sample != cursor
                    or type(packet.sample_rate_hz) is not int or packet.sample_rate_hz != 24000
                    or not isinstance(packet.pcm, bytes) or not packet.pcm or len(packet.pcm) % 2
                    or len(packet.pcm) > 2 * 1024 * 1024
                    or (packet.pcm[:4] == b"RIFF" and packet.pcm[8:12] == b"WAVE")):
                raise DomainError("invalid_audio", "Speech provider returned invalid PCM.")
            if cursor + len(packet.pcm) // 2 > MAX_OUTPUT_SAMPLES:
                raise DomainError("output_limit", "Speech output exceeded its sample budget.")
            for offset in range(0, len(packet.pcm), MAX_PCM_BYTES):
                pcm = packet.pcm[offset:offset + MAX_PCM_BYTES]
                yield AudioPacket(effect.id, cursor, 24000, pcm)
                cursor += len(pcm) // 2
        if cursor == 0:
            raise DomainError("empty_audio", "Speech provider returned no audio.")
    finally:
        await close_iterator(stream)


class MicrophoneBuffer:
    """Ephemeral PCM queue. Finish drains; cancel discards. Neither creates a turn."""
    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self._queue: asyncio.Queue[AudioPacket | None] = asyncio.Queue(maxsize=8)
        self._samples = 0
        self._sequence = 0
        self._started = asyncio.get_running_loop().time()
        self._finished = False

    @property
    def finished(self) -> bool:
        return self._finished

    def push(self, *, sequence: int, first_sample: int, pcm: bytes) -> None:
        elapsed = asyncio.get_running_loop().time() - self._started
        if self._finished or sequence != self._sequence + 1 or first_sample != self._samples:
            raise DomainError("invalid_input", "Microphone chunks must be contiguous.")
        if (not pcm or len(pcm) % 2 or len(pcm) > MAX_PCM_BYTES
                or (first_sample == 0 and pcm[:4] == b"RIFF" and pcm[8:12] == b"WAVE")):
            raise DomainError("invalid_audio", "Microphone chunk is not bounded PCM16.")
        samples = self._samples + len(pcm) // 2
        if samples > 16000 * MAX_INPUT_SECONDS:
            raise DomainError("input_limit", "Microphone duration budget reached.")
        if samples > 16000 * (elapsed + 1) or sequence > 100 + elapsed * 100:
            raise DomainError("input_limit", "Microphone input exceeds its pacing budget.")
        try:
            self._queue.put_nowait(AudioPacket(self.stream_id, first_sample, 16000, pcm))
        except asyncio.QueueFull:
            raise DomainError("input_limit", "Microphone input buffer is full.") from None
        self._samples, self._sequence = samples, sequence

    async def finish(self) -> None:
        self._finished = True
        # If full, the consumer observes finished after draining; never block
        # the socket receiver here, so disconnect can still cancel recognition.
        if not self._queue.full():
            self._queue.put_nowait(None)

    async def packets(self) -> AsyncIterator[AudioPacket]:
        while True:
            if self._finished and self._queue.empty():
                return
            packet = await self._queue.get()
            if packet is None:
                return
            yield packet

    def clear(self) -> None:
        self._finished = True
        while not self._queue.empty():
            self._queue.get_nowait()
