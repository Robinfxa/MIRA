"""Bounded current-request lineage, separate from immutable conversation facts.

The Actor owns this transient value. It never retrieves another session or writes
memory. Drafts are generated text only; actual display/audio remain in the ledgers.
"""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from typing import Literal

from mira.domain.errors import DomainError
from mira.domain.models import EffectKind

InputRelation = Literal["independent", "continuation", "new_topic"]
MAX_INTENT_INPUTS = 8
MAX_INTENT_BYTES = 32768
MAX_DRAFTS = 8
MAX_DRAFT_BYTES = 16384


@dataclass(frozen=True, slots=True)
class AcceptedInput:
    request_id: str
    output_epoch: int
    text: str
    source: Literal["text", "asr_final"]
    user_input_index: int


@dataclass(frozen=True, slots=True)
class GeneratedDraft:
    draft_id: str
    request_id: str
    output_epoch: int
    kind: EffectKind
    value: str
    evidence_stage: Literal["generated_plan_only"] = "generated_plan_only"


@dataclass(frozen=True, slots=True)
class RequestContext:
    relation: InputRelation
    resolution: Literal["root", "linked", "new_topic", "unmatched_parent", "budget_exceeded"]
    root_request_id: str
    version: int
    accepted_inputs: tuple[AcceptedInput, ...]
    generated_drafts: tuple[GeneratedDraft, ...] = ()
    generated_drafts_truncated: bool = False


def validate_relation(relation: str, request_id: str | None, output_epoch: int | None) -> None:
    if relation not in ("independent", "continuation", "new_topic"):
        raise DomainError("invalid_input", "Unknown input relation.")
    if relation == "continuation":
        valid = (type(request_id) is str and bool(request_id.strip()) and len(request_id) <= 128
                 and type(output_epoch) is int and output_epoch >= 1)
    else:
        valid = request_id is None and output_epoch is None
    if not valid:
        raise DomainError("invalid_input", "Input relation has inconsistent parent identity.")


def begin_request(previous: RequestContext | None, current: AcceptedInput, *,
                  relation: InputRelation, parent_id: str | None,
                  parent_epoch: int | None) -> RequestContext:
    resolution = "new_topic" if relation == "new_topic" else "root"
    if relation == "continuation":
        resolution = "unmatched_parent"
        if previous is not None and (
            previous.accepted_inputs[-1].request_id,
            previous.accepted_inputs[-1].output_epoch,
        ) == (parent_id, parent_epoch):
            inputs = previous.accepted_inputs + (current,)
            if (len(inputs) <= MAX_INTENT_INPUTS
                    and sum(len(item.text.encode("utf-8")) for item in inputs) <= MAX_INTENT_BYTES):
                return replace(previous, relation=relation, resolution="linked",
                               version=previous.version + 1, accepted_inputs=inputs)
            resolution = "budget_exceeded"
    return RequestContext(relation, resolution, current.request_id, 1, (current,))


def retain_generated(packet: RequestContext, *, request_id: str, output_epoch: int,
                     texts: tuple[tuple[EffectKind, str], ...]) -> RequestContext:
    """Keep complete bounded text pieces; never slice a cue into purported heard words."""
    if (packet.accepted_inputs[-1].request_id, packet.accepted_inputs[-1].output_epoch) != (
            request_id, output_epoch):
        return packet
    drafts = packet.generated_drafts
    truncated = packet.generated_drafts_truncated
    for kind, value in texts:
        if kind not in (EffectKind.SUBTITLE, EffectKind.SPEECH) or type(value) is not str:
            continue
        if len(value) > 4096:
            truncated = True
            continue
        try:
            value_bytes = value.encode("utf-8")
        except UnicodeError:
            truncated = True
            continue
        if len(value_bytes) > MAX_DRAFT_BYTES:
            truncated = True
            continue
        encoded = json.dumps((request_id, output_epoch, kind, value), ensure_ascii=False).encode("utf-8")
        identity = sha256(encoded).hexdigest()
        if any(item.draft_id == identity for item in drafts):
            continue
        drafts += (GeneratedDraft(identity, request_id, output_epoch, kind, value),)
        # Recent completed drafts are most relevant; original accepted intent stays intact.
        while (len(drafts) > MAX_DRAFTS
               or sum(len(item.value.encode("utf-8")) for item in drafts) > MAX_DRAFT_BYTES):
            drafts = drafts[1:]
            truncated = True
    return replace(packet, generated_drafts=drafts, generated_drafts_truncated=truncated)


def request_context_data(packet: RequestContext, *, user_text: str, user_inputs: tuple[str, ...],
                         output_epoch: int) -> dict[str, object]:
    """Closed provider projection. The current user text is never replaced or concatenated."""
    if (type(packet) is not RequestContext or type(packet.accepted_inputs) is not tuple
            or not 1 <= len(packet.accepted_inputs) <= MAX_INTENT_INPUTS
            or any(type(item) is not AcceptedInput or type(item.request_id) is not str
                   or not item.request_id or len(item.request_id) > 128
                   or type(item.output_epoch) is not int or item.output_epoch < 1
                   or type(item.user_input_index) is not int
                   or not 0 <= item.user_input_index < len(user_inputs)
                   or type(item.text) is not str or not item.text.strip()
                   or len(item.text) > 8192 or item.source not in ("text", "asr_final")
                   for item in packet.accepted_inputs)
            or packet.root_request_id != packet.accepted_inputs[0].request_id
            or any(item.text != user_inputs[item.user_input_index] for item in packet.accepted_inputs)
            or tuple(item.user_input_index for item in packet.accepted_inputs)
               != tuple(range(len(user_inputs) - len(packet.accepted_inputs), len(user_inputs)))
            or packet.version != len(packet.accepted_inputs)
            or (packet.accepted_inputs[-1].text, packet.accepted_inputs[-1].output_epoch)
               != (user_text, output_epoch)
            or len({item.request_id for item in packet.accepted_inputs}) != packet.version
            or sum(len(item.text.encode("utf-8")) for item in packet.accepted_inputs) > MAX_INTENT_BYTES
            or packet.relation not in ("independent", "continuation", "new_topic")
            or packet.resolution not in ("root", "linked", "new_topic", "unmatched_parent", "budget_exceeded")
            or type(packet.generated_drafts) is not tuple or len(packet.generated_drafts) > MAX_DRAFTS
            or type(packet.generated_drafts_truncated) is not bool):
        raise ValueError("request_context_invalid")
    inputs = {(item.request_id, item.output_epoch) for item in packet.accepted_inputs}
    if (any(type(item) is not GeneratedDraft or type(item.value) is not str
            or len(item.value) > 4096 or item.kind not in (EffectKind.SUBTITLE, EffectKind.SPEECH)
            or item.evidence_stage != "generated_plan_only"
            or (item.request_id, item.output_epoch) not in inputs
            for item in packet.generated_drafts)
            or sum(len(item.value.encode("utf-8")) for item in packet.generated_drafts) > MAX_DRAFT_BYTES
            or len({item.draft_id for item in packet.generated_drafts}) != len(packet.generated_drafts)):
        raise ValueError("request_context_invalid")
    result = asdict(packet)
    # Exact references avoid copying accepted text already present in reliable user_inputs.
    result["accepted_inputs"] = tuple({"request_id": item.request_id,
        "output_epoch": item.output_epoch, "source": item.source, "user_input_index": item.user_input_index}
        for item in packet.accepted_inputs)
    return {"schema": "mira.request-context.v1", **result, "actual_hearing": "unknown"}
