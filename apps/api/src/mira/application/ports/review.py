from typing import Protocol

from mira.application.contracts import CandidateRange, GenerationContext, ReviewObservation


class ReviewBackend(Protocol):
    async def review(
        self, context: GenerationContext, candidate: CandidateRange
    ) -> ReviewObservation:
        """Return an observation, never mutate state or issue presentation permits."""
        ...


class DisabledReviewBackend:
    """Explicit disabled legacy port: never approves a native action or dialogue."""
    async def review(self, context, candidate):
        from mira.domain.errors import DomainError
        raise DomainError('review_unavailable','Legacy review is disabled in native tool mode.')
