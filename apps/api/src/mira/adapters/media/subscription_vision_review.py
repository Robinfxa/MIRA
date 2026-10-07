"""Independent pixel review over the private Codex subscription compatibility route.

Only the already generated canonical PNG and bounded fictional criteria are sent.
No API credential, route fallback, tool, auth discovery or remote token-cap claim.
Live entitlement and review quality are not established by these offline contracts.
"""
import asyncio
import base64
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re

import httpx

from mira.adapters.generation.direct_codex_responses import (
    CodexCredentialSource, DirectResponsesError, DirectResponsesLimits,
    SUBSCRIPTION_ENDPOINT, _ResponseAssembler, _SSE_CONTENT_TYPE, _iter_sse_events,
)
from mira.application.ports.media import (
    MediaArtifact, MediaRequest, MediaReviewObservation, PixelCheck,
)
from mira.domain.story_images import REQUIRED_PIXEL_CHECKS

from ._openai_http import (
    ImageProviderError, MODEL_PATTERN, PNG_SIGNATURE, RequestFence,
    bounded_text, strict_json, validate_request,
)
from ._subscription_auth import subscription_headers
from .openai_vision_review import _bindings, _CHECK_MEANINGS, _INSTRUCTIONS, _schema
from .png_decoder import PillowPngDecoder
from mira.domain.story_images import image_output_dimensions

_METADATA_EVENTS = frozenset({
    'response.created', 'response.in_progress', 'response.queued',
    'response.output_text.done', 'response.content_part.added', 'response.content_part.done',
    'response.reasoning_summary_text.delta', 'response.reasoning_summary_text.done',
    'response.reasoning_text.delta', 'response.reasoning_text.done',
    'response.reasoning_summary_part.added', 'response.reasoning_summary_part.done',
    'codex.response.metadata', 'response.metadata', 'responsesapi.websocket_timing',
})
_ALLOWED_EVENTS = _METADATA_EVENTS | _ResponseAssembler._JSON_EVENT_NAMES


@dataclass(frozen=True, slots=True)
class SubscriptionVisionOptions:
    model: str

    def __post_init__(self):
        if type(self.model) is not str or not MODEL_PATTERN.fullmatch(self.model):
            raise ValueError('subscription_review_model_invalid')


class _FencedStream(httpx.AsyncByteStream):
    """Fence every byte await and cleanup without changing the shared SSE parser."""
    def __init__(self, stream, fence, expected_length, maximum):
        self._stream = stream
        self._fence = fence
        self._expected_length = expected_length
        self._maximum = maximum

    async def __aiter__(self):
        count = 0
        async for part in self._stream:
            self._fence.check()
            count += len(part)
            if count > self._maximum:
                raise ImageProviderError('subscription_review_wire_limit')
            yield part
        self._fence.check()
        if self._expected_length is not None and count != self._expected_length:
            raise ImageProviderError('subscription_review_content_length')

    async def aclose(self):
        await self._stream.aclose()
        self._fence.check()


class _ReviewCollector:
    """Stricter review envelope around the existing independently tested assembler."""
    def __init__(self, limits):
        self._assembler = _ResponseAssembler(limits, subscription=True)
        self._message_count = 0
        self._terminal = False

    def consume(self, event):
        if not event.name and event.data == '[DONE]':
            self._assembler.consume(event)
            return
        value = strict_json(event.data)
        if type(value) is not dict or type(value.get('type')) is not str:
            raise ImageProviderError('subscription_review_event')
        kind = event.name or value['type']
        if kind != value['type'] or kind not in _ALLOWED_EVENTS:
            raise ImageProviderError('subscription_review_event')
        if kind in ('response.output_item.added', 'response.output_item.done'):
            item = value.get('item')
            if type(item) is not dict or item.get('type') not in ('message', 'reasoning'):
                raise ImageProviderError('subscription_review_item')
            if item['type'] == 'message':
                if kind == 'response.output_item.done':
                    self._message_count += 1
        if kind == 'response.completed':
            body = value.get('response')
            if (type(body) is not dict
                    or body.get('error') is not None or body.get('incomplete_details') is not None
                    or not self._message_count):
                raise ImageProviderError('subscription_review_terminal')
            self._terminal = True
        self._assembler.consume(event)

    def finish(self):
        if not self._terminal or not self._message_count:
            raise ImageProviderError('subscription_review_incomplete')
        return self._assembler.finish()[0]


