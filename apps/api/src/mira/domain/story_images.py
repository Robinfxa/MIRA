"""Pure, bounded optional image intent and presentation identities. No IO."""
from dataclasses import asdict, dataclass
import json
from typing import Literal

SCHEMA = 'mira.story-image-proposal.v1'
# Requested shape remains square. This finite compatibility policy admits only
# the standard square, landscape and portrait provider output shapes.
SQUARE_OUTPUT_POLICY = 'square-1024-v1'
SUBSCRIPTION_OUTPUT_POLICY = 'subscription-native-size-v1'


def image_output_dimensions(policy: str) -> tuple[tuple[int, int], ...]:
    if type(policy) is str and policy == SQUARE_OUTPUT_POLICY:
        return ((1024, 1024),)
    if type(policy) is str and policy == SUBSCRIPTION_OUTPUT_POLICY:
        return ((1024, 1024), (1536, 1024), (1024, 1536))
    raise ValueError('image_output_policy_invalid')


POLICY_REVISION = 'mira-story-image-pixels-v1'
CATALOG_REVISION = 'mira-fiction-scenes-v1'
FICTION_BRIEF_REVISION = 'mira-fiction-brief-v1'
FICTION_BRIEF_POLICY_REVISION = 'mira-story-image-pixels-v2'
REQUIRED_PIXEL_CHECKS = ('allowed_scene', 'no_people_identity_text_documents', 'no_unreleased_disclosure', 'visually_assessable')
@dataclass(frozen=True, slots=True)
class ImageProposal:
    scene_id: str
    framing: str = 'wide'
    lighting: str = 'scene_default'
    def as_dict(self):
        return {'schema': SCHEMA, **asdict(self)}


def parse_image_proposal(value) -> ImageProposal:
    if (type(value) is not dict or set(value) != {'schema','scene_id','framing','lighting'}
            or value.get('schema') != SCHEMA or type(value.get('scene_id')) is not str
            or not (1 <= len(value['scene_id']) <= 64 and all(c in 'abcdefghijklmnopqrstuvwxyz_' for c in value['scene_id']))
            or value.get('framing') not in ('wide','detail')
            or value.get('lighting') not in ('scene_default','warm')):
        raise ValueError('image_proposal_invalid')
    return ImageProposal(value['scene_id'], value['framing'], value['lighting'])


def parse_image_proposal_json(raw: str) -> ImageProposal:
    if type(raw) is not str or len(raw.encode('utf-8')) > 1024:
        raise ValueError('image_proposal_limit')
    def pairs(items):
        result={}
        for k,v in items:
            if k in result: raise ValueError('image_proposal_duplicate')
            result[k]=v
        return result
    return parse_image_proposal(json.loads(raw, object_pairs_hook=pairs))


@dataclass(frozen=True, slots=True)
class FictionImageProposal:
    """Model-untrusted depiction data, never provider configuration or permission."""
    brief: str
    framing: str = 'wide'
    lighting: str = 'scene_default'

    def as_dict(self):
        return asdict(self)


# Reject explicit external-source syntax, not inferred topic/content categories.
# Nothing in this module resolves a location or opens a resource. Semantic scope
# still requires application scope/consent admission and independent exact pixel review.
def _has_external_reference(brief: str) -> bool:
    lower = brief.lower()
    if '://' in lower:
        return True
    for delimiter in '\"\'(':
        lower = lower.replace(delimiter, ' ')
    for word in lower.split():
        if word.startswith(('data:', 'mailto:', 'file:', 'www.', '/', '~/','~\\',
                            './', '.\\', '../', '..\\', '\\\\')):
            return True
        if (len(word) >= 3 and word[0] in 'abcdefghijklmnopqrstuvwxyz'
                and word[1] == ':' and word[2] in '/\\'):
            return True
    return False


