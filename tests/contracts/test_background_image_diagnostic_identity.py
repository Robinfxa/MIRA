"""Exact job diagnostics survive reply turns without borrowing newer-job authority."""
import asyncio
from dataclasses import asdict, replace

import pytest

from mira.application.image_operation_diagnostics import SafeImageOperationDiagnostic
from mira.application.image_readiness import runtime_image_readiness
from tests.contracts.test_image_operation_diagnostics import runtime, png, native_actor, image_turn


def current(value, epoch=2):
    return asdict(runtime_image_readiness(value, output_epoch=epoch, activity_seq=epoch))


@pytest.mark.parametrize("phase", ["generating", "reviewing", "qualified", "presented", "failed", "held"])
def test_same_job_operation_facts_survive_a_new_reply_epoch(phase):
    value, images, reviews = runtime(png())
    value._begin_operation_diagnostic("job-a", output_epoch=1, activity_seq=1)
    value.update_phase("job-a", phase)
    value.operation_diagnostic = SafeImageOperationDiagnostic(
        operation_stage="pixel_review", failure_reason="image_http_transport",
        failure_exception="value_error", png_width=1024, png_height=1024,
        png_dimensions="bounded", png_mode="rgb", png_bit_depth="8", png_alpha="opaque")
    value.provider_observation = "review_error"
    observed = current(value)
    assert observed["output_epoch"] == 2 and observed["job_origin_epoch"] == 1
    assert observed["job_state"] == phase
    assert observed["operation_stage"] == "pixel_review"
    assert observed["failure_reason"] == "image_http_transport"
    assert observed["png_width"] == observed["png_height"] == 1024
    assert observed["provider_observation"] == "review_error"
    assert images.calls == reviews.calls == 0


def test_new_job_resets_observation_and_old_duplicate_writes_cannot_pollute_it():
    value, images, reviews = runtime(png())
    value._begin_operation_diagnostic("job-a", output_epoch=1, activity_seq=1)
    value._operation_diagnostic("job-a", stage="pixel_review", data=png(),
        provider="review_error", alpha="opaque")
    value.record_operation_failure(ValueError("image_http_transport"), request_id="job-a")
    value._begin_operation_diagnostic("job-b", output_epoch=2, activity_seq=2)
    value.update_phase("job-b", "generating")
    before = current(value, 3)
    assert before["operation_stage"] == "admission"
    assert before["failure_reason"] == "none" and before["png_width"] is None
    for _ in range(2):
        value._operation_diagnostic("job-a", stage="review_validation",
            provider="review_returned", data=png((512, 512)))
        value.record_operation_failure(TimeoutError(), request_id="job-a")
        value.update_phase("job-a", "failed")
    assert current(value, 3) == before
    value._operation_diagnostic("job-b", stage="generation")
    assert current(value, 3)["operation_stage"] == "generation"
    assert images.calls == reviews.calls == 0


def test_same_failed_job_duplicate_callbacks_never_erase_its_terminal_cause():
    value, _, _ = runtime(png())
    value._begin_operation_diagnostic("job-a", output_epoch=1, activity_seq=1)
    value.update_phase("job-a", "failed")
    value._operation_diagnostic("job-a", stage="pixel_review")
    value.record_operation_failure(ValueError("image_http_transport"), request_id="job-a")
    before = current(value)
    for _ in range(2):
        value._operation_diagnostic("job-a", stage="qualified", provider="review_returned")
        value.record_operation_failure(TimeoutError(), request_id="job-a")
    assert current(value) == before
    assert before["failure_reason"] == "image_http_transport"


@pytest.mark.asyncio
async def test_real_actor_preserves_review_metadata_across_input_and_failure():
    from tests.contracts.test_luna_tool_actor import ToolTurn, text_candidate, wait_state
    from tests.contracts.test_development_review_composition import finish

    value, images, _ = runtime(png())
    value.admission = replace(value.admission, timeout_seconds=4, authorized_custom_brief=True)
    arrived, release = asyncio.Event(), asyncio.Event()
    class Review:
        calls = 0
        async def review(self, artifact, request):
            self.calls += 1
            arrived.set()
            await release.wait()
            raise ValueError("image_http_transport")
    review = Review()
    value.vision_backend = review
    text_turns = [ToolTurn(), ToolTurn()]
    for turn in text_turns: turn.call = text_candidate()
    actor = native_actor(value, [image_turn("image"), *text_turns])
    try:
        await actor.submit(request_id="turn1", activity_seq=1, cutoff=0, text="An empty fictional lake.")
        await asyncio.wait_for(arrived.wait(), 1)
        await actor.submit(request_id="turn2", activity_seq=2, cutoff=0, text="A separate ordinary topic.")
        await finish(actor)
        reviewing = current(value)
        assert reviewing["job_state"] == "reviewing"
        assert reviewing["operation_stage"] == "pixel_review"
        assert reviewing["png_width"] == 1024 and reviewing["png_alpha"] == "opaque"
        release.set()
        await wait_state(actor, lambda s: s.story_image.state == "failed")
        await actor.submit(request_id="turn3", activity_seq=3, cutoff=0, text="Continue the ordinary topic.")
        await finish(actor)
        failed = current(value, 3)
        assert failed["job_state"] == "failed" and failed["job_origin_epoch"] == 1
        assert failed["operation_stage"] == "pixel_review"
        assert failed["failure_reason"] == "image_http_transport"
        assert failed["failure_exception"] == "value_error"
        assert failed["png_width"] == 1024 and failed["png_alpha"] == "opaque"
        assert images.calls == review.calls == 1
        assert not any(e.kind.value == "media" for e in (await actor.snapshot()).active_grants)
    finally:
        release.set()
        await actor.close()



REVIEW_CODES = (
    "subscription_review_artifact_binding", "subscription_review_checks",
    "subscription_review_content_length", "subscription_review_content_type",
    "subscription_review_encoding", "subscription_review_event",
    "subscription_review_event_limit", "subscription_review_output_limit",
    "subscription_review_decoded_limit", "subscription_review_line_limit",
    "subscription_review_http_status",
    "subscription_review_incomplete", "subscription_review_item",
    "subscription_review_not_canonical", "subscription_review_observation_binding",
    "subscription_review_request_limit", "subscription_review_response",
    "subscription_review_terminal", "subscription_review_timeout",
    "subscription_review_transport", "subscription_review_wire_limit",
)


@pytest.mark.parametrize("code", REVIEW_CODES)
def test_known_subscription_review_codes_remain_closed_payload_free_metadata(code):
    from mira.application.image_operation_diagnostics import failure_observation
    from mira.adapters.media._openai_http import ImageProviderError
    observed = failure_observation(SafeImageOperationDiagnostic(operation_stage="pixel_review"),
        ImageProviderError(code))
    assert observed.failure_reason == code
    assert observed.failure_exception == "image_provider_error"


@pytest.mark.parametrize("message", ["subscription_review_event_limit token=private",
    "subscription_review_new_unknown", "https://private.example/response?token=private"])
def test_unknown_review_exception_text_is_never_exported(message):
    from mira.application.image_operation_diagnostics import failure_observation
    observed = failure_observation(SafeImageOperationDiagnostic(operation_stage="pixel_review"),ValueError(message))
    assert observed.failure_reason == "unknown"
    assert message not in str(asdict(observed))
