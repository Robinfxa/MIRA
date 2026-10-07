"""Check configuration offline, or explicitly run one fictional subscription image job.

Run sends the fixed public lighthouse brief and its resulting PNG to OpenAI using
existing MIRA OAuth. Subscription quota consumption is unknown. This internal
compatibility route and a passed component check do not prove full scene acceptance.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'apps/api/src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'apps/api/src'))

IMAGE_MODEL = 'gpt-image-2'
# Exact local production constants only. New parser codes must be reviewed here;
# a provider/exception prefix or arbitrary metadata never expands this set.
_PROVIDER_DETAILS = frozenset({
    'image_json_duplicate', 'image_json_invalid', 'image_request_invalid',
    'image_specification_binding', 'image_subscription_auth', 'image_request_bytes',
    'image_http_timeout', 'image_http_transport', 'image_http_status',
    'image_http_content_type', 'image_http_encoding', 'image_http_content_length',
    'image_http_wire_limit', 'image_http_decoded_limit', 'image_generation_envelope',
    'image_generation_created', 'image_generation_incomplete', 'image_generation_count',
    'image_generation_resource', 'image_base64_limit', 'image_base64_invalid',
    'image_generation_bytes', 'image_png_input', 'image_png_container',
    'image_png_animation', 'image_png_header', 'image_png_dimensions', 'image_png_crc',
    'image_png_trailing', 'image_png_missing_pixels', 'image_png_truncated',
    'image_png_deflate_trailing', 'image_png_deflate_limit', 'image_png_deflate_incomplete',
    'image_png_deflate_invalid', 'image_png_decoder_tolerance', 'image_png_mode',
    'image_png_transparency', 'image_png_output_limit', 'image_png_decode',
    'subscription_review_wire_limit', 'subscription_review_content_length',
    'subscription_review_event', 'subscription_review_item', 'subscription_review_terminal',
    'subscription_review_incomplete', 'subscription_review_artifact_binding',
    'subscription_review_not_canonical', 'subscription_review_request_limit',
    'subscription_review_timeout', 'subscription_review_response',
    'subscription_review_event_limit', 'subscription_review_output_limit',
    'subscription_review_decoded_limit', 'subscription_review_line_limit',
    'subscription_review_transport', 'subscription_review_observation_binding',
    'subscription_review_checks', 'subscription_review_http_status',
    'subscription_review_content_type', 'subscription_review_encoding',
})
_RUNTIME_DETAILS = frozenset({'image_generation_invalid', 'image_decode_invalid',
                              'image_review_invalid'})


class _ArgumentsInvalid(ValueError):
    pass


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes untrusted arguments and chosen paths.
        raise _ArgumentsInvalid from None


def parse_args(argv=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='offline check only (default)')
    mode.add_argument('--run', action='store_true', help='one image and at most one pixel review')
    parser.add_argument('--review-model', help='explicit independent subscription vision model')
    parser.add_argument('--auth-store', type=Path,
        help='absolute existing MIRA OAuth store; omitted uses the normal MIRA location')
    parser.add_argument('--authorize-fiction-data-to-openai', action='store_true',
        help='acknowledge OpenAI receives the public fictional brief and generated PNG')
    parser.add_argument('--authorize-subscription-usage', action='store_true',
        help='acknowledge subscription usage with unknown quota consumption')
    args = parser.parse_args(argv)
    if (args.review_model is not None
            and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', args.review_model)):
        raise _ArgumentsInvalid
    if args.auth_store is not None and not args.auth_store.is_absolute():
        raise _ArgumentsInvalid
    return args


def make_options(args):
    from mira.bootstrap.story_image_provider import StoryImageOptions
    return StoryImageOptions(enabled=True, provider='chatgpt_subscription',
        image_model=IMAGE_MODEL, review_model=args.review_model, quality='auto',
        authorize_data_to_openai=args.authorize_fiction_data_to_openai,
        authorize_subscription_usage=args.authorize_subscription_usage,
        review_max_output_tokens=None)


def _report(model=None):
    return {'stage': 'configuration', 'code': 'configuration_only_unverified', 'detail_code': None,
        'status': 'not_run', 'route': 'chatgpt_subscription', 'image_model': IMAGE_MODEL,
        'review_model': model, 'admitted_jobs': 0, 'generation_attempts': 0,
        'review_attempts': 0, 'image_http_requests': 0, 'image_http_responses': 0,
        'image_http_status': None, 'review_http_requests': 0, 'review_http_responses': 0,
        'review_http_status': None}


class _ObservedTransport(httpx.AsyncBaseTransport):
    """Delegate one fixed-route request; retain only counters and numeric status.

