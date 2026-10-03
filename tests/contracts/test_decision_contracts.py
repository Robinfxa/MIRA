"""Application facts and producer, entirely synthetic and transport independent."""
from dataclasses import FrozenInstanceError, replace

import pytest

from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
from mira.application.decision_contracts import (
    ChoiceProbability, ControlledReferent, DecisionSnapshot, DirectiveFact,
    InputDecisionObservation, InputDecisionStatus, PredicateObservation, PresentationFact,
    ReferentObservation, ReliableUserInput, ResponseContractProducer, SemanticValue,
    evidence_digest, mira26_author_policy, valid_snapshot,
)
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind


def snapshot(text="不要说话，给我看看刚才那张照片。"):
    photo = Effect("photo-1", EffectKind.MEDIA, "fixed-photo-v1", "photo-digest", 1, 1)
    partial = Effect("speech-1", EffectKind.SPEECH, "这是窗外的雨。", "speech-digest", 1, 1)
    context = GenerationContext(text, (text,), (photo,), 2, audio_progress=(
        AudioProgress("speech-1", "speech-digest", 1, 1, 2, 24000, 2400, AudioStatus.INTERRUPTED),))
    return DecisionSnapshot(
        "snapshot-2", 7, 2, 2, 1, "generation-2", context,
        (ReliableUserInput("input-2", text),), mira26_author_policy(),
        (PresentationFact(photo, "presented"), PresentationFact(partial, "partial")),
        (ControlledReferent("photo-1", "刚才已展示的雨窗照片", "photo-1"),),
        (DirectiveFact("capture-boundary", "不要拍我。", "input-1", "session"),),
    )


def observation(snap, *, speech=SemanticValue.YES, display=SemanticValue.YES):
    return InputDecisionObservation(
        snap.snapshot_id, evidence_digest(snap), InputDecisionStatus.OBSERVED, "synthetic",
        (PredicateObservation("speech_restriction", speech, 1.0 if speech == "yes" else 0.0),
         PredicateObservation("capture_restriction", SemanticValue.NO, 0.0),
         PredicateObservation("display_request", display, 1.0 if display == "yes" else 0.0)),
        ReferentObservation("resolved", "photo-1", (
            ChoiceProbability("none", 0.0), ChoiceProbability("ambiguous", 0.0),
            ChoiceProbability("photo-1", 1.0)), 1.0),
        calibration_ref="synthetic-test-only", model="jev-1.13.0",
    )


def candidate(kind=EffectKind.POSE, value="camera_lowered"):
    return CandidateRange((EffectProposal(kind, value),), "candidate-1")


def produce(snap=None, obs=None, proposal=None, **kwargs):
    snap = snap or snapshot()
    return ResponseContractProducer().produce(snap.context, proposal or candidate(), snapshot=snap,
                                             observation=obs or observation(snap), **kwargs)


def test_snapshot_preserves_actual_partial_facts_and_raw_reliable_input():
    snap = snapshot()
    assert valid_snapshot(snap)
    assert snap.presentation_facts[1].status == "partial"
    assert snap.presentation_facts[1].observed_text is None
    assert snap.context.audio_progress[0].rendered_samples == 2400
    assert snap.context.presented_effects == (snap.presentation_facts[0].effect,)
    with pytest.raises(FrozenInstanceError):
        snap.input_revision = 9


@pytest.mark.parametrize("change", [
    {"reliable_inputs": []}, {"presentation_facts": []}, {"referents": []},
    {"input_revision": True}, {"effective_constraints": []},
    {"referents": (ControlledReferent("invented", "not presented", "future-1"),)},
])
def test_mutable_or_unbound_snapshot_evidence_is_rejected(change):
    assert not valid_snapshot(replace(snapshot(), **change))


def test_full_presentation_cannot_be_invented_from_partial_or_unknown():
    snap = snapshot()
    invented = replace(snap.context, presented_effects=tuple(f.effect for f in snap.presentation_facts))
    assert not valid_snapshot(replace(snap, context=invented))


def test_producer_keeps_simultaneous_raw_requirements_and_never_releases_prior_boundary():
    snap = snapshot()
    contract = produce(snap)
    assert contract is not None
    assert "不要拍我。" in contract.effective_constraints
    assert snap.context.user_text in contract.effective_constraints
    assert snap.context.user_text in contract.response_obligations
    assert contract.snapshot.presentation_facts[1].status == "partial"
    assert contract.effective_constraints == ("不要拍我。", snap.context.user_text)
    assert contract.character_facts == snap.author_policy.character_facts
    assert contract.context_digest == evidence_digest(snap.context)
    assert contract.candidate_digest == evidence_digest(candidate())
    assert contract.basis_snapshot_digest == evidence_digest(snap)


def test_changed_context_candidate_scope_or_snapshot_changes_contract_identity():
    snap = snapshot()
    first = produce(snap)
    second = produce(snap, proposal=candidate(value="face_warm"))
    sealed = produce(snap, scope="seal")
    assert first and second and sealed
    assert len({first.contract_id, second.contract_id, sealed.contract_id}) == 3
    assert sealed.scope == "seal"
    assert ResponseContractProducer().produce(replace(snap.context, output_epoch=9), candidate(),
        snapshot=snap, observation=observation(snap)) is None


