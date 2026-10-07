"""Strict metadata-only Codex setup handshake; never starts a thread or model turn."""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass

from .payload import canonical, strict_json
from .process import StdioProcessTransport
from .protocol import _ConfigValidationError, _verify_config
from .types import CodexGenerationError, CodexLimits, CodexRuntime, PINNED_VERSION

_VERSION = PINNED_VERSION
_REQUESTS = (("initialize", {"clientInfo": {"name": "mira_metadata_setup", "version": "1.0"},
                              "capabilities": {"experimentalApi": True}}),
             ("config/read", {"includeLayers": False}))
_RESULT_FIELDS = frozenset(("jsonrpc", "id", "result"))
_UNSAFE_CONFIG_KEYS = frozenset((
    "api_key", "apikey", "openai_api_key", "openaiapikey", "access_token",
    "refresh_token", "authorization", "auth_headers", "headers", "credentials",
    "client_secret", "developer_instructions", "custom_instructions", "instructions_file",
))
_KNOWN_NOTIFICATION_METHODS = frozenset((
    # Exact event names accepted by the pinned local session protocol. These are
    # diagnostic labels only; only the two pinned startup notices below may be discarded.
    "configWarning", "deprecationNotice", "account/rateLimits/updated",
    "turn/moderationMetadata", "thread/settings/updated", "account/updated",
    "remoteControl/status/changed", "warning", "thread/started",
    "thread/status/changed", "turn/started", "turn/completed", "item/started",
    "item/completed", "item/agentMessage/delta", "item/reasoning/textDelta",
    "item/reasoning/summaryTextDelta", "item/reasoning/summaryPartAdded",
    "item/plan/delta", "turn/plan/updated", "thread/tokenUsage/updated",
))
_STARTUP_NOTICES = frozenset(("configWarning", "deprecationNotice"))
_PASSIVE_STARTUP_NOTIFICATIONS = _STARTUP_NOTICES | frozenset(("remoteControl/status/changed",))
_REMOTE_CONTROL_STATUSES = frozenset(("disabled", "connecting", "connected", "errored"))
_MAX_STARTUP_NOTICES = 16
_MAX_NOTICE_BYTES = 32_768
_MAX_TOTAL_NOTICE_BYTES = 131_072
_MAX_PREFLIGHT_LINE_BYTES = 131_072
_MAX_PREFLIGHT_WIRE_BYTES = 1_048_576
_EXPECTED_BODY_FIELDS = {
    "initialize": ("userAgent", "codexHome", "platformFamily", "platformOs"),
    "config/read": ("config", "origins", "layers"),
}
_OPTIONAL_BODY_FIELDS = {"initialize": (), "config/read": ("layers",)}


class PreflightDiagnosticError(CodexGenerationError):
    """Fixed reason plus protocol-envelope facts safe to show in local diagnostics."""

    def __init__(self, reason: str, details: dict):
        super().__init__(reason)
        # `details` is constructed only from fixed labels, bounded ints and bools.
        self.safe_details = details


@dataclass(frozen=True, slots=True)
class MetadataDeclaration:
    """Non-secret fingerprints describing observed setup metadata, not readiness."""

    executable_sha256: str
    config_sha256: str
    environment_sha256: str
    codex_version: str = _VERSION
    route_kind: str = "public"
    startup_notifications: tuple[tuple[str, int], ...] = ()


