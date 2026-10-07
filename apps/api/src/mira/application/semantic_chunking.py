"""Bounded post-completion caption planning, never text approval or TTS splitting.

Speech-bearing candidates stay whole: the Actor awaits their permission check
before consuming another range. Only text-only unissued tails can be repartitioned.
Late/uncooperative work has one tracked slot.
"""
import asyncio
from dataclasses import replace
import hashlib
import math
import unicodedata
from uuid import uuid4

from mira.application.chunking_contracts import (
    BoundaryBackend, BoundaryChoice, BoundaryPlan, BoundaryRequest, boundary_digest,
)
from mira.application.contracts import CandidateRange, EffectProposal
from mira.application.decision_contracts import evidence_digest
from mira.application.ports.generation import GenerationBackend
from mira.domain.models import CaptionChunk, EffectKind

MAX_TEXT = 4096
MAX_CHUNKS = 4
_OPEN = {'(': ')', '[': ']', '{': '}', '（': '）', '【': '】', '“': '”', '‘': '’', '「': '」', '『': '』'}
_CLOSE = set(_OPEN.values())
_TERMINAL = set('。！？!?')
_ABBREVIATIONS = {'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc', 'e.g', 'i.e'}


def legal_boundaries(text: str) -> tuple[int, ...]:
    """Conservative sentence/paragraph edges; never arbitrary character limits.

    Offsets count Python Unicode code points, not UTF-16 units. Punctuation and
    trailing whitespace stay on the left. Combining marks/ZWJ never start a chunk.
    Unknown/unbalanced quoting remains whole rather than guessing a safe cut.
    """
    stack = []
    candidates = []
    pending_terminal = False
    for index, char in enumerate(text):
        if char in _OPEN:
            stack.append(_OPEN[char])
        elif char in _CLOSE:
            if not stack or stack[-1] != char:
                return (len(text),)
            stack.pop()
        elif char == '"' or (char == "'" and not (
                index > 0 and index + 1 < len(text)
                and text[index - 1].isalnum() and text[index + 1].isalnum())):
            if stack and stack[-1] == char: stack.pop()
            else: stack.append(char)
        terminal = char in _TERMINAL or char == '\n'
        if char == '.':
            before = text[:index].rsplit(None, 1)[-1].lower() if text[:index].strip() else ''
            terminal = (bool(before) and before not in _ABBREVIATIONS and len(before) > 1
                        and index + 1 < len(text) and text[index + 1].isspace()
                        and not (text[index - 1].isdigit() and text[index + 1:index + 2].isdigit()))
        # Punctuation within quoted/parenthetical content cannot prove that the
        # enclosing sentence is complete. In particular, do not cut at its closer
        # before an outer qualifier (", then..." / "尚未确认") arrives.
        if terminal: pending_terminal = not stack
        elif not char.isspace() and char not in _CLOSE and char not in {'"', "'"}: pending_terminal = False
        if pending_terminal and not stack:
            end = index + 1
            while end < len(text) and (text[end].isspace() or text[end] in _TERMINAL): end += 1
            if end < len(text) and (unicodedata.category(text[end]) in {'Mn', 'Mc', 'Me'}
                                   or text[end] == '\u200d'):
                continue
            if end < len(text) and text[:end].strip() and text[end:].strip(): candidates.append(end)
    if stack: return (len(text),)
    return tuple(sorted(set(candidates))) + (len(text),)


