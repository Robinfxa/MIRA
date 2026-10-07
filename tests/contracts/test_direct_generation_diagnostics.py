"""Synthetic transport/actor/export regressions; never reads auth or calls providers."""
import asyncio
import gzip
import json
import zlib
from uuid import uuid4

import pytest

from mira.adapters.diagnostics.privacy import encode_event, validate_event_record
from mira.adapters.generation.direct_codex_responses import DirectResponsesError, DirectResponsesLimits
from mira.adapters.journal.memory import MemoryEventJournal
from mira.adapters.review.mock import FixtureReviewBackend
from mira.application.diagnostic_events import DiagnosticStage, DiagnosticOutcome
from mira.application.session_actor import RuntimeLimits, SessionActor
from mira.domain.models import SessionState
from tests.contracts.test_diagnostics_runtime import CollectDiagnostics
from tests.contracts.test_direct_codex_responses import (
    backend, collect, response, item_done, completed, event, ByteStream,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding,compress', [('gzip', gzip.compress), ('deflate', zlib.compress)])
@pytest.mark.parametrize('chunk_size', [1, 4096])
async def test_compressed_sse_is_decoded_once_before_strict_parsing(encoding, compress, chunk_size):
    wire = compress(item_done() + completed())
    stream = ByteStream([wire[i:i+chunk_size] for i in range(0, len(wire), chunk_size)])
    async def handle(_):
        return response(b'', headers={'content-type': 'text/event-stream',
                        'content-encoding': encoding}, stream=stream)
    instance, _, requests = backend(handle)
    assert len(await collect(instance)) == 1
    assert len(requests) == 1 and stream.closed


@pytest.mark.asyncio
async def test_decoded_sse_budget_survives_high_compression():
    body = (b': ' + b'a' * 80 + b'\n') * 100
    async def handle(_):
        return response(gzip.compress(body), headers={'content-type': 'text/event-stream',
                        'content-encoding': 'gzip'})
    instance, _, _ = backend(handle, limits=DirectResponsesLimits(max_wire_bytes=1024))
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == 'response_limit'


@pytest.mark.asyncio
@pytest.mark.parametrize('wire', [gzip.compress(item_done()+completed())[:-4],
                                 b'not-a-valid-gzip-stream'])
async def test_bad_compressed_stream_never_yields(wire):
    async def handle(_):
        return response(wire, headers={'content-type': 'text/event-stream',
                                      'content-encoding': 'gzip'})
    instance, _, _ = backend(handle)
    with pytest.raises(DirectResponsesError) as raised:
        await collect(instance)
    assert raised.value.code == 'invalid_response'
    diagnostic = getattr(raised.value, 'generation_diagnostic', None)
    assert diagnostic is not None
    assert diagnostic.reason == 'content_decode'


async def actor_failure(instance):
    sink = CollectDiagnostics()
    actor = SessionActor(SessionState(str(uuid4()), str(uuid4())), instance,
        FixtureReviewBackend(), MemoryEventJournal(20), RuntimeLimits(2, 10, 30), diagnostics=sink)
    await actor.submit(request_id=str(uuid4()), activity_seq=1, cutoff=0, text='PRIVATE_USER_TEXT')
    await asyncio.gather(*tuple(actor._tasks))
    terminal, = [e for e in sink.events if e.stage == DiagnosticStage.GENERATION
                 and e.outcome == DiagnosticOutcome.FAILED]
    await actor.close()
    record = encode_event(terminal, 1)
    assert validate_event_record(record) == record
    return record


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 429, 503])
async def test_http_status_and_fixed_phase_reach_actor_and_export(status):
    async def handle(_):
        return response(b'PRIVATE_PROVIDER_BODY', status=status,
                        headers={'content-type': 'application/json', 'x-secret': 'PRIVATE_HEADER'})
    instance, _, _ = backend(handle)
    record = await actor_failure(instance)
    assert record.get('http_status') == status
    diag = record.get('generation_diagnostic')
    assert diag is not None and diag['phase'] in {'http_status', 'auth', 'authorization', 'quota'}
    assert 'PRIVATE' not in json.dumps(record)