class MetadataOnlyTransport:
    """Enforce the exact setup RPC sequence before sending anything to the process."""

    def __init__(self, transport: StdioProcessTransport, runtime: CodexRuntime):
        self._transport = transport
        self._runtime = runtime
        self._closed = False
        self._notice_counts: dict[str, int] = {}
        self._notice_bytes = 0
        self._wire_bytes = 0
        self._phase = "initialize"

    async def _one_response(self, request_id: int, method: str) -> dict | None:
        raw = await self._transport.receive()
        if type(raw) is not bytes or not raw.endswith(b"\n"):
            raise _diagnostic_error(method, "transport_invalid", request_id)
        self._wire_bytes += len(raw)
        if len(raw) > _MAX_PREFLIGHT_LINE_BYTES or self._wire_bytes > _MAX_PREFLIGHT_WIRE_BYTES:
            raise _diagnostic_error(method, "wire_limit", request_id)
        try:
            message = strict_json(raw)
        except CodexGenerationError as error:
            if str(error) != "codex_json_invalid":
                raise
            raise _diagnostic_error(method, "malformed_json", request_id) from None
        if type(message) is not dict:
            raise _diagnostic_error(method, "non_object", request_id)

        message_method = message.get("method")
        if (method == "config/read" and type(message_method) is str
                and message_method in _PASSIVE_STARTUP_NOTIFICATIONS
                and "id" not in message):
            if not _valid_startup_notification(message):
                raise _diagnostic_error(method, "notification_invalid", request_id,
                                        notification_method=message_method)
            if (len(raw) > _MAX_NOTICE_BYTES
                    or self._notice_bytes + len(raw) > _MAX_TOTAL_NOTICE_BYTES
                    or sum(self._notice_counts.values()) >= _MAX_STARTUP_NOTICES):
                raise _diagnostic_error(method, "notification_limit", request_id,
                                        notification_method=message_method)
            self._notice_bytes += len(raw)
            self._notice_counts[message_method] = self._notice_counts.get(message_method, 0) + 1
            return None  # Never retain warning text/path or treat it as permission.

        if type(message_method) is str:
            category = "server_request" if "id" in message else "notification"
            reported_method = (message_method if category == "notification"
                               and message_method in _KNOWN_NOTIFICATION_METHODS
                               else "unknown")
            raise _diagnostic_error(method, category, request_id,
                                    observed_id=message.get("id"),
                                    notification_method=reported_method)

        if "error" in message:
            error = message.get("error")
            code = error.get("code") if type(error) is dict else None
            if type(code) is not int or not -(2**31) <= code <= 2**31 - 1:
                code = None
            raise _diagnostic_error(method, "rpc_error", request_id,
                                    observed_id=message.get("id"),
                                    numeric_error_code=code)

        if set(message) - _RESULT_FIELDS:
            raise _diagnostic_error(method, "response_extra_fields", request_id)
        if (message.get("jsonrpc", "2.0") != "2.0"
                or type(message.get("id")) is not int or message["id"] != request_id):
            raise _diagnostic_error(method, "response_id_or_version_mismatch", request_id,
                                    observed_id=message.get("id"))
        if "result" not in message or type(message["result"]) is not dict:
            raise _diagnostic_error(method, "response_result_invalid", request_id)
        return message["result"]

    async def _response(self, request_id: int, method: str) -> dict:
        while True:
            result = await self._one_response(request_id, method)
            if result is not None:
                return result

    async def _request(self, request_id: int, method: str, params: dict) -> dict:
        if (request_id, method, params) not in ((1, _REQUESTS[0][0], _REQUESTS[0][1]),
                                               (2, _REQUESTS[1][0], _REQUESTS[1][1])):
            raise CodexGenerationError("codex_preflight_rpc_forbidden")
        self._phase = method
        await self._transport.send({"id": request_id, "method": method, "params": params})
        return await self._response(request_id, method)

    async def observe(self, timeout_seconds: float) -> MetadataDeclaration:
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 30:
            raise CodexGenerationError("codex_preflight_timeout_invalid")
        if self._runtime.development_context is not None:
            raise CodexGenerationError("codex_preflight_route_unsupported")
        try:
            async with asyncio.timeout(timeout_seconds):
                initialized = await self._request(1, *_REQUESTS[0])
                if (set(initialized) - {"userAgent", "codexHome", "platformFamily", "platformOs"}
                        or initialized.get("codexHome") != str(self._runtime.codex_home)
                        or type(initialized.get("userAgent")) is not str
                        or not re.search(
                            rf"(?:^|/){re.escape(_VERSION)}(?:\s|\(|$)",
                            initialized["userAgent"],
                        )
                        or initialized.get("platformFamily") != self._runtime.platform_family
                        or initialized.get("platformOs") != self._runtime.platform_os):
                    raise _profile_failure("initialize_profile", phase="initialize")
                await self._transport.send({"method": "initialized"})
                config_result = await self._request(2, *_REQUESTS[1])
                if set(config_result) - {"config", "origins", "layers"}:
                    raise _profile_failure("config_body_fields",
                        unknown_field_count=len(set(config_result) - {"config", "origins", "layers"}))
                if type(config_result.get("origins", {})) is not dict:
                    raise _profile_failure("origins_type", field="origins", value=config_result.get("origins"))
                if (config_result.get("layers") is not None
                        and type(config_result["layers"]) not in (dict, list)):
                    raise _profile_failure("layers_type", field="layers", value=config_result["layers"])
                config = config_result.get("config")
                if type(config) is not dict:
                    raise _profile_failure("config_type", field="config", value=config)
                _reject_unsafe_config_keys(config)
                _verify_config(config_result, self._runtime)
                config_digest = hashlib.sha256(canonical(config)).hexdigest()
                del config_result, config, initialized
                return MetadataDeclaration(
                    executable_sha256=self._runtime.executable_sha256,
                    config_sha256=config_digest,
                    environment_sha256=hashlib.sha256(
                        canonical(dict(self._runtime.environment))).hexdigest(),
                    startup_notifications=tuple(sorted(self._notice_counts.items())),
                )
        except TimeoutError:
            if self._notice_counts:
                raise PreflightDiagnosticError("codex_preflight_timeout", {
                    "phase": self._phase,
                    "startup_notifications": dict(self._notice_counts),
                }) from None
            raise CodexGenerationError("codex_preflight_timeout") from None
        except CodexGenerationError as error:
            if isinstance(error, _ConfigValidationError):
                error = PreflightDiagnosticError(str(error), {"phase": self._phase,
                    "check_code": error.check_code})
            if self._notice_counts:
                details = (dict(error.safe_details) if isinstance(error, PreflightDiagnosticError)
                           else {"phase": self._phase})
                details["startup_notifications"] = dict(self._notice_counts)
                raise PreflightDiagnosticError(str(error), details) from None
            raise error
        except (TypeError, ValueError, RecursionError, UnicodeError) as error:
            raise PreflightDiagnosticError("codex_preflight_profile_drift", {
                "phase": self._phase, "check_code": "value_conversion",
                "exception_kind": type(error).__name__}) from None
        finally:
            await self.close()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._transport.close()


