"""Actual Actor grants/receipts drive a bounded story; synthetic ports only."""
import asyncio
import json
from uuid import uuid4

from mira.application.actor_story import SessionCharacterRuntime
from mira.application.story import StoryRuntime
from mira.application.contracts import (CandidateRange,EffectProposal,ReviewObservation,ReviewVerdict,
    CharacterSemanticEvidence,CharacterSemanticValue as V)
from mira.application.decision_contracts import evidence_digest
from mira.application.session_actor import SessionActor,RuntimeLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.generation.codex_support.character_payload import offered_id
from mira.domain.models import SessionState,EffectKind,Receipt
from mira.domain.story import (StoryDefinition,StoryGraph,CanonRevision,CanonEntry,StoryNode,
    ReadinessCatalog,CapabilityRecord,CapabilityState,OfferStatus)


def _run(coroutine):
    # Keep pytest-asyncio's policy loop owned by its fixture lifecycle.
    with asyncio.Runner(loop_factory=asyncio.new_event_loop) as runner:
        return runner.run(coroutine)


def definition():
    return StoryDefinition(StoryGraph('rain','graph',1,tuple(StoryNode),StoryNode.CAFE_CHAT,'a'*64),
        CanonRevision('rain',1,(CanonEntry('canon.identity','inherited_canonical','inherited_canonical',
            'MIRA is an adult fictional photographer.','identity'),),content_hash='b'*64))


class Generation:
    def __init__(self):self.contexts=[]
    async def generate(self,context):
        self.contexts.append(context)
        if context.user_text=='offer':
            text='一起看看窗外的雨吗？'
            proposal={'transition_id':'t.offer','signal':'offer_rain','offer_id':offered_id(context),'draft_cue':text}
        elif context.user_text=='yes':
            text='那我换上雨衣。'
            proposal={'transition_id':'t.yes','signal':'accept_raincoat','offer_id':context.character_story.active_offer_id,
                'target_capabilities':['mira.outfit.amber_raincoat']}
        else:text='那我们留在室内聊。';proposal={'transition_id':'t.chat','signal':'chat'}
        yield CandidateRange((EffectProposal(EffectKind.SUBTITLE,text),),'synthetic',
            story_proposal_json=json.dumps(proposal,ensure_ascii=False))


class Review:
    def __init__(self,uncertain=False):self.contexts=[];self.uncertain=uncertain
    async def review(self,context,candidate):
        self.contexts.append(context)
        evidence=CharacterSemanticEvidence(evidence_digest(context),evidence_digest(candidate),
            relevance=V.YES,willingness=V.YES if context.user_text=='yes' else V.UNKNOWN,
            refusal=V.YES if context.user_text=='no' else V.NO)
        if self.uncertain:evidence=None
        return ReviewObservation(ReviewVerdict.ALLOW,'synthetic',character_evidence=evidence)


def setup(*,ready=True,uncertain=False):
    runtime=StoryRuntime(definition(),'synthetic-scope')
    catalog=ReadinessCatalog('synthetic-ready',(
        CapabilityRecord('mira.outfit.amber_raincoat',CapabilityState.READY,'test-assets',
            ('outer.amber','inner.cream'),'synthetic-proof'),)) if ready else ReadinessCatalog('not-ready')
    character=SessionCharacterRuntime(runtime,catalog)
    generation=Generation();review=Review(uncertain)
    actor=SessionActor(SessionState(str(uuid4()),str(uuid4())),generation,review,MemoryEventJournal(100),
        RuntimeLimits(3,10,30),character_runtime=character)
    return actor,character,generation,review


async def turn(actor,text,activity,cutoff=0):
    await actor.submit(request_id=str(uuid4()),activity_seq=activity,cutoff=cutoff,text=text)
    async with asyncio.timeout(2):
        while True:
            state=await actor.snapshot()
            if state.sealed or state.last_error:return state
            await asyncio.sleep(.002)


async def acknowledge(actor,effect,seq):
    return await actor.receipt(Receipt(effect.id,effect.digest,effect.output_epoch,effect.activity_seq,seq))


def test_offer_visible_then_barge_stop_then_yes_changes_outfit_only_after_receipt():
    async def run():
        actor,character,generation,review=setup()
        try:
            first=await turn(actor,'offer',1)
            assert first.sealed and character.runtime.story.node is StoryNode.CAFE_CHAT
            assert generation.contexts[0].character_story==review.contexts[0].character_story
            await acknowledge(actor,first.active_grants[0],1)
            assert character.runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
            await actor.stop(activity_seq=2,cutoff=1)
            assert character.runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
            second=await turn(actor,'yes',3,1)
            assert second.sealed,second.last_error
            outfit=next(e for e in second.active_grants if e.value=='outfit_amber_raincoat')
            assert character.runtime.story.current_outfit=='black_jacket'
            # Preserve causal receipt sequence for every prior visible effect.
            subtitle=next(e for e in second.active_grants if e.kind is EffectKind.SUBTITLE)
            await acknowledge(actor,subtitle,2)
            await acknowledge(actor,outfit,3)
            assert character.runtime.story.node is StoryNode.RAIN_VIEW
            assert character.runtime.story.current_outfit=='amber_raincoat'
            assert len(character.runtime.story.episodes)==1
            await acknowledge(actor,outfit,3)
            assert len(character.runtime.story.episodes)==1
            await actor.stop(activity_seq=4,cutoff=3)
            assert character.runtime.story.node is StoryNode.RAIN_VIEW
        finally:await actor.close()
    _run(run())


def test_explicit_no_closes_visible_offer_without_relationship_penalty():
    async def run():
        actor,character,_,_=setup()
        try:
            first=await turn(actor,'offer',1);await acknowledge(actor,first.active_grants[0],1)
            second=await turn(actor,'no',2,1)
            assert second.sealed
            assert character.runtime.story.node is StoryNode.CAFE_CHAT
            assert character.runtime.story.offer_status is OfferStatus.DECLINED
            assert character.runtime.story.relationship_delta==0
            assert all(not e.value.startswith('outfit_') for e in second.active_grants)
        finally:await actor.close()
    _run(run())


def test_unready_assets_and_missing_semantic_evidence_never_grant_outfit():
    async def run():
        actor,character,_,_=setup(ready=False)
        try:
            first=await turn(actor,'offer',1);await acknowledge(actor,first.active_grants[0],1)
            second=await turn(actor,'yes',2,1)
            assert not second.active_grants and character.runtime.story.current_outfit=='black_jacket'
        finally:await actor.close()
        actor,character,_,_=setup(uncertain=True)
        try:
            state=await turn(actor,'offer',1)
            assert state.last_error=='review_uncertain' and not state.active_grants
            assert character.runtime.story.node is StoryNode.CAFE_CHAT
        finally:await actor.close()
    _run(run())
