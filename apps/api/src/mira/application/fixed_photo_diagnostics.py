"""Closed metadata for the existing fixed illustration path; no model text or URLs."""
from dataclasses import dataclass
from mira.domain.fixed_photo import FIXED_PHOTO_STATES, FIXED_PHOTO_REASONS

@dataclass(frozen=True, slots=True)
class SafeFixedPhotoDiagnostic:
    phase: str
    state: str
    attempt_seq: int
    output_epoch: int
    activity_seq: int
    reason: str | None = None
    fixed_photo_count: int | None = None
    subtitle_count: int | None = None
    speech_count: int | None = None
    pose_count: int | None = None
    scene_count: int | None = None
    media_count: int | None = None

    def __post_init__(self):
        if (self.phase not in ('candidate','readiness','review','grant','preparation','presentation','receipt','cancel','dismiss')
                or self.state not in (*FIXED_PHOTO_STATES,'absent')
                or self.reason is not None and self.reason not in FIXED_PHOTO_REASONS
                or any(type(n) is not int or not 0 <= n <= 2**53-1 for n in
                       (self.attempt_seq,self.output_epoch,self.activity_seq))
                or any(n is not None and (type(n) is not int or not 0 <= n <= 8) for n in
                       (self.fixed_photo_count,self.subtitle_count,self.speech_count,self.pose_count,self.scene_count,self.media_count))):
            raise ValueError('invalid fixed photo diagnostic')
