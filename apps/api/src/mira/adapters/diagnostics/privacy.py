"""Allowlist encoding plus defensive credential filtering, not a universal DLP claim."""
import base64
import json
import math
import re
import unicodedata
from dataclasses import dataclass, fields

from mira.application.diagnostic_events import (
    CancellationReason,
    ContentReview,
    DiagnosticCode,
    DiagnosticContext,
    DiagnosticEvent,
    DiagnosticKind,
    DiagnosticOutcome,
    DiagnosticStage,
    RecordingKind,
    ReviewedRecording,
    correlation_hash,
)

_CONTEXT_KEYS = tuple(field.name for field in fields(DiagnosticContext))
_HASH = re.compile(r"h_[0-9a-f]{32}\Z")
_FORBIDDEN_ENVELOPE = re.compile(
    r'(?i)(?:authorization\s*[":=]|["\'](?:headers|private_key|client_secret|credentials|'
    r'access_token|refresh_token|id_token|password|api_key|x-api-key)["\']\s*:|'
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----)')
_SECRET_SHAPES = (
    re.compile(r"(?i)(?<![A-Za-z0-9_-])[_-]*(?:[A-Za-z][A-Za-z0-9_-]*[_-])?(?:api[_-]?key|password|passwd|private[_-]?key|access[_-]?token|refresh[_-]?token|"
               r"client[_-]?secret|secret|credentials|token)\s*(?:=|:|\bis\b)\s*"
               r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*')"),
    re.compile(r"(?i)\bBearer\s+[^\s,;\"']+"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"),
    re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)(?<![A-Za-z0-9_-])[_-]*(?:[A-Za-z][A-Za-z0-9_-]*[_-])?(?:api[_-]?key|password|passwd|private[_-]?key|access[_-]?token|refresh[_-]?token|"
               r"client[_-]?secret|secret|credentials|token)\s*(?:=|:|\bis\b)\s*[^\s,;\"']+"),
    re.compile(r"(?i)https?://[^\s/@:]+:[^\s/@]+@[^\s]+"),
)


# Raw text is deliberately a small, conservative language, not arbitrary encoding/DLP.
_MAX_TEXT_BYTES = 128 * 1024
_MAX_DEPTH = 16
_MAX_NODES = 4096
_MAX_REVIEW_CHARS = 1024 * 1024
_CREDENTIAL_KEYS = frozenset((
    "authorization", "proxyauthorization", "headers", "requestheaders", "httpheaders",
    "privatekey", "clientsecret", "credentials", "accesstoken", "refreshtoken",
    "idtoken", "password", "passwd", "apikey", "xapikey", "secret", "token",
    "cookie", "setcookie",
))
_QUOTED_ASSIGNMENT = re.compile(r"[\"']([^\"'\\\r\n]{1,256})[\"']\s*[:=]")
_JSON_START = re.compile(r"[\[{]")
_NON_JSON_ESCAPE = re.compile(r'\\(?:["\\]|u[0-9a-fA-F]{4})')


def _credential_key(value: str) -> bool:
    # JSON decoding handles Unicode escapes; NFKC covers compatibility-width keys.
    # This intentionally does not promise arbitrary homoglyph/encoded-key detection.
    normal = unicodedata.normalize("NFKC", value).casefold()
    compact = "".join(char for char in normal if char.isalnum())
    return (compact in _CREDENTIAL_KEYS or
            any(compact.endswith(key) for key in _CREDENTIAL_KEYS
                if key not in ("headers", "token", "secret", "cookie")) or
            any(part in _CREDENTIAL_KEYS for part in re.split(r"[_\s-]+", normal)))


@dataclass
class _ReviewBudget:
    nodes: int = 0
    chars: int = 0

    def spend(self, *, depth: int, chars: int = 0) -> None:
        self.nodes += 1
        self.chars += chars
        if depth > _MAX_DEPTH or self.nodes > _MAX_NODES or self.chars > _MAX_REVIEW_CHARS:
            raise ValueError("privacy review budget exceeded")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON object")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite JSON value")


