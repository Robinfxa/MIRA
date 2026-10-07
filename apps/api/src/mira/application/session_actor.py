"""One state writer per session. Provider waits never hold the transition lock.

This is a small application coordinator, not a general actor/FSM framework.
All transitions are synchronous while the lock is held. The in-memory journal
is deliberately nonblocking; durable state/outbox is a separate WP05 migration.
"""
import asyncio
import hashlib
import json
import math
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from mira.application.compiler import compile_range, compile_generated_media
from mira.application.story_images import StoryImageRuntime, compile_image_intent, eligible_scenes
from mira.domain.story_images import (ImageReservation, StoryImageStatus, parse_image_proposal_json, parse_generated_photo)
from mira.application.authored_visual_events import filter_visual_events, camera_uncertain, event_available
from mira.domain.fixed_photo import FixedPhotoStatus, FIXED_PHOTO_PENDING
from mira.application.fixed_photo_diagnostics import SafeFixedPhotoDiagnostic
from mira.application.wardrobe_diagnostics import SafeWardrobeDiagnostic, WARDROBE_CONTROLS
from mira.application.native_tool_diagnostics import SafeNativeToolDiagnostic, TOOL_REASONS
from mira.application.image_readiness import (image_tool_readiness, runtime_image_readiness,
    advertised_image_readiness)
from mira.domain.story import ReadinessCatalog
from mira.application.response_preference import begin_response
from mira.application.generation_diagnostics import generation_failure_diagnostic
from mira.application.decision_contracts import InputDecisionObservation, InputDecisionStatus, ReliableUserInput, evidence_digest
from mira.application.decision_runtime import (
    DecisionSnapshotOwner, SemanticReviewCoordinator, snapshot_matches_state, snapshot_same_branch,
)
from mira.application.diagnostic_errors import (
    classify_failure, classify_reason, is_jev_transport_reason, is_semantic_uncertainty_reason,
    jev_resource_failure_code, public_error_code,
)
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticEvent, DiagnosticKind, DiagnosticOutcome,
    DiagnosticSpan, DiagnosticStage, RecordingKind, capture_model_safely, capture_text_safely,
    diagnostic_context, emit_safely, failure_diagnostic_id,
)
from mira.application.ports.diagnostics import Diagnostics
from mira.application.media_runtime import MediaOperation, MicrophoneBuffer, speech_packets
from mira.application.ports.media import ImageOperationAdmissionDenied, SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.application.contracts import (
    AuditEvent, CandidateRange, EffectProposal, GenerationContext, ReportedConfidenceWarning,
    ReviewObservation, ReviewVerdict, audio_context_progress, candidate_data,
)
from mira.application.choice_confidence import choice_confidence_consistent
from mira.application.choice_wire_policy import CHOICE_WIRE_POLICY_REPORTED_V2
from mira.application.ports.generation_tools import (GenerationToolCall, ToolGenerationBackend, CompleteCandidateChunker, NATIVE_CHARACTER_TOOLS)
from mira.application.generation_tool_execution import (
    tool_definitions, parse_tool_arguments, dialogue_only, visible_fixed_receipt, tool_result, project_tool_result,
    NativeToolIdentity, NativeDialogueIntent, control_effect, control_ready, current_control_receipt,
)
from mira.application.ports.generation import GenerationBackend
from mira.application.ports.journal import EventJournal
from mira.application.ports.review import ReviewBackend
from mira.application.actor_memory import (
    ActorMemoryBindingError, SessionMemoryBinding,
)
from mira.application.memory_context import (
    RequiredMemoryContextOverflow,
)
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.actor_conversation import SessionConversationBinding
from mira.application.conversation_archive import ConversationArchiveError
from mira.application.interrupted_intent import (
    AcceptedInput, InputRelation, RequestContext, begin_request, retain_generated, validate_relation,
)
from mira.domain.memory import MemoryRevisionChangedError
from mira.domain import transitions
from mira.domain.errors import DomainError
from mira.domain.models import AudioProgress, AudioStatus, EffectKind, Phase, Receipt, SessionState
from mira.domain.chapter_presentation import ChapterChoice, chapter_presentation


def _review_failure_code(observation) -> str:
    """Map only explicit semantic UNKNOWN to conversational clarification."""
    if observation.verdict == ReviewVerdict.REJECT:
        return "review_not_allowed"
    if is_semantic_uncertainty_reason(observation.reason_code):
        return "review_uncertain"
    failure = classify_reason(observation.reason_code)
    if failure.code == DiagnosticCode.INVALID_RESPONSE:
        return "invalid_response"
    if is_jev_transport_reason(observation.reason_code):
        return "timeout" if failure.code == DiagnosticCode.TIMEOUT else "unavailable"
    if resource_code := jev_resource_failure_code(observation.reason_code):
        return resource_code
    # Contract, calibration, snapshot and unknown-backend failures must not look like
    # ordinary conversational ambiguity in the existing system-notice path.
    return "unknown"


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    timeout_seconds: float
    max_turns: int | None
    max_effects: int