class SubscriptionVisionReviewBackend:
    """One explicitly composed independent review; admission belongs to the caller."""
    def __init__(self, *, credential_source: CodexCredentialSource,
                 options: SubscriptionVisionOptions,
                 transport: httpx.AsyncBaseTransport | None = None,
                 timeout_seconds: float = 45.0, max_wire_bytes: int = 65_536):
        if not isinstance(options, SubscriptionVisionOptions):
            raise ValueError('subscription_review_options_required')
        if not callable(getattr(credential_source, 'get_credentials', None)):
            raise ValueError('subscription_review_credentials_required')
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 120):
            raise ValueError('subscription_review_timeout_invalid')
        if type(max_wire_bytes) is not int or not 1024 <= max_wire_bytes <= 65_536:
            raise ValueError('subscription_review_wire_limit_invalid')
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise ValueError('subscription_review_transport_invalid')
        self.options = options
        self._credentials = credential_source
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._limits = DirectResponsesLimits(
            max_line_bytes=min(16_384, max_wire_bytes), max_wire_bytes=max_wire_bytes,
            # Small strict JSON may arrive as hundreds of valid text deltas.
            # Keep the shared bounded event budget and independent byte ceilings.
            max_output_bytes=8192, max_events=1024,
        )

    async def review(self, artifact: MediaArtifact, request: MediaRequest) -> MediaReviewObservation:
        fence = RequestFence(self._timeout_seconds)
        fence.check()
        validate_request(request, subscription=True)
        allowed_sizes = image_output_dimensions(request.output_dimension_policy)
        if (not isinstance(artifact, MediaArtifact) or type(artifact.png) is not bytes
                or not artifact.png.startswith(PNG_SIGNATURE)
                or not 1 <= len(artifact.png) <= request.max_output_bytes
                or artifact.media_type != 'image/png'
                or type(artifact.width) is not int or type(artifact.height) is not int
                or (artifact.width, artifact.height) not in allowed_sizes
                or artifact.request_id != request.request_id
                or artifact.specification_digest != request.specification_digest
                or artifact.policy_revision != request.policy_revision
                or artifact.content_digest != sha256(artifact.png).hexdigest()):
            raise ImageProviderError('subscription_review_artifact_binding')
        canonical = PillowPngDecoder(max_bytes=request.max_output_bytes,
            output_dimension_policy=request.output_dimension_policy).canonicalize(artifact.png)
        if (canonical.png != artifact.png
                or (canonical.width, canonical.height) != (artifact.width, artifact.height)):
            raise ImageProviderError('subscription_review_not_canonical')
        bindings = _bindings(artifact, request)
        text = json.dumps({**bindings, 'specification': request.specification,
            'image_dimensions': {'width': artifact.width, 'height': artifact.height},
            'required_checks': _CHECK_MEANINGS, 'response_schema': _schema(bindings)}, ensure_ascii=False)
        body = {
            'model': self.options.model, 'instructions': _INSTRUCTIONS,
            'tools': [], 'store': False, 'stream': True,
            'input': [{'role': 'user', 'content': [
                {'type': 'input_text', 'text': text},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,'
                    + base64.b64encode(artifact.png).decode('ascii')},
            ]}],
        }
        encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        # The direct text request limit is deliberately not applied to PNG input.
        if len(encoded) > 4 * ((request.max_output_bytes + 2) // 3) + 32_768:
            raise ImageProviderError('subscription_review_request_limit')
        fence.check()
        collector = _ReviewCollector(self._limits)
        try:
            async with asyncio.timeout_at(fence.deadline) as timeout:
                fence.timeout = timeout
                headers = await subscription_headers(self._credentials, fence=fence)
                fence.check()
                headers.update({'Content-Type': 'application/json', 'Accept': 'text/event-stream',
                                'Accept-Encoding': 'identity'})
                async with httpx.AsyncClient(
                    transport=self._transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(self._timeout_seconds, connect=min(10, self._timeout_seconds)),
                ) as client:
                    fence.check()
                    async with client.stream('POST', SUBSCRIPTION_ENDPOINT,
                                             content=encoded, headers=headers) as response:
                        fence.check()
                        expected_length = self._check_headers(response)
                        response.stream = _FencedStream(response.stream, fence, expected_length,
                                                        self._limits.max_wire_bytes)
                        async for event in _iter_sse_events(response, self._limits):
                            fence.check()
                            collector.consume(event)
                        fence.check()
                    fence.check()
                fence.check()
            fence.check()
        except asyncio.CancelledError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            fence.check()
            raise ImageProviderError('subscription_review_timeout') from None
        except ImageProviderError:
            fence.check()
            raise
        except DirectResponsesError as error:
            fence.check()
            limit_reason = {
                'event_limit': 'subscription_review_event_limit',
                'wire_limit': 'subscription_review_wire_limit',
                'decoded_limit': 'subscription_review_decoded_limit',
                'line_limit': 'subscription_review_line_limit',
            }.get(error.reason) if error.code == 'response_limit' else None
            if error.code == 'output_limit':
                limit_reason = 'subscription_review_output_limit'
            raise ImageProviderError(limit_reason or 'subscription_review_response') from None
        except httpx.HTTPError:
            fence.check()
            raise ImageProviderError('subscription_review_response') from None
        except Exception:
            fence.check()
            raise ImageProviderError('subscription_review_transport') from None
        try:
            observed = strict_json(collector.finish())
        except (DirectResponsesError, RuntimeError):
            raise ImageProviderError('subscription_review_incomplete') from None
        fields = {*bindings, 'checks', 'observed_description'}
        if (type(observed) is not dict or set(observed) != fields
                or any(observed[key] != value for key, value in bindings.items())
                or not bounded_text(observed['observed_description'], 512, empty=True)):
            raise ImageProviderError('subscription_review_observation_binding')
        checks = observed['checks']
        if (type(checks) is not dict or set(checks) != set(REQUIRED_PIXEL_CHECKS)
                or any(type(value) is not str or value not in ('pass', 'fail', 'unassessable')
                       for value in checks.values())):
            raise ImageProviderError('subscription_review_checks')
        fence.check()
        return MediaReviewObservation(**bindings,
            checks=tuple(PixelCheck(key, checks[key]) for key in REQUIRED_PIXEL_CHECKS),
            observed_description=observed['observed_description'])

    def _check_headers(self, response):
        if response.status_code != 200:
            raise ImageProviderError('subscription_review_http_status')
        missing_subscription_mime = ('content-type' not in response.headers
                                     and str(response.request.url) == SUBSCRIPTION_ENDPOINT)
        if not missing_subscription_mime and not _SSE_CONTENT_TYPE.fullmatch(
                response.headers.get('content-type', '')):
            raise ImageProviderError('subscription_review_content_type')
        if response.headers.get('content-encoding', 'identity').strip().lower() not in (
                'identity', 'gzip', 'deflate'):
            raise ImageProviderError('subscription_review_encoding')
        length = response.headers.get('content-length')
        if length is not None and (not re.fullmatch(r'[0-9]{1,9}', length)
                or int(length) > self._limits.max_wire_bytes):
            raise ImageProviderError('subscription_review_content_length')
        return int(length) if length is not None else None
