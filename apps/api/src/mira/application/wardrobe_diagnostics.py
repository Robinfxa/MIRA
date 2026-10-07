"""Closed local wardrobe metadata, never generation/review facts or authority."""
from dataclasses import dataclass

WARDROBE_CONTROLS = ('outfit_black_jacket', 'outfit_cream_inner_only', 'outfit_amber_raincoat')
_STATES = {
    'context': ('initial', 'acknowledged'),
    'candidate': ('absent', 'proposed'),
    'readiness': ('absent', 'ready', 'held'),
    'review': ('allowed', 'held'),
    'grant': ('granted', 'held'),
    'receipt': ('presented',),
    'cancel': ('cancelled',),
}
_REASONS = ('no_proposal', 'unavailable', 'story_compiled', 'already_current',
    'review_unknown', 'review_rejected', 'review_failed', 'context_changed',
    'optional_ineligible', 'preparation_failed', 'cancelled', 'historical_receipt')


@dataclass(frozen=True, slots=True)
class SafeWardrobeDiagnostic:
    phase: str
    state: str
    output_epoch: int
    activity_seq: int
    outfit: str | None = None
    count: int = 0
    reason: str | None = None
    acknowledged_outfit: str | None = None

    def __post_init__(self):
        if (type(self.phase) is not str or self.phase not in _STATES
                or type(self.state) is not str or self.state not in _STATES[self.phase]
                or any(type(n) is not int or not 0 <= n <= 2**53-1
                       for n in (self.output_epoch, self.activity_seq))
                or type(self.count) is not int or not 0 <= self.count <= 8
                or any(v is not None and (type(v) is not str or v not in WARDROBE_CONTROLS)
                       for v in (self.outfit, self.acknowledged_outfit))
                or self.reason is not None and (type(self.reason) is not str or self.reason not in _REASONS)
                or self.state == 'absent' and (self.count != 0 or self.outfit is not None)
                or self.phase != 'context' and self.state != 'absent'
                   and (self.outfit is None or self.count == 0)):
            raise ValueError('invalid wardrobe diagnostic')
