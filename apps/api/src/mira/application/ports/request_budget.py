"""Read-only view of one composition-owned irreversible provider request budget."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RequestBudgetSnapshot:
    used: int
    limit: int | None

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)


class RequestBudget(Protocol):
    """One shared request reservation counter; read-only to application/UI consumers."""
    def snapshot(self) -> RequestBudgetSnapshot: ...
