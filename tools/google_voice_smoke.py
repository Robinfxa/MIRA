"""One-shot, bounded Google voice smoke runner.

This tool is intentionally separate from the application bootstrap. It never
discovers credentials on import, never retries, and requires a fresh sanitized
readiness receipt before it can create billable transports. All provider calls
use the already-approved exact model/region/text choices.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

# Project and ADC directory are supplied only by the private invocation.
PROJECT_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}"
SYNTHETIC_TEXT = "你好，这是一次语音连接测试。"
TTS_MODEL = "gemini-3.8-flash-tts"
TTS_LOCATION = "global"
TTS_VOICE = "Kore"
STT_LOCATION = "us"
STT_MODEL = "chirp_3"
STT_LANGUAGE = "cmn-Hans-CN"
STT_FIXTURE_LANGUAGE = "en-US"
STT_SAMPLE_RATE_HZ = 24000
STT_MAX_SECONDS = Decimal("30")
USD_LIMIT = Decimal("1.00")
APPROVED_FINAL_TTS_LIMIT_USD = Decimal("2.00")

# Use the highest published standard rates among the checked current/announced
# rates, not credits. This reserves $0.303104 per possible full-limit TTS call.
# One 30 s standard STT stream reserves $0.008. Fees/taxes are a separate gate.
TTS_INPUT_LIMIT = 8192
TTS_OUTPUT_LIMIT = 1024
TTS_MAX_OUTPUT_TOKENS = 1024
TTS_FULL_OUTPUT_LIMIT = 16384
TTS_INPUT_USD_PER_MILLION = Decimal("1")
TTS_OUTPUT_USD_PER_MILLION = Decimal("18")
STT_USD_PER_MINUTE = Decimal("0.016")
TTS_RESERVE_USD = (
    Decimal(TTS_INPUT_LIMIT) * TTS_INPUT_USD_PER_MILLION
    + Decimal(TTS_OUTPUT_LIMIT) * TTS_OUTPUT_USD_PER_MILLION
) / Decimal(1_000_000)
TTS_FULL_RESERVE_USD = (
    Decimal(TTS_INPUT_LIMIT) * TTS_INPUT_USD_PER_MILLION
    + Decimal(TTS_FULL_OUTPUT_LIMIT) * TTS_OUTPUT_USD_PER_MILLION
) / Decimal(1_000_000)
STT_RESERVE_USD = STT_USD_PER_MINUTE * STT_MAX_SECONDS / Decimal(60)
TOTAL_RESERVE_USD = TTS_RESERVE_USD * 2 + STT_RESERVE_USD

CALL_ORDER = ("tts_normal", "tts_cancel_after_first_packet", "stt_v2")
ADDITIONAL_TTS_KIND = "tts_diagnostic_additional"
RECOVERY_TTS_KIND = "tts_recovery_additional"
TTS_TEXT_DIAGNOSTIC_KIND = "tts_text_diagnostic_followup"
TTS_FINAL_APPROVED_KIND = "tts_final_approved_additional"
ROOT = Path(__file__).resolve().parents[1]
OFFLINE_FLITE_FIXTURE_DIR = ROOT / "apps/api/src/mira/adapters/generation/rehearsal/fixtures/audio"
SAFE_PROVIDER_ERRORS = {
    "invalid_input", "input_limit", "output_limit", "invalid_response",
    "response_limit", "invalid_audio", "unsupported_audio", "empty_audio",
    "incomplete_stream", "blocked", "unauthenticated", "permission_denied",
    "quota_exhausted", "timeout", "unavailable", "unknown",
}
SAFE_PROVIDER_REASONS = {
    "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
    "API_DISABLED", "SERVICE_DISABLED", "BILLING_DISABLED", "RATE_LIMIT_EXCEEDED",
    "QUOTA_EXCEEDED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "USER_PROJECT_DENIED",
}
SAFE_PROVIDER_DIAGNOSTICS = {
    "unknown_request_field", "unsupported_request_parameter", "invalid_request_value",
    "invalid_request_shape", "missing_request_field", "authentication_rejected",
    "authorization_rejected", "quota_rejected", "request_rejected",
    "invalid_voice", "unsupported_method", "unsupported_model",
}
SAFE_FIELD_PATH = re.compile(r"[A-Za-z][A-Za-z0-9_.\[\]-]{0,127}\Z")


def _verify_offline_fixture_dir(fixture_dir: Path) -> dict[str, Any]:
    """Load the local fixture verifier whether invoked as a module or script."""
    try:
        from tools.generate_rehearsal_audio import verify
    except ModuleNotFoundError as error:
        if error.name not in {"tools", "tools.generate_rehearsal_audio"}:
            raise
        from generate_rehearsal_audio import verify
    return verify(fixture_dir)


def _safe_field_names(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for item in values:
        if isinstance(item, str) and SAFE_FIELD_PATH.fullmatch(item) and item not in result:
            result.append(item)
        if len(result) >= 8:
            break
    return result


def _sanitize_provider_message(value: str) -> str:
    """The report admits only normalized diagnostic enums, never provider prose."""
    return value if value in SAFE_PROVIDER_DIAGNOSTICS else ""
MAX_ERROR_BODY_BYTES = 8192


class TtsLatencyTrace:
    """Record privacy-bounded monotonic boundaries for one diagnostic TTS stream."""

    def __init__(self, clock_ns: Callable[[], int] | None = None):
        self._clock_ns = clock_ns or time.monotonic_ns
        self._origin_ns = self._read_clock()
        self._last_ns = self._origin_ns
        self._events_ns: dict[str, int] = {}
        self._http_status: int | None = None
        self._non_audio_events = 0
        self._valid_packets = 0
        self._valid_bytes = 0
        self._total_samples = 0
        self._invalid_packets = 0
        self._stream_outcome: str | None = None
        self._file_save_outcome: str | None = None

    def _read_clock(self) -> int:
        value = self._clock_ns()
        if type(value) is not int:
            raise TypeError("clock must return integer nanoseconds")
        if hasattr(self, "_last_ns") and value < self._last_ns:
            raise ValueError("monotonic clock moved backwards")
        self._last_ns = value
        return value

    def _mark_once(self, name: str) -> None:
        if name in self._events_ns:
            raise ValueError("phase already observed")
        self._events_ns[name] = self._read_clock()

    def _require_dispatch(self) -> None:
        if "dispatch_started" not in self._events_ns:
            raise ValueError("dispatch was not observed")

    def _require_stream_open(self) -> None:
        self._require_dispatch()
        if self._stream_outcome is not None:
            raise ValueError("stream already terminal")

    def dispatch_started(self) -> None:
        self._mark_once("dispatch_started")

    def http_headers_received(self, status_code: int) -> None:
        self._require_stream_open()
        if type(status_code) is not int or not 100 <= status_code <= 599:
            raise ValueError("invalid HTTP status code")
        if "http_headers_received" in self._events_ns:
            raise ValueError("headers phase already observed")
        self._http_status = status_code
        self._mark_once("http_headers_received")

    def non_audio_event_received(self) -> None:
        """Count a non-audio event without retaining its content."""
        self._require_stream_open()
        self._non_audio_events += 1

    def invalid_pcm_packet_received(self) -> None:
        self._require_stream_open()
        self._invalid_packets += 1

    def pcm_packet_yielded(self, pcm: bytes, sample_rate_hz: int) -> bool:
        """Observe only valid nonempty 24-kHz S16LE bytes at the adapter yield."""
        self._require_stream_open()
        if (type(pcm) is not bytes or not pcm or len(pcm) % 2
                or type(sample_rate_hz) is not int or sample_rate_hz != 24000):
            self._invalid_packets += 1
            return False
        now = self._read_clock()
        self._events_ns.setdefault("first_valid_pcm_yielded", now)
        self._events_ns["last_valid_pcm_yielded"] = now
        self._valid_packets += 1
        self._valid_bytes += len(pcm)
        self._total_samples += len(pcm) // 2
        return True

    def stream_terminal(self, outcome: str) -> None:
        self._require_dispatch()
        if self._stream_outcome is not None:
            raise ValueError("stream already terminal")
        if outcome not in {"completed", "error", "cancelled"}:
            raise ValueError("invalid terminal outcome")
        self._stream_outcome = outcome
        self._mark_once("stream_terminal")

    def stream_closed(self) -> None:
        self._require_dispatch()
        if "stream_closed" in self._events_ns:
            raise ValueError("stream close already observed")
        self._mark_once("stream_closed")
        if self._stream_outcome is None:
            self._stream_outcome = "early_close"

    def file_save_completed(self, succeeded: bool) -> None:
        if type(succeeded) is not bool:
            raise ValueError("save result must be boolean")
        if self._stream_outcome != "completed":
            raise ValueError("file save only follows a completed stream")
        if self._file_save_outcome is not None:
            raise ValueError("file save already observed")
        self._file_save_outcome = "saved" if succeeded else "failed"
        self._mark_once("file_save_completed")

    def _elapsed_ms(self, name: str) -> float | None:
        value = self._events_ns.get(name)
        return None if value is None else round((value - self._origin_ns) / 1_000_000, 3)

    def _between_ms(self, start: str, end: str) -> float | None:
        left, right = self._events_ns.get(start), self._events_ns.get(end)
        return None if left is None or right is None else round((right - left) / 1_000_000, 3)

    def to_dict(self) -> dict[str, Any]:
        event_names = (
            "dispatch_started", "http_headers_received", "first_valid_pcm_yielded",
            "last_valid_pcm_yielded", "stream_terminal", "stream_closed", "file_save_completed",
        )
        return {
            "schema": "mira.tts.latency.v1",
            "clock": "monotonic_elapsed_ms",
            "events_ms": {name: self._elapsed_ms(name) for name in event_names},
            "durations_ms": {
                "dispatch_to_headers": self._between_ms("dispatch_started", "http_headers_received"),
                "dispatch_to_first_valid_pcm": self._between_ms("dispatch_started", "first_valid_pcm_yielded"),
                "headers_to_first_valid_pcm": self._between_ms("http_headers_received", "first_valid_pcm_yielded"),
                "dispatch_to_last_pcm": self._between_ms("dispatch_started", "last_valid_pcm_yielded"),
                "dispatch_to_stream_terminal": self._between_ms("dispatch_started", "stream_terminal"),
                "dispatch_to_file_save": self._between_ms("dispatch_started", "file_save_completed"),
                "last_pcm_to_file_save": self._between_ms("last_valid_pcm_yielded", "file_save_completed"),
            },
            "http_status": self._http_status,
            "stream_outcome": self._stream_outcome or "not_observed",
            "cancelled_after_first_valid_pcm": (
                self._valid_packets > 0 if self._stream_outcome == "cancelled" else None
            ),
            "file_save_outcome": self._file_save_outcome or "not_observed",
            "counts": {
                "non_audio_events": self._non_audio_events,
                "valid_pcm_packets": self._valid_packets,
                "valid_pcm_bytes": self._valid_bytes,
                "total_samples": self._total_samples,
                "invalid_pcm_packets": self._invalid_packets,
            },
            "authentication": "unobserved",
            "browser_scheduling": "unobserved",
            "physical_playback": "unobserved",
        }


def _persist_tts_latency(reporter: "DurableReporter", trace: TtsLatencyTrace | None) -> None:
    if trace is not None:
        reporter.record["tts_timing"] = trace.to_dict()
        reporter._flush()


class SmokeBlocked(RuntimeError):
    """A local preflight or one-shot execution stop; safe to report."""


class DurableReporter:
    """Append sanitized phases atomically and flush one JSON line per phase."""

    def __init__(self, path: Path, seed: dict[str, Any]):
        if path.exists():
            raise SmokeBlocked("report_already_exists")
        self.path = path
        self.record = {"schema": 1, **seed, "events": [], "state": "starting"}
        self._flush()

    def emit(self, phase: str, *, call: str | None = None, state: str | None = None,
             http_status: int | None = None, provider_error: str | None = None,
             first_packet_samples: int | None = None, duration_seconds: float | None = None,
             reserved_usd: str | None = None, fixed_text_match: bool | None = None,
             provider_status: str | None = None, provider_reason: str | None = None,
             field_names: list[str] | None = None, diagnostic: str | None = None,
             body_bytes_read: int | None = None, body_truncated: bool | None = None,
             body_capture_status: str | None = None,
             audio_diagnostic: dict[str, Any] | None = None,
             total_samples: int | None = None) -> None:
        allowed_phases = {
            "preflight_verified", "tts_reserved", "tts_dispatch_started",
            "tts_http_status_received", "tts_first_packet_received", "tts_cancel_started",
            "tts_transport_closed", "tts_completed", "tts_terminal_failure", "stt_reserved",
            "stt_dispatch_started", "stt_terminal_result", "resources_closed",
            "bundle_finalized", "bundle_interrupted_unknown", "bundle_blocked",
        }
        if phase not in allowed_phases or (state is not None and state not in {
            "starting", "ready", "reserved_unknown_usage", "completed",
            "cancelled_after_first_packet", "failed_unknown_usage", "blocked", "unknown",
        }):
            raise SmokeBlocked("invalid_report_event")
        if http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599):
            raise SmokeBlocked("invalid_report_http_status")
        if provider_error is not None and provider_error not in SAFE_PROVIDER_ERRORS:
            raise SmokeBlocked("invalid_report_provider_error")
        if provider_reason is not None and not re.fullmatch(r"[A-Z0-9_]{1,64}", provider_reason):
            raise SmokeBlocked("invalid_report_provider_reason")
        if provider_status is not None and provider_status not in {
            "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
            "FAILED_PRECONDITION", "NOT_FOUND", "UNAVAILABLE", "DEADLINE_EXCEEDED",
        }:
            raise SmokeBlocked("invalid_report_provider_status")
        safe_fields = _safe_field_names(field_names or [])
        if safe_fields != (field_names or []):
            raise SmokeBlocked("invalid_report_field_names")
        if diagnostic is not None and (not isinstance(diagnostic, str) or len(diagnostic) > 256
                                        or diagnostic != _sanitize_provider_message(diagnostic)):
            raise SmokeBlocked("invalid_report_diagnostic")
        if body_bytes_read is not None and (type(body_bytes_read) is not int or not 0 <= body_bytes_read <= MAX_ERROR_BODY_BYTES):
            raise SmokeBlocked("invalid_report_body_size")
        if body_truncated is not None and type(body_truncated) is not bool:
            raise SmokeBlocked("invalid_report_body_truncated")
        if body_capture_status is not None and body_capture_status not in {"parsed", "unparsed", "timeout", "unavailable"}:
            raise SmokeBlocked("invalid_report_body_status")
        if audio_diagnostic is not None:
            try:
                audio_diagnostic = _validate_audio_diagnostic(audio_diagnostic)
            except SmokeBlocked:
                raise SmokeBlocked("invalid_report_audio_diagnostic") from None
        if first_packet_samples is not None and (type(first_packet_samples) is not int or first_packet_samples < 0):
            raise SmokeBlocked("invalid_report_sample_count")
        if total_samples is not None and (type(total_samples) is not int or total_samples < 0):
            raise SmokeBlocked("invalid_report_total_sample_count")
        if duration_seconds is not None and (not isinstance(duration_seconds, (int, float)) or duration_seconds < 0):
            raise SmokeBlocked("invalid_report_duration")
        if reserved_usd is not None:
            try:
                amount = Decimal(reserved_usd)
            except (ValueError, ArithmeticError):
                raise SmokeBlocked("invalid_report_reservation") from None
            if not amount.is_finite() or amount < 0:
                raise SmokeBlocked("invalid_report_reservation")
        event = {"phase": phase, "at_epoch": time.time()}
        for key, value in (("call", call), ("state", state), ("http_status", http_status),
                           ("provider_error", provider_error), ("first_packet_samples", first_packet_samples),
                           ("duration_seconds", round(float(duration_seconds), 3) if duration_seconds is not None else None),
                           ("reserved_usd", reserved_usd), ("fixed_text_match", fixed_text_match),
                           ("provider_status", provider_status), ("provider_reason", provider_reason),
                           ("field_names", safe_fields if field_names is not None else None),
                           ("diagnostic", diagnostic), ("body_bytes_read", body_bytes_read),
                           ("body_truncated", body_truncated), ("body_capture_status", body_capture_status),
                           ("audio_diagnostic", audio_diagnostic), ("total_samples", total_samples)):
            if value is not None:
                event[key] = value
        self.record["events"].append(event)
        self.record["state"] = state or self.record["state"]
        self.record["last_phase"] = phase
        self.record["updated_at_epoch"] = event["at_epoch"]
        self._flush()
        print(json.dumps(event, sort_keys=True, separators=(",", ":")), flush=True)

    def _flush(self) -> None:
        _write_json_atomic(self.path, self.record)


class TtsRequestPolicyTransport:
    """Apply either the bounded cap or exact official minimal TTS request shape."""

    def __init__(self, delegate: Any, mode: str):
        if mode not in {"capped", "official_minimal"}:
            raise SmokeBlocked("invalid_tts_request_policy")
        self.delegate, self.mode = delegate, mode

    async def stream(self, *, url: str, body: dict[str, Any], timeout_seconds: float):
        request = json.loads(json.dumps(body))
        generation = request.get("generationConfig")
        if not isinstance(generation, dict):
            raise SmokeBlocked("tts_request_config_invalid")
        if self.mode == "capped":
            generation["maxOutputTokens"] = TTS_MAX_OUTPUT_TOKENS
        else:
            generation.pop("maxOutputTokens", None)
            generation.pop("responseFormat", None)
        async for event in self.delegate.stream(url=url, body=request, timeout_seconds=timeout_seconds):
            yield event


def check_readiness_receipt(path: Path, *, project_id: str, now: float | None = None) -> dict[str, Any]:
    """Require fresh, explicit readiness evidence without logging it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SmokeBlocked("readiness_receipt_unavailable") from None
    if not isinstance(data, dict):
        raise SmokeBlocked("readiness_receipt_invalid")
    if data.get("project_id") != project_id or data.get("project_state") != "ACTIVE":
        raise SmokeBlocked("project_not_verified")
    if data.get("tts_model") != TTS_MODEL or data.get("tts_location") != TTS_LOCATION:
        raise SmokeBlocked("tts_selection_mismatch")
    if data.get("stt_location") != STT_LOCATION or data.get("stt_model") != STT_MODEL:
        raise SmokeBlocked("stt_selection_mismatch")
    if data.get("stt_language") != STT_LANGUAGE or data.get("voice") != TTS_VOICE:
        raise SmokeBlocked("voice_selection_mismatch")
    if data.get("speech_api") != "ENABLED" or data.get("aiplatform_api") != "ENABLED":
        raise SmokeBlocked("required_api_state_unknown_or_disabled")
    permissions = data.get("granted_permissions")
    required = {"speech.recognizers.recognize", "aiplatform.endpoints.predict", "serviceusage.services.use"}
    if not isinstance(permissions, list) or not required.issubset(set(permissions)):
        raise SmokeBlocked("runtime_permissions_unverified")
    if data.get("billing_enabled") is not True:
        raise SmokeBlocked("billing_not_verified_enabled")
    if data.get("billing_currency") != "USD":
        raise SmokeBlocked("billing_currency_not_verified_usd")
    # Callers must derive this from an authorized, current billing/tax estimate;
    # no default or guessed rate is accepted.
    try:
        extra = Decimal(str(data["bounded_tax_and_fees_usd"]))
        issued_at = float(data["checked_at_epoch"])
    except (KeyError, ValueError, TypeError, ArithmeticError):
        raise SmokeBlocked("tax_fee_bound_missing") from None
    current = time.time() if now is None else now
    if not extra.is_finite() or extra < 0 or TOTAL_RESERVE_USD + extra > USD_LIMIT:
        raise SmokeBlocked("tax_fee_bound_exceeds_approval")
    if not (0 <= current - issued_at <= 900):
        raise SmokeBlocked("readiness_receipt_stale")
    return data


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _write_pcm_private(path: Path, pcm: bytes) -> None:
    """Atomically keep only bounded synthetic PCM with private filesystem modes."""
    if not isinstance(pcm, bytes) or not pcm or len(pcm) > STT_SAMPLE_RATE_HZ * 30 * 2:
        raise SmokeBlocked("pcm_artifact_bounds_invalid")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(pcm)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