async def observe_public_metadata(runtime: CodexRuntime, *, timeout_seconds: float = 10.0,
                                  limits: CodexLimits | None = None) -> MetadataDeclaration:
    """Run the bounded public-route handshake and always reap its native child."""
    if runtime.development_context is not None:
        raise CodexGenerationError("codex_preflight_route_unsupported")
    from .process import open_stdio_preflight

    transport = await open_stdio_preflight(runtime, limits or CodexLimits(
        startup_seconds=timeout_seconds, turn_seconds=timeout_seconds))
    return await MetadataOnlyTransport(transport, runtime).observe(timeout_seconds)


def _profile_failure(check_code: str, *, phase: str = "config/read", field: str | None = None,
                     value: object = None, unknown_field_count: int | None = None) -> PreflightDiagnosticError:
    details = {"phase": phase, "check_code": check_code}
    if field is not None:
        # Only fixed contract names or members of _UNSAFE_CONFIG_KEYS reach this helper.
        details["field"] = field
        details["value_kind"] = {type(None): "null", str: "string", list: "array", dict: "object",
            bool: "boolean", int: "integer", float: "number"}.get(type(value), "other")
        details["value_empty"] = value is None or (type(value) in (str, list, dict) and len(value) == 0)
    if unknown_field_count is not None:
        details["unknown_field_count"] = unknown_field_count
    return PreflightDiagnosticError("codex_preflight_profile_drift", details)