_JSON = json.JSONDecoder(object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _json_end(value: str, start: int, depth: int) -> int:
    """Bound structural depth before handing untrusted text to the JSON decoder."""
    quoted, escaped, stack = False, False, []
    for index in range(start, len(value)):
        char = value[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "[{":
            stack.append(char)
            if depth + len(stack) > _MAX_DEPTH:
                raise ValueError("privacy review depth exceeded")
        elif char in "]}":
            if not stack or stack.pop() != ("[" if char == "]" else "{"):
                raise ValueError("malformed JSON structure")
            if not stack:
                return index + 1
    raise ValueError("incomplete JSON structure")


def context_dict(context: DiagnosticContext) -> dict:
    if type(context) is not DiagnosticContext:
        raise ValueError("invalid correlation")
    result = {}
    for key in _CONTEXT_KEYS:
        value = getattr(context, key)
        if value is not None:
            if type(value) is not str or not 1 <= len(value) <= 256:
                raise ValueError("invalid correlation")
            result[key] = correlation_hash(value)
    return result


def _number(value, *, minimum=0, maximum=86400000):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("invalid numeric field")
    return round(value, 3)


def encode_event(event: DiagnosticEvent, now: float) -> dict:
    if type(event) is not DiagnosticEvent:
        raise ValueError("invalid event")
    result = {"schema": 1, "record_type": "event", "timestamp": _number(now, maximum=1e12),
              "stage": DiagnosticStage(event.stage).value,
              "kind": DiagnosticKind(event.kind).value,
              "outcome": DiagnosticOutcome(event.outcome).value,
              "context": context_dict(event.context)}
    if event.code is not None:
        result["code"] = DiagnosticCode(event.code).value
    if event.cancellation_reason is not None:
        if event.outcome != DiagnosticOutcome.CANCELLED:
            raise ValueError("cancellation reason requires cancelled outcome")
        result["cancellation_reason"] = CancellationReason(event.cancellation_reason).value
    if event.duration_ms is not None:
        result["duration_ms"] = _number(event.duration_ms)
    if event.http_status is not None:
        if type(event.http_status) is not int or not 100 <= event.http_status <= 599:
            raise ValueError("invalid status")
        result["http_status"] = event.http_status
    return result


def validate_event_record(record: dict) -> dict:
    required = {"schema", "record_type", "timestamp", "stage", "kind", "outcome", "context"}
    optional = {"code", "cancellation_reason", "duration_ms", "http_status"}
    if (type(record) is not dict or not required <= record.keys()
            or record.keys() - required - optional or type(record["schema"]) is not int
            or record["schema"] != 1 or record["record_type"] != "event"):
        raise ValueError("invalid event schema")
    context = record["context"]
    if (type(context) is not dict or context.keys() - set(_CONTEXT_KEYS)
            or any(type(value) is not str or not _HASH.fullmatch(value) for value in context.values())):
        raise ValueError("invalid correlation")
    event = DiagnosticEvent(stage=record["stage"], kind=record["kind"], outcome=record["outcome"],
        code=record.get("code"), cancellation_reason=record.get("cancellation_reason"),
        duration_ms=record.get("duration_ms"), http_status=record.get("http_status"))
    checked = encode_event(event, record["timestamp"])
    checked["context"] = dict(context)
    return checked


class PrivacyFilter:
    """Trusted injection of active secrets; repr never exposes them.

    Pattern checks are a second defense. Exact-record privacy review is still
    mandatory, especially for audio and unknown credential formats.
    """
    def __init__(self, secrets=()):
        self._secrets: tuple[str, ...] = ()
        for value in secrets:
            self.add_secret(value)

    def add_secret(self, value: str) -> None:
        if type(value) is not str or not value or len(value) > 8192:
            raise ValueError("invalid trusted secret")
        if value in self._secrets:
            return
        if len(self._secrets) >= 4096:
            raise ValueError("trusted secret budget reached")
        self._secrets += (value,)

    def text(self, value: str) -> str:
        if (type(value) is not str or len(value) > _MAX_TEXT_BYTES
                or len(value.encode()) > _MAX_TEXT_BYTES):
            raise ValueError("invalid text buffer")
        result = self._text(value, _ReviewBudget(), 0)
        if len(result) > _MAX_TEXT_BYTES or len(result.encode()) > _MAX_TEXT_BYTES:
            raise ValueError("filtered text exceeds budget")
        return result

    def _plain(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        if (_FORBIDDEN_ENVELOPE.search(normalized) or any(
                _credential_key(match.group(1)) for match in _QUOTED_ASSIGNMENT.finditer(normalized))):
            raise ValueError("credential envelope is ineligible")
        for secret in sorted(self._secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        for pattern in _SECRET_SHAPES:
            value = pattern.sub("[REDACTED]", value)
        # Escaped syntax outside valid JSON is uncertain, never guessed/decoded.
        if _NON_JSON_ESCAPE.search(value):
            raise ValueError("ambiguous non-JSON escape")
        return value

    def _walk(self, value, budget: _ReviewBudget, depth: int):
        budget.spend(depth=depth)
        if type(value) is str:
            return self._text(value, budget, depth + 1)
        if type(value) is list:
            return [self._walk(item, budget, depth + 1) for item in value]
        if type(value) is dict:
            result = {}
            for key, item in value.items():
                budget.spend(depth=depth + 1, chars=len(key))
                if _credential_key(key):
                    raise ValueError("credential envelope is ineligible")
                safe_key = self._text(key, budget, depth + 1)
                if safe_key in result:
                    raise ValueError("ambiguous filtered JSON object")
                result[safe_key] = self._walk(item, budget, depth + 1)
            return result
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        raise ValueError("invalid JSON value")

    def _text(self, value: str, budget: _ReviewBudget, depth: int) -> str:
        budget.spend(depth=depth, chars=len(value))
        stripped = value.lstrip()
        if stripped and stripped[0] in '{["' and not stripped.startswith("[REDACTED]"):
            if stripped[0] in "{[":
                _json_end(stripped, 0, depth)
            parsed, end = _JSON.raw_decode(stripped)
            if stripped[end:].strip():
                raise ValueError("ambiguous JSON suffix")
            checked = self._walk(parsed, budget, depth + 1)
            return (value if checked == parsed else
                    json.dumps(checked, ensure_ascii=False, allow_nan=False))
        value = self._plain(value)
        # A JSON envelope embedded in prose still receives the same review. Invalid
        # bracket/brace fragments are dropped conservatively rather than decoded.
        pieces, cursor = [], 0
        while cursor < len(value):
            match = _JSON_START.search(value, cursor)
            if match is None:
                break
            start = match.start()
            pieces.append(value[cursor:start])
            if value.startswith("[REDACTED]", start):
                pieces.append("[REDACTED]")
                cursor = start + len("[REDACTED]")
                continue
            end = _json_end(value, start, depth)
            parsed, decoded_end = _JSON.raw_decode(value, start)
            if end != decoded_end:
                raise ValueError("ambiguous JSON fragment")
            checked = self._walk(parsed, budget, depth + 1)
            pieces.append(value[start:end] if checked == parsed else
                          json.dumps(checked, ensure_ascii=False, allow_nan=False))
            cursor = end
        pieces.append(value[cursor:])
        return "".join(pieces)

    def recording(self, record: ReviewedRecording, *, now: float,
                  max_text_bytes: int, max_audio_bytes: int) -> dict:
        if (type(record) is not ReviewedRecording
                or record.review not in (ContentReview.APPROVED, ContentReview.REDACTED)):
            raise ValueError("privacy review required")
        kind = RecordingKind(record.kind)
        result = {"schema": 1, "record_type": "reviewed_raw",
                  "timestamp": _number(now, maximum=1e12), "kind": kind.value,
                  "privacy_review": ContentReview(record.review).value,
                  "context": context_dict(record.context)}
        if kind in (RecordingKind.DIALOGUE, RecordingKind.MODEL_INPUT, RecordingKind.MODEL_OUTPUT):
            if (type(record.text) is not str or record.audio is not None
                    or record.sample_rate_hz is not None
                    or len(record.text) > max_text_bytes
                    or len(record.text.encode()) > max_text_bytes):
                raise ValueError("invalid text buffer")
            result["text"] = self.text(record.text)
            if result["text"] != record.text:
                result["privacy_review"] = ContentReview.REDACTED.value
        else:
            if (type(record.audio) is not bytes or record.text is not None
                    or not record.audio or len(record.audio) % 2
                    or len(record.audio) > max_audio_bytes
                    or type(record.sample_rate_hz) is not int
                    or record.sample_rate_hz not in (16000, 24000, 48000)):
                raise ValueError("invalid audio buffer")
            # A known credential embedded as bytes is also forbidden. This is not
            # spoken-secret detection; approval must cover listening/privacy review.
            if any(secret.encode() in record.audio for secret in self._secrets):
                raise ValueError("credential bytes")
            ascii_view = record.audio.decode("ascii", errors="ignore")
            if _FORBIDDEN_ENVELOPE.search(ascii_view) or any(
                    pattern.search(ascii_view) for pattern in _SECRET_SHAPES):
                raise ValueError("credential bytes")
            result["audio_base64"] = base64.b64encode(record.audio).decode("ascii")
            result["sample_rate_hz"] = record.sample_rate_hz
        return result


def validate_raw_record(record: dict) -> dict:
    required = {"schema", "record_type", "timestamp", "kind", "privacy_review", "context"}
    if (type(record) is not dict or not required <= record.keys()
            or record.keys() - required - {"text", "audio_base64", "sample_rate_hz"}
            or type(record["schema"]) is not int or record["schema"] != 1
            or record["record_type"] != "reviewed_raw"):
        raise ValueError("invalid recording schema")
    context = record["context"]
    if (type(context) is not dict or context.keys() - set(_CONTEXT_KEYS)
            or any(type(value) is not str or not _HASH.fullmatch(value) for value in context.values())):
        raise ValueError("invalid correlation")
    audio = None
    if "audio_base64" in record:
        audio = base64.b64decode(record["audio_base64"], validate=True)
    checked = PrivacyFilter().recording(ReviewedRecording(kind=record["kind"],
        review=record["privacy_review"], text=record.get("text"), audio=audio,
        sample_rate_hz=record.get("sample_rate_hz")), now=record["timestamp"],
        max_text_bytes=128 * 1024, max_audio_bytes=512 * 1024)
    checked["context"] = dict(context)
    return checked
