import asyncio
from dataclasses import asdict, replace
import io
from pathlib import Path

from PIL import Image
import pytest

from mira.adapters.media.png_decoder import PillowPngDecoder
from mira.application.story_images import StoryImageRuntime, StoryImageAdmission
from mira.application.ports.media import GeneratedImage, MediaRequest
from mira.application.image_readiness import runtime_image_readiness


def operation_readiness(value):
    epoch, activity = value._diagnostic_context
    return runtime_image_readiness(value, output_epoch=epoch, activity_seq=activity)


def png(size=(1024, 1024), mode='RGB', color=(32, 64, 96)):
    output = io.BytesIO()
    with Image.new(mode, size, color) as image:
        image.save(output, format='PNG')
    return output.getvalue()


class OfflineImage:
    def __init__(self, data, media_type='image/png'):
        self.data, self.media_type = data, media_type
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        return GeneratedImage(self.data, self.media_type, 'synthetic', 'offline')


class ForbiddenReview:
    def __init__(self):
        self.calls = 0

    async def review(self, *_):
        self.calls += 1
        pytest.fail('Rejected pixels must never reach review.')


def request():
    return MediaRequest('synthetic-image', 'offline synthetic fixture', (), 1,
        'synthetic-session', 'synthetic-parent', 1, 0, 'a'*64, 'b'*64,
        1, 'synthetic', 'synthetic', 'synthetic')


def runtime(data, mime='image/png'):
    image, review = OfflineImage(data, mime), ForbiddenReview()
    return StoryImageRuntime(image, review, PillowPngDecoder(),
        StoryImageAdmission('synthetic', True)), image, review


async def reject(data, mime='image/png'):
    value, image, review = runtime(data, mime)
    phases = []
    async def phase(name):
        phases.append(name)
        return True
    with pytest.raises(ValueError):
        await value.generate_and_review(request(), phase)
    assert image.calls == 1 and review.calls == 0 and phases == []
    assert value.provider_observation == 'generation_returned'
    return asdict(operation_readiness(value))


@pytest.mark.asyncio
async def test_invalid_returned_image_contract_is_distinct():
    observed = await reject(png(), 'image/jpeg')
    assert observed.get('operation_stage') == 'generated_validation'
    assert observed.get('failure_reason') == 'image_generation_invalid'
    assert observed.get('failure_exception') == 'value_error'
    assert observed.get('png_width') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('case,reason,width,height,mode', [
    ('dimensions', 'image_png_dimensions', 512, 512, 'rgb'),
    ('crc', 'image_png_crc', 1024, 1024, 'rgb'),
    ('alpha', 'image_png_transparency', 1024, 1024, 'rgba'),
])
async def test_png_rejections_preserve_safe_exact_reason(case, reason, width, height, mode):
    data = png((512, 512)) if case == 'dimensions' else (
        png(mode='RGBA', color=(32, 64, 96, 128)) if case == 'alpha' else png())
    if case == 'crc':
        damaged = bytearray(data)
        damaged[29] ^= 1
        data = bytes(damaged)
    observed = await reject(data)
    assert observed.get('operation_stage') == 'png_decode'
    assert observed.get('failure_reason') == reason
    assert observed.get('failure_exception') == 'image_provider_error'
    assert (observed.get('png_width'), observed.get('png_height')) == (width, height)
    assert observed.get('png_mode') == mode
    assert observed.get('png_bit_depth') == '8'


def test_timeout_preserves_phase_and_does_not_copy_exception_text():
    value, _, _ = runtime(png())
    assert callable(getattr(value, 'record_operation_failure', None))
    from mira.application.image_operation_diagnostics import SafeImageOperationDiagnostic
    value.operation_diagnostic = SafeImageOperationDiagnostic(operation_stage='png_decode')
    value.record_operation_failure(TimeoutError('secret raw request and auth token'))
    observed = asdict(operation_readiness(value))
    assert observed['operation_stage'] == 'png_decode'
    assert observed['failure_reason'] == 'timeout'
    assert observed['failure_exception'] == 'timeout'
    assert 'secret' not in str(observed)


def test_timeout_observation_is_terminal_even_if_same_job_returns_late():
    from mira.application.image_operation_diagnostics import SafeImageOperationDiagnostic
    value, _, _ = runtime(png())
    value._begin_operation_diagnostic('timed-out', output_epoch=1, activity_seq=1)
    value.operation_diagnostic = SafeImageOperationDiagnostic(operation_stage='png_decode')
    value.record_operation_failure(TimeoutError(), request_id='timed-out')
    before = asdict(operation_readiness(value))
    value._operation_diagnostic('timed-out', stage='review_validation', provider='review_returned')
    value.record_operation_failure(ValueError('image_png_crc'), request_id='timed-out')
    assert asdict(operation_readiness(value)) == before