@dataclass(frozen=True, slots=True)
class Reservation:
    call_id: str
    kind: str
    reserved_usd: Decimal


class SharedLedger:
    """Atomic no-retry ledger; uncertain attempts remain reserved forever."""

    def __init__(self, path: Path, *, budget_limit: Decimal = USD_LIMIT):
        if not isinstance(budget_limit, Decimal) or not budget_limit.is_finite() or budget_limit <= 0:
            raise SmokeBlocked("invalid_budget_limit")
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.budget_limit = budget_limit

    def reserve(self, kind: str, amount: Decimal) -> Reservation:
        if kind not in {*CALL_ORDER, ADDITIONAL_TTS_KIND, RECOVERY_TTS_KIND,
                        TTS_TEXT_DIAGNOSTIC_KIND, TTS_FINAL_APPROVED_KIND} or not amount.is_finite() or amount <= 0:
            raise SmokeBlocked("invalid_reservation")
        with self.lock_path.open("a+") as lock:
            os.chmod(self.lock_path, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if self.path.exists():
                try:
                    record = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    raise SmokeBlocked("ledger_unreadable") from None
            else:
                record = {"schema": 1, "currency": "USD", "calls": []}
            if (not isinstance(record, dict) or record.get("schema") != 1
                    or record.get("currency") != "USD" or not isinstance(record.get("calls"), list)):
                raise SmokeBlocked("ledger_invalid")
            calls = record["calls"]
            expected_amounts = {
                "tts_normal": TTS_RESERVE_USD,
                "tts_cancel_after_first_packet": TTS_RESERVE_USD,
                "tts_diagnostic_additional": TTS_FULL_RESERVE_USD,
                "tts_recovery_additional": TTS_FULL_RESERVE_USD,
                "tts_text_diagnostic_followup": TTS_FULL_RESERVE_USD,
                "tts_final_approved_additional": TTS_FULL_RESERVE_USD,
                "stt_v2": STT_RESERVE_USD,
            }
            if amount != expected_amounts[kind]:
                raise SmokeBlocked("reservation_amount_mismatch")
            sequence_ok = (
                (len(calls) == 0 and kind == "tts_normal")
                or (len(calls) == 1 and kind == "tts_cancel_after_first_packet")
                or (len(calls) == 2 and kind in {"stt_v2", ADDITIONAL_TTS_KIND})
                or (len(calls) == 3 and calls[2].get("kind") == ADDITIONAL_TTS_KIND and kind == "stt_v2")
                or (len(calls) == 4 and kind == RECOVERY_TTS_KIND)
                or (len(calls) == 5 and calls[4].get("kind") == RECOVERY_TTS_KIND and kind == "stt_v2")
                or (len(calls) == 6 and kind == TTS_TEXT_DIAGNOSTIC_KIND)
                or (len(calls) == 7 and calls[6].get("kind") == TTS_TEXT_DIAGNOSTIC_KIND and kind == "stt_v2")
                or (len(calls) == 7 and kind == TTS_FINAL_APPROVED_KIND)
            )
            if not sequence_ok or len(calls) >= 8:
                raise SmokeBlocked("attempt_already_recorded_or_out_of_order")
            try:
                committed = sum((Decimal(c["reserved_usd"]) for c in calls), Decimal("0"))
            except (KeyError, ValueError, TypeError, ArithmeticError):
                raise SmokeBlocked("ledger_invalid") from None
            if committed + amount > self.budget_limit:
                raise SmokeBlocked("approval_reservation_exceeded")
            index = len(calls) + 1
            reservation = Reservation(f"google-voice-{index}", kind, amount)
            calls.append({
                "call_id": reservation.call_id,
                "kind": kind,
                "attempt_count": 1,
                "state": "reserved_unknown_usage",
                "phase": "reserved_before_dispatch",
                "reserved_usd": format(amount, "f"),
                "started_at_epoch": time.time(),
            })
            record["reserved_total_usd"] = format(committed + amount, "f")
            _write_json_atomic(self.path, record)
            return reservation

    def set_phase(self, reservation: Reservation, phase: str, *, http_status: int | None = None,
                  provider_error: str | None = None, first_packet_samples: int | None = None,
                  provider_status: str | None = None, provider_reason: str | None = None,
                  field_names: list[str] | None = None, diagnostic: str | None = None,
                  body_bytes_read: int | None = None, body_truncated: bool | None = None,
                  body_capture_status: str | None = None) -> None:
        allowed_phases = {
            "dispatch_started", "http_status_received", "first_packet_received",
            "cancel_started", "transport_closed", "stt_dispatch_started",
            "stt_completed", "tts_completed", "interrupted_unknown", "terminal_failure",
        }
        if phase not in allowed_phases:
            raise SmokeBlocked("invalid_phase")
        if http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599):
            raise SmokeBlocked("invalid_http_status")
        if provider_error is not None and provider_error not in SAFE_PROVIDER_ERRORS:
            raise SmokeBlocked("invalid_provider_error")
        if provider_reason is not None and provider_reason not in SAFE_PROVIDER_REASONS:
            raise SmokeBlocked("invalid_provider_reason")
        if provider_status is not None and provider_status not in {
            "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
            "FAILED_PRECONDITION", "NOT_FOUND", "UNAVAILABLE", "DEADLINE_EXCEEDED",
        }:
            raise SmokeBlocked("invalid_provider_status")
        if field_names is not None and _safe_field_names(field_names) != field_names:
            raise SmokeBlocked("invalid_provider_fields")
        if diagnostic is not None and _sanitize_provider_message(diagnostic) != diagnostic:
            raise SmokeBlocked("invalid_provider_diagnostic")
        if body_bytes_read is not None and (type(body_bytes_read) is not int or not 0 <= body_bytes_read <= MAX_ERROR_BODY_BYTES):
            raise SmokeBlocked("invalid_body_size")
        if body_truncated is not None and type(body_truncated) is not bool:
            raise SmokeBlocked("invalid_body_truncated")
        if body_capture_status is not None and body_capture_status not in {"parsed", "unparsed", "timeout", "unavailable"}:
            raise SmokeBlocked("invalid_body_capture_status")
        if first_packet_samples is not None and (type(first_packet_samples) is not int or first_packet_samples < 0):
            raise SmokeBlocked("invalid_sample_count")
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                record = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise SmokeBlocked("ledger_unreadable") from None
            call = next((c for c in record.get("calls", []) if c.get("call_id") == reservation.call_id), None)
            if call is None or call.get("state") != "reserved_unknown_usage":
                raise SmokeBlocked("reservation_state_invalid")
            call["phase"] = phase
            call["phase_at_epoch"] = time.time()
            if http_status is not None:
                call["http_status"] = http_status
            if provider_error is not None:
                call["provider_error"] = provider_error
            if provider_reason is not None:
                call["provider_reason"] = provider_reason
            if provider_status is not None:
                call["provider_status"] = provider_status
            if field_names is not None:
                call["field_names"] = field_names
            if diagnostic is not None:
                call["diagnostic"] = diagnostic
            if body_bytes_read is not None:
                call["body_bytes_read"] = body_bytes_read
            if body_truncated is not None:
                call["body_truncated"] = body_truncated
            if body_capture_status is not None:
                call["body_capture_status"] = body_capture_status
            if first_packet_samples is not None:
                call["first_packet_samples"] = first_packet_samples
            _write_json_atomic(self.path, record)

    def finish(self, reservation: Reservation, state: str, *, status_class: str | None = None,
               sample_count: int | None = None, duration_seconds: float | None = None,
               token_cost_estimate_usd: str | None = None, http_status: int | None = None,
               provider_error: str | None = None, terminal_phase: str | None = None,
               provider_status: str | None = None, provider_reason: str | None = None,
               field_names: list[str] | None = None, diagnostic: str | None = None,
               body_bytes_read: int | None = None, body_truncated: bool | None = None,
               body_capture_status: str | None = None,
               audio_diagnostic: dict[str, Any] | None = None) -> None:
        if state not in {"completed", "cancelled_after_first_packet", "failed_unknown_usage"}:
            raise SmokeBlocked("invalid_call_state")
        # Store only fixed state/status and numeric metadata. Never accept free text.
        if status_class is not None and status_class not in {
            "2xx", "4xx", "5xx", "timeout", "cancelled", "transport_error"
        }:
            raise SmokeBlocked("invalid_status_class")
        if http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599):
            raise SmokeBlocked("invalid_http_status")
        if provider_error is not None and provider_error not in SAFE_PROVIDER_ERRORS:
            raise SmokeBlocked("invalid_provider_error")
        if provider_reason is not None and provider_reason not in SAFE_PROVIDER_REASONS:
            raise SmokeBlocked("invalid_provider_reason")
        if provider_status is not None and provider_status not in {
            "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
            "FAILED_PRECONDITION", "NOT_FOUND", "UNAVAILABLE", "DEADLINE_EXCEEDED",
        }:
            raise SmokeBlocked("invalid_provider_status")
        if field_names is not None and _safe_field_names(field_names) != field_names:
            raise SmokeBlocked("invalid_provider_fields")
        if diagnostic is not None and _sanitize_provider_message(diagnostic) != diagnostic:
            raise SmokeBlocked("invalid_provider_diagnostic")
        if body_bytes_read is not None and (type(body_bytes_read) is not int or not 0 <= body_bytes_read <= MAX_ERROR_BODY_BYTES):
            raise SmokeBlocked("invalid_body_size")
        if body_truncated is not None and type(body_truncated) is not bool:
            raise SmokeBlocked("invalid_body_truncated")
        if body_capture_status is not None and body_capture_status not in {"parsed", "unparsed", "timeout", "unavailable"}:
            raise SmokeBlocked("invalid_body_capture_status")
        if audio_diagnostic is not None:
            audio_diagnostic = _validate_audio_diagnostic(audio_diagnostic)
        if terminal_phase is not None and terminal_phase not in {
            "tts_cancelled_after_first_packet", "tts_completed", "stt_completed",
            "terminal_failure", "interrupted_unknown"
        }:
            raise SmokeBlocked("invalid_terminal_phase")
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                record = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise SmokeBlocked("ledger_unreadable") from None
            call = next((c for c in record.get("calls", []) if c.get("call_id") == reservation.call_id), None)
            if call is None or call.get("state") != "reserved_unknown_usage":
                raise SmokeBlocked("reservation_state_invalid")
            call["state"] = state
            call["finished_at_epoch"] = time.time()
            if status_class is not None:
                call["status_class"] = status_class
            if http_status is not None:
                call["http_status"] = http_status
            if provider_error is not None:
                call["provider_error"] = provider_error
            if provider_reason is not None:
                call["provider_reason"] = provider_reason
            if provider_status is not None:
                call["provider_status"] = provider_status
            if field_names is not None:
                call["field_names"] = field_names
            if diagnostic is not None:
                call["diagnostic"] = diagnostic
            if body_bytes_read is not None:
                call["body_bytes_read"] = body_bytes_read
            if body_truncated is not None:
                call["body_truncated"] = body_truncated
            if body_capture_status is not None:
                call["body_capture_status"] = body_capture_status
            if audio_diagnostic is not None:
                call["audio_diagnostic"] = audio_diagnostic
            if terminal_phase is not None:
                call["phase"] = terminal_phase
            if sample_count is not None:
                if type(sample_count) is not int or sample_count < 0:
                    raise SmokeBlocked("invalid_sample_count")
                call["sample_count"] = sample_count
            if duration_seconds is not None:
                if not isinstance(duration_seconds, (float, int)) or duration_seconds < 0:
                    raise SmokeBlocked("invalid_duration")
                call["duration_seconds"] = round(float(duration_seconds), 3)
            if token_cost_estimate_usd is not None:
                try:
                    estimate = Decimal(token_cost_estimate_usd)
                except (ValueError, ArithmeticError):
                    raise SmokeBlocked("invalid_cost_estimate") from None
                if not estimate.is_finite() or estimate < 0 or estimate > reservation.reserved_usd:
                    raise SmokeBlocked("cost_estimate_exceeds_reservation")
                call["token_cost_estimate_usd"] = format(estimate, "f")
            _write_json_atomic(self.path, record)


