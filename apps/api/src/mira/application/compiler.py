"""Assign application-owned effect identity only after a complete range is reviewed."""
import hashlib
import json
import re
from dataclasses import asdict
from uuid import uuid4

from mira.application.contracts import CandidateRange
from mira.domain.errors import DomainError
from mira.domain.models import CaptionChunk, Effect, EffectKind


def compile_range(candidate: CandidateRange, *, epoch: int, activity: int) -> tuple[Effect, ...]:
    if not candidate.effects or len(candidate.effects) > 8:
        raise DomainError("invalid_range", "A range must contain between one and eight effects.")
    speech_count = sum(proposal.kind == EffectKind.SPEECH for proposal in candidate.effects)
    subtitle_count = sum(proposal.kind == EffectKind.SUBTITLE for proposal in candidate.effects)
    if speech_count > 1 or (speech_count and subtitle_count > 1):
        raise DomainError("invalid_cue", "A speech cue permits one speech and at most one subtitle.")
    chunk = candidate.caption_chunk
    if chunk is not None and subtitle_count:
        subtitle = next(p for p in candidate.effects if p.kind is EffectKind.SUBTITLE)
        if (type(chunk) is not CaptionChunk or subtitle_count != 1
                or type(chunk.group_id) is not str or re.fullmatch(r'[0-9a-f-]{36}', chunk.group_id) is None
                or any(type(v) is not int for v in (chunk.index, chunk.start, chunk.end, chunk.total))
                or not 0 <= chunk.index < 4 or not 0 <= chunk.start < chunk.end <= chunk.total <= 4096
                or (chunk.index == 0) != (chunk.start == 0)
                or len(subtitle.value) != chunk.end - chunk.start
                or type(chunk.source_sha256) is not str
                or re.fullmatch(r'[0-9a-f]{64}', chunk.source_sha256) is None):
            raise DomainError('invalid_caption_chunk', 'Invalid original caption range.')
    cue_id = str(uuid4())
    identities = tuple(str(uuid4()) for _ in candidate.effects)
    speech_id = next((identity for identity, proposal in zip(identities, candidate.effects)
                      if proposal.kind == EffectKind.SPEECH), None)
    effects = []
    for identity, proposal in zip(identities, candidate.effects):
        chunk_metadata = chunk if proposal.kind is EffectKind.SUBTITLE else None
        data = {"kind": proposal.kind.value, "value": proposal.value,
                "cue_id": cue_id, "cue_speech_id": speech_id}
        if chunk_metadata is not None:
            data['caption_chunk'] = asdict(chunk_metadata)
        content = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        effects.append(Effect(
            id=identity, kind=proposal.kind, value=proposal.value,
            digest=hashlib.sha256(content.encode()).hexdigest(),
            output_epoch=epoch, activity_seq=activity, cue_id=cue_id, cue_speech_id=speech_id,
            caption_chunk=chunk_metadata,
        ))
    return tuple(effects)


def compile_generated_media(resource_id: str, content_digest: str, *, epoch: int, activity: int) -> Effect:
    from mira.domain.story_images import parse_generated_photo
    from mira.application.contracts import EffectProposal
    value='generated_story_photo:v1:'+resource_id+':'+content_digest
    if parse_generated_photo(value) is None:raise ValueError('generated_photo_invalid')
    return compile_range(CandidateRange((EffectProposal(EffectKind.MEDIA,value),),'application-image'),
                         epoch=epoch,activity=activity)[0]
