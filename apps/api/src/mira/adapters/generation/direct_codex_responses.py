"""Provider-direct OpenAI Responses transports for MIRA candidate generation.

Both supported routes are fixed endpoints selected explicitly by the caller. The
ChatGPT Codex subscription endpoint is an undocumented/private compatibility target;
this module makes no claim that it is a public OpenAI API contract. Credentials are
injected as opaque SecretStr values, and all provider output remains an untrusted
candidate until the existing independent review/application path accepts it.
"""
from __future__ import annotations

import asyncio

from mira.application.response_preference import generation_speech_enabled
import json
import math
import re
import uuid
import zlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

import httpx

from mira.application.contracts import CandidateRange, GenerationContext
from mira.domain.errors import DomainError
from mira.application.generation_diagnostics import (
    SafeGenerationDiagnostic, SafeServiceTierDiagnostic, GENERATION_PHASES, GENERATION_REASONS, GENERATION_EVENTS,
    GENERATION_STATUSES, GENERATION_ERROR_CODES, GENERATION_ENCODINGS, GENERATION_CONTENT_TYPES,
)

from .codex_support.payload import author_instructions, build_prompt, strict_json, StrictJsonError
from .codex_support.character_payload import parse_image_character_candidate

SUBSCRIPTION_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"
OPENAI_API_ENDPOINT = "https://api.openai.com/v1/responses"
_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z")
_SAFE_HEADER_VALUE = re.compile(r"[\x21-\x7e]{1,256}\Z")
_MIME_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_MIME_QUOTED_VALUE = r'"(?:[\t\x20-\x21\x23-\x5b\x5d-\x7e]|\\[\t\x20-\x7e])*"'
_SSE_CONTENT_TYPE = re.compile(
    rf"\A[ \t]*text/event-stream[ \t]*(?:;[ \t]*{_MIME_TOKEN}[ \t]*=[ \t]*"
    rf"(?:{_MIME_TOKEN}|{_MIME_QUOTED_VALUE})[ \t]*)*\Z", re.IGNORECASE | re.ASCII)
_TOOL_ITEM_TYPES = frozenset({
    "function_call", "computer_call", "web_search_call", "file_search_call",
    "mcp_call", "code_interpreter_call", "image_generation_call", "shell_call",
})


class ResponsesRoute(StrEnum):
    """Explicit route selection; each value resolves only to a hard-coded endpoint."""

    CHATGPT_SUBSCRIPTION = "chatgpt_subscription"
    OPENAI_API = "openai_api"


def resolve_direct_service_tier(route: ResponsesRoute, model: str,
                                selection: str | None = None) -> tuple[str, str]:
    """The approved default is scoped to this exact subscription/model pair."""
    if type(route) is not ResponsesRoute:
        raise ValueError('direct_responses_route_invalid')
    if selection is not None and (type(selection) is not str
                                  or selection not in {'standard', 'fast'}):
        raise ValueError('direct_responses_service_tier_invalid')
    requested = selection or ('fast' if route is ResponsesRoute.CHATGPT_SUBSCRIPTION
                             and model == 'gpt-6-luna' else 'unspecified')
    # First-party Codex uses priority for Fast and omits explicit Standard on
    # its subscription wire. See docs/development/DIRECT_SERVICE_TIER.md.
    wire = ('priority' if requested == 'fast' else 'default' if requested == 'standard'
            and route is ResponsesRoute.OPENAI_API else 'omitted')
    return requested, wire


def _service_tier_rejected(error: object) -> bool:
    return (type(error) is dict and (error.get('param') == 'service_tier'
        or error.get('code') in ('unsupported_service_tier', 'service_tier_unsupported')))


class SecretToken(Protocol):
    """Small structural view of pydantic.SecretStr; never stringify a credential."""

    def get_secret_value(self) -> str: ...


class CredentialRecord(Protocol):
    access_token: SecretToken
    account_id: str | None
    residency: str | None


class CodexCredentialSource(Protocol):
    """Auth owner supplies credentials; the generation adapter never opens auth storage."""

    async def get_credentials(self) -> CredentialRecord: ...


@dataclass(frozen=True, slots=True)
class DirectResponsesLimits:
    startup_seconds: float = 10.0
    turn_seconds: float = 60.0
    max_line_bytes: int = 131_072
    max_wire_bytes: int = 1_048_576
    max_request_bytes: int = 131_072
    max_output_bytes: int = 16_384
    max_prompt_bytes: int = 65_536
    max_events: int = 1_024

    def __post_init__(self) -> None:
        for value in (self.startup_seconds, self.turn_seconds):
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 < value <= 120):
                raise ValueError("direct_responses_timeout_limit_invalid")
        bounds = (
            (self.max_line_bytes, 128, 262_144),
            (self.max_wire_bytes, 1_024, 4_194_304),
            (self.max_request_bytes, 1_024, 262_144),
            (self.max_output_bytes, 128, 65_536),
            (self.max_prompt_bytes, 1_024, 131_072),
            (self.max_events, 1, 4_096),
        )
        if any(type(value) is not int or not low <= value <= high
               for value, low, high in bounds):
            raise ValueError("direct_responses_size_limit_invalid")


class DirectResponsesError(DomainError):
    """Fixed safe code plus local stage/status; never contains provider strings."""

    def __init__(self, code: str, stage: str, *, http_status: int | None = None,
                 reason: str | None = None) -> None:
        super().__init__(code, code)
        self.stage = stage
        self.http_status = http_status
        self.reason = reason or stage
        self.generation_diagnostic: SafeGenerationDiagnostic | None = None


