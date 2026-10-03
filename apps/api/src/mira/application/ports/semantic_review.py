"""Review a complete application-owned response contract without dropping evidence."""
from typing import Protocol

from mira.application.contracts import CandidateRange, GenerationContext, ReviewObservation
from mira.application.decision_contracts import ResponseContract


class ResponseContractReviewBackend(Protocol):
    async def review_contract(self, context: GenerationContext, candidate: CandidateRange,
                              contract: ResponseContract) -> ReviewObservation:
        """Return a judgment, never permits; the Actor revalidates after the await."""
        ...
