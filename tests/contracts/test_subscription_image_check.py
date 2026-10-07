"""Local command contracts: production runtime/parsers, fake auth, mock HTTP only."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import httpx
from pydantic import SecretStr
import pytest

from tools import check_subscription_image as check
from tests.contracts.test_story_image_adapters import ByteStream, png

MODEL = 'gpt-vision-synthetic-snapshot'
SENTINEL = 'PRIVATE_SENTINEL_NEVER_PRINT_84da'
RUN = ['--run', '--review-model', MODEL, '--authorize-fiction-data-to-openai',
       '--authorize-subscription-usage']


def cli_main(argv, **injected):
    # A standalone CLI owns its thread's loop policy. Running its asyncio.run()
    # on pytest's main thread would detach the loop pytest-asyncio restores there.
    # Keep injection-based CLI tests isolated; async business tests await run_check.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(check.main, argv, **injected).result()


class Credentials:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    async def get_credentials(self):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(access_token=SecretStr('synthetic-token-' + SENTINEL),
                               account_id=SENTINEL, residency=None)


def image_response(*, status=200, data=None):
    body = {'created': 123, 'data': [{'b64_json': base64.b64encode(
        png(metadata=True) if data is None else data).decode()}], 'metadata': SENTINEL}
    return httpx.Response(status, headers={'content-type': 'application/json',
        'x-test-secret': SENTINEL}, stream=ByteStream([json.dumps(body).encode()]))


def review_response(request, *, result='pass', status=200, mutation=None):
    body = json.loads(request.content)
    text, image = body['input'][0]['content']
    criteria = json.loads(text['text'])
    pixels = base64.b64decode(image['image_url'].split(',')[1], validate=True)
    assert pixels.startswith(b'\x89PNG\r\n\x1a\n') and b'private_metadata' not in pixels
    assert sha256(pixels).hexdigest() == criteria['checked_content_digest']
    doc = {key: criteria[key] for key in ('request_id', 'specification_digest',
                                        'checked_content_digest', 'policy_revision')}
    doc.update(checks={key: result for key in criteria['required_checks']},
               observed_description=SENTINEL)
    doc.update(mutation or {})
    item = {'type': 'message', 'id': 'msg-check', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': json.dumps(doc)}]}
    events = [('response.output_item.done', {'output_index': 0, 'item': item}),
              ('response.completed', {'response': {'status': 'completed', 'model': MODEL,
                                                   'output': [item], 'metadata': SENTINEL}})]
    data = b''.join(('event: ' + kind + '\ndata: ' + json.dumps({'type': kind, **value})
                     + '\n\n').encode() for kind, value in events)
    return httpx.Response(status, headers={'content-type': 'text/event-stream'},
                          stream=ByteStream([data]))


def invoke(capsys, *, argv=None, image=None, review=None, source=None):
    source = source or Credentials()
    seen = []
    def generate(request):
        seen.append(request)
        return image(request) if image else image_response()
    def inspect(request):
        seen.append(request)
        return review(request) if review else review_response(request)
    code = cli_main(RUN if argv is None else argv, credential_source_factory=lambda _: source,
        image_transport=httpx.MockTransport(generate), review_transport=httpx.MockTransport(inspect))
    captured = capsys.readouterr()
    assert not captured.err and SENTINEL not in captured.out
    report = json.loads(captured.out)
    assert set(report) == {'stage', 'code', 'detail_code', 'status', 'route', 'image_model', 'review_model',
        'admitted_jobs', 'generation_attempts', 'review_attempts',
        'image_http_requests', 'image_http_responses', 'image_http_status',
        'review_http_requests', 'review_http_responses', 'review_http_status'}
    return code, report, source, seen


def test_default_check_never_constructs_auth_or_transport(capsys):
    def forbidden(*args, **kwargs):
        pytest.fail('check-only constructed credentials')
    assert cli_main([], credential_source_factory=forbidden) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'not_run' and report['code'] == 'configuration_only_unverified'
    assert report['admitted_jobs'] == report['image_http_requests'] == 0


@pytest.mark.parametrize('argv', [
    ['--run'], ['--run', '--review-model', MODEL],
    ['--run', '--review-model', MODEL, '--authorize-fiction-data-to-openai'],
    ['--run', '--review-model', MODEL, '--authorize-subscription-usage'],
    RUN + ['--auth-store', 'relative/' + SENTINEL],
    RUN + ['--prompt', SENTINEL], RUN + ['--review-model', SENTINEL + '/bad'],
])
def test_no_consent_or_bad_arguments_make_zero_calls(capsys, argv):
    code, report, source, seen = invoke(capsys, argv=argv)
    assert code == 2 and report['status'] == 'blocked'
    assert source.calls == len(seen) == report['admitted_jobs'] == 0


def test_auth_failure_has_no_http_or_review(capsys):
    code, report, source, seen = invoke(capsys, source=Credentials(RuntimeError(SENTINEL)))
    assert code == 1 and report['code'] == 'credentials_unavailable'
    assert source.calls == report['admitted_jobs'] == report['generation_attempts'] == 1
    assert not seen and report['image_http_requests'] == report['review_attempts'] == 0


@pytest.mark.parametrize('status', [401, 403, 429, 500, 503])
def test_generation_http_failure_stops_before_review(capsys, status):
    code, report, source, seen = invoke(capsys, image=lambda _: image_response(status=status))
    assert code == 1 and report['stage'] == 'generation'
    assert report['image_http_status'] == status
    assert report['image_http_requests'] == report['image_http_responses'] == 1
    assert source.calls == len(seen) == 1 and report['review_attempts'] == 0


@pytest.mark.parametrize('data', [b'not-png', b'\x89PNG\r\n\x1a\nmalformed', png(width=2)])
def test_malformed_image_is_never_reviewed(capsys, data):
    code, report, source, seen = invoke(capsys, image=lambda _: image_response(data=data))
    assert code == 1 and report['code'] == 'image_unavailable'
    assert report['image_http_status'] == 200 and report['review_attempts'] == 0
    assert source.calls == len(seen) == 1


@pytest.mark.parametrize('result', ['unknown', 'unassessable', 'fail'])
def test_unknown_or_failed_pixel_review_is_not_success(capsys, result):
    code, report, source, seen = invoke(capsys,
        review=lambda request: review_response(request, result=result))
    assert code == 1 and report['code'] == 'review_unavailable'
    assert report['stage'] == 'review' and report['status'] == 'failed'
    assert len(seen) == source.calls == 2 and report['review_http_status'] == 200


def test_success_is_exactly_one_fixed_image_and_one_actual_png_review(capsys):
    code, report, source, seen = invoke(capsys)
    assert code == 0 and report['status'] == 'passed' and report['code'] == 'component_passed'
    assert report['stage'] == 'complete' and report['admitted_jobs'] == 1
    assert report['generation_attempts'] == report['review_attempts'] == 1
    assert report['image_http_requests'] == report['review_http_requests'] == 1
    assert report['image_http_responses'] == report['review_http_responses'] == 1
    assert len(seen) == source.calls == 2
    assert [str(request.url) for request in seen] == [
        'https://chatgpt.com/backend-api/codex/images/generations',
        'https://chatgpt.com/backend-api/codex/responses']
    generation = json.loads(seen[0].content)
    assert generation['n'] == 1 and generation['model'] == 'gpt-image-2'
    assert 'lighthouse' in generation['prompt'] and 'No people' in generation['prompt']
    assert json.loads(seen[1].content)['model'] == MODEL


@pytest.mark.parametrize('error', [RuntimeError(SENTINEL), ValueError(SENTINEL),
                                  httpx.ReadTimeout(SENTINEL)])
def test_transport_exceptions_are_closed_safe_and_never_retry(capsys, error):
    def fail(_):
        raise error
    code, report, source, seen = invoke(capsys, image=fail)
    assert code == 1 and report['image_http_requests'] == 1
    assert report['image_http_responses'] == 0 and report['image_http_status'] is None
    assert report['review_attempts'] == 0 and len(seen) == source.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_stage', ['generation', 'review'])
async def test_cancellation_has_no_extra_requests(cancel_stage):
    entered = asyncio.Event()
    source = Credentials()
    async def block(request):
        entered.set()
        await asyncio.Event().wait()
    image = httpx.MockTransport(block if cancel_stage == 'generation' else lambda _: image_response())
    review = httpx.MockTransport(block)
    args = check.parse_args(RUN)
    task = asyncio.create_task(check.run_check(args, credential_source_factory=lambda _: source,
        image_transport=image, review_transport=review))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    code, report = await asyncio.wait_for(task, 2)
    assert code == 130 and report['status'] == 'cancelled'
    assert report['image_http_requests'] == 1
    assert report['review_http_requests'] == (cancel_stage == 'review')
    assert report['review_attempts'] == (cancel_stage == 'review')


@pytest.mark.asyncio
async def test_total_timeout_has_no_retry_or_review():
    entered = asyncio.Event()
    async def block(request):
        entered.set()
        await asyncio.Event().wait()
    options = replace(check.make_options(check.parse_args(RUN)), timeout_seconds=0.03)
    code, report = await check.run_check(check.parse_args(RUN),
        credential_source_factory=lambda _: Credentials(), image_transport=httpx.MockTransport(block),
        review_transport=httpx.MockTransport(lambda _: pytest.fail('unexpected review')),
        options=options)
    assert entered.is_set() and code == 1 and report['code'] == 'timeout'
    assert report['image_http_requests'] == 1 and report['review_attempts'] == 0


def test_cli_exit_codes_and_default_do_not_depend_on_credentials():
    script = Path(check.__file__)
    for arguments, expected in (([], 0), (['--run'], 2), (['--unknown', SENTINEL], 2)):
        result = subprocess.run([sys.executable, str(script), *arguments],
            capture_output=True, text=True, timeout=5, check=False)
        assert result.returncode == expected and not result.stderr
        assert SENTINEL not in result.stdout
        report = json.loads(result.stdout)
        assert report['image_http_requests'] == report['review_http_requests'] == 0


def test_png_failure_reports_a_closed_specific_detail(capsys):
    code, report, _, _ = invoke(capsys, image=lambda _: image_response(data=png(width=2)))
    assert code == 1 and report.get('detail_code') == 'image_png_dimensions'


@pytest.mark.parametrize('mode,detail', [
    ('json', 'image_json_invalid'), ('count', 'image_generation_count'),
    ('base64', 'image_base64_invalid'), ('encoding', 'image_http_encoding'),
])
def test_http_200_image_parser_details_are_specific_and_safe(capsys, mode, detail):
    raw = b'{not-json-' + SENTINEL.encode()
    headers = {'content-type': 'application/json'}
    if mode == 'count':
        raw = json.dumps({'created': 123, 'data': [], 'metadata': SENTINEL}).encode()
    elif mode == 'base64':
        raw = json.dumps({'created': 123, 'data': [{'b64_json': '!' + SENTINEL}]}).encode()
    elif mode == 'encoding':
        headers['content-encoding'] = 'br'
    code, report, _, seen = invoke(capsys, image=lambda _: httpx.Response(200,
        headers=headers, stream=ByteStream([raw])))
    assert code == 1 and report['code'] == 'image_unavailable' and report['detail_code'] == detail
    assert len(seen) == 1 and report['image_http_status'] == 200


@pytest.mark.parametrize('mode,detail', [
    ('event', 'subscription_review_event'), ('binding', 'subscription_review_observation_binding'),
    ('event_limit', 'subscription_review_event_limit'),
    ('checks', 'subscription_review_checks'), ('rejected', 'image_review_invalid'),
])
def test_http_200_review_parser_details_are_specific_and_safe(capsys, mode, detail):
    def reply(request):
        if mode == 'event_limit':
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                stream=ByteStream([b'data:{"type":"response.created"}\n\n' * 1025]))
        if mode == 'event':
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                stream=ByteStream([b'data: {"type":"' + SENTINEL.encode() + b'"}\n\n']))
        return review_response(request,
            result='unknown' if mode == 'checks' else 'fail' if mode == 'rejected' else 'pass',
            mutation={'request_id': SENTINEL} if mode == 'binding' else None)
    code, report, _, seen = invoke(capsys, review=reply)
    assert code == 1 and report['code'] == 'review_unavailable' and report['detail_code'] == detail
    assert len(seen) == 2 and report['review_http_status'] == 200


@pytest.mark.parametrize('prefix', ['image_json_invalid', 'image_png_decode',
                                   'subscription_review_observation_binding'])
def test_exception_prefix_is_not_a_detail_allowlist(capsys, prefix):
    from mira.adapters.media._openai_http import ImageProviderError
    def hostile(_):
        raise ImageProviderError(prefix + ':' + SENTINEL)
    code, report, _, seen = invoke(capsys, image=hostile)
    assert code == 1 and report['detail_code'] == 'unknown' and len(seen) == 1
    assert report['image_http_status'] is None
    assert check._detail_code(RuntimeError(prefix)) == 'unknown'
    assert check._detail_code(ValueError(prefix)) == 'unknown'


@pytest.mark.parametrize('mode', ['check', 'missing_consent', 'success', 'auth_failure', 'cancelled'])
def test_sync_cli_harness_preserves_pytest_policy_loop(capsys, mode):
    class TrackedPolicy(asyncio.DefaultEventLoopPolicy):
        def __init__(self):
            super().__init__()
            self.created = []

        def new_event_loop(self):
            loop = super().new_event_loop()
            self.created.append((loop, threading.current_thread()))
            return loop

    previous_policy = asyncio.get_event_loop_policy()
    policy = TrackedPolicy()
    outside_loop = policy.new_event_loop()
    policy.set_event_loop(outside_loop)
    asyncio.set_event_loop_policy(policy)
    try:
        argv = [] if mode == 'check' else ['--run'] if mode == 'missing_consent' else RUN
        source = Credentials(RuntimeError(SENTINEL)) if mode == 'auth_failure' else Credentials()
        if mode == 'cancelled':
            source = Credentials(asyncio.CancelledError())
        code, _, _, _ = invoke(capsys, argv=argv, source=source)
        assert code == {'check': 0, 'missing_consent': 2, 'success': 0,
                       'auth_failure': 1, 'cancelled': 130}[mode]
        assert policy.get_event_loop() is outside_loop
        assert not outside_loop.is_closed()
        owned = [(loop, owner) for loop, owner in policy.created if loop is not outside_loop]
        assert len(owned) == 1
        assert owned[0][0].is_closed()
        assert owned[0][1] is not threading.current_thread() and not owned[0][1].is_alive()
    finally:
        outside_loop.close()
        asyncio.set_event_loop_policy(previous_policy)