@pytest.mark.asyncio
async def test_invalid_effects_report_safe_validation_reason_and_terminal_events():
    async def handle(_):
        return response(item_done(text='PRIVATE_INVALID_JSON') + completed())
    instance, _, _ = backend(handle)
    record = await actor_failure(instance)
    assert record.get('http_status') == 200
    diagnostic = record.get('generation_diagnostic')
    assert diagnostic is not None and diagnostic['phase'] == 'validation'
    assert diagnostic['reason'] == 'codex_json_invalid'
    assert diagnostic['terminal_status'] == 'completed'
    assert diagnostic['event_types'] == ['response.output_item.done', 'response.completed']
    assert diagnostic['event_count'] == 2
    assert 'PRIVATE' not in json.dumps(record)


@pytest.mark.asyncio
@pytest.mark.parametrize('code,expected', [('model_not_found', 'model_not_found'),
                                         ('PRIVATE_UNKNOWN_CODE', 'other')])
async def test_provider_error_codes_are_fixed_allowlist_only(code, expected):
    async def handle(_):
        return response(event('response.failed', {'type': 'response.failed', 'response': {
            'status': 'failed', 'error': {'code': code, 'message': 'PRIVATE_ERROR_MESSAGE'}}}))
    instance, _, _ = backend(handle)
    record = await actor_failure(instance)
    diagnostic = record.get('generation_diagnostic')
    assert diagnostic is not None and diagnostic['provider_error_code'] == expected
    assert diagnostic['terminal_status'] == 'failed'
    assert record['code'] == 'unavailable'
    assert 'PRIVATE' not in json.dumps(record)


@pytest.mark.asyncio
async def test_raw_deflate_and_null_optional_response_metadata_are_supported():
    codec = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    body = item_done() + event('response.completed', {'type': 'response.completed', 'response': {
        'status': 'completed', 'output': None, 'usage': None, 'error': None}})
    wire = codec.compress(body) + codec.flush()
    async def handle(_):
        return response(wire, headers={'content-type': 'text/event-stream',
                                      'content-encoding': 'deflate'})
    instance, _, _ = backend(handle)
    assert len(await collect(instance)) == 1


@pytest.mark.asyncio
async def test_compressed_stream_cancel_and_timeout_close_without_candidates():
    from tests.contracts.test_direct_codex_responses import BlockingStream
    for explicit_cancel in (True, False):
        stream = BlockingStream(gzip.compress(item_done()))
        async def handle(_):
            return response(b'', stream=stream, headers={'content-type': 'text/event-stream',
                                                        'content-encoding': 'gzip'})
        limits = DirectResponsesLimits(turn_seconds=2 if explicit_cancel else 0.02)
        instance, _, _ = backend(handle, limits=limits)
        task = asyncio.create_task(collect(instance))
        await stream.entered.wait()
        if explicit_cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(DirectResponsesError) as raised:
                await task
            assert raised.value.code == 'timeout'
        assert stream.closed


@pytest.mark.asyncio
async def test_unknown_event_type_and_encoding_never_enter_safe_diagnostics():
    async def handle(_):
        return response(b'event: PRIVATE_EVENT\ndata: PRIVATE_CONTENT\n\n')
    instance, _, _ = backend(handle)
    record = await actor_failure(instance)
    assert record['generation_diagnostic']['event_types'] == ['other']
    assert 'PRIVATE' not in json.dumps(record)
    async def handle_encoding(_):
        return response(b'PRIVATE_BYTES', headers={'content-type': 'text/event-stream',
                                      'content-encoding': 'PRIVATE_ENCODING'})
    instance, _, _ = backend(handle_encoding)
    record = await actor_failure(instance)
    assert record['generation_diagnostic']['content_encoding'] == 'other'
    assert record['generation_diagnostic']['reason'] == 'content_encoding'
    assert 'PRIVATE' not in json.dumps(record)


