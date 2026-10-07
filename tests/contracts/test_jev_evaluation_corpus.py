"""Offline corpus integrity and DTO mechanics; never Chinese model-quality evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / "specs/features/WP01-jev-evaluation"


def test_evaluation_release_exists_and_is_frozen():
    # Written before the first corpus release. Missing corpus is an asserted artifact
    # requirement, not an import/collection failure or an invented model-quality RED.
    assert (FEATURE / "release-manifest.v2.json").is_file(), "frozen corpus release is missing"
    manifest = json.loads((FEATURE / "release-manifest.v2.json").read_text())
    assert manifest["production_calibration_admitted"] is False
    for path, digest in manifest["artifact_sha256"].items():
        target = (FEATURE / "archive-v2/tests/contracts/test_jev_evaluation_corpus.py"
                  if path == "tests/contracts/test_jev_evaluation_corpus.py" else ROOT / path)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest

from collections import Counter
from dataclasses import asdict
from decimal import Decimal

import pytest

from mira.adapters.review.jev import (
    JevHttpResponse, JevReviewBackend, JevReviewContract, candidate_digest, context_digest,
)
from mira.adapters.review.jev_input import JevInputDecisionBackend
from mira.application.contracts import candidate_data
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
from mira.application.decision_contracts import (
    AuthorPolicy, ControlledReferent, DecisionSnapshot, DirectiveFact, PresentationFact,
    ReliableUserInput, decision_snapshot_data, valid_snapshot,
)
from mira.domain.models import AudioProgress, AudioStatus, Effect, EffectKind


def load(name):
    return json.loads((FEATURE / name).read_text())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def proposal(row):
    return EffectProposal(EffectKind(row["kind"]), row["value"])


def effect(row):
    return Effect(**{**row, "kind": EffectKind(row["kind"])})


def snapshot(row):
    """Lossless exact DTO reconstruction, no inferred presentation or hearing."""
    c, p = row["context"], row["author_policy"]
    context = GenerationContext(c["user_text"], tuple(c["user_inputs"]),
        tuple(effect(e) for e in c["presented_effects"]), c["output_epoch"],
        tuple(effect(e) for e in c["accepted_prefix"]),
        tuple(AudioProgress(**{**a, "status": AudioStatus(a["status"])})
              for a in c["audio_progress"]))
    policy = AuthorPolicy(p["policy_revision"], p["character_revision"], p["capability_revision"],
        tuple(p["character_facts"]), tuple(proposal(e) for e in p["allowed_controls"]),
        tuple(DirectiveFact(**d) for d in p["constraints"]))
    return DecisionSnapshot(row["snapshot_id"], row["event_watermark"], row["activity_seq"],
        row["input_epoch"], row["input_revision"], row["generation_id"], context,
        tuple(ReliableUserInput(**i) for i in row["reliable_inputs"]), policy,
        tuple(PresentationFact(effect(f["effect"]), f["status"], f["observed_text"])
              for f in row["presentation_facts"]),
        tuple(ControlledReferent(**r) for r in row["referents"]),
        tuple(DirectiveFact(**d) for d in row["effective_constraints"]),
        tuple(DirectiveFact(**d) for d in row["response_obligations"]), row["local_stop"])


def all_cases():
    return (load("input-additions.v2.zh.json")["cases"]
            + load("output-candidates.v2.zh.json")["cases"])


def test_original_input_audit_is_complete_and_separates_gold_from_runtime():
    audit = load("input-audit.v2.zh.json")
    source = ROOT / audit["source_path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == audit["source_sha256"]
    old = json.loads(source.read_text())["cases"]
    assert len(old) == len(audit["cases"]) == 20
    assert {r["source_id"] for r in audit["cases"]} == {r["id"] for r in old}
    for row in audit["cases"]:
        assert row["partition"] == "development"
        assert row["critique"] and "status" not in row["gold_semantics"]
        assert row["runtime_without_calibration"] in {"unknown", "unavailable"}
    revised = {r["source_id"] for r in audit["cases"] if r["disposition"] == "needs_context"}
    assert revised == {"no_new_boundary", "rejected_invite_yes", "negative_boundary_later"}


@pytest.mark.parametrize("case", all_cases(), ids=lambda c: c["id"])
def test_every_fixture_round_trips_application_dtos(case):
    snap = snapshot(case["snapshot"])
    assert valid_snapshot(snap)
    assert json.loads(canonical(decision_snapshot_data(snap))) == case["snapshot"]
    assert all(f.observed_text is None for f in snap.presentation_facts)
    if "candidate" in case:
        candidate = CandidateRange(tuple(proposal(e) for e in case["candidate"]["effects"]),
                                   case["candidate"]["fixture_id"])
        assert json.loads(canonical(candidate_data(candidate))) == case["candidate"]


def test_holdout_family_and_content_separation_is_frozen():
    cases = all_cases()
    assert len({c["id"] for c in cases}) == len(cases)
    groups, contents = {}, {}
    for case in cases:
        group, split = case["scenario_family"], case["partition"]
        assert groups.setdefault(group, split) == split
        # Context, scope and candidate participate; no text-only deduplication hides
        # deliberate stage/seal or accepted/presented contrasts within one partition.
        content = {"snapshot": case["snapshot"], "scope": case.get("scope"),
                   "candidate": case.get("candidate")}
        content["snapshot"] = {k: v for k, v in content["snapshot"].items()
                               if k not in {"snapshot_id", "generation_id"}}
        if content["candidate"]:
            content["candidate"] = {"effects": content["candidate"]["effects"]}
        digest = hashlib.sha256(canonical(content)).hexdigest()
        assert contents.setdefault(digest, split) == split
    assert Counter(c["partition"] for c in cases) == {
        "development": 30, "holdout": 20, "guard": 3,
    }


def test_output_dimensions_and_three_way_labels_cover_every_effect():
    cases = load("output-candidates.v2.zh.json")["cases"]
    for case in cases:
        expected = {"o1", "o2", "o3", "o4", "o5", "o6"} | {
            f"effect_{i}" for i in range(len(case["candidate"]["effects"]))}
        assert set(case["gold_questions"]) == expected
        labels = set(case["gold_questions"].values())
        kind = case["gold_class"]
        assert case["rationale"] and case["evaluation_mode"].startswith("synthetic_")
        if kind == "compatible":
            assert labels == {"allow"}
        elif kind == "violating":
            assert "reject" in labels and "not_called" not in labels
        elif kind == "ambiguous":
            assert "unknown" in labels and labels <= {"allow", "unknown"}
        else:
            assert kind == "guard" and labels == {"not_called"} and case["deterministic_guard"]
    for partition in ("development", "holdout"):
        assert {c["gold_class"] for c in cases if c["partition"] == partition} == {
            "compatible", "violating", "ambiguous",
        }
    tags = {t for c in all_cases() for t in c["tags"]}
    assert {"negation", "quotation", "simultaneous_requests", "old_restriction",
            "raw_obligation", "partial_audio", "not_heard", "accepted_not_presented",
            "effect_coverage", "character_facts", "unsupported_external_action",
            "control_injection", "chinese_variant"} <= tags


def test_input_gold_does_not_invent_referents_or_erase_old_directives():
    cases = load("input-additions.v2.zh.json")["cases"]
    for case in cases:
        gold = case["gold_semantics"]
        assert set(gold) == {"speech_restriction", "capture_restriction",
                             "display_request", "referent"}
        snap = snapshot(case["snapshot"])
        if snap.local_stop:
            assert set(gold.values()) == {None}
            continue
        for name in ("speech_restriction", "capture_restriction", "display_request"):
            assert gold[name] in {"yes", "no", "unknown"}
        assert gold["referent"] in {"none", "ambiguous", *(r.referent_id for r in snap.referents)}
        if gold["referent"] not in {"none", "ambiguous"}:
            ref = next(r for r in snap.referents if r.referent_id == gold["referent"])
            assert any(f.effect.id == ref.presentation_effect_id and f.status == "presented"
                       for f in snap.presentation_facts)
    old = next(c for c in cases if c["id"] == "in_old_boundary")
    assert old["gold_semantics"]["speech_restriction"] == "no"
    assert old["snapshot"]["effective_constraints"][0]["raw_text"] == "本次会话请一直别出声。"
    raw = next(c for c in cases if c["id"] == "in_raw_share")
    assert raw["snapshot"]["response_obligations"][0]["raw_text"] == raw["snapshot"]["context"]["user_text"]


class OfflineShapeTransport:
    """Fabricated all-allow wire response tests mechanics only, never semantic labels."""
    def __init__(self):
        self.calls = []

    async def __call__(self, payload, **kwargs):
        assert len(payload) <= 16 * 1024
        request = json.loads(payload)
        self.calls.append(request)
        answers = {key: {"type": "choice", "choice": "allow", "confidence": 1.0,
            "probabilities": {"allow": 1.0, "reject": 0.0, "unknown": 0.0}}
            for key in request["questions"]}
        return JevHttpResponse(200, canonical({"model": "jev-1.13.0", "answers": answers,
            "usage": {"input_tokens": 100, "output_tokens": 20}}))


def review_fixture(case):
    snap = snapshot(case["snapshot"])
    candidate = CandidateRange(tuple(proposal(e) for e in case["candidate"]["effects"]),
                               case["candidate"]["fixture_id"])
    # Explicit output-isolation contract, not an InputDecisionObservation or production
    # admission reference. Raw obligations and original effective constraints survive.
    obligations = tuple(d.raw_text for d in snap.response_obligations)
    if snap.context.user_text not in obligations:
        obligations += (snap.context.user_text,)
    contract = JevReviewContract("eval-" + case["id"], "mira-output-v1",
        context_digest(snap.context), candidate_digest(candidate),
        tuple(d.raw_text for d in snap.author_policy.constraints + snap.effective_constraints),
        obligations, snap.author_policy.character_facts, snap.author_policy.allowed_controls,
        case["scope"], synthetic=True)
    return snap.context, candidate, contract


@pytest.mark.asyncio
@pytest.mark.parametrize("case", load("output-candidates.v2.zh.json")["cases"],
                         ids=lambda c: c["id"])
async def test_output_wire_coverage_and_uncalibrated_no_allow(case):
    transport = OfflineShapeTransport()
    if case["deterministic_guard"] == "application_local_stop_no_review":
        result = await JevInputDecisionBackend(transport=transport, model="jev-1.13.0",
            request_limit=1).observe(snapshot(case["snapshot"]))
        assert result.reason_code == "jev_input_local_stop"
        assert not transport.calls
        return
    context, candidate, contract = review_fixture(case)
    result = await JevReviewBackend(transport=transport, model="jev-1.13.0",
        contract_resolver=lambda *_: contract, request_limit=1).review_detailed(context, candidate)
    assert result.observation.verdict == "unknown"
    if case["deterministic_guard"]:
        assert result.observation.reason_code == case["deterministic_guard"]
        assert not transport.calls
        return
    assert result.observation.reason_code == "jev_policy_not_calibrated"
    assert len(transport.calls) == 1
    request = transport.calls[0]
    assert {key.rsplit(":", 1)[-1] for key in request["questions"]} == set(case["gold_questions"])
    assert request["state"]["context"] == case["snapshot"]["context"]
    assert request["state"]["candidate"] == case["candidate"]
    assert request["state"]["contract"]["synthetic"] is True


def test_first_run_is_development_only_and_budget_requires_sequential_reservations():
    plan = load("preregistration.v2.json")
    cases = {c["id"]: c for c in all_cases()}
    run = plan["ordered_first_run"]
    assert len(run) == len({r["case_id"] for r in run}) == 16
    assert Counter(r["track"] for r in run) == {"input": 6, "output": 10}
    assert all(cases[r["case_id"]]["partition"] == "development" for r in run)
    assert plan["holdout_first_run"] is False and plan["sentinels"]["new_live_calls_planned"] == 0
    budget = plan["budget_snapshot"]
    remaining = Decimal(budget["remaining_usd"])
    reserved = Decimal(budget["operational_per_attempt_reserve_usd"])
    assert Decimal(budget["reserved_or_charged_usd"]) + remaining == Decimal("0.01")
    assert Decimal("0.002688") < reserved <= remaining < 2 * reserved
    assert reserved * 16 > remaining
    assert budget["concurrency"] == 1 and budget["automatic_retries"] == 0
    assert budget["unknown_usage_keeps_full_reserve"] is True
    assert budget["remaining_attempts"] + budget["attempts_consumed"] == 20


def test_manifest_case_hashes_are_complete_and_tampering_is_detectable():
    manifest = load("release-manifest.v2.json")
    cases = all_cases()
    assert set(manifest["case_sha256"]) == {c["id"] for c in cases}
    for case in cases:
        expected = manifest["case_sha256"][case["id"]]
        assert hashlib.sha256(canonical(case)).hexdigest() == expected
        altered = {**case, "partition": "tampered"}
        assert hashlib.sha256(canonical(altered)).hexdigest() != expected


def test_original_v1_artifact_bytes_remain_verifiable_in_archive():
    archive = FEATURE / "archive-v1"
    manifest = json.loads((archive / "release-manifest.v1.json").read_text())
    for path, digest in manifest["artifact_sha256"].items():
        assert hashlib.sha256((archive / path).read_bytes()).hexdigest() == digest


def test_v2_cue_schema_migration_preserves_v1_gold_and_partitions():
    def without_unset_cues(value):
        if isinstance(value, list):
            return [without_unset_cues(item) for item in value]
        if isinstance(value, dict):
            return {key: without_unset_cues(item) for key, item in value.items()
                    if not (key in {"cue_id", "cue_speech_id"} and item is None)}
        return value
    for name in ("input-additions", "output-candidates"):
        original = load(name + ".v1.zh.json")
        migrated = load(name + ".v2.zh.json")
        old_cases = {case["id"]: case for case in original["cases"]}
        new_cases = {case["id"]: case for case in migrated["cases"]}
        assert old_cases.keys() <= new_cases.keys()
        for identity, case in old_cases.items():
            assert without_unset_cues(new_cases[identity]) == case


def test_v2_selected_queue_is_adjudicated_and_o2_has_real_negative_coverage():
    rows = {row["case_id"]: row for row in load("adjudication.v2.json")["cases"]}
    cases = {case["id"]: case for case in all_cases()}
    plan = load("preregistration.v2.json")
    for selected in plan["ordered_first_run"]:
        row, case = rows[selected["case_id"]], cases[selected["case_id"]]
        assert row["review_disposition"] in {"agreed", "adjudicated"}
        assert row["semantic_score_eligible"] is True
        assert row["source_case_sha256"] == hashlib.sha256(canonical(case)).hexdigest()
        assert row["frozen_labels"] == case.get("gold_semantics", case.get("gold_questions"))
    assert len([case for case in cases.values()
                if case.get("gold_questions", {}).get("o2") == "reject"]) >= 2
