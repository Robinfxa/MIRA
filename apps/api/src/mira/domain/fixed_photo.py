"""Bounded authored-photo feedback, never an authority or presentation receipt."""
from dataclasses import dataclass
from typing import Literal

FixedPhotoState = Literal['idle','pending','held','granted','preparing','receipt_pending','presented','failed','cancelled','dismissed']
FixedPhotoReason = Literal['unavailable','already_visible','dismissed','review_unknown','review_rejected','review_failed','optional_ineligible','preparation_failed','presentation_failed','receipt_unconfirmed','cancelled']
FIXED_PHOTO_STATES = ('idle','pending','held','granted','preparing','receipt_pending','presented','failed','cancelled','dismissed')
FIXED_PHOTO_REASONS = ('unavailable','already_visible','dismissed','review_unknown','review_rejected','review_failed','optional_ineligible','preparation_failed','presentation_failed','receipt_unconfirmed','cancelled')
FIXED_PHOTO_PENDING = ('pending','granted','preparing','receipt_pending')

@dataclass(frozen=True, slots=True)
class FixedPhotoStatus:
    state: FixedPhotoState = 'idle'
    reason: FixedPhotoReason | None = None
    attempt_seq: int = 0
    output_epoch: int = 0
    activity_seq: int = 0
    effect_id: str | None = None

    def __post_init__(self):
        if (self.state not in FIXED_PHOTO_STATES or self.reason is not None and self.reason not in FIXED_PHOTO_REASONS
                or any(type(n) is not int or n < 0 for n in (self.attempt_seq,self.output_epoch,self.activity_seq))):
            raise ValueError('invalid fixed photo status')