def make_readiness_receipt(*, project_id: str, project_state: str, granted_permissions: list[str],
                           speech_api: str, aiplatform_api: str, billing_enabled: bool,
                           billing_currency: str, bounded_tax_and_fees_usd: str,
                           checked_at_epoch: float | None = None) -> dict[str, Any]:
    """Small pure builder used by tests and external sanitized receipt writers."""
    return {
        "project_id": project_id, "project_state": project_state,
        "granted_permissions": list(granted_permissions),
        "speech_api": speech_api, "aiplatform_api": aiplatform_api,
        "billing_enabled": billing_enabled, "billing_currency": billing_currency,
        "bounded_tax_and_fees_usd": bounded_tax_and_fees_usd,
        "checked_at_epoch": time.time() if checked_at_epoch is None else checked_at_epoch,
        "tts_model": TTS_MODEL, "tts_location": TTS_LOCATION, "voice": TTS_VOICE,
        "stt_location": STT_LOCATION, "stt_model": STT_MODEL,
        "stt_language": STT_LANGUAGE,
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SmokeBlocked("readiness_receipt_unavailable") from None
    if not isinstance(value, dict):
        raise SmokeBlocked("readiness_receipt_invalid")
    return value


def check_resume_readiness(readiness_path: Path, enable_receipt_path: Path, *, project_id: str) -> dict[str, Any]:
    """Check existing sanitized setup evidence; preserve billing unknown as unknown."""
    readiness = _read_json_object(readiness_path)
    enabled = _read_json_object(enable_receipt_path)
    project = readiness.get("results", {}).get("project", {})
    permissions = readiness.get("results", {}).get("permissions", {}).get("granted", [])
    if (project.get("status") != "ok" or project.get("id_matches") is not True
            or project.get("lifecycle_state") != "ACTIVE"):
        raise SmokeBlocked("project_not_verified")
    if enabled.get("project_id") != project_id:
        raise SmokeBlocked("enablement_project_mismatch")
    result = enabled.get("results", {})
    if (result.get("aiplatform_state", {}).get("service_state") != "ENABLED"
            or result.get("speech_final_state", {}).get("service_state") != "ENABLED"):
        raise SmokeBlocked("required_api_state_unknown_or_disabled")
    required = {"speech.recognizers.recognize", "aiplatform.endpoints.predict", "serviceusage.services.use"}
    if not isinstance(permissions, list) or not required.issubset(set(permissions)):
        raise SmokeBlocked("runtime_permissions_unverified")
    # Billing's read API itself was unavailable. Never promote that to true/false;
    # the approved per-call token/duration reservations remain the charge guard.
    billing = readiness.get("results", {}).get("billing", {})
    return {
        "billing_status": "unknown",
        "billing_http_status": billing.get("http_status") if type(billing.get("http_status")) is int else None,
        "billing_error_reason": "SERVICE_DISABLED" if "SERVICE_DISABLED" in billing.get("error_reasons", []) else "unknown",
    }


def _ledger_calls(path: Path) -> list[dict[str, Any]]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        calls = record["calls"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        raise SmokeBlocked("ledger_unreadable") from None
    if (not isinstance(record, dict) or record.get("schema") != 1 or record.get("currency") != "USD"
            or not isinstance(calls, list)):
        raise SmokeBlocked("ledger_invalid")
    return calls


def _status_class(status: int | None, error: Exception | None = None) -> str:
    if status is not None:
        return "2xx" if 200 <= status < 300 else "4xx" if 400 <= status < 500 else "5xx" if status >= 500 else "transport_error"
    return _safe_status(error or RuntimeError("unknown"))


def _provider_error_code(error: Exception | None) -> str | None:
    if error is None:
        return None
    value = getattr(error, "code", None)
    value = getattr(value, "value", value)
    return value if isinstance(value, str) and value in SAFE_PROVIDER_ERRORS else "unknown"


def _safe_provider_details(error: Exception | None) -> dict[str, Any]:
    details = getattr(error, "details", None) if error is not None else None
    if details is None:
        return {}
    status = getattr(details, "http_status", None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    provider_status = getattr(details, "provider_status", None)
    provider_status = provider_status if provider_status in {
        "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
        "FAILED_PRECONDITION", "NOT_FOUND", "UNAVAILABLE", "DEADLINE_EXCEEDED",
    } else None
    reason = getattr(details, "provider_reason", None)
    reason = reason if reason in SAFE_PROVIDER_REASONS else None
    fields = _safe_field_names(list(getattr(details, "field_names", ())))
    diagnostic = getattr(details, "diagnostic", None)
    diagnostic = diagnostic if _sanitize_provider_message(diagnostic or "") else None
    size = getattr(details, "body_bytes_read", None)
    size = size if type(size) is int and 0 <= size <= MAX_ERROR_BODY_BYTES else None
    truncated = getattr(details, "body_truncated", None)
    truncated = truncated if type(truncated) is bool else None
    capture = getattr(details, "body_capture_status", None)
    capture = capture if capture in {"parsed", "unparsed", "timeout", "unavailable"} else None
    output = {"http_status": status, "provider_status": provider_status,
              "provider_reason": reason, "field_names": fields, "diagnostic": diagnostic,
              "body_bytes_read": size, "body_truncated": truncated,
              "body_capture_status": capture}
    return {key: value for key, value in output.items() if value is not None}


def _safe_audio_details(error: Exception | None, *, approved_text: str = SYNTHETIC_TEXT,
                        project_id: str | None = None) -> dict[str, Any]:
    """Project response metadata onto a small allowlist; never expose audio bytes."""
    details = getattr(error, "audio_details", None) if error is not None else None
    if details is None:
        return {}
    part_allowlist = {"inlineData", "text", "thought", "functionCall", "functionResponse",
                      "videoMetadata", "executableCode", "codeExecutionResult", "fileData",
                      "thoughtSignature"}
    reason_allowlist = {"non_audio_part", "unsupported_mime_type", "unsupported_mime_parameter",
                        "missing_audio_data", "audio_data_too_large", "invalid_base64",
                        "odd_pcm_bytes", "wav_header"}
    parts = getattr(details, "part_type_names", ())
    params = getattr(details, "mime_param_names", ())
    result = {
        "part_index": getattr(details, "part_index", None),
        "part_type_names": [v for v in parts if v in part_allowlist][:8] if isinstance(parts, tuple) else [],
        "mime_type": getattr(details, "mime_type", None),
        "mime_param_names": [v for v in params if v in {"codec", "rate", "channels"}][:8] if isinstance(params, tuple) else [],
        "sample_rate_hz": getattr(details, "sample_rate_hz", None),
        "channels": getattr(details, "channels", None),
        "codec": getattr(details, "codec", None),
        "audio_data_chars": getattr(details, "audio_data_chars", None),
        "candidate_finish_reason": getattr(details, "candidate_finish_reason", None),
        "validation_reason": getattr(details, "validation_reason", None),
        "pcm_byte_count": getattr(details, "pcm_byte_count", None),
        "wav_header": getattr(details, "wav_header", None),
        "model_version": getattr(details, "model_version", None),
        "input_token_count": getattr(details, "input_token_count", None),
        "output_token_count": getattr(details, "output_token_count", None),
        "total_token_count": getattr(details, "total_token_count", None),
        "response_text_excerpt": getattr(details, "response_text_excerpt", None),
    }
    mime = result["mime_type"]
    if not isinstance(mime, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.+-]{0,31}/[a-z0-9][a-z0-9.+-]{0,31}", mime):
        result["mime_type"] = None
    if result["validation_reason"] not in reason_allowlist:
        result["validation_reason"] = None
    if result["codec"] not in {"pcm", "alaw", "mulaw", "unknown"}:
        result["codec"] = None
    if result["candidate_finish_reason"] not in {
        "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER", "BLOCKLIST",
        "PROHIBITED_CONTENT", "SPII", "IMAGE_PROHIBITED_CONTENT",
    }:
        result["candidate_finish_reason"] = None
    if result["model_version"] is not None and (
            not isinstance(result["model_version"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", result["model_version"])):
        result["model_version"] = None
    for key in ("input_token_count", "output_token_count", "total_token_count"):
        value = result[key]
        if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000):
            result[key] = None
    excerpt = result["response_text_excerpt"]
    if excerpt is not None:
        if not isinstance(excerpt, str):
            excerpt = ""
        excerpt = excerpt[:2048]
        if approved_text:
            excerpt = excerpt.replace(approved_text, "[synthetic-prompt-redacted]")
        if project_id and len(project_id) >= 3:
            excerpt = re.sub(re.escape(project_id), "[project-id-redacted]", excerpt, flags=re.I)
        for pattern, replacement in (
            (r"(?i)\bbearer\s+[^\s,;]+", "[credential-redacted]"),
            (r"\bya29\.[A-Za-z0-9._~+/-]+", "[credential-redacted]"),
            (r"\bAIza[A-Za-z0-9_-]{20,}", "[credential-redacted]"),
            (r"(?i)\b(?:access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|password|api[_ -]?key)\b\s*[:=]\s*[^\s,;]+", "[credential-redacted]"),
            (r"(?i)https?://[^\s]+", "[url-redacted]"),
            (r"\b(?:projects|locations|publishers|models|endpoints|recognizers)/[A-Za-z0-9_.-]+", "[resource-redacted]"),
            (r"\b[A-Za-z0-9_-]{40,}\b", "[opaque-value-redacted]"),
        ):
            excerpt = re.sub(pattern, replacement, excerpt)
        excerpt = "".join(ch if ch in "\t\n\r" or ord(ch) >= 32 else " " for ch in excerpt)[:512]
        result["response_text_excerpt"] = excerpt or None
    for key, minimum, maximum in (
        ("part_index", 0, 255), ("sample_rate_hz", 1000, 384000), ("channels", 1, 8),
        ("audio_data_chars", 0, 2 * 1024 * 1024), ("pcm_byte_count", 0, 2 * 1024 * 1024),
    ):
        value = result[key]
        if value is not None and (type(value) is not int or not minimum <= value <= maximum):
            result[key] = None
    if result["wav_header"] is not None and type(result["wav_header"]) is not bool:
        result["wav_header"] = None
    return {key: value for key, value in result.items() if value is not None}


def _validate_audio_diagnostic(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "part_index", "part_type_names", "mime_type", "mime_param_names", "sample_rate_hz",
        "channels", "codec", "audio_data_chars", "candidate_finish_reason",
        "validation_reason", "pcm_byte_count", "wav_header", "model_version",
        "input_token_count", "output_token_count", "total_token_count", "response_text_excerpt",
    }:
        raise SmokeBlocked("invalid_audio_diagnostic")
    payload = dict(value)
    for key in ("part_type_names", "mime_param_names"):
        if key in payload:
            if not isinstance(payload[key], list):
                raise SmokeBlocked("invalid_audio_diagnostic")
            payload[key] = tuple(payload[key])
    projected = _safe_audio_details(
        type("SafeAudioError", (), {"audio_details": type("SafeAudio", (), payload)()})()
    )
    if any(projected.get(key) != item for key, item in value.items()):
        raise SmokeBlocked("invalid_audio_diagnostic")
    return projected


async def run_remaining_cancel_stt(readiness_path: Path, enable_receipt_path: Path,
                                   ledger_path: Path, report_path: Path, *, project_id: str,
                                   adc_dir: Path,
                                   adapter_factory: Callable[[Callable[[int], None]], tuple[Any, Any, Any]] | None = None
                                   ) -> dict[str, Any]:
    """Spend only the remaining cancel-TTS slot and one STT stream on its PCM packet."""
    import re
    if not isinstance(project_id, str) or not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise SmokeBlocked("invalid_project_id")
    billing = check_resume_readiness(readiness_path, enable_receipt_path, project_id=project_id)
    prior = _ledger_calls(ledger_path)
    if (len(prior) != 1 or prior[0].get("kind") != "tts_normal"
            or prior[0].get("state") != "reserved_unknown_usage"
            or prior[0].get("attempt_count") != 1
            or Decimal(prior[0].get("reserved_usd", "0")) != TTS_RESERVE_USD):
        raise SmokeBlocked("unknown_normal_reservation_not_sole_prior_attempt")
    previous_reserved = sum((Decimal(c["reserved_usd"]) for c in prior), Decimal("0"))
    reporter = DurableReporter(report_path, {
        "project": "selected_project", "tts_model": TTS_MODEL, "tts_location": TTS_LOCATION,
        "voice": TTS_VOICE, "stt_model": STT_MODEL, "stt_location": STT_LOCATION,
        "stt_language": STT_LANGUAGE, "billing_status": billing["billing_status"],
        "billing_read_http_status": billing["billing_http_status"],
        "billing_read_error_reason": billing["billing_error_reason"],
        "previous_normal_call": "reserved_unknown_usage",
        "previous_normal_reserved_usd": format(previous_reserved, "f"),
        "pre_tax_reserved_max_usd": format(previous_reserved + TTS_RESERVE_USD + STT_RESERVE_USD, "f"),
        "taxes_and_fees_status": "unknown",
        "full_phrase_accuracy_claim": False,
    })
    ledger = SharedLedger(ledger_path)
    statuses: list[int] = []
    tts_reservation = None

    def status_received(status: int) -> None:
        statuses.append(status)
        if tts_reservation is not None:
            ledger.set_phase(tts_reservation, "http_status_received", http_status=status)
        reporter.emit("tts_http_status_received", call="tts_cancel_after_first_packet",
                      state="reserved_unknown_usage", http_status=status)

    resources = None
    tts_stream = None
    first_packet = None
    try:
        reporter.emit("preflight_verified", state="ready")
        if adapter_factory is None:
            tts, stt, resources = _make_live_adapters(
                billing, project_id=project_id, adc_dir=adc_dir, on_http_status=status_received
            )
        else:
            tts, stt, resources = adapter_factory(status_received)

        tts_reservation = ledger.reserve(CALL_ORDER[1], TTS_RESERVE_USD)
        reporter.emit("tts_reserved", call=CALL_ORDER[1], state="reserved_unknown_usage",
                      reserved_usd=format(TTS_RESERVE_USD, "f"))
        ledger.set_phase(tts_reservation, "dispatch_started")
        reporter.emit("tts_dispatch_started", call=CALL_ORDER[1], state="reserved_unknown_usage")
        tts_stream = tts.synthesize(SYNTHETIC_TEXT, "google-smoke-cancel")
        try:
            first_packet = await anext(tts_stream)
        except asyncio.CancelledError:
            ledger.set_phase(tts_reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call=CALL_ORDER[1], state="unknown")
            raise
        except Exception as error:
            status = statuses[-1] if statuses else None
            code = _provider_error_code(error)
            provider_details = _safe_provider_details(error)
            detail_status = provider_details.get("http_status", status)
            ledger.finish(tts_reservation, "failed_unknown_usage", status_class=_status_class(status, error),
                          http_status=detail_status, provider_error=code, terminal_phase="terminal_failure",
                          provider_reason=provider_details.get("provider_reason"),
                          field_names=provider_details.get("field_names"),
                          diagnostic=provider_details.get("diagnostic"))
            reporter.emit("tts_terminal_failure", call=CALL_ORDER[1], state="failed_unknown_usage",
                          http_status=detail_status, provider_error=code,
                          provider_reason=provider_details.get("provider_reason"),
                          field_names=provider_details.get("field_names"),
                          diagnostic=provider_details.get("diagnostic"))
            return reporter.record

        from mira.application.ports.media import AudioPacket
        if (not isinstance(first_packet, AudioPacket) or first_packet.sample_rate_hz != STT_SAMPLE_RATE_HZ
                or not first_packet.pcm or len(first_packet.pcm) % 2
                or len(first_packet.pcm) // 2 > int(STT_MAX_SECONDS * STT_SAMPLE_RATE_HZ)):
            status = statuses[-1] if statuses else None
            ledger.finish(tts_reservation, "failed_unknown_usage", status_class=_status_class(status),
                          http_status=status, provider_error="invalid_audio", terminal_phase="terminal_failure")
            reporter.emit("tts_terminal_failure", call=CALL_ORDER[1], state="failed_unknown_usage",
                          http_status=status, provider_error="invalid_audio")
            return reporter.record
        if not statuses or statuses[-1] != 200:
            status = statuses[-1] if statuses else None
            ledger.finish(tts_reservation, "failed_unknown_usage", status_class=_status_class(status),
                          http_status=status, provider_error="unknown", terminal_phase="terminal_failure")
            reporter.emit("tts_terminal_failure", call=CALL_ORDER[1], state="failed_unknown_usage",
                          http_status=status, provider_error="unknown")
            return reporter.record

        first_samples = len(first_packet.pcm) // 2
        ledger.set_phase(tts_reservation, "first_packet_received", http_status=200,
                         first_packet_samples=first_samples)
        reporter.emit("tts_first_packet_received", call=CALL_ORDER[1], state="reserved_unknown_usage",
                      http_status=200, first_packet_samples=first_samples,
                      duration_seconds=first_samples / STT_SAMPLE_RATE_HZ)
        ledger.set_phase(tts_reservation, "cancel_started", http_status=200,
                         first_packet_samples=first_samples)
        reporter.emit("tts_cancel_started", call=CALL_ORDER[1], state="reserved_unknown_usage",
                      http_status=200, first_packet_samples=first_samples)
        await tts_stream.aclose()
        ledger.set_phase(tts_reservation, "transport_closed", http_status=200,
                         first_packet_samples=first_samples)
        ledger.finish(tts_reservation, "cancelled_after_first_packet", status_class="2xx",
                      http_status=200, sample_count=first_samples,
                      duration_seconds=first_samples / STT_SAMPLE_RATE_HZ,
                      terminal_phase="tts_cancelled_after_first_packet")
        reporter.emit("tts_transport_closed", call=CALL_ORDER[1], state="cancelled_after_first_packet",
                      http_status=200, first_packet_samples=first_samples,
                      duration_seconds=first_samples / STT_SAMPLE_RATE_HZ,
                      reserved_usd=format(TTS_RESERVE_USD, "f"))

        pcm_16k, samples_16k = _resample_mono_s16le(first_packet.pcm, first_packet.sample_rate_hz, 16000)
        if not pcm_16k or samples_16k > 30 * 16000:
            reporter.emit("bundle_blocked", call=CALL_ORDER[2], state="blocked", provider_error="input_limit")
            reporter.record["state"] = "blocked"
            reporter._flush()
            return reporter.record

        stt_reservation = ledger.reserve(CALL_ORDER[2], STT_RESERVE_USD)
        reporter.emit("stt_reserved", call=CALL_ORDER[2], state="reserved_unknown_usage",
                      reserved_usd=format(STT_RESERVE_USD, "f"))
        ledger.set_phase(stt_reservation, "stt_dispatch_started")
        reporter.emit("stt_dispatch_started", call=CALL_ORDER[2], state="reserved_unknown_usage")
        async def pcm_packets():
            cursor = 0
            for offset in range(0, len(pcm_16k), 12000):
                part = pcm_16k[offset:offset + 12000]
                yield AudioPacket("google-smoke-stt", cursor, 16000, part)
                cursor += len(part) // 2
        try:
            revisions = [r async for r in stt.transcribe(pcm_packets())]
        except asyncio.CancelledError:
            ledger.set_phase(stt_reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call=CALL_ORDER[2], state="unknown")
            raise
        except Exception as error:
            code = _provider_error_code(error)
            ledger.finish(stt_reservation, "failed_unknown_usage", status_class=_safe_status(error),
                          provider_error=code, sample_count=samples_16k,
                          duration_seconds=samples_16k / 16000, terminal_phase="terminal_failure")
            reporter.emit("stt_terminal_result", call=CALL_ORDER[2], state="failed_unknown_usage",
                          provider_error=code, first_packet_samples=samples_16k,
                          duration_seconds=samples_16k / 16000)
            return reporter.record
        final_text = next((r.text for r in reversed(revisions) if r.is_final), None)
        ledger.finish(stt_reservation, "completed", status_class="2xx", sample_count=samples_16k,
                      duration_seconds=samples_16k / 16000, terminal_phase="stt_completed")
        reporter.emit("stt_terminal_result", call=CALL_ORDER[2], state="completed",
                      first_packet_samples=samples_16k, duration_seconds=samples_16k / 16000,
                      fixed_text_match=final_text == SYNTHETIC_TEXT)
        reporter.record["final_revision_received"] = final_text is not None
        reporter.record["partial_recognition_only"] = final_text != SYNTHETIC_TEXT
        reporter.record["finalized_at_epoch"] = time.time()
        reporter.record["state"] = "completed"
        reporter._flush()
        reporter.emit("bundle_finalized", state="completed")
        return reporter.record
    finally:
        if tts_stream is not None:
            try:
                await tts_stream.aclose()
            except Exception:
                pass
        await _close_resources(resources)
        if resources is not None:
            try:
                reporter.emit("resources_closed", state=reporter.record.get("state", "unknown"))
            except Exception:
                pass


async def run_additional_official_tts(readiness_path: Path, enable_receipt_path: Path,
                                     ledger_path: Path, report_path: Path, *, project_id: str,
                                     adc_dir: Path,
                                     adapter_factory: Callable[[Callable[[int], None]], tuple[Any, Any, Any]] | None = None
                                     ) -> dict[str, Any]:
    """Use the newly authorized single TTS slot with the official minimal body, then its STT slot."""
    import re
    if not isinstance(project_id, str) or not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise SmokeBlocked("invalid_project_id")
    billing = check_resume_readiness(readiness_path, enable_receipt_path, project_id=project_id)
    prior = _ledger_calls(ledger_path)
    if (len(prior) != 2 or prior[0].get("kind") != "tts_normal"
            or prior[0].get("state") != "reserved_unknown_usage"
            or prior[0].get("attempt_count") != 1
            or Decimal(prior[0].get("reserved_usd", "0")) != TTS_RESERVE_USD
            or prior[1].get("kind") != "tts_cancel_after_first_packet"
            or prior[1].get("state") != "failed_unknown_usage"
            or prior[1].get("http_status") != 400
            or prior[1].get("provider_error") != "invalid_input"
            or Decimal(prior[1].get("reserved_usd", "0")) != TTS_RESERVE_USD):
        raise SmokeBlocked("expected_unknown_and_invalid_input_prior_attempts")
    ledger = SharedLedger(ledger_path)
    prior_reserved = sum((Decimal(c["reserved_usd"]) for c in prior), Decimal("0"))
    projected_with_stt = prior_reserved + TTS_FULL_RESERVE_USD + STT_RESERVE_USD
    if projected_with_stt > USD_LIMIT:
        raise SmokeBlocked("approved_aggregate_reserve_exceeded")
    reporter = DurableReporter(report_path, {
        "project": "selected_project", "tts_model": TTS_MODEL, "tts_location": TTS_LOCATION,
        "voice": TTS_VOICE, "stt_model": STT_MODEL, "stt_location": STT_LOCATION,
        "stt_language": STT_LANGUAGE, "billing_status": billing["billing_status"],
        "billing_read_http_status": billing["billing_http_status"],
        "billing_read_error_reason": billing["billing_error_reason"],
        "prior_call_count": len(prior), "prior_reserved_usd": format(prior_reserved, "f"),
        "additional_tts_reserve_usd": format(TTS_FULL_RESERVE_USD, "f"),
        "projected_pre_tax_total_with_stt_usd": format(projected_with_stt, "f"),
        "taxes_and_fees_status": "unknown", "request_mode": "official_minimal_streaming_tts",
        "full_phrase_accuracy_claim": False,
    })
    statuses: list[int] = []
    tts_reservation: Reservation | None = None
    resources = None
    tts_stream = None

    def status_received(status: int) -> None:
        statuses.append(status)
        if tts_reservation is not None:
            ledger.set_phase(tts_reservation, "http_status_received", http_status=status)
        reporter.emit("tts_http_status_received", call=ADDITIONAL_TTS_KIND,
                      state="reserved_unknown_usage", http_status=status)

    try:
        reporter.emit("preflight_verified", state="ready")
        if adapter_factory is None:
            tts, stt, resources = _make_live_adapters(
                billing, project_id=project_id, adc_dir=adc_dir,
                on_http_status=status_received, tts_mode="official_minimal",
            )
        else:
            tts, stt, resources = adapter_factory(status_received)

        tts_reservation = ledger.reserve(ADDITIONAL_TTS_KIND, TTS_FULL_RESERVE_USD)
        reporter.emit("tts_reserved", call=ADDITIONAL_TTS_KIND, state="reserved_unknown_usage",
                      reserved_usd=format(TTS_FULL_RESERVE_USD, "f"))
        ledger.set_phase(tts_reservation, "dispatch_started")
        reporter.emit("tts_dispatch_started", call=ADDITIONAL_TTS_KIND, state="reserved_unknown_usage")
        tts_stream = tts.synthesize(SYNTHETIC_TEXT, "google-smoke-additional")
        packets = []
        try:
            async for packet in tts_stream:
                if (not isinstance(packet, __import__("mira.application.ports.media", fromlist=["AudioPacket"]).AudioPacket)
                        or packet.stream_id != "google-smoke-additional"
                        or packet.sample_rate_hz != STT_SAMPLE_RATE_HZ
                        or not isinstance(packet.pcm, bytes) or not packet.pcm or len(packet.pcm) % 2):
                    raise SmokeBlocked("invalid_tts_audio_packet")
                packets.append(packet)
        except asyncio.CancelledError:
            ledger.set_phase(tts_reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call=ADDITIONAL_TTS_KIND, state="unknown")
            raise
        except Exception as error:
            status = statuses[-1] if statuses else None
            detail = _safe_provider_details(error)
            audio_detail = _safe_audio_details(error)
            http_status = detail.get("http_status", status)
            code = _provider_error_code(error) or "unknown"
            ledger.finish(
                tts_reservation, "failed_unknown_usage", status_class=_status_class(http_status, error),
                http_status=http_status, provider_error=code, terminal_phase="terminal_failure",
                provider_status=detail.get("provider_status"), provider_reason=detail.get("provider_reason"),
                field_names=detail.get("field_names"), diagnostic=detail.get("diagnostic"),
                body_bytes_read=detail.get("body_bytes_read"), body_truncated=detail.get("body_truncated"),
                body_capture_status=detail.get("body_capture_status"),
                audio_diagnostic=audio_detail or None,
            )
            reporter.emit(
                "tts_terminal_failure", call=ADDITIONAL_TTS_KIND, state="failed_unknown_usage",
                http_status=http_status, provider_error=code,
                provider_status=detail.get("provider_status"), provider_reason=detail.get("provider_reason"),
                field_names=detail.get("field_names"), diagnostic=detail.get("diagnostic"),
                body_bytes_read=detail.get("body_bytes_read"), body_truncated=detail.get("body_truncated"),
                body_capture_status=detail.get("body_capture_status"),
                audio_diagnostic=audio_detail or None,
            )
            return reporter.record

        status = statuses[-1] if statuses else None
        sample_count = sum(len(packet.pcm) // 2 for packet in packets)
        if (status != 200 or not packets or sample_count > 30 * STT_SAMPLE_RATE_HZ):
            ledger.finish(tts_reservation, "failed_unknown_usage", status_class=_status_class(status),
                          http_status=status, provider_error="unknown", sample_count=sample_count,
                          duration_seconds=sample_count / STT_SAMPLE_RATE_HZ,
                          terminal_phase="terminal_failure")
            reporter.emit("tts_terminal_failure", call=ADDITIONAL_TTS_KIND, state="failed_unknown_usage",
                          http_status=status, provider_error="unknown", first_packet_samples=sample_count,
                          duration_seconds=sample_count / STT_SAMPLE_RATE_HZ)
            return reporter.record

        pcm_24k = b"".join(packet.pcm for packet in packets)
        ledger.finish(tts_reservation, "completed", status_class="2xx", http_status=200,
                      sample_count=sample_count, duration_seconds=sample_count / STT_SAMPLE_RATE_HZ,
                      terminal_phase="tts_completed")
        reporter.emit("tts_completed", call=ADDITIONAL_TTS_KIND, state="completed", http_status=200,
                      first_packet_samples=sample_count, duration_seconds=sample_count / STT_SAMPLE_RATE_HZ,
                      reserved_usd=format(TTS_FULL_RESERVE_USD, "f"))

        pcm_16k, samples_16k = _resample_mono_s16le(pcm_24k, STT_SAMPLE_RATE_HZ, 16000)
        if not pcm_16k or samples_16k > 30 * 16000:
            reporter.emit("bundle_blocked", call="stt_v2", state="blocked", provider_error="input_limit")
            reporter.record["state"] = "blocked"
            reporter._flush()
            return reporter.record
        stt_reservation = ledger.reserve("stt_v2", STT_RESERVE_USD)
        reporter.emit("stt_reserved", call="stt_v2", state="reserved_unknown_usage",
                      reserved_usd=format(STT_RESERVE_USD, "f"))
        ledger.set_phase(stt_reservation, "stt_dispatch_started")
        reporter.emit("stt_dispatch_started", call="stt_v2", state="reserved_unknown_usage")
        from mira.application.ports.media import AudioPacket
        async def pcm_packets():
            cursor = 0
            for offset in range(0, len(pcm_16k), 12000):
                chunk = pcm_16k[offset:offset + 12000]
                yield AudioPacket("google-smoke-stt", cursor, 16000, chunk)
                cursor += len(chunk) // 2
        try:
            revisions = [revision async for revision in stt.transcribe(pcm_packets())]
        except asyncio.CancelledError:
            ledger.set_phase(stt_reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call="stt_v2", state="unknown")
            raise
        except Exception as error:
            code = _provider_error_code(error) or "unknown"
            detail = _safe_provider_details(error)
            ledger.finish(stt_reservation, "failed_unknown_usage", status_class=_safe_status(error),
                          provider_error=code, sample_count=samples_16k,
                          duration_seconds=samples_16k / 16000, terminal_phase="terminal_failure",
                          provider_status=detail.get("provider_status"), provider_reason=detail.get("provider_reason"),
                          field_names=detail.get("field_names"), diagnostic=detail.get("diagnostic"),
                          body_bytes_read=detail.get("body_bytes_read"), body_truncated=detail.get("body_truncated"),
                          body_capture_status=detail.get("body_capture_status"))
            reporter.emit("stt_terminal_result", call="stt_v2", state="failed_unknown_usage",
                          provider_error=code, first_packet_samples=samples_16k,
                          duration_seconds=samples_16k / 16000)
            return reporter.record
        final_text = next((revision.text for revision in reversed(revisions) if revision.is_final), None)
        ledger.finish(stt_reservation, "completed", status_class="2xx", sample_count=samples_16k,
                      duration_seconds=samples_16k / 16000, terminal_phase="stt_completed")
        reporter.emit("stt_terminal_result", call="stt_v2", state="completed",
                      first_packet_samples=samples_16k, duration_seconds=samples_16k / 16000,
                      fixed_text_match=final_text == SYNTHETIC_TEXT)
        reporter.record["final_revision_received"] = final_text is not None
        reporter.record["partial_recognition_only"] = final_text is None
        reporter.record["finalized_at_epoch"] = time.time()
        reporter.record["state"] = "completed"
        reporter._flush()
        reporter.emit("bundle_finalized", state="completed")
        return reporter.record
    finally:
        if tts_stream is not None:
            try:
                await tts_stream.aclose()
            except Exception:
                pass
        await _close_resources(resources)
        if resources is not None:
            try:
                reporter.emit("resources_closed", state=reporter.record.get("state", "unknown"))
            except Exception:
                pass


async def run_offline_english_fixture_stt(readiness_path: Path, enable_receipt_path: Path,
                                         ledger_path: Path, report_path: Path, *, project_id: str,
                                         adc_dir: Path, fixture_dir: Path = OFFLINE_FLITE_FIXTURE_DIR,
                                         adapter_factory: Callable[[str], tuple[Any, Any, Any]] | None = None,
                                         recovery_after_tts: bool = False,
                                         ) -> dict[str, Any]:
    """Consume one approved STT slot using a verified synthetic en-US Flite fixture."""
    import re
    if not isinstance(project_id, str) or not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise SmokeBlocked("invalid_project_id")
    billing = check_resume_readiness(readiness_path, enable_receipt_path, project_id=project_id)
    prior = _ledger_calls(ledger_path)
    if recovery_after_tts:
        expected_kinds = ["tts_normal", "tts_cancel_after_first_packet", ADDITIONAL_TTS_KIND,
                          "stt_v2", RECOVERY_TTS_KIND]
        if (len(prior) != 5 or [call.get("kind") for call in prior] != expected_kinds
                or prior[0].get("state") != "reserved_unknown_usage"
                or prior[1].get("state") != "failed_unknown_usage" or prior[1].get("http_status") != 400
                or prior[2].get("state") != "failed_unknown_usage" or prior[2].get("http_status") != 200
                or prior[2].get("provider_error") != "unsupported_audio"
                or prior[3].get("state") != "failed_unknown_usage"
                or prior[3].get("provider_error") != "unavailable"
                or prior[4].get("state") != "failed_unknown_usage" or prior[4].get("http_status") != 200
                or prior[4].get("provider_error") != "unsupported_audio"
                or prior[4].get("audio_diagnostic", {}).get("validation_reason") != "non_audio_part"):
            raise SmokeBlocked("recovery_stt_prior_attempt_evidence_mismatch")
    elif (len(prior) != 3 or [call.get("kind") for call in prior] != [
            "tts_normal", "tts_cancel_after_first_packet", ADDITIONAL_TTS_KIND]
            or prior[0].get("state") != "reserved_unknown_usage"
            or prior[1].get("state") != "failed_unknown_usage"
            or prior[1].get("http_status") != 400
            or prior[2].get("state") != "failed_unknown_usage"
            or prior[2].get("http_status") != 200
            or prior[2].get("provider_error") != "unsupported_audio"):
        raise SmokeBlocked("expected_three_prior_tts_attempts")
    # The project-owned manifest verifies the fixture's provenance, metadata and PCM/WAV integrity.
    manifest = _verify_offline_fixture_dir(fixture_dir)
    clip = manifest["clips"]["greeting"]
    if (manifest.get("language") != STT_FIXTURE_LANGUAGE or manifest.get("synthetic") is not True
            or manifest.get("offline_only") is not True or manifest.get("human_listening_verified") is not False
            or manifest.get("sample_rate") != 24000 or manifest.get("channels") != 1
            or manifest.get("sample_width_bytes") != 2 or manifest.get("encoding") != "pcm_s16le"):
        raise SmokeBlocked("offline_fixture_metadata_mismatch")
    pcm = (fixture_dir / clip["pcm_file"]).read_bytes()
    digest = hashlib.sha256(pcm).hexdigest()
    sample_count = len(pcm) // 2
    duration = sample_count / manifest["sample_rate"]
    if digest != clip.get("pcm_sha256") or duration <= 0 or duration > 30:
        raise SmokeBlocked("offline_fixture_integrity_failed")
    prior_reserved = sum((Decimal(call["reserved_usd"]) for call in prior), Decimal("0"))
    projected = prior_reserved + STT_RESERVE_USD
    if projected > USD_LIMIT:
        raise SmokeBlocked("approved_aggregate_reserve_exceeded")
    reporter = DurableReporter(report_path, {
        "project": "selected_project", "source": "offline_flite_fixture",
        "fixture_id": "greeting", "fixture_pcm_sha256": digest,
        "fixture_caption_sha256": clip["caption_sha256"],
        "input_language": STT_FIXTURE_LANGUAGE, "stt_language": STT_FIXTURE_LANGUAGE,
        "stt_model": STT_MODEL, "stt_location": STT_LOCATION,
        "sample_rate_hz": manifest["sample_rate"], "channels": 1,
        "sample_count": sample_count, "duration_seconds": round(duration, 3),
        "synthetic": True, "offline_source": True, "microphone_used": False,
        "billing_status": billing["billing_status"],
        "billing_read_http_status": billing["billing_http_status"],
        "billing_read_error_reason": billing["billing_error_reason"],
        "prior_reserved_usd": format(prior_reserved, "f"),
        "stt_reserved_usd": format(STT_RESERVE_USD, "f"),
        "projected_pre_tax_total_usd": format(projected, "f"),
        "taxes_and_fees_status": "unknown",
        "chinese_quality_claim": False,
    })
    reporter.emit("preflight_verified", state="ready")
    if adapter_factory is None:
        _tts, stt, resources = _make_live_adapters(
            billing, project_id=project_id, adc_dir=adc_dir, tts_mode="official_minimal",
            stt_language_code=STT_FIXTURE_LANGUAGE,
        )
    else:
        stt, resources = adapter_factory(STT_FIXTURE_LANGUAGE)
    ledger = SharedLedger(ledger_path)
    reservation = ledger.reserve("stt_v2", STT_RESERVE_USD)
    reporter.emit("stt_reserved", call="stt_v2", state="reserved_unknown_usage",
                  reserved_usd=format(STT_RESERVE_USD, "f"))
    ledger.set_phase(reservation, "stt_dispatch_started")
    reporter.emit("stt_dispatch_started", call="stt_v2", state="reserved_unknown_usage")
    from mira.application.ports.media import AudioPacket

    async def packets():
        cursor = 0
        for offset in range(0, len(pcm), 12000):
            chunk = pcm[offset:offset + 12000]
            yield AudioPacket("offline-flite-greeting", cursor, manifest["sample_rate"], chunk)
            cursor += len(chunk) // 2

    try:
        try:
            revisions = [revision async for revision in stt.transcribe(packets())]
        except asyncio.CancelledError:
            ledger.set_phase(reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call="stt_v2", state="unknown")
            raise
        except Exception as error:
            code = _provider_error_code(error) or "unknown"
            detail = _safe_provider_details(error)
            ledger.finish(reservation, "failed_unknown_usage", status_class=_safe_status(error),
                          provider_error=code, sample_count=sample_count, duration_seconds=duration,
                          terminal_phase="terminal_failure", provider_status=detail.get("provider_status"),
                          provider_reason=detail.get("provider_reason"), field_names=detail.get("field_names"),
                          diagnostic=detail.get("diagnostic"))
            reporter.emit("stt_terminal_result", call="stt_v2", state="failed_unknown_usage",
                          provider_error=code, first_packet_samples=sample_count,
                          duration_seconds=duration)
            return reporter.record
        final_text = next((revision.text for revision in reversed(revisions) if revision.is_final), None)
        ledger.finish(reservation, "completed", status_class="2xx", sample_count=sample_count,
                      duration_seconds=duration, terminal_phase="stt_completed")
        partial_count = sum(1 for revision in revisions if not revision.is_final)
        reporter.emit("stt_terminal_result", call="stt_v2", state="completed",
                      first_packet_samples=sample_count, duration_seconds=duration,
                      fixed_text_match=final_text == clip["caption"])
        reporter.record["final_revision_received"] = final_text is not None
        reporter.record["partial_revision_count"] = partial_count
        reporter.record["fixture_caption_match"] = final_text == clip["caption"]
        reporter.record["finalized_at_epoch"] = time.time()
        reporter.record["state"] = "completed"
        reporter._flush()
        reporter.emit("bundle_finalized", state="completed")
        return reporter.record
    finally:
        await _close_resources(resources)
        reporter.emit("resources_closed", state=reporter.record.get("state", "unknown"))


async def run_recovery_tts_stt(readiness_path: Path, enable_receipt_path: Path,
                               ledger_path: Path, report_path: Path, *, project_id: str,
                               adc_dir: Path,
                               adapter_factory: Callable[..., tuple[Any, Any, Any]] | None = None,
                               fixture_dir: Path = OFFLINE_FLITE_FIXTURE_DIR,
                               followup_after_stt: bool = False) -> dict[str, Any]:
    """Use one approved minimal TTS attempt and one STT stream, once each."""
    import re
    if not isinstance(project_id, str) or not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise SmokeBlocked("invalid_project_id")
    billing = check_resume_readiness(readiness_path, enable_receipt_path, project_id=project_id)
    prior = _ledger_calls(ledger_path)
    base_kinds = ["tts_normal", "tts_cancel_after_first_packet", ADDITIONAL_TTS_KIND, "stt_v2"]
    base_amounts = [TTS_RESERVE_USD, TTS_RESERVE_USD, TTS_FULL_RESERVE_USD, STT_RESERVE_USD]
    followup_kinds = [*base_kinds, RECOVERY_TTS_KIND, "stt_v2"]
    followup_amounts = [*base_amounts, TTS_FULL_RESERVE_USD, STT_RESERVE_USD]
    expected_kinds = followup_kinds if followup_after_stt else base_kinds
    expected_amounts = followup_amounts if followup_after_stt else base_amounts
    call_kind = TTS_TEXT_DIAGNOSTIC_KIND if followup_after_stt else RECOVERY_TTS_KIND
    if len(prior) != len(expected_kinds) or [item.get("kind") for item in prior] != expected_kinds:
        raise SmokeBlocked("unexpected_prior_attempt_sequence")
    expected_facts = [
        ("reserved_unknown_usage", None, None),
        ("failed_unknown_usage", 400, "invalid_input"),
        ("failed_unknown_usage", 200, "unsupported_audio"),
        ("failed_unknown_usage", None, "unavailable"),
    ]
    if followup_after_stt:
        expected_facts.extend([
            ("failed_unknown_usage", 200, "unsupported_audio"),
            ("completed", None, None),
        ])
        if (prior[4].get("audio_diagnostic", {}).get("validation_reason") != "non_audio_part"
                or prior[5].get("status_class") != "2xx"):
            raise SmokeBlocked("followup_tts_evidence_mismatch")
    for item, amount, facts in zip(prior, expected_amounts, expected_facts, strict=True):
        state, status, error = facts
        if (Decimal(item.get("reserved_usd", "0")) != amount
                or item.get("attempt_count") != 1 or item.get("state") != state
                or (status is not None and item.get("http_status") != status)
                or (error is not None and item.get("provider_error") != error)):
            raise SmokeBlocked("prior_attempt_evidence_mismatch")
    prior_reserved = sum((Decimal(item["reserved_usd"]) for item in prior), Decimal("0"))
    projected = prior_reserved + TTS_FULL_RESERVE_USD + (Decimal("0") if followup_after_stt else STT_RESERVE_USD)
    if projected > USD_LIMIT:
        raise SmokeBlocked("approved_aggregate_reserve_exceeded")
    reporter = DurableReporter(report_path, {
        "project": "selected_project", "tts_model": TTS_MODEL, "tts_location": TTS_LOCATION,
        "voice": TTS_VOICE, "stt_model": STT_MODEL, "stt_location": STT_LOCATION,
        "stt_language": STT_LANGUAGE, "prior_reserved_usd": format(prior_reserved, "f"),
        "tts_reserve_usd": format(TTS_FULL_RESERVE_USD, "f"),
        "stt_reserve_usd": format(Decimal("0") if followup_after_stt else STT_RESERVE_USD, "f"),
        "projected_pre_tax_reserve_usd": format(projected, "f"),
        "taxes_and_fees_status": "unknown", "request_mode": "official_minimal_streaming_tts",
        "response_text_diagnostics_enabled": followup_after_stt,
        "tts_only": followup_after_stt,
        "automatic_retry": False, "microphone_used": False, "raw_transcript_retained": False,
        "full_phrase_accuracy_claim": False,
    })
    ledger = SharedLedger(ledger_path)
    statuses: list[int] = []
    tts_reservation: Reservation | None = None
    stt_reservation: Reservation | None = None
    resources = None
    tts_stream = None

    def status_received(status: int) -> None:
        statuses.append(status)
        if tts_reservation is not None:
            ledger.set_phase(tts_reservation, "http_status_received", http_status=status)
        reporter.emit("tts_http_status_received", call=call_kind,
                      state="reserved_unknown_usage", http_status=status)

    try:
        reporter.emit("preflight_verified", state="ready")
        if adapter_factory is None:
            tts, stt, resources = _make_live_adapters(
                billing, project_id=project_id, adc_dir=adc_dir,
                on_http_status=status_received, tts_mode="official_minimal",
                stt_language_code=STT_LANGUAGE,
                capture_tts_text_diagnostics=followup_after_stt,
            )
        else:
            tts, stt, resources = adapter_factory(status_received, STT_LANGUAGE)

        # Reservation is durable before the billable request begins.
        tts_reservation = ledger.reserve(call_kind, TTS_FULL_RESERVE_USD)
        reporter.emit("tts_reserved", call=call_kind, state="reserved_unknown_usage",
                      reserved_usd=format(TTS_FULL_RESERVE_USD, "f"))
        ledger.set_phase(tts_reservation, "dispatch_started")
        reporter.emit("tts_dispatch_started", call=call_kind, state="reserved_unknown_usage")
        packets = []
        tts_error: Exception | None = None
        stream_id = "google-smoke-diagnostic-followup" if followup_after_stt else "google-smoke-recovery"
        tts_stream = tts.synthesize(SYNTHETIC_TEXT, stream_id)
        try:
            async for packet in tts_stream:
                if (not isinstance(packet, __import__("mira.application.ports.media", fromlist=["AudioPacket"]).AudioPacket)
                        or packet.stream_id != stream_id
                        or packet.sample_rate_hz != STT_SAMPLE_RATE_HZ
                        or not isinstance(packet.pcm, bytes) or not packet.pcm or len(packet.pcm) % 2):
                    raise SmokeBlocked("invalid_tts_audio_packet")
                packets.append(packet)
        except asyncio.CancelledError:
            ledger.set_phase(tts_reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call=call_kind, state="unknown")
            raise
        except Exception as error:
            tts_error = error

        status = statuses[-1] if statuses else None
        sample_count = sum(len(packet.pcm) // 2 for packet in packets)
        tts_ok = tts_error is None and status == 200 and bool(packets) and sample_count <= 30 * STT_SAMPLE_RATE_HZ
        audio_24k = b"".join(packet.pcm for packet in packets) if tts_ok else b""
        if tts_ok:
            audio_sha256 = hashlib.sha256(audio_24k).hexdigest()
            tts_duration = sample_count / STT_SAMPLE_RATE_HZ
            ledger.finish(tts_reservation, "completed", status_class="2xx", http_status=200,
                          sample_count=sample_count, duration_seconds=tts_duration,
                          terminal_phase="tts_completed")
            reporter.emit("tts_completed", call=call_kind, state="completed",
                          http_status=200, first_packet_samples=sample_count,
                          duration_seconds=tts_duration, reserved_usd=format(TTS_FULL_RESERVE_USD, "f"))
            reporter.record["tts_audio_sha256"] = audio_sha256
            reporter.record["tts_sample_rate_hz"] = STT_SAMPLE_RATE_HZ
            reporter.record["tts_sample_count"] = sample_count
            reporter.record["tts_duration_seconds"] = round(tts_duration, 3)
            if followup_after_stt:
                reporter.record["finalized_at_epoch"] = time.time()
                reporter.record["state"] = "completed"
                reporter._flush()
                reporter.emit("bundle_finalized", state="completed")
                return reporter.record
            input_language, stt_source = STT_LANGUAGE, "tts_pcm"
            pcm_16k, stt_samples = _resample_mono_s16le(audio_24k, STT_SAMPLE_RATE_HZ, 16000)
        else:
            detail = _safe_provider_details(tts_error)
            audio_detail = _safe_audio_details(tts_error, project_id=project_id)
            code = _provider_error_code(tts_error) or ("unknown" if status == 200 else "unavailable")
            http_status = detail.get("http_status", status)
            ledger.finish(
                tts_reservation, "failed_unknown_usage", status_class=_status_class(http_status, tts_error),
                http_status=http_status, provider_error=code, terminal_phase="terminal_failure",
                provider_status=detail.get("provider_status"), provider_reason=detail.get("provider_reason"),
                field_names=detail.get("field_names"), diagnostic=detail.get("diagnostic"),
                body_bytes_read=detail.get("body_bytes_read"), body_truncated=detail.get("body_truncated"),
                body_capture_status=detail.get("body_capture_status"), audio_diagnostic=audio_detail or None,
            )
            reporter.emit(
                "tts_terminal_failure", call=call_kind, state="failed_unknown_usage",
                http_status=http_status, provider_error=code, provider_status=detail.get("provider_status"),
                provider_reason=detail.get("provider_reason"), field_names=detail.get("field_names"),
                diagnostic=detail.get("diagnostic"), body_bytes_read=detail.get("body_bytes_read"),
                body_truncated=detail.get("body_truncated"), body_capture_status=detail.get("body_capture_status"),
                audio_diagnostic=audio_detail or None,
            )
            if followup_after_stt:
                reporter.record["state"] = "failed_unknown_usage"
                reporter._flush()
                return reporter.record
            if http_status in {401, 403, 429} or code in {"unauthenticated", "permission_denied", "quota_exhausted"}:
                reporter.record["state"] = "failed_unknown_usage"
                reporter._flush()
                return reporter.record
            # TTS audio did not validate. A separate STT slot can still establish
            # streaming connectivity using the pre-owned offline synthetic fixture.
            if tts_stream is not None:
                await tts_stream.aclose()
                tts_stream = None
            await _close_resources(resources)
            resources = None
            if adapter_factory is None:
                _unused_tts, stt, resources = _make_live_adapters(
                    billing, project_id=project_id, adc_dir=adc_dir,
                    on_http_status=status_received, tts_mode="official_minimal",
                    stt_language_code=STT_FIXTURE_LANGUAGE,
                )
            else:
                _unused_tts, stt, resources = adapter_factory(status_received, STT_FIXTURE_LANGUAGE)
            manifest = _verify_offline_fixture_dir(fixture_dir)
            clip = manifest["clips"]["greeting"]
            if (manifest.get("language") != STT_FIXTURE_LANGUAGE or manifest.get("synthetic") is not True
                    or manifest.get("offline_only") is not True or manifest.get("sample_rate") != 24000
                    or manifest.get("channels") != 1 or manifest.get("sample_width_bytes") != 2
                    or manifest.get("encoding") != "pcm_s16le"):
                raise SmokeBlocked("offline_fixture_metadata_mismatch")
            audio_24k = (fixture_dir / clip["pcm_file"]).read_bytes()
            audio_sha256 = hashlib.sha256(audio_24k).hexdigest()
            source_samples = len(audio_24k) // 2
            if (audio_sha256 != clip.get("pcm_sha256") or not audio_24k or len(audio_24k) % 2
                    or source_samples > 30 * STT_SAMPLE_RATE_HZ):
                raise SmokeBlocked("offline_fixture_integrity_failed")
            input_language, stt_source = STT_FIXTURE_LANGUAGE, "offline_flite_fixture"
            pcm_16k, stt_samples = _resample_mono_s16le(audio_24k, STT_SAMPLE_RATE_HZ, 16000)
            reporter.record.update({
                "stt_fixture_id": "greeting", "stt_fixture_pcm_sha256": audio_sha256,
                "stt_fixture_caption_sha256": clip["caption_sha256"],
                "stt_source_sample_rate_hz": STT_SAMPLE_RATE_HZ,
                "stt_source_sample_count": source_samples,
                "stt_source_duration_seconds": round(source_samples / STT_SAMPLE_RATE_HZ, 3),
            })

        if not pcm_16k or stt_samples > 30 * 16000 or len(pcm_16k) % 2:
            raise SmokeBlocked("stt_pcm_bounds_invalid")
        stt_duration = stt_samples / 16000
        reporter.record.update({
            "stt_source": stt_source, "stt_input_language": input_language,
            "stt_transmitted_sample_rate_hz": 16000,
            "stt_transmitted_sample_count": stt_samples,
            "stt_transmitted_duration_seconds": round(stt_duration, 3),
            "stt_transmitted_pcm_sha256": hashlib.sha256(pcm_16k).hexdigest(),
        })
        stt_reservation = ledger.reserve("stt_v2", STT_RESERVE_USD)
        reporter.emit("stt_reserved", call="stt_v2", state="reserved_unknown_usage",
                      reserved_usd=format(STT_RESERVE_USD, "f"))
        ledger.set_phase(stt_reservation, "stt_dispatch_started")
        reporter.emit("stt_dispatch_started", call="stt_v2", state="reserved_unknown_usage")
        from mira.application.ports.media import AudioPacket
        async def audio_packets():
            cursor = 0
            for offset in range(0, len(pcm_16k), 12000):
                chunk = pcm_16k[offset:offset + 12000]
                yield AudioPacket("google-smoke-recovery-stt", cursor, 16000, chunk)
                cursor += len(chunk) // 2
        try:
            revisions = [revision async for revision in stt.transcribe(audio_packets())]
        except asyncio.CancelledError:
            ledger.set_phase(stt_reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call="stt_v2", state="unknown")
            raise
        except Exception as error:
            detail = _safe_provider_details(error)
            code = _provider_error_code(error) or "unknown"
            ledger.finish(stt_reservation, "failed_unknown_usage", status_class=_safe_status(error),
                          provider_error=code, sample_count=stt_samples, duration_seconds=stt_duration,
                          terminal_phase="terminal_failure", provider_status=detail.get("provider_status"),
                          provider_reason=detail.get("provider_reason"), field_names=detail.get("field_names"),
                          diagnostic=detail.get("diagnostic"))
            reporter.emit("stt_terminal_result", call="stt_v2", state="failed_unknown_usage",
                          provider_error=code, first_packet_samples=stt_samples,
                          duration_seconds=stt_duration)
            reporter.record["state"] = "failed_unknown_usage"
            reporter._flush()
            return reporter.record
        final_text = next((revision.text for revision in reversed(revisions) if revision.is_final), None)
        expected_text = SYNTHETIC_TEXT if input_language == STT_LANGUAGE else clip["caption"] if stt_source == "offline_flite_fixture" else None
        ledger.finish(stt_reservation, "completed", status_class="2xx", sample_count=stt_samples,
                      duration_seconds=stt_duration, terminal_phase="stt_completed")
        partial_count = sum(1 for revision in revisions if not revision.is_final)
        reporter.emit("stt_terminal_result", call="stt_v2", state="completed",
                      first_packet_samples=stt_samples, duration_seconds=stt_duration,
                      fixed_text_match=final_text == expected_text if expected_text is not None else False)
        reporter.record["final_revision_received"] = final_text is not None
        reporter.record["partial_revision_count"] = partial_count
        reporter.record["fixed_text_match"] = final_text == expected_text if expected_text is not None else False
        reporter.record["partial_recognition_only"] = final_text is None
        reporter.record["finalized_at_epoch"] = time.time()
        reporter.record["state"] = "completed"
        reporter._flush()
        reporter.emit("bundle_finalized", state="completed")
        return reporter.record
    finally:
        if tts_stream is not None:
            try:
                await tts_stream.aclose()
            except Exception:
                pass
        await _close_resources(resources)
        reporter.emit("resources_closed", state=reporter.record.get("state", "unknown"))


async def run_final_approved_tts_only(readiness_path: Path, enable_receipt_path: Path,
                                      ledger_path: Path, report_path: Path, *, project_id: str,
                                      adc_dir: Path,
                                      adapter_factory: Callable[[Callable[[int], None], int],
                                                                tuple[Any, Any, Any]] | None = None
                                      ) -> dict[str, Any]:
    """Use the single newly approved TTS slot with a 60-second diagnostic deadline."""
    import re
    if not isinstance(project_id, str) or not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise SmokeBlocked("invalid_project_id")
    billing = check_resume_readiness(readiness_path, enable_receipt_path, project_id=project_id)
    prior = _ledger_calls(ledger_path)
    expected_kinds = [
        "tts_normal", "tts_cancel_after_first_packet", ADDITIONAL_TTS_KIND, "stt_v2",
        RECOVERY_TTS_KIND, "stt_v2", TTS_TEXT_DIAGNOSTIC_KIND,
    ]
    expected_amounts = [
        TTS_RESERVE_USD, TTS_RESERVE_USD, TTS_FULL_RESERVE_USD, STT_RESERVE_USD,
        TTS_FULL_RESERVE_USD, STT_RESERVE_USD, TTS_FULL_RESERVE_USD,
    ]
    expected_facts = [
        ("reserved_unknown_usage", None, None),
        ("failed_unknown_usage", 400, "invalid_input"),
        ("failed_unknown_usage", 200, "unsupported_audio"),
        ("failed_unknown_usage", None, "unavailable"),
        ("failed_unknown_usage", 200, "unsupported_audio"),
        ("completed", None, None),
        ("failed_unknown_usage", 200, "timeout"),
    ]
    if len(prior) != 7 or [item.get("kind") for item in prior] != expected_kinds:
        raise SmokeBlocked("unexpected_final_attempt_sequence")
    if (prior[4].get("audio_diagnostic", {}).get("validation_reason") != "non_audio_part"
            or prior[5].get("status_class") != "2xx"
            or prior[6].get("status_class") != "2xx"):
        raise SmokeBlocked("final_attempt_evidence_mismatch")
    for item, amount, facts in zip(prior, expected_amounts, expected_facts, strict=True):
        state, status, error = facts
        if (Decimal(item.get("reserved_usd", "0")) != amount
                or item.get("attempt_count") != 1 or item.get("state") != state
                or (status is not None and item.get("http_status") != status)
                or (error is not None and item.get("provider_error") != error)):
            raise SmokeBlocked("prior_attempt_evidence_mismatch")

    prior_reserved = sum((Decimal(item["reserved_usd"]) for item in prior), Decimal("0"))
    projected = prior_reserved + TTS_FULL_RESERVE_USD
    if projected > APPROVED_FINAL_TTS_LIMIT_USD:
        raise SmokeBlocked("approved_aggregate_reserve_exceeded")
    audio_path = report_path.with_suffix(".pcm")
    if audio_path.exists():
        raise SmokeBlocked("pcm_artifact_already_exists")
    reporter = DurableReporter(report_path, {
        "project": "selected_project", "tts_model": TTS_MODEL, "tts_location": TTS_LOCATION,
        "voice": TTS_VOICE, "request_mode": "official_minimal_streaming_tts",
        "prior_reserved_usd": format(prior_reserved, "f"),
        "tts_reserve_usd": format(TTS_FULL_RESERVE_USD, "f"),
        "projected_pre_tax_reserve_usd": format(projected, "f"),
        "approved_aggregate_limit_usd": format(APPROVED_FINAL_TTS_LIMIT_USD, "f"),
        "taxes_and_fees_status": "unknown", "tts_timeout_seconds": 60,
        "response_text_diagnostics_enabled": True, "automatic_retry": False,
        "microphone_used": False, "stt_dispatched": False,
        "raw_prompt_retained": False, "raw_response_text_retained": False,
    })
    ledger = SharedLedger(ledger_path, budget_limit=APPROVED_FINAL_TTS_LIMIT_USD)
    statuses: list[int] = []
    reservation: Reservation | None = None
    stream = None
    resources = None
    latency_trace: TtsLatencyTrace | None = None

    def status_received(status: int) -> None:
        first_status = not statuses
        statuses.append(status)
        if first_status and latency_trace is not None:
            latency_trace.http_headers_received(status)
        if reservation is not None:
            ledger.set_phase(reservation, "http_status_received", http_status=status)
        reporter.emit("tts_http_status_received", call=TTS_FINAL_APPROVED_KIND,
                      state="reserved_unknown_usage", http_status=status)

    try:
        reporter.emit("preflight_verified", state="ready")
        if adapter_factory is None:
            tts, _stt, resources = _make_live_adapters(
                billing, project_id=project_id, adc_dir=adc_dir,
                on_http_status=status_received, tts_mode="official_minimal",
                stt_language_code=STT_LANGUAGE, capture_tts_text_diagnostics=True,
                tts_timeout_seconds=60,
            )
        else:
            tts, _stt, resources = adapter_factory(status_received, 60)

        # Persist the maximum full-output reservation before entering the model call.
        reservation = ledger.reserve(TTS_FINAL_APPROVED_KIND, TTS_FULL_RESERVE_USD)
        reporter.emit("tts_reserved", call=TTS_FINAL_APPROVED_KIND,
                      state="reserved_unknown_usage", reserved_usd=format(TTS_FULL_RESERVE_USD, "f"))
        ledger.set_phase(reservation, "dispatch_started")
        reporter.emit("tts_dispatch_started", call=TTS_FINAL_APPROVED_KIND,
                      state="reserved_unknown_usage")

        from mira.application.ports.media import AudioPacket
        stream_id = "google-smoke-final-approved"
        latency_trace = TtsLatencyTrace()
        latency_trace.dispatch_started()
        stream = tts.synthesize(SYNTHETIC_TEXT, stream_id)
        packets = []
        terminal_error: Exception | None = None
        try:
            async for packet in stream:
                if (not isinstance(packet, AudioPacket) or packet.stream_id != stream_id
                        or packet.sample_rate_hz != STT_SAMPLE_RATE_HZ
                        or not isinstance(packet.pcm, bytes) or not packet.pcm
                        or len(packet.pcm) % 2):
                    latency_trace.invalid_pcm_packet_received()
                    raise SmokeBlocked("invalid_tts_audio_packet")
                if not latency_trace.pcm_packet_yielded(packet.pcm, packet.sample_rate_hz):
                    raise SmokeBlocked("invalid_tts_audio_packet")
                packets.append(packet)
            latency_trace.stream_terminal("completed")
        except asyncio.CancelledError:
            latency_trace.stream_terminal("cancelled")
            ledger.set_phase(reservation, "interrupted_unknown")
            reporter.emit("bundle_interrupted_unknown", call=TTS_FINAL_APPROVED_KIND, state="unknown")
            raise
        except Exception as error:
            latency_trace.stream_terminal("error")
            terminal_error = error

        status = statuses[-1] if statuses else None
        sample_count = sum(len(packet.pcm) // 2 for packet in packets)
        tts_ok = (terminal_error is None and status == 200 and bool(packets)
                  and sample_count <= 30 * STT_SAMPLE_RATE_HZ)
        if tts_ok:
            pcm = b"".join(packet.pcm for packet in packets)
            pcm_digest = hashlib.sha256(pcm).hexdigest()
            try:
                _write_pcm_private(audio_path, pcm)
            except Exception:
                latency_trace.file_save_completed(False)
                _persist_tts_latency(reporter, latency_trace)
                raise
            latency_trace.file_save_completed(True)
            duration = sample_count / STT_SAMPLE_RATE_HZ
            ledger.finish(reservation, "completed", status_class="2xx", http_status=200,
                          sample_count=sample_count, duration_seconds=duration,
                          terminal_phase="tts_completed")
            reporter.emit("tts_completed", call=TTS_FINAL_APPROVED_KIND, state="completed",
                          http_status=200, total_samples=sample_count,
                          duration_seconds=duration, reserved_usd=format(TTS_FULL_RESERVE_USD, "f"))
            reporter.record.update({
                "audio_artifact_name": audio_path.name, "audio_bytes": len(pcm),
                "audio_sha256": pcm_digest, "sample_rate_hz": STT_SAMPLE_RATE_HZ,
                "sample_count": sample_count, "duration_seconds": round(duration, 3),
                "audio_artifact_saved": True, "played": False,
            })
            reporter.record["state"] = "completed"
        else:
            detail = _safe_provider_details(terminal_error)
            audio_detail = _safe_audio_details(terminal_error, project_id=project_id)
            provider_error = _provider_error_code(terminal_error) or (
                "unknown" if status == 200 else "unavailable")
            http_status = detail.get("http_status", status)
            ledger.finish(
                reservation, "failed_unknown_usage", status_class=_status_class(http_status, terminal_error),
                http_status=http_status, provider_error=provider_error,
                terminal_phase="terminal_failure", provider_status=detail.get("provider_status"),
                provider_reason=detail.get("provider_reason"), field_names=detail.get("field_names"),
                diagnostic=detail.get("diagnostic"), body_bytes_read=detail.get("body_bytes_read"),
                body_truncated=detail.get("body_truncated"),
                body_capture_status=detail.get("body_capture_status"),
                audio_diagnostic=audio_detail or None,
            )
            reporter.emit(
                "tts_terminal_failure", call=TTS_FINAL_APPROVED_KIND,
                state="failed_unknown_usage", http_status=http_status,
                provider_error=provider_error, provider_status=detail.get("provider_status"),
                provider_reason=detail.get("provider_reason"), field_names=detail.get("field_names"),
                diagnostic=detail.get("diagnostic"), audio_diagnostic=audio_detail or None,
            )
            reporter.record["state"] = "failed_unknown_usage"

        reporter.record["finalized_at_epoch"] = time.time()
        _persist_tts_latency(reporter, latency_trace)
        reporter._flush()
        reporter.emit("bundle_finalized", state=reporter.record["state"])
        return reporter.record
    finally:
        if stream is not None:
            try:
                await stream.aclose()
            except Exception:
                pass
            if latency_trace is not None:
                latency_trace.stream_closed()
        _persist_tts_latency(reporter, latency_trace)
        await _close_resources(resources)
        if resources is not None:
            reporter.emit("resources_closed", state=reporter.record.get("state", "unknown"))


async def run_bundle(readiness_path: Path, ledger_path: Path, *, project_id: str, adc_dir: Path,
                     adapter_factory: Callable[[], tuple[Any, Any, Any]] | None = None) -> dict[str, Any]:
    """Run the authorized one-off bundle. No retries; ledger reservation precedes each call.

    adapter_factory is injectable only for offline tests. A real run constructs
    fresh clients using the explicitly configured ADC path, inside this function.
    """
    import re
    if not isinstance(project_id, str) or not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise SmokeBlocked("invalid_project_id")
    readiness = check_readiness_receipt(readiness_path, project_id=project_id)
    if adapter_factory is None:
        tts, stt, resources = _make_live_adapters(readiness, project_id=project_id, adc_dir=adc_dir)
    else:
        tts, stt, resources = adapter_factory()
    ledger = SharedLedger(ledger_path)
    evidence: dict[str, Any] = {
        "project": "selected_project", "tts_model": TTS_MODEL,
        "tts_location": TTS_LOCATION, "voice": TTS_VOICE,
        "stt_model": STT_MODEL, "stt_location": STT_LOCATION,
        "stt_language": STT_LANGUAGE, "sample_rate_hz": STT_SAMPLE_RATE_HZ,
        "attempts": [],
    }
    try:
        reserve = ledger.reserve(CALL_ORDER[0], TTS_RESERVE_USD)
        try:
            pcm_packets = [p async for p in tts.synthesize(SYNTHETIC_TEXT, "google-smoke-normal")]
        except Exception as error:
            ledger.finish(reserve, "failed_unknown_usage", status_class=_safe_status(error))
            raise SmokeBlocked("tts_normal_failed") from None
        sample_count = sum(len(p.pcm) // 2 for p in pcm_packets)
        if not pcm_packets or sample_count > 30 * STT_SAMPLE_RATE_HZ:
            ledger.finish(reserve, "failed_unknown_usage", status_class="2xx", sample_count=sample_count)
            raise SmokeBlocked("tts_output_out_of_bounds")
        ledger.finish(reserve, "completed", status_class="2xx", sample_count=sample_count,
                      duration_seconds=sample_count / STT_SAMPLE_RATE_HZ)
        evidence["attempts"].append({"kind": "tts_normal", "status": "2xx",
                                     "sample_count": sample_count,
                                     "duration_seconds": round(sample_count / STT_SAMPLE_RATE_HZ, 3)})

        cancel = ledger.reserve(CALL_ORDER[1], TTS_RESERVE_USD)
        stream = tts.synthesize(SYNTHETIC_TEXT, "google-smoke-cancel")
        try:
            await anext(stream)
            await stream.aclose()
        except Exception as error:
            ledger.finish(cancel, "failed_unknown_usage", status_class=_safe_status(error))
            raise SmokeBlocked("tts_cancel_call_failed") from None
        ledger.finish(cancel, "cancelled_after_first_packet", status_class="2xx")
        evidence["attempts"].append({"kind": "tts_cancel_after_first_packet", "status": "2xx",
                                     "cancelled_after_first_packet": True})

        # Local resampling only; never mislabel 24k TTS PCM as 16k STT audio.
        pcm_16k, sample_count_16k = _resample_mono_s16le(
            b"".join(p.pcm for p in pcm_packets), STT_SAMPLE_RATE_HZ, 16000
        )
        if not pcm_16k or sample_count_16k > 30 * 16000:
            raise SmokeBlocked("stt_input_out_of_bounds")
        from mira.application.ports.media import AudioPacket

        async def pcm_source():
            yield AudioPacket("google-smoke-stt", 0, 16000, pcm_16k)

        stt_reservation = ledger.reserve(CALL_ORDER[2], STT_RESERVE_USD)
        try:
            revisions = [r async for r in stt.transcribe(pcm_source())]
        except Exception as error:
            ledger.finish(stt_reservation, "failed_unknown_usage", status_class=_safe_status(error),
                          sample_count=sample_count_16k, duration_seconds=sample_count_16k / 16000)
            raise SmokeBlocked("stt_stream_failed") from None
        final_text = next((r.text for r in reversed(revisions) if r.is_final), None)
        ledger.finish(stt_reservation, "completed", status_class="2xx", sample_count=sample_count_16k,
                      duration_seconds=sample_count_16k / 16000)
        # Store transcript equality only; never persist the transcript itself.
        evidence["attempts"].append({"kind": "stt_v2", "status": "2xx",
                                     "sample_count": sample_count_16k,
                                     "duration_seconds": round(sample_count_16k / 16000, 3),
                                     "fixed_text_match": final_text == SYNTHETIC_TEXT,
                                     "final_revision_received": final_text is not None})
        evidence["reserved_pre_tax_usd"] = format(TOTAL_RESERVE_USD, "f")
        evidence["taxes_and_fees_included_in_bound"] = True
        return evidence
    finally:
        await _close_resources(resources)


def _safe_status(error: Exception) -> str:
    # Deliberately use only a coarse category. Never include exception text.
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "cancel" in name:
        return "cancelled"
    if name in {"connecterror", "networkerror", "transporterror"}:
        return "transport_error"
    return "transport_error"


def _resample_mono_s16le(pcm: bytes, source_rate: int, target_rate: int) -> tuple[bytes, int]:
    """Simple dependency-free linear resampler for short synthetic PCM only."""
    if (not isinstance(pcm, bytes) or not pcm or len(pcm) % 2
            or source_rate <= 0 or target_rate <= 0):
        raise SmokeBlocked("invalid_synthetic_pcm")
    if source_rate == target_rate:
        return pcm, len(pcm) // 2
    import array
    samples = array.array("h")
    samples.frombytes(pcm)
    if os.sys.byteorder != "little":
        samples.byteswap()
    target_count = (len(samples) * target_rate + source_rate - 1) // source_rate
    out = array.array("h")
    for target_index in range(target_count):
        position_num = target_index * source_rate
        left = min(position_num // target_rate, len(samples) - 1)
        right = min(left + 1, len(samples) - 1)
        fraction = (position_num % target_rate) / target_rate
        value = round(samples[left] * (1 - fraction) + samples[right] * fraction)
        out.append(max(-32768, min(32767, value)))
    if os.sys.byteorder != "little":
        out.byteswap()
    return out.tobytes(), target_count


async def _close_resources(resources: Any) -> None:
    if resources is None:
        return
    for resource in resources:
        close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
        if close is None and callable(resource):
            close = resource
        if close is None:
            continue
        result = close()
        if asyncio.iscoroutine(result):
            try:
                await result
            except Exception:
                pass


def _make_grpc_ca_credentials(ca_bundle: Path):
    """Build standard verifying gRPC TLS credentials from the approved CA file."""
    import grpc
    import ssl
    try:
        ca_bytes = Path(ca_bundle).read_bytes()
        if not ca_bytes or len(ca_bytes) > 8 * 1024 * 1024:
            raise ValueError("invalid_ca_bundle_size")
        # Validate PEM syntax locally before constructing the channel credential.
        # The resulting gRPC channel uses its normal chain and hostname checks.
        ssl.create_default_context(cadata=ca_bytes.decode("ascii"))
        return grpc.ssl_channel_credentials(root_certificates=ca_bytes)
    except Exception:
        raise SmokeBlocked("approved_ca_bundle_invalid") from None


def _make_live_adapters(readiness: dict[str, Any], *, project_id: str, adc_dir: Path,
                        on_http_status: Callable[[int], None] | None = None,
                        tts_mode: str = "capped", stt_language_code: str = STT_LANGUAGE,
                        capture_tts_text_diagnostics: bool = False,
                        tts_timeout_seconds: int = 30):
    """Create one TTS + STT client from the explicitly-approved ADC file only."""
    if type(tts_timeout_seconds) is not int or not 1 <= tts_timeout_seconds <= 120:
        raise SmokeBlocked("invalid_tts_timeout")
    auth_dir = adc_dir
    adc = auth_dir / "application_default_credentials.json"
    if not adc.is_file():
        raise SmokeBlocked("approved_adc_missing")
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise SmokeBlocked("unexpected_credential_override")
    import google.auth
    from google.auth.transport.requests import Request
    from google.cloud.speech_v2 import SpeechAsyncClient
    from google.cloud.speech_v2.services.speech.transports.grpc_asyncio import SpeechGrpcAsyncIOTransport
    from google.cloud.speech_v2.types import cloud_speech
    import grpc
    import httpx
    import ssl
    from urllib.parse import urlsplit
    from mira.adapters.speech.google_gemini_tts import (
        GeminiTtsOptions, GoogleGeminiTtsBackend, GoogleGeminiTtsRestTransport,
    )
    from mira.adapters.speech.google_stt_v2 import (
        GoogleSpeechV2Backend, GoogleSpeechV2GrpcTransport, SttOptions,
    )

    try:
        credentials, discovered_project = google.auth.load_credentials_from_file(
            str(adc), scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    except Exception:
        raise SmokeBlocked("approved_adc_unreadable") from None
    if discovered_project not in (None, project_id):
        raise SmokeBlocked("unexpected_adc_project")

    async def token_provider() -> str:
        if not credentials.valid:
            await asyncio.to_thread(credentials.refresh, Request())
        return credentials.token

    http_statuses: list[int] = []

    async def capture_status(response):
        # Status only; never retain headers, URL, request, or response content.
        status = int(response.status_code)
        http_statuses.append(status)
        if on_http_status is not None:
            on_http_status(status)

    # Select only the already-approved HTTPS proxy/CA inputs. In particular,
    # ignore unrelated proxy variables that can require optional proxy plugins.
    ca_bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
             or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy"))
    if not ca_bundle or not proxy:
        raise SmokeBlocked("approved_proxy_or_ca_missing")
    if urlsplit(proxy).scheme not in {"http", "https"}:
        raise SmokeBlocked("approved_proxy_scheme_unsupported")
    # Constructing a secure channel credential with explicit roots preserves
    # gRPC's CA-chain and hostname verification. No system roots or TLS checks
    # are disabled, and this process does not edit environment trust settings.
    stt_ssl_credentials = _make_grpc_ca_credentials(Path(ca_bundle))
    # Same approved CA context as the existing HTTPS route; the proxy itself is
    # selected opaquely from the already-present HTTPS proxy setting.
    tls_context = ssl.create_default_context(cafile=ca_bundle)
    transport = httpx.AsyncHTTPTransport(proxy=proxy, verify=tls_context,
                                         trust_env=False, retries=0)
    client = httpx.AsyncClient(transport=transport, trust_env=False,
                               timeout=35.0, follow_redirects=False,
                               event_hooks={"response": [capture_status]})

    tts = GoogleGeminiTtsBackend(
        GeminiTtsOptions(project_id=project_id, voice=TTS_VOICE, location=TTS_LOCATION,
                         model=TTS_MODEL, timeout_seconds=tts_timeout_seconds,
                         max_audio_samples=STT_SAMPLE_RATE_HZ * 30,
                         capture_provider_text_diagnostics=capture_tts_text_diagnostics),
        TtsRequestPolicyTransport(GoogleGeminiTtsRestTransport(client, token_provider=token_provider,
                                     quota_project_id=project_id,
                                     max_event_bytes=2 * 1024 * 1024,
                                     max_response_bytes=16 * 1024 * 1024), tts_mode),
    )
    stt_transport = SpeechGrpcAsyncIOTransport(
        credentials=credentials, host="us-speech.googleapis.com",
        quota_project_id=project_id, ssl_channel_credentials=stt_ssl_credentials,
    )
    stt_client = SpeechAsyncClient(transport=stt_transport)
    stt = GoogleSpeechV2Backend(
        SttOptions(project_id=project_id, location=STT_LOCATION, model=STT_MODEL,
                   language_code=stt_language_code, timeout_seconds=35,
                   max_stream_seconds=float(STT_MAX_SECONDS), max_chunk_bytes=12000),
        GoogleSpeechV2GrpcTransport(stt_client, request_factory=cloud_speech.StreamingRecognizeRequest),
    )

    async def close_clients():
        await client.aclose()
        await stt_client.transport.close()

    # Expose one async closure, but never credential values or client reprs.
    return tts, stt, (close_clients, http_statuses)


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--project-id", required=True, help="Selected project ID (private invocation only)")
    parser.add_argument("--adc-dir", type=Path, required=True, help="Approved ADC directory")
    parser.add_argument("--enable-receipt", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--remaining-cancel-stt", action="store_true",
                        help="Use only the remaining cancel-TTS and one-STT slots after an unknown normal attempt")
    parser.add_argument("--additional-official-tts", action="store_true",
                        help="Use one separately approved extra TTS slot with Google's documented minimal request")
    parser.add_argument("--offline-english-fixture-stt", action="store_true",
                        help="Use the existing local synthetic en-US Flite fixture for the original STT slot")
    parser.add_argument("--recovery-stt-only", action="store_true",
                        help="Use the still-unspent approved STT slot after a recorded recovery TTS attempt")
    parser.add_argument("--followup-diagnostic-tts-only", action="store_true",
                        help="Use one approved bounded TTS diagnostic attempt without a new STT stream")
    parser.add_argument("--approved-final-2usd-tts-only", action="store_true",
                        help="Use the single approved final TTS slot with the explicit USD 2 aggregate cap and 60-second deadline")
    parser.add_argument("--recovery-tts-stt", action="store_true",
                        help="Use one newly approved minimal TTS attempt and one STT stream after the recorded attempts")
    parser.add_argument("--live", action="store_true", help="Required to invoke the approved one-off live test")
    args = parser.parse_args()
    if not args.live:
        print("offline_only: live calls require --live and a fresh verified readiness receipt")
        return 2
    try:
        if args.approved_final_2usd_tts_only:
            if args.enable_receipt is None or args.report is None:
                raise SmokeBlocked("approved_final_tts_requires_enable_receipt_and_new_report")
            result = asyncio.run(run_final_approved_tts_only(
                args.readiness, args.enable_receipt, args.ledger, args.report,
                project_id=args.project_id, adc_dir=args.adc_dir,
            ))
        elif args.followup_diagnostic_tts_only:
            if args.enable_receipt is None or args.report is None:
                raise SmokeBlocked("followup_tts_requires_enable_receipt_and_new_report")
            result = asyncio.run(run_recovery_tts_stt(
                args.readiness, args.enable_receipt, args.ledger, args.report,
                project_id=args.project_id, adc_dir=args.adc_dir, followup_after_stt=True,
            ))
        elif args.recovery_stt_only:
            if args.enable_receipt is None or args.report is None:
                raise SmokeBlocked("recovery_stt_requires_enable_receipt_and_new_report")
            result = asyncio.run(run_offline_english_fixture_stt(
                args.readiness, args.enable_receipt, args.ledger, args.report,
                project_id=args.project_id, adc_dir=args.adc_dir, recovery_after_tts=True,
            ))
        elif args.offline_english_fixture_stt:
            if args.enable_receipt is None or args.report is None:
                raise SmokeBlocked("fixture_stt_requires_enable_receipt_and_new_report")
            result = asyncio.run(run_offline_english_fixture_stt(
                args.readiness, args.enable_receipt, args.ledger, args.report,
                project_id=args.project_id, adc_dir=args.adc_dir,
            ))
        elif args.recovery_tts_stt:
            if args.enable_receipt is None or args.report is None:
                raise SmokeBlocked("recovery_mode_requires_enable_receipt_and_new_report")
            result = asyncio.run(run_recovery_tts_stt(
                args.readiness, args.enable_receipt, args.ledger, args.report,
                project_id=args.project_id, adc_dir=args.adc_dir,
            ))
        elif args.additional_official_tts:
            if args.enable_receipt is None or args.report is None:
                raise SmokeBlocked("additional_tts_requires_enable_receipt_and_new_report")
            result = asyncio.run(run_additional_official_tts(
                args.readiness, args.enable_receipt, args.ledger, args.report,
                project_id=args.project_id, adc_dir=args.adc_dir,
            ))
        elif args.remaining_cancel_stt:
            if args.enable_receipt is None or args.report is None:
                raise SmokeBlocked("remaining_mode_requires_enable_receipt_and_new_report")
            result = asyncio.run(run_remaining_cancel_stt(
                args.readiness, args.enable_receipt, args.ledger, args.report,
                project_id=args.project_id, adc_dir=args.adc_dir,
            ))
        else:
            result = asyncio.run(run_bundle(args.readiness, args.ledger,
                                            project_id=args.project_id, adc_dir=args.adc_dir))
    except SmokeBlocked as error:
        # Every raised value is a fixed low-sensitivity enum, never provider text.
        print(f"blocked: {error}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