def parse_fiction_image_proposal(value) -> FictionImageProposal:
    if (type(value) is not dict or set(value) != {'brief', 'framing', 'lighting'}
            or type(value.get('brief')) is not str
            or not 1 <= len(value['brief']) <= 600 or not value['brief'].strip()
            or any((ord(c) < 32 and c not in '\n\t') or 127 <= ord(c) <= 159
                   or 0xD800 <= ord(c) <= 0xDFFF for c in value['brief'])
            or _has_external_reference(value['brief'])
            or type(value.get('framing')) is not str or value['framing'] not in ('wide', 'detail')
            or type(value.get('lighting')) is not str or value['lighting'] not in ('scene_default', 'warm')):
        raise ValueError('image_brief_invalid')
    return FictionImageProposal(value['brief'], value['framing'], value['lighting'])


@dataclass(frozen=True, slots=True)
class FictionImageScope:
    """Actor-selected released identifiers only; no canon text or user history.

    The Actor validates release authority in its current story projection. This
    value cannot establish that authority by itself and is not model-selectable.
    """
    story_id: str
    canon_revision: int
    canon_hash: str
    released_story_events: tuple[str, ...] = ()

    def __post_init__(self):
        if (type(self.story_id) is not str or self.story_id != 'mira.rain_window.unfinished_print'
                or type(self.canon_revision) is not int or self.canon_revision < 1
                or type(self.canon_hash) is not str or len(self.canon_hash) != 64
                or any(c not in '0123456789abcdef' for c in self.canon_hash)
                or type(self.released_story_events) is not tuple or len(self.released_story_events) > 16
                or any(type(event) is not str or not 1 <= len(event) <= 128
                       or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-'
                              for c in event)
                       for event in self.released_story_events)
                or len(set(self.released_story_events)) != len(self.released_story_events)):
            raise ValueError('image_brief_scope_invalid')


def parse_generated_photo(value: str) -> tuple[str,str] | None:
    if type(value) is not str: return None
    parts=value.split(':')
    if len(parts)!=4 or parts[:2]!=['generated_story_photo','v1']:return None
    identity,digest=parts[2:]
    if (len(identity)!=36 or [i for i,c in enumerate(identity) if c=='-']!=[8,13,18,23]
            or identity[14]!='4' or identity[19] not in '89ab'
            or any(c not in '0123456789abcdef-' for c in identity)
            or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)):return None
    return identity,digest

@dataclass(frozen=True, slots=True)
class ImageIntent:
    specification: str
    specification_digest: str
    dependency_digest: str
    scene_id: str
    canon_revision: int
    canon_hash: str
    catalog_revision: str = CATALOG_REVISION
    policy_revision: str = POLICY_REVISION

@dataclass(frozen=True, slots=True)
class ImageReservation:
    request_id: str
    parent_request_id: str
    output_epoch: int
    activity_seq: int
    photo_visibility_revision: int
    specification_digest: str
    dependency_digest: str
    policy_revision: str
    session_id: str = ""
    cancellation_generation: int = 0
    consumed: bool = False
    current_effect_id: str | None = None
    qualified_resource_id: str | None = None
    qualified_content_digest: str | None = None

ImageState = Literal['unavailable','idle','held','pending','generating','reviewing','qualified','presented','failed','cancelled']

@dataclass(frozen=True, slots=True)
class StoryImageStatus:
    capability: Literal['unavailable','bounded_fiction'] = 'unavailable'
    state: ImageState = 'unavailable'
    request_id: str | None = None
    scene_id: str | None = None
    resource_id: str | None = None
    content_digest: str | None = None
    failure_code: Literal['unavailable','ineligible','budget','generation','review','timeout','cancelled'] | None = None
    completion_state: Literal['unavailable','pending','context_consumed','requested','granted','presented','failed','cancelled'] = 'unavailable'
    completion_effect_id: str | None = None
    completion_speech_effect_id: str | None = None
    completion_available: bool = False

@dataclass(frozen=True, slots=True)
class StoryImageFact:
    request_id: str
    scene_id: str
    state: ImageState
    resource_id: str | None = None
    content_digest: str | None = None
    observed_description: str | None = None
    presented_effect_id: str | None = None
    visible: bool = False
    provider: str | None = None
    model: str | None = None
    provenance: str = 'generated_visualization'
    interpretation: str = 'fallible fictional picture observation; never a real event or user memory'
