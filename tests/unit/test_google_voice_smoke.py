"""Offline lifecycle proof for the isolated Google smoke runner."""
import json
import time

import pytest

from mira.application.ports.media import AudioPacket, TranscriptRevision
from mira.adapters.speech.errors import SafeAudioDiagnostic, SpeechProviderError
from tools.google_voice_smoke import (
    CALL_ORDER,
    SYNTHETIC_TEXT,
    SmokeBlocked,
    STT_RESERVE_USD,
    TTS_RESERVE_USD,
    TTS_FULL_RESERVE_USD,
    ADDITIONAL_TTS_KIND,
    RECOVERY_TTS_KIND,
    TTS_TEXT_DIAGNOSTIC_KIND,
    OFFLINE_FLITE_FIXTURE_DIR,
    SharedLedger,
    make_readiness_receipt,
    run_bundle,
    run_remaining_cancel_stt,
    run_additional_official_tts,
    run_offline_english_fixture_stt,
    run_recovery_tts_stt,
    _make_grpc_ca_credentials,
)


class SyntheticTts:
    def __init__(self):
        self.calls = []
        self.closed = []

    async def synthesize(self, text, stream_id):
        self.calls.append((text, stream_id))
        try:
            yield AudioPacket(stream_id, 0, 24000, b"\x10\x00" * 2400)
            if stream_id == "google-smoke-cancel":
                await __import__("asyncio").Event().wait()
        finally:
            self.closed.append(stream_id)


class SyntheticStt:
    def __init__(self):
        self.input_packets = []
        self.closed = False

    async def transcribe(self, packets):
        async for packet in packets:
            self.input_packets.append(packet)
        yield TranscriptRevision("google-smoke-stt", 1, SYNTHETIC_TEXT, True)


class Resource:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


def synthetic_ca_pem():
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "offline-ca-fixture")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM)


def test_grpc_ca_bundle_validation_is_local_and_rejects_invalid_roots(tmp_path):
    import grpc

    valid = tmp_path / "test-ca.pem"
    valid.write_bytes(synthetic_ca_pem())
    credentials = _make_grpc_ca_credentials(valid)
    assert isinstance(credentials, grpc.ChannelCredentials)
    invalid = tmp_path / "invalid-ca.pem"
    invalid.write_text("not a CA certificate", encoding="ascii")
    with pytest.raises(SmokeBlocked, match="approved_ca_bundle_invalid"):
        _make_grpc_ca_credentials(invalid)


def resume_receipts(tmp_path):
    readiness = {
        "results": {
            "project": {"status": "ok", "id_matches": True, "lifecycle_state": "ACTIVE"},
            "permissions": {"granted": ["speech.recognizers.recognize", "aiplatform.endpoints.predict",
                                          "serviceusage.services.use"]},
            "billing": {"status": "unknown", "http_status": 403, "error_reasons": ["SERVICE_DISABLED"]},
        }
    }
    enabled = {
        "project_id": "offline-test",
        "results": {"aiplatform_state": {"service_state": "ENABLED"},
                    "speech_final_state": {"service_state": "ENABLED"}},
    }
    readiness_path, enabled_path = tmp_path / "readiness.json", tmp_path / "enabled.json"
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    enabled_path.write_text(json.dumps(enabled), encoding="utf-8")
    return readiness_path, enabled_path