def test_diagnostic_contract_rejects_arbitrary_strings_counts_and_extra_export_keys(tmp_path):
    from dataclasses import replace
    from mira.application.generation_diagnostics import SafeGenerationDiagnostic
    from mira.application.diagnostic_events import DiagnosticEvent
    from mira.adapters.diagnostics.recorder import LocalDiagnostics, DiagnosticOptions
    from mira.adapters.diagnostics.export import export_diagnostics
    import zipfile
    value = SafeGenerationDiagnostic(phase='sse', reason='utf8', http_status=200)
    for changes in ({'phase': 'PRIVATE'}, {'reason': 'PRIVATE'}, {'provider_error_code': 'PRIVATE'},
                    {'terminal_status': 'PRIVATE'}, {'event_types': ('PRIVATE',)},
                    {'wire_bytes': 4194306}, {'decoded_bytes': -1}, {'event_count': True},
                    {'http_status': True}):
        with pytest.raises(ValueError):
            replace(value, **changes)
    event = DiagnosticEvent(DiagnosticStage.GENERATION, DiagnosticOutcome.FAILED,
                            generation_diagnostic=value, http_status=200)
    record = encode_event(event, 1)
    bad = json.loads(json.dumps(record))
    bad['generation_diagnostic']['private_message'] = 'PRIVATE'
    with pytest.raises(ValueError):
        validate_event_record(bad)
    root = tmp_path / 'diagnostics'
    sink = LocalDiagnostics(DiagnosticOptions(root), worker=False, clock=lambda: 1)
    assert sink.emit(event)
    assert sink.flush()
    sink.close()
    target = tmp_path / 'safe.zip'
    manifest = export_diagnostics(root, target)
    assert manifest['event_count'] == 1 and manifest['raw_count'] == 0
    with zipfile.ZipFile(target) as bundle:
        exported = json.loads(bundle.read('events.jsonl'))
    assert exported['generation_diagnostic'] == record['generation_diagnostic']


@pytest.mark.parametrize('raw,kind,shape', [
    ('{"PRIVATE_SECRET":', 'syntax', 'bare_object'),
    ('{"PRIVATE_SECRET":1,"PRIVATE_SECRET":2}', 'duplicate_key', 'bare_object'),
    ('{"PRIVATE_SECRET":NaN}', 'nonfinite', 'bare_object'),
    ('{"PRIVATE_SECRET":Infinity}', 'nonfinite', 'bare_object'),
    ('{"PRIVATE_SECRET":-Infinity}', 'nonfinite', 'bare_object'),
    (b'\xffPRIVATE_SECRET', 'encoding', 'plain_or_other'),
    ('[' * 20000 + '"PRIVATE_SECRET"' + ']' * 20000, 'depth', 'array'),
    ({'PRIVATE_SECRET': 1}, 'type', 'plain_or_other'),
    ('```json\n{"PRIVATE_SECRET":1}\n```', 'syntax', 'markdown_fence'),
    ('["PRIVATE_SECRET",]', 'syntax', 'array'),
    ('PRIVATE_SECRET', 'syntax', 'plain_or_other'),
], ids=['syntax', 'duplicate', 'nan', 'positive-infinity', 'negative-infinity',
        'encoding', 'depth', 'type', 'fence', 'array', 'plain'])
def test_strict_json_failure_classes_are_fixed_and_content_free(raw, kind, shape):
    from mira.adapters.generation.codex_support.payload import strict_json
    from mira.adapters.generation.codex_support.types import CodexGenerationError
    with pytest.raises(CodexGenerationError) as raised:
        strict_json(raw)
    error = raised.value
    assert error.args == ('codex_json_invalid',)
    assert getattr(error, 'json_failure_kind', None) == kind
    assert getattr(error, 'wrapper_shape', None) == shape
    assert 'PRIVATE' not in repr(error) + repr(vars(error))


