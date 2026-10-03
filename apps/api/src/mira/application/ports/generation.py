from collections.abc import AsyncIterator
from typing import Protocol

from mira.application.contracts import CandidateRange, GenerationContext


class GenerationBackend(Protocol):
    def generate(self, context: GenerationContext) -> AsyncIterator[CandidateRange]:
        """Yield complete ranges. Cancellation may be delayed; origin checks remain mandatory."""
        ...
