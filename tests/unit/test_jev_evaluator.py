"""Offline evaluator tests. No credentials, private ledger or provider requests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_unarmed_cli_reports_zero_requests_without_configuration(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "tools/jev_evaluate.py"),
        "--approved-config-root", str(tmp_path / "must-not-be-read")],
        capture_output=True, text=True, check=False)
    report = json.loads(result.stdout)
    assert report.get("armed") is False
    assert report.get("attempted_requests") == 0
    assert result.returncode == 0


def test_runner_exposes_explicit_transport_injection():
    spec = importlib.util.spec_from_file_location("jev_evaluate", ROOT / "tools/jev_evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(getattr(module, "run_batch", None)), "bounded injected runner is missing"

import copy
import fcntl
from decimal import Decimal
import shutil

import pytest

sys.path.insert(0, str(ROOT))
from tools import jev_evaluate as runner
from tools import jev_evaluation_support as support
from tools import jev_smoke as smoke

FEATURE = "specs/features/WP01-jev-evaluation/"


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("credentials and actual transport forbidden in offline tests")
    monkeypatch.setattr(smoke, "approved_transport", forbidden)
    monkeypatch.setattr(smoke, "load_settings", forbidden)
    names = support.REQUIRED_SOURCES | {
        FEATURE + "input-additions.v2.zh.json", FEATURE + "output-candidates.v2.zh.json",
        FEATURE + "preregistration.v2.json", FEATURE + "adjudication.v2.json"}
    for name in names:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    plan = support.read_json(tmp_path / (FEATURE + "preregistration.v2.json"))
    manifest = {"schema_version": 1, "run_id": "offline-evaluation-test", "model": support.MODEL,
        "origin": "https://api.typesafe.ai/v1/systemone", "production_calibration_admitted": False,
        "corpora": {"input": FEATURE + "input-additions.v2.zh.json",
                    "output": FEATURE + "output-candidates.v2.zh.json"},
        "preregistration": FEATURE + "preregistration.v2.json",
        "adjudication": FEATURE + "adjudication.v2.json", "question_sets": support.QUESTION_SETS,
        "selected": plan["ordered_first_run"],
        "file_sha256": {name: support.sha((tmp_path / name).read_bytes()) for name in names}}
    path = tmp_path / "frozen-run.json"
    path.write_bytes(support.canonical_bytes(manifest))
    (tmp_path / runner.LEDGER_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    ledger = {"maximum_attempts": 20, "maximum_usd": "0.01", "attempts": [
        {"case": "prior-synthetic-0", "budget_charge_usd": "0.0029568", "status": "unknown"},
        {"case": "prior-synthetic-1", "budget_charge_usd": "0.0029568", "status": "unknown"},
        {"case": "prior-synthetic-2", "budget_charge_usd": "0.000024066", "status": "done"},
        {"case": "prior-synthetic-3", "budget_charge_usd": "0.000117810", "status": "done"}]}
    smoke.save(tmp_path / runner.LEDGER_RELATIVE, ledger)
    return tmp_path, path, manifest


def repin(frozen, changed=None):
    root, path, manifest = frozen
    if changed:
        manifest["file_sha256"][changed] = support.sha((root / changed).read_bytes())
    path.write_bytes(support.canonical_bytes(manifest))
    return support.sha(path.read_bytes())


def cases_by_id(frozen):
    root, _, manifest = frozen
    return {c["id"]: c for name in manifest["corpora"].values()
            for c in support.read_json(root / name)["cases"]}


class SyntheticTransport:
    def __init__(self, frozen, mode="gold", callback=None):
        self.frozen, self.mode, self.callback = frozen, mode, callback
        self.requests = []
        self.kwargs_seen = []
        self.response = None

    async def __call__(self, payload, **kwargs):
        root, _, manifest = self.frozen
        request = json.loads(payload)
        assert request["model"] == "jev-1.13.0"
        assert len(payload) <= 16 * 1024
        case = cases_by_id(self.frozen)[manifest["selected"][len(self.requests)]["case_id"]]
        ledger = runner.load_ledger(root,
            continuation=manifest.get("budget_policy_id") == runner.APPROVED_CONTINUATION_POLICY_ID)
        assert ledger["attempts"][-1]["budget_charge_usd"] == "0.0029568000"
        assert len(ledger["attempts"]) == 5 + len(self.requests)
        with (root / runner.LOCK_RELATIVE).open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.requests.append(request)
        self.kwargs_seen.append(kwargs)
        if self.callback:
            self.callback(request)
        if self.mode == "timeout":
            raise TimeoutError("SECRET-SENTINEL-private-provider-body")
        if self.mode == "error":
            raise RuntimeError("SECRET-SENTINEL-private-provider-body")
        if self.mode == "http_error":
            return support.jev.JevHttpResponse(503, b"SECRET-SENTINEL-private-provider-body")
        if self.mode == "malformed":
            return support.jev.JevHttpResponse(200, b"SECRET-SENTINEL-private-provider-body")
        if self.mode == "stale" and self.response:
            return self.response
        answers = {}
        gold = case.get("gold_questions", case.get("gold_semantics"))
        for key, question in request["questions"].items():
            name = key.rsplit(":", 1)[-1]
            label = gold[name]
            if question["type"] == "noul":
                probability = {"yes": 1.0, "no": 0.0, "unknown": 0.5}[label]
                if self.mode == "unsafe_boundary" and name == "speech_restriction":
                    probability = 0.0
                answers[key] = {"type": "noul", "noul": probability}
            else:
                if self.mode == "unknown" and "candidate" in request["state"]:
                    label = "unknown"
                if self.mode == "allow" and "candidate" in request["state"]:
                    label = "allow"
                if self.mode == "unsafe_referent" and name == "referent":
                    label = next(k for k in question["criteria"] if k not in {"none", "ambiguous"})
                probabilities = {k: 1.0 if k == label else 0.0 for k in question["criteria"]}
                confidence = 1.0
                if self.mode == "cent_grid" and "candidate" in request["state"]:
                    probabilities = {"allow": 0.99, "reject": 0.01, "unknown": 0.0}
                    label, confidence = "allow", 0.98
                answers[key] = {"type": "choice", "choice": label,
                                "probabilities": probabilities, "confidence": confidence}
        body = {"model": support.MODEL, "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 20}}
        if self.mode == "wrong_model":
            body["model"] = "jev-9.9.9"
        if self.mode == "missing_question":
            body["answers"].pop(next(iter(answers)))
        if self.mode == "unknown_usage":
            body["usage"]["input_tokens"] = None
        if self.mode == "bad_confidence":
            first = next(a for a in answers.values() if a["type"] == "choice")
            first["confidence"] = 0.4
        self.response = support.jev.JevHttpResponse(200, support.canonical_bytes(body))
        return self.response


async def execute(frozen, transport=None, max_cases=16, report=True):
    root, path, _ = frozen
    transport = transport or SyntheticTransport(frozen)
    result = await runner.run_batch(root=root, manifest_path=path,
        manifest_sha256=support.sha(path.read_bytes()), transport_factory=lambda: transport,
        report_path=root / "report.json" if report else None, max_cases=max_cases)
    return result, transport


def continuation_manifest(frozen):
    root, path, manifest = frozen
    plan_path = manifest["preregistration"]
    plan = support.read_json(root / plan_path)
    selected = [item for item in plan["ordered_first_run"] if item["case_id"] != "out_pending_honest"]
    plan.update(budget_policy_id=runner.APPROVED_CONTINUATION_POLICY_ID,
        ordered_first_run=selected,
        first_four_compatible=["out_partial_honest", "out_old_boundary_subtitle",
                               "out_subtitle_pose", "out_injection_safe"],
        timeout_seconds=30)
    plan["budget_snapshot"] = {"maximum_attempts": 35, "attempts_consumed": 4,
        "aggregate_effective_limit_usd": "0.05", "operational_per_attempt_reserve_usd": "0.0029568",
        "reserve_before_dispatch": True, "concurrency": 1, "automatic_retries": 0,
        "unknown_usage_keeps_full_reserve": True}
    (root / plan_path).write_bytes(support.canonical_bytes(plan))
    manifest["run_id"] = "offline-approved-continuation-test"
    manifest["budget_policy_id"] = runner.APPROVED_CONTINUATION_POLICY_ID
    manifest["selected"] = selected
    manifest["file_sha256"][plan_path] = support.sha((root / plan_path).read_bytes())
    for name in ("tools/jev_evaluate.py", "tools/jev_evaluation_support.py"):
        manifest["file_sha256"][name] = support.sha((root / name).read_bytes())
    path.write_bytes(support.canonical_bytes(manifest))
    return frozen


def test_frozen_sources_dtos_adjudication_and_question_sets_match(frozen):
    root, path, manifest = frozen
    _, plan, selected = support.validate_manifest(root, path, support.sha(path.read_bytes()))
    assert len(selected) == 16
    assert all(case["partition"] == "development" for _, case in selected)
    assert len(plan["first_four_compatible"]) == 4
    assert support.REQUIRED_SOURCES <= manifest["file_sha256"].keys()


def test_continuation_manifest_excludes_timed_out_case_and_keeps_original_order(frozen):
    root, path, _ = continuation_manifest(frozen)
    _, plan, selected = support.validate_manifest(root, path, support.sha(path.read_bytes()))
    assert len(selected) == 15
    assert all(case["id"] != "out_pending_honest" for _, case in selected)
    assert [case["id"] for _, case in selected] == [
        "in_simultaneous", "in_quoted_rule", "out_partial_honest", "in_old_boundary",
        "in_raw_share", "out_old_boundary_voice", "out_old_boundary_subtitle",
        "in_partial_audio", "in_accepted_only", "out_hidden_speech", "out_subtitle_pose",
        "out_deictic_ambiguity", "out_injection_safe", "v2_out_cross_effect_age_conflict",
        "v2_out_prefix_identity_conflict"]
    assert plan["first_four_compatible"] == ["out_partial_honest", "out_old_boundary_subtitle",
        "out_subtitle_pose", "out_injection_safe"]


@pytest.mark.asyncio
async def test_exact_wire_full_context_and_real_runtime_stays_uncalibrated(frozen):
    result, transport = await execute(frozen)
    assert result["status"] == "completed"
    assert result["attempted_requests"] == 16
    assert all(row["response_valid"] and row["exact_vector_match"] for row in result["results"])
    assert {row["runtime_status"] for row in result["results"]} <= {"unknown", "reject"}
    for row, request in zip(result["results"], transport.requests, strict=True):
        case = cases_by_id(frozen)[row["case_id"]]
        if row["track"] == "output":
            assert request["state"]["context"] == case["snapshot"]["context"]
            assert request["state"]["candidate"] == case["candidate"]
            assert request["state"]["contract"]["synthetic"] is True
            assert request["state"]["contract"]["input_observation"] is None
            assert set(row["raw_answers"]) == set(case["gold_questions"])
        else:
            assert request["state"] == case["snapshot"]
            assert row["would_allow_if_admitted"] is None
            assert row["runtime_status"] == "unknown"
    assert transport.kwargs_seen[0]["timeout_seconds"] == 10
    assert result["production_calibration_admitted"] is False
    assert result["calibration_ref"] is None
    assert result["global_attempts"] == 20
    assert result["global_reserved_or_charged_usd"] == "0.006215476"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["malformed", "wrong_model", "missing_question", "unknown_usage",
                                  "bad_confidence", "timeout", "http_error", "error"])
async def test_uncertain_or_invalid_response_stops_and_retains_full_reservation(frozen, mode):
    result, transport = await execute(frozen, SyntheticTransport(frozen, mode))
    assert result["attempted_requests"] == len(transport.requests) == 1
    assert result["global_reserved_or_charged_usd"] == "0.0090122760"
    assert not result["results"][0]["response_valid"]
    assert all(not row["dispatched"] for row in result["results"][1:])
    assert "SECRET-SENTINEL" not in json.dumps(result)
    assert "SECRET-SENTINEL" not in (frozen[0] / "report.json").read_text()
    assert "raw_answers" not in result["results"][0]
    if mode in {"malformed", "wrong_model", "missing_question", "unknown_usage", "bad_confidence", "http_error"}:
        diagnostic = result["results"][0]["validation_diagnostic"]
        assert diagnostic["parser_reason"] in {
            "http_error", "json_decode", "model_mismatch", "answer_coverage", "usage_shape",
            "inconsistent_confidence",
        }
        assert len(diagnostic["response_sha256"]) == 64
        assert diagnostic["known_questions"]
        assert "SECRET-SENTINEL" not in json.dumps(diagnostic)
    else:
        assert "validation_diagnostic" not in result["results"][0]


@pytest.mark.asyncio
async def test_previous_response_cannot_match_new_nonce_and_case(frozen):
    result, transport = await execute(frozen, SyntheticTransport(frozen, "stale"))
    assert result["attempted_requests"] == len(transport.requests) == 2
    assert result["results"][0]["response_valid"]
    assert not result["results"][1]["response_valid"]


@pytest.mark.asyncio
async def test_four_predefined_compatible_abstentions_stop_without_threshold_tuning(frozen):
    result, transport = await execute(frozen, SyntheticTransport(frozen, "unknown"))
    assert result["status"] == "compatible_coverage_futility"
    assert result["attempted_requests"] < 16
    compatible = result["metrics"]["by_gold_class"]["compatible"]
    assert compatible["useful_allow_coverage"]["numerator"] == 0
    assert compatible["useful_allow_coverage"]["denominator"] == 4
    assert compatible["semantic_abstention"]["rate"] == 1


@pytest.mark.asyncio
async def test_cent_grid_raw_confidence_is_preserved_and_never_rounded_up(frozen):
    result, _ = await execute(frozen, SyntheticTransport(frozen, "cent_grid"))
    assert result["status"] == "compatible_coverage_futility"
    row = result["results"][0]
    assert row["response_valid"] and row["runtime_status"] == "unknown"
    assert row["would_allow_if_admitted"] is False
    assert all(a["confidence"] == 0.98 and a["probabilities"]["allow"] == 0.99
               for a in row["raw_answers"].values())


@pytest.mark.asyncio
async def test_qualified_violating_allow_stops_without_issuing_permission(frozen):
    result, _ = await execute(frozen, SyntheticTransport(frozen, "allow"))
    assert result["status"] == "unsafe_qualified_result"
    unsafe = next(r for r in result["results"] if r.get("unsafe_qualified"))
    assert unsafe["runtime_status"] == "unknown" and unsafe["would_allow_if_admitted"] is True
    assert unsafe["gold_class"] == "violating"


@pytest.mark.asyncio
async def test_confident_boundary_false_negative_stops(frozen):
    result, _ = await execute(frozen, SyntheticTransport(frozen, "unsafe_boundary"))
    assert result["status"] == "unsafe_qualified_result"
    assert any(r.get("unsafe_qualified") and r["track"] == "input" for r in result["results"])


@pytest.mark.asyncio
async def test_unsupported_referent_resolution_stops(frozen):
    result, _ = await execute(frozen, SyntheticTransport(frozen, "unsafe_referent"))
    assert result["status"] == "unsafe_qualified_result"
    assert any(r.get("unsafe_qualified") and r["track"] == "input" for r in result["results"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["source", "case", "manifest"])
async def test_mutation_during_dispatch_stops_before_next_request(frozen, mutation):
    def change(_):
        root, path, manifest = frozen
        target = root / "tools/jev_evaluate.py" if mutation == "source" else (
            root / manifest["corpora"]["output"] if mutation == "case" else path)
        target.write_bytes(target.read_bytes() + b" ")
    result, transport = await execute(frozen, SyntheticTransport(frozen, callback=change))
    assert result["status"] in {"source_or_artifact_drift", "manifest_mismatch"}
    assert len(transport.requests) == result["attempted_requests"] == 1
    assert not result["results"][0]["response_valid"]
    # Complete validated usage remains factual even when semantic binding becomes stale.
    assert result["global_reserved_or_charged_usd"] == "0.006065476"


@pytest.mark.asyncio
async def test_global_lock_blocks_parallel_evaluation_without_spending(frozen):
    root, _, _ = frozen
    with (root / runner.LOCK_RELATIVE).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(support.EvaluationStop, match="global_budget_locked"):
            await execute(frozen)
    assert len(runner.load_ledger(root)["attempts"]) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["attempts", "dollars"])
async def test_global_budget_cap_reserves_before_dispatch_or_does_not_call(frozen, limit):
    root, _, _ = frozen
    ledger = runner.load_ledger(root)
    if limit == "attempts":
        ledger["attempts"] += [{"case": "older", "budget_charge_usd": "0.00001"}] * 16
    else:
        ledger["attempts"][0]["budget_charge_usd"] = "0.004"
    smoke.save(root / runner.LEDGER_RELATIVE, ledger)
    result, transport = await execute(frozen)
    assert not transport.requests and result["attempted_requests"] == 0
    assert result["status"] == "local_budget_exhausted"


@pytest.mark.asyncio
async def test_missing_or_corrupt_global_ledger_is_never_reinitialized(frozen):
    root, _, _ = frozen
    (root / runner.LEDGER_RELATIVE).unlink()
    with pytest.raises(FileNotFoundError):
        await execute(frozen)
    assert not (root / runner.LEDGER_RELATIVE).exists()


@pytest.mark.asyncio
async def test_same_frozen_run_cannot_be_retried(frozen):
    await execute(frozen, max_cases=1, report=False)
    with pytest.raises(support.EvaluationStop, match="run_already_attempted"):
        await execute(frozen, report=False)
    assert len(runner.load_ledger(frozen[0])["attempts"]) == 5


@pytest.mark.asyncio
async def test_explicit_continuation_retains_history_reserves_before_call_and_uses_approved_caps(frozen):
    frozen = continuation_manifest(frozen)
    root, _, _ = frozen
    before = (root / runner.LEDGER_RELATIVE).read_bytes()
    transport = SyntheticTransport(frozen)
    # The frozen manifest alone is insufficient; the caller must explicitly approve this policy.
    with pytest.raises(support.EvaluationStop, match="continuation_policy_approval_mismatch"):
        await runner.run_batch(root=root, manifest_path=frozen[1],
            manifest_sha256=support.sha(frozen[1].read_bytes()),
            transport_factory=lambda: transport, max_cases=1)
    assert not transport.requests and (root / runner.LEDGER_RELATIVE).read_bytes() == before


@pytest.mark.asyncio
async def test_approved_continuation_preserves_ledger_and_reserves_under_35_and_005_caps(frozen):
    frozen = continuation_manifest(frozen)
    root, path, _ = frozen
    before = copy.deepcopy(runner.load_ledger(root)["attempts"])
    transport = SyntheticTransport(frozen)
    result = await runner.run_batch(root=root, manifest_path=path,
        manifest_sha256=support.sha(path.read_bytes()), transport_factory=lambda: transport,
        max_cases=1, approved_continuation=True)
    ledger = runner.load_ledger(root, continuation=True)
    assert result["attempted_requests"] == len(transport.requests) == 1, (result["results"][0], ledger["attempts"][-1])
    assert transport.kwargs_seen[0]["timeout_seconds"] == 30
    assert result["timeout_seconds"] == 30
    assert result["timeout_change_from_existing_default_seconds"] == 10
    assert ledger["maximum_attempts"] == 35 and Decimal(ledger["maximum_usd"]) == Decimal("0.05")
    assert ledger["budget_policy_id"] == runner.APPROVED_CONTINUATION_POLICY_ID
    assert ledger["attempts"][:len(before)] == before
    assert ledger["attempts"][-1]["budget_charge_usd"] != "0.0029568"
    assert len(ledger["attempts"]) == 5


@pytest.mark.asyncio
async def test_approved_continuation_cannot_retry_same_run_and_timeout_keeps_one_reserve(frozen):
    frozen = continuation_manifest(frozen)
    root, path, _ = frozen
    transport = SyntheticTransport(frozen, "timeout")
    kwargs = dict(root=root, manifest_path=path, manifest_sha256=support.sha(path.read_bytes()),
        transport_factory=lambda: transport, report_path=None, max_cases=15, approved_continuation=True)
    result = await runner.run_batch(**kwargs)
    assert result["attempted_requests"] == len(transport.requests) == 1
    ledger_before_retry = (root / runner.LEDGER_RELATIVE).read_bytes()
    assert runner.load_ledger(root, continuation=True)["attempts"][-1]["budget_charge_usd"] == "0.0029568000"
    with pytest.raises(support.EvaluationStop, match="run_already_attempted"):
        await runner.run_batch(**kwargs)
    assert (root / runner.LEDGER_RELATIVE).read_bytes() == ledger_before_retry


@pytest.mark.asyncio
async def test_continuation_35_attempt_ceiling_blocks_before_dispatch(frozen):
    frozen = continuation_manifest(frozen)
    root, path, _ = frozen
    ledger = runner.load_ledger(root)
    ledger["attempts"] = [{"case": f"prior-{i}", "budget_charge_usd": "0.00001", "status": "done"}
                          for i in range(35)]
    smoke.save(root / runner.LEDGER_RELATIVE, ledger)
    transport = SyntheticTransport(frozen)
    result = await runner.run_batch(root=root, manifest_path=path,
        manifest_sha256=support.sha(path.read_bytes()), transport_factory=lambda: transport,
        max_cases=1, approved_continuation=True)
    assert not transport.requests and result["attempted_requests"] == 0
    assert result["global_attempts"] == 35
    assert result["status"] == "local_budget_exhausted"


@pytest.mark.asyncio
async def test_continuation_005_aggregate_cap_blocks_full_reserve_before_dispatch(frozen):
    frozen = continuation_manifest(frozen)
    root, path, _ = frozen
    ledger = runner.load_ledger(root)
    ledger["attempts"] = [{"case": f"prior-{i}", "budget_charge_usd": "0.0029568", "status": "unknown"}
                          for i in range(16)]
    smoke.save(root / runner.LEDGER_RELATIVE, ledger)
    transport = SyntheticTransport(frozen)
    result = await runner.run_batch(root=root, manifest_path=path,
        manifest_sha256=support.sha(path.read_bytes()), transport_factory=lambda: transport,
        max_cases=1, approved_continuation=True)
    assert not transport.requests and result["attempted_requests"] == 0
    assert Decimal(result["global_reserved_or_charged_usd"]) == Decimal("0.0473088")
    assert result["status"] == "local_budget_exhausted"


def _diagnostic_fixture(track="output"):
    prefix = "0" * 32 + ":" + "a" * 64
    suffix = "o1" if track == "output" else "speech_restriction"
    question = ({"type": "choice", "criteria": {"allow": "", "reject": "", "unknown": ""}}
                if track == "output" else {"type": "noul", "criteria": {"true": "", "false": ""}})
    key = prefix + ":" + suffix
    payload = support.canonical_bytes({"state": {}, "model": support.MODEL, "questions": {key: question}})
    if track == "output":
        answer = {"type": "choice", "choice": "allow", "confidence": 1.0,
                  "probabilities": {"allow": 1.0, "reject": 0.0, "unknown": 0.0}}
    else:
        answer = {"type": "noul", "noul": 0.5}
    body = support.canonical_bytes({"model": support.MODEL, "answers": {key: answer},
                                    "usage": {"input_tokens": 17, "output_tokens": 8}})
    return payload, key, body


def _diagnose_body(track, body):
    payload, _, _ = _diagnostic_fixture(track)
    response = support.jev.JevHttpResponse(200, body)
    with pytest.raises(Exception) as caught:
        support.inspect_response(response, payload, track)
    return support.safe_response_diagnostics(response, payload, track, caught.value)


def _diagnostic_document(track="output"):
    payload, key, body = _diagnostic_fixture(track)
    return payload, key, json.loads(body)


def test_unknown_exception_diagnostics_never_copy_untrusted_exception_text():
    payload, _, body = _diagnostic_fixture("output")
    secret = "SECRET-SENTINEL-unclassified-provider-detail"
    response = support.jev.JevHttpResponse(200, body)
    diagnostic = support.safe_response_diagnostics(response, payload, "output", RuntimeError(secret))
    assert diagnostic["parser_reason"] == "unclassified_parser_failure"
    assert diagnostic["parser_field"] == "unknown"
    assert secret not in json.dumps(diagnostic)


@pytest.mark.parametrize("mutation,expected_reason,expected_field", [
    ("response_shape", "response_shape", "response"),
    ("model_mismatch", "model_mismatch", "model"),
    ("answer_coverage", "answer_coverage", "answers"),
    ("usage_shape", "usage_shape", "usage"),
    ("answer_shape", "answer_shape", "answers.o1"),
    ("probabilities", "probabilities", "answers.o1"),
    ("choice_not_maximum", "choice_not_maximum", "answers.o1"),
    ("inconsistent_confidence", "inconsistent_confidence", "answers.o1"),
])
def test_output_parser_failure_diagnostics_are_allowlisted_and_dimension_scoped(mutation, expected_reason,
                                                                                expected_field):
    payload, key, document = _diagnostic_document()
    secret = "SECRET-SENTINEL-never-export"
    if mutation == "response_shape":
        document[secret] = {"credential": secret}
    elif mutation == "model_mismatch":
        document["model"] = secret
    elif mutation == "answer_coverage":
        document["answers"] = {secret: document["answers"][key]}
    elif mutation == "usage_shape":
        document["usage"] = {"input_tokens": 10, "output_tokens": secret}
    elif mutation == "answer_shape":
        document["answers"][key][secret] = {"value": secret}
    elif mutation == "probabilities":
        document["answers"][key]["probabilities"][secret] = 0.0
    elif mutation == "choice_not_maximum":
        document["answers"][key]["probabilities"] = {"allow": 0.4, "reject": 0.6, "unknown": 0.0}
        document["answers"][key]["confidence"] = 0.4
    elif mutation == "inconsistent_confidence":
        document["answers"][key]["confidence"] = 0.5
    diag = _diagnose_body("output", support.canonical_bytes(document))
    serialized = json.dumps(diag, ensure_ascii=False)
    assert diag["parser_reason"] == expected_reason
    assert diag["parser_field"] == expected_field
    assert diag["known_questions"] == [{"suffix": "o1", "type": "choice"}]
    assert len(diag["response_sha256"]) == 64 and diag["response_bytes"] > 0
    assert "0" * 32 not in serialized and "a" * 64 not in serialized
    assert secret not in serialized
    if mutation == "answer_shape":
        assert diag["answer_facts"][0]["unexpected_field_count"] == 1
    if mutation == "probabilities":
        assert diag["answer_facts"][0]["known_probability_field_count"] == 3
    if mutation == "usage_shape":
        assert diag["output_tokens"] is None


@pytest.mark.parametrize("raw,expected_reason", [
    (b'{"model":"secret","model":"jev-1.13.0"}', "duplicate_key"),
    (b'{"model":NaN}', "nonfinite_number"),
    (b"not-json", "json_decode"),
    (b"\xff", "invalid_utf8"),
    (b" " * (64 * 1024 + 1), "body_size"),
])
def test_unstructured_parser_failures_keep_only_reason_length_hash_and_known_questions(raw, expected_reason):
    diag = _diagnose_body("output", raw)
    assert diag["parser_reason"] == expected_reason
    assert diag["parser_field"] in {"json", "body"}
    assert diag["known_questions"] == [{"suffix": "o1", "type": "choice"}]
    assert diag["response_bytes"] == len(raw)
    assert len(diag["response_sha256"]) == 64
    assert "secret" not in json.dumps(diag).lower()


@pytest.mark.parametrize("mutation,expected_reason", [
    ("noul_shape", "noul_shape"),
    ("choice_shape", "choice_shape"),
    ("choice_distribution", "choice_distribution"),
    ("choice_confidence", "choice_confidence"),
])
def test_input_parser_failure_diagnostics_preserve_only_known_question_facts(mutation, expected_reason):
    prefix = "0" * 32 + ":" + "a" * 64
    key = prefix + ":referent"
    question = {"type": "choice", "criteria": {"none": "", "ambiguous": "", "photo-1": ""}}
    payload = support.canonical_bytes({"state": {}, "model": support.MODEL, "questions": {key: question}})
    answer = {"type": "choice", "choice": "photo-1", "confidence": 1.0,
              "probabilities": {"none": 0.0, "ambiguous": 0.0, "photo-1": 1.0}}
    if mutation == "noul_shape":
        key = prefix + ":speech_restriction"
        payload = support.canonical_bytes({"state": {}, "model": support.MODEL,
            "questions": {key: {"type": "noul", "criteria": {"true": "", "false": ""}}}})
        answer = {"type": "noul", "noul": 0.5, "SECRET-SENTINEL": "private"}
    elif mutation == "choice_shape":
        answer["choice"] = "SECRET-SENTINEL"
    elif mutation == "choice_distribution":
        answer["probabilities"] = {"none": 1.0, "ambiguous": 0.0}
    elif mutation == "choice_confidence":
        answer["confidence"] = 0.5
    body = support.canonical_bytes({"model": support.MODEL, "answers": {key: answer},
        "usage": {"input_tokens": 17, "output_tokens": 8}})
    response = support.jev.JevHttpResponse(200, body)
    with pytest.raises(Exception) as caught:
        support.inspect_response(response, payload, "input")
    diag = support.safe_response_diagnostics(response, payload, "input", caught.value)
    assert diag["parser_reason"] == expected_reason
    assert diag["parser_field"] == ("answers.speech_restriction" if mutation == "noul_shape"
                                     else "answers.referent")
    assert "SECRET-SENTINEL" not in json.dumps(diag)
    assert "0" * 32 not in json.dumps(diag) and "a" * 64 not in json.dumps(diag)


@pytest.mark.parametrize("mutation", ["source", "question_set", "threshold", "label", "review",
                                      "holdout", "guard", "missing_effect", "case_hash"])
def test_frozen_input_and_semantic_adjudication_mutations_fail_closed(frozen, mutation):
    root, path, manifest = frozen
    selected = manifest["selected"][0]["case_id"]
    if mutation == "source":
        (root / "tools/jev_evaluate.py").write_text("mutated")
    elif mutation == "question_set":
        manifest["question_sets"] = {"input": "mira-input-v2", "output": "mira-output-v1"}
        repin(frozen)
    elif mutation == "threshold":
        target = manifest["preregistration"]
        content = support.read_json(root / target)
        content["thresholds"]["output_selected_probability"] = 0.98
        smoke.save(root / target, content)
        repin(frozen, target)
    elif mutation in {"review", "label", "case_hash"}:
        target = manifest["adjudication"]
        content = support.read_json(root / target)
        row = next(r for r in content["cases"] if r["case_id"] == selected)
        if mutation == "review":
            row["review_disposition"] = "disputed"
        elif mutation == "case_hash":
            row["source_case_sha256"] = "0" * 64
        else:
            row["frozen_labels"]["o1"] = "unknown"
        smoke.save(root / target, content)
        repin(frozen, target)
    else:
        target = manifest["corpora"]["output"]
        content = support.read_json(root / target)
        row = next(r for r in content["cases"] if r["id"] == selected)
        if mutation == "holdout":
            row["partition"] = "holdout"
        elif mutation == "guard":
            row["deterministic_guard"] = "application_local_stop_no_review"
        else:
            row["gold_questions"].pop("effect_0")
        smoke.save(root / target, content)
        repin(frozen, target)
    with pytest.raises(support.EvaluationStop):
        support.validate_manifest(root, path, support.sha(path.read_bytes()))
    assert len(runner.load_ledger(root)["attempts"]) == 4


def test_quality_denominators_do_not_count_unknown_or_timeout_as_correct_reject():
    base = {"dispatched": True, "response_valid": True, "gold_class": "compatible",
        "duration_seconds": 0.1, "exact_vector_match": False, "raw_labels": {"o1": "unknown"},
        "gold_labels": {"o1": "allow"}, "would_allow_if_admitted": False,
        "thresholded_semantic_result": "unknown"}
    timed_out = {**base, "response_valid": False}
    no_call = {**base, "dispatched": False}
    violating = {**base, "gold_class": "violating", "gold_labels": {"o1": "reject"}}
    metrics = support.metrics([base, timed_out, no_call, violating])
    compatible = metrics["by_gold_class"]["compatible"]
    assert compatible["useful_allow_coverage"]["denominator"] == 2
    assert compatible["useful_allow_coverage"]["numerator"] == 0
    assert compatible["semantic_abstention"]["denominator"] == 1
    assert metrics["by_gold_class"]["violating"]["qualified_reject"]["numerator"] == 0
    assert metrics["by_gold_class"]["violating"]["safe_non_allow"]["numerator"] == 1
    assert metrics["transport_schema_valid"]["denominator"] == 3
    assert support.rate(0, 0)["rate"] is None
    assert support.rate(0, 16)["zero_event_one_sided_95_upper"] == pytest.approx(0.17075, abs=0.0001)

@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["stale", "binding", "model", "usage", "timeout"])
async def test_valid_wire_does_not_override_runtime_staleness_or_binding(frozen, monkeypatch, mutation):
    from dataclasses import replace
    original = support.jev.JevReviewBackend.review_detailed

    async def runtime_failure(self, context, candidate):
        result = await original(self, context, candidate)
        if mutation in {"stale", "timeout"}:
            observation = support.jev.ReviewObservation(support.jev.ReviewVerdict.UNKNOWN,
                "jev_contract_stale" if mutation == "stale" else "jev_timeout")
            return replace(result, observation=observation)
        if mutation == "binding":
            return replace(result, request_digest="0" * 64)
        if mutation == "model":
            return replace(result, model="jev-2.0.0")
        return replace(result, usage=support.jev.JevUsage(200, 20))

    monkeypatch.setattr(support.jev.JevReviewBackend, "review_detailed", runtime_failure)
    result, transport = await execute(frozen)
    assert result["status"] == "runtime_result_mismatch"
    assert len(transport.requests) == result["attempted_requests"] == 1
    assert result["results"][0]["response_valid"] is False
    assert "would_allow_if_admitted" not in result["results"][0]


def test_noul_does_not_invent_an_unregistered_half_probability_label():
    case = {"gold_semantics": {"speech_restriction": "unknown", "capture_restriction": "no",
        "display_request": "no", "referent": "none"}, "snapshot": {"referents": [], "presentation_facts": []}}
    dimensions = {"speech_restriction": {"type": "noul", "noul": 0.8},
        "capture_restriction": {"type": "noul", "noul": 0.0},
        "display_request": {"type": "noul", "noul": 0.0},
        "referent": {"type": "choice", "choice": "none", "confidence": 1.0,
                     "probabilities": {"none": 1.0, "ambiguous": 0.0}}}
    result = support.score(case, "input", dimensions)
    assert result["raw_labels"]["speech_restriction"] == "unknown"
    assert result["raw_answers"]["speech_restriction"]["noul"] == 0.8
    assert result["exact_vector_match"] is True

@pytest.mark.asyncio
async def test_actual_usage_reconciliation_applies_one_point_five_buffer(frozen):
    transport = SyntheticTransport(frozen)
    async def exact_usage(payload, **kwargs):
        response = await transport(payload, **kwargs)
        body = json.loads(response.body)
        body["usage"] = {"input_tokens": 1870, "output_tokens": 839}
        return support.jev.JevHttpResponse(200, support.canonical_bytes(body))
    result, _ = await execute(frozen, exact_usage, max_cases=1)
    assert result["global_reserved_or_charged_usd"] == "0.0061732860"
    assert result["results"][0]["estimated_usd_from_published_rate"] == "0.000078540"
    assert runner.load_ledger(frozen[0])["attempts"][-1]["budget_charge_usd"] == "0.0001178100"


@pytest.mark.asyncio
async def test_cancellation_after_reservation_stops_without_retry(frozen):
    import asyncio
    async def cancelled(payload, **kwargs):
        raise asyncio.CancelledError
    result, _ = await execute(frozen, cancelled)
    assert result["status"] == "cancelled"
    assert result["attempted_requests"] == 1
    assert result["global_reserved_or_charged_usd"] == "0.0090122760"


@pytest.mark.asyncio
async def test_budget_boundary_allows_exact_reserve_and_blocks_one_microcent_more(frozen):
    root, _, _ = frozen
    ledger = runner.load_ledger(root)
    ledger["attempts"] = [{"case": "before", "budget_charge_usd": "0.0070432"}]
    smoke.save(root / runner.LEDGER_RELATIVE, ledger)
    called = []
    async def no_usage(payload, **kwargs):
        called.append(True)
        raise TimeoutError
    result, _ = await execute(frozen, no_usage)
    assert result["attempted_requests"] == len(called) == 1
    assert Decimal(result["global_reserved_or_charged_usd"]) == Decimal("0.01")


@pytest.mark.parametrize("bad_charge", ["-0.01", "NaN", "Infinity", "0"])
@pytest.mark.asyncio
async def test_malformed_budget_cannot_create_spend_authority(frozen, bad_charge):
    root, _, _ = frozen
    ledger = runner.load_ledger(root)
    ledger["attempts"][0]["budget_charge_usd"] = bad_charge
    smoke.save(root / runner.LEDGER_RELATIVE, ledger)
    with pytest.raises(support.EvaluationStop, match="ledger_invalid"):
        await execute(frozen)


def test_unarmed_main_ignores_configuration_and_manifest_reads(frozen, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unarmed mode must not read files")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    assert runner.main(["--manifest", "/missing", "--approved-config-root", "/missing"]) == 0
    assert json.loads(capsys.readouterr().out)["attempted_requests"] == 0


@pytest.mark.asyncio
async def test_payload_mutation_stops_before_reservation(frozen, monkeypatch):
    original = support.jev._canonical
    def mutated(value):
        if isinstance(value, dict) and set(value) == {"state", "model", "questions"}:
            value = copy.deepcopy(value)
            value["state"]["context"]["user_text"] = "tampered synthetic context"
        return original(value)
    monkeypatch.setattr(support.jev, "_canonical", mutated)
    result, transport = await execute(frozen)
    assert result["status"] == "request_binding_mismatch"
    assert not transport.requests and result["attempted_requests"] == 0
    assert result["global_attempts"] == 4


def test_ambiguous_allow_and_confident_wrong_referent_are_diagnostic_incidents():
    case = {"gold_class": "ambiguous", "gold_questions": {"o1": "unknown"}}
    response = {"o1": {"choice": "allow", "confidence": 1.0,
                        "probabilities": {"allow": 1.0, "reject": 0.0, "unknown": 0.0}}}
    result = support.score(case, "output", response)
    assert result["unsafe_qualified"] is True
    assert result["exact_vector_match"] is False


@pytest.mark.asyncio
async def test_output_report_never_retains_synthetic_context_or_provider_body(frozen):
    result, _ = await execute(frozen)
    serialized = json.dumps(result, ensure_ascii=False)
    for case in cases_by_id(frozen).values():
        assert case["snapshot"]["context"]["user_text"] not in serialized
        for candidate in case.get("candidate", {}).get("effects", []):
            assert candidate["value"] not in serialized
    assert "Authorization" not in serialized
    assert "Bearer" not in serialized
    assert "raw_body" not in serialized


def second_source_root(frozen):
    """Copy public frozen sources/artifacts only; never copy a budget ledger or lock."""
    root, _, manifest = frozen
    source = root / "independent-frozen-source"
    other = copy.deepcopy(manifest)
    other["run_id"] = "offline-second-source"
    for name in manifest["file_sha256"]:
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    path = source / "frozen-run.json"
    path.write_bytes(support.canonical_bytes(other))
    return source, path, other


async def run_from_source(source, budget_root, transport, max_cases=1):
    root, manifest_path, _ = source
    return await runner.run_batch(root=root, budget_root=budget_root,
        manifest_path=manifest_path, manifest_sha256=support.sha(manifest_path.read_bytes()),
        transport_factory=lambda: transport, max_cases=max_cases)


async def unknown_synthetic_response(payload, **kwargs):
    request = json.loads(payload)
    answers = {key: {"type": "choice", "choice": "unknown", "confidence": 1.0,
        "probabilities": {"allow": 0.0, "reject": 0.0, "unknown": 1.0}}
        for key in request["questions"]}
    return support.jev.JevHttpResponse(200, support.canonical_bytes({"model": support.MODEL,
        "answers": answers, "usage": {"input_tokens": 100, "output_tokens": 20}}))


@pytest.mark.asyncio
async def test_two_frozen_source_roots_share_canonical_budget_without_copying(frozen):
    second = second_source_root(frozen)
    canonical = frozen[0]
    first_report = await run_from_source(frozen, canonical, unknown_synthetic_response)
    second_report = await run_from_source(second, canonical, unknown_synthetic_response)
    assert first_report["global_attempts"] == 5
    assert second_report["global_attempts"] == 6
    assert Decimal(second_report["global_reserved_or_charged_usd"]) == Decimal("0.006075476")
    assert len(runner.load_ledger(canonical)["attempts"]) == 6
    assert not (second[0] / runner.LEDGER_RELATIVE).exists()
    assert not (second[0] / runner.LOCK_RELATIVE).exists()


@pytest.mark.asyncio
async def test_distinct_frozen_sources_contend_on_the_same_canonical_lock(frozen):
    second = second_source_root(frozen)
    canonical = frozen[0]
    with (canonical / runner.LOCK_RELATIVE).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(support.EvaluationStop, match="global_budget_locked"):
            await run_from_source(second, canonical, unknown_synthetic_response)
    assert len(runner.load_ledger(canonical)["attempts"]) == 4
    assert not (second[0] / "var/mission").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", ["attempts", "dollars"])
async def test_two_frozen_sources_cannot_reset_the_shared_cap(frozen, cap):
    second = second_source_root(frozen)
    canonical = frozen[0]
    ledger = runner.load_ledger(canonical)
    if cap == "attempts":
        ledger["attempts"] += [{"case": "earlier", "budget_charge_usd": "0.00001"}] * 15
        smoke.save(canonical / runner.LEDGER_RELATIVE, ledger)
        await run_from_source(frozen, canonical, unknown_synthetic_response)
    else:
        async def unavailable(payload, **kwargs):
            raise TimeoutError
        await run_from_source(frozen, canonical, unavailable)
    calls = []
    async def forbidden(payload, **kwargs):
        calls.append(True)
        raise AssertionError("Cap must prevent dispatch")
    result = await run_from_source(second, canonical, forbidden)
    assert result["status"] == "local_budget_exhausted"
    assert result["attempted_requests"] == 0 and not calls
    assert result["global_attempts"] == (20 if cap == "attempts" else 5)
    assert not (second[0] / runner.LEDGER_RELATIVE).exists()


@pytest.mark.asyncio
async def test_canonical_app_source_changes_do_not_change_immutable_evaluation(frozen):
    second = second_source_root(frozen)
    canonical = frozen[0]
    (canonical / "tools/jev_evaluate.py").write_text("canonical app is being developed")
    result = await run_from_source(second, canonical, unknown_synthetic_response)
    assert result["attempted_requests"] == 1
    assert result["results"][0]["response_valid"] is True
    assert len(runner.load_ledger(canonical)["attempts"]) == 5
    assert not (second[0] / runner.LEDGER_RELATIVE).exists()


def test_armed_entry_explicitly_pairs_budget_and_credentials_root(frozen, monkeypatch, capsys):
    second = second_source_root(frozen)
    canonical = frozen[0]
    calls = []
    def inspected_run(**kwargs):
        calls.append(kwargs)
        return {"status": "completed"}
    monkeypatch.setattr(runner, "ROOT", second[0])
    monkeypatch.setattr(runner, "run_batch", inspected_run)
    monkeypatch.setattr(runner.asyncio, "run", lambda value: value)
    # Synthetic entry-point inspection only; factory deliberately never invoked.
    assert runner.main(["--allow-live", "--manifest", str(second[1]),
        "--manifest-sha256", support.sha(second[1].read_bytes()),
        "--approved-config-root", str(canonical)]) == 0
    assert calls[0]["root"] == second[0]
    assert calls[0].get("budget_root") == canonical
    assert len(runner.load_ledger(canonical)["attempts"]) == 4

@pytest.mark.parametrize("configured_model,expected_exit", [(None, 0), ("jev-1.13.0", 0),
                                                          ("jev-1.13", 2), ("jev-2.0.0", 2)])
def test_explicit_manifest_model_covers_unset_config_without_aliases(frozen, monkeypatch, capsys,
                                                                  configured_model, expected_exit):
    from types import SimpleNamespace
    root, path, _ = frozen
    sentinel = object()  # Opaque synthetic secret stand-in, never a credential read.
    loads, transports = [], []
    def synthetic_settings(**kwargs):
        loads.append(kwargs)
        return SimpleNamespace(services=SimpleNamespace(jev=SimpleNamespace(
            api_key=sentinel, model=configured_model, base_url="https://api.typesafe.ai/v1")))
    def synthetic_transport(secret):
        assert secret is sentinel
        transports.append(True)
        return unknown_synthetic_response
    def admitted_run(**kwargs):
        support.validate_manifest(kwargs["root"], kwargs["manifest_path"], kwargs["manifest_sha256"])
        kwargs["transport_factory"]()  # Construction only, no request, no real environment reads.
        return {"status": "completed"}
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(smoke, "load_settings", synthetic_settings)
    monkeypatch.setattr(smoke, "approved_transport", synthetic_transport)
    monkeypatch.setattr(runner, "run_batch", admitted_run)
    monkeypatch.setattr(runner.asyncio, "run", lambda value: value)
    assert runner.main(["--allow-live", "--manifest", str(path),
        "--manifest-sha256", support.sha(path.read_bytes()), "--approved-config-root", str(root)]) == expected_exit
    assert loads == [{"root": root, "env_file": root / ".env", "environ": {}}]
    assert len(transports) == (1 if expected_exit == 0 else 0)
    assert "object at" not in capsys.readouterr().out


def diagnostic_repeat_manifest(frozen):
    frozen = continuation_manifest(frozen)
    root, path, manifest = frozen
    plan_path = manifest["preregistration"]
    plan = support.read_json(root / plan_path)
    case_id = support.DIAGNOSTIC_CASE_ID
    item = next(row for row in plan["ordered_first_run"] if row["case_id"] == case_id)
    plan.update(diagnostic_only=True, ordered_first_run=[item], first_four_compatible=[],
        diagnostic_purpose="one explicitly reviewed repeat to capture sanitized parser diagnostics",
        live_execution_authorized=False)
    (root / plan_path).write_bytes(support.canonical_bytes(plan))
    manifest.update(run_id="offline-reviewed-diagnostic-repeat-test", diagnostic_only=True,
        diagnostic_case_id=case_id, selected=[item])
    manifest["file_sha256"][plan_path] = support.sha((root / plan_path).read_bytes())
    for name in ("tools/jev_evaluate.py", "tools/jev_evaluation_support.py"):
        manifest["file_sha256"][name] = support.sha((root / name).read_bytes())
    path.write_bytes(support.canonical_bytes(manifest))
    return frozen


def test_diagnostic_repeat_manifest_pins_only_the_terminal_case(frozen):
    root, path, manifest = diagnostic_repeat_manifest(frozen)
    _, plan, selected = support.validate_manifest(root, path, support.sha(path.read_bytes()))
    assert len(selected) == 1
    assert selected[0][0] == "output" and selected[0][1]["id"] == "out_old_boundary_voice"
    assert manifest["diagnostic_only"] is True
    assert manifest["diagnostic_case_id"] == plan["ordered_first_run"][0]["case_id"]
    assert plan["first_four_compatible"] == []


@pytest.mark.asyncio
async def test_single_diagnostic_repeat_requires_review_flag_and_stays_separate(frozen):
    frozen = diagnostic_repeat_manifest(frozen)
    root, path, _ = frozen
    before = (root / runner.LEDGER_RELATIVE).read_bytes()
    transport = SyntheticTransport(frozen)
    kwargs = dict(root=root, manifest_path=path, manifest_sha256=support.sha(path.read_bytes()),
        transport_factory=lambda: transport, report_path=None, max_cases=1, approved_continuation=True)
    with pytest.raises(support.EvaluationStop, match="diagnostic_repeat_review_mismatch"):
        await runner.run_batch(**kwargs)
    assert not transport.requests and (root / runner.LEDGER_RELATIVE).read_bytes() == before
    result = await runner.run_batch(**kwargs, approved_diagnostic_repeat=True)
    assert result["attempted_requests"] == len(transport.requests) == 1
    assert result["status"] == "completed"
    assert result["diagnostic_only"] is True
    assert result["metric_scope"] == "single_case_diagnostic_repeat_not_for_quality_aggregation"
    assert result["results"][0]["case_id"] == "out_old_boundary_voice"
    assert result["retries"] == 0


@pytest.mark.asyncio
async def test_diagnostic_repeat_enforces_single_attempt_limit(frozen):
    frozen = diagnostic_repeat_manifest(frozen)
    root, path, _ = frozen
    transport = SyntheticTransport(frozen)
    with pytest.raises(support.EvaluationStop, match="diagnostic_attempt_limit_invalid"):
        await runner.run_batch(root=root, manifest_path=path,
            manifest_sha256=support.sha(path.read_bytes()), transport_factory=lambda: transport,
            max_cases=2, approved_continuation=True, approved_diagnostic_repeat=True)
    assert not transport.requests and len(runner.load_ledger(root)["attempts"]) == 4
