"""Closed observations of actual native tool operations; never authority or payloads."""
from dataclasses import dataclass

TOOL_NAMES = frozenset(('show_photo', 'generate_story_image', 'cancel_story_image', 'set_outfit', 'set_accessory',
    'set_emotion', 'perform_action', 'set_scene', 'advance_story'))
TOOL_STATUSES = frozenset(('requested', 'held', 'pending', 'applied', 'shown', 'reused',
    'failed', 'cancelled', 'unavailable'))
TOOL_TRANSITIONS = frozenset(('x.ask_role', 'x.recognize', 'x.exit', 'x.story', 'x.promise',
    'x.gift_offer', 'x.gift_accept', 'x.gift_decline', 't.offer', 't.yes', 't.no', 't.window'))
TOOL_REASONS = frozenset(('readiness', 'current_role_question_required', 'needs_confirmation',
    'current_input_act_required', 'unexpected_input_act', 'story_cue_required', 'chapter_precondition',
    'current_offer_choice_required', 'current_offer_required', 'current_reopen_required',
    'offer_cue_required', 'story_precondition', 'precondition', 'unavailable', 'invalid_arguments',
    'call_id_conflict', 'story_unavailable', 'authority_unavailable', 'already_presented',
    'superseded', 'grant_revoked', 'dismissed', 'cancelled', 'ineligible', 'review_timeout',
    'budget', 'timeout', 'review', 'generation', 'other', 'awaiting_dialogue'))
_CHAPTER_STAGES = frozenset(('stranger_cafe', 'recognized', 'old_friend_story', 'photo_promise',
    'photo_previewed', 'gift_offered', 'gift_declined', 'completed'))
_RECEIPT_KINDS = frozenset(('subtitle', 'pose', 'scene', 'media'))


@dataclass(frozen=True, slots=True)
class SafeNativeToolDiagnostic:
    tool: str
    status: str
    output_epoch: int
    activity_seq: int
    transition: str | None = None
    reason: str | None = None
    chapter_before: str | None = None
    chapter_after: str | None = None
    role_before: bool | None = None
    role_after: bool | None = None
    receipt_kind: str | None = None

    def __post_init__(self):
        def closed(value, allowed, *, optional=False):
            return optional and value is None or type(value) is str and value in allowed
        if (not closed(self.tool, TOOL_NAMES) or not closed(self.status, TOOL_STATUSES)
                or not closed(self.transition, TOOL_TRANSITIONS, optional=True)
                or not closed(self.reason, TOOL_REASONS, optional=True)
                or not closed(self.receipt_kind, _RECEIPT_KINDS, optional=True)
                or any(type(n) is not int or not 0 <= n <= 2**53-1
                       for n in (self.output_epoch, self.activity_seq))
                or any(not closed(v, _CHAPTER_STAGES, optional=True)
                       for v in (self.chapter_before, self.chapter_after))
                or any(v is not None and type(v) is not bool for v in (self.role_before, self.role_after))
                or (self.chapter_before is None) != (self.role_before is None)
                or (self.chapter_after is None) != (self.role_after is None)
                or self.transition is not None and self.tool != 'advance_story'
                or self.receipt_kind is not None and self.status not in ('shown', 'reused')
                or self.status == 'requested' and any(v is not None
                    for v in (self.reason, self.chapter_after, self.role_after, self.receipt_kind))):
            raise ValueError('invalid native tool diagnostic')
