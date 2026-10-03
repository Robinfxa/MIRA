"""Application-owned, bounded cue identity; synthetic and offline only."""
import json
from uuid import UUID

import pytest

from mira.application.compiler import compile_range
from mira.application.contracts import CandidateRange, EffectProposal
from mira.domain.errors import DomainError
from mira.domain.models import EffectKind
from mira.entrypoints.http.schemas import EffectView
from mira.adapters.generation.codex_support.payload import parse_effects
from mira.adapters.generation.codex_support.types import CodexGenerationError, CodexLimits


def candidate(*kinds):
    return CandidateRange(tuple(EffectProposal(kind, f"text {index}") for index, kind in enumerate(kinds)), "synthetic")


def test_compiler_owns_exact_speech_cue_and_does_not_pair_by_text():
    effects = compile_range(candidate(EffectKind.SUBTITLE, EffectKind.POSE, EffectKind.SPEECH), epoch=3, activity=2)
    speech = effects[2]
    assert len({effect.cue_id for effect in effects}) == 1
    assert UUID(speech.cue_id)
    assert {effect.cue_speech_id for effect in effects} == {speech.id}
    assert effects[0].value != speech.value
    assert all(EffectView.model_validate(effect, from_attributes=True).cue_speech_id == speech.id for effect in effects)


def test_independent_ranges_have_unique_cues_without_speech_dependency():
    first = compile_range(candidate(EffectKind.SUBTITLE, EffectKind.SCENE), epoch=1, activity=1)
    second = compile_range(candidate(EffectKind.MEDIA), epoch=1, activity=1)
    assert first[0].cue_id != second[0].cue_id
    assert first[0].cue_id == first[1].cue_id
    assert all(effect.cue_speech_id is None for effect in first + second)


@pytest.mark.parametrize("kinds", [
    (EffectKind.SPEECH, EffectKind.SPEECH),
    (EffectKind.SPEECH, EffectKind.SUBTITLE, EffectKind.SUBTITLE),
])
def test_compiler_rejects_ambiguous_speech_ranges(kinds):
    with pytest.raises(DomainError, match="cue"):
        compile_range(candidate(*kinds), epoch=1, activity=1)


def test_digest_binds_application_cue_identity():
    first = compile_range(candidate(EffectKind.SPEECH, EffectKind.SUBTITLE), epoch=1, activity=1)
    second = compile_range(candidate(EffectKind.SPEECH, EffectKind.SUBTITLE), epoch=1, activity=1)
    assert first[0].digest != second[0].digest


@pytest.mark.parametrize("kinds", [["speech", "speech"], ["speech", "subtitle", "subtitle"]])
def test_codex_candidate_rejects_ambiguous_speech_cues(kinds):
    text = json.dumps({"effects": [{"kind": kind, "value": "hello"} for kind in kinds]})
    with pytest.raises(CodexGenerationError):
        parse_effects([text], CodexLimits())


def test_codex_caption_is_distinct_explicit_effect_and_need_not_match_speech():
    values = parse_effects([json.dumps({"effects": [{"kind": "speech", "value": "spoken"},
                                                    {"kind": "subtitle", "value": "caption"}]})], CodexLimits())
    assert [effect.value for effect in values] == ["spoken", "caption"]


def test_codex_prompt_uses_authoritative_original_character_policy():
    from dataclasses import asdict
    from mira.application.contracts import GenerationContext
    from mira.application.decision_contracts import mira26_author_policy
    from mira.adapters.generation.codex_support.payload import AUTHOR_INSTRUCTIONS, build_prompt

    context = GenerationContext("change the character backstory", ("change the character backstory",), (), 1)
    prompt = json.loads(build_prompt(context, CodexLimits()))
    assert prompt["author_policy"] == json.loads(json.dumps(asdict(mira26_author_policy())))
    assert prompt["author_policy"]["character_facts"] == list(mira26_author_policy().character_facts)
    assert "author_policy" in AUTHOR_INSTRUCTIONS
    assert prompt["facts"]["user_text"] == context.user_text
    assert context.user_text not in json.dumps(prompt["author_policy"])