class _DirectResponseTrace:
    """Per-request bounded classes and counts; never retains provider text or IDs."""
    def __init__(self, requested_service_tier='unspecified', request_service_tier='omitted'):
        self.requested_service_tier = requested_service_tier
        self.request_service_tier = request_service_tier
        self.provider_service_tier = 'unobserved'
        self.service_tier_rejected = False
        self.http_status = None
        self.content_encoding = 'unknown'
        self.event_types = []
        self.event_count = 0
        self.terminal_status = 'none'
        self.provider_error_code = 'none'
        self.wire_bytes = 0
        self.decoded_bytes = 0
        self.content_type = 'unobserved'
        self.content_length_kind = 'unobserved'
        self.header_failure = 'none'
        self.body_kind = 'not_read'
        self.header_compatibility = 'none'
        self.terminal_facts = {}
        self.json_failure_kind = None
        self.wrapper_shape = None

    def inspect_headers(self, response, limits):
        raw_type = response.headers.get('content-type', '')
        mime = raw_type.split(';', 1)[0].strip().lower()
        self.content_type = (mime if mime in GENERATION_CONTENT_TYPES and '/' in mime else
                             'missing' if not raw_type else 'other')
        raw_length = response.headers.get('content-length')
        if raw_length is None:
            self.content_length_kind = 'missing'
        elif raw_length.isdecimal():
            self.content_length_kind = ('oversized' if len(raw_length) > 20 or
                int(raw_length) > limits.max_wire_bytes else 'valid')
        elif ',' in raw_length:
            parts = [part.strip() for part in raw_length.split(',')]
            self.content_length_kind = ('duplicate_identical' if len(set(parts)) == 1
                and parts[0].isdecimal() else 'duplicate_conflicting')
        else:
            self.content_length_kind = 'invalid'

    def observe(self, event):
        self.event_count = min(self.event_count + 1, 4097)
        kind = event.name
        obj = None
        if not kind and event.data == '[DONE]':
            kind = 'done_sentinel'
        elif not kind or kind in GENERATION_EVENTS:
            try:
                obj = strict_json(event.data)
            except RuntimeError:
                pass
            if not kind and type(obj) is dict:
                kind = obj.get('type')
        safe_kind = kind if type(kind) is str and kind in GENERATION_EVENTS else 'other'
        if safe_kind not in self.event_types:
            self.event_types.append(safe_kind)
        if type(obj) is not dict:
            return
        if safe_kind == 'response.completed':
            response = obj.get('response')
            if type(response) is dict:
                tier = response.get('service_tier')
                self.provider_service_tier = ('absent' if tier is None else
                    'invalid' if type(tier) is not str else tier if tier in
                    {'default', 'priority', 'fast', 'flex', 'scale', 'auto'} else 'unknown')
        if safe_kind in {'response.completed', 'response.failed', 'response.incomplete',
                         'response.cancelled', 'response.canceled', 'response.error', 'error'}:
            response = obj.get('response')
            status = response.get('status') if type(response) is dict else None
            fallback = safe_kind.removeprefix('response.')
            status = fallback if status is None else status
            self.terminal_status = (status if type(status) is str and status in
                                    GENERATION_STATUSES else 'other')
            error = response.get('error') if type(response) is dict else obj.get('error')
            self.service_tier_rejected = (_service_tier_rejected(error)
                or (safe_kind == 'error' and _service_tier_rejected(obj)))
            if type(error) is dict:
                code = error.get('code')
            else:
                code = obj.get('code') if safe_kind == 'error' else None
            if code is not None:
                self.provider_error_code = (code if type(code) is str and code in
                                            GENERATION_ERROR_CODES else 'other')

    def snapshot(self, error):
        return SafeGenerationDiagnostic(
            phase=error.stage if error.stage in GENERATION_PHASES else 'transport',
            reason=error.reason if error.reason in GENERATION_REASONS else 'other',
            http_status=error.http_status or self.http_status,
            content_encoding=self.content_encoding, event_types=tuple(self.event_types),
            event_count=self.event_count, terminal_status=self.terminal_status,
            provider_error_code=self.provider_error_code,
            wire_bytes=self.wire_bytes, decoded_bytes=self.decoded_bytes,
            content_type=self.content_type, content_length_kind=self.content_length_kind,
            header_failure=self.header_failure, body_kind=self.body_kind,
            header_compatibility=self.header_compatibility,
            json_failure_kind=self.json_failure_kind, wrapper_shape=self.wrapper_shape,
            requested_service_tier=self.requested_service_tier,
            request_service_tier=self.request_service_tier,
            provider_service_tier=self.provider_service_tier,
            **self.terminal_facts)


@dataclass(frozen=True, slots=True)
class _SSEEvent:
    name: str
    data: str


@dataclass(frozen=True, slots=True)
class _CompletedOutput:
    output_index: int
    item_id: str | None
    text: str
    phase: str | None = 'final_answer'


def _payload_error_code(error: RuntimeError) -> str | None:
    """Recognize only fixed local payload/parser codes; never stringify error objects."""
    try:
        args = error.args
    except Exception:
        return None
    if len(args) == 1 and type(args[0]) is str and args[0] in {
            "codex_prompt_limit", "codex_context_invalid", "codex_capability_invalid",
            "codex_output_limit", "codex_json_invalid", "codex_effects_invalid",
            "codex_effects_unsupported", "codex_character_proposal_invalid"}:
        return args[0]
    return None


