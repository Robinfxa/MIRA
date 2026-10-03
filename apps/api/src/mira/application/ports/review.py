from typing import Protocol

from mira.application.contracts import CandidateRange, GenerationContext, ReviewObservation


class ReviewBackend(Protocol):
    async def review(
        self, context: GenerationContext, candidate: CandidateRange
    ) -> ReviewObservation:
        """Return an observation, never mutate state or issue presentation permits."""
        ...