@pytest.mark.parametrize('raw', [
    '{"effects":[{"kind":"subtitle","value":"雨声很轻。"}]}',
    ' [1, true, null, {"x":2}] ', '"string"', '42',
    b'{"x":1}', bytearray(b'{"x":1}'), '{"x":1}'.encode('utf-16'),
])
def test_strict_json_valid_acceptance_is_unchanged(raw):
    from mira.adapters.generation.codex_support.payload import strict_json
    assert strict_json(raw) == json.loads(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize('text,kind,shape', [
    ('{"PRIVATE_SECRET":', 'syntax', 'bare_object'),
    ('{"PRIVATE_SECRET":1,"PRIVATE_SECRET":2}', 'duplicate_key', 'bare_object'),
    ('{"PRIVATE_SECRET":NaN}', 'nonfinite', 'bare_object'),
    ('[' * 20000 + '"PRIVATE_SECRET"' + ']' * 20000, 'depth', 'array'),
    ('```json\n{"PRIVATE_SECRET":1}\n```', 'syntax', 'markdown_fence'),
    ('PRIVATE_SECRET', 'syntax', 'plain_or_other'),
], ids=['syntax', 'duplicate', 'nonfinite', 'depth', 'fence', 'plain'])
async def test_json_failure_classes_reach_export_without_content_or_retry(tmp_path, text, kind, shape):
    from mira.adapters.diagnostics.export import export_diagnostics
    import zipfile
    async def handle(_):
        return response(item_done(text=text) + completed())
    instance, source, requests = backend(handle, limits=DirectResponsesLimits(max_output_bytes=65536))
    record = await actor_failure(instance)
    diagnostic = record['generation_diagnostic']
    assert record['code'] == 'invalid_response'
    assert diagnostic['reason'] == 'codex_json_invalid'
    assert diagnostic['phase'] == 'validation' and diagnostic['terminal_status'] == 'completed'
    assert diagnostic.get('json_failure_kind') == kind
    assert diagnostic.get('wrapper_shape') == shape
    assert len(requests) == source.calls == 1
    root = tmp_path / 'diagnostics'
    (root / 'events').mkdir(parents=True, mode=0o700)
    (root / 'events' / ('events-' + '0' * 32 + '.jsonl')).write_text(
        json.dumps(record) + '\n', encoding='utf-8')
    target = tmp_path / 'safe.zip'
    manifest = export_diagnostics(root, target)
    assert manifest['event_count'] == 1 and manifest['raw_count'] == 0
    with zipfile.ZipFile(target) as bundle:
        exported = bundle.read('events.jsonl')
        assert b'PRIVATE_SECRET' not in b''.join(bundle.read(name) for name in bundle.namelist())
    assert json.loads(exported)['generation_diagnostic'] == diagnostic


def test_json_failure_classes_are_closed_and_old_records_still_validate():
    from dataclasses import replace
    from mira.application.generation_diagnostics import SafeGenerationDiagnostic
    from mira.application.diagnostic_events import DiagnosticEvent
    value = SafeGenerationDiagnostic(phase='validation', reason='codex_json_invalid')
    for field in ('json_failure_kind', 'wrapper_shape'):
        for invalid in ('PRIVATE_SECRET', {'PRIVATE_SECRET': 1}, True):
            with pytest.raises(ValueError):
                replace(value, **{field: invalid})
    event = DiagnosticEvent(DiagnosticStage.GENERATION, DiagnosticOutcome.FAILED,
                            generation_diagnostic=value)
    record = encode_event(event, 1)
    for field in ('json_failure_kind', 'wrapper_shape'):
        record['generation_diagnostic'].pop(field, None)
    checked = validate_event_record(record)
    assert checked['generation_diagnostic']['json_failure_kind'] is None
    assert checked['generation_diagnostic']['wrapper_shape'] is None


def test_unknown_json_value_error_does_not_export_exception_text(monkeypatch):
    from mira.adapters.generation.codex_support import payload
    from mira.adapters.generation.codex_support.types import CodexGenerationError
    def fail(*args, **kwargs):
        raise ValueError('PRIVATE_SECRET_FROM_PARSER')
    monkeypatch.setattr(payload.json, 'loads', fail)
    with pytest.raises(CodexGenerationError) as raised:
        payload.strict_json('{"PRIVATE_SECRET":1}')
    assert raised.value.json_failure_kind == 'unknown'
    assert raised.value.wrapper_shape == 'bare_object'
    assert 'PRIVATE' not in repr(raised.value) + repr(vars(raised.value))
