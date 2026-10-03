"""Load a bounded packaged script. This is fixture data, not an executable DSL."""
import json
from importlib.resources import files
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mira.adapters.fixture_catalog import FIXTURES

SCENARIOS = frozenset({"photo-tour", "delayed-photo", "failed-tail"})
MAX_SCRIPT_BYTES = 16 * 1024


class ReplayScriptError(ValueError):
    """Safe diagnostic with no reflected script payload."""


class ReplayStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    fixture_id: Annotated[str, Field(min_length=1, max_length=32)]
    delay_ms: Annotated[int, Field(ge=0, le=5000)] = 0


class ReplayScript(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    schema_version: Literal["1"]
    steps: Annotated[tuple[ReplayStep, ...], Field(min_length=1, max_length=8)]
    finish: Literal["complete", "fail"]

    @model_validator(mode="after")
    def check_references_and_budget(self) -> Self:
        if any(step.fixture_id not in FIXTURES for step in self.steps):
            raise ValueError("unknown fixture")
        if sum(step.delay_ms for step in self.steps) > 10_000:
            raise ValueError("script delay budget exceeded")
        return self


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def parse_script(raw: bytes) -> ReplayScript:
    """Validate all steps before generation can start, including the terminal outcome."""
    if len(raw) > MAX_SCRIPT_BYTES:
        raise ReplayScriptError("replay_script_too_large")
    try:
        # JSON parsers may otherwise accept the last duplicate key. Inspect every
        # object before schema validation, including nested fixture references.
        json.loads(raw, object_pairs_hook=_unique_object)
        return ReplayScript.model_validate_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ReplayScriptError("invalid_replay_script") from None


def load_script(name: str) -> ReplayScript:
    """Only construction-time package I/O. An input string never becomes an arbitrary path."""
    if name not in SCENARIOS:
        raise ReplayScriptError("unknown_replay_scenario")
    resource = files(__package__).joinpath("fixtures", f"{name}.json")
    try:
        with resource.open("rb") as file:
            raw = file.read(MAX_SCRIPT_BYTES + 1)
    except OSError:
        raise ReplayScriptError("replay_resource_unavailable") from None
    return parse_script(raw)
