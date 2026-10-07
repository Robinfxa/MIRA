"""Bounded generation-tool exchange; providers propose, the application executes.

The per-turn adapter owns its private continuation items. Nothing in these DTOs
is permission, a presentation receipt, a user-memory fact or an executable path.
"""
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Protocol

from mira.application.contracts import CandidateRange, GenerationContext


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters_json: str


@dataclass(frozen=True, slots=True)
class GenerationToolCall:
    call_id: str
    name: str
    arguments_json: str
    commentary: CandidateRange | None = None


@dataclass(frozen=True, slots=True)
class GenerationToolResult:
    call_id: str
    output_json: str


class ToolTurn(Protocol):
    async def start(self) -> CandidateRange | GenerationToolCall:
        """Return a complete candidate or one complete, untrusted tool call."""
        ...

    async def continue_after_tool(
        self, result: GenerationToolResult, current_context: GenerationContext,
    ) -> CandidateRange:
        """Return one text/speech cue using this call's actual application result."""
        ...

    def close(self) -> None:
        """Fence further requests and release private, unused continuation state."""
        ...


class ToolGenerationBackend(Protocol):
    def open_tool_turn(
        self, context: GenerationContext, tools: tuple[ToolDefinition, ...],
    ) -> ToolTurn:
        """Open at most one tool operation and two admitted model requests."""
        ...


class CompleteCandidateChunker(Protocol):
    def expand(
        self, context: GenerationContext, candidate: CandidateRange,
    ) -> AsyncIterator[CandidateRange]:
        """Use the existing optional caption planner on one complete cue."""
        ...


# Single closed vocabulary shared by the application and native wire adapter.
# Availability remains a separate per-request readiness fact.
TOOL_FIELDS = {
    'show_photo': {'photo_id': {'type': 'string', 'enum': ['trip_photo']}},
    'cancel_story_image': {'request_id': {'type': 'string', 'minLength': 36, 'maxLength': 36}},
    'generate_story_image': {
        'brief': {'type': 'string', 'minLength': 1, 'maxLength': 600},
        'framing': {'type': 'string', 'enum': ['wide', 'detail']},
        'lighting': {'type': 'string', 'enum': ['scene_default', 'warm']},
    },
    'set_outfit': {'outfit': {'type': 'string', 'enum': ['black_jacket', 'cream_inner_only', 'amber_raincoat']}},
    'set_accessory': {'accessory': {'type': 'string', 'enum': ['camera_clip', 'star_clip']}},
    'set_emotion': {'emotion': {'type': 'string', 'enum': ['normal', 'guarded', 'happy', 'shy']}},
    'perform_action': {'action': {'type': 'string', 'enum': ['raise_camera', 'return_camera']}},
    'set_scene': {'scene': {'type': 'string', 'enum': ['cafe', 'rain_window']}},
    'advance_story': {
        'transition_id': {'type': 'string', 'enum': ['t.offer', 't.yes', 't.window', 't.no',
            'x.ask_role', 'x.recognize', 'x.story', 'x.promise', 'x.gift_offer', 'x.gift_accept', 'x.gift_decline', 'x.exit']},
        'input_act': {'type': 'string', 'enum': ['none', 'claim_role', 'confirm_role', 'ask_role_confirmation',
            'exit_role', 'reopen_gift', 'reopen_accept_gift', 'reopen_rain', 'accept_gift', 'decline_gift', 'accept_rain', 'decline_rain']},
        'evidence_text': {'type': 'string', 'minLength': 0, 'maxLength': 500},
        'reference_effect_id': {'type': 'string', 'minLength': 0, 'maxLength': 128},
        'offer_id': {'type': 'string', 'minLength': 0, 'maxLength': 96},
        'draft_cue': {'type': 'string', 'minLength': 0, 'maxLength': 500},
        'target': {'type': 'string', 'enum': ['none', 'amber_raincoat', 'rain_window']},
        'scope': {'type': 'string', 'enum': ['fictional_role_only']},
    },
}
NATIVE_CHARACTER_TOOLS = frozenset(TOOL_FIELDS) - {'show_photo', 'generate_story_image', 'cancel_story_image'}
