"""Typed extension seams, NOT registered capabilities in the foundation build.

WP02 / WP03 must add capability checks, progress and cancellation receipts before
these ports are used. This module does not import or initialize any vendor SDK.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from mira.application.contracts import ReviewVerdict


@dataclass(frozen=True, slots=True)
class AudioPacket:
    stream_id: str
    first_sample: int
    sample_rate_hz: int
    pcm: bytes


@dataclass(frozen=True, slots=True)
class MediaArtifact:
    resource_id: str
    content_digest: str
    media_type: str


@dataclass(frozen=True, slots=True)
class TranscriptRevision:
    input_stream_id: str
    revision: int
    text: str
    is_final: bool  # ASR final is NOT a semantic turn-complete assertion.


@dataclass(frozen=True, slots=True)
class MediaRequest:
    request_id: str
    specification: str
    allowed_resource_ids: tuple[str, ...]
    output_epoch: int


@dataclass(frozen=True, slots=True)
class MediaReviewObservation:
    verdict: ReviewVerdict
    checked_content_digest: str
    coverage: tuple[str, ...]
    reason_code: str


class SpeechRecognitionBackend(Protocol):
    def transcribe(self, packets: AsyncIterator[AudioPacket]) -> AsyncIterator[TranscriptRevision]: ...


class SpeechSynthesisBackend(Protocol):
    def synthesize(self, approved_text: str, stream_id: str) -> AsyncIterator[AudioPacket]: ...


class ImageBackend(Protocol):
    async def generate(self, request: MediaRequest) -> MediaArtifact: ...


class VisionReviewBackend(Protocol):
    async def review(self, artifact: MediaArtifact, request: MediaRequest) -> MediaReviewObservation: ...