def make_request(context, candidate: CandidateRange) -> BoundaryRequest | None:
    if (type(candidate) is not CandidateRange or candidate.caption_chunk is not None
            or candidate.story_proposal_json is not None or candidate.affect_proposal_json is not None
            or candidate.image_proposal_json is not None or candidate.image_intent is not None
            or type(candidate.effects) is not tuple or not 1 <= len(candidate.effects) <= 2
            or any(type(effect) is not EffectProposal or effect.kind is not EffectKind.SUBTITLE
                   for effect in candidate.effects)):
        return None
    subtitles = [effect for effect in candidate.effects if effect.kind is EffectKind.SUBTITLE]
    if len(subtitles) != 1 or sum(e.kind is EffectKind.SPEECH for e in candidate.effects) > 1:
        return None
    text = subtitles[0].value
    if type(text) is not str or not 24 <= len(text) <= MAX_TEXT: return None
    ends = legal_boundaries(text)
    if len(ends) < 3: return None  # One tail sentence offers no semantic partition choice.
    prefix = ends[0]
    tail = ends[1:]
    plans = [BoundaryPlan('whole_tail', (len(text),))]
    middle = tail[(len(tail) - 1) // 2]
    if middle != len(text): plans.append(BoundaryPlan('two_tail_chunks', (middle, len(text))))
    if len(tail) > 2:
        # Keep <=3 tail chunks even for long responses; candidate edges remain complete.
        selected = (tail[(len(tail) - 1) // 3], tail[2 * (len(tail) - 1) // 3], len(text))
        selected = tuple(sorted(set(selected)))
        if len(selected) == 3: plans.append(BoundaryPlan('three_tail_chunks', selected))
    return BoundaryRequest(text, prefix, tuple(plans), evidence_digest(context),
                           evidence_digest(candidate), context.output_epoch)


class SemanticChunkingGeneration:
    def __init__(self, generation: GenerationBackend, boundary_backend: BoundaryBackend, *,
                 timeout_seconds: float = 0.4):
        if (not callable(getattr(generation, 'generate', None))
                or not callable(getattr(boundary_backend, 'choose', None))
                or type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 2):
            raise ValueError('chunking_configuration_invalid')
        self._generation = generation
        self._boundary_backend = boundary_backend
        self._timeout_seconds = timeout_seconds
        self._pending: set[asyncio.Task] = set()

    def _reap(self, task):
        self._pending.discard(task)
        if not task.cancelled(): task.exception()

    async def _plan(self, request):
        if self._pending: return request.plans[0]
        task = asyncio.create_task(self._boundary_backend.choose(request))
        self._pending.add(task)
        task.add_done_callback(self._reap)
        try:
            done, _ = await asyncio.wait((task,), timeout=self._timeout_seconds)
            if not done:
                task.cancel()
                return request.plans[0]
            try: choice = task.result()
            except (Exception, asyncio.CancelledError): return request.plans[0]
            if type(choice) is BoundaryChoice and choice.request_digest == boundary_digest(request):
                return next((plan for plan in request.plans if plan.plan_id == choice.plan_id), request.plans[0])
            return request.plans[0]
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def generate(self, context):
        async for candidate in self._generation.generate(context):
            async for expanded in self.expand(context, candidate):
                yield expanded

    async def expand(self, context, candidate):
        if asyncio.current_task().cancelling(): raise asyncio.CancelledError
        request = make_request(context, candidate)
        if request is None:
            yield candidate
            return
        group = str(uuid4())
        sha = hashlib.sha256(request.text.encode()).hexdigest()
        def part(start, end, index, *, first=False):
            effects = tuple(replace(effect, value=request.text[start:end])
                if effect.kind is EffectKind.SUBTITLE else effect
                for effect in candidate.effects
                if first or effect.kind is EffectKind.SUBTITLE)
            return replace(candidate, effects=effects,
                caption_chunk=CaptionChunk(group, index, start, end, len(request.text), sha))
        # Launched before the first yield; no wait can hold the initial text.
        planner = asyncio.create_task(self._plan(request))
        try:
            yield part(0, request.prefix_end, 0, first=True)
            plan = await planner
            if asyncio.current_task().cancelling(): raise asyncio.CancelledError
            start = request.prefix_end
            for index, end in enumerate(plan.ends, 1):
                if asyncio.current_task().cancelling(): raise asyncio.CancelledError
                yield part(start, end, index)
                start = end
        finally:
            if not planner.done(): planner.cancel()
            # The coordinator is cancellation-cooperative; provider child is tracked
            # independently and can neither publish a range nor occupy another slot.
            if planner.done() and not planner.cancelled(): planner.exception()


class DeterministicCaptionChunking:
    """Reuse conservative complete-sentence ranges without a review/model call.

    This planner makes no approval or timing decision. Speech and event-bearing
    cues remain whole, retaining the single existing speech synthesis/playback
    path. A complete eligible caption is split into at most four exact slices.
    """

    def __init__(self, generation: GenerationBackend):
        if not callable(getattr(generation, 'generate', None)):
            raise ValueError('chunking_configuration_invalid')
        self._generation = generation

    async def generate(self, context):
        async for candidate in self._generation.generate(context):
            async for expanded in self.expand(context, candidate):
                yield expanded

    async def expand(self, context, candidate):
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        request = make_request(context, candidate)
        if request is None:
            yield candidate
            return
        # Plans contain only known legal codepoint boundaries. Choosing the
        # largest bounded partition is deterministic; no guessed timing is added.
        ends = (request.prefix_end,) + request.plans[-1].ends
        group = str(uuid4())
        sha = hashlib.sha256(request.text.encode()).hexdigest()
        start = 0
        for index, end in enumerate(ends):
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            effects = tuple(replace(effect, value=request.text[start:end])
                            for effect in candidate.effects)
            yield replace(candidate, effects=effects,
                caption_chunk=CaptionChunk(group, index, start, end, len(request.text), sha))
            start = end