class DirectCodexResponsesGenerationBackend:
    """Default-OFF, bounded provider-direct `GenerationBackend` implementation.

    `transport` is an optional HTTPX transport injection for offline tests. Omit it for
    the normal HTTPX client, which keeps TLS verification and the environment's default
    proxy/network policy. Redirects are always disabled and the destination is fixed.
    """

    def __init__(self, route: ResponsesRoute, model: str,
                 credential_source: CodexCredentialSource, *, admitted: bool = False,
                 request_limit: int | None = 0, limits: DirectResponsesLimits | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 speech_enabled: bool = True, service_tier: str | None = None,
                 native_character_tools: bool = True,
                 tier_observer: Callable[[SafeServiceTierDiagnostic], None] | None = None) -> None:
        if type(route) is not ResponsesRoute:
            raise ValueError("direct_responses_route_invalid")
        if type(model) is not str or not _MODEL_PATTERN.fullmatch(model):
            raise ValueError("direct_responses_model_invalid")
        if (credential_source is None
                or not callable(getattr(credential_source, "get_credentials", None))):
            raise ValueError("direct_responses_credentials_unavailable")
        if type(native_character_tools) is not bool:raise ValueError("native_character_tools_invalid")
        self._native_character_tools=native_character_tools
        if type(admitted) is not bool or type(speech_enabled) is not bool:
            raise ValueError("direct_responses_admission_invalid")
        if not ((request_limit is None and route is ResponsesRoute.CHATGPT_SUBSCRIPTION)
                or (type(request_limit) is int and 0 <= request_limit <= 100)):
            raise ValueError("direct_responses_request_limit_invalid")
        if limits is not None and type(limits) is not DirectResponsesLimits:
            raise ValueError("direct_responses_limits_invalid")
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise ValueError("direct_responses_transport_invalid")
        self._requested_service_tier, self._request_service_tier = resolve_direct_service_tier(
            route, model, service_tier)
        if tier_observer is not None and not callable(tier_observer):
            raise ValueError('direct_responses_tier_observer_invalid')
        self._tier_observer = tier_observer
        self._route = route
        self._endpoint = (SUBSCRIPTION_ENDPOINT if route is ResponsesRoute.CHATGPT_SUBSCRIPTION
                          else OPENAI_API_ENDPOINT)
        self._model = model
        self._credential_source = credential_source
        self._admitted = admitted
        self._remaining = request_limit
        self._reserved = 0
        self._limits = limits or DirectResponsesLimits()
        self._transport = transport
        self._speech_enabled = speech_enabled

    async def generate(self, context: GenerationContext) -> AsyncIterator[CandidateRange]:
        trace = _DirectResponseTrace(self._requested_service_tier, self._request_service_tier)
        outcome, reason = 'failed', 'other'
        try:
            async for candidate in self._generate(context, trace):
                outcome = 'completed'
                yield candidate
        except asyncio.CancelledError:
            outcome = 'cancelled'
            raise
        except DirectResponsesError as error:
            if trace.service_tier_rejected:
                error.reason = 'service_tier_rejected'
            error.generation_diagnostic = trace.snapshot(error)
            error.http_status = error.generation_diagnostic.http_status
            reason = error.generation_diagnostic.reason
            raise
        finally:
            if self._tier_observer is not None:
                try:
                    self._tier_observer(SafeServiceTierDiagnostic(
                        self._requested_service_tier, self._request_service_tier,
                        trace.provider_service_tier, outcome, reason))
                except Exception:
                    # Optional diagnostics must never convert valid content to failure.
                    pass

    async def _generate(self, context: GenerationContext,
                        trace: _DirectResponseTrace) -> AsyncIterator[CandidateRange]:
        if not self._admitted:
            raise DirectResponsesError("blocked", "admission")
        if self._remaining is not None and self._remaining <= self._reserved:
            raise DirectResponsesError("generation_budget_exhausted", "admission")

        try:
            speech_enabled = generation_speech_enabled(context, self._speech_enabled)
            prompt = build_prompt(context, self._limits, speech_enabled=speech_enabled)
        except RuntimeError as error:
            code = _payload_error_code(error)
            mapped = "input_limit" if code == "codex_prompt_limit" else "invalid_input"
            raise DirectResponsesError(mapped, "prompt") from None
        except Exception:
            raise DirectResponsesError("invalid_input", "prompt") from None

        body = {
            "model": self._model,
            "instructions": author_instructions(
                speech_enabled=speech_enabled,
                memory_enabled=context.memory_packet is not None,
                character_story_enabled=context.character_story is not None,
                story_images_enabled=bool(context.story_image_scenes),
            ),
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "store": False,
            "stream": True,
        }
        assembler = _ResponseAssembler(self._limits, trace=trace,
            subscription=self._route is ResponsesRoute.CHATGPT_SUBSCRIPTION)
        texts = await self._exchange(body, trace, assembler)
        try:
            candidates,story_proposal,affect_proposal,image_proposal = parse_image_character_candidate(
                texts,self._limits,context,speech_enabled=speech_enabled)
        except RuntimeError as error:
            if type(error) is StrictJsonError:
                trace.json_failure_kind = error.json_failure_kind
                trace.wrapper_shape = error.wrapper_shape
            code = _payload_error_code(error)
            mapped = ("output_limit" if code == "codex_output_limit"
                      else "invalid_response")
            raise DirectResponsesError(mapped, "validation", reason=code) from None
        except (ValueError, TypeError):
            # JSON decoding can succeed before canonical value validation
            # rejects a numeric overflow or an unpaired Unicode surrogate.
            # This boundary surrounds candidate parsing only; transport
            # and SSE failures keep their original stages and codes.
            raise DirectResponsesError("invalid_response", "validation",
                reason="candidate_value_invalid") from None
        yield CandidateRange(candidates, f"direct-codex-responses-origin:{uuid.uuid4().hex}",
                             story_proposal,affect_proposal,image_proposal_json=image_proposal)

    def open_tool_turn(self, context, tools):
        """Open an application-executed, ephemeral two-request turn; never execute a tool."""
        from .direct_tools import DirectToolTurn
        return DirectToolTurn(self, context, tools)

    @property
    def supports_image_completion(self):
        return self._admitted and self._native_character_tools and self._route is ResponsesRoute.CHATGPT_SUBSCRIPTION

    async def generate_image_completion(self,context):
        """One tools-disabled subscription request charged by the existing ledger."""
        if not self.supports_image_completion:raise DirectResponsesError('blocked','admission')
        turn=self.open_tool_turn(context,())
        try:return await turn.start()
        finally:turn.close()

    async def _exchange(self, body, trace, assembler):
        """Shared fixed-route transport; every attempted request consumes one allowance."""
        if not self._admitted:
            raise DirectResponsesError("blocked", "admission")
        if self._remaining is not None and self._remaining <= self._reserved:
            raise DirectResponsesError("generation_budget_exhausted", "admission")
        if self._request_service_tier != 'omitted':
            body['service_tier'] = self._request_service_tier
        try:
            request_body = json.dumps(body, ensure_ascii=False, separators=(",", ":"),
                                      allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise DirectResponsesError("invalid_input", "request") from None
        if len(request_body) > self._limits.max_request_bytes:
            raise DirectResponsesError("input_limit", "request")

        # Reserve before the first await; every attempt, including auth/transport errors,
        # consumes one admitted request. There is deliberately no retry or route fallback.
        if self._remaining is not None:
            self._remaining -= 1
        try:
            async with asyncio.timeout(self._limits.startup_seconds):
                credentials = await self._credential_source.get_credentials()
                headers = self._headers(credentials)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DirectResponsesError("timeout", "credentials") from None
        except DirectResponsesError:
            raise
        except Exception:
            raise DirectResponsesError("unauthenticated", "credentials") from None

        client_timeout = httpx.Timeout(
            connect=self._limits.startup_seconds,
            read=self._limits.turn_seconds,
            write=self._limits.startup_seconds,
            pool=self._limits.startup_seconds,
        )
        try:
            async with httpx.AsyncClient(
                    transport=self._transport, follow_redirects=False,
                    timeout=client_timeout, headers={"Accept-Encoding": "identity"}) as client:
                async with asyncio.timeout(self._limits.turn_seconds):
                    async with client.stream(
                            "POST", self._endpoint, content=request_body,
                            headers=headers) as response:
                        trace.http_status = response.status_code
                        encoding = response.headers.get('content-encoding', 'identity').strip().lower()
                        trace.content_encoding = (encoding if encoding in GENERATION_ENCODINGS
                                                  else 'other')
                        trace.inspect_headers(response, self._limits)
                        try:
                            self._check_status(response)
                        except DirectResponsesError:
                            if (self._request_service_tier != 'omitted'
                                    and response.status_code in (400, 422)):
                                await _diagnose_rejected_response(response, self._limits, trace)
                            raise
                        try:
                            self._check_content_length(response)
                            # Observed subscription replies may omit Content-Type entirely.
                            # Do not peek/consume or trust a body prefix: the original stream
                            # still must satisfy every bounded SSE/JSON/terminal/effect check.
                            missing_subscription_mime = (
                                self._route is ResponsesRoute.CHATGPT_SUBSCRIPTION
                                and response.status_code == 200
                                and str(response.request.url) == SUBSCRIPTION_ENDPOINT
                                and "content-type" not in response.headers)
                            if missing_subscription_mime:
                                trace.header_compatibility = 'subscription_missing_content_type'
                            elif not _SSE_CONTENT_TYPE.fullmatch(
                                    response.headers.get("content-type", "")):
                                reason = ('content_type_missing' if trace.content_type == 'missing'
                                    else 'content_type_parameters' if
                                    trace.content_type == 'text/event-stream' else 'content_type_unsupported')
                                raise DirectResponsesError('invalid_response', 'response_headers',
                                    http_status=response.status_code, reason=reason)
                        except DirectResponsesError as error:
                            trace.header_failure = error.reason
                            if error.stage == 'response_headers':
                                await _diagnose_rejected_response(response, self._limits, trace)
                            raise
                        async for event in _iter_sse_events(response, self._limits, trace):
                            trace.observe(event)
                            assembler.consume(event)
                        return assembler.finish()
        except asyncio.CancelledError:
            raise
        except DirectResponsesError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise DirectResponsesError("timeout", "stream") from None
        except httpx.HTTPStatusError as error:
            # Status is known and safe. The provider body and headers are not retained.
            raise DirectResponsesError("unavailable", "http_status",
                                       http_status=error.response.status_code) from None
        except httpx.HTTPError:
            raise DirectResponsesError("unavailable", "transport") from None
        except (UnicodeError, json.JSONDecodeError):
            raise DirectResponsesError("invalid_response", "sse") from None
        except Exception:
            # Never stringify network exceptions: they may include request details.
            raise DirectResponsesError("unavailable", "transport") from None


    def _headers(self, credentials: CredentialRecord) -> dict[str, str]:
        if credentials is None:
            raise DirectResponsesError("unauthenticated", "credentials")
        secret = getattr(credentials, "access_token", None)
        getter = getattr(secret, "get_secret_value", None)
        if not callable(getter):
            raise DirectResponsesError("unauthenticated", "credentials")
        try:
            token = getter()
        except Exception:
            raise DirectResponsesError("unauthenticated", "credentials") from None
        if (type(token) is not str or not token
                or any(ord(char) < 33 or ord(char) > 126 for char in token)):
            raise DirectResponsesError("unauthenticated", "credentials")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Originator": "mira",
            "User-Agent": "MIRA/0.4.1",
        }
        if self._route is ResponsesRoute.CHATGPT_SUBSCRIPTION:
            account_id = getattr(credentials, "account_id", None)
            residency = getattr(credentials, "residency", None)
            if account_id is not None:
                if type(account_id) is not str or not _SAFE_HEADER_VALUE.fullmatch(account_id):
                    raise DirectResponsesError("unauthenticated", "credentials")
                headers["ChatGPT-Account-ID"] = account_id
            if residency is not None:
                if type(residency) is not str or not _SAFE_HEADER_VALUE.fullmatch(residency):
                    raise DirectResponsesError("unauthenticated", "credentials")
                headers["x-openai-internal-codex-residency"] = residency
        return headers

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 300:
            return
        if status == 401:
            code, stage = "unauthenticated", "auth"
        elif status == 403:
            code, stage = "permission_denied", "authorization"
        elif status == 429:
            code, stage = "quota_exhausted", "quota"
        elif status in (408, 504):
            code, stage = "timeout", "http_status"
        elif status in (400, 422):
            code, stage = "invalid_input", "http_status"
        elif 300 <= status < 400:
            code, stage = "unavailable", "redirect"
        elif status >= 500:
            code, stage = "unavailable", "http_status"
        else:
            code, stage = "invalid_response", "http_status"
        raise DirectResponsesError(code, stage, http_status=status)

    def _check_content_length(self, response: httpx.Response) -> None:
        raw = response.headers.get("content-length")
        if raw is None:
            return
        if not raw.isdecimal():
            raise DirectResponsesError("invalid_response", "response_headers",
                                       http_status=response.status_code, reason='content_length_invalid')
        if len(raw) > 20 or int(raw) > self._limits.max_wire_bytes:
            raise DirectResponsesError("response_limit", "sse",
                                       http_status=response.status_code, reason='content_length_limit')


