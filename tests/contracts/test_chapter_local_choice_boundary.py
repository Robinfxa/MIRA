from uuid import uuid4

import pytest

from mira.adapters.generation.mock import MockGenerationBackend
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.chapter_presentation import ChapterChoice
from mira.domain.errors import DomainError
from mira.domain.models import SessionState


@pytest.mark.asyncio
async def test_explicit_choice_without_chapter_does_not_consume_input_or_call_model():
    class MustNotGenerate(MockGenerationBackend):
        async def generate(self, context):
            raise AssertionError('invalid local choice must not open a provider')
            yield
    value = SessionActor(SessionState('session', 'client'), MustNotGenerate(0),
        FixtureReviewBackend(), MemoryEventJournal(10), RuntimeLimits(1, 20, 128))
    before = await value.snapshot()
    choice = ChapterChoice('accept', 'offer', str(uuid4()), 'a' * 64)
    with pytest.raises(DomainError) as caught:
        await value.submit(request_id='choice-one', activity_seq=1, cutoff=0,
                           text=choice.text, chapter_choice=choice)
    assert caught.value.code == 'chapter_choice_unavailable'
    assert await value.snapshot() == before
    await value.close()


def test_old_or_disabled_chapter_choice_has_closed_recoverable_error_code():
    from mira.application.diagnostic_errors import classify_failure, public_error_code
    for code in ('stale_chapter_choice', 'chapter_choice_unavailable'):
        assert public_error_code(code) == code
        assert classify_failure(DomainError(code, 'untrusted detail')).code.value == 'cancelled'
        assert 'untrusted detail' not in classify_failure(DomainError(code, 'untrusted detail')).message
