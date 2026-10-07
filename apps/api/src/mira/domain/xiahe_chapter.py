"""Finite authored roleplay, independent of identity and the optional rain loop.

Only typed proposals can stage work. Completion needs an exact issued effect
receipt; a line of generated dialogue is never a chapter fact.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import hashlib
import json
import re

CHAPTER_SCHEMA = 'mira.xiahe-chapter.v1'
CHAPTER_REVISION = 'xiahe-chapter-v1'
ROLE_NAME = '夏禾'
CHAPTER_SCENES = {
    'x.recognize': 'xiahe_recognition',
    'x.gift_offer': 'xiahe_gift_offer',
    'x.gift_accept': 'xiahe_photo_handover',
}
CHAPTER_CAPABILITIES = {
    'xiahe_recognition': 'chapter.xiahe.recognition',
    'xiahe_gift_offer': 'chapter.xiahe.gift_offer',
    'xiahe_photo_handover': 'chapter.xiahe.photo_handover',
}
CHAPTER_ASSETS = {
    'xiahe_recognition': 'chapter.recognition.composition',
    'xiahe_gift_offer': 'chapter.gift_offer.composition',
    'xiahe_photo_handover': 'chapter.photo_handover.composition',
}
CHAPTER_TRANSITIONS = frozenset((*CHAPTER_SCENES, 'x.story', 'x.promise',
    'x.gift_decline', 'x.exit'))
# These are existing author-created story sources, not acquired user memories.
CHAPTER_CANON = (
    ('old_friend', 'chapter.xiahe.canon.contact_sheet',
     '有一次我们在这家店摊开一桌试印，我每张都想重选。你把它们按明暗排成一排，问我：哪张让你想起按快门的那一秒？我才发现自己一直盯着小缺点。'),
    ('old_friend_2', 'chapter.xiahe.canon.electronic_copy',
     '海边那次是我一个人去的，回来后把灯塔电子版发给你。我先解释风怎么把背带吹到镜头前，你却先问雨后的海是什么味道。我讲了半天湿石头，才想起来还没说照片。'),
    ('old_friend_3', 'chapter.xiahe.canon.unfinished_print',
     '后来我们在这儿看纸样，你说可以留一点不完美，我嘴上答应，还是把照片塞回纸袋，说再选一次。你没有催，只替我把杯子挪远了，怕咖啡洒上去。那一点体贴，我一直记得。'),
    ('photo_promise', 'canon.photo_promise',
     '旅行前我答应给你一张洗出来的旅行照片。电子版早发过，纸质照片却被我借口还想再选一张，拖了很久。今晚想正式把选好的灯塔照片交给你。'),
)
CHAPTER_SOURCE_HASH = hashlib.sha256(json.dumps({'schema': CHAPTER_SCHEMA,
    'canon': CHAPTER_CANON, 'scenes': CHAPTER_SCENES}, ensure_ascii=False,
    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ChapterStage(StrEnum):
    STRANGER = 'stranger_cafe'
    RECOGNIZED = 'recognized'
    OLD_FRIEND = 'old_friend_story'
    PROMISE = 'photo_promise'
    PREVIEWED = 'photo_previewed'
    GIFT_OFFERED = 'gift_offered'
    GIFT_DECLINED = 'gift_declined'
    COMPLETED = 'completed'


@dataclass(frozen=True, slots=True)
class ChapterInputAct:
    kind: str
    evidence_text: str
    role_name: str = ROLE_NAME

    def __post_init__(self):
        if (self.kind not in {'claim_role', 'exit_role', 'reopen_gift', 'reopen_rain', 'accept_gift', 'decline_gift'}
                or self.role_name != ROLE_NAME or type(self.evidence_text) is not str
                or not 0 < len(self.evidence_text) <= 500):
            raise ValueError('chapter input act is not an explicit bounded fictional role act')


@dataclass(frozen=True, slots=True)
class NativeChapterAct:
    """Model-typed fictional act whose exact reliable origin was checked by Actor.

    Semantic interpretation remains Luna's. This is no real identity or memory
    authority and contains no persisted authentication or user profile state.
    """
    kind: str
    evidence_text: str
    input_id: str
    epoch: int
    offer_effect_id: str | None = None

    def __post_init__(self):
        if (self.kind not in {'claim_role','exit_role','reopen_gift','reopen_accept_gift','accept_gift','decline_gift'}
                or type(self.evidence_text) is not str or not 0<len(self.evidence_text)<=500
                or type(self.input_id) is not str or not 0<len(self.input_id)<=128
                or type(self.epoch) is not int or self.epoch<0):
            raise ValueError('invalid native fictional act')
        if self.offer_effect_id is not None and (type(self.offer_effect_id) is not str
                or not 0 < len(self.offer_effect_id) <= 128):
            raise ValueError('invalid native offer reference')


def parse_input_act(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'kind', 'evidence_text', 'role_name'}:
        raise ValueError('invalid chapter input act')
    return ChapterInputAct(**value)


def validate_input_act(act, current_text, expected_kind, *, awaited_friend=False):
    """Conservative whole-statement validation AFTER a typed model proposal.

    Names/keywords alone never invoke this function or trigger a transition.
    Ambiguous prose can be clarified in normal conversation without an action.
    """
    if (type(awaited_friend) is not bool or type(act) is not ChapterInputAct or act.kind != expected_kind
            or act.evidence_text != current_text or type(current_text) is not str):
        return False
    text = current_text.strip()
    # Quoted/reported text is data, not a current self-declaration. Mask complete
    # quote spans; reject unbalanced quotes rather than accidentally reading them.
    for left, right in (("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』"), ('"', '"'), ("'", "'")):
        pattern = re.escape(left) + '.*?' + re.escape(right)
        text = re.sub(pattern, lambda m: ' ' * len(m.group()), text, flags=re.S)
    if any(c in text for c in ('"', "'", '“', '”', '‘', '’', '「', '」', '『', '』')):
        return False
    clauses = re.split(r'([，,。！？!?；;\n])', text)
    pairs = [(clauses[i].strip(), clauses[i+1] if i+1 < len(clauses) else '')
             for i in range(0,len(clauses),2)]
    if any(marker in text for marker in ('如果','假设','要是','倘若','可能','也许','假如','假装我说',
            '台词','这句话','让我说','叫我说','引用','转述','举例','她说','他说',
            '他们说','别人说','朋友说','请跟我说','请说','骗你','开玩笑','别当真')):
        return False
    if expected_kind == 'claim_role' and re.search(r'我(?:其实)?(?:并)?不是夏禾|我不(?:再)?扮演夏禾',text):
        return False
    patterns = {
        'claim_role': r'(?:其实|对|没错|是的|好吧)?我(?:就是|是|叫|现在扮演|来扮演|在这段故事里是)夏禾(?:本人|呀|啊|呢|啦)?',
        'exit_role': r'(?:其实|更正一下|纠正一下)?(?:我(?:其实)?(?:并)?不是夏禾|我不再(?:是|扮演)夏禾|退出(?:角色扮演|剧情)|结束角色扮演|停止角色扮演|我(?:其实)?是[^夏\W]{1,12}不是夏禾)',
        'reopen_gift': r'(?:现在|这次|还是)?(?:可以把照片给我了|把照片给我吧|我想收下(?:这张)?照片|我(?:愿意|要|想)收下(?:这张)?照片|重新(?:送|给)我照片(?:吧)?)',
        'reopen_rain': r'(?:现在|这次|还是|重新)?(?:我)?(?:想|要|可以)?(?:再)?(?:看看?雨|去窗边(?:看雨)?|看看?窗外|换上?(?:那件)?雨衣|披上雨衣)(?:吧|了)?',
        'accept_gift': r'(?:好|好的|好呀|好啊|可以|行|愿意|我(?:愿意|要|想)?收下(?:这张)?(?:照片)?(?:了)?|收下(?:这张)?照片|给我吧|拿给我吧)',
        'decline_gift': r'(?:不|不要|不用|暂时不(?:要|收(?:照片)?)|我(?:现在|暂时)?不(?:想|要|愿意)?收(?:下)?(?:这张)?(?:照片)?|先不收(?:照片)?|照片你先留着吧)',
    }
    if expected_kind == 'accept_gift' and any(marker in text for marker in ('不收','不想收','不要','拒绝','先别','不用','不接受','等等','没决定',
            '再想','不是现在','晚点','不愿意','不想','还不能','以后再')):
        return False
    explicit = any(delimiter not in {'?', '？'} and re.fullmatch(patterns[expected_kind],
        re.sub(r'\s+', '', clause)) is not None for clause, delimiter in pairs)
    if explicit:
        return True
    if expected_kind != 'claim_role' or not awaited_friend:
        return False
    # This new branch matches the entire statement, not a clause lifted out of
    # reported speech, a larger question/condition or a later retraction. Only
    # bounded neutral prefaces and fixed greetings may surround the self-claim.
    indirect = (r'(?:(?:明白了|我明白了|原来如此)[，,])?'
                r'(?:(?:其实|对|没错|是的|好吧)[，,]?)?我(?:其实)?(?:就是|是)'
                r'你(?:要|在|一直在|正在)?(?:找|等|等待)的(?:那个|那位)?老朋友(?:呀|啊|呢|啦)?'
                r'(?:[，,](?:好久不见|很久没见了|好多年没见了|好几年没见面了))?[。.!！]?')
    return re.fullmatch(indirect, re.sub(r'\s+', '', current_text.strip())) is not None



@dataclass(frozen=True, slots=True)
class ChapterPending:
    transition: str
    milestone: str
    input_id: str
    epoch: int
    scope_binding: str
    grant_id: str
    offer_id: str | None = None
    cue_digest: str | None = None
    effect_id: str | None = None
    effect_digest: str | None = None

    def __post_init__(self):
        if (self.transition not in CHAPTER_TRANSITIONS | {'x.preview'}
                or self.milestone not in _MILESTONES or type(self.epoch) is not int or self.epoch < 0
                or not self.input_id or len(self.input_id) > 128 or not self.scope_binding
                or not self.grant_id):
            raise ValueError('invalid pending chapter presentation')
        if (self.effect_id is None) != (self.effect_digest is None):
            raise ValueError('chapter effect binding must be complete')
        for value in (self.effect_digest, self.cue_digest):
            if value is not None and not _digest(value):
                raise ValueError('invalid chapter effect digest')


_MILESTONES = ('recognition', 'old_friend', 'old_friend_2', 'old_friend_3', 'photo_promise', 'photo_preview', 'gift_offer', 'photo_handover')
_STAGE_BY_MILESTONE = {'recognition': ChapterStage.RECOGNIZED,
    'old_friend': ChapterStage.OLD_FRIEND, 'old_friend_2': ChapterStage.OLD_FRIEND,
    'old_friend_3': ChapterStage.OLD_FRIEND, 'photo_promise': ChapterStage.PROMISE,
    'photo_preview': ChapterStage.PREVIEWED, 'gift_offer': ChapterStage.GIFT_OFFERED,
    'photo_handover': ChapterStage.COMPLETED}
_MILESTONE_BY_TRANSITION = dict(zip(('x.recognize', 'x.story', 'x.promise', 'x.preview', 'x.gift_offer',
    'x.gift_accept'), ('recognition','old_friend','photo_promise','photo_preview','gift_offer','photo_handover')))


@dataclass(frozen=True, slots=True)
class ChapterPreviewReference:
    mode: str
    receipt_id: str
    effect_id: str
    effect_digest: str
    output_epoch: int
    activity_seq: int
    presentation_seq: int

    def __post_init__(self):
        if (self.mode not in {'new_presentation','reused_visible'}
                or not self.receipt_id or len(self.receipt_id)>256
                or not self.effect_id or len(self.effect_id)>128 or not _digest(self.effect_digest)
                or any(type(n) is not int or n<0 for n in (self.output_epoch,self.activity_seq,self.presentation_seq))):
            raise ValueError('invalid exact photo preview source')


@dataclass(frozen=True, slots=True)
class DeclinedGiftOffer:
    """A past presented invitation, never an active offer or handover receipt."""
    offer_id: str
    effect_id: str
    effect_digest: str
    receipt_id: str

    def __post_init__(self):
        if (any(type(value) is not str or not 0 < len(value) <= limit
                for value, limit in ((self.offer_id,128),(self.effect_id,128),(self.receipt_id,256)))
                or not _digest(self.effect_digest)):
            raise ValueError('invalid declined gift offer reference')


@dataclass(frozen=True, slots=True)
class ChapterState:
    schema: str = CHAPTER_SCHEMA
    source_hash: str = CHAPTER_SOURCE_HASH
    stage: ChapterStage = ChapterStage.STRANGER
    role_active: bool = False
    milestones: tuple[tuple[str, str], ...] = ()
    active_gift_offer_id: str | None = None
    gift_offer_effect_id: str | None = None
    gift_offer_effect_digest: str | None = None
    pending: ChapterPending | None = None
    revision: int = 0
    compatibility: str = 'fresh_chapter_v1'
    suspended: bool = False
    last_progress_input_id: str | None = None
    last_progress_epoch: int | None = None
    preview_reference: ChapterPreviewReference | None = None
    declined_gift_offer: DeclinedGiftOffer | None = None

    def __post_init__(self):
        if (self.schema != CHAPTER_SCHEMA or self.source_hash != CHAPTER_SOURCE_HASH
                or type(self.stage) is not ChapterStage or type(self.role_active) is not bool
                or type(self.suspended) is not bool or type(self.revision) is not int or self.revision < 0
                or self.compatibility not in {'fresh_chapter_v1', 'legacy_story_schema_3',
                    'legacy_story_schema_4', 'legacy_story_schema_5'}):
            raise ValueError('unsupported or invalid chapter state')
        if (type(self.milestones) is not tuple or len(self.milestones) > 8
                or any(type(row) is not tuple or len(row) != 2 or row[0] not in _MILESTONES
                    or type(row[1]) is not str or not row[1] or len(row[1]) > 256 for row in self.milestones)
                or len(dict(self.milestones)) != len(self.milestones)):
            raise ValueError('invalid acknowledged chapter milestones')
        if (self.last_progress_input_id is not None and (type(self.last_progress_input_id) is not str
                or not self.last_progress_input_id or len(self.last_progress_input_id)>128)
                or self.last_progress_epoch is not None and (type(self.last_progress_epoch) is not int or self.last_progress_epoch<0)
                or (self.last_progress_input_id is None)!=(self.last_progress_epoch is None)):
            raise ValueError('invalid chapter progress input binding')
        if self.preview_reference is not None and type(self.preview_reference) is not ChapterPreviewReference:
            raise ValueError("invalid chapter preview source")
        if self.declined_gift_offer is not None and type(self.declined_gift_offer) is not DeclinedGiftOffer:
            raise ValueError('invalid declined gift offer source')
        if self.pending is not None and type(self.pending) is not ChapterPending:
            raise ValueError('invalid chapter pending state')
        for value in (self.active_gift_offer_id, self.gift_offer_effect_id):
            if value is not None and (type(value) is not str or not value or len(value) > 128):
                raise ValueError('invalid chapter offer identity')
        if self.gift_offer_effect_digest is not None and not _digest(self.gift_offer_effect_digest):
            raise ValueError('invalid chapter offer digest')


def _digest(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _resting_stage(state):
    # Revoking a direct offer cannot invent an optional preview.
    done = dict(state.milestones)
    return next((_STAGE_BY_MILESTONE[name] for name in reversed(_MILESTONES[:6])
        if name in done), ChapterStage.STRANGER)


def cancel_chapter(state, *, exit_role=False, invalidate_offer=False):
    revoke_offer=(exit_role or invalidate_offer) and state.stage is ChapterStage.GIFT_OFFERED
    revoke_declined=exit_role and state.declined_gift_offer is not None
    suspend_declined=invalidate_offer and state.declined_gift_offer is not None and not state.suspended
    if state.pending is None and not revoke_offer and not revoke_declined and not suspend_declined and (not exit_role or not state.role_active):
        return state
    return replace(state, pending=None, role_active=False if exit_role else state.role_active,
        stage=_resting_stage(state) if revoke_offer else state.stage,
        active_gift_offer_id=None if exit_role or invalidate_offer else state.active_gift_offer_id,
        gift_offer_effect_id=None if exit_role or invalidate_offer else state.gift_offer_effect_id,
        gift_offer_effect_digest=None if exit_role or invalidate_offer else state.gift_offer_effect_digest,
        declined_gift_offer=None if exit_role else state.declined_gift_offer,
        suspended=True, revision=state.revision + 1)


def _reconsiderable_offer(state):
    # Stop retains this past fact, never a pending grant. Only a newly bound
    # reopen_accept_gift can use it to clear suspension and stage new work.
    reference = state.declined_gift_offer
    return reference if (reference is not None and state.role_active
        and state.stage is ChapterStage.GIFT_DECLINED
        and dict(state.milestones).get('gift_offer') == reference.receipt_id) else None


def stage_chapter(state, *, transition, input_id, epoch, user_text, input_act=None,
                  offer_id=None, draft_cue=None, reviewed=False, relevant=False,
                  willingness='UNKNOWN', refusal=False, ready=False, scope_binding,
                  awaited_friend=False, native_act=None, recognition_effect_id=None):
    def current_act(expected):
        if native_act is not None:
            return (type(native_act) is NativeChapterAct and native_act.kind==expected
                and (native_act.input_id,native_act.epoch,native_act.evidence_text)==(input_id,epoch,user_text))
        return validate_input_act(input_act,user_text,expected,awaited_friend=awaited_friend)
    if transition == 'x.exit':
        return cancel_chapter(state, exit_role=True) if current_act('exit_role') else state
    if transition not in _MILESTONE_BY_TRANSITION and transition != 'x.gift_decline':
        return state
    same_input = (input_id,epoch)==(state.last_progress_input_id,state.last_progress_epoch)
    recognition_offer = (transition == 'x.gift_offer' and same_input
        and type(recognition_effect_id) is str and bool(recognition_effect_id)
        and state.role_active and state.stage is ChapterStage.RECOGNIZED
        and not state.suspended and dict(state.milestones).get('recognition','').startswith(
            'visual.'+recognition_effect_id+'.'))
    if recognition_effect_id is not None and not recognition_offer:
        return state
    if state.pending is not None or same_input and not recognition_offer:
        return state
    if transition == 'x.recognize':
        # Recognition is a current role declaration, not a JEV relevance test.
        if state.role_active or not (current_act('claim_role') if native_act is not None else validate_input_act(input_act, user_text, 'claim_role',
                awaited_friend=awaited_friend is True and state.stage is ChapterStage.STRANGER
                    and not state.suspended and not state.milestones)):
            return state
    elif not state.role_active:
        return state
    done = dict(state.milestones)
    if transition == 'x.gift_decline':
        if state.stage is ChapterStage.GIFT_OFFERED and offer_id == state.active_gift_offer_id and current_act('decline_gift'):
            reference = (DeclinedGiftOffer(offer_id,state.gift_offer_effect_id,
                state.gift_offer_effect_digest,done['gift_offer'])
                if offer_id and state.gift_offer_effect_id and state.gift_offer_effect_digest
                    and 'gift_offer' in done else None)
            return replace(state, stage=ChapterStage.GIFT_DECLINED, active_gift_offer_id=None,
                gift_offer_effect_id=None, gift_offer_effect_digest=None, declined_gift_offer=reference,
                revision=state.revision + 1)
        return state
    required = {'x.story': 'recognition', 'x.promise': 'recognition', 'x.preview': 'recognition',
        'x.gift_offer': 'recognition', 'x.gift_accept': 'gift_offer'}.get(transition)
    milestone = _MILESTONE_BY_TRANSITION[transition]
    if transition == 'x.story':
        milestone = next((name for name in ('old_friend','old_friend_2','old_friend_3') if name not in done), 'old_friend_3')
    if required and required not in done:
        return state
    if milestone in done and transition not in {'x.recognize', 'x.gift_offer'}:
        return state
    if transition == 'x.gift_offer':
        if not offer_id or state.stage is ChapterStage.COMPLETED:
            return state
        if state.stage is ChapterStage.GIFT_OFFERED:
            return state
        if (state.stage is ChapterStage.GIFT_DECLINED or state.suspended) and not current_act('reopen_gift'):
            return state
    if transition == 'x.gift_accept':
        reference = _reconsiderable_offer(state)
        reconsider = (current_act('reopen_accept_gift') and reference is not None
            and offer_id == reference.offer_id and native_act.offer_effect_id == reference.effect_id)
        current = (state.stage is ChapterStage.GIFT_OFFERED and bool(offer_id)
            and offer_id == state.active_gift_offer_id and current_act('accept_gift'))
        if not current and not reconsider:
            return state
    if not ready:
        return state
    if (transition in {'x.story', 'x.promise'} or recognition_offer) and (type(draft_cue) is not str or not 0 < len(draft_cue) <= 500):
        return state
    cue = hashlib.sha256(draft_cue.encode()).hexdigest() if transition in {'x.story', 'x.promise'} or recognition_offer else None
    grant = 'chapter.' + hashlib.sha256(f'{scope_binding}|{input_id}|{epoch}|{transition}|{state.revision}'.encode()).hexdigest()[:24]
    return replace(state, pending=ChapterPending(transition, milestone, input_id, epoch,
        scope_binding, grant, offer_id, cue), last_progress_input_id=input_id,last_progress_epoch=epoch,
        suspended=False if (transition == 'x.gift_offer' and current_act('reopen_gift')
            or transition == 'x.gift_accept' and current_act('reopen_accept_gift')) else state.suspended,
        revision=state.revision + 1)


def bind_chapter_effect(state, *, effect_id, digest, epoch):
    p = state.pending
    if p is None or p.epoch != epoch or not effect_id or len(effect_id) > 128 or not _digest(digest):
        raise ValueError('chapter effect has no exact current staged presentation')
    return replace(state, pending=replace(p, effect_id=effect_id, effect_digest=digest), revision=state.revision + 1)


def acknowledge_chapter(state, *, receipt_id, effect_id, digest, epoch, scope_binding):
    p = state.pending
    if (p is None or (p.effect_id, p.effect_digest, p.epoch, p.scope_binding) !=
            (effect_id, digest, epoch, scope_binding) or not receipt_id):
        return state
    milestones = dict(state.milestones)
    milestones[p.milestone] = receipt_id
    # A new role affirmation never rewinds an acknowledged later chapter beat.
    stage = (_STAGE_BY_MILESTONE[p.milestone] if p.milestone != 'recognition'
        or state.stage is ChapterStage.STRANGER else state.stage)
    if p.milestone in {'old_friend','old_friend_2','old_friend_3','photo_promise','photo_preview'}:
        stage = state.stage if state.stage in {ChapterStage.GIFT_OFFERED,
            ChapterStage.GIFT_DECLINED,ChapterStage.COMPLETED} else stage
    return replace(state, pending=None, role_active=True, stage=stage,
        milestones=tuple((name, milestones[name]) for name in _MILESTONES if name in milestones),
        active_gift_offer_id=p.offer_id if p.milestone == 'gift_offer' else state.active_gift_offer_id,
        gift_offer_effect_id=effect_id if p.milestone == 'gift_offer' else state.gift_offer_effect_id,
        gift_offer_effect_digest=digest if p.milestone == 'gift_offer' else state.gift_offer_effect_digest,
        declined_gift_offer=None if p.milestone in {'gift_offer','photo_handover'} else state.declined_gift_offer,
        revision=state.revision + 1)


def reuse_visible_preview(state, reference, *, input_id, epoch):
    """New explicit viewing intent can cite an existing actual visible receipt.

    It records a causal reuse, not a new presentation or a gift. The application
    must validate visibility and exact Actor receipt identity before calling.
    """
    if (type(reference) is not ChapterPreviewReference or reference.mode!='reused_visible'
            or not state.role_active or state.pending is not None
            or 'recognition' not in dict(state.milestones)
            or 'photo_preview' in dict(state.milestones)
            or (input_id,epoch)==(state.last_progress_input_id,state.last_progress_epoch)):
        return state
    milestones=dict(state.milestones);milestones['photo_preview']=reference.receipt_id
    return replace(state,stage=state.stage if state.stage in {ChapterStage.GIFT_OFFERED,
        ChapterStage.GIFT_DECLINED,ChapterStage.COMPLETED} else ChapterStage.PREVIEWED,preview_reference=reference,
        milestones=tuple((key,milestones[key]) for key in _MILESTONES if key in milestones),
        last_progress_input_id=input_id,last_progress_epoch=epoch,revision=state.revision+1)


def chapter_to_dict(state):
    value = asdict(state)
    value['stage'] = state.stage.value
    return value


def chapter_from_dict(value):
    fields = set(ChapterState.__dataclass_fields__)
    if type(value) is not dict or set(value) not in (fields, fields - {'declined_gift_offer'}):
        raise ValueError('unsupported chapter checkpoint schema')
    data = dict(value)
    data['stage'] = ChapterStage(data['stage'])
    data['milestones'] = tuple(tuple(row) for row in data['milestones'])
    data['pending'] = ChapterPending(**data['pending']) if data['pending'] else None
    data['preview_reference'] = ChapterPreviewReference(**data['preview_reference']) if data['preview_reference'] else None
    reference = data.get('declined_gift_offer')
    data['declined_gift_offer'] = DeclinedGiftOffer(**reference) if reference is not None else None
    return ChapterState(**data)


def chapter_is_dormant(state):
    """Preserve legacy request bytes until this additive chapter has actual state.

    The typed default still exists. Ordinary old rain-loop turns do not add an
    unrelated chapter envelope to their tightly bounded semantic review wire.
    """
    return (state.stage is ChapterStage.STRANGER and not state.role_active
        and not state.milestones and state.pending is None and state.revision == 0
        and not state.suspended and state.last_progress_input_id is None)


def chapter_projection(state):
    done = dict(state.milestones)
    if not state.role_active:
        allowed = ['x.recognize', 'x.exit']
    elif state.stage is ChapterStage.COMPLETED:
        allowed = ['x.exit']
    elif state.stage is ChapterStage.GIFT_OFFERED:
        allowed = ['x.gift_accept', 'x.gift_decline', 'x.exit']
    else:
        allowed = ['x.gift_offer']
        if _reconsiderable_offer(state) is not None: allowed.append('x.gift_accept')
        if 'old_friend_3' not in done: allowed.append('x.story')
        if 'photo_promise' not in done: allowed.append('x.promise')
        allowed.extend(('show_photo','x.exit'))
    next_canon = []
    if state.role_active:
        next_beat = next((name for name in ('old_friend','old_friend_2','old_friend_3','photo_promise')
            if name not in done), None)
        next_canon = [dict(beat=beat, source_id=source, text=text, source='authored_backstory',
            source_revision=1, author_created=True, is_real_user_fact=False,
            is_real_shared_history=False) for beat, source, text in CHAPTER_CANON if beat == next_beat]
    return {'schema': state.schema, 'source_hash': state.source_hash, 'stage': state.stage.value,
        'role_name': ROLE_NAME if state.role_active else None, 'role_active': state.role_active,
        'allowed_next': allowed,
        'active_gift_offer_id': state.active_gift_offer_id,
        'gift_offer_effect_id': state.gift_offer_effect_id,
        'gift_offer_effect_digest': state.gift_offer_effect_digest,
        'declined_gift_offer': asdict(reference) if (reference := _reconsiderable_offer(state)) else None,
        'acknowledged_milestones': [list(row) for row in state.milestones],
        'pending_transition': state.pending.transition if state.pending else None,
        'completed': state.stage is ChapterStage.COMPLETED,
        **({'ending_scope': 'receipt_backed_fictional_software_photo_handover_not_physical_delivery'}
            if state.stage is ChapterStage.COMPLETED else {}),
        'author_canon_for_current_beat': next_canon,
        **({'photo_preview_source':asdict(state.preview_reference)} if state.preview_reference else {}),
        'compatibility': state.compatibility, 'suspended': state.suspended,
        'revision': state.revision}
