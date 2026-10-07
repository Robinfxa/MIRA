"""Original-codepoint boundary choices. These observations carry no authority."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BoundaryPlan:
    plan_id: str
    ends: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BoundaryRequest:
    text: str = field(repr=False)
    prefix_end: int
    plans: tuple[BoundaryPlan, ...]
    context_digest: str
    candidate_digest: str
    output_epoch: int


@dataclass(frozen=True, slots=True)
class BoundaryChoice:
    request_digest: str
    plan_id: str | None = None


def boundary_data(request: BoundaryRequest) -> dict:
    return asdict(request)


def boundary_digest(request: BoundaryRequest) -> str:
    return hashlib.sha256(json.dumps(boundary_data(request), ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class BoundaryBackend(Protocol):
    async def choose(self, request: BoundaryRequest) -> BoundaryChoice: ...
