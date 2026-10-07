"""Loss-aware bounded wire projection of immutable conversation evidence.

No LLM, durable logging, inferred preferences or semantic summaries. The full
Actor ledger remains the authority. Only whole optional source rows are omitted;
the current request, linked intent and actual control receipts are mandatory.
"""
from __future__ import annotations

from copy import deepcopy
import json
from hashlib import sha256
import re
from mira.domain.xiahe_chapter import CHAPTER_CAPABILITIES

MAX_CONVERSATION_CONTEXT_BYTES = 48_000
MAX_RECENT_INPUTS = 32
MAX_RECENT_EFFECTS = 24
MAX_RECENT_AUDIO = 16


def _bytes(data):
    return len(json.dumps(data, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _control_channel(effect):
    kind, value = effect["kind"], effect["value"]
    if kind == "scene" and value in CHAPTER_CAPABILITIES:
        return "chapter"
    if kind in ("scene", "media"):
        return kind
    if kind != "pose":
        return None
    for prefix in ("outfit_", "emotion_", "accessory_", "face_", "gaze_"):
        if value.startswith(prefix):
            return prefix[:-1]
    if value in ("lower_camera", "raise_camera"):
        return "camera_pose"
    # Unknown controls cannot silently overwrite another named control.
    return "pose:" + value


def bound_conversation_data(original: dict, *, max_bytes: int = MAX_CONVERSATION_CONTEXT_BYTES) -> dict:
    """Project a scope-free provider view without mutating reliable source rows.

    Required evidence overflow is left visible to the existing provider guard.
    Omitted history is explicitly unavailable, not a meaning-preserving summary.
    """
    inputs = original["user_inputs"]
    effects = original["presented_effects"]
    audio = original["audio_progress"]
    without_drafts = deepcopy(original)
    if without_drafts.get("request_context") is not None:
        without_drafts["request_context"]["generated_drafts"] = ()
    if (len(inputs) <= MAX_RECENT_INPUTS and len(effects) <= MAX_RECENT_EFFECTS
            and len(audio) <= MAX_RECENT_AUDIO and _bytes(without_drafts) <= max_bytes):
        return original
    source_digest = sha256(json.dumps((inputs, effects, audio), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    data = deepcopy(original)
    request = data.get("request_context")
    mandatory_inputs = {len(inputs) - 1} if inputs else set()
    if request is not None:
        mandatory_inputs.update(item["user_input_index"] for item in request["accepted_inputs"])
    input_indices = list(range(max(0, len(inputs) - MAX_RECENT_INPUTS), len(inputs)))
    input_indices = sorted(set(input_indices) | mandatory_inputs)
    latest_controls = {}
    for index, effect in enumerate(effects):
        channel = _control_channel(effect)
        if channel is not None:
            latest_controls[channel] = index
    mandatory_effects = set(latest_controls.values())
    effect_indices = sorted(set(range(max(0, len(effects) - MAX_RECENT_EFFECTS), len(effects))) | mandatory_effects)
    # Prefer the latest actual dialogue over older optional user rows. Short
    # replies often refer to that just-presented suggestion. These rows remain
    # optional: an oversized reply must not block the current required input.
    recent_dialogue = set()
    for index in reversed(effect_indices):
        if effects[index]["kind"] in ("subtitle", "speech"):
            recent_dialogue.add(index)
            epoch = effects[index].get("output_epoch")
            if type(epoch) is int:
                recent_dialogue.update(other for other in effect_indices
                    if effects[other]["kind"] in ("subtitle", "speech")
                    and effects[other].get("output_epoch") == epoch)
            break
    audio_indices = list(range(max(0, len(audio) - MAX_RECENT_AUDIO), len(audio)))
    drafts = list(request["generated_drafts"]) if request is not None else []
    old_dialogue = original.get("first_person_dialogue")

    def project():
        data["user_inputs"] = tuple(inputs[index] for index in input_indices)
        data["presented_effects"] = tuple(effects[index] for index in effect_indices)
        data["audio_progress"] = tuple(audio[index] for index in audio_indices)
        user_map = {index: new for new, index in enumerate(input_indices)}
        effect_map = {index: new for new, index in enumerate(effect_indices)}
        if request is not None:
            request["accepted_inputs"] = tuple({**item, "user_input_index": user_map[item["user_input_index"]]}
                for item in original["request_context"]["accepted_inputs"])
            request["generated_drafts"] = tuple(drafts)
            request["generated_drafts_truncated"] = (original["request_context"]["generated_drafts_truncated"]
                or len(drafts) != len(original["request_context"]["generated_drafts"]))
        if old_dialogue is not None:
            dialogue = deepcopy(old_dialogue)
            for group, mapping, name in (("user_statements", user_map, "user_inputs"),
                                         ("presented_replies", effect_map, "presented_effects")):
                rows = []
                for row in old_dialogue[group]:
                    ref = row["quoted_text_reference"]
                    match = re.fullmatch(r"(user_inputs|presented_effects)\[(\d+)\](\.value)?", ref)
                    if match and int(match[2]) in mapping:
                        rows.append({"quoted_text_reference": f"{name}[{mapping[int(match[2])]}]{match[3] or ''}"})
                dialogue[group] = rows
                dialogue[group + "_omitted"] += len(old_dialogue[group]) - len(rows)
            data["first_person_dialogue"] = dialogue
        omitted_inputs = len(inputs) - len(input_indices)
        omitted_effects = len(effects) - len(effect_indices)
        data["conversation_history"] = {
            "schema": "mira.bounded-conversation.v1",
            "source_history_digest": source_digest,
            "source_user_input_indices": tuple(input_indices),
            "source_presented_effect_indices": tuple(effect_indices),
            "total_accepted_inputs": len(inputs),
            "total_presented_effects": len(effects),
            "omitted_accepted_inputs": omitted_inputs,
            "omitted_presented_effects": omitted_effects,
            "omitted_audio_progress": len(audio) - len(audio_indices),
            "historical_detail_omitted": bool(omitted_inputs or omitted_effects or len(audio) != len(audio_indices)),
            "semantic_summary_available": False,
            "older_history_status": "not_in_this_context_do_not_invent_or_claim_complete_recall",
            "historical_presentation_counts": {kind: sum(effect["kind"] == kind for effect in effects)
                                               for kind in ("subtitle", "speech", "pose", "scene", "media")},
            "latest_control_receipts": {channel: {"effect_id": effects[index]["id"],
                "digest": effects[index]["digest"], "presented_effect_index": effect_map[index]}
                for channel, index in latest_controls.items()},
            "evidence_rule": "Exact source rows only; receipts establish software presentation, never physical hearing, current permissions, or verified user facts. Control rows are the latest recorded presentation for each control.",
        }

    project()
    while _bytes(data) > max_bytes:
        if drafts:
            drafts.pop(0)
        elif any(index not in mandatory_effects and index not in recent_dialogue
                 for index in effect_indices):
            effect_indices.remove(next(index for index in effect_indices
                if index not in mandatory_effects and index not in recent_dialogue))
        elif audio_indices:
            audio_indices.pop(0)
        elif any(index not in mandatory_inputs for index in input_indices):
            input_indices.remove(next(index for index in input_indices if index not in mandatory_inputs))
        elif any(index not in mandatory_effects for index in effect_indices):
            effect_indices.remove(next(index for index in effect_indices if index not in mandatory_effects))
        else:
            break  # Existing hard provider budget fails closed on required facts.
        project()
    return data