class SessionActor:
    def __init__(self, state: SessionState, generation: GenerationBackend,
                 review: ReviewBackend, journal: EventJournal, limits: RuntimeLimits, *,
                 speech_synthesis: SpeechSynthesisBackend | None = None,
                 speech_recognition: SpeechRecognitionBackend | None = None,
                 diagnostics: Diagnostics | None = None,
                 semantic_review: SemanticReviewCoordinator | None = None,
                 decision_owner: DecisionSnapshotOwner | None = None,
                 memory_binding: SessionMemoryBinding | None = None,
                 character_runtime: SessionCharacterRuntime | None = None,
                 visual_readiness: ReadinessCatalog | None = None,
                 conversation_binding: SessionConversationBinding | None = None,
                 story_image_runtime: StoryImageRuntime | None = None,
                 tool_generation: ToolGenerationBackend | None = None,
                 tool_caption_chunker: CompleteCandidateChunker | None = None,
                 tool_result_wait_seconds: float = 1.0,
                 native_tool_authority: bool = False) -> None:
        if (semantic_review is None) != (decision_owner is None):
            raise ValueError("semantic_composition_requires_owner_and_review")
        if memory_binding is not None and type(memory_binding) is not SessionMemoryBinding:
            raise ValueError("memory_binding_invalid")
        if (type(tool_result_wait_seconds) not in (int,float) or not math.isfinite(tool_result_wait_seconds)
                or not 0 < tool_result_wait_seconds <= 5):
            raise ValueError('tool_result_wait_invalid')
        if type(native_tool_authority) is not bool or (native_tool_authority and
                (tool_generation is None or semantic_review is not None or decision_owner is not None)):
            raise ValueError('native_tool_authority_composition_invalid')
        if review is None:
            if not native_tool_authority:raise ValueError('review_required')
            from mira.application.ports.review import DisabledReviewBackend
            review=DisabledReviewBackend()
        self._native_tool_authority=native_tool_authority
        self._native_tool_executions={}
        self._tool_generation = tool_generation
        self._tool_caption_chunker = tool_caption_chunker
        self._tool_result_wait_seconds = tool_result_wait_seconds
        self._tool_turns = {}
        self._tool_state_changed = asyncio.Event()
        self._semantic_review = semantic_review
        self._decision_owner = decision_owner
        self._memory_binding = memory_binding
        if conversation_binding is not None and type(conversation_binding) is not SessionConversationBinding:
            raise ValueError("conversation_binding_invalid")
        if (conversation_binding is not None and conversation_binding.recall_session_id is not None
                and speech_synthesis is not None
                and not conversation_binding.authorize_recalled_speech_to_google):
            raise ValueError("conversation_google_transmission_not_authorized")
        self._conversation_binding = conversation_binding
        self._conversation_inputs: tuple[AcceptedInput, ...] = ()
        if character_runtime is not None and type(character_runtime) is not SessionCharacterRuntime:
            raise ValueError("character_runtime_invalid")
        self._character_runtime = character_runtime
        if visual_readiness is not None and type(visual_readiness) is not ReadinessCatalog:
            raise ValueError("visual_readiness_invalid")
        self._visual_readiness = visual_readiness
        # At most one current-turn packet; never serialized into session views.
        # Used to recheck a delayed speech dispatch and future media delivery.
        self._current_generation_context: GenerationContext | None = None
        self._memory_close_started = False
        self._decision_inputs: tuple[ReliableUserInput, ...] = ()
        self._request_context: RequestContext | None = None
        # One provider wait per session; cancelled pending turns never enter the call.
        self._semantic_lock = asyncio.Lock()
        if story_image_runtime is not None:
            if type(story_image_runtime) is not StoryImageRuntime or character_runtime is None:
                raise ValueError('story_images_require_explicit_runtime_and_story')
            story_image_runtime.bind_session(state.session_id)
            state=replace(state,story_image=StoryImageStatus('bounded_fiction','idle'))
        self._story_images=story_image_runtime
        self._image_tasks=set()
        self._image_origins={}
        self._image_completion_events={}
        self._image_completion_claims={}
        self._image_completion_tasks={}
        # One valid image intent per accepted input, claimed before any JEV await.
        # Key binds that input/epoch and compiled specification; no cross-turn reuse.
        self._image_review_intents: dict[tuple[str, int, str], str] = {}
        self._state = self._with_chapter_projection(state)
        self._photo_dismissals: dict[str, tuple[int, int]] = {}
        self._diagnostics = diagnostics
        # Diagnostic-only current candidate; never serialized into context/state.
        self._wardrobe_waiting = (0, 0, ())
        self._diagnostic_spans: dict[asyncio.Task, DiagnosticSpan] = {}
        self._generation = generation
        self._review = review
        self._journal = journal
        self._limits = limits
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._request_fingerprints: dict[str, tuple[object, ...]] = {}
        self._accepted_turn_count = 0
        self._microphone_start_count = 0
        self._closed = False
        self._speech_synthesis = speech_synthesis
        self._speech_recognition = speech_recognition
        self._media_operations: set[MediaOperation] = set()
        self._speech_started: set[str] = set()
        self._microphone_started: dict[str, None] = {}

    def _with_chapter_projection(self, state: SessionState) -> SessionState:
        if self._character_runtime is None:
            projected = None
        else:
            from mira.domain.xiahe_chapter import chapter_projection
            projected = chapter_presentation(chapter_projection(self._character_runtime.runtime.story.chapter))
        return state if state.chapter_projection == projected else replace(state, chapter_projection=projected)

    def _commit(self, state: SessionState, kind: str) -> None:
        state = self._with_chapter_projection(state)
        if state is self._state:
            return
        if state.chapter_projection != self._state.chapter_projection and state.revision <= self._state.revision:
            state = replace(state, revision=self._state.revision + 1)
        previous = self._state
        self._state = state
        if state.issued_effects != previous.issued_effects:
            for effect in state.issued_effects:
                if effect not in previous.issued_effects and self._wardrobe_effect(effect):
                    self._wardrobe_event('grant','granted',effect.output_epoch,effect.activity_seq,
                        effect.value,1,effect_id=effect.id)
        self._tool_state_changed.set()
        self._tool_state_changed = asyncio.Event()
        if self._conversation_binding is not None and kind in (
                "input_committed", "receipt_recorded", "audio_progress_recorded"):
            self._conversation_binding.schedule_capture(state, self._conversation_inputs)
        try:
            self._journal.append(AuditEvent(
                sequence=state.revision, session_id=state.session_id, kind=kind,
                state_revision=state.revision, output_epoch=state.output_epoch,
                occurred_at=datetime.now(UTC).isoformat(),
            ))
        except Exception:
            pass
        emit_safely(self._diagnostics, DiagnosticEvent(DiagnosticStage.SESSION,
            DiagnosticOutcome.SUCCEEDED, diagnostic_context(session_id=state.session_id,
                turn_id=str(state.output_epoch)), kind=DiagnosticKind.STATE_CHANGED))
        if kind in ('plan_sealed','native_continuation_failed_cue_retained'):
            self._grant_ready_story_image()

    async def snapshot(self) -> SessionState:
        async with self._lock:
            image=self._state.story_image
            if image.request_id in self._image_origins and not self._image_scope_current(image.request_id):
                if image.state in ('pending','generating','reviewing','qualified'):
                    self._cancel_story_images('scope_changed')
                else:self._cancel_image_completion()
            return self._state

    def _cancel_tasks(self, reason: CancellationReason = CancellationReason.UNKNOWN) -> None:
        self._current_generation_context = None
        self._cancel_wardrobe()
        self._cancel_tool_turns()
        self._cancel_fixed_photo()
        if reason is not CancellationReason.SUPERSEDED or self._state.story_image.completion_state!='pending':
            self._cancel_image_completion()
        if reason in (CancellationReason.USER_STOP,CancellationReason.SESSION_CLOSED):
            self._cancel_story_images('stop_all' if reason is CancellationReason.USER_STOP else 'session_close')
        elif self._story_images is not None:
            self._story_images.job_event_reason='ordinary_input' if reason is CancellationReason.SUPERSEDED else 'reply_interrupted'
        for task in tuple(self._tasks):
            if span := self._diagnostic_spans.get(task):
                span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED, reason=reason)
            task.cancel()
        self._cancel_media(reason)

    def _cancel_media(self, reason: CancellationReason = CancellationReason.UNKNOWN) -> None:
        for operation in tuple(self._media_operations):
            operation.cancel(reason)

    async def submit(self, *, request_id: str, activity_seq: int,
                     cutoff: int, text: str,
                     source: Literal["text", "asr_final"] = "text",
                     relation: InputRelation = "independent",
                     continuation_of_request_id: str | None = None,
                     continuation_of_output_epoch: int | None = None,
                     chapter_choice: ChapterChoice | None = None) -> SessionState:
        if source not in ("text", "asr_final"):
            raise DomainError("invalid_input", "Only reliable text or final ASR may start a turn.")
        validate_relation(relation, continuation_of_request_id, continuation_of_output_epoch)
        if chapter_choice is not None and (type(chapter_choice) is not ChapterChoice
                or relation != 'independent' or source != 'text' or text != chapter_choice.text):
            raise DomainError('invalid_input', 'Invalid explicit chapter choice.')
        async with self._lock:
            if self._closed:
                raise DomainError("session_closed", "Session has closed.")
            fingerprint = (activity_seq, cutoff, text, source, relation,
                           continuation_of_request_id, continuation_of_output_epoch, chapter_choice)
            previous = self._request_fingerprints.get(request_id)
            if previous is not None:
                if previous != fingerprint:
                    raise DomainError("request_conflict", "Request ID was reused with different data.")
                return self._state
            local_candidate = None
            if chapter_choice is not None:
                if self._character_runtime is None:
                    raise DomainError('chapter_choice_unavailable', 'No current chapter offer is available.')
                local_candidate = self._character_runtime.choice_candidate(
                    chapter_choice.choice, chapter_choice.offer_id, chapter_choice.offer_effect_id,
                    chapter_choice.offer_effect_digest, input_id=request_id, epoch=self._state.output_epoch + 1)
            try:
                state = transitions.begin_input(self._state, activity_seq=activity_seq,
                    cutoff=cutoff, request_id=request_id, text=text)
            except DomainError as error:
                if error.code == "history_pending":
                    # A rejected new turn still removes authority from a current old
                    # branch, but does not consume the caller's request/activity ID.
                    revoked = transitions.revoke_for_history_pending(self._state, cutoff=cutoff)
                    if revoked is not self._state:
                        self._cancel_tasks(CancellationReason.SUPERSEDED)
                        revoked=replace(revoked,story_image=self._state.story_image,
                            revision=max(revoked.revision,self._state.revision+1))
                        self._commit(revoked, "history_pending_revoked")
                raise
            if self._limits.max_turns is not None and self._accepted_turn_count >= self._limits.max_turns:
                raise DomainError("session_capacity", "Foundation turn budget reached; create a new session.")
            # Cancellation-resistant providers are not allowed to create an unbounded task set.
            if len(self._tasks) >= 4:
                raise DomainError("busy", "Previous work is still terminating.")
            if self._limits.max_turns is None:
                if (self._conversation_binding is not None and
                        (len(state.user_inputs) > 64 or len(state.issued_effects) > self._limits.max_effects // 2)
                        and self._conversation_binding.persistence_status != 'saved'):
                    raise DomainError('busy', 'Pending archive records must settle before history retirement.')
                state = transitions.retain_recent_history(state, max_effects=max(1, self._limits.max_effects // 2))
                removed = state.retired_user_inputs - self._state.retired_user_inputs
                if removed and self._request_context is not None:
                    self._request_context = replace(self._request_context, accepted_inputs=tuple(
                        replace(item, user_input_index=item.user_input_index - removed)
                        for item in self._request_context.accepted_inputs))
            accepted_input = AcceptedInput(request_id, state.output_epoch, text, source, len(state.user_inputs) - 1)
            request_context = begin_request(self._request_context,
                accepted_input, relation=relation,
                parent_id=continuation_of_request_id, parent_epoch=continuation_of_output_epoch)
            self._cancel_tasks(CancellationReason.SUPERSEDED)
            state=replace(state,story_image=self._state.story_image,fixed_photo=self._state.fixed_photo,
                          revision=max(state.revision,self._state.revision+1))
            self._image_review_intents.clear()
            self._native_tool_executions.clear()
            self._request_fingerprints[request_id] = fingerprint
            self._accepted_turn_count += 1
            self._decision_inputs += (ReliableUserInput(request_id, text, source),)
            if self._limits.max_turns is None:
                for old in tuple(self._request_fingerprints)[:-64]:
                    self._request_fingerprints.pop(old)
                self._decision_inputs = self._decision_inputs[-64:]
                kept = {item.id for item in state.issued_effects}
                self._speech_started.intersection_update(kept)
                if self._character_runtime is not None:
                    self._character_runtime.retain_effect_metadata(kept)
            self._request_context = request_context
            state = begin_response(state, text, speech_available=self._speech_synthesis is not None)
            if self._conversation_binding is not None:
                # Archive source indices remain absolute even though live context is recent.
                self._conversation_inputs += (replace(accepted_input,
                    user_input_index=state.retired_user_inputs + accepted_input.user_input_index),)
                if self._limits.max_turns is None:
                    self._conversation_inputs = self._conversation_inputs[-64:]
            if self._story_images is not None:
                state=replace(state,story_image_facts=self._story_images.facts(state))
            self._commit(state, "input_committed")
            if self._story_images is not None and self._state.story_image.request_id is not None:
                self._emit_image_readiness(replace(runtime_image_readiness(self._story_images,
                    output_epoch=state.output_epoch,activity_seq=state.activity_seq),phase='operation'))
            capture_text_safely(self._diagnostics, RecordingKind.DIALOGUE, text,
                diagnostic_context(session_id=state.session_id, turn_id=str(state.output_epoch)))
            context = GenerationContext(text, state.user_inputs, state.presented_effects,
                state.output_epoch, audio_progress=audio_context_progress(state.audio_progress),
                retired_user_inputs=state.retired_user_inputs,
                character_story=(self._character_runtime.begin_input(request_id,state.output_epoch)
                                 if self._character_runtime is not None else None),
                character_assets=(self._character_runtime.readiness if self._character_runtime is not None
                                  else self._visual_readiness),
                request_context=self._request_context if relation != "independent" else None,
                visual_action_uncertain=camera_uncertain(state),
                response_mode=state.response_mode, photo_visible=state.photo_visible, photo_visibility_revision=state.photo_visibility_revision,
                story_images=self._image_context_facts(),fixed_photo=state.fixed_photo,
                story_image_completions=self._take_image_completions(),
                story_image_scenes=eligible_scenes(self._character_runtime.runtime.project().projection) if self._story_images else ())
            self._current_generation_context = context
            self._commit(self._state, 'chapter_input_bound')
            task = asyncio.create_task(self._generate(context, activity_seq, local_candidate=local_candidate)
                                       if local_candidate is not None else self._generate(context, activity_seq))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return self._state

    @staticmethod
    def _memory_domain_error(error: BaseException) -> DomainError:
        """Translate any reader failure to stable, non-content-revealing codes."""
        if isinstance(error, (MemoryRevisionChangedError, ActorMemoryBindingError)):
            detail = error.args[0] if len(error.args) == 1 else None
            if detail == "memory_context_stale":
                return DomainError("memory_context_stale",
                    "Memory context changed during this turn. Retry the request.")
        if isinstance(error, RequiredMemoryContextOverflow):
            return DomainError("memory_context_overflow",
                "Required memory context exceeded its safe size limit.")
        if isinstance(error, TimeoutError):
            return DomainError("memory_timeout",
                "The local memory read timed out. Retry this turn.")
        return DomainError("memory_unavailable",
            "The local memory context is unavailable. Check its setup and retry.")

    async def _capture_memory_packet(self, context: GenerationContext,
                                    activity_seq: int) -> GenerationContext | None:
        binding = self._memory_binding
        if binding is None:
            return context
        async with self._lock:
            if (self._closed or self._state.request_id is None
                    or (self._state.output_epoch, self._state.activity_seq)
                    != (context.output_epoch, activity_seq)):
                return None
        try:
            packet = await binding.build_packet(context.user_text)
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError) as error:
            # No packet was accepted: local operational absence cannot prevent chat.
            # Contract, scope, consent and revision failures still fail closed below.
            if isinstance(error, PermissionError):
                raise self._memory_domain_error(error) from None
            packet = None
        except Exception as error:
            raise self._memory_domain_error(error) from None
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        async with self._lock:
            if (self._closed or self._state.request_id is None
                    or (self._state.output_epoch, self._state.activity_seq)
                    != (context.output_epoch, activity_seq)):
                return None
            captured = replace(context, memory_packet=packet,
                memory_recall_status="unavailable" if packet is None else None)
            self._current_generation_context = captured
            return captured

    async def _capture_conversation_packet(self, context, activity_seq):
        binding = self._conversation_binding
        if binding is None:
            return context
        try:
            packet = await binding.build_packet(context.user_text, output_epoch=context.output_epoch)
            status = None
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError) as error:
            if isinstance(error, PermissionError):
                raise DomainError("memory_unavailable", "Conversation archive access was denied.") from None
            packet, status = None, "unavailable"
        except Exception:
            raise DomainError("memory_unavailable", "Conversation recall could not be safely validated.") from None
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        async with self._lock:
            if (self._closed or self._state.request_id is None
                    or (self._state.output_epoch, self._state.activity_seq)
                    != (context.output_epoch, activity_seq)):
                return None
            captured = replace(context, conversation_recall=packet, conversation_recall_status=status)
            self._current_generation_context = captured
            return captured

    async def _ensure_context_current(self, context: GenerationContext) -> None:
        if self._conversation_binding is not None and context.conversation_recall is not None:
            try:
                await self._conversation_binding.ensure_current(context.conversation_recall)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise DomainError("memory_context_stale", "Conversation recall changed during this turn.") from None
        if self._character_runtime is not None:
            self._character_runtime.ensure_definition(context)
        binding = self._memory_binding
        packet = context.memory_packet
        if binding is None or packet is None:
            return
        try:
            await binding.ensure_current(packet)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise self._memory_domain_error(error) from None
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError

    async def set_response_preference(self, *, muted: bool, expected_revision: int) -> SessionState:
        async with self._lock:
            if self._closed:
                raise DomainError("session_closed", "Session has closed.")
            state = transitions.set_response_preference(self._state, muted=muted,
                                                       expected_revision=expected_revision)
            self._commit(state, "response_preference_changed")
            if muted:
                # Input capture and generation continue; only this output loses authority.
                for operation in tuple(self._media_operations):
                    if operation.effect is not None:
                        operation.cancel(CancellationReason.PERMIT_REVOKED)
            return self._state

    async def stop(self, *, activity_seq: int, cutoff: int, scope: str = "all") -> SessionState:
        async with self._lock:
            state = transitions.stop(self._state, activity_seq=activity_seq, cutoff=cutoff,cancel_images=scope=="all")
            if state is not self._state:
                self._cancel_tasks(CancellationReason.USER_STOP if scope=="all" else CancellationReason.SUPERSEDED)
                if self._character_runtime is not None:
                    if scope=='all':self._character_runtime.stop(state.output_epoch)
                    else:self._character_runtime.reply_fence(state.output_epoch,state.presented_effects)
                state=replace(state,story_image=self._state.story_image,fixed_photo=self._state.fixed_photo,
                              revision=max(state.revision,self._state.revision+1))
                self._commit(state, "stopped")
            return self._state

    async def dismiss_photo(self, *, request_id: str, expected_revision: int, cutoff: int,
                            target: str = 'display', expected_image_request_id: str | None = None,
                            expected_photo_effect_id: str | None = None) -> SessionState:
        async with self._lock:
            if self._closed:raise DomainError('session_closed','Session has closed.')
            identity=(expected_revision,cutoff,target,expected_image_request_id,expected_photo_effect_id)
            if request_id in self._photo_dismissals:
                if self._photo_dismissals[request_id]!=identity:
                    raise DomainError('photo_request_conflict','Photo dismissal request cannot change.')
                return self._state
            if self._limits.max_turns is not None and len(self._photo_dismissals)>=self._limits.max_effects:
                raise DomainError('effect_capacity','Photo control budget reached.')
            image=self._state.story_image
            photos={e.id:e for e in self._state.presented_effects if e.kind is EffectKind.MEDIA
                and (e.value in ('trip_photo','trip_photo_placeholder') or parse_generated_photo(e.value))}
            latest=max((r for r in self._state.receipts if r.effect_id in photos),key=lambda r:r.presentation_seq,default=None)
            shown=photos.get(latest.effect_id) if latest is not None and self._state.photo_visible else None
            if expected_photo_effect_id is not None and (shown is None or shown.id!=expected_photo_effect_id):
                raise DomainError('photo_target_conflict','The displayed photo changed.')
            if target=='image_job' and (expected_image_request_id is None or expected_image_request_id!=image.request_id):
                raise DomainError('image_request_conflict','The image cancellation target changed.')
            effective=('display_generated' if shown is not None and parse_generated_photo(shown.value) else 'fixed_photo') if target=='display' else target
            state=transitions.dismiss_photo(self._state,expected_revision=expected_revision,cutoff=cutoff,
                target=effective,effect_id=shown.id if shown else None,resource_id=image.resource_id)
            had_tool_turn=bool(self._tool_turns)
            if effective in ('fixed_photo','all_photos') and not self._native_tool_authority:self._cancel_tool_turns()
            if effective in ('image_job','all_photos'):self._cancel_story_images('explicit_photo_cancel')
            elif effective=='display_generated' and shown is not None and parse_generated_photo(shown.value)==(image.resource_id,image.content_digest):
                self._cancel_image_completion()
            if had_tool_turn and not self._native_tool_authority and effective in ('fixed_photo','all_photos'):
                state=transitions.seal(state,output_epoch=state.output_epoch)
            state=replace(state,story_image=self._state.story_image,fixed_photo=self._state.fixed_photo,
                revision=max(state.revision,self._state.revision+1))
            if self._story_images is not None:state=replace(state,story_image_facts=self._story_images.facts(state))
            self._photo_dismissals[request_id]=identity
            if self._limits.max_turns is None:
                for old in tuple(self._photo_dismissals)[:-64]:self._photo_dismissals.pop(old)
            self._commit(state,'photo_dismissed')
            if effective in ('fixed_photo','all_photos') and self._state.fixed_photo.state!='idle':
                self._set_fixed_photo(replace(self._state.fixed_photo,state='dismissed',reason='dismissed'),'dismiss')
            return self._state

    async def receipt(self, receipt: Receipt) -> SessionState:
        checkpoint = None
        async with self._lock:
            if self._closed:
                raise DomainError("session_closed", "Session has closed.")
            new_receipt = receipt not in self._state.receipts
            effect=next((e for e in self._state.issued_effects if e.id==receipt.effect_id),None)
            identity=parse_generated_photo(effect.value) if effect is not None else None
            if identity is not None and new_receipt:
                reservation=next((r for r in self._state.image_reservations if
                    (r.qualified_resource_id,r.qualified_content_digest)==identity),None)
                if (reservation is None or reservation.cancellation_generation!=self._state.image_cancellation_generation
                        or reservation.current_effect_id!=receipt.effect_id
                        or not self._image_scope_current(reservation.request_id)):
                    raise DomainError('image_not_granted','Image job no longer authorizes presentation.')
            state=transitions.record_receipt(self._state, receipt)
            if self._story_images is not None:
                facts=self._story_images.facts(state)
                image=next((f for f in facts if f.presented_effect_id==receipt.effect_id),None)
                status=(replace(state.story_image,state='presented') if image is not None
                        and image.request_id==state.story_image.request_id else state.story_image)
                state=replace(state,story_image_facts=facts,story_image=status)
            self._commit(state, "receipt_recorded")
            if new_receipt and identity is not None and self._state.story_image.state=='presented':self._queue_image_completion()
            if new_receipt and receipt.effect_id==self._state.story_image.completion_effect_id:self._set_image_completion('presented')
            if (new_receipt and receipt.effect_id == self._state.fixed_photo.effect_id
                    and self._state.fixed_photo.state != 'dismissed'
                    and (receipt.output_epoch,receipt.activity_seq) == (self._state.fixed_photo.output_epoch,self._state.fixed_photo.activity_seq)):
                self._set_fixed_photo(replace(self._state.fixed_photo,state='presented',reason=None),'receipt')
            if self._character_runtime is not None:
                effect=next(effect for effect in self._state.issued_effects if effect.id==receipt.effect_id)
                self._character_runtime.acknowledge(receipt,effect)
                if new_receipt and self._wardrobe_effect(effect):
                    acknowledged = self._character_runtime.runtime.story.last_acknowledged_outfit
                    self._wardrobe_event('receipt','presented',effect.output_epoch,effect.activity_seq,
                        effect.value,1,'historical_receipt' if receipt.output_epoch != self._state.output_epoch else None,
                        effect_id=effect.id,acknowledged=
                        'outfit_'+acknowledged if acknowledged is not None else None)
                self._commit(self._state, 'chapter_receipt_projected')
                checkpoint = self._character_runtime.checkpoint_snapshot()
        # Never hold the Actor transition lock across SQLite. Stop/new input can
        # fence presentation immediately while this exact receipt becomes durable.
        if self._character_runtime is not None:
            await self._character_runtime.persist(checkpoint)
        async with self._lock:
            return self._state

    async def audio_progress(self, progress: AudioProgress) -> SessionState:
        async with self._lock:
            if self._closed:
                raise DomainError("session_closed", "Session has closed.")
            previous = self._state
            context = diagnostic_context(session_id=previous.session_id,
                turn_id=str(progress.output_epoch), effect_id=progress.effect_id)
            self._commit(transitions.record_audio_progress(previous, progress,
                diagnostic_id=failure_diagnostic_id(context)), "audio_progress_recorded")
            if (self._state is not previous and progress.output_epoch == previous.output_epoch
                    and previous.request_id is not None
                    and any(e.id == progress.effect_id for e in previous.active_grants)
                    and progress.status in {AudioStatus.INTERRUPTED, AudioStatus.FAILED}):
                interrupted = progress.status == AudioStatus.INTERRUPTED
                # The report proves interruption, not which local action caused it.
                # Dependent work stops because this transition revoked its permit.
                emit_safely(self._diagnostics, DiagnosticEvent(DiagnosticStage.PLAYBACK,
                    DiagnosticOutcome.CANCELLED if interrupted else DiagnosticOutcome.FAILED,
                    context, code=DiagnosticCode.CANCELLED if interrupted else DiagnosticCode.UNKNOWN,
                    cancellation_reason=CancellationReason.UNKNOWN if interrupted else None))
                self._cancel_tasks(CancellationReason.PERMIT_REVOKED)
                self._grant_ready_story_image()
            elif progress.status != AudioStatus.RENDERED:
                for operation in tuple(self._media_operations):
                    if operation.effect is not None and operation.effect.id == progress.effect_id:
                        operation.cancel(CancellationReason.PERMIT_REVOKED)
            return self._state

    def _media_capacity(self) -> None:
        if self._closed:
            raise DomainError("session_closed", "Session has closed.")
        if len(self._media_operations) >= 4:
            raise DomainError("busy", "Previous media work is still terminating.")

    def _track_media(self, operation: MediaOperation) -> MediaOperation:
        self._media_operations.add(operation)
        return operation

    def close_media(self, operation: MediaOperation,
                    reason: CancellationReason = CancellationReason.UNKNOWN) -> Coroutine:
        # Establish revocation and ownership before the caller can be cancelled
        # at its next await. Capacity includes an uncooperative socket child too.
        operation.cancel(reason)
        def reap(task) -> None:
            if not task.cancelled():
                task.exception()
            if all(owned.done() for owned in operation.tasks):
                self._media_operations.discard(operation)
        for task in operation.tasks:
            if task.done():
                reap(task)
            else:
                task.add_done_callback(reap)
        return operation.close(reason)

    async def open_speech(self, *, effect_id: str, digest: str, output_epoch: int,
                          activity_seq: int) -> MediaOperation:
        if self._memory_binding is not None or self._character_runtime is not None or self._conversation_binding is not None:
            async with self._lock:
                effect = next((e for e in self._state.active_grants if e.id == effect_id), None)
                if (self._closed or effect is None or effect.kind != EffectKind.SPEECH
                        or (effect.digest, effect.output_epoch, effect.activity_seq) !=
                        (digest, output_epoch, activity_seq)):
                    raise DomainError("speech_not_granted", "There is no current speech grant.")
                context = self._current_generation_context
                if context is None or context.output_epoch != output_epoch:
                    raise DomainError("memory_context_stale", "Memory context is no longer current.")
            # No transition lock during local I/O: Stop/new input remains immediate.
            # The ordinary grant/epoch checks below run again after the await.
            await self._ensure_context_current(context)
        async with self._lock:
            self._media_capacity()
            effect = next((e for e in self._state.active_grants if e.id == effect_id), None)
            if effect is None or effect.kind != EffectKind.SPEECH:
                raise DomainError("speech_not_granted", "There is no current speech grant.")
            if (effect.digest, effect.output_epoch, effect.activity_seq) != (
                    digest, output_epoch, activity_seq):
                raise DomainError("receipt_mismatch", "Speech origin differs from the current grant.")
            if self._speech_synthesis is None:
                raise DomainError("speech_unavailable", "No speech synthesis provider is injected.")
            if effect.id in self._speech_started or any(
                    p.effect_id == effect.id and p.status != AudioStatus.RENDERED
                    for p in self._state.audio_progress):
                raise DomainError("speech_consumed", "This speech grant has already been consumed.")
            if any(op.effect is not None and not op.cancelled.is_set() for op in self._media_operations):
                raise DomainError("busy", "The session voice slot is already in use.")
            self._speech_started.add(effect.id)
            backend = self._speech_synthesis
            return self._track_media(MediaOperation(lambda: speech_packets(backend, effect),
                activity_seq=activity_seq, input_epoch=self._state.input_epoch,
                output_epoch=output_epoch, effect=effect, diagnostics=self._diagnostics,
                diagnostic_context=diagnostic_context(session_id=self._state.session_id,
                    turn_id=str(output_epoch), effect_id=effect.id)))

    async def open_microphone(self, *, stream_id: str, activity_seq: int,
                              input_epoch: int, buffer: MicrophoneBuffer) -> MediaOperation:
        async with self._lock:
            self._media_capacity()
            if (activity_seq, input_epoch) != (self._state.activity_seq, self._state.input_epoch):
                raise DomainError("stale_activity", "Microphone origin is no longer current.")
            if self._speech_recognition is None:
                raise DomainError("microphone_unavailable", "No speech recognition provider is injected.")
            if stream_id in self._microphone_started:
                raise DomainError("stream_consumed", "Microphone stream identity has already been used.")
            if self._limits.max_turns is not None and self._microphone_start_count >= self._limits.max_turns:
                raise DomainError("session_capacity", "Microphone stream budget reached.")
            if any(op.effect is None and not op.cancelled.is_set() for op in self._media_operations):
                raise DomainError("busy", "A microphone stream is already open.")
            self._microphone_started[stream_id] = None
            self._microphone_start_count += 1
            if self._limits.max_turns is None:
                for old in tuple(self._microphone_started)[:-128]:
                    self._microphone_started.pop(old)
            backend = self._speech_recognition
            return self._track_media(MediaOperation(lambda: backend.transcribe(buffer.packets()),
                activity_seq=activity_seq, input_epoch=input_epoch,
                output_epoch=self._state.output_epoch, diagnostics=self._diagnostics,
                discard_input=buffer.clear,
                diagnostic_context=diagnostic_context(session_id=self._state.session_id,
                    turn_id=str(self._state.output_epoch), effect_id=stream_id)))

    async def validate_media(self, operation: MediaOperation) -> None:
        async with self._lock:
            self._validate_media_locked(operation)
            context = self._current_generation_context
        if operation.effect is not None and (self._memory_binding is not None or self._character_runtime is not None or self._conversation_binding is not None):
            if context is None or context.output_epoch != operation.output_epoch:
                operation.cancel(CancellationReason.PERMIT_REVOKED)
                raise DomainError("memory_context_stale", "Memory context is no longer current.")
            try:
                await self._ensure_context_current(context)
            except BaseException:
                operation.cancel(CancellationReason.PERMIT_REVOKED)
                raise
            async with self._lock:
                self._validate_media_locked(operation)

    def _validate_media_locked(self, operation: MediaOperation) -> None:
        state = self._state
        if (self._closed or operation.cancelled.is_set()
                or (operation.activity_seq, operation.input_epoch, operation.output_epoch)
                != (state.activity_seq, state.input_epoch, state.output_epoch)
                or (operation.effect is not None and (
                    operation.effect not in state.active_grants or any(
                        p.effect_id == operation.effect.id and p.status != AudioStatus.RENDERED
                        for p in state.audio_progress)))):
            operation.cancel(CancellationReason.PERMIT_REVOKED)
            raise DomainError("media_cancelled", "Media authority has been revoked.")

    async def media_failed(self, operation: MediaOperation, code: str) -> None:
        async with self._lock:
            if not self._closed and operation.effect is not None:
                failed = transitions.fail_speech(self._state, output_epoch=operation.output_epoch,
                    effect_id=operation.effect.id, code=public_error_code(code),
                    diagnostic_id=operation.diagnostic_id)
                if failed is not self._state:
                    self._commit(failed, "media_failed")
                    # Independent text remains receiptable; pending generation and
                    # optional actions cannot extend this now sealed response.
                    self._cancel_tasks(CancellationReason.PERMIT_REVOKED)
                    self._grant_ready_story_image()

    async def _semantic_candidate(self, context: GenerationContext, activity_seq: int,
                                  candidate: CandidateRange, generation_span: DiagnosticSpan, *,
                                  scope: Literal["stage", "seal"] = "stage") -> bool:
        """Review and apply one pending range, or seal, with both post-await lock checks.

        Receipt/audio changes refresh the pending candidate instead of dropping the
        turn. Supersede/Stop invalidates the branch immediately, including a provider
        that suppresses cancellation. The enclosing generation timeout bounds retries.
        """
        assert self._semantic_review is not None and self._decision_owner is not None
        async with self._semantic_lock:
            while True:
                async with self._lock:
                    if (self._closed or self._state.request_id is None
                            or (self._state.output_epoch, self._state.activity_seq)
                            != (context.output_epoch, activity_seq)):
                        return False
                    snapshot = self._decision_owner.snapshot(
                        self._state, self._decision_inputs,
                        memory_packet=context.memory_packet,
                        character_story=context.character_story,
                        character_assets=context.character_assets, request_context=context.request_context,
                        visual_action_uncertain=context.visual_action_uncertain,
                        memory_recall_status=context.memory_recall_status,
                        conversation_recall=context.conversation_recall,
                        conversation_recall_status=context.conversation_recall_status,
                    )
                    if snapshot is None:
                        raise DomainError("review_not_allowed", "Reliable decision facts are incomplete.")
                input_span = DiagnosticSpan(self._diagnostics, DiagnosticStage.INPUT_REVIEW,
                                            generation_span.context)
                try:
                    await self._ensure_context_current(context)
                    input_observation = await self._semantic_review.observe(snapshot)
                    await self._ensure_context_current(context)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                except asyncio.CancelledError:
                    input_span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED,
                        reason=generation_span.cancellation_reason or CancellationReason.UNKNOWN)
                    raise
                except Exception as error:
                    input_span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code)
                    raise
                warning = None
                referent = input_observation.referent
                if (input_observation.choice_wire_policy_version == CHOICE_WIRE_POLICY_REPORTED_V2
                        and referent.confidence is not None and referent.probabilities):
                    probabilities = {item.option: item.probability for item in referent.probabilities}
                    if not choice_confidence_consistent(probabilities, referent.confidence):
                        warning = ReportedConfidenceWarning(
                            CHOICE_WIRE_POLICY_REPORTED_V2, max(probabilities.values()),
                            referent.confidence, sum(probabilities.values()))
                input_span.finish(DiagnosticOutcome.SUCCEEDED if (
                    input_observation.status == InputDecisionStatus.OBSERVED) else DiagnosticOutcome.FAILED,
                    code=None if input_observation.status == InputDecisionStatus.OBSERVED else (
                        classify_reason(input_observation.reason_code).code),
                    reported_confidence_warning=warning)
                async with self._lock:
                    if self._closed or not snapshot_same_branch(self._state, snapshot):
                        return False
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    if not snapshot_matches_state(self._state, snapshot):
                        continue
                review_span = DiagnosticSpan(self._diagnostics, DiagnosticStage.OUTPUT_REVIEW,
                                             generation_span.context)
                try:
                    observation = await self._semantic_review.review(
                        snapshot, candidate, input_observation, scope=scope)
                    if observation.verdict == ReviewVerdict.ALLOW:
                        await self._ensure_context_current(context)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                except asyncio.CancelledError:
                    review_span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED,
                        reason=generation_span.cancellation_reason or CancellationReason.UNKNOWN)
                    raise
                except Exception as error:
                    review_span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code)
                    raise
                review_span.finish(DiagnosticOutcome.SUCCEEDED if (
                    observation.verdict == ReviewVerdict.ALLOW) else DiagnosticOutcome.FAILED,
                    code=None if observation.verdict == ReviewVerdict.ALLOW else (
                        DiagnosticCode.BLOCKED if observation.verdict == ReviewVerdict.REJECT
                        else classify_reason(observation.reason_code).code),
                    response_validation=observation.response_diagnostics)
                async with self._lock:
                    if self._closed or not snapshot_same_branch(self._state, snapshot):
                        return False
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    if not snapshot_matches_state(self._state, snapshot):
                        continue
                    self._wardrobe_decision(context,observation.verdict)
                    if observation.verdict != ReviewVerdict.ALLOW:
                        raise DomainError(_review_failure_code(observation),
                                          "Candidate did not pass review.")
                    if scope == "seal":
                        self._commit(transitions.seal(self._state, output_epoch=context.output_epoch),
                                     "plan_sealed")
                    else:
                        self._accept_reviewed_range(snapshot.context,candidate,observation,activity_seq)
                    return True

    def _accept_reviewed_range(self,context,candidate,observation,activity_seq):
        effects=compile_range(candidate,epoch=context.output_epoch,activity=activity_seq)
        try:
            update=(self._character_runtime.prepare_accept(context,candidate,observation,effects,
                    self._state.request_id) if self._character_runtime is not None else None)
        except DomainError:
            self._wardrobe_hold(context,'optional_ineligible')
            raise
        if update is not None:
            effects=update.admitted_effects
        if self._state.response_muted or self._state.response_mode == 'text_only':
            effects = tuple(replace(effect, cue_speech_id=None) for effect in effects
                            if effect.kind is EffectKind.SUBTITLE or
                            (effect.kind is not EffectKind.SPEECH and effect.cue_speech_id is None))
        if len(self._state.issued_effects)+len(effects)>self._limits.max_effects:
            raise DomainError("effect_capacity","Foundation effect budget reached.")
        state=transitions.accept_range(self._state,output_epoch=context.output_epoch,effects=effects)
        if state is not self._state:
            self._commit(state,"range_accepted")
            if update is not None:
                self._character_runtime.commit(update)
                self._commit(self._state, 'chapter_plan_projected')
        self._wardrobe_admitted(context,effects)

    def _conversation_current(self, snapshot, text_effects, speech_effects=()) -> bool:
        """Only this cue's monotonic subtitle receipts may arrive during event review.

        They cannot alter permissions or character state. Other presentation/audio,
        accepted-effect or branch drift holds events without another provider call.
        """
        if not snapshot_same_branch(self._state, snapshot):
            return False
        context = snapshot.context
        own_ids = {effect.id for effect in (*text_effects,*speech_effects)}
        return (self._state.active_grants == context.accepted_prefix
                and tuple(item for item in audio_context_progress(self._state.audio_progress)
                          if item.effect_id not in own_ids)
                == tuple(item for item in context.audio_progress if item.effect_id not in own_ids)
                and tuple(effect for effect in self._state.presented_effects if effect.id not in own_ids)
                == tuple(effect for effect in context.presented_effects if effect.id not in own_ids)
                and all(effect in self._state.presented_effects for effect in context.presented_effects))

    def _accept_conversation_effects(self, effects, context):
        if not effects:
            return
        if len(self._state.issued_effects) + len(effects) > self._limits.max_effects:
            raise DomainError('effect_capacity', 'Foundation effect budget reached.')
        self._commit(transitions.accept_range(self._state, output_epoch=context.output_epoch,
                                             effects=effects), 'range_accepted')

    async def _conversation_candidate(self, context, activity_seq, candidate, generation_span, *, tool_image_intent=None, native_dialogue=None):
        """Publish the complete text cue before evaluating optional event proposals.

        Text is schema-checked provider output, never labeled JEV-approved. A held
        event cannot revoke it. No completed action is invented from a proposal.
        """
        if (type(candidate) is not CandidateRange or type(candidate.effects) is not tuple
                or not (1 <= len(candidate.effects) <= 8 or not candidate.effects and tool_image_intent is not None)
                or any(type(effect) is not EffectProposal or type(effect.kind) is not EffectKind
                       or type(effect.value) is not str or not effect.value.strip()
                       or len(effect.value) > 4096 for effect in candidate.effects)):
            raise DomainError('invalid_response', 'Invalid complete conversation cue.')
        async with self._lock:
            if (self._closed or self._state.request_id is None
                    or (self._state.output_epoch,self._state.activity_seq)!=(context.output_epoch,activity_seq)):
                return False
            candidate = self._prepare_image_candidate(context,candidate,tool_image_intent=tool_image_intent)
        candidate_data(candidate)  # Reject malformed proposal envelopes before any grant.
        async with self._lock:
            photo_attempt = self._begin_fixed_photo(candidate,context,activity_seq)
            candidate = filter_visual_events(context, candidate, self._state)
            if photo_attempt is not None and not any(e.kind is EffectKind.MEDIA and e.value == 'trip_photo' for e in candidate.effects):
                reason = ('unavailable' if not event_available(EffectProposal(EffectKind.MEDIA,'trip_photo'),context.character_assets)
                          else 'dismissed' if self._state.activity_seq <= self._state.photo_dismissed_through_activity
                          else 'already_visible')
                self._update_fixed_photo(context,photo_attempt,'held','readiness',reason)
                photo_attempt = None
            elif photo_attempt is not None:
                self._photo_diagnostic('readiness', self._state.fixed_photo)
        text_candidate = replace(candidate, effects=tuple(effect for effect in candidate.effects
            if effect.kind is EffectKind.SUBTITLE), story_proposal_json=None, affect_proposal_json=None, image_proposal_json=None, image_intent=None)
        speech_candidate = replace(candidate, effects=tuple(effect for effect in candidate.effects
            if effect.kind is EffectKind.SPEECH), story_proposal_json=None, affect_proposal_json=None, image_proposal_json=None, image_intent=None)
        event_candidate = replace(candidate, effects=tuple(effect for effect in candidate.effects
            if effect.kind is not EffectKind.SPEECH))
        # Independent compilation prevents uncertain/disabled speech from holding
        # an already available caption behind a cue_speech_id that will never play.
        text_effects = (compile_range(text_candidate, epoch=context.output_epoch, activity=activity_seq)
                        if text_candidate.effects else ())
        pending_proposals = tuple(effect for effect in event_candidate.effects
                                 if effect.kind is not EffectKind.SUBTITLE)
        pending_effects = (compile_range(replace(event_candidate,effects=pending_proposals),
            epoch=context.output_epoch,activity=activity_seq) if pending_proposals else ())
        text_iter, event_iter = iter(text_effects), iter(pending_effects)
        event_effects = tuple(next(text_iter) if effect.kind is EffectKind.SUBTITLE else next(event_iter)
                              for effect in event_candidate.effects)
        needs_events = bool(pending_proposals or candidate.story_proposal_json
                            or candidate.affect_proposal_json or candidate.image_intent)
        needs_speech = bool(speech_candidate.effects and self._speech_synthesis is not None
                            and context.response_mode == 'voice')
        speech_effects = ()
        await self._ensure_context_current(context)
        async with self._lock:
            if (self._closed or self._state.request_id is None
                    or (self._state.output_epoch,self._state.activity_seq)!=(context.output_epoch,activity_seq)):
                return False
            if photo_attempt is not None:
                photo = next(e for e in pending_effects if e.kind is EffectKind.MEDIA and e.value == 'trip_photo')
                self._update_fixed_photo(context,photo_attempt,'pending','review',effect_id=photo.id)
            self._accept_conversation_effects(text_effects, context)
            if native_dialogue is not None and self._character_runtime is not None:
                from mira.application.native_character_tools import bind_native_dialogue
                try:
                    update=bind_native_dialogue(self._character_runtime,context,native_dialogue,
                        text_effects,self._state.request_id,activity_seq)
                except (DomainError,ValueError,TypeError,KeyError):
                    update=None  # Optional progression never erases legal dialogue.
                if update is not None:
                    self._character_runtime.commit(update)
                    if native_dialogue.transition_id=='x.ask_role':
                        self._character_runtime._native_role_question=(
                            text_effects[0].id,context.output_epoch,self._state.request_id)
                    self._commit(self._state,'native_dialogue_plan_projected')
            if needs_speech and self._state.response_mode == 'voice' and not self._state.response_muted:
                speech_effects = compile_range(speech_candidate, epoch=context.output_epoch, activity=activity_seq)
                self._accept_conversation_effects(speech_effects, context)
        if not needs_events:
            return True
        # Finite fictional chapter proposals are local, typed plans. Ordinary
        # chapter narration never waits for a second semantic approval. Existing
        # content admission, issued effects, capacity, Stop and receipt gates stay.
        async with self._lock:
            if (self._closed or self._state.request_id is None
                    or (self._state.output_epoch,self._state.activity_seq)!=(context.output_epoch,activity_seq)):
                return False
            if (self._character_runtime is not None and
                    self._character_runtime.local_chapter_candidate(context,event_candidate,self._state.request_id)):
                try:
                    update = self._character_runtime.prepare_local_chapter_accept(
                        context,event_candidate,event_effects,self._state.request_id)
                except (DomainError,ValueError):
                    return True  # Hold this optional action; keep the published text.
                text_ids={effect.id for effect in text_effects}
                self._accept_conversation_effects(tuple(effect for effect in update.admitted_effects
                    if effect.id not in text_ids),context)
                self._character_runtime.commit(update)
                for receipt in self._state.receipts:
                    effect=next((effect for effect in text_effects if effect.id==receipt.effect_id),None)
                    if effect is not None:self._character_runtime.acknowledge(receipt,effect)
                self._commit(self._state, 'chapter_plan_projected')
                self._hold_image_candidate(candidate,context)
                self._update_fixed_photo(context,photo_attempt,'held','review','optional_ineligible')
                return True
        async with self._semantic_lock:
            async with self._lock:
                if (self._closed or self._state.request_id is None
                        or (self._state.output_epoch,self._state.activity_seq)!=(context.output_epoch,activity_seq)):
                    return False
                # Outcome feedback is the same bounded evidence seen by generation.
                # This candidate's live pending status is UI metadata, not new review authority.
                # Current presentation receipts/visibility still come from the real state.
                snapshot = self._decision_owner.snapshot(replace(self._state,fixed_photo=context.fixed_photo),self._decision_inputs,
                    memory_packet=context.memory_packet,character_story=context.character_story,
                    character_assets=context.character_assets, request_context=context.request_context,
                    visual_action_uncertain=context.visual_action_uncertain,
                    memory_recall_status=context.memory_recall_status,
                    conversation_recall=context.conversation_recall,
                    conversation_recall_status=context.conversation_recall_status)
                if snapshot is None:
                    self._hold_image_candidate(candidate,context)
                    self._wardrobe_hold(context,'review_unknown')
                    self._update_fixed_photo(context,photo_attempt,'held','review','review_unknown')
                    return True  # No event authority; already published text stays available.
            input_span=DiagnosticSpan(self._diagnostics,DiagnosticStage.INPUT_REVIEW,generation_span.context)
            try:
                observation=await self._semantic_review.observe(snapshot)
                if type(observation) is not InputDecisionObservation:
                    raise DomainError('invalid_response','Invalid optional input observation.')
                await self._ensure_context_current(context)
                if asyncio.current_task().cancelling(): raise asyncio.CancelledError
            except asyncio.CancelledError:
                input_span.finish(DiagnosticOutcome.CANCELLED,code=DiagnosticCode.CANCELLED)
                raise
            except Exception as error:
                input_span.finish(DiagnosticOutcome.FAILED,code=classify_failure(error).code)
                async with self._lock:
                    self._hold_image_candidate(candidate,context)
                    self._wardrobe_hold(context,'review_failed')
                    self._update_fixed_photo(context,photo_attempt,'held','review','review_failed')
                return True
            input_span.finish(DiagnosticOutcome.SUCCEEDED if observation.status is InputDecisionStatus.OBSERVED
                else DiagnosticOutcome.FAILED,code=None if observation.status is InputDecisionStatus.OBSERVED
                else classify_reason(observation.reason_code).code)
            async with self._lock:
                if self._closed or not self._conversation_current(snapshot,text_effects,speech_effects):
                    self._hold_image_candidate(candidate,context)
                    self._wardrobe_hold(context,'context_changed')
                    self._update_fixed_photo(context,photo_attempt,'held','review','review_unknown')
                    return snapshot_same_branch(self._state,snapshot) and not self._closed
            review_span=DiagnosticSpan(self._diagnostics,DiagnosticStage.OUTPUT_REVIEW,generation_span.context)
            try:
                reviewed=await self._semantic_review.review(snapshot,event_candidate,observation)
                if type(reviewed) is not ReviewObservation:
                    raise DomainError('invalid_response','Invalid optional event observation.')
                await self._ensure_context_current(context)
                if asyncio.current_task().cancelling(): raise asyncio.CancelledError
            except asyncio.CancelledError:
                review_span.finish(DiagnosticOutcome.CANCELLED,code=DiagnosticCode.CANCELLED)
                raise
            except Exception as error:
                review_span.finish(DiagnosticOutcome.FAILED,code=classify_failure(error).code)
                async with self._lock:
                    self._hold_image_candidate(candidate,context)
                    self._wardrobe_hold(context,'review_failed')
                    self._update_fixed_photo(context,photo_attempt,'held','review','review_failed')
                return True
            review_span.finish(DiagnosticOutcome.SUCCEEDED if reviewed.verdict is ReviewVerdict.ALLOW
                else DiagnosticOutcome.FAILED,code=None if reviewed.verdict is ReviewVerdict.ALLOW else
                DiagnosticCode.BLOCKED if reviewed.verdict is ReviewVerdict.REJECT else
                classify_reason(reviewed.reason_code).code,response_validation=reviewed.response_diagnostics)
            async with self._lock:
                if (self._state.photo_visibility_revision != snapshot.context.photo_visibility_revision
                        or self._state.photo_visible != snapshot.context.photo_visible):
                    self._hold_image_candidate(candidate,context)
                    self._wardrobe_hold(context,'context_changed')
                    self._update_fixed_photo(context,photo_attempt,'held','review','review_unknown')
                    return snapshot_same_branch(self._state,snapshot) and not self._closed
                if self._closed or not self._conversation_current(snapshot,text_effects,speech_effects):
                    self._hold_image_candidate(candidate,context)
                    self._wardrobe_hold(context,'context_changed')
                    self._update_fixed_photo(context,photo_attempt,'held','review','review_unknown')
                    return snapshot_same_branch(self._state,snapshot) and not self._closed
                if reviewed.verdict is not ReviewVerdict.ALLOW:
                    self._hold_image_candidate(candidate,context)
                    reason = (
                        'review_rejected' if reviewed.verdict is ReviewVerdict.REJECT else
                        'review_failed' if (observation.status in (InputDecisionStatus.UNAVAILABLE,InputDecisionStatus.INVALID)
                            or is_jev_transport_reason(reviewed.reason_code)
                            or jev_resource_failure_code(reviewed.reason_code) is not None
                            or classify_reason(reviewed.reason_code).code is DiagnosticCode.INVALID_RESPONSE)
                        else 'review_unknown')
                    self._wardrobe_hold(context,reason)
                    self._update_fixed_photo(context,photo_attempt,'held','review',reason)
                    return True
                self._wardrobe_decision(context,reviewed.verdict)
                try:
                    update = (self._character_runtime.prepare_accept(snapshot.context,event_candidate,
                        reviewed,event_effects,self._state.request_id,hold_optional_failures=True)
                        if self._character_runtime is not None else None)
                except DomainError:
                    self._hold_image_candidate(candidate,context)
                    self._wardrobe_hold(context,'optional_ineligible')
                    self._update_fixed_photo(context,photo_attempt,'held','review','optional_ineligible')
                    return True  # Invalid/unavailable optional reduction grants nothing.
                admitted = update.admitted_effects if update is not None else event_effects
                text_ids={effect.id for effect in text_effects}
                self._accept_conversation_effects(tuple(effect for effect in admitted if effect.id not in text_ids),context)
                if photo_attempt is not None:
                    admitted_photo = any(e.kind is EffectKind.MEDIA and e.value == 'trip_photo' for e in admitted)
                    self._update_fixed_photo(context,photo_attempt,'granted' if admitted_photo else 'held',
                        'grant', None if admitted_photo else 'optional_ineligible')
                self._wardrobe_admitted(context,admitted)
                if candidate.image_intent is not None:
                    self._start_story_image(candidate.image_intent)
                if update is not None:
                    self._character_runtime.commit(update)
                    # A real subtitle receipt may predate the optional invitation
                    # approval. Reconcile the exact issued identity, never fabricate it.
                    for receipt in self._state.receipts:
                        effect=next((effect for effect in text_effects if effect.id==receipt.effect_id),None)
                        if effect is not None:self._character_runtime.acknowledge(receipt,effect)
                    self._commit(self._state, 'chapter_plan_projected')
            return True

    @staticmethod
    def _wardrobe_effect(effect):
        return effect.kind is EffectKind.POSE and type(effect.value) is str and effect.value in WARDROBE_CONTROLS

    def _wardrobe_event(self, phase, state, epoch, activity, outfit=None, count=0,
                        reason=None, *, effect_id=None, acknowledged=None):
        # Like emit_safely, invalid/unavailable diagnostics must not affect a turn.
        if self._diagnostics is None: return
        try:
            if (reason is None and phase in ('readiness','grant') and state in ('ready','granted')
                    and self._character_runtime is not None
                    and outfit == 'outfit_'+self._character_runtime.runtime.story.current_outfit):
                reason = 'already_current'
            value = SafeWardrobeDiagnostic(phase,state,epoch,activity,outfit,count,reason,acknowledged)
            outcome = (DiagnosticOutcome.CANCELLED if state == 'cancelled' else
                       DiagnosticOutcome.DROPPED if state == 'held' else DiagnosticOutcome.SUCCEEDED)
            emit_safely(self._diagnostics,DiagnosticEvent(DiagnosticStage.WARDROBE,outcome,
                diagnostic_context(session_id=self._state.session_id,turn_id=str(epoch),effect_id=effect_id),
                kind=DiagnosticKind.STATE_CHANGED,wardrobe=value))
        except Exception:
            pass

    def _wardrobe_candidate(self, context, activity, candidate):
        if (self._closed or (context.output_epoch,activity) !=
                (self._state.output_epoch,self._state.activity_seq)): return
        controls = tuple(e.value for e in candidate.effects if self._wardrobe_effect(e))
        self._wardrobe_waiting = (context.output_epoch,activity,controls)
        for value in controls or (None,):
            self._wardrobe_event('candidate','proposed' if controls else 'absent',
                context.output_epoch,activity,value,len(controls),None if controls else 'no_proposal')

    def _wardrobe_ready(self, context, activity, original, prepared):
        if (self._closed or (context.output_epoch,activity) !=
                (self._state.output_epoch,self._state.activity_seq)): return
        original_controls = tuple(e.value for e in original.effects if self._wardrobe_effect(e))
        controls = tuple(e.value for e in prepared.effects if self._wardrobe_effect(e))
        for value in original_controls:
            if value not in controls:
                self._wardrobe_event('readiness','held',context.output_epoch,activity,value,1,'unavailable')
        for value in controls:
            self._wardrobe_event('readiness','ready',context.output_epoch,activity,value,len(controls),
                'story_compiled' if value not in original_controls else None)
        if not original_controls and not controls:
            self._wardrobe_event('readiness','absent',context.output_epoch,activity,reason='no_proposal')
        self._wardrobe_waiting = (context.output_epoch,activity,controls)

    def _wardrobe_hold(self, context, reason, *, phase='review'):
        epoch,activity,controls = self._wardrobe_waiting
        if (epoch,activity) != (context.output_epoch,self._state.activity_seq): return
        for value in controls:
            self._wardrobe_event(phase,'held',epoch,activity,value,len(controls),reason)
        self._wardrobe_waiting = (0,0,())

    def _wardrobe_decision(self, context, verdict):
        if verdict is not ReviewVerdict.ALLOW:
            self._wardrobe_hold(context,'review_rejected' if verdict is ReviewVerdict.REJECT else 'review_unknown')
            return
        epoch,activity,controls = self._wardrobe_waiting
        if (epoch,activity) != (context.output_epoch,self._state.activity_seq): return
        for value in controls:
            self._wardrobe_event('review','allowed',epoch,activity,value,len(controls))

    def _wardrobe_admitted(self, context, effects):
        epoch,activity,controls = self._wardrobe_waiting
        if (epoch,activity) != (context.output_epoch,self._state.activity_seq): return
        admitted = tuple(e.value for e in effects if self._wardrobe_effect(e))
        for value in controls:
            if value not in admitted:
                self._wardrobe_event('grant','held',epoch,activity,value,len(controls),'optional_ineligible')
        self._wardrobe_waiting = (0,0,())

    def _cancel_wardrobe(self):
        epoch,activity,controls = self._wardrobe_waiting
        for value in controls:
            self._wardrobe_event('cancel','cancelled',epoch,activity,value,len(controls),'cancelled')
        self._wardrobe_waiting = (0,0,())
        for effect in self._state.active_grants:
            if self._wardrobe_effect(effect) and not any(r.effect_id == effect.id for r in self._state.receipts):
                self._wardrobe_event('cancel','cancelled',effect.output_epoch,effect.activity_seq,
                    effect.value,1,'cancelled',effect_id=effect.id)

    def _photo_diagnostic(self, phase, status, *, counts=None):
        value = SafeFixedPhotoDiagnostic(phase,status.state,status.attempt_seq,
            status.output_epoch,status.activity_seq,status.reason,**(counts or {}))
        outcome = (DiagnosticOutcome.FAILED if status.state == 'failed' else
                   DiagnosticOutcome.CANCELLED if status.state == 'cancelled' else
                   DiagnosticOutcome.DROPPED if status.state == 'held' else DiagnosticOutcome.SUCCEEDED)
        emit_safely(self._diagnostics,DiagnosticEvent(DiagnosticStage.FIXED_PHOTO,outcome,
            diagnostic_context(session_id=self._state.session_id,turn_id=str(status.output_epoch),
                effect_id=status.effect_id),kind=DiagnosticKind.STATE_CHANGED,fixed_photo=value))

    def _set_fixed_photo(self, status, phase):
        if status == self._state.fixed_photo: return
        self._commit(replace(self._state,revision=self._state.revision+1,fixed_photo=status),'fixed_photo_status')
        self._photo_diagnostic(phase,status)

    def _begin_fixed_photo(self, candidate, context, activity_seq):
        if (self._closed or (self._state.output_epoch,self._state.activity_seq) != (context.output_epoch,activity_seq)):
            return None
        count = sum(e.kind is EffectKind.MEDIA and e.value == 'trip_photo' for e in candidate.effects)
        counts = {kind.value+'_count':sum(e.kind is kind for e in candidate.effects) for kind in EffectKind}
        counts['fixed_photo_count'] = count
        if not count:
            status = FixedPhotoStatus(output_epoch=context.output_epoch,activity_seq=activity_seq)
            self._photo_diagnostic('candidate',status,counts=counts)
            return None
        status = FixedPhotoStatus('pending',attempt_seq=self._state.fixed_photo.attempt_seq+1,
            output_epoch=context.output_epoch,activity_seq=activity_seq)
        self._set_fixed_photo(status,'candidate')
        self._photo_diagnostic('candidate',status,counts=counts)
        return status.attempt_seq

    def _update_fixed_photo(self, context, attempt, state, phase, reason=None, *, effect_id=None):
        current = self._state.fixed_photo
        if (attempt is None or self._closed or current.attempt_seq != attempt
                or current.state not in FIXED_PHOTO_PENDING
                or (current.output_epoch,current.activity_seq) != (self._state.output_epoch,self._state.activity_seq)
                or current.output_epoch != context.output_epoch): return
        self._set_fixed_photo(replace(current,state=state,reason=reason,
            effect_id=effect_id if effect_id is not None else current.effect_id),phase)

    def _cancel_fixed_photo(self):
        status = self._state.fixed_photo
        if status.state in ('pending','granted','preparing'):
            self._set_fixed_photo(replace(status,state='cancelled',reason='cancelled'),'cancel')
        # A submitted receipt may still arrive under the existing presentation fence.
        # Its absence is neither proof of display nor proof of rendering failure.

    async def fixed_photo_progress(self, *, effect_id, digest, output_epoch, activity_seq, outcome):
        if outcome not in ('preparing','preparation_failed','presentation_failed','receipt_pending'):
            raise DomainError('invalid_input','Invalid fixed illustration progress.')
        async with self._lock:
            if self._closed: raise DomainError('session_closed','Session has closed.')
            status = self._state.fixed_photo
            effect = next((e for e in self._state.active_grants if e.id == effect_id),None)
            if (effect is None or effect.kind is not EffectKind.MEDIA or effect.value != 'trip_photo'
                    or (effect.digest,effect.output_epoch,effect.activity_seq) != (digest,output_epoch,activity_seq)
                    or (output_epoch,activity_seq) != (self._state.output_epoch,self._state.activity_seq)
                    or status.effect_id != effect_id or status.state not in ('granted','preparing','receipt_pending')
                    or any(r.effect_id == effect_id for r in self._state.receipts)):
                return self._state
            if status.state == 'receipt_pending': return self._state
            state = 'failed' if outcome.endswith('_failed') else outcome
            reason = outcome if state == 'failed' else 'receipt_unconfirmed' if state == 'receipt_pending' else None
            self._set_fixed_photo(replace(status,state=state,reason=reason),
                'presentation' if outcome in ('presentation_failed','receipt_pending') else 'preparation')
            return self._state

    def _image_status(self,state,*,failure_code=None,request=None,artifact=None,scene_id=None):
        previous=self._state.story_image
        same=request is None or request.request_id==previous.request_id
        status=replace(previous if same else StoryImageStatus('bounded_fiction','idle'),state=state,
            capability='bounded_fiction' if self._story_images else 'unavailable',
            request_id=request.request_id if request else previous.request_id,scene_id=scene_id or previous.scene_id,
            resource_id=artifact.resource_id if artifact else None if request else previous.resource_id,
            content_digest=artifact.content_digest if artifact else None if request else previous.content_digest,
            failure_code=failure_code)
        if self._story_images is not None and status.request_id:self._story_images.update_phase(status.request_id,state)
        facts=self._story_images.facts(self._state) if self._story_images else ()
        self._commit(replace(self._state,revision=self._state.revision+1,story_image=status,
            story_image_facts=facts),'story_image_status')
        self._emit_image_readiness(replace(runtime_image_readiness(self._story_images,
            output_epoch=self._state.output_epoch,activity_seq=self._state.activity_seq),phase='operation'))
        if state=='failed':self._queue_image_completion()

    def _image_context_facts(self):
        return tuple(f for f in self._state.story_image_facts if self._image_scope_current(f.request_id))

    def _set_image_completion(self,state):
        image=self._state.story_image
        self._image_completion_claims[image.request_id]=state
        if self._story_images is not None:self._story_images.completion_state=state
        self._commit(replace(self._state,revision=self._state.revision+1,
            story_image=replace(image,completion_state=state)),'story_image_completion_'+state)
        self._emit_image_readiness(replace(runtime_image_readiness(self._story_images,
            output_epoch=self._state.output_epoch,activity_seq=self._state.activity_seq),phase='operation'))

    def _queue_image_completion(self):
        image=self._state.story_image
        if image.request_id in self._image_completion_claims or not self._image_scope_current(image.request_id):return
        event=next((f for f in self._state.story_image_facts if f.request_id==image.request_id and f.state in ('presented','failed')),None)
        if event is None:return
        self._image_completion_events[event.request_id]=event
        self._story_images.update_phase(event.request_id,event.state);self._story_images.completion_state='pending'
        self._commit(replace(self._state,revision=self._state.revision+1,
            story_image=replace(image,completion_state='pending',completion_available=
                getattr(self._tool_generation,'supports_image_completion',False) is True)), 'story_image_completion_pending')
        self._emit_image_readiness(replace(runtime_image_readiness(self._story_images,
            output_epoch=self._state.output_epoch,activity_seq=self._state.activity_seq),phase='operation'))

    def _take_image_completions(self):
        events=tuple(event for identity,event in self._image_completion_events.items()
            if identity not in self._image_completion_claims and self._image_scope_current(identity))
        for event in events:self._image_completion_claims[event.request_id]='context_consumed'
        if any(e.request_id==self._state.story_image.request_id for e in events):self._set_image_completion('context_consumed')
        return events

    def _cancel_image_completion(self):
        image=self._state.story_image
        task=self._image_completion_tasks.get(image.request_id)
        if task is not None and task is not asyncio.current_task():task.cancel()
        if image.completion_state in ('pending','requested','granted'):self._set_image_completion('cancelled')

    async def complete_story_image(self,*,request_id,parent_request_id,output_epoch,activity_seq,presented_effect_id):
        async with self._lock:
            image=self._state.story_image
            if (self._closed or self._state.request_id!=parent_request_id
                    or (self._state.output_epoch,self._state.activity_seq)!=(output_epoch,activity_seq)
                    or image.request_id!=request_id):
                raise DomainError('image_completion_stale','Image completion origin changed.')
            if request_id in self._image_completion_claims:return self._state
            event=self._image_completion_events.get(request_id)
            if (not self._state.sealed or self._state.phase is not Phase.IDLE
                    or self._state.chapter_projection is not None and self._state.chapter_projection.pending_transition is not None
                    or event is None or event.presented_effect_id!=presented_effect_id
                    or event.state not in ('presented','failed') or not self._image_scope_current(request_id)
                    or self._current_generation_context is None
                    or self._character_runtime is not None and self._character_runtime._native_role_question is not None
                    or getattr(self._tool_generation,'supports_image_completion',False) is not True):
                raise DomainError('image_completion_unavailable','No current receipted idle image completion.')
            if len(self._state.issued_effects)+2>self._limits.max_effects:
                self._set_image_completion('failed');return self._state
            context=replace(self._refresh_tool_context(self._current_generation_context,consume_image_completions=False),
                story_image_completions=(event,),story_image_completion_only=True)
            self._current_generation_context=context;self._set_image_completion('requested')
            task=asyncio.create_task(self._run_image_completion(context,activity_seq,request_id,parent_request_id))
            self._image_completion_tasks[request_id]=task;self._tasks.add(task)
            def done(completed):
                self._tasks.discard(completed)
                if self._image_completion_tasks.get(request_id) is completed:self._image_completion_tasks.pop(request_id,None)
                if not completed.cancelled():completed.exception()
            task.add_done_callback(done)
            return self._state

    async def _run_image_completion(self,context,activity_seq,request_id,parent_request_id):
        outcome='failed'
        try:
            async with asyncio.timeout(self._limits.timeout_seconds):
                await self._ensure_context_current(context)
                candidate=dialogue_only(await self._tool_generation.generate_image_completion(context))
                candidate_data(candidate)
                if sum(p.kind is EffectKind.SUBTITLE for p in candidate.effects)!=1 or any(len(p.value)>500 for p in candidate.effects):
                    raise DomainError('invalid_response','Invalid image completion dialogue.')
                await self._ensure_context_current(context)
                async with self._lock:
                    if (self._closed or asyncio.current_task().cancelling()
                            or self._state.story_image.request_id!=request_id):outcome='cancelled';return
                    if not self._image_scope_current(request_id):outcome='cancelled';return
                    proposals=tuple(p for p in candidate.effects if p.kind is EffectKind.SUBTITLE or
                        self._speech_synthesis is not None and self._state.response_mode=='voice' and not self._state.response_muted)
                    effects=tuple(e for proposal in proposals for e in compile_range(replace(candidate,effects=(proposal,)),
                        epoch=context.output_epoch,activity=activity_seq))
                    if len(self._state.issued_effects)+len(effects)>self._limits.max_effects:
                        raise DomainError('effect_capacity','Image completion effect budget reached.')
                    state=transitions.accept_image_completion(self._state,request_id=request_id,parent_request_id=parent_request_id,
                        output_epoch=context.output_epoch,activity_seq=activity_seq,effects=effects)
                    self._commit(state,'story_image_completion_granted')
                    if state.story_image.completion_state=='granted':
                        self._image_completion_claims[request_id]='granted';self._story_images.completion_state='granted'
        except asyncio.CancelledError:
            outcome='cancelled';raise
        except Exception:
            outcome='failed' if self._image_scope_current(request_id) else 'cancelled'
        finally:
            async with self._lock:
                self._image_completion_tasks.pop(request_id,None)
                if self._state.story_image.request_id==request_id and self._state.story_image.completion_state=='requested':
                    self._set_image_completion(outcome)

    def _hold_image_candidate(self, candidate, context):
        """An uncertain optional review ends only its pending image operation."""
        if self._closed or context.output_epoch!=self._state.output_epoch:
            return
        intent=candidate.image_intent
        status=self._state.story_image
        if intent is not None and status.state=='pending':
            key=(self._state.request_id,self._state.output_epoch,intent.specification_digest)
            if self._image_review_intents.get(key)==status.request_id:
                self._image_status('held',failure_code='review')

    def _prepare_image_candidate(self,context,candidate,*,tool_image_intent=None):
        if candidate.image_proposal_json is None and tool_image_intent is None:
            return replace(candidate,image_intent=None)
        branch=(self._state.request_id,self._state.output_epoch)
        if self._state.story_image.state in ('generating','reviewing'):
            return replace(candidate,image_proposal_json=None,image_intent=None)
        # Deduplicate before review/reservation, including prior REJECT/UNKNOWN.
        # A later duplicate or changed suggestion cannot relabel an active job.
        if any(key[:2]==branch for key in self._image_review_intents):
            return replace(candidate,image_proposal_json=None,image_intent=None)
        try:
            if self._story_images is None:raise ValueError('unavailable')
            if self._state.activity_seq<=self._state.image_dismissed_through_activity:
                raise ValueError('photo_dismissed')
            if tool_image_intent is None:
                proposal=parse_image_proposal_json(candidate.image_proposal_json)
                intent=compile_image_intent(proposal,context.character_story)
            else:
                intent=tool_image_intent
            request_id=str(uuid4())
            self._image_review_intents[(*branch,intent.specification_digest)]=request_id
            status=StoryImageStatus('bounded_fiction','pending',request_id,intent.scene_id)
            self._commit(replace(self._state,revision=self._state.revision+1,
                story_image=status),'story_image_pending_review')
            return replace(candidate,image_intent=intent)
        except (ValueError,TypeError,UnicodeError,RecursionError):
            self._image_status('held' if self._story_images else 'unavailable',
                               failure_code='ineligible' if self._story_images else 'unavailable')
            return replace(candidate,image_proposal_json=None,image_intent=None)

    def _cancel_story_images(self,reason='scope_changed'):
        self._cancel_image_completion()
        for task in tuple(self._image_tasks):task.cancel()
        runtime=self._story_images
        if runtime is None:return
        runtime.job_event_reason=reason
        for reservation in self._state.image_reservations:runtime.cancel(reservation.request_id)
        self._commit(replace(self._state,revision=self._state.revision+1,permit_revision=self._state.permit_revision+1,
            image_cancellation_generation=self._state.image_cancellation_generation+1,
            active_grants=tuple(e for e in self._state.active_grants if not parse_generated_photo(e.value))), 'story_images_revoked')
        if self._state.story_image.state in ('pending','generating','reviewing','qualified'):
            self._image_status('cancelled',failure_code='cancelled')

    def _image_scope_current(self,request_id):
        origin=self._image_origins.get(request_id)
        if origin is None or self._character_runtime is None or self._story_images is None:return False
        story,assets,admission,memory,conversation=origin
        current=self._character_runtime.runtime.project().projection
        return (story is not None and admission==self._story_images.admission and admission.authorized_fiction_only
            and memory is self._memory_binding and conversation is self._conversation_binding
            and not getattr(conversation,'_revoked',False)
            and evidence_digest(self._character_runtime.runtime.definition)==self._character_runtime._definition_digest
            and assets==self._character_runtime.readiness
            and (story.scope_binding_hash,story.graph_hash,story.canon_hash,story.canon_revision)==
                (current.scope_binding_hash,current.graph_hash,current.canon_hash,current.canon_revision)
            and set(story.released_story_events).issubset(current.released_story_events))

    def _image_current(self,reservation):
        state=self._state
        return (not self._closed and self._story_images.is_reserved(reservation.request_id)
            and reservation in state.image_reservations and not reservation.consumed
            and reservation.session_id==state.session_id
            and reservation.cancellation_generation==state.image_cancellation_generation)

    def _grant_ready_story_image(self):
        if self._closed or self._state.request_id is None:return
        for reservation in self._state.image_reservations:
            if (not reservation.qualified_resource_id
                    or reservation.cancellation_generation!=self._state.image_cancellation_generation):continue
            if reservation.consumed:
                if (any(e.id==reservation.current_effect_id for e in self._state.active_grants)
                        or any(parse_generated_photo(e.value)==(reservation.qualified_resource_id,reservation.qualified_content_digest)
                            for e in self._state.presented_effects)):continue
                old=reservation;reservation=replace(reservation,consumed=False)
                self._commit(replace(self._state,revision=self._state.revision+1,
                    image_reservations=tuple(reservation if r==old else r for r in self._state.image_reservations)),
                    'story_image_presentation_released')
            if not self._state.sealed and reservation.parent_request_id!=self._state.request_id:continue
            if not self._image_scope_current(reservation.request_id):self._cancel_story_images();return
            if len(self._state.issued_effects)>=self._limits.max_effects:return
            effect=compile_generated_media(reservation.qualified_resource_id,reservation.qualified_content_digest,
                epoch=self._state.output_epoch,activity=self._state.activity_seq)
            self._commit(transitions.accept_generated_media(self._state,reservation=reservation,effect=effect),'story_image_current_grant')

    def _track_image_task(self, coroutine):
        task=asyncio.create_task(coroutine);self._image_tasks.add(task)
        def done(completed):
            self._image_tasks.discard(completed)
            if not completed.cancelled():completed.exception()
        task.add_done_callback(done)
        return task

    def _start_story_image(self,intent):
        key=(self._state.request_id,self._state.output_epoch,intent.specification_digest)
        request_id=self._image_review_intents.get(key)
        if self._story_images is None or request_id is None:return
        if len(self._image_tasks)+2>4:
            self._image_status('held',failure_code='budget');return
        try:
            current=self._character_runtime.runtime.project().projection
            if current.canon_hash != intent.canon_hash or current.canon_revision != intent.canon_revision:
                self._image_status('held',failure_code='ineligible');return
            request=self._story_images.reserve(intent,self._state,request_id=request_id)
        except (ValueError,TypeError):
            self._image_status('held',failure_code='budget');return
        old_ready=tuple(r for r in self._state.image_reservations if r.qualified_resource_id
            and r.cancellation_generation==self._state.image_cancellation_generation
            and not any(parse_generated_photo(e.value)==(r.qualified_resource_id,r.qualified_content_digest)
                for e in self._state.presented_effects))
        if old_ready:
            for old in old_ready:
                self._story_images.cancel(old.request_id);self._image_completion_claims[old.request_id]='cancelled'
            self._commit(replace(self._state,revision=self._state.revision+1,permit_revision=self._state.permit_revision+1,
                image_cancellation_generation=self._state.image_cancellation_generation+1,
                active_grants=tuple(e for e in self._state.active_grants if not parse_generated_photo(e.value))), 'story_image_replaced')
        reservation=ImageReservation(request.request_id,request.parent_request_id,request.output_epoch,
            request.activity_seq,request.photo_visibility_revision,request.specification_digest,
            request.dependency_digest,request.policy_revision,session_id=self._state.session_id,
            cancellation_generation=self._state.image_cancellation_generation)
        reserved=transitions.reserve_generated_media(self._state,reservation)
        if reserved is self._state:
            self._story_images.release(request.request_id)
            self._image_status('cancelled',failure_code='cancelled');return
        self._commit(reserved,'story_image_reserved')
        self._image_status('generating',request=request,scene_id=intent.scene_id)
        context=self._current_generation_context
        self._image_origins[request.request_id]=(context.character_story,context.character_assets,
            self._story_images.admission,self._memory_binding,self._conversation_binding)
        self._track_image_task(self._run_story_image(request,reservation,intent))

    async def _run_story_image(self,request,reservation,intent):
        work=None
        async def phase(value):
            async with self._lock:
                if not self._image_current(reservation):return False
                self._image_status(value,request=request);return True
        try:
            work=self._track_image_task(self._story_images.generate_and_review(request,phase))
            done,_=await asyncio.wait((work,),timeout=self._story_images.admission.timeout_seconds)
            if not done:
                work.cancel();raise TimeoutError
            artifact,description=work.result()
            async with self._lock:
                if not self._image_current(reservation):return
                if not self._image_scope_current(request.request_id):self._cancel_story_images();return
                qualified=transitions.qualify_generated_media(self._state,reservation=reservation,
                    resource_id=artifact.resource_id,content_digest=artifact.content_digest,
                    specification_digest=artifact.specification_digest,policy_revision=artifact.policy_revision)
                if qualified is self._state:return
                self._story_images.qualify(artifact,description)
                self._commit(replace(qualified,story_image_facts=self._story_images.facts(qualified)),'story_image_qualified')
                self._image_status('qualified',request=request,artifact=artifact)
                self._grant_ready_story_image()
        except asyncio.CancelledError:
            if work is not None:work.cancel()
            raise
        except ImageOperationAdmissionDenied as error:
            async with self._lock:
                if self._image_current(reservation):
                    self._image_status('held',request=request,
                        failure_code='budget' if error.reason=='budget' else 'ineligible')
        except Exception as error:
            async with self._lock:
                if self._image_current(reservation):
                    self._story_images.record_operation_failure(error, request_id=request.request_id)
                    self._image_status('failed',request=request,
                        failure_code='timeout' if isinstance(error,TimeoutError) else
                            'review' if self._state.story_image.state=='reviewing' else 'generation')
        finally:
            async with self._lock:
                status=self._state.story_image
                if (not self._closed and status.request_id==request.request_id
                        and status.state in ('pending','generating','reviewing')):
                    self._image_status('held',failure_code='ineligible')
                self._story_images.release(request.request_id,
                    'failed' if self._state.story_image.state=='failed' else 'cancelled')

    async def story_image_resource(self, *, resource_id, effect_id, digest, output_epoch, activity_seq, content_digest):
        async with self._lock:
            effect=next((e for e in self._state.active_grants if e.id==effect_id),None)
            if (self._closed or self._story_images is None or effect is None
                    or (effect.digest,effect.output_epoch,effect.activity_seq)!=(digest,output_epoch,activity_seq)
                    or (output_epoch,activity_seq)!=(self._state.output_epoch,self._state.activity_seq)
                    or parse_generated_photo(effect.value)!=(resource_id,content_digest)):
                raise DomainError('image_not_granted','There is no current image grant.')
            artifact=self._story_images.artifact(resource_id)
            if (artifact is None or not self._image_scope_current(artifact.request_id)
                    or artifact.content_digest!=content_digest
                    or hashlib.sha256(artifact.png).hexdigest()!=content_digest):
                raise DomainError('image_not_granted','There is no current image grant.')
            return artifact.png

    def _cancel_tool_turns(self):
        for task,turn in tuple(self._tool_turns.items()):
            # close is local and synchronous; no provider wait owns this lock.
            self._tool_turns.pop(task,None)
            try: turn.close()
            except Exception: pass
            task.cancel()

    def _tool_branch_current(self,context,activity_seq,request_id):
        task=asyncio.current_task()
        return (not self._closed and self._state.request_id==request_id
            and (self._state.output_epoch,self._state.activity_seq)==(context.output_epoch,activity_seq)
            and (self._native_tool_authority or self._state.activity_seq>self._state.photo_dismissed_through_activity)
            and task is not None and not task.cancelling() and task in self._tool_turns)

    def _refresh_tool_context(self,context,*,consume_image_completions=True):
        state=self._state
        return replace(context,accepted_prefix=state.active_grants,presented_effects=state.presented_effects,
            audio_progress=audio_context_progress(state.audio_progress),response_mode=state.response_mode,
            photo_visible=state.photo_visible,photo_visibility_revision=state.photo_visibility_revision,
            fixed_photo=state.fixed_photo,story_images=self._image_context_facts(),
            story_image_completions=(context.story_image_completions or self._take_image_completions()
                if consume_image_completions else context.story_image_completions),
            visual_action_uncertain=camera_uncertain(state),
            character_story=(self._character_runtime.runtime.project().projection
                if self._character_runtime is not None else context.character_story))

    def _emit_image_readiness(self, value):
        if value.phase=='operation' and self._state.story_image.state=='failed':
            provider_error=value.provider_observation in ('generation_error','review_error')
            value=replace(value,state='provider_error' if provider_error else 'held',reason='provider_error' if provider_error else 'operation_failed')
        emit_safely(self._diagnostics, DiagnosticEvent(DiagnosticStage.IMAGE_READINESS,
            DiagnosticOutcome.FAILED if value.state == 'provider_error' else DiagnosticOutcome.SUCCEEDED,
            diagnostic_context(session_id=self._state.session_id, turn_id=self._state.request_id),
            kind=DiagnosticKind.STATE_CHANGED, image_readiness=value))

    def _observe_image_tools(self, context, activity_seq, request_id, readiness, names, continuation):
        if not self._tool_branch_current(context, activity_seq, request_id): return
        # Continuation can observe changed runtime counters but can never advertise tools.
        if continuation:
            readiness = runtime_image_readiness(self._story_images,
                output_epoch=self._state.output_epoch, activity_seq=self._state.activity_seq)
        self._emit_image_readiness(advertised_image_readiness(readiness, tuple(n for n in names if n in ('show_photo','generate_story_image')),
            continuation=continuation))

    def _native_tool_observation(self, call, context, activity_seq):
        if not self._native_tool_authority:
            return None
        try:
            try:
                transition = parse_tool_arguments(call).get('transition_id')
            except (ValueError, TypeError, UnicodeError, RecursionError):
                transition = None
            chapter = context.character_story.chapter if context.character_story is not None else None
            return SafeNativeToolDiagnostic(call.name, 'requested', context.output_epoch, activity_seq,
                transition=transition, chapter_before=chapter.stage.value if chapter is not None else None,
                role_before=chapter.role_active if chapter is not None else None)
        except (ValueError, TypeError, AttributeError):
            return None

    def _emit_native_tool(self, observation, request_id, *, result=None, context=None, status=None, reason=None):
        if observation is None:
            return
        try:
            if result is not None:
                value = json.loads(result.output_json)
                status = value['status']
                reason = value.get('reason')
                reason = reason if reason is None or type(reason) is str and reason in TOOL_REASONS else 'other'
                if status == 'pending' and value.get('phase') == 'awaiting_dialogue':
                    reason = 'awaiting_dialogue'
                receipt_value = value.get('receipt')
                receipt_id = receipt_value.get('effect_id') if type(receipt_value) is dict else None
                effect = next((e for e in self._state.presented_effects if e.id == receipt_id), None)
                chapter = context.character_story.chapter if context.character_story is not None else None
                observation = replace(observation, status=status, reason=reason,
                    chapter_after=chapter.stage.value if chapter is not None else None,
                    role_after=chapter.role_active if chapter is not None else None,
                    receipt_kind=effect.kind.value if effect is not None else None)
            elif status is not None:
                # Cancellation carries the original operation identity and no new-epoch state.
                observation = replace(observation, status=status, reason=reason)
            outcome = (DiagnosticOutcome.STARTED if observation.status == 'requested' else
                DiagnosticOutcome.CANCELLED if observation.status == 'cancelled' else
                DiagnosticOutcome.FAILED if observation.status == 'failed' else DiagnosticOutcome.SUCCEEDED)
            emit_safely(self._diagnostics, DiagnosticEvent(DiagnosticStage.NATIVE_TOOL, outcome,
                diagnostic_context(session_id=self._state.session_id, turn_id=request_id),
                kind=DiagnosticKind.STATE_CHANGED, native_tool=observation))
        except (ValueError, TypeError, KeyError, AttributeError):
            pass

    async def _generation_candidates(self,context,activity_seq,span):
        if self._tool_generation is None:
            async for candidate in self._generation.generate(context):
                yield context,candidate,None
            return
        task=asyncio.current_task()
        async with self._lock:
            request_id=self._state.request_id
            role_reference=None
            if self._native_tool_authority and self._character_runtime is not None:
                question=self._character_runtime._native_role_question
                if question is not None and self._character_runtime.native_role_question_current(
                        context.output_epoch,context.presented_effects,request_id):
                    role_reference=question[:2]
            definitions=tool_definitions(context,self._state,self._story_images,
                review_available=self._native_tool_authority or self._semantic_review is not None and self._semantic_review.conversation_first,
                image_task_count=len(self._image_tasks),max_effects=self._limits.max_effects,
                native_authority=self._native_tool_authority,role_confirmation_reference=role_reference)
            turn=self._tool_generation.open_tool_turn(context,definitions)
            self._tool_turns[task]=turn
            readiness=image_tool_readiness(context,self._state,self._story_images,
                review_available=self._native_tool_authority or self._semantic_review is not None and self._semantic_review.conversation_first,
                image_task_count=len(self._image_tasks),max_effects=self._limits.max_effects)
            self._emit_image_readiness(readiness)
            observe=getattr(turn,'observe_tool_advertisement',None)
            if callable(observe):
                try:
                    observe(lambda names, continuation: self._observe_image_tools(context,activity_seq,
                        request_id,readiness,names,continuation))
                except Exception:
                    pass
        native_observation = None
        native_result_observed = False
        native_dialogue = None
        try:
            candidate=await turn.start()
            await self._ensure_context_current(context)
            async with self._lock:
                if not self._tool_branch_current(context,activity_seq,request_id): return
            if type(candidate) is GenerationToolCall:
                call=candidate
                native_observation = self._native_tool_observation(call, context, activity_seq)
                self._emit_native_tool(native_observation, request_id)
                if self._native_tool_authority and call.commentary is not None:
                    yield context,dialogue_only(call.commentary),None
                    await self._ensure_context_current(context)
                    async with self._lock:
                        if not self._tool_branch_current(context,activity_seq,request_id):return
                result,identity=await self._execute_tool(call,definitions,context,activity_seq,request_id,span)
                await self._ensure_context_current(context)
                async with self._lock:
                    if not self._tool_branch_current(context,activity_seq,request_id): return
                    if type(identity) is NativeToolIdentity:
                        native_dialogue=identity.dialogue_intent
                    if type(identity) in (int,str,NativeToolIdentity):
                        result=project_tool_result(call,self._state,identity)
                    elif identity is not None:
                        result=tool_result(call,'reused',state=self._state,receipt=identity)
                    context=self._refresh_tool_context(context)
                    self._current_generation_context=context
                    self._emit_native_tool(native_observation, request_id, result=result, context=context)
                    native_result_observed = True
                candidate=dialogue_only(await turn.continue_after_tool(result,context))
                await self._ensure_context_current(context)
                async with self._lock:
                    if not self._tool_branch_current(context,activity_seq,request_id): return
            if self._native_tool_authority:
                candidate=dialogue_only(candidate)
                if self._character_runtime is not None:
                    question=self._character_runtime._native_role_question
                    if question is not None and question[1]<context.output_epoch:
                        self._character_runtime._native_role_question=None
            # A story/question/invitation binds its one complete spoken cue.
            # Splitting it would let a partial caption acknowledge the whole beat.
            if self._tool_caption_chunker is None or native_dialogue is not None:
                yield context,candidate,native_dialogue
            else:
                async for chunk in self._tool_caption_chunker.expand(context,candidate):
                    async with self._lock:
                        if not self._tool_branch_current(context,activity_seq,request_id): return
                    yield context,chunk,None
        except Exception:
            if native_observation is not None and not native_result_observed:
                self._emit_native_tool(native_observation, request_id, status='failed', reason='other')
                native_result_observed = True
            raise
        finally:
            if native_observation is not None and not native_result_observed:
                self._emit_native_tool(native_observation, request_id, status='cancelled', reason='cancelled')
            if self._tool_turns.pop(task,None) is not None:
                turn.close()

    def _grant_fixed_photo_tool(self,context,activity_seq,request_id):
        """Grant the one shipped asset under the Actor lock, without semantic review.

        The real tool call and strict closed arguments were checked by _execute_tool.
        Bootstrap attests fixed asset bytes in the immutable readiness catalog.
        This local admission is neither a JEV ALLOW nor a presentation receipt.
        """
        if (not self._tool_branch_current(context,activity_seq,request_id)
                or self._state.sealed):
            raise asyncio.CancelledError
        candidate=CandidateRange((EffectProposal(EffectKind.MEDIA,'trip_photo'),),
            'application-local-fixed-photo-tool')
        attempt=self._begin_fixed_photo(candidate,context,activity_seq)
        if not event_available(candidate.effects[0],context.character_assets):
            self._update_fixed_photo(context,attempt,'held','readiness','unavailable')
            return
        candidate=filter_visual_events(context,candidate,self._state)
        if not candidate.effects:
            self._update_fixed_photo(context,attempt,'held','readiness','already_visible')
            return
        self._photo_diagnostic('readiness',self._state.fixed_photo)
        effects=compile_range(candidate,epoch=context.output_epoch,activity=activity_seq)
        self._accept_conversation_effects(effects,context)
        self._update_fixed_photo(context,attempt,'granted','grant',effect_id=effects[0].id)

    async def _execute_tool(self,call,definitions,context,activity_seq,request_id,span):
        if call.name not in {definition.name for definition in definitions}:
            return tool_result(call,'unavailable',reason='unavailable'),None
        try:
            arguments=parse_tool_arguments(call)
        except (ValueError,TypeError,UnicodeError,RecursionError):
            return tool_result(call,'held',reason='invalid_arguments'),None
        if call.name in NATIVE_CHARACTER_TOOLS:
            if not self._native_tool_authority:return tool_result(call,'held',reason='authority_unavailable'),None
            return await self._execute_native_character_tool(call,arguments,context,activity_seq,request_id)
        if call.name=='cancel_story_image':
            async with self._lock:
                if not self._tool_branch_current(context,activity_seq,request_id):raise asyncio.CancelledError
                if arguments['request_id']!=self._state.story_image.request_id:
                    return tool_result(call,'held',state=self._state,reason='superseded'),None
                if self._state.story_image.state=='cancelled':return tool_result(call,'cancelled',state=self._state,reason='cancelled'),None
                if self._state.story_image.state not in ('pending','generating','reviewing','qualified'):
                    return tool_result(call,'held',state=self._state,reason='precondition'),None
                self._cancel_story_images('explicit_photo_cancel')
                return tool_result(call,'cancelled',state=self._state,reason='cancelled'),None
        intent=None
        reused=None
        reused_state=None
        reused_checkpoint=None
        async with self._lock:
            if not self._tool_branch_current(context,activity_seq,request_id): raise asyncio.CancelledError
            dismissed=self._state.photo_dismissed_through_activity if call.name=='show_photo' else self._state.image_dismissed_through_activity
            if self._native_tool_authority and self._state.activity_seq<=dismissed:
                return tool_result(call,'cancelled',state=self._state,reason='dismissed'),None
            if call.name=='show_photo':
                reused=visible_fixed_receipt(self._state)
                if reused is not None:
                    if self._character_runtime is not None:
                        effect = next(e for e in self._state.presented_effects if e.id == reused.effect_id)
                        if self._character_runtime.reconcile_visible_preview(effect,reused,request_id,
                                context.output_epoch,visible=self._state.photo_visible):
                            self._commit(self._state, 'chapter_visible_preview_reused')
                        # An earlier write may be pending even when this exact
                        # visible-reference reconciliation is already a no-op.
                        reused_checkpoint = self._character_runtime.checkpoint_snapshot()
                    reused_state = self._state
                else:
                    self._grant_fixed_photo_tool(context,activity_seq,request_id)
            else:
                from mira.domain.story import valid_story_projection
                from mira.domain.story_images import FictionImageScope, parse_fiction_image_proposal
                from mira.application.story_images import compile_fiction_image_intent
                try:
                    story=context.character_story
                    if not valid_story_projection(story): raise ValueError('story_invalid')
                    scope=FictionImageScope(story.story_id,story.canon_revision,story.canon_hash,story.released_story_events)
                    intent=compile_fiction_image_intent(parse_fiction_image_proposal(arguments),scope,
                        authorized_custom_brief=self._story_images.admission.authorized_custom_brief)
                except (ValueError,TypeError,UnicodeError,RecursionError):
                    return tool_result(call,'held',reason='ineligible'),None
                candidate=CandidateRange((),'application-tool-image')
        if reused is not None:
            if reused_checkpoint is not None:
                await self._character_runtime.persist(reused_checkpoint)
            return tool_result(call,'reused',state=reused_state,receipt=reused),reused
        if call.name!='show_photo' and self._native_tool_authority:
            async with self._lock:
                if not self._tool_branch_current(context,activity_seq,request_id):raise asyncio.CancelledError
                candidate=self._prepare_image_candidate(context,candidate,tool_image_intent=intent)
                if candidate.image_intent is not None:self._start_story_image(candidate.image_intent)
        elif call.name!='show_photo':
            try:
                async with asyncio.timeout(min(5.0,self._limits.timeout_seconds/4)):
                    current=await self._conversation_candidate(context,activity_seq,candidate,span,tool_image_intent=intent)
                    if not current: raise asyncio.CancelledError
            except TimeoutError:
                async with self._lock:
                    if not self._tool_branch_current(context,activity_seq,request_id): raise asyncio.CancelledError
                    self._hold_image_candidate(replace(candidate,image_intent=intent),context)
                return tool_result(call,'held',reason='review_timeout'),None
        deadline=asyncio.get_running_loop().time()+self._tool_result_wait_seconds
        async with self._lock:
            identity=self._state.fixed_photo.attempt_seq if call.name=='show_photo' else self._state.story_image.request_id
        while True:
            await self._ensure_context_current(context)
            async with self._lock:
                if not self._tool_branch_current(context,activity_seq,request_id): raise asyncio.CancelledError
                result=project_tool_result(call,self._state,identity)
                remaining=deadline-asyncio.get_running_loop().time()
                if json.loads(result.output_json)['status']!='pending' or remaining<=0: return result,identity
                changed=self._tool_state_changed
            # Timeout means the result is still unknown, never render failure.
            try: await asyncio.wait_for(changed.wait(),timeout=remaining)
            except TimeoutError: pass

    async def _execute_native_character_tool(self,call,arguments,context,activity_seq,request_id):
        """Compile one current native operation; exact receipts alone establish display."""
        from mira.application.native_character_tools import prepare_native_character, recognition_offer_intent
        await self._ensure_context_current(context)
        key=(request_id,context.output_epoch,call.call_id)
        fingerprint=(call.name,call.arguments_json)
        async with self._lock:
            if not self._tool_branch_current(context,activity_seq,request_id) or self._state.sealed:
                raise asyncio.CancelledError
            if (self._character_runtime is not None and arguments.get('transition_id')=='x.exit'
                    and arguments.get('input_act')=='exit_role' and arguments.get('evidence_text')==context.user_text):
                self._character_runtime._native_role_question=None
            prior=self._native_tool_executions.get(key)
            if prior is not None:
                if prior[0]!=fingerprint:return tool_result(call,'held',reason='call_id_conflict'),None
                identity=prior[1]
                if identity.dialogue_intent is not None and identity.effect_id is None:
                    return project_tool_result(call,self._state,identity),identity
            else:
                proposal=control_effect(call.name,arguments)
                if proposal is not None and not control_ready(proposal,context.character_assets):
                    return tool_result(call,'held',state=self._state,reason='readiness'),None
                reused=current_control_receipt(self._state,proposal) if proposal is not None else None
                if reused is not None:
                    return tool_result(call,'shown',state=self._state,receipt=reused,reason='already_presented'),reused
                try:
                    update=None;reason=None
                    if self._character_runtime is not None:
                        update,reason=prepare_native_character(self._character_runtime,context,call,arguments,request_id,activity_seq)
                        if type(update) is NativeDialogueIntent:
                            identity=NativeToolIdentity(None,request_id,context.output_epoch,
                                activity_seq,dialogue_intent=update)
                            self._native_tool_executions[key]=(fingerprint,identity)
                            return project_tool_result(call,self._state,identity),identity
                        effects=update.admitted_effects
                    elif proposal is not None:
                        effects=compile_range(CandidateRange((proposal,),'application-native-character-tool'),
                            epoch=context.output_epoch,activity=activity_seq)
                    else:return tool_result(call,'held',reason='story_unavailable'),None
                    self._accept_conversation_effects(effects,context)
                    if update is not None:
                        self._character_runtime.commit(update)
                        if arguments.get('transition_id')=='x.ask_role':
                            self._character_runtime._native_role_question=(effects[0].id,context.output_epoch,request_id)
                        elif arguments.get('transition_id')=='x.recognize':
                            self._character_runtime._native_role_question=None
                        self._commit(self._state,'native_character_plan_projected')
                    self._wardrobe_admitted(context,effects)
                    identity=NativeToolIdentity(effects[0].id if effects else None,request_id,
                        context.output_epoch,activity_seq,'pending' if effects else 'applied',reason,
                        recognition_offer_intent(update,arguments))
                except (DomainError,ValueError,TypeError,KeyError) as error:
                    # Only application-owned finite holds cross the result boundary.
                    # Never expose arbitrary exception messages or argument text.
                    allowed_reasons = {
                        'readiness', 'current_role_question_required', 'needs_confirmation',
                        'current_input_act_required', 'unexpected_input_act', 'story_cue_required',
                        'chapter_precondition', 'current_offer_choice_required', 'current_offer_required',
                        'current_reopen_required', 'offer_cue_required', 'story_precondition',
                    }
                    reason = (error.args[0] if type(error) is DomainError and error.code == 'tool_held'
                        and len(error.args) == 1 and type(error.args[0]) is str
                        and error.args[0] in allowed_reasons else 'precondition')
                    identity=NativeToolIdentity(None,request_id,context.output_epoch,activity_seq,'held',reason)
                self._native_tool_executions[key]=(fingerprint,identity)
        deadline=asyncio.get_running_loop().time()+self._tool_result_wait_seconds
        while True:
            await self._ensure_context_current(context)
            async with self._lock:
                if not self._tool_branch_current(context,activity_seq,request_id):raise asyncio.CancelledError
                result=project_tool_result(call,self._state,identity)
                remaining=deadline-asyncio.get_running_loop().time()
                if json.loads(result.output_json)['status']!='pending' or remaining<=0:return result,identity
                changed=self._tool_state_changed
            try:await asyncio.wait_for(changed.wait(),timeout=remaining)
            except TimeoutError:pass

    async def _local_choice_candidates(self, context, candidate):
        yield context, candidate, None

    async def _generate(self, context: GenerationContext, activity_seq: int, *, local_candidate=None) -> None:
        span = DiagnosticSpan(self._diagnostics, DiagnosticStage.GENERATION,
            diagnostic_context(session_id=self._state.session_id, turn_id=str(context.output_epoch)))
        task = asyncio.current_task()
        self._diagnostic_spans[task] = span
        review_span = None
        conversation_wait = False
        try:
            async with asyncio.timeout(self._limits.timeout_seconds):
                if local_candidate is None:
                    context = await self._capture_conversation_packet(context, activity_seq)
                    if context is None:
                        return
                    context = await self._capture_memory_packet(context, activity_seq)
                    if context is None:
                        return
                async with self._lock:
                    if (self._closed or self._state.request_id is None
                            or (self._state.output_epoch, self._state.activity_seq)
                            != (context.output_epoch, activity_seq)):
                        return
                    # Local controls can change during an authorized recall. Use
                    # current app facts at dispatch, retaining the bound historical
                    # evidence and never treating it as current display state.
                    context = replace(context, response_mode=self._state.response_mode,
                        photo_visible=self._state.photo_visible,
                        photo_visibility_revision=self._state.photo_visibility_revision,
                        fixed_photo=self._state.fixed_photo)
                    self._current_generation_context = context
                    if context.character_story is not None:
                        appearance = context.character_story
                        self._wardrobe_event('context',
                            'acknowledged' if appearance.last_acknowledged_outfit is not None else 'initial',
                            context.output_epoch,activity_seq,'outfit_'+appearance.outfit,
                            acknowledged='outfit_'+appearance.last_acknowledged_outfit
                                if appearance.last_acknowledged_outfit is not None else None)
                if self._memory_binding is None and self._conversation_binding is None and self._story_images is None:
                    capture_model_safely(self._diagnostics, RecordingKind.MODEL_INPUT,
                                         context, span.context)
                count = 0
                candidates = (self._local_choice_candidates(context, local_candidate) if local_candidate is not None
                              else self._generation_candidates(context,activity_seq,span))
                async for context, candidate, native_dialogue in candidates:
                    async with self._lock:
                        if (self._closed or self._state.request_id is None
                                or (self._state.output_epoch, self._state.activity_seq)
                                != (context.output_epoch, activity_seq)
                                or (task is not None and task.cancelling())):
                            return
                        if self._request_context is not None:
                            self._request_context = retain_generated(self._request_context,
                                request_id=self._state.request_id, output_epoch=context.output_epoch,
                                texts=tuple((effect.kind, effect.value) for effect in candidate.effects))
                    raw_candidate = candidate
                    if (candidate.optional_hold is not None and (candidate.caption_chunk is None
                            or candidate.caption_chunk.index == 0)):
                        emit_safely(self._diagnostics, DiagnosticEvent(DiagnosticStage.GENERATION,
                            DiagnosticOutcome.DROPPED, span.context, kind=DiagnosticKind.STATE_CHANGED,
                            optional_candidate_hold=candidate.optional_hold))
                    async with self._lock:
                        self._wardrobe_candidate(context,activity_seq,raw_candidate)
                    if self._character_runtime is not None:
                        async with self._lock:
                            if self._closed or self._state.output_epoch!=context.output_epoch:
                                return
                            try:
                                candidate=self._character_runtime.prepare_candidate(context,candidate,
                                    self._state.request_id)
                            except DomainError:
                                self._wardrobe_hold(context,'preparation_failed',phase='readiness')
                                raise
                    async with self._lock:
                        self._wardrobe_ready(context,activity_seq,raw_candidate,candidate)
                    # Captured before semantic review, so rejected candidates can be reproduced.
                    if self._memory_binding is None and self._conversation_binding is None and self._story_images is None:
                        capture_model_safely(self._diagnostics, RecordingKind.MODEL_OUTPUT,
                                             candidate, span.context)
                    if self._native_tool_authority and local_candidate is None:
                        dialogue_only(candidate)
                        if not await self._conversation_candidate(context,activity_seq,candidate,span,
                                native_dialogue=native_dialogue):return
                        count+=1
                        continue
                    if self._semantic_review is not None or local_candidate is not None:
                        if local_candidate is not None or self._semantic_review.conversation_first:
                            conversation_wait = True
                            if not await self._conversation_candidate(context,activity_seq,candidate,span):
                                return
                            conversation_wait = False
                            count += 1
                            continue
                        if not await self._semantic_candidate(context, activity_seq, candidate, span):
                            return
                        count += 1
                        last_candidate = candidate
                        continue
                    await self._ensure_context_current(context)
                    async with self._lock:
                        if self._closed or self._state.output_epoch != context.output_epoch:
                            return
                        review_context = replace(context, accepted_prefix=self._state.active_grants,
                                                 presented_effects=self._state.presented_effects,
                                                 audio_progress=audio_context_progress(self._state.audio_progress),
                                                 photo_visible=self._state.photo_visible,
                                                 photo_visibility_revision=self._state.photo_visibility_revision,
                        fixed_photo=self._state.fixed_photo)
                    review_span = DiagnosticSpan(self._diagnostics, DiagnosticStage.OUTPUT_REVIEW,
                        span.context)
                    try:
                        observation = await self._review.review(review_context, candidate)
                    except asyncio.CancelledError:
                        # Outer timeout/explicit-cancel boundary knows the actual cause.
                        raise
                    except Exception as review_error:
                        review_span.finish(DiagnosticOutcome.FAILED,
                                           code=classify_failure(review_error).code)
                        raise
                    else:
                        review_span.finish(DiagnosticOutcome.SUCCEEDED if (
                            observation.verdict == ReviewVerdict.ALLOW) else DiagnosticOutcome.FAILED,
                            code=None if observation.verdict == ReviewVerdict.ALLOW else (
                                DiagnosticCode.BLOCKED if observation.verdict == ReviewVerdict.REJECT
                                else classify_reason(observation.reason_code).code),
                            response_validation=observation.response_diagnostics)
                    self._wardrobe_decision(context,observation.verdict)
                    if observation.verdict != ReviewVerdict.ALLOW:
                        raise DomainError(_review_failure_code(observation),
                                          "Candidate did not pass review.")
                    await self._ensure_context_current(context)
                    async with self._lock:
                        if self._closed or self._state.output_epoch != context.output_epoch:
                            return
                        self._accept_reviewed_range(review_context,candidate,observation,activity_seq)
                        count += 1
                if not count:
                    raise DomainError("empty_generation", "Provider returned no complete range.")
                if local_candidate is None and self._semantic_review is not None and not self._semantic_review.conversation_first:
                    if not await self._semantic_candidate(context, activity_seq, last_candidate,
                                                          span, scope="seal"):
                        return
                else:
                    await self._ensure_context_current(context)
                    async with self._lock:
                        self._commit(transitions.seal(self._state, output_epoch=context.output_epoch),
                                     "plan_sealed")
            span.finish(DiagnosticOutcome.SUCCEEDED)
        except asyncio.CancelledError:
            # Local stop owns invalidation. Cancellation is not natural PlanEnd.
            reason = span.cancellation_reason or CancellationReason.UNKNOWN
            if review_span is not None:
                review_span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED, reason=reason)
            span.finish(DiagnosticOutcome.CANCELLED, code=DiagnosticCode.CANCELLED, reason=reason)
            raise
        except Exception as error:
            if task is not None and task.cancelling():
                raise asyncio.CancelledError from None
            if review_span is not None:
                review_span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code)
            span.finish(DiagnosticOutcome.FAILED, code=classify_failure(error).code,
                        generation_diagnostic=generation_failure_diagnostic(error))
            if isinstance(error, TimeoutError) and conversation_wait:
                # Exhausting the turn budget while awaiting optional assessment
                # holds its events; it is not retroactive rejection of this cue.
                # Stop/new input and changed memory/story versions still win.
                try:
                    await self._ensure_context_current(context)
                except Exception:
                    pass
                else:
                    async with self._lock:
                        if (not self._closed and self._state.request_id is not None
                                and (self._state.output_epoch,self._state.activity_seq)
                                == (context.output_epoch,activity_seq)
                                and any(effect.kind is EffectKind.SUBTITLE
                                        for effect in self._state.active_grants)):
                            self._wardrobe_hold(context,'review_failed')
                            if self._state.fixed_photo.state=='pending':
                                self._set_fixed_photo(replace(self._state.fixed_photo,state='held',reason='review_failed'),'review')
                            if self._state.story_image.state=='pending':
                                self._image_status('held',failure_code='review')
                            self._commit(transitions.seal(self._state,output_epoch=context.output_epoch),
                                         'plan_sealed')
                            return
            code = public_error_code(error.code) if isinstance(error, DomainError) else (
                "generation_timeout" if isinstance(error, TimeoutError) else (
                    DiagnosticCode.CODEX_STARTUP_READONLY_FILESYSTEM.value
                    if classify_failure(error).code == DiagnosticCode.CODEX_STARTUP_READONLY_FILESYSTEM
                    else "generation_failed"
                )
            )
            if self._native_tool_authority:
                # A failed optional continuation cannot retroactively reject a
                # complete independent cue or a previously validated tool grant.
                # Source/permission drift still fails closed below.
                try:await self._ensure_context_current(context)
                except Exception:pass
                else:
                    async with self._lock:
                        if (not self._closed and self._state.request_id is not None
                                and (self._state.output_epoch,self._state.activity_seq)==(context.output_epoch,activity_seq)
                                and any(e.kind is EffectKind.SUBTITLE and e.cue_speech_id is None
                                    for e in self._state.active_grants)):
                            sealed=transitions.seal(self._state,output_epoch=context.output_epoch)
                            self._commit(replace(sealed,last_error=code,
                                last_error_diagnostic_id=failure_diagnostic_id(span.context)),
                                'native_continuation_failed_cue_retained')
                            return
            async with self._lock:
                failed = transitions.fail(self._state, output_epoch=context.output_epoch, code=code,
                                          diagnostic_id=failure_diagnostic_id(span.context))
                if failed is not self._state:
                    self._wardrobe_hold(context,'review_failed')
                    self._cancel_wardrobe()
                    self._commit(failed, "generation_failed")
                    self._cancel_fixed_photo()
                    if code in ('memory_context_stale','memory_context_overflow','memory_unavailable'):
                        self._cancel_story_images('scope_changed')
                    self._cancel_media(CancellationReason.PERMIT_REVOKED)
        finally:
            self._diagnostic_spans.pop(task, None)

    async def close(self) -> None:
        character_checkpoint = None
        async with self._lock:
            self._closed = True
            self._request_context = None
            self._cancel_tasks(CancellationReason.SESSION_CLOSED)
            if self._character_runtime is not None:
                self._character_runtime.stop(self._state.output_epoch + 1)
                character_checkpoint = self._character_runtime.checkpoint_snapshot()
            tasks = tuple(self._tasks) + tuple(self._image_tasks)
            if self._story_images is not None:self._story_images.close()
            media = tuple(self._media_operations)
            close_owned_reader = (
                self._memory_binding is not None
                and self._memory_binding.close_reader_on_actor_close
                and not self._memory_close_started
            )
            if close_owned_reader:
                self._memory_close_started = True
            # Synchronous close_media registers reaping even if shutdown's next
            # await is cancelled while generation is still terminating.
            media_cleanup = asyncio.gather(*(self.close_media(operation,
                CancellationReason.SESSION_CLOSED) for operation in media)) if media else None
        try:
            if tasks:
                await asyncio.wait(tasks, timeout=1.0)
        finally:
            if media_cleanup is not None:
                await media_cleanup
            if close_owned_reader and self._memory_binding is not None:
                try:
                    async with asyncio.timeout(1.0):
                        await self._memory_binding.aclose()
                except Exception:
                    # Cleanup failures are intentionally content-free and never
                    # reopen the closed Actor or mask its previous terminal state.
                    pass
            if self._conversation_binding is not None:
                try:
                    async with asyncio.timeout(2.0):
                        await self._conversation_binding.aclose()
                except Exception:
                    pass  # A committed write is never falsely reported rolled back.
            if self._character_runtime is not None:
                try:
                    await self._character_runtime.persist(character_checkpoint)
                except DomainError:
                    # The UI was never told a pending checkpoint was durable.
                    # A failed close cannot resurrect the closed session.
                    pass