@pytest.mark.parametrize("change", [
    {"calibration_ref": None}, {"status": InputDecisionStatus.UNKNOWN},
    {"snapshot_digest": "0" * 64}, {"question_set_revision": "old"},
    {"referent": ReferentObservation("ambiguous")}, {"predicates": ()},
    {"unresolved_items": ("不可判定",)},
])
def test_missing_unknown_uncalibrated_or_stale_input_never_produces_contract(change):
    snap = snapshot()
    assert produce(snap, replace(observation(snap), **change)) is None
    assert ResponseContractProducer().produce(snap.context, candidate(), snapshot=snap,
                                             observation=None) is None


def test_unknown_original_directive_and_local_stop_are_not_widened():
    snap = snapshot()
    uncertain = replace(snap, effective_constraints=(
        DirectiveFact("unknown", "不要那个。", "input-1", interpretation="unknown"),))
    assert produce(uncertain) is None
    assert produce(replace(snap, local_stop=True)) is None


def test_speech_restriction_and_exact_control_catalog_are_deterministic_bounds():
    assert produce(proposal=candidate(EffectKind.SPEECH, "我仍然要说话。")) is None
    assert produce(proposal=candidate(value="capture_user")) is None
    assert produce(proposal=candidate(EffectKind.MEDIA, "fixed-photo-v1")) is None
    assert produce(proposal=candidate(EffectKind.POSE, "face_calm")) is not None


def test_author_policy_is_local_adult_fiction_and_has_no_media_capability():
    policy = mira26_author_policy()
    assert any("26岁" in fact and "成年" in fact for fact in policy.character_facts)
    assert all(control.kind in (EffectKind.POSE, EffectKind.SCENE) for control in policy.allowed_controls)


@pytest.mark.parametrize("progress_change", [
    {"status": AudioStatus.COMPLETED, "rendered_samples": 0},
    {"status": AudioStatus.RENDERED, "rendered_samples": 0},
    {"rendered_samples": 24_000 * 60 * 60},
])
def test_invalid_audio_evidence_is_not_admitted_as_presentation(progress_change):
    snap = snapshot()
    changed = replace(snap.context.audio_progress[0], **progress_change)
    status = ("presented" if changed.status == AudioStatus.COMPLETED else
              "partial" if changed.rendered_samples else "unknown")
    facts = (snap.presentation_facts[0], replace(snap.presentation_facts[1], status=status))
    context = replace(snap.context, audio_progress=(changed,),
                      presented_effects=tuple(f.effect for f in facts if f.status == "presented"))
    assert not valid_snapshot(replace(snap, context=context, presentation_facts=facts))


def test_duplicate_or_changed_accepted_effect_identity_is_rejected():
    snap = snapshot()
    effect = snap.presentation_facts[1].effect
    context = replace(snap.context, accepted_prefix=(effect, replace(effect, value="different")))
    assert not valid_snapshot(replace(snap, context=context))


def test_partial_audio_never_invents_an_aligned_spoken_prefix():
    snap = snapshot()
    facts = (snap.presentation_facts[0], replace(snap.presentation_facts[1], observed_text="这是"))
    assert not valid_snapshot(replace(snap, presentation_facts=facts))


def test_current_scope_and_original_obligations_survive_stage_and_seal():
    snap = replace(snapshot(), response_obligations=(
        DirectiveFact("old-obligation", "之后请说明拍摄地点。", "input-1", "session"),))
    stage, seal = produce(snap), produce(snap, scope="seal")
    assert stage and seal
    assert stage.response_obligations == seal.response_obligations == (
        "之后请说明拍摄地点。", snap.context.user_text)
    assert stage.allowed_controls == seal.allowed_controls == snap.author_policy.allowed_controls


def test_malformed_nested_identity_is_invalid_instead_of_raising():
    snap = snapshot()
    bad_referent = replace(snap.referents[0], presentation_effect_id=[])
    assert not valid_snapshot(replace(snap, referents=(bad_referent,)))
    progress = replace(snap.context.audio_progress[0], effect_id=[])
    assert not valid_snapshot(replace(snap, context=replace(snap.context, audio_progress=(progress,))))
    observed = observation(snap)
    bad_choice = replace(observed.referent, probabilities=(ChoiceProbability([], 1.0),))
    assert produce(snap, replace(observed, referent=bad_choice)) is None


def test_unencodable_raw_text_is_invalid_instead_of_provider_crash():
    assert not valid_snapshot(snapshot("bad\ud800text"))


def test_snapshot_repr_does_not_expose_raw_presented_or_partial_text():
    snap = snapshot()
    assert snap.context.user_text not in repr(snap)
    assert snap.presentation_facts[1].effect.value not in repr(snap)
    contract = produce(snap)
    assert contract and snap.context.user_text not in repr(contract)


def test_old_accepted_only_prefix_is_not_current_context():
    snap = snapshot()
    old = snap.presentation_facts[1].effect
    assert not valid_snapshot(replace(snap, context=replace(snap.context, accepted_prefix=(old,))))