async def _diagnose_rejected_response(response, limits, trace):
    """Classify at most 16 KiB/0.5s in memory; never accept it as generated output.

    This is a same-response read, not a retry. Only closed classes reach diagnostics.
    Malformed/unknown MIME never bypasses the SSE content-type requirement.
    """
    body = bytearray()
    budget = replace(limits, max_wire_bytes=min(limits.max_wire_bytes, 16384))
    try:
        async with asyncio.timeout(0.5):
            async for chunk in _iter_decoded_bytes(response, budget, trace):
                body.extend(chunk)
                prefix = bytes(body[:256]).lstrip().lower()
                if prefix.startswith((b'<!doctype html', b'<html')):
                    trace.body_kind = 'html'
                    return
                if prefix.startswith((b'event:', b'data:', b':')):
                    trace.body_kind = 'sse_like'
                    return
        if not body:
            trace.body_kind = 'empty'
            return
        try:
            obj = strict_json(bytes(body))
        except RuntimeError:
            trace.body_kind = 'other'
            return
        trace.body_kind = 'json_other'
        if type(obj) is not dict:
            return
        error = obj.get('error')
        if error is not None:
            trace.body_kind = 'json_error'
            trace.service_tier_rejected = _service_tier_rejected(error)
            code = error.get('code') if type(error) is dict else obj.get('code')
            if code is not None:
                trace.provider_error_code = (code if type(code) is str and code in
                                             GENERATION_ERROR_CODES else 'other')
        elif obj.get('object') == 'response' and type(obj.get('output')) is list:
            trace.body_kind = 'json_response'
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        trace.body_kind = 'read_timeout'
    except DirectResponsesError as error:
        trace.body_kind = 'truncated' if error.code == 'response_limit' else 'decode_failed'
    except Exception:
        trace.body_kind = 'read_failed'


