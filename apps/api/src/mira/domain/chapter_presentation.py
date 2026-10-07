"""Read-only, bounded UI projection of the authoritative fictional chapter.

This cache cannot grant a role, execute a transition, or authorize memory access.
The story reducer remains the only authority. No authored text crosses this DTO.
"""
from dataclasses import dataclass, fields
import re


CHAPTER_STAGES = frozenset(('stranger_cafe', 'recognized', 'old_friend_story',
    'photo_promise', 'photo_previewed', 'gift_offered', 'gift_declined', 'completed'))
CHAPTER_TRANSITIONS = frozenset(('x.recognize', 'x.story', 'x.promise', 'x.preview',
    'x.gift_offer', 'x.gift_accept', 'x.gift_decline', 'x.exit'))
_UUID_TEXT = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


@dataclass(frozen=True, slots=True)
class ChapterChoice:
    choice: str
    offer_id: str
    offer_effect_id: str
    offer_effect_digest: str

    def __post_init__(self):
        if (self.choice not in ('accept', 'decline') or type(self.offer_id) is not str
                or not 0 < len(self.offer_id) <= 128
                or any(ord(c) < 33 or ord(c) == 127 for c in self.offer_id)
                or type(self.offer_effect_digest) is not str
                or re.fullmatch(r'[a-f0-9]{64}', self.offer_effect_digest) is None):
            raise ValueError('chapter_choice_invalid')
        if type(self.offer_effect_id) is not str or re.fullmatch(_UUID_TEXT, self.offer_effect_id) is None:
            raise ValueError('chapter_choice_invalid')

    @property
    def text(self):
        return '我收下这张照片' if self.choice == 'accept' else '暂时不收照片'


@dataclass(frozen=True, slots=True)
class ChapterPresentation:
    schema: str
    source_hash: str
    stage: str
    role_active: bool
    role_name: str | None
    active_gift_offer_id: str | None
    gift_offer_effect_id: str | None
    gift_offer_effect_digest: str | None
    pending_transition: str | None
    completed: bool
    revision: int
    suspended: bool

    def __post_init__(self):
        if (self.schema != 'mira.xiahe-chapter.v1' or self.stage not in CHAPTER_STAGES
                or self.pending_transition not in CHAPTER_TRANSITIONS | {None}
                or any(type(v) is not bool for v in (self.role_active, self.completed, self.suspended))
                or type(self.revision) is not int or self.revision < 0
                or self.role_name != ('夏禾' if self.role_active else None)):
            raise ValueError('chapter_presentation_invalid')
        for name, digest in (('source', self.source_hash), ('effect', self.gift_offer_effect_digest)):
            if name == 'effect' and digest is None:
                continue
            if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
                raise ValueError('chapter_presentation_digest_invalid')
        if self.active_gift_offer_id is not None and (type(self.active_gift_offer_id) is not str
                or not 0 < len(self.active_gift_offer_id) <= 128
                or any(ord(c) < 33 or ord(c) == 127 for c in self.active_gift_offer_id)):
            raise ValueError('chapter_presentation_offer_invalid')
        if (self.gift_offer_effect_id is None) != (self.gift_offer_effect_digest is None):
            raise ValueError('chapter_presentation_effect_incomplete')
        if self.gift_offer_effect_id is not None:
            if type(self.gift_offer_effect_id) is not str:
                raise ValueError('chapter_presentation_effect_invalid')
            if re.fullmatch(_UUID_TEXT, self.gift_offer_effect_id) is None:
                raise ValueError('chapter_presentation_effect_invalid')


def chapter_presentation(projection):
    if projection is None:
        return None
    if type(projection) is not dict:
        raise ValueError('chapter_presentation_invalid')
    try:
        return ChapterPresentation(**{field.name: projection[field.name]
                                     for field in fields(ChapterPresentation)})
    except KeyError as error:
        raise ValueError('chapter_presentation_field_missing') from error
