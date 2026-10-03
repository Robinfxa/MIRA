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
    SpeechProviderError,
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

    def __post_init__(self):
        if not isinstance(self.project_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", self.project_id):
            raise ValueError("Invalid Google project identifier")
        if self.model != MODEL or self.location != "global":
            raise ValueError("Only exact Gemini 3.8 Flash TTS in global is supported")
        if self.voice not in PREBUILT_VOICES:
            raise ValueError("Select an explicitly supported prebuilt voice")
        if self.style is not None and (not isinstance(self.style, str) or not self.style.strip() or len(self.style) > 1000):
            raise ValueError("Speech style must be bounded nonblank text")
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
                    raise SpeechProviderError("blocked" if finish in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"} else "incomplete_stream")
                content = candidate.get("content", {})
                if not isinstance(content, dict) or not isinstance(content.get("parts", []), list):
                    raise SpeechProviderError("invalid_response")
                for response_part in content.get("parts", []):
                    if not isinstance(response_part, dict):
                        raise SpeechProviderError("invalid_response")
                    inline = response_part.get("inlineData")
                    if inline is None:
                        raise SpeechProviderError("unsupported_audio")
                    if stopped:
                        raise SpeechProviderError("invalid_response")
                    pcm = self._decode_pcm(inline)
                    if not pcm:
                        continue
                    if sample_cursor + len(pcm) // 2 > self.options.max_audio_samples:
                        raise SpeechProviderError("output_limit")
                    raise_if_cancelled()
                    yield AudioPacket(stream_id, sample_cursor, SAMPLE_RATE_HZ, pcm)
                    sample_cursor += len(pcm) // 2
                stopped = stopped or finish == "STOP"
            if not sample_cursor:
                raise SpeechProviderError("empty_audio")
            if not stopped:
                raise SpeechProviderError("incomplete_stream")
        except Exception as error:
            raise safe_error(error) from None
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
                    raise http_error(response.status_code)
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