async def _iter_decoded_bytes(response: httpx.Response, limits: DirectResponsesLimits,
                              trace: _DirectResponseTrace | None = None) -> AsyncIterator[bytes]:
    """Decode raw HTTP content exactly once with independent wire/decoded byte caps.

    Accept-Encoding: identity is a preference, not proof of an identity response.
    zlib's max_length bounds decompression itself, unlike an unbounded decode followed
    by a size check. No compressed trailer, extra member or truncated stream is ignored.
    """
    encoding = response.headers.get('content-encoding', 'identity').strip().lower()
    if encoding not in {'identity', 'gzip', 'deflate'}:
        raise DirectResponsesError('invalid_response', 'response_headers',
                                   reason='content_encoding')
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == 'gzip' else None
    prefix = b''
    wire_bytes = decoded_bytes = 0
    async for chunk in response.aiter_raw():
        wire_bytes += len(chunk)
        if trace is not None:
            trace.wire_bytes = min(wire_bytes, 4194305)
        if wire_bytes > limits.max_wire_bytes:
            raise DirectResponsesError('response_limit', 'sse', reason='wire_limit')
        if not chunk:
            continue
        if encoding == 'deflate' and decoder is None:
            prefix += chunk
            if len(prefix) < 2:
                continue
            # RFC zlib wrapper or the de-facto raw deflate form also handled by HTTPX.
            wrapped = (prefix[0] & 15 == 8 and (prefix[0] >> 4) <= 7
                       and int.from_bytes(prefix[:2], 'big') % 31 == 0)
            decoder = zlib.decompressobj(zlib.MAX_WBITS if wrapped else -zlib.MAX_WBITS)
            chunk, prefix = prefix, b''
        try:
            decoded = (chunk if encoding == 'identity' else
                       decoder.decompress(chunk, limits.max_wire_bytes - decoded_bytes + 1))
        except zlib.error:
            raise DirectResponsesError('invalid_response', 'sse', reason='content_decode') from None
        decoded_bytes += len(decoded)
        if trace is not None:
            trace.decoded_bytes = min(decoded_bytes, 4194305)
        if decoded_bytes > limits.max_wire_bytes:
            raise DirectResponsesError('response_limit', 'sse', reason='decoded_limit')
        if decoder is not None and (decoder.unused_data or decoder.unconsumed_tail):
            raise DirectResponsesError('invalid_response', 'sse', reason='content_decode')
        if decoded:
            yield decoded
    if encoding != 'identity' and (decoder is None or not decoder.eof):
        raise DirectResponsesError('invalid_response', 'sse', reason='content_decode')


async def _iter_sse_events(response: httpx.Response,
                           limits: DirectResponsesLimits,
                           trace: _DirectResponseTrace | None = None) -> AsyncIterator[_SSEEvent]:
    """Incrementally decode bounded UTF-8 SSE records, including CR/LF and multiline data."""
    pending = bytearray()
    data_lines: list[str] = []
    event_name = ""
    event_count = 0
    wire_bytes = 0
    first_line = True

    def process_line(raw: bytes) -> None:
        nonlocal event_name, first_line
        if len(raw) > limits.max_line_bytes:
            raise DirectResponsesError("response_limit", "sse", reason='line_limit')
        try:
            line = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise DirectResponsesError("invalid_response", "sse", reason="utf8") from None
        if first_line:
            first_line = False
            if line.startswith("\ufeff"):
                line = line[1:]
        if not line:
            return
        if line.startswith(":"):
            return
        field, separator, value = line.partition(":")
        if not separator:
            value = ""
        elif value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        elif field == "event":
            # Event names are opaque until dispatch; the line bound constrains storage.
            event_name = value

    def dispatch() -> _SSEEvent | None:
        nonlocal event_name, event_count, data_lines
        if not data_lines and not event_name:
            return None
        event_count += 1
        if event_count > limits.max_events:
            raise DirectResponsesError("response_limit", "sse", reason='event_limit')
        event = _SSEEvent(event_name, "\n".join(data_lines))
        event_name = ""
        data_lines = []
        return event

    async for chunk in _iter_decoded_bytes(response, limits, trace):
        wire_bytes += len(chunk)
        if wire_bytes > limits.max_wire_bytes:
            raise DirectResponsesError("response_limit", "sse", reason='decoded_limit')
        pending.extend(chunk)
        while True:
            lf = pending.find(b"\n")
            cr = pending.find(b"\r")
            separators = [index for index in (lf, cr) if index >= 0]
            if not separators:
                if len(pending) > limits.max_line_bytes:
                    raise DirectResponsesError("response_limit", "sse", reason='line_limit')
                break
            index = min(separators)
            if pending[index] == 13 and index == len(pending) - 1:
                if index > limits.max_line_bytes:
                    raise DirectResponsesError("response_limit", "sse", reason='line_limit')
                break
            raw_line = bytes(pending[:index])
            delim_size = 2 if pending[index] == 13 and pending[index + 1] == 10 else 1
            del pending[:index + delim_size]
            process_line(raw_line)
            if not raw_line:
                emitted = dispatch()
                if emitted is not None:
                    yield emitted

    if pending:
        if pending.endswith(b"\r"):
            raw_line = bytes(pending[:-1])
        else:
            raw_line = bytes(pending)
        process_line(raw_line)
        pending.clear()
    if data_lines or event_name:
        emitted = dispatch()
        if emitted is not None:
            yield emitted