@pytest.mark.asyncio
async def test_synthetic_bundle_finalizes_reservations_cancellation_and_resources(tmp_path):
    # This receipt is a test fixture only; it is never used for a live request.
    readiness = make_readiness_receipt(
        project_id="offline-test", project_state="ACTIVE",
        granted_permissions=["speech.recognizers.recognize", "aiplatform.endpoints.predict",
                             "serviceusage.services.use"],
        speech_api="ENABLED", aiplatform_api="ENABLED", billing_enabled=True,
        billing_currency="USD", bounded_tax_and_fees_usd="0",
        checked_at_epoch=time.time(),
    )
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    ledger_path = tmp_path / "ledger.json"
    tts, stt, resource = SyntheticTts(), SyntheticStt(), Resource()

    evidence = await run_bundle(
        readiness_path, ledger_path, project_id="offline-test", adc_dir=tmp_path,
        adapter_factory=lambda: (tts, stt, [resource]),
    )

    record = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert [call["kind"] for call in record["calls"]] == list(CALL_ORDER)
    assert [call["attempt_count"] for call in record["calls"]] == [1, 1, 1]
    assert [call["state"] for call in record["calls"]] == [
        "completed", "cancelled_after_first_packet", "completed"]
    assert record["reserved_total_usd"] == format(TTS_RESERVE_USD * 2 + STT_RESERVE_USD, "f")
    assert evidence["attempts"][1]["cancelled_after_first_packet"] is True
    assert evidence["attempts"][2]["fixed_text_match"] is True
    assert tts.calls == [(SYNTHETIC_TEXT, "google-smoke-normal"),
                         (SYNTHETIC_TEXT, "google-smoke-cancel")]
    assert tts.closed == ["google-smoke-normal", "google-smoke-cancel"]
    assert len(stt.input_packets) == 1
    assert stt.input_packets[0].sample_rate_hz == 16000
    assert len(stt.input_packets[0].pcm) == 3200
    assert resource.closed
    assert SYNTHETIC_TEXT not in ledger_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_remaining_scope_cancels_one_packet_then_stt_chunks_partial_audio(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    ledger = SharedLedger(ledger_path)
    ledger.reserve("tts_normal", TTS_RESERVE_USD)  # Prior real slot stays unknown/consumed.

    class Tts:
        def __init__(self, report_status):
            self.report_status, self.closed, self.calls = report_status, [], []

        def synthesize(self, text, stream_id):
            self.calls.append((text, stream_id))

            async def source():
                try:
                    self.report_status(200)
                    yield AudioPacket(stream_id, 0, 24000, b"\x10\x00" * 24000)
                    await __import__("asyncio").Event().wait()
                finally:
                    self.closed.append(stream_id)
            return source()

    class Stt:
        def __init__(self):
            self.packets = []

        async def transcribe(self, packets):
            async for packet in packets:
                self.packets.append(packet)
            yield TranscriptRevision("google-smoke-stt", 1, "partial", False)

    tts, stt, resource = None, Stt(), Resource()

    def factory(report_status):
        nonlocal tts
        tts = Tts(report_status)
        return tts, stt, [resource]

    result = await run_remaining_cancel_stt(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
    )
    calls = json.loads(ledger_path.read_text(encoding="utf-8"))["calls"]
    assert [c["kind"] for c in calls] == list(CALL_ORDER)
    assert [c["state"] for c in calls] == [
        "reserved_unknown_usage", "cancelled_after_first_packet", "completed"]
    assert calls[0]["reserved_usd"] == format(TTS_RESERVE_USD, "f")
    assert calls[1]["sample_count"] == 24000
    assert [text for text, _ in tts.calls] == [SYNTHETIC_TEXT]
    assert tts.closed == ["google-smoke-cancel"] and resource.closed
    assert len(stt.packets) == 3
    assert all(0 < len(packet.pcm) <= 12000 and packet.sample_rate_hz == 16000 for packet in stt.packets)
    assert [packet.first_sample for packet in stt.packets] == [0, 6000, 12000]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    phases = [event["phase"] for event in report["events"]]
    assert phases.index("tts_dispatch_started") < phases.index("tts_http_status_received")
    assert phases.index("tts_first_packet_received") < phases.index("tts_cancel_started")
    assert phases.index("tts_transport_closed") < phases.index("stt_dispatch_started")
    assert report["billing_status"] == "unknown" and report["taxes_and_fees_status"] == "unknown"
    assert report["partial_recognition_only"] is True
    assert SYNTHETIC_TEXT not in report_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_remaining_scope_persists_denial_and_never_starts_stt(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    SharedLedger(ledger_path).reserve("tts_normal", TTS_RESERVE_USD)

    class DeniedTts:
        def synthesize(self, text, stream_id):
            async def source():
                report_status(403)
                raise RuntimeError("private error body must not escape")
                yield  # pragma: no cover
            return source()

    class NeverStt:
        async def transcribe(self, packets):
            raise AssertionError("STT must not start after TTS denial")
            yield

    report_status = None
    def factory(callback):
        nonlocal report_status
        report_status = callback
        return DeniedTts(), NeverStt(), []

    result = await run_remaining_cancel_stt(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
    )
    calls = json.loads(ledger_path.read_text(encoding="utf-8"))["calls"]
    assert len(calls) == 2
    assert calls[-1]["kind"] == "tts_cancel_after_first_packet"
    assert calls[-1]["state"] == "failed_unknown_usage" and calls[-1]["http_status"] == 403
    assert calls[-1]["reserved_usd"] == format(TTS_RESERVE_USD, "f")
    assert result["state"] == "failed_unknown_usage"
    assert "private error body" not in report_path.read_text(encoding="utf-8")


def prior_two_failed_slots(ledger_path):
    ledger = SharedLedger(ledger_path)
    first = ledger.reserve("tts_normal", TTS_RESERVE_USD)
    second = ledger.reserve("tts_cancel_after_first_packet", TTS_RESERVE_USD)
    ledger.finish(second, "failed_unknown_usage", status_class="4xx", http_status=400,
                  provider_error="invalid_input", terminal_phase="terminal_failure")
    return first, second


@pytest.mark.asyncio
async def test_additional_minimal_tts_and_stt_use_only_newly_authorized_slots(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    prior_two_failed_slots(ledger_path)

    class Tts:
        def __init__(self, report_status):
            self.report_status, self.calls = report_status, []

        async def synthesize(self, text, stream_id):
            self.calls.append((text, stream_id))
            self.report_status(200)
            yield AudioPacket(stream_id, 0, 24000, b"\x01\x00" * 24000)

    class Stt:
        def __init__(self):
            self.packets = []

        async def transcribe(self, packets):
            async for packet in packets:
                self.packets.append(packet)
            yield TranscriptRevision("google-smoke-stt", 1, SYNTHETIC_TEXT, True)

    tts, stt, resource = None, Stt(), Resource()
    def factory(report_status):
        nonlocal tts
        tts = Tts(report_status)
        return tts, stt, [resource]

    result = await run_additional_official_tts(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
    )
    calls = json.loads(ledger_path.read_text(encoding="utf-8"))["calls"]
    assert [call["kind"] for call in calls] == [
        "tts_normal", "tts_cancel_after_first_packet", ADDITIONAL_TTS_KIND, "stt_v2"]
    assert [call["state"] for call in calls] == [
        "reserved_unknown_usage", "failed_unknown_usage", "completed", "completed"]
    assert calls[2]["reserved_usd"] == format(TTS_FULL_RESERVE_USD, "f")
    assert len(tts.calls) == 1 and tts.calls[0][0] == SYNTHETIC_TEXT
    assert len(stt.packets) == 3 and all(len(packet.pcm) <= 12000 for packet in stt.packets)
    assert result["state"] == "completed"
    assert result["final_revision_received"] is True
    stt_event = next(event for event in result["events"] if event["phase"] == "stt_terminal_result")
    assert stt_event["fixed_text_match"] is True
    assert resource.closed
    assert result["request_mode"] == "official_minimal_streaming_tts"
    assert result["taxes_and_fees_status"] == "unknown"


@pytest.mark.asyncio
async def test_additional_tts_records_sanitized_field_diagnostic_and_skips_stt(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    prior_two_failed_slots(ledger_path)

    from mira.adapters.speech.errors import ProviderErrorDetails, SpeechProviderError

    class DeniedTts:
        def __init__(self, report_status):
            self.report_status = report_status

        async def synthesize(self, text, stream_id):
            self.report_status(400)
            raise SpeechProviderError("invalid_input", details=ProviderErrorDetails(
                http_status=400, provider_status="INVALID_ARGUMENT", provider_reason="INVALID_ARGUMENT",
                field_names=("generationConfig.responseFormat",), diagnostic="unknown_request_field",
                body_bytes_read=120, body_capture_status="parsed",
            ))
            yield

    class NeverStt:
        async def transcribe(self, packets):
            raise AssertionError("STT must not start when additional TTS was rejected")
            yield

    def factory(callback):
        return DeniedTts(callback), NeverStt(), []

    result = await run_additional_official_tts(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
    )
    calls = json.loads(ledger_path.read_text(encoding="utf-8"))["calls"]
    assert len(calls) == 3 and calls[-1]["kind"] == ADDITIONAL_TTS_KIND
    assert calls[-1]["state"] == "failed_unknown_usage"
    assert calls[-1]["provider_status"] == "INVALID_ARGUMENT"
    assert calls[-1]["field_names"] == ["generationConfig.responseFormat"]
    assert calls[-1]["diagnostic"] == "unknown_request_field"
    assert result["state"] == "failed_unknown_usage"
    diagnostic_event = next(event for event in result["events"] if event["phase"] == "tts_terminal_failure")
    assert diagnostic_event["field_names"] == ["generationConfig.responseFormat"]


@pytest.mark.asyncio
async def test_original_stt_slot_uses_manifest_verified_synthetic_english_flite_fixture(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    prior_two_failed_slots(ledger_path)
    diagnostic = SharedLedger(ledger_path).reserve(ADDITIONAL_TTS_KIND, TTS_FULL_RESERVE_USD)
    SharedLedger(ledger_path).finish(diagnostic, "failed_unknown_usage", status_class="2xx",
                                     http_status=200, provider_error="unsupported_audio",
                                     terminal_phase="terminal_failure")

    from tools.generate_rehearsal_audio import verify
    from mira.application.ports.media import AudioPacket

    manifest = verify(OFFLINE_FLITE_FIXTURE_DIR)
    expected = manifest["clips"]["greeting"]["caption"]

    class Stt:
        def __init__(self):
            self.packets = []

        async def transcribe(self, packets):
            async for packet in packets:
                self.packets.append(packet)
            yield TranscriptRevision("offline-flite-greeting", 1, expected, True)

    stt, resource = Stt(), Resource()
    def factory(language_code):
        assert language_code == "en-US"
        return stt, [resource]

    result = await run_offline_english_fixture_stt(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
    )
    calls = json.loads(ledger_path.read_text(encoding="utf-8"))["calls"]
    assert [call["kind"] for call in calls] == [
        "tts_normal", "tts_cancel_after_first_packet", ADDITIONAL_TTS_KIND, "stt_v2"]
    assert calls[-1]["state"] == "completed" and calls[-1]["reserved_usd"] == format(STT_RESERVE_USD, "f")
    assert result["fixture_pcm_sha256"] == manifest["clips"]["greeting"]["pcm_sha256"]
    assert result["input_language"] == "en-US" and result["stt_model"] == "chirp_3"
    assert result["sample_rate_hz"] == 24000 and result["channels"] == 1
    assert result["sample_count"] == manifest["clips"]["greeting"]["frames"]
    assert result["duration_seconds"] == 6.135
    assert result["final_revision_received"] is True and result["fixture_caption_match"] is True
    assert len(stt.packets) == 25 and all(len(packet.pcm) <= 12000 for packet in stt.packets)
    assert resource.closed
    serialized = report_path.read_text(encoding="utf-8")
    assert expected not in serialized
    assert "microphone_used" in serialized and "chinese_quality_claim" in serialized


@pytest.mark.asyncio
async def test_recovery_tts_media_error_is_sanitized_and_stt_runs_on_verified_fixture(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    prior_two_failed_slots(ledger_path)
    diagnostic = SharedLedger(ledger_path).reserve(ADDITIONAL_TTS_KIND, TTS_FULL_RESERVE_USD)
    SharedLedger(ledger_path).finish(diagnostic, "failed_unknown_usage", status_class="2xx",
        http_status=200, provider_error="unsupported_audio", terminal_phase="terminal_failure")
    original_stt = SharedLedger(ledger_path).reserve("stt_v2", STT_RESERVE_USD)
    SharedLedger(ledger_path).finish(original_stt, "failed_unknown_usage", status_class="transport_error",
        provider_error="unavailable", terminal_phase="terminal_failure")

    from tools.generate_rehearsal_audio import verify
    expected = verify(OFFLINE_FLITE_FIXTURE_DIR)["clips"]["greeting"]["caption"]
    resources, stt_packets, factory_languages = [], [], []

    class Tts:
        def __init__(self, status_callback):
            self.status_callback = status_callback

        def synthesize(self, text, stream_id):
            async def source():
                self.status_callback(200)
                raise SpeechProviderError("unsupported_audio", audio_details=SafeAudioDiagnostic(
                    part_index=0, part_type_names=("inlineData",), mime_type="audio/wav",
                    audio_data_chars=24, validation_reason="unsupported_mime_type",
                ))
                yield  # pragma: no cover - force an async generator
            return source()

    class Stt:
        async def transcribe(self, packets):
            async for packet in packets:
                stt_packets.append(packet)
            yield TranscriptRevision("recovery-stt", 1, expected, True)

    def factory(status_callback, language):
        factory_languages.append(language)
        resource = Resource()
        resources.append(resource)
        return Tts(status_callback), Stt(), [resource]

    result = await run_recovery_tts_stt(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
    )
    record = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert record["reserved_total_usd"] == "0.675456"
    assert [call["kind"] for call in record["calls"]][-2:] == [RECOVERY_TTS_KIND, "stt_v2"]
    assert [call["state"] for call in record["calls"]][-2:] == ["failed_unknown_usage", "completed"]
    assert record["calls"][-2]["audio_diagnostic"]["validation_reason"] == "unsupported_mime_type"
    assert factory_languages == ["cmn-Hans-CN", "en-US"]
    assert result["stt_source"] == "offline_flite_fixture" and result["stt_input_language"] == "en-US"
    assert result["final_revision_received"] is True and result["fixed_text_match"] is True
    assert sum(len(packet.pcm) for packet in stt_packets) == 98160 * 2
    assert all(len(packet.pcm) <= 12000 for packet in stt_packets)
    assert all(resource.closed for resource in resources)
    serialized = report_path.read_text(encoding="utf-8")
    assert expected not in serialized and "synthetic-only" not in serialized


@pytest.mark.asyncio
async def test_recovery_stt_only_skips_every_tts_call_and_uses_existing_slot(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    prior_two_failed_slots(ledger_path)
    extra = SharedLedger(ledger_path).reserve(ADDITIONAL_TTS_KIND, TTS_FULL_RESERVE_USD)
    SharedLedger(ledger_path).finish(extra, "failed_unknown_usage", status_class="2xx",
        http_status=200, provider_error="unsupported_audio", terminal_phase="terminal_failure")
    original = SharedLedger(ledger_path).reserve("stt_v2", STT_RESERVE_USD)
    SharedLedger(ledger_path).finish(original, "failed_unknown_usage", status_class="transport_error",
        provider_error="unavailable", terminal_phase="terminal_failure")
    recovery = SharedLedger(ledger_path).reserve(RECOVERY_TTS_KIND, TTS_FULL_RESERVE_USD)
    SharedLedger(ledger_path).finish(recovery, "failed_unknown_usage", status_class="2xx",
        http_status=200, provider_error="unsupported_audio", terminal_phase="terminal_failure",
        audio_diagnostic={"part_index": 0, "part_type_names": ["text"],
                          "candidate_finish_reason": "STOP", "validation_reason": "non_audio_part"})

    from tools.generate_rehearsal_audio import verify
    expected = verify(OFFLINE_FLITE_FIXTURE_DIR)["clips"]["greeting"]["caption"]
    class Stt:
        async def transcribe(self, packets):
            async for packet in packets:
                pass
            yield TranscriptRevision("recovery-stt", 1, expected, True)
    resource = Resource()
    def factory(language):
        assert language == "en-US"
        return Stt(), [resource]

    result = await run_offline_english_fixture_stt(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
        recovery_after_tts=True,
    )
    calls = json.loads(ledger_path.read_text(encoding="utf-8"))["calls"]
    assert len(calls) == 6 and calls[-1]["kind"] == "stt_v2" and calls[-1]["state"] == "completed"
    assert calls[-1]["reserved_usd"] == format(STT_RESERVE_USD, "f")
    assert result["prior_reserved_usd"] == "0.667456"
    assert result["projected_pre_tax_total_usd"] == "0.675456"
    assert result["final_revision_received"] and result["fixture_caption_match"]
    assert resource.closed and expected not in report_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_text_diagnostic_followup_is_one_tts_only_and_scrubs_provider_excerpt(tmp_path):
    readiness_path, enabled_path = resume_receipts(tmp_path)
    ledger_path, report_path = tmp_path / "ledger.json", tmp_path / "report.json"
    prior_two_failed_slots(ledger_path)
    extra = SharedLedger(ledger_path).reserve(ADDITIONAL_TTS_KIND, TTS_FULL_RESERVE_USD)
    SharedLedger(ledger_path).finish(extra, "failed_unknown_usage", status_class="2xx",
        http_status=200, provider_error="unsupported_audio", terminal_phase="terminal_failure")
    original = SharedLedger(ledger_path).reserve("stt_v2", STT_RESERVE_USD)
    SharedLedger(ledger_path).finish(original, "failed_unknown_usage", status_class="transport_error",
        provider_error="unavailable", terminal_phase="terminal_failure")
    recovery = SharedLedger(ledger_path).reserve(RECOVERY_TTS_KIND, TTS_FULL_RESERVE_USD)
    prior_audio = {"part_index": 0, "part_type_names": ["text"], "mime_param_names": [],
                   "candidate_finish_reason": "STOP", "validation_reason": "non_audio_part"}
    SharedLedger(ledger_path).finish(recovery, "failed_unknown_usage", status_class="2xx",
        http_status=200, provider_error="unsupported_audio", terminal_phase="terminal_failure",
        audio_diagnostic=prior_audio)
    prior_stt = SharedLedger(ledger_path).reserve("stt_v2", STT_RESERVE_USD)
    SharedLedger(ledger_path).finish(prior_stt, "completed", status_class="2xx", sample_count=147240,
        duration_seconds=6.135, terminal_phase="stt_completed")

    resources = []
    class Tts:
        def __init__(self, status_callback):
            self.status_callback = status_callback
            self.calls = []

        def synthesize(self, text, stream_id):
            self.calls.append((text, stream_id))
            async def source():
                self.status_callback(200)
                raise SpeechProviderError("unsupported_audio", audio_details=SafeAudioDiagnostic(
                    part_index=0, part_type_names=("text",), candidate_finish_reason="STOP",
                    validation_reason="non_audio_part", model_version="gemini-3.8-flash-tts-002",
                    input_token_count=5, output_token_count=9, total_token_count=14,
                    response_text_excerpt="拒绝处理 你好，这是一次语音连接测试。 access_token=ya29.SECRET "
                                          "projects/offline-test https://private.example/path",
                ))
                yield  # pragma: no cover
            return source()

    class NoStt:
        async def transcribe(self, packets):
            raise AssertionError("This explicitly approved diagnostic action is TTS only")
            yield

    def factory(status_callback, language):
        assert language == "cmn-Hans-CN"
        resource = Resource()
        resources.append(resource)
        return Tts(status_callback), NoStt(), [resource]

    result = await run_recovery_tts_stt(
        readiness_path, enabled_path, ledger_path, report_path,
        project_id="offline-test", adc_dir=tmp_path, adapter_factory=factory,
        followup_after_stt=True,
    )
    calls = json.loads(ledger_path.read_text(encoding="utf-8"))["calls"]
    assert len(calls) == 7 and calls[-1]["kind"] == TTS_TEXT_DIAGNOSTIC_KIND
    assert calls[-1]["state"] == "failed_unknown_usage" and calls[-1]["http_status"] == 200
    assert calls[-1]["audio_diagnostic"]["model_version"] == "gemini-3.8-flash-tts-002"
    assert calls[-1]["audio_diagnostic"]["total_token_count"] == 14
    excerpt = calls[-1]["audio_diagnostic"]["response_text_excerpt"]
    assert "拒绝处理" in excerpt and "[synthetic-prompt-redacted]" in excerpt
    for secret in ("ya29.SECRET", "offline-test", "private.example", "https://"):
        assert secret not in excerpt
    assert calls[-1]["reserved_usd"] == format(TTS_FULL_RESERVE_USD, "f")
    assert json.loads(ledger_path.read_text(encoding="utf-8"))["reserved_total_usd"] == "0.978560"
    assert result["tts_only"] is True and result["response_text_diagnostics_enabled"] is True
    assert "token_count" in report_path.read_text(encoding="utf-8")
    assert all(resource.closed for resource in resources)
