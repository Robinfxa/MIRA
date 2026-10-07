"""Exact Gemini 3.8 Flash TTS on Gemini Enterprise, with injected authentication.

No legacy Cloud TTS endpoint, Developer API key, SDK discovery, or fallback. Output
is PCM16 LE mono at 24 kHz, never WAV bytes mislabeled as PCM. Caller owns playback.
"""
import asyncio
import base64
import binascii
import json
import re
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mira.adapters.speech.errors import (
    ProviderErrorDetails, SafeAudioDiagnostic, SpeechProviderError, parse_provider_error_details,
    close_stream,
    http_error,
    raise_if_cancelled,
    safe_error,
)
from mira.application.ports.media import AudioPacket

PREBUILT_VOICES = frozenset({
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam", "Aoede", "Autonoe", "Callirrhoe",
    "Charon", "Despina", "Enceladus", "Erinome", "Fenrir", "Gacrux", "Iapetus", "Kore",
    "Laomedeia", "Leda", "Orus", "Puck", "Pulcherrima", "Rasalgethi", "Sadachbia",
    "Sadaltager", "Schedar", "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr", "Zubenelgenubi",
})
MODEL = "gemini-3.8-flash-tts"
SAMPLE_RATE_HZ = 24000


@dataclass(frozen=True, slots=True)
class GeminiTtsOptions:
    project_id: str
    voice: str
    model: str = MODEL
    location: str = "global"
    style: str | None = None
    timeout_seconds: float = 60
    max_text_characters: int = 16000
    max_audio_samples: int = 24000 * 180
    capture_provider_text_diagnostics: bool = False

    def __post_init__(self):
        if not isinstance(self.project_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", self.project_id):
            raise ValueError("Invalid Google project identifier")
        if self.model != MODEL or self.location != "global":
            raise ValueError("Only exact Gemini 3.8 Flash TTS in global is supported")
        if not isinstance(self.voice, str) or self.voice not in PREBUILT_VOICES:
            raise ValueError("Select an explicitly supported prebuilt voice")
        if self.style is not None and (not isinstance(self.style, str) or not self.style.strip() or len(self.style) > 1000):
            raise ValueError("Speech style must be bounded nonblank text")
        if type(self.capture_provider_text_diagnostics) is not bool:
            raise ValueError("Text diagnostic capture must be explicitly enabled or disabled")
        if not 0 < self.timeout_seconds <= 300 or not 0 < self.max_text_characters <= 32000 or not 0 < self.max_audio_samples <= 24000 * 300:
            raise ValueError("TTS requires bounded request and audio limits")

    @property
    def url(self) -> str:
        return (f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/global/"
                f"publishers/google/models/{MODEL}:streamGenerateContent?alt=sse")


class GeminiTtsTransport(Protocol):
    def stream(self, *, url: str, body: dict[str, Any], timeout_seconds: float
               ) -> AsyncGenerator[dict[str, Any], None]: ...


class GoogleGeminiTtsBackend:
    def __init__(self, options: GeminiTtsOptions, transport: GeminiTtsTransport):
        self.options, self.transport = options, transport

    async def synthesize(self, approved_text: str, stream_id: str) -> AsyncGenerator[AudioPacket, None]:
        if (not isinstance(approved_text, str) or not approved_text.strip()
                or len(approved_text) > self.options.max_text_characters
                or not isinstance(stream_id, str) or not stream_id):
            raise SpeechProviderError("invalid_input")
        part: dict[str, Any] = {"text": approved_text}
        if self.options.style is not None:
            part["speechMetadata"] = {"style": self.options.style}
        body = {"contents": [{"role": "user", "parts": [part]}], "generationConfig": {
            "responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"voice": self.options.voice}},
            "responseFormat": [{"audio": {"mimeType": "AUDIO_L16"}}]}}
        raise_if_cancelled()
        stream = self.transport.stream(url=self.options.url, body=body,
                                       timeout_seconds=self.options.timeout_seconds)
        sample_cursor, stopped = 0, False
        last_non_audio_details: SafeAudioDiagnostic | None = None
        try:
            async for chunk in stream:
                raise_if_cancelled()
                if not isinstance(chunk, dict):
                    raise SpeechProviderError("invalid_response")
                feedback = chunk.get("promptFeedback", {})
                if not isinstance(feedback, dict):
                    raise SpeechProviderError("invalid_response")
                if feedback.get("blockReason"):
                    raise SpeechProviderError("blocked")
                candidates = chunk.get("candidates", [])
                if not isinstance(candidates, list) or len(candidates) > 1:
                    raise SpeechProviderError("invalid_response")
                if not candidates:
                    continue  # Usage-only or empty metadata events carry no sound.
                candidate = candidates[0]
                if not isinstance(candidate, dict):
                    raise SpeechProviderError("invalid_response")
                finish = candidate.get("finishReason")
                if finish and finish != "STOP":
                    raise SpeechProviderError(
                        "blocked" if finish in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"} else "incomplete_stream",
                        audio_details=self._safe_audio_details(
                            {}, None, finish, model_version=chunk.get("modelVersion"),
                            usage_metadata=chunk.get("usageMetadata"),
                            capture_text=self.options.capture_provider_text_diagnostics,
                            approved_text=approved_text, project_id=self.options.project_id,
                        ),
                    )
                content = candidate.get("content", {})
                if not isinstance(content, dict) or not isinstance(content.get("parts", []), list):
                    raise SpeechProviderError("invalid_response")
                for part_index, response_part in enumerate(content.get("parts", [])):
                    if not isinstance(response_part, dict):
                        raise SpeechProviderError("invalid_response")
                    if "inlineData" not in response_part:
                        # The documented streaming sample emits only inline audio.
                        # Other parts never become dialogue or sound. Keep bounded
                        # facts for a later empty/failed stream, not the raw part.
                        last_non_audio_details = self._safe_audio_details(
                                response_part, part_index, finish,
                                model_version=chunk.get("modelVersion"),
                                usage_metadata=chunk.get("usageMetadata"),
                                response_text=response_part.get("text"),
                                capture_text=self.options.capture_provider_text_diagnostics,
                                approved_text=approved_text, project_id=self.options.project_id,
                            )
                        continue
                    if stopped:
                        raise SpeechProviderError("invalid_response")
                    try:
                        pcm = self._decode_pcm(response_part["inlineData"])
                    except SpeechProviderError as error:
                        raise SpeechProviderError(error.code, audio_details=self._safe_audio_details(
                            response_part, part_index, finish,
                            model_version=chunk.get("modelVersion"),
                            usage_metadata=chunk.get("usageMetadata"),
                            response_text=response_part.get("text"),
                            capture_text=self.options.capture_provider_text_diagnostics,
                            approved_text=approved_text, project_id=self.options.project_id,
                        )) from None
                    if not pcm:
                        continue
                    if sample_cursor + len(pcm) // 2 > self.options.max_audio_samples:
                        raise SpeechProviderError("output_limit")
                    raise_if_cancelled()
                    yield AudioPacket(stream_id, sample_cursor, SAMPLE_RATE_HZ, pcm)
                    sample_cursor += len(pcm) // 2
                stopped = stopped or finish == "STOP"
            if not sample_cursor:
                raise SpeechProviderError("empty_audio", audio_details=last_non_audio_details)
            if not stopped:
                raise SpeechProviderError("incomplete_stream")
        except Exception as error:
            safe = safe_error(error)
            if safe.audio_details is None and last_non_audio_details is not None:
                safe = SpeechProviderError(safe.code, details=safe.details,
                                          audio_details=last_non_audio_details)
            raise safe from None
        finally:
            await close_stream(stream, preserve_error=sys.exc_info()[0] is not None)

    @staticmethod
    def _decode_pcm(inline: Any) -> bytes:
        if not isinstance(inline, dict) or not isinstance(inline.get("mimeType"), str):
            raise SpeechProviderError("invalid_response")
        mime = inline["mimeType"].lower().replace(" ", "").split(";")
        if mime[0] != "audio/l16" or any(p not in {"codec=pcm", "rate=24000", "channels=1"} for p in mime[1:]):
            raise SpeechProviderError("unsupported_audio")
        encoded = inline.get("data")
        if not isinstance(encoded, str) or len(encoded) > 2 * 1024 * 1024:
            raise SpeechProviderError("invalid_audio")
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise SpeechProviderError("invalid_audio") from None
        if len(pcm) % 2 or (pcm[:4] == b"RIFF" and pcm[8:12] == b"WAVE"):
            raise SpeechProviderError("invalid_audio")
        return pcm

    @staticmethod
    def _safe_audio_details(part: dict[str, Any], part_index: int | None,
                            finish_reason: Any = None, *, model_version: Any = None,
                            usage_metadata: Any = None, response_text: Any = None,
                            capture_text: bool = False, approved_text: str | None = None,
                            project_id: str | None = None) -> SafeAudioDiagnostic:
        """Keep only allowlisted metadata and decode facts; never retain audio bytes."""
        from mira.adapters.speech.errors import _SAFE_PART_TYPES, _SAFE_FINISH_REASONS, _SAFE_MEDIA_MIME

        part_types = tuple(sorted(key for key in part if key in _SAFE_PART_TYPES))[:8]
        inline = part.get("inlineData") if isinstance(part, dict) else None
        mime_type = None
        params: list[str] = []
        sample_rate = channels = None
        codec = None
        data_chars = None
        validation_reason = None
        pcm_byte_count = None
        wav_header = None
        if isinstance(inline, dict):
            mime = inline.get("mimeType")
            mime_tokens: list[str] = []
            if isinstance(mime, str):
                mime_tokens = mime.lower().replace(" ", "").split(";")
                candidate = mime_tokens[0]
                if _SAFE_MEDIA_MIME.fullmatch(candidate):
                    mime_type = candidate
                for token in mime_tokens[1:]:
                    if "=" not in token:
                        continue
                    key, value = token.split("=", 1)
                    if key not in {"codec", "rate", "channels"}:
                        continue
                    if key not in params:
                        params.append(key)
                    if key == "rate" and value.isdigit():
                        rate = int(value)
                        if 1000 <= rate <= 384000:
                            sample_rate = rate
                    elif key == "channels" and value.isdigit():
                        channel_count = int(value)
                        if 1 <= channel_count <= 8:
                            channels = channel_count
                    elif key == "codec":
                        codec = value if value in {"pcm", "alaw", "mulaw"} else "unknown"
            encoded = inline.get("data")
            if isinstance(encoded, str) and len(encoded) <= 2 * 1024 * 1024:
                data_chars = len(encoded)
            if not isinstance(mime, str):
                validation_reason = "unsupported_mime_type"
            elif mime_tokens[0] != "audio/l16":
                validation_reason = "unsupported_mime_type"
            elif any(p not in {"codec=pcm", "rate=24000", "channels=1"}
                     for p in mime_tokens[1:]):
                validation_reason = "unsupported_mime_parameter"
            elif not isinstance(encoded, str):
                validation_reason = "missing_audio_data"
            elif len(encoded) > 2 * 1024 * 1024:
                validation_reason = "audio_data_too_large"
            else:
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    validation_reason = "invalid_base64"
                else:
                    pcm_byte_count = len(decoded)
                    wav_header = decoded[:4] == b"RIFF" and decoded[8:12] == b"WAVE"
                    if wav_header:
                        validation_reason = "wav_header"
                    elif len(decoded) % 2:
                        validation_reason = "odd_pcm_bytes"
        elif "inlineData" not in part:
            validation_reason = "non_audio_part"
        safe_finish = finish_reason if isinstance(finish_reason, str) and finish_reason in _SAFE_FINISH_REASONS else None
        safe_model_version = (model_version if isinstance(model_version, str)
                              and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", model_version) else None)
        usage = usage_metadata if isinstance(usage_metadata, dict) else {}
        input_tokens = GoogleGeminiTtsBackend._safe_token_count(usage.get("promptTokenCount"))
        output_tokens = GoogleGeminiTtsBackend._safe_token_count(usage.get("candidatesTokenCount"))
        total_tokens = GoogleGeminiTtsBackend._safe_token_count(usage.get("totalTokenCount"))
        excerpt = (GoogleGeminiTtsBackend._safe_synthetic_response_excerpt(
            response_text, approved_text=approved_text, project_id=project_id,
        ) if capture_text else None)
        return SafeAudioDiagnostic(
            part_index=part_index, part_type_names=part_types, mime_type=mime_type,
            mime_param_names=tuple(params), sample_rate_hz=sample_rate, channels=channels,
            codec=codec, audio_data_chars=data_chars, candidate_finish_reason=safe_finish,
            validation_reason=validation_reason, pcm_byte_count=pcm_byte_count, wav_header=wav_header,
            model_version=safe_model_version, input_token_count=input_tokens,
            output_token_count=output_tokens, total_token_count=total_tokens,
            response_text_excerpt=excerpt,
        )

    @staticmethod
    def _safe_token_count(value: Any) -> int | None:
        return value if type(value) is int and 0 <= value <= 1_000_000 else None

    @staticmethod
    def _safe_synthetic_response_excerpt(value: Any, *, approved_text: str | None,
                                         project_id: str | None) -> str | None:
        """Redact bounded provider text for this fixed synthetic smoke only."""
        if not isinstance(value, str) or not value:
            return None
        excerpt = value[:2048]
        if approved_text:
            excerpt = excerpt.replace(approved_text, "[synthetic-prompt-redacted]")
        if project_id and len(project_id) >= 3:
            excerpt = re.sub(re.escape(project_id), "[project-id-redacted]", excerpt, flags=re.I)
        redactions = (
            (r"(?i)\bbearer\s+[^\s,;]+", "[credential-redacted]"),
            (r"\bya29\.[A-Za-z0-9._~+/-]+", "[credential-redacted]"),
            (r"\bAIza[A-Za-z0-9_-]{20,}", "[credential-redacted]"),
            (r"(?i)\b(?:access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|password|api[_ -]?key)\b\s*[:=]\s*[^\s,;]+", "[credential-redacted]"),
            (r"(?i)https?://[^\s]+", "[url-redacted]"),
            (r"\b(?:projects|locations|publishers|models|endpoints|recognizers)/[A-Za-z0-9_.-]+", "[resource-redacted]"),
            (r"\b[A-Za-z0-9_-]{40,}\b", "[opaque-value-redacted]"),
        )
        for pattern, replacement in redactions:
            excerpt = re.sub(pattern, replacement, excerpt)
        excerpt = "".join(ch if ch in "\t\n\r" or ord(ch) >= 32 else " " for ch in excerpt)
        excerpt = excerpt[:512]
        return excerpt or None


class GoogleGeminiTtsRestTransport:
    """Injected authenticated async HTTP client, such as a configured httpx client.

    Bootstrap owns OAuth refresh, credentials, proxies and client's lifetime.
    Per-request redirect following is forbidden. No raw body/header is logged.
    """
    def __init__(self, client: Any, *, token_provider: Callable[[], Awaitable[str]] | None = None,
                 quota_project_id: str | None = None,
                 max_event_bytes: int = 2 * 1024 * 1024,
                 max_response_bytes: int = 32 * 1024 * 1024):
        if not 1 <= max_event_bytes <= max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("Invalid response bounds")
        if quota_project_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", quota_project_id):
            raise ValueError("Invalid quota project identifier")
        self._client = client
        self._token_provider, self._quota_project_id = token_provider, quota_project_id
        self._max_event_bytes, self._max_response_bytes = max_event_bytes, max_response_bytes

    async def stream(self, *, url: str, body: dict[str, Any], timeout_seconds: float
                     ) -> AsyncGenerator[dict[str, Any], None]:
        if not re.fullmatch(r"https://aiplatform\.googleapis\.com/v1/projects/[A-Za-z0-9_-]+/locations/global/publishers/google/models/gemini-3\.8-flash-tts:streamGenerateContent\?alt=sse", url):
            raise SpeechProviderError("invalid_input")
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        try:
            headers = {"Accept": "text/event-stream", "Accept-Encoding": "identity"}
            if self._token_provider is not None:
                async with asyncio.timeout_at(deadline):
                    token = await self._token_provider()
                if (not isinstance(token, str) or not token or len(token) > 16384
                        or any(character.isspace() for character in token)):
                    raise SpeechProviderError("unauthenticated")
                headers["Authorization"] = f"Bearer {token}"
            if self._quota_project_id is not None:
                headers["X-Goog-User-Project"] = self._quota_project_id
            async with self._client.stream("POST", url, json=body, headers=headers,
                                           timeout=timeout_seconds,
                                           follow_redirects=False) as response:
                if response.status_code != 200:
                    remaining = max(0.001, deadline - asyncio.get_running_loop().time())
                    try:
                        async with asyncio.timeout(remaining):
                            details = await self._read_provider_error(response, response.status_code)
                    except TimeoutError:
                        details = ProviderErrorDetails(
                            http_status=response.status_code, body_capture_status="timeout",
                        )
                    raise http_error(response.status_code, details=details)
                if response.headers.get("content-type", "").split(";", 1)[0].lower() != "text/event-stream":
                    raise SpeechProviderError("invalid_response")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise SpeechProviderError("invalid_response")
                events = self._events(response.aiter_bytes())
                try:
                    while True:
                        try:
                            # The timeout context must end BEFORE yielding: otherwise its
                            # callback could cancel unrelated consumer work between packets.
                            async with asyncio.timeout_at(deadline):
                                event = await anext(events)
                        except StopAsyncIteration:
                            break
                        raise_if_cancelled()
                        yield event
                finally:
                    await close_stream(events, preserve_error=sys.exc_info()[0] is not None)
        except Exception as error:
            raise safe_error(error) from None

    async def _read_provider_error(self, response: Any, status: int) -> ProviderErrorDetails:
        """Read at most 8 KiB and retain only allowlisted provider error facts."""
        body = bytearray()
        truncated = False
        try:
            async for chunk in response.aiter_bytes():
                if not isinstance(chunk, bytes):
                    return parse_provider_error_details(status, bytes(body), truncated=truncated,
                                                        capture_status="unavailable")
                remaining = 8192 - len(body)
                if len(chunk) > remaining:
                    body.extend(chunk[:remaining])
                    truncated = True
                    break
                body.extend(chunk)
                if len(body) >= 8192:
                    truncated = True
                    break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            name = type(error).__name__.lower()
            capture_status = "timeout" if "timeout" in name else "unavailable"
            return parse_provider_error_details(status, bytes(body), truncated=truncated,
                                                capture_status=capture_status)
        return parse_provider_error_details(status, bytes(body), truncated=truncated)

    async def _events(self, chunks: AsyncIterator[bytes]) -> AsyncGenerator[dict[str, Any], None]:
        pending = bytearray()
        data_lines: list[str] = []
        total, event_bytes = 0, 0
        async for chunk in chunks:
            raise_if_cancelled()
            total += len(chunk)
            if total > self._max_response_bytes:
                raise SpeechProviderError("response_limit")
            pending.extend(chunk)
            while b"\n" in pending:
                raw, _, tail = pending.partition(b"\n")
                pending = bytearray(tail)
                event_bytes += len(raw) + 1
                if event_bytes > self._max_event_bytes:
                    raise SpeechProviderError("response_limit")
                try:
                    line = raw.rstrip(b"\r").decode("utf-8")
                except UnicodeDecodeError:
                    raise SpeechProviderError("invalid_response") from None
                if line == "":
                    if data_lines:
                        yield self._parse_event("\n".join(data_lines))
                    data_lines, event_bytes = [], 0
                elif line.startswith("data:"):
                    data_lines.append(line[5:].removeprefix(" "))
                elif line.startswith(":") or line.startswith(("event:", "id:", "retry:")):
                    continue
                else:
                    raise SpeechProviderError("invalid_response")
            if event_bytes + len(pending) > self._max_event_bytes:
                raise SpeechProviderError("response_limit")
        # A partial SSE event is a truncated stream, not a successful close.
        if pending or data_lines:
            raise SpeechProviderError("incomplete_stream")

    @staticmethod
    def _parse_event(data: str) -> dict[str, Any]:
        try:
            event = json.loads(data)
        except (ValueError, RecursionError):
            raise SpeechProviderError("invalid_response") from None
        if not isinstance(event, dict):
            raise SpeechProviderError("invalid_response")
        if "error" in event:
            error = event["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise http_error(code) if isinstance(code, int) else SpeechProviderError("unavailable")
        return event
