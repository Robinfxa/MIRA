"""Opt-in bounded synthetic JEV diagnostic evaluation; never runtime admission."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import re
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api/src"))

from tools import jev_evaluation_support as support
from tools import jev_smoke as smoke

LEDGER_RELATIVE = "var/mission/jev-live-budget.json"
LOCK_RELATIVE = "var/mission/jev-live-budget.lock"
MAX_ATTEMPTS = 20
LEGACY_POLICY_ID = "jev-evaluation-legacy-20-001-v1"
APPROVED_CONTINUATION_POLICY_ID = "jev-zh-approved-continuation-20261003-v1"
CONTINUATION_MAX_ATTEMPTS = 35
CONTINUATION_TOTAL_LIMIT = Decimal("0.05")


def utc_now():
    return datetime.now(UTC).isoformat()


def load_ledger(root, *, continuation=False):
    # Never initialize/reset the approved global budget, even if its file is missing.
    ledger = support.read_json(root / LEDGER_RELATIVE)
    expected_attempts = CONTINUATION_MAX_ATTEMPTS if continuation else MAX_ATTEMPTS
    expected_usd = CONTINUATION_TOTAL_LIMIT if continuation else smoke.TOTAL_LIMIT
    allowed_old_ledger = (continuation and ledger.get("maximum_attempts") == MAX_ATTEMPTS
                          and type(ledger.get("maximum_attempts")) is int
                          and Decimal(ledger.get("maximum_usd", "NaN")) == smoke.TOTAL_LIMIT
                          and ledger.get("budget_policy_id") in (None, LEGACY_POLICY_ID))
    if ((ledger.get("maximum_attempts") != expected_attempts and not allowed_old_ledger)
            or type(ledger.get("maximum_attempts")) is not int
            or (Decimal(ledger.get("maximum_usd", "NaN")) != expected_usd and not allowed_old_ledger)
            or (continuation and ledger.get("budget_policy_id") not in
                (None, LEGACY_POLICY_ID, APPROVED_CONTINUATION_POLICY_ID))
            or (not continuation and ledger.get("budget_policy_id") not in (None, LEGACY_POLICY_ID))
            or type(ledger.get("attempts")) is not list):
        raise support.EvaluationStop("ledger_invalid")
    for attempt in ledger["attempts"]:
        value = Decimal(attempt["budget_charge_usd"])
        if not value.is_finite() or value < Decimal("0.00001"):
            raise support.EvaluationStop("ledger_invalid")
    return ledger


def _upgrade_ledger_for_continuation(root, ledger):
    """Widen only the recorded ceiling under the existing global lock; retain every row."""
    if ledger.get("maximum_attempts") == MAX_ATTEMPTS:
        if len(ledger["attempts"]) > CONTINUATION_MAX_ATTEMPTS or charged(ledger) > CONTINUATION_TOTAL_LIMIT:
            raise support.EvaluationStop("local_budget_exhausted")
        ledger["maximum_attempts"] = CONTINUATION_MAX_ATTEMPTS
        ledger["maximum_usd"] = str(CONTINUATION_TOTAL_LIMIT)
        ledger["budget_policy_id"] = APPROVED_CONTINUATION_POLICY_ID
        smoke.save(root / LEDGER_RELATIVE, ledger)
    elif (ledger.get("maximum_attempts") != CONTINUATION_MAX_ATTEMPTS
            or Decimal(ledger.get("maximum_usd", "NaN")) != CONTINUATION_TOTAL_LIMIT
            or ledger.get("budget_policy_id") != APPROVED_CONTINUATION_POLICY_ID):
        raise support.EvaluationStop("ledger_invalid")


def charged(ledger):
    return sum((Decimal(a["budget_charge_usd"]) for a in ledger["attempts"]), Decimal(0))


def request_shape(payload, track, case, snap, candidate=None, contract=None):
    request = json.loads(payload, object_pairs_hook=support.unique)
    expected_state = (asdict(snap) if track == "input" else {
        "context": asdict(snap.context), "candidate": asdict(candidate), "contract": asdict(contract)})
    binding = support.digest({"state": expected_state, "model": support.MODEL,
                              "question_set": support.QUESTION_SETS[track]})
    expected_questions = (support.jev_input._questions(snap, binding) if track == "input"
                          else support.jev._questions(expected_state, binding))
    questions = request.get("questions", {})
    names = {key.rsplit(":", 1)[-1]: value for key, value in questions.items()}
    expected_names = {key.rsplit(":", 1)[-1]: value for key, value in expected_questions.items()}
    prefixes = {key.rsplit(":", 1)[0] for key in questions}
    if (set(request) != {"state", "model", "questions"} or request["model"] != support.MODEL
            or support.digest(request["state"]) != support.digest(expected_state)
            or len(names) != len(questions) or names != expected_names or len(prefixes) != 1
            or not re.fullmatch(r"[a-f0-9]{32}:" + binding, next(iter(prefixes), ""))
            or len(payload) > support.jev.MAX_REQUEST_BYTES):
        raise support.EvaluationStop("request_binding_mismatch")
    return binding, support.digest(names)


async def run_batch(*, root, manifest_path, manifest_sha256, transport_factory,
                    report_path=None, max_cases=16, budget_root=None,
                    approved_continuation=False, approved_diagnostic_repeat=False):
    """Injected transport entry point. Tests use temporary roots/ledgers only.

    Main is the only credential-aware caller. All adapters remain uncalibrated.
    The global smoke lock covers the entire sequential run, including reconciliation.
    Frozen source root and explicit approved accounting root may be separate directories.
    """
    root, manifest_path = Path(root), Path(manifest_path)
    budget_root = root if budget_root is None else Path(budget_root)
    manifest, plan, selected = support.validate_manifest(root, manifest_path, manifest_sha256)
    policy_id = manifest.get("budget_policy_id", LEGACY_POLICY_ID)
    continuation = policy_id == APPROVED_CONTINUATION_POLICY_ID
    diagnostic_only = manifest.get("diagnostic_only") is True
    if (continuation and approved_continuation is not True) or (
            not continuation and approved_continuation is not False):
        raise support.EvaluationStop("continuation_policy_approval_mismatch")
    if (diagnostic_only and approved_diagnostic_repeat is not True) or (
            not diagnostic_only and approved_diagnostic_repeat is not False):
        raise support.EvaluationStop("diagnostic_repeat_review_mismatch")
    if policy_id not in {LEGACY_POLICY_ID, APPROVED_CONTINUATION_POLICY_ID}:
        raise support.EvaluationStop("budget_policy_invalid")
    if type(max_cases) is not int or not 1 <= max_cases <= 16:
        raise support.EvaluationStop("attempt_limit_invalid")
    if diagnostic_only and max_cases != 1:
        raise support.EvaluationStop("diagnostic_attempt_limit_invalid")
    if report_path is not None:
        report_path = Path(report_path)
        if report_path.exists() or report_path.resolve() in {
                manifest_path.resolve(), (budget_root / LEDGER_RELATIVE).resolve()}:
            raise support.EvaluationStop("report_path_occupied")
        report_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"case_id": case["id"], "track": track,
        "gold_class": case.get("gold_class", "input"), "case_sha256": support.digest(case),
        "policy_sha256": support.digest(case["snapshot"]["author_policy"]),
        "question_set": support.QUESTION_SETS[track], "dispatched": False,
        "response_valid": False, "status": "not_dispatched"} for track, case in selected]
    report = {"schema_version": 1, "run_id": manifest["run_id"], "model": support.MODEL,
        "manifest_sha256": manifest_sha256, "source_sha256": support.digest(manifest["file_sha256"]),
        "production_calibration_admitted": False, "calibration_ref": None,
        "concurrency": 1, "retries": 0, "attempted_requests": 0,
        "budget_policy_id": policy_id,
        "diagnostic_only": diagnostic_only,
        "metric_scope": ("single_case_diagnostic_repeat_not_for_quality_aggregation" if diagnostic_only
                         else "registered_development_diagnostic"),
        "timeout_seconds": 30 if continuation else 10,
        "timeout_change_from_existing_default_seconds": 10 if continuation else 0,
        "status": "running", "results": rows,
        "evidence_class": "synthetic_development_diagnostic_not_admission",
        "interval_scope": "descriptive_only_nonrandom_correlated_synthetic_cases",
        "billing_note": "conservative_local_reserve_and_token_estimate_not_invoice"}

    def persist():
        report["attempted_requests"] = sum(row["dispatched"] for row in rows)
        report["metrics"] = support.metrics(rows)
        if report_path:
            smoke.save(report_path, report)

    lock_path = budget_root / LOCK_RELATIVE
    # Existing private mission directory/ledger is required; no new budget path.
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise support.EvaluationStop("global_budget_locked") from None
        ledger = load_ledger(budget_root, continuation=continuation)
        if any(a.get("evaluation_run_id") == manifest["run_id"] for a in ledger["attempts"]):
            raise support.EvaluationStop("run_already_attempted")
        if continuation:
            _upgrade_ledger_for_continuation(budget_root, ledger)
        persist()
        for index, (track, case) in enumerate(selected[:max_cases]):
            row = rows[index]
            attempt, trace = None, {}
            started = time.monotonic()
            snap = support.snapshot(case["snapshot"])
            candidate, contract = (support.review_fixture(case, snap) if track == "output" else (None, None))

            async def bounded_transport(payload, **kwargs):
                nonlocal attempt, ledger
                try:
                    if attempt is not None:
                        raise support.EvaluationStop("retry_forbidden")
                    support.validate_manifest(root, manifest_path, manifest_sha256)
                    # The selected in-memory row must still match the frozen artifact.
                    if support.digest(case) != row["case_sha256"]:
                        raise support.EvaluationStop("case_binding_mismatch")
                    binding, question_hash = request_shape(payload, track, case, snap, candidate, contract)
                    ledger = load_ledger(budget_root, continuation=continuation)
                    max_attempts = CONTINUATION_MAX_ATTEMPTS if continuation else MAX_ATTEMPTS
                    total_limit = CONTINUATION_TOTAL_LIMIT if continuation else smoke.TOTAL_LIMIT
                    if (len(ledger["attempts"]) >= max_attempts
                            or charged(ledger) + smoke.PER_ATTEMPT_RESERVE > total_limit):
                        raise support.EvaluationStop("local_budget_exhausted")
                    attempt = {"case": case["id"], "evaluation_run_id": manifest["run_id"],
                        "started_at": utc_now(), "budget_charge_usd": str(smoke.PER_ATTEMPT_RESERVE),
                        "status": "reserved", "manifest_sha256": manifest_sha256}
                    ledger["attempts"].append(attempt)
                    smoke.save(budget_root / LEDGER_RELATIVE, ledger)
                    row.update(dispatched=True, attempt=len(ledger["attempts"]),
                        request_sha256=support.sha(payload), request_binding=binding,
                        question_sha256=question_hash, started_at=attempt["started_at"])
                    # Persist reservation and in-flight status before any secret/network access.
                    row["status"] = "reserved"
                    row["duration_seconds"] = time.monotonic() - started
                    persist()
                    response = await transport_factory()(payload, **kwargs)
                    if type(response) is support.jev.JevHttpResponse and type(response.status_code) is int:
                        trace["http_status"] = response.status_code
                    try:
                        dimensions, usage = support.inspect_response(response, payload, track)
                    except Exception as error:
                        trace["validation_diagnostic"] = support.safe_response_diagnostics(
                            response, payload, track, error)
                        if (type(error) is support.EvaluationStop and error.args == ("http_error",)):
                            raise
                        raise support.EvaluationStop("response_invalid") from None
                    trace.update(raw_answers=dimensions, usage=usage)
                    support.validate_manifest(root, manifest_path, manifest_sha256)
                    trace["response_valid"] = True
                    return response
                except support.EvaluationStop as error:
                    trace["stop"] = str(error)
                    raise

            try:
                if track == "input":
                    result = await support.jev_input.JevInputDecisionBackend(transport=bounded_transport,
                        model=support.MODEL, calibration_ref=None, request_limit=1,
                        timeout_seconds=30 if continuation else 10).observe(snap)
                    row.update(runtime_status=result.status.value, runtime_reason=result.reason_code)
                else:
                    result = await support.jev.JevReviewBackend(transport=bounded_transport,
                        model=support.MODEL, calibration_ref=None, request_limit=1,
                        timeout_seconds=30 if continuation else 10,
                        contract_resolver=lambda *_: contract).review_detailed(snap.context, candidate)
                    row.update(runtime_status=result.observation.verdict.value,
                               runtime_reason=result.observation.reason_code)
                if trace.get("response_valid"):
                    actual_usage = ({"input_tokens": result.input_tokens, "output_tokens": result.output_tokens}
                        if track == "input" else asdict(result.usage) if result.usage else None)
                    allowed_reasons = ({"jev_input_not_calibrated"} if track == "input" else {
                        "jev_policy_not_calibrated", "jev_semantic_unknown", "jev_semantic_reject"})
                    if (result.model != support.MODEL or result.request_digest != row["request_binding"]
                            or actual_usage != trace["usage"] or row["runtime_reason"] not in allowed_reasons
                            or (track == "output" and result.contract_digest != support.digest(asdict(contract)))
                            or (track == "input" and (result.snapshot_id != snap.snapshot_id
                                or result.snapshot_digest != support.digest(asdict(snap))
                                or result.calibration_ref is not None))):
                        trace.update(response_valid=False, stop="runtime_result_mismatch")
                row["status"] = trace.get("stop", row["runtime_reason"])
            except asyncio.CancelledError:
                row.update(status="cancelled", runtime_status="unknown", runtime_reason="cancelled")
                trace["stop"] = "cancelled"
            except Exception:
                row.update(status="evaluation_failure", runtime_status="unknown", runtime_reason="evaluation_failure")
                trace["stop"] = "evaluation_failure"
            row.update(duration_seconds=time.monotonic() - started, completed_at=utc_now(),
                       response_valid=trace.get("response_valid", False))
            if "http_status" in trace:
                row["http_status"] = trace["http_status"]
            if "validation_diagnostic" in trace:
                row["validation_diagnostic"] = trace["validation_diagnostic"]
            if "usage" in trace:
                usage = trace["usage"]
                row["usage"] = usage
                estimate = Decimal(usage["input_tokens"]) * smoke.PRICE_PER_INPUT_TOKEN
                row["estimated_usd_from_published_rate"] = str(estimate)
                if attempt is not None:
                    attempt["budget_charge_usd"] = str(max(estimate * Decimal("1.5"), Decimal("0.00001")))
            if row["response_valid"]:
                row.update(support.score(case, track, trace["raw_answers"]))
            if attempt is not None:
                attempt["status"] = row["status"]
                attempt["completed_at"] = row["completed_at"]
                smoke.save(budget_root / LEDGER_RELATIVE, ledger)
            if trace.get("stop"):
                report["status"] = trace["stop"]
            elif not row["dispatched"]:
                report["status"] = "preflight_no_dispatch"
            elif not row["response_valid"]:
                report["status"] = "response_unavailable_or_invalid"
            elif row.get("runtime_status") == "allow" or row.get("runtime_status") == "observed":
                report["status"] = "uncalibrated_runtime_violation"
            elif row.get("unsafe_qualified"):
                report["status"] = "unsafe_qualified_result"
            else:
                four = [r for r in rows if r["case_id"] in plan["first_four_compatible"]]
                if four and all(r["dispatched"] and r.get("thresholded_semantic_result") == "unknown"
                                for r in four):
                    report["status"] = "compatible_coverage_futility"
                elif charged(ledger) > (CONTINUATION_TOTAL_LIMIT if continuation else smoke.TOTAL_LIMIT):
                    report["status"] = "local_budget_exhausted"
            persist()
            if report["status"] != "running":
                break
        if report["status"] == "running":
            report["status"] = "completed" if max_cases >= len(selected) else "attempt_limit_reached"
        for row in rows:
            if not row["dispatched"] and row["status"] == "not_dispatched":
                row["status"] = report["status"]
        report["global_attempts"] = len(ledger["attempts"])
        report["global_reserved_or_charged_usd"] = str(charged(ledger))
        persist()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--approved-config-root", type=Path)
    parser.add_argument("--approved-continuation", action="store_true",
                        help="require the frozen 2026-10-03 approved continuation policy")
    parser.add_argument("--root-reviewed-diagnostic-repeat", action="store_true",
                        help="require explicit review of a frozen one-case diagnostic repeat")
    parser.add_argument("--max-cases", type=int, choices=range(1, 17), default=16)
    args = parser.parse_args(argv)
    if not args.allow_live:
        print(json.dumps({"armed": False, "attempted_requests": 0, "model": support.MODEL,
                          "production_calibration_admitted": False}))
        return 0
    if not args.manifest or not args.manifest_sha256 or not args.approved_config_root:
        print(json.dumps({"armed": False, "attempted_requests": 0,
                          "status": "explicit_manifest_pin_and_config_root_required"}))
        return 2
    try:
        config_root = args.approved_config_root
        if not config_root.is_absolute() or not config_root.is_dir():
            raise support.EvaluationStop("approved_config_root_invalid")
        # No implicit config discovery: called only after manifest and budget reservation.
        def live_transport():
            settings = smoke.load_settings(root=config_root, env_file=config_root / ".env", environ={})
            service = settings.services.jev
            if (service.api_key is None or service.model not in (None, support.MODEL)
                    or service.base_url != "https://api.typesafe.ai/v1"):
                raise support.EvaluationStop("explicit_configuration_invalid")
            return smoke.approved_transport(service.api_key)
        report_path = config_root / "var/mission/jev-evaluation" / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        report = asyncio.run(run_batch(root=ROOT, budget_root=config_root, manifest_path=args.manifest,
            manifest_sha256=args.manifest_sha256, transport_factory=live_transport,
            approved_continuation=args.approved_continuation,
            approved_diagnostic_repeat=args.root_reviewed_diagnostic_repeat,
            report_path=report_path, max_cases=args.max_cases))
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
        return 0 if report["status"] in {"completed", "attempt_limit_reached"} else 2
    except Exception:
        print(json.dumps({"status": "configuration_or_manifest_or_runtime_failure", "details_redacted": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
