"""Typed provider events needed only by a continuous microphone lease.

Offsets are integer samples from the beginning of one lease's 16 kHz mono stream.
A final text result alone is not an utterance endpoint. Provider activity or an
explicit bounded client-silence drain can establish a candidate source interval;
the latter is a UI timing heuristic and does not prove human-speech finality.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from mira.application.ports.media import AudioPacket


@dataclass(frozen=True, slots=True)
class ContinuousTranscriptResult:
    text: str
    is_final: bool
    result_end_offset_samples: int | None
    provider_batch_complete: bool = True
    has_pending_interim: bool = False


@dataclass(frozen=True, slots=True)
class ContinuousSpeechActivity:
    kind: Literal["begin", "end"]
    speech_event_offset_samples: int


@dataclass(frozen=True, slots=True)
class ContinuousRecognitionStarted:
    """An irreversible shared attempt was reserved; not a billing receipt."""
    requests_used: int
    requests_remaining: int | None


ContinuousRecognitionEvent: TypeAlias = ContinuousTranscriptResult | ContinuousSpeechActivity | ContinuousRecognitionStarted


class ContinuousSpeechRecognitionBackend(Protocol):
    """One bounded streaming RPC; adapters must retain provider offsets and VAD events."""
    def transcribe_events(self, packets: AsyncIterator[AudioPacket]
                          ) -> AsyncIterator[ContinuousRecognitionEvent]: ...