No URL option, auth inspection, response body inspection or global monkeypatch.
The production transport is created lazily, with retries and environment disabled.
OAuth refresh is separately owned by the existing MIRA credential source and is
not included in these specifically named image/review HTTP counters.
"""
    def __init__(self, kind, report, delegate=None):
        if kind not in ('image', 'review'):
            raise ValueError('invalid_observer_kind')
        self._kind = kind
        self._report = report
        self._delegate = delegate
        self._closed = False

    async def handle_async_request(self, request):
        from mira.adapters.generation.direct_codex_responses import SUBSCRIPTION_ENDPOINT
        from mira.adapters.media.subscription_images import SUBSCRIPTION_IMAGE_ENDPOINT
        endpoint = SUBSCRIPTION_IMAGE_ENDPOINT if self._kind == 'image' else SUBSCRIPTION_ENDPOINT
        counter = self._kind + '_http_requests'
        if (self._closed or request.method != 'POST' or str(request.url) != endpoint
                or self._report[counter] >= 1):
            raise ValueError('component_transport_boundary')
        if self._delegate is None:
            self._delegate = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self._report[counter] += 1
        response = await self._delegate.handle_async_request(request)
        self._report[self._kind + '_http_responses'] += 1
        self._report[self._kind + '_http_status'] = response.status_code
        return response

    async def aclose(self):
        if not self._closed:
            self._closed = True
            if self._delegate is not None:
                await self._delegate.aclose()


def _credential_source(store_path):
    from mira.adapters.auth.openai_codex import CodexOAuthCredentialSource
    return CodexOAuthCredentialSource(store_path=store_path)


def _failure_code(error, report):
    # Only these known local codes are inspected; arbitrary exception text, even
    # metadata resembling a status, cannot be serialized or used to guess HTTP.
    from mira.adapters.media._openai_http import ImageProviderError
    local = error.args[0] if (type(error) is ImageProviderError and len(error.args) == 1
                             and type(error.args[0]) is str) else None
    if local == 'image_subscription_auth':
        return 'credentials_unavailable'
    if isinstance(error, (TimeoutError, httpx.TimeoutException)) or local in (
            'image_http_timeout', 'subscription_review_timeout'):
        return 'timeout'
    kind = 'review' if report['stage'] == 'review' else 'image'
    status = report[kind + '_http_status']
    if status is not None and status != 200:
        if status in (401, 403, 429):
            return {401: 'http_unauthorized', 403: 'http_forbidden', 429: 'http_rate_limited'}[status]
        return 'http_server_error' if 500 <= status <= 599 else 'http_unexpected_status'
    if report['stage'] == 'configuration':
        return 'configuration_unavailable'
    return 'review_unavailable' if kind == 'review' else 'image_unavailable'


def _detail_code(error):
    from mira.adapters.media._openai_http import ImageProviderError
    if type(error) not in (ImageProviderError, ValueError):
        return 'unknown'
    if len(error.args) != 1 or type(error.args[0]) is not str:
        return 'unknown'
    detail = error.args[0]
    if ((type(error) is ImageProviderError and detail in _PROVIDER_DETAILS)
            or (type(error) is ValueError and detail in _RUNTIME_DETAILS)):
        return detail
    return 'unknown'


async def run_check(args, *, credential_source_factory=None, image_transport=None,
                    review_transport=None, options=None):
    """Local orchestration seam. Injected transports/auth are for offline tests only."""
    report = _report(args.review_model)
    if not args.run:
        return 0, report
    if (args.authorize_fiction_data_to_openai is not True
            or args.authorize_subscription_usage is not True or not args.review_model):
        report.update(status='blocked', code='run_acknowledgements_required')
        return 2, report
    runtime = request = None
    observers = []
    code = 1
    try:
        from mira.application.story_images import compile_image_intent
        from mira.bootstrap.character_story import ephemeral_character_factory
        from mira.bootstrap.story_image_provider import create_story_image_factory
        from mira.domain.models import SessionState
        from mira.domain.story_images import ImageProposal

        selected = make_options(args)
        if options is not None:
            # The test seam may shorten the total deadline only. It cannot expand
            # any resource ceiling, provider selection, consent or content scope.
            from dataclasses import replace
            if (options != replace(selected, timeout_seconds=options.timeout_seconds)
                    or not 0 < options.timeout_seconds <= selected.timeout_seconds):
                raise ValueError('component_options_invalid')
            selected = options
        credentials = (credential_source_factory or _credential_source)(args.auth_store)
        image = _ObservedTransport('image', report, image_transport)
        review = _ObservedTransport('review', report, review_transport)
        observers = [image, review]
        factory = create_story_image_factory(options=selected, story_enabled=True,
            credential_source=credentials, image_transport=image, review_transport=review)
        state = SessionState('subscription-component-session', 'subscription-component-client')
        story = ephemeral_character_factory()(state).begin_input('subscription-component-turn', 1)
        intent = compile_image_intent(ImageProposal('authored_lighthouse_coast'), story)
        runtime = factory(state)
        runtime.bind_session(state.session_id)
        request = runtime.reserve(intent, state, request_id='subscription-component-image')
        report['admitted_jobs'] = runtime.attempts
        report.update(stage='generation', generation_attempts=1)

        async def phase(value):
            if value != 'reviewing' or report['review_attempts']:
                return False
            report.update(stage='review', review_attempts=1)
            return True

        async with asyncio.timeout(selected.timeout_seconds):
            await runtime.generate_and_review(request, phase)
        report.update(stage='complete', status='passed', code='component_passed')
        code = 0
    except asyncio.CancelledError:
        report.update(status='cancelled', code='cancelled')
        code = 130
    except Exception as error:
        report.update(status='failed', code=_failure_code(error, report),
                      detail_code=_detail_code(error))
        code = 2 if report['stage'] == 'configuration' else 1
    finally:
        # Results exist only for this component operation. Nothing is published,
        # persisted, qualified as a story event or inserted into conversation.
        if runtime is not None:
            if request is not None:
                runtime.release(request.request_id)
            runtime.close()
        for observer in observers:
            try:
                await observer.aclose()
            except asyncio.CancelledError:
                report.update(status='cancelled', code='cancelled')
                code = 130
            except Exception:
                if code == 0:
                    report.update(status='failed', code='cleanup_unavailable', detail_code='unknown')
                    code = 1
    return code, report


def main(argv=None, **injected):
    report = _report()
    try:
        args = parse_args(argv)
        code, report = asyncio.run(run_check(args, **injected))
    except _ArgumentsInvalid:
        report.update(status='blocked', code='arguments_invalid')
        code = 2
    except KeyboardInterrupt:
        report.update(status='cancelled', code='cancelled')
        code = 130
    except Exception:
        report.update(status='failed', code='configuration_unavailable', detail_code='unknown')
        code = 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
