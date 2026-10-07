"""Typed extension seams, NOT registered capabilities in the foundation build.

WP02 / WP03 must add capability checks, progress and cancellation receipts before
these ports are used. This module does not import or initialize any vendor SDK.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from mira.domain.story_images import REQUIRED_PIXEL_CHECKS, SQUARE_OUTPUT_POLICY


@dataclass(frozen=True, slots=True)
class AudioPacket:
    stream_id: str
    first_sample: int
    sample_rate_hz: int
    pcm: bytes


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes = field(repr=False)
    media_type: str
    provider: str
    model: str
    usage_units: int | None = None


@dataclass(frozen=True, slots=True)
class CanonicalImage:
    png: bytes = field(repr=False)
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class MediaArtifact:
    resource_id: str
    content_digest: str
    media_type: str
    png: bytes = field(repr=False)
    width: int
    height: int
    request_id: str
    specification_digest: str
    policy_revision: str
    provider: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class TranscriptRevision:
    input_stream_id: str
    revision: int
    text: str
    is_final: bool  # ASR final is NOT a semantic turn-complete assertion.


@dataclass(frozen=True, slots=True)
class MediaRequest:
    request_id: str
    specification: str = field(repr=False)
    allowed_resource_ids: tuple[str, ...]
    output_epoch: int
    session_id: str
    parent_request_id: str
    activity_seq: int
    photo_visibility_revision: int
    specification_digest: str
    dependency_digest: str
    canon_revision: int
    catalog_revision: str
    policy_revision: str
    admission_reference: str
    max_output_bytes: int = 8_388_608
    width: int = 1024
    height: int = 1024
    required_checks: tuple[str, ...] = REQUIRED_PIXEL_CHECKS
    output_dimension_policy: str = SQUARE_OUTPUT_POLICY


@dataclass(frozen=True, slots=True)
class PixelCheck:
    check_id: str
    result: str  # Exactly pass, fail, or unassessable; unknown values fail closed.


@dataclass(frozen=True, slots=True)
class MediaReviewObservation:
    request_id: str
    specification_digest: str
    checked_content_digest: str
    policy_revision: str
    checks: tuple[PixelCheck, ...]
    observed_description: str = field(default='',repr=False)


class CanonicalImageDecoder(Protocol):
    def canonicalize(self, data: bytes) -> CanonicalImage: ...


class SpeechRecognitionBackend(Protocol):
    def transcribe(self, packets: AsyncIterator[AudioPacket]) -> AsyncIterator[TranscriptRevision]: ...


class SpeechSynthesisBackend(Protocol):
    def synthesize(self, approved_text: str, stream_id: str) -> AsyncIterator[AudioPacket]: ...


class ImageBackend(Protocol):
    async def generate(self, request: MediaRequest) -> GeneratedImage: ...


class VisionReviewBackend(Protocol):
    async def review(self, artifact: MediaArtifact, request: MediaRequest) -> MediaReviewObservation: ...


class ImageOperationAdmissionDenied(ValueError):
    """Closed process-admission outcome, distinct from provider failures."""

    def __init__(self, reason: Literal['budget', 'busy']):
        if type(reason) is not str or reason not in ('budget', 'busy'):
            raise ValueError('invalid_image_admission_reason')
        self.reason = reason
        super().__init__('image_process_budget_exhausted' if reason == 'budget'
                         else 'image_process_busy')


class ImageOperationAdmission(Protocol):
    """Process-owned image/vision allowance; this narrow port performs no IO.

    reserve is synchronous and atomic: ImageOperationAdmissionDenied grants
    nothing and describes a budget/busy hold. Other failures remain errors. release clears
    active-operation ownership only, never refunds attempts or unknown costs.
    """
    def reserve(self, request: MediaRequest) -> None: ...
    def release(self, request_id: str) -> None: ...