def _reject_unsafe_config_keys(value: object) -> None:
    """Fail closed on credential-bearing or instruction injection config fields."""
    if type(value) is dict:
        for key, child in value.items():
            normalized = key.lower().replace("-", "_") if type(key) is str else ""
            if normalized in _UNSAFE_CONFIG_KEYS:
                # A serialized inactive optional field is not an instruction or credential.
                # Do not strip nonempty strings or skip nonempty nested containers.
                inactive = child is None or (type(child) in (str, dict, list) and len(child) == 0)
                if not inactive:
                    raise _profile_failure("unsafe_config_field", field=normalized, value=child)
            _reject_unsafe_config_keys(child)
    elif type(value) is list:
        for child in value:
            _reject_unsafe_config_keys(child)


def _valid_startup_notification(message: dict) -> bool:
    """Validate a small pinned passive startup notice without acting on its values."""
    if message.get("method") == "remoteControl/status/changed":
        return _valid_remote_control_status_notification(message)
    return _valid_startup_notice(message)


def _valid_remote_control_status_notification(message: dict) -> bool:
    """Pinned v0.159.2 notification schema; all status/identity values are discarded."""
    if (set(message) - {"jsonrpc", "method", "params", "emittedAtMs"}
            or message.get("jsonrpc", "2.0") != "2.0"):
        return False
    stamp = message.get("emittedAtMs")
    if stamp is not None and (type(stamp) is not int or not -(2**63) <= stamp < 2**63):
        return False
    params = message.get("params")
    if type(params) is not dict or set(params) - {"status", "serverName", "installationId", "environmentId"}:
        return False
    if not {"status", "serverName", "installationId"} <= set(params):
        return False
    return (type(params["status"]) is str and params["status"] in _REMOTE_CONTROL_STATUSES
            and type(params["serverName"]) is str
            and type(params["installationId"]) is str
            and ("environmentId" not in params or params["environmentId"] is None
                 or type(params["environmentId"]) is str))


def _valid_startup_notice(message: dict) -> bool:
    """Pinned v0.159.2 schema only; values remain transient and are never used."""
    if (set(message) - {"jsonrpc", "method", "params", "emittedAtMs"}
            or message.get("jsonrpc", "2.0") != "2.0"):
        return False
    stamp = message.get("emittedAtMs")
    if stamp is not None and (type(stamp) is not int or not -(2**63) <= stamp < 2**63):
        return False
    method, params = message.get("method"), message.get("params")
    allowed = ({"summary", "details", "path", "range"} if method == "configWarning"
               else {"summary", "details"})
    if (type(params) is not dict or set(params) - allowed
            or type(params.get("summary")) is not str
            or params.get("details") is not None and type(params["details"]) is not str):
        return False
    if method == "configWarning":
        if params.get("path") is not None and type(params["path"]) is not str:
            return False
        span = params.get("range")
        if span is not None:
            if type(span) is not dict or set(span) != {"start", "end"}:
                return False
            for position in span.values():
                if (type(position) is not dict or set(position) != {"line", "column"}
                        or any(type(v) is not int or not 1 <= v < 2**64
                               for v in position.values())):
                    return False
    return True


def _diagnostic_error(phase: str, category: str, request_id: int, *,
                      observed_id: object = None,
                      notification_method: str | None = None,
                      numeric_error_code: int | None = None) -> PreflightDiagnosticError:
    id_matches = (observed_id == request_id if type(observed_id) is int else None)
    details = {
        "phase": phase,
        "envelope_category": category,
        "request_id_match": id_matches,
        "expected_protocol_fields": ["jsonrpc", "id", "result"],
        "expected_body_fields": list(_EXPECTED_BODY_FIELDS[phase]),
        "optional_body_fields": list(_OPTIONAL_BODY_FIELDS[phase]),
    }
    if notification_method is not None:
        details["notification_method"] = notification_method
    if numeric_error_code is not None:
        details["numeric_error_code"] = numeric_error_code
    return PreflightDiagnosticError("codex_preflight_" + category, details)
