from mira.adapters.fixture_catalog import FIXTURES
from mira.application.contracts import (
    CandidateRange, GenerationContext, ReviewObservation, ReviewVerdict,
)


class FixtureReviewBackend:
    """Accept only exact authored mock fixtures; never enable on a live generator."""

    async def review(
        self, context: GenerationContext, candidate: CandidateRange
    ) -> ReviewObservation:
        known = FIXTURES.get(candidate.fixture_id)
        accepted = known is not None and known == candidate.effects
        return ReviewObservation(
            ReviewVerdict.ALLOW if accepted else ReviewVerdict.REJECT,
            "exact_fixture" if accepted else "not_a_fixture",
        )
