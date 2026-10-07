"""Closed local facts about held suggestions; no payload or execution authority."""
from dataclasses import dataclass

OPTIONAL_HOLD_REASONS = frozenset({
    'story_proposal_invalid', 'affect_proposal_invalid', 'visual_controls_invalid', 'native_function_required',
})


@dataclass(frozen=True, slots=True)
class SafeOptionalCandidateDiagnostic:
    reasons: tuple[str, ...]
    retained_subtitle_count: int
    retained_speech_count: int
    held_control_count: int

    def __post_init__(self):
        if (type(self.reasons) is not tuple or not 1 <= len(self.reasons) <= 3
                or any(type(r) is not str or r not in OPTIONAL_HOLD_REASONS for r in self.reasons)
                or len(set(self.reasons)) != len(self.reasons)
                or any(type(n) is not int or not 0 <= n <= 8 for n in (
                    self.retained_subtitle_count, self.retained_speech_count, self.held_control_count))
                or self.retained_subtitle_count < 1 or self.retained_speech_count > 1):
            raise ValueError('invalid optional candidate diagnostic')