def test_unknown_exception_text_is_not_exported():
    value, _, _ = runtime(png())
    assert callable(getattr(value, 'record_operation_failure', None))
    value.record_operation_failure(ValueError('secret unknown runtime error'))
    observed = asdict(operation_readiness(value))
    assert observed['failure_reason'] == 'unknown'
    assert observed['failure_exception'] == 'value_error'
    assert 'secret' not in str(observed)

@pytest.mark.asyncio
async def test_oversized_ihdr_is_closed_metadata_not_raw_dimensions():
    import struct
    import zlib
    data = bytearray(png())
    data[16:20] = struct.pack('>I', 2**32 - 1)
    data[29:33] = struct.pack('>I', zlib.crc32(data[12:29]))
    observed = await reject(bytes(data))
    assert observed['failure_reason'] == 'image_png_dimensions'
    assert observed['png_dimensions'] == 'over_limit'
    assert observed['png_width'] is None and observed['png_height'] is None


def test_old_image_events_roundtrip_with_defaults_and_unknown_metadata_rejected():
    import json
    from mira.application.diagnostic_events import DiagnosticEvent, DiagnosticStage, DiagnosticOutcome
    from mira.adapters.diagnostics.privacy import encode_event, validate_event_record
    from mira.application.image_operation_diagnostics import SafeImageOperationDiagnostic
    operation_fields = set(asdict(SafeImageOperationDiagnostic()))
    value, _, _ = runtime(png())
    record = encode_event(DiagnosticEvent(DiagnosticStage.IMAGE_READINESS, DiagnosticOutcome.SUCCEEDED,
        image_readiness=runtime_image_readiness(value)), 123)
    old = json.loads(json.dumps(record))
    for key in operation_fields:
        del old['image_readiness'][key]
    restored = validate_event_record(old)
    assert restored['image_readiness']['operation_stage'] == 'unobserved'
    assert restored['image_readiness']['failure_reason'] == 'none'
    for key, bad in [('failure_reason', 'private exception'), ('png_width', True),
                     ('png_mode', 'secret'), ('prompt', 'private prompt'), ('png_dimensions', 'huge raw value')]:
        invalid = json.loads(json.dumps(record))
        invalid['image_readiness'][key] = bad
        with pytest.raises((ValueError, TypeError)):
            validate_event_record(invalid)


@pytest.mark.asyncio
async def test_diagnostic_projection_failure_cannot_reject_valid_image(monkeypatch):
    from mira.application import story_images
    from tests.contracts.test_story_images import Vision
    value, image, _ = runtime(png())
    value.vision_backend = Vision()
    def broken(*_):
        raise ValueError('private diagnostic-only fault')
    monkeypatch.setattr(story_images, 'png_header_observation', broken)
    async def phase(_): return True
    artifact, description = await value.generate_and_review(request(), phase)
    assert artifact.png and len(value.vision_backend.calls) == 1
    assert value.provider_observation == 'review_returned'
    assert value.operation_diagnostic.operation_stage == 'review_passed'
    assert value.operation_diagnostic.failure_reason == 'none'


def native_actor(value, turns):
    from mira.application.session_actor import RuntimeLimits
    from mira.adapters.journal.memory import MemoryEventJournal
    from mira.bootstrap.character_story import ephemeral_character_factory
    from mira.domain.models import SessionState
    from tests.contracts.test_native_character_tools import NeverReview
    from tests.contracts.test_luna_tool_actor import Tools, LegacyGeneration, ObservedActor
    from tests.contracts.test_authored_photo_events import ready
    character = ephemeral_character_factory(readiness=ready())(SessionState('s', 'c'))
    return ObservedActor(SessionState('s', 'c'), LegacyGeneration(), NeverReview(),
        MemoryEventJournal(200), RuntimeLimits(3, 8, 64), tool_generation=Tools(*turns),
        native_tool_authority=True, character_runtime=character, story_image_runtime=value,
        tool_result_wait_seconds=.01)


def image_turn(call_id):
    import json
    from mira.application.ports.generation_tools import GenerationToolCall
    from tests.contracts.test_luna_tool_actor import ToolTurn
    return ToolTurn(GenerationToolCall(call_id, 'generate_story_image', json.dumps({
        'brief': 'An empty imaginary blue lakeside.', 'framing': 'wide', 'lighting': 'warm'})))