class _ResponseAssembler:
    """Private bounded state: done message items win; deltas are fallback only."""

    _JSON_EVENT_NAMES = frozenset({
        "response.output_item.done", "response.output_item.added",
        "response.output_text.delta", "response.completed", "response.failed",
        "response.incomplete", "response.cancelled", "response.canceled",
        "response.error", "error",
    })
    _FAILURE_EVENTS = frozenset({"response.failed", "response.error", "error"})
    _INCOMPLETE_EVENTS = frozenset({
        "response.incomplete", "response.cancelled", "response.canceled",
    })

    def __init__(self, limits: DirectResponsesLimits, *, trace=None, subscription=False) -> None:
        self._limits = limits
        self._trace = trace
        self._subscription = subscription
        self._phases = {}
        self._announced_messages = set()
        self._reasoning_count = 0
        self._completed: dict[int, _CompletedOutput] = {}
        self._deltas: dict[int, dict[int, str]] = {}
        self._delta_ids: dict[int, str] = {}
        self._terminal = False
        self._failed = False
        self._done_sentinel_seen = False

    def _sync_trace(self):
        if self._trace is not None:
            self._trace.terminal_facts.update(
                completed_message_count=min(len(self._completed),4097),
                completed_reasoning_count=min(self._reasoning_count,4097),
                delta_message_count=min(len(self._deltas),4097),
                unmatched_delta_count=min(len(set(self._deltas)-set(self._completed)),4097),
                completed_text_bytes=min(sum(len(v.text.encode('utf-8')) for v in self._completed.values()),4194305))

    def _inspect_snapshot(self, response):
        if self._trace is None:
            return
        facts = self._trace.terminal_facts
        output = response.get('output')
        facts['snapshot_output_kind'] = ('omitted' if 'output' not in response else
            'null' if output is None else 'empty' if type(output) is list and not output else
            'list' if type(output) is list else 'other')
        if type(output) is not list:
            return
        facts['snapshot_item_count'] = min(len(output),4097)
        types, statuses, phases = [], [], []
        messages = reasoning = text_bytes = 0
        for item in output[:4097]:
            if type(item) is not dict:
                kind, status = 'other', 'other'
            else:
                raw = item.get('type')
                kind = raw if raw in ('message','reasoning') else 'tool' if type(raw) is str and raw in _TOOL_ITEM_TYPES else 'other'
                raw_status = item.get('status')
                status = 'none' if raw_status is None else raw_status if type(raw_status) is str and raw_status in ('completed','in_progress','incomplete') else 'other'
                messages += kind == 'message'
                reasoning += kind == 'reasoning'
                if kind == 'message':
                    raw_phase = item.get('phase')
                    phase = 'none' if raw_phase is None else raw_phase if type(raw_phase) is str and raw_phase in ('commentary','final_answer') else 'other'
                    if phase not in phases: phases.append(phase)
                    content = item.get('content')
                    if type(content) is list:
                        for part in content[:4097]:
                            if type(part) is dict and type(part.get('text')) is str:
                                text_bytes += len(part['text'].encode('utf-8'))
            if kind not in types: types.append(kind)
            if status not in statuses: statuses.append(status)
        facts.update(snapshot_message_count=messages,snapshot_reasoning_count=reasoning,
                     snapshot_item_types=tuple(types),snapshot_item_statuses=tuple(statuses),
                     snapshot_message_phases=tuple(phases),snapshot_text_bytes=min(text_bytes,4194305))

    def consume(self, sse: _SSEEvent) -> None:
        self._sync_trace()
        if self._done_sentinel_seen:
            raise DirectResponsesError("invalid_response", "terminal")
        if not sse.name and sse.data == "[DONE]":
            if not self._terminal:
                raise DirectResponsesError("invalid_response", "terminal")
            self._done_sentinel_seen = True
            return
        kind = sse.name
        obj: object | None = None
        if kind in self._JSON_EVENT_NAMES or not kind:
            try:
                obj = strict_json(sse.data)
            except RuntimeError:
                # Unknown named metadata events are opaque and deliberately discarded.
                if kind and kind not in self._JSON_EVENT_NAMES:
                    return
                raise DirectResponsesError("invalid_response", "sse", reason="json_shape") from None
            if not kind:
                if type(obj) is not dict or type(obj.get("type")) is not str:
                    return
                kind = obj["type"]
            if kind not in self._JSON_EVENT_NAMES and kind not in (
                    "response.created", "response.in_progress", "response.queued",
                    "response.output_text.done", "response.content_part.added",
                    "response.content_part.done", "response.refusal.delta",
                    "response.refusal.done", "response.reasoning_summary_text.delta",
                    "response.reasoning_summary_text.done", "response.reasoning_text.delta",
                    "response.reasoning_text.done", "response.output_text.annotation.added"):
                # Future event types may carry benign metadata. Count/bytes stay bounded,
                # and no event is allowed to create a candidate without a known text event.
                return
        else:
            # Opaque named events do not need a JSON shape and are safely discarded.
            return

        if type(obj) is not dict:
            raise DirectResponsesError("invalid_response", "sse")
        data_type = obj.get("type")
        if type(data_type) is str and kind in self._JSON_EVENT_NAMES and data_type != kind:
            raise DirectResponsesError("invalid_response", "sse")
        if self._terminal and kind in (
                "response.output_item.added", "response.output_item.done",
                "response.output_text.delta", "response.completed", "response.failed",
                "response.incomplete", "response.cancelled", "response.canceled",
                "response.error", "error"):
            raise DirectResponsesError("invalid_response", "terminal")
        if kind in self._FAILURE_EVENTS:
            self._failed = True
            raise DirectResponsesError("unavailable", "provider")
        if kind in self._INCOMPLETE_EVENTS:
            self._failed = True
            raise DirectResponsesError("invalid_response", "terminal")
        if kind == "response.output_item.added":
            item = obj.get("item")
            if type(item) is dict and type(item.get("type")) is str and item["type"] in _TOOL_ITEM_TYPES:
                raise DirectResponsesError("invalid_response", "tool_forbidden")
            if type(item) is dict and item.get('type') == 'message':
                index = self._output_index(obj.get('output_index'))
                if index in self._announced_messages or index in self._completed:
                    raise DirectResponsesError('invalid_response','output_item',reason='duplicate_output_item')
                self._announced_messages.add(index)
                phase = self._message_phase(item, stage='output_item')
                if item.get('phase') is not None:
                    self._phases[index] = phase
            return
        if kind == "response.output_text.delta":
            self._consume_delta(obj)
            return
        if kind == "response.output_item.done":
            self._consume_completed_item(obj)
            return
        if kind == "response.completed":
            if self._terminal:
                raise DirectResponsesError("invalid_response", "terminal")
            response_data = obj.get("response")
            if type(response_data) is not dict:
                raise DirectResponsesError("invalid_response", "terminal")
            self._inspect_snapshot(response_data)
            status = response_data.get("status")
            if status in ("failed", "error"):
                raise DirectResponsesError("unavailable", "provider")
            if status == "incomplete":
                raise DirectResponsesError("invalid_response", "terminal")
            if status not in (None, "completed"):
                raise DirectResponsesError("invalid_response", "terminal")
            if response_data.get("error") is not None:
                raise DirectResponsesError("unavailable", "provider")
            output = response_data.get('output')
            if type(output) is list and not output and self._subscription:
                # First-party Codex emits an empty redundant terminal snapshot after
                # authoritative output_item.done messages. Never synthesize missing done items.
                if not self._completed:
                    raise DirectResponsesError('invalid_response','terminal_output',
                                               reason='empty_snapshot_without_completed')
                self._assembled_candidate_text()
                if self._trace is not None:
                    self._trace.terminal_facts['terminal_compatibility'] = 'subscription_empty_output'
            elif output is not None:
                snapshot_messages = self._terminal_snapshot_messages(output)
                streamed = self._assembled_messages()
                texts_equal = [m.text for m in snapshot_messages] == [m.text for m in streamed]
                phases_equal = len(snapshot_messages) == len(streamed) and all(
                    snapshot.phase is None or snapshot.phase == actual.phase
                    for snapshot,actual in zip(snapshot_messages,streamed))
                equal = texts_equal and phases_equal
                if self._trace is not None:
                    self._trace.terminal_facts['snapshot_matches_stream'] = equal
                if len(snapshot_messages) != len(streamed):
                    raise DirectResponsesError('invalid_response','terminal_output',reason='snapshot_message_count')
                if not equal:
                    raise DirectResponsesError('invalid_response','terminal_output',
                        reason='snapshot_phase_mismatch' if texts_equal else 'snapshot_text_mismatch')
            self._terminal = True
            return

    def _consume_delta(self, obj: dict) -> None:
        index = self._output_index(obj.get("output_index"))
        if index in self._completed:
            raise DirectResponsesError('invalid_response','output_item',reason='late_delta_after_done')
        content_index = obj.get("content_index", 0)
        if (type(content_index) is not int or content_index < 0 or content_index > 1_000_000
                or type(obj.get("delta")) is not str):
            raise DirectResponsesError("invalid_response", "sse")
        item_id = obj.get("item_id")
        if item_id is not None:
            self._check_item_id(item_id)
            old_id = self._delta_ids.setdefault(index, item_id)
            if old_id != item_id:
                raise DirectResponsesError("invalid_response", "sse")
        parts = self._deltas.setdefault(index, {})
        parts[content_index] = parts.get(content_index, "") + obj["delta"]
        size = sum(len(part.encode("utf-8")) for groups in self._deltas.values()
                   for part in groups.values())
        if size > self._limits.max_output_bytes:
            raise DirectResponsesError("output_limit", "sse")

    def _consume_completed_item(self, obj: dict) -> None:
        index = self._output_index(obj.get("output_index"))
        item = obj.get("item")
        if type(item) is not dict:
            raise DirectResponsesError("invalid_response", "sse")
        if item.get("type") == "reasoning":
            self._validate_reasoning_item(item, stage="output_item")
            self._reasoning_count += 1
            return
        full_text = self._message_item_text(item, stage="output_item")
        item_id = item.get("id")
        if item_id is not None:
            self._check_item_id(item_id)
            delta_id = self._delta_ids.get(index)
            if delta_id is not None and delta_id != item_id:
                raise DirectResponsesError("invalid_response", "output_item")
        if index in self._completed:
            raise DirectResponsesError("invalid_response", "output_item")
        if item_id is not None and any(old.item_id == item_id for old in self._completed.values()):
            raise DirectResponsesError('invalid_response','output_item',reason='message_id_reused')
        phase = self._message_phase(item, stage='output_item')
        if item.get('phase') is None:
            phase = self._phases.get(index, phase)
        if index in self._phases and self._phases[index] != phase:
            raise DirectResponsesError('invalid_response','output_item',reason='message_phase_mismatch')
        if index in self._deltas:
            delta_text = ''.join(self._deltas[index][part] for part in sorted(self._deltas[index]))
            if delta_text != full_text:
                raise DirectResponsesError('invalid_response','output_item',reason='delta_done_text_mismatch')
        self._completed[index] = _CompletedOutput(index, item_id, full_text, phase)
        if sum(len(v.text.encode('utf-8')) for v in self._completed.values()) > self._limits.max_output_bytes:
            raise DirectResponsesError('output_limit','output_item',reason='message_total_limit')

    def _terminal_snapshot_messages(self, output: object) -> list[_CompletedOutput]:
        if type(output) is not list:
            raise DirectResponsesError('invalid_response','terminal_output',reason='snapshot_output_shape')
        if len(output) > self._limits.max_events:
            raise DirectResponsesError('response_limit','terminal_output')
        messages = []
        for index,item in enumerate(output):
            if type(item) is not dict:
                raise DirectResponsesError('invalid_response','terminal_output',reason='snapshot_item_shape')
            if item.get('type') == 'reasoning':
                self._validate_reasoning_item(item, stage='terminal_output')
                continue
            text = self._message_item_text(item, stage='terminal_output')
            messages.append(_CompletedOutput(index,item.get('id'),text,
                                             self._message_phase(item,stage='terminal_output')
                                             if item.get('phase') is not None else None))
        if not messages:
            raise DirectResponsesError('invalid_response','terminal_output',reason='snapshot_message_count')
        return messages

    @staticmethod
    def _message_phase(item, *, stage):
        phase = item.get('phase')
        if phase not in (None,'commentary','final_answer'):
            raise DirectResponsesError('invalid_response',stage,reason='message_phase')
        return phase or 'final_answer'

    def _message_item_text(self, item: dict, *, stage: str) -> str:
        item_type = item.get("type")
        if type(item_type) is str and item_type in _TOOL_ITEM_TYPES:
            raise DirectResponsesError("invalid_response", "tool_forbidden")
        if item_type != "message":
            raise DirectResponsesError("invalid_response", stage, reason='message_type')
        if item.get("role") not in (None, "assistant"):
            raise DirectResponsesError("invalid_response", stage, reason='message_role')
        if item.get("status") not in (None, "completed"):
            raise DirectResponsesError('invalid_response', stage, reason='message_status')
        item_id = item.get("id")
        if item_id is not None:
            self._check_item_id(item_id)
        content = item.get("content")
        if type(content) is not list:
            raise DirectResponsesError('invalid_response', stage, reason='message_content_shape')
        if len(content) > self._limits.max_events:
            raise DirectResponsesError("response_limit", stage)
        texts = []
        for part in content:
            if type(part) is not dict:
                raise DirectResponsesError('invalid_response', stage, reason='message_part_shape')
            if part.get("type") != "output_text" or type(part.get("text")) is not str:
                raise DirectResponsesError('invalid_response', stage, reason='message_part_type')
            texts.append(part["text"])
        full_text = "".join(texts)
        if not full_text:
            raise DirectResponsesError('invalid_response', stage, reason='message_text_empty')
        if len(full_text.encode("utf-8")) > self._limits.max_output_bytes:
            raise DirectResponsesError("output_limit", stage)
        return full_text

    def _validate_reasoning_item(self, item: dict, *, stage: str) -> None:
        """Validate known non-candidate reasoning structure, without retaining its text."""
        if item.get("status") not in (None, "completed"):
            raise DirectResponsesError('invalid_response', stage, reason='reasoning_status')
        item_id = item.get("id")
        if item_id is not None:
            self._check_item_id(item_id)
        encrypted_content = item.get("encrypted_content")
        if encrypted_content is not None and type(encrypted_content) is not str:
            raise DirectResponsesError('invalid_response', stage, reason='reasoning_encrypted_shape')
        for field, allowed_types in (
                ("summary", frozenset({"summary_text"})),
                ("content", frozenset({"reasoning_text", "summary_text"}))):
            parts = item.get(field)
            if parts is None:
                continue
            if type(parts) is not list:
                raise DirectResponsesError('invalid_response', stage, reason='reasoning_parts_shape')
            if len(parts) > self._limits.max_events:
                raise DirectResponsesError("response_limit", stage)
            for part in parts:
                if (type(part) is not dict or (type(part.get("type")) is not str or part["type"] not in allowed_types)
                        or type(part.get("text")) is not str):
                    raise DirectResponsesError('invalid_response', stage, reason='reasoning_part_shape')

    def _assembled_messages(self) -> list[_CompletedOutput]:
        if self._completed:
            if set(self._deltas) - set(self._completed):
                raise DirectResponsesError('invalid_response','terminal_output',reason='unmatched_delta')
            return [self._completed[index] for index in sorted(self._completed)]
        if not self._deltas:
            raise DirectResponsesError('invalid_response','terminal_output',reason='candidate_missing')
        return [_CompletedOutput(index,self._delta_ids.get(index),
                    ''.join(self._deltas[index][part] for part in sorted(self._deltas[index])),
                    self._phases.get(index,'final_answer')) for index in sorted(self._deltas)]

    def _assembled_candidate_text(self) -> str:
        text = ''.join(item.text for item in self._assembled_messages() if item.phase != 'commentary')
        if not text:
            raise DirectResponsesError('invalid_response','output_missing',reason='candidate_missing')
        if len(text.encode('utf-8')) > self._limits.max_output_bytes:
            raise DirectResponsesError('output_limit','validation')
        return text

    @staticmethod
    def _output_index(value: object) -> int:
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise DirectResponsesError("invalid_response", "sse")
        return value

    @staticmethod
    def _check_item_id(value: object) -> None:
        if (type(value) is not str or not value or len(value) > 256
                or any(ord(char) < 33 or ord(char) > 126 for char in value)):
            raise DirectResponsesError("invalid_response", "sse")

    def finish(self) -> list[str]:
        self._sync_trace()
        if not self._terminal:
            raise DirectResponsesError('invalid_response','incomplete_stream')
        if self._failed:
            raise DirectResponsesError('invalid_response','terminal')
        # Preserve one strict application JSON document after protocol-level message assembly.
        return [self._assembled_candidate_text()]
