"""Shared immutable configuration model; no reading environment or I/O."""
from pydantic import BaseModel, ConfigDict


class FrozenSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
