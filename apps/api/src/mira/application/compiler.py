"""Assign application-owned effect identity only after a complete range is reviewed."""
import hashlib
import json
from uuid import uuid4

from mira.application.contracts import CandidateRange
from mira.domain.errors import DomainError
from mira.domain.models import Effect, EffectKind


def compile_range(candidate: CandidateRange, *, epoch: int, activity: int) -> tuple[Effect, ...]:
    if not candidate.effects or len(candidate.effects) > 8:
        raise DomainError("invalid_range", "A range must contain between one and eight effects.")
    speech_count = sum(proposal.kind == EffectKind.SPEECH for proposal in candidate.effects)
    subtitle_count = sum(proposal.kind == EffectKind.SUBTITLE for proposal in candidate.effects)
    if speech_count > 1 or (speech_count and subtitle_count > 1):
        raise DomainError("invalid_cue", "A speech cue permits one speech and at most one subtitle.")
    cue_id = str(uuid4())
    identities = tuple(str(uuid4()) for _ in candidate.effects)
    speech_id = next((identity for identity, proposal in zip(identities, candidate.effects)
                      if proposal.kind == EffectKind.SPEECH), None)
    effects = []
    for identity, proposal in zip(identities, candidate.effects):
        content = json.dumps({"kind": proposal.kind.value, "value": proposal.value,
                              "cue_id": cue_id, "cue_speech_id": speech_id},
                             ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        effects.append(Effect(
            id=identity, kind=proposal.kind, value=proposal.value,
            digest=hashlib.sha256(content.encode()).hexdigest(),
            output_epoch=epoch, activity_seq=activity, cue_id=cue_id, cue_speech_id=speech_id,
        ))
    return tuple(effects)
