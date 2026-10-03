import asyncio
from dataclasses import replace

import pytest

from mira.adapters.generation.mock import FIXTURES, MockGenerationBackend
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.contracts import CandidateRange, ReviewObservation, ReviewVerdict
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.models import Phase, Receipt, SessionState
from mira.domain.errors import DomainError


def actor(generation=None, review=None, timeout=1, max_turns=64):
    return SessionActor(SessionState("s","c"),generation or MockGenerationBackend(0),
                        review or FixtureReviewBackend(),MemoryEventJournal(100),
                        RuntimeLimits(timeout,max_turns,128))


async def wait_for(value, predicate):
    async with asyncio.timeout(2):
        while True:
            state=await value.snapshot()
            if predicate(state): return state
            await asyncio.sleep(0.002)


@pytest.mark.asyncio
async def test_mock_ranges_are_reviewed_and_sealed_but_not_presented():
    value=actor()
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="看照片")
    state=await wait_for(value,lambda s:s.sealed)
    assert len(state.active_grants)==2 and state.receipts==()
    assert state.phase==Phase.READY
    await value.close()


@pytest.mark.asyncio
async def test_uncooperative_provider_result_cannot_revive_stop():
    entered=asyncio.Event();release=asyncio.Event()
    class Uncooperative:
        async def generate(self,context):
            entered.set()
            try: await release.wait()
            except asyncio.CancelledError: await release.wait()
            yield CandidateRange(FIXTURES["hello"],"hello")
    value=actor(Uncooperative())
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    await entered.wait()
    stopped=await value.stop(activity_seq=2,cutoff=0)
    release.set();await asyncio.sleep(.02)
    state=await value.snapshot()
    assert state==stopped and not state.active_grants
    await value.close()


@pytest.mark.asyncio
async def test_stop_is_not_waiting_for_model_completion():
    entered=asyncio.Event()
    class Blocked:
        async def generate(self,context):
            entered.set();await asyncio.sleep(60)
            yield CandidateRange(FIXTURES["hello"],"hello")
    value=actor(Blocked())
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    await entered.wait()
    async with asyncio.timeout(.2): state=await value.stop(activity_seq=2,cutoff=0)
    assert state.phase==Phase.STOPPED
    await value.close()


@pytest.mark.asyncio
async def test_rejected_candidate_never_gets_permit():
    class Reject:
        async def review(self,context,candidate):
            return ReviewObservation(ReviewVerdict.REJECT,"test_reject")
    value=actor(review=Reject())
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    state=await wait_for(value,lambda s:s.phase==Phase.ERROR)
    assert state.active_grants==() and state.last_error=="review_not_allowed"
    await value.close()


@pytest.mark.asyncio
async def test_unknown_review_never_defaults_to_allow():
    class Unknown:
        async def review(self,context,candidate):
            return ReviewObservation(ReviewVerdict.UNKNOWN,"unknown")
    value=actor(review=Unknown())
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    state=await wait_for(value,lambda s:s.phase==Phase.ERROR)
    assert state.issued_effects==()
    await value.close()


@pytest.mark.asyncio
async def test_empty_generation_not_quiet_success():
    class Empty:
        async def generate(self,context):
            if False: yield
    value=actor(Empty())
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    state=await wait_for(value,lambda s:s.phase==Phase.ERROR)
    assert state.last_error=="empty_generation"
    await value.close()


@pytest.mark.asyncio
async def test_timeout_not_normal_seal():
    value=actor(MockGenerationBackend(1000),timeout=.01)
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    state=await wait_for(value,lambda s:s.phase==Phase.ERROR)
    assert not state.sealed and state.last_error=="generation_timeout"
    await value.close()


@pytest.mark.asyncio
async def test_request_idempotence_does_not_reopen_after_stop():
    value=actor()
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    stopped=await value.stop(activity_seq=2,cutoff=0)
    retried=await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    assert retried==stopped
    await value.close()


@pytest.mark.asyncio
async def test_request_conflict_detected():
    value=actor()
    await value.submit(request_id="r",activity_seq=1,cutoff=0,text="hello")
    with pytest.raises(DomainError,match="reused"):
        await value.submit(request_id="r",activity_seq=2,cutoff=0,text="different")
    await value.close()


@pytest.mark.asyncio
async def test_context_contains_only_receipted_assistant_effects():
    contexts=[]
    class Capture:
        async def generate(self,context):
            contexts.append(context)
            yield CandidateRange(FIXTURES["hello"],"hello")
    value=actor(Capture())
    await value.submit(request_id="r1",activity_seq=1,cutoff=0,text="one")
    first=await wait_for(value,lambda s:s.sealed)
    await value.submit(request_id="r2",activity_seq=2,cutoff=0,text="two")
    await wait_for(value,lambda s:s.sealed and s.output_epoch==2)
    assert contexts[1].presented_effects==()
    await value.close()


@pytest.mark.asyncio
async def test_budget_is_bounded():
    value=actor(max_turns=1)
    await value.submit(request_id="r1",activity_seq=1,cutoff=0,text="one")
    with pytest.raises(DomainError,match="budget"):
        await value.submit(request_id="r2",activity_seq=2,cutoff=0,text="two")
    await value.close()


@pytest.mark.asyncio
async def test_later_review_observes_accepted_not_yet_presented_prefix():
    observed=[]
    class CaptureReview:
        async def review(self,context,candidate):
            observed.append(context)
            return ReviewObservation(ReviewVerdict.ALLOW,"test")
    value=actor(review=CaptureReview())
    await value.submit(request_id="r1",activity_seq=1,cutoff=0,text="看照片")
    await wait_for(value,lambda s:s.sealed)
    assert len(observed)==2
    assert len(observed[1].accepted_prefix)==1
    assert observed[1].presented_effects==()
    await value.close()