@pytest.mark.asyncio
async def test_actor_timeout_is_reported_at_decode_stage_without_review():
    import threading
    from tests.contracts.test_luna_tool_actor import wait_state
    value, image, review = runtime(png())
    value.admission = replace(value.admission, timeout_seconds=.15, authorized_custom_brief=True)
    entered, release = threading.Event(), threading.Event()
    class BlockedDecoder:
        def canonicalize(self, data):
            entered.set()
            assert release.wait(2)
            return PillowPngDecoder().canonicalize(data)
    value.decoder = BlockedDecoder()
    actor = native_actor(value, [image_turn('timeout')])
    try:
        await actor.submit(request_id='turn1', activity_seq=1, cutoff=0, text='Imagine an empty lake.')
        assert await asyncio.to_thread(entered.wait, 1)
        state = await wait_state(actor, lambda state: state.story_image.state == 'failed')
        observed = asdict(operation_readiness(value))
        assert state.story_image.failure_code == 'timeout'
        assert observed['operation_stage'] == 'png_decode'
        assert observed['failure_reason'] == 'timeout' and observed['failure_exception'] == 'timeout'
        assert observed['provider_observation'] == 'generation_returned' and review.calls == 0
    finally:
        release.set()
        await actor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('stop_first', [False, True])
async def test_cancelled_late_job_cannot_overwrite_new_job_diagnostics(stop_first):
    from tests.contracts.test_luna_tool_actor import wait_state
    value, _, review = runtime(png())
    value.admission = replace(value.admission, timeout_seconds=2, authorized_custom_brief=True)
    arrived, release = asyncio.Event(), asyncio.Event()
    class LateImage:
        def __init__(self): self.calls = 0
        async def generate(self, request):
            self.calls += 1
            if self.calls == 1:
                arrived.set()
                while not release.is_set():
                    try: await release.wait()
                    except asyncio.CancelledError: pass
                raise ValueError('image_generation_invalid')
            return GeneratedImage(png((512, 512)), 'image/png', 'synthetic', 'offline')
    value.image_backend = LateImage()
    actor = native_actor(value, [image_turn('old'), image_turn('new')])
    try:
        await actor.submit(request_id='turn1', activity_seq=1, cutoff=0, text='Imagine an empty lake.')
        await asyncio.wait_for(arrived.wait(), 1)
        if stop_first:
            await actor.stop(activity_seq=2, cutoff=0)
        else:
            await actor.dismiss_photo(request_id='cancel-old',expected_revision=0,cutoff=0,
                target='image_job',expected_image_request_id=(await actor.snapshot()).story_image.request_id)
        activity = 3 if stop_first else 2
        await actor.submit(request_id='turn2', activity_seq=activity, cutoff=0, text='Imagine a different empty lake.')
        state = await wait_state(actor, lambda state: state.activity_seq == activity and state.story_image.state == 'failed')
        before = asdict(operation_readiness(value))
        assert before['failure_reason'] == 'image_png_dimensions'
        assert before['png_width'] == 512 and review.calls == 0
        pending = tuple(actor._image_tasks)
        release.set()
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 1)
        assert asdict(operation_readiness(value)) == before
        assert (await actor.snapshot()).story_image == state.story_image
    finally:
        release.set()
        await actor.close()

@pytest.mark.asyncio
async def test_new_input_without_image_does_not_inherit_late_image_metadata():
    from tests.contracts.test_luna_tool_actor import ToolTurn, text_candidate
    from tests.contracts.test_development_review_composition import finish
    value, _, review = runtime(png())
    value.admission = replace(value.admission, timeout_seconds=2, authorized_custom_brief=True)
    arrived, release = asyncio.Event(), asyncio.Event()
    class LateImage:
        async def generate(self, request):
            arrived.set()
            while not release.is_set():
                try: await release.wait()
                except asyncio.CancelledError: pass
            return GeneratedImage(png((512, 512)), 'image/png', 'synthetic', 'offline')
    value.image_backend = LateImage()
    text_turn = ToolTurn()
    text_turn.call = text_candidate()
    actor = native_actor(value, [image_turn('old'), text_turn])
    try:
        await actor.submit(request_id='turn1', activity_seq=1, cutoff=0, text='Imagine an empty lake.')
        await asyncio.wait_for(arrived.wait(), 1)
        await actor.stop(activity_seq=2, cutoff=0)
        await actor.submit(request_id='turn2', activity_seq=3, cutoff=0, text='Just talk.')
        await finish(actor)
        pending = tuple(actor._image_tasks)
        release.set()
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 1)
        state = await actor.snapshot()
        observed = asdict(runtime_image_readiness(value,
            output_epoch=state.output_epoch, activity_seq=state.activity_seq))
        assert observed['operation_stage'] == 'unobserved'
        assert observed['failure_reason'] == 'none'
        assert observed['png_width'] is None and observed['png_mode'] == 'unobserved'
        assert review.calls == 0
    finally:
        release.set()
        await actor.close()
