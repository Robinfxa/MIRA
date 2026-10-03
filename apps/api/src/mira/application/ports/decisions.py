"""Input interpretation is evidence, never state mutation or an execution permit."""
from typing import Protocol

from mira.application.decision_contracts import DecisionSnapshot, InputDecisionObservation


class InputDecisionBackend(Protocol):
    async def observe(self, snapshot: DecisionSnapshot) -> InputDecisionObservation:
        """Observe exact immutable input facts; explicit local Stop never waits here."""
        ...
