"""Small developer-only API setup helper. No runtime registration or inference.

Configuration is always read through mira.config.loader. Metadata is opt-in,
credential-specific and limited to GET /models; reports never include raw bodies.
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from mira.config.service_settings import ServiceSettings
from mira.config.settings import Settings

MAX_RESPONSE_BYTES = 256 * 1024
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}")
CORE_CAPABILITIES = ("text", "review", "asr", "tts")

# These routes have concrete, deliberately opt-in development entries. This is
# implementation inventory only: it says nothing about login, entitlement,
# inference, or composition into the normal application provider factory.
DEVELOPMENT_ENTRYPOINTS = {
    ("text", "codex_native"): "tools/live_dev.py",
    ("review", "jev"): "tools/live_dev.py",
    ("asr", "google_cloud_stt_v2"): "tools/live_voice.py",
    ("tts", "google_gemini_enterprise_tts"): "tools/live_voice.py",
}


class ServicePreparationError(ValueError):
    """Messages contain fixed reason codes, never credential or response values."""


def _adapter_status(capability: str, route: str) -> dict[str, Any]:
    entrypoint = DEVELOPMENT_ENTRYPOINTS.get((capability, route))
    return {
        "adapter": ("implemented_in_explicit_development_entry" if entrypoint else "not_implemented"),
        "adapter_entrypoint": entrypoint,
        # All supported live entries are explicit tools, not the default app
        # factory. Keep that readiness boundary visible in the offline report.
        "default_provider_factory_composed": False,
    }


def credential_present(key: SecretStr | None) -> bool:
    if key is None:
        return False
    value = key.get_secret_value()
    placeholder = value.lower()
    return bool(value) and not (
        placeholder.startswith(("your_", "your-", "replace", "<", "placeholder"))
        or placeholder in {"changeme", "todo", "example", "none", "null"}
    )


def inspect_services(settings: Settings, *, executable_available: bool = False) -> dict[str, Any]:
    """Pure field inspection: no sockets, credential discovery, subprocess, or file reads."""
    services = settings.services
    rows: dict[str, dict[str, Any]] = {}
    for capability in ("text", "image", "vision"):
        route = getattr(services.routes, capability)
        group = {"codex_native": services.codex, "gateway": services.gateway,
                 "openai_api": services.openai}[route]
        missing = []
        if getattr(group, capability + "_model") is None:
            missing.append("model_selection")
        if route == "codex_native":
            auth = "codex_managed_not_checked"
            if not executable_available:
                missing.append("codex_executable")
        else:
            auth = "credential_supplied_not_checked" if credential_present(group.api_key) else "credential_missing"
            if not credential_present(group.api_key):
                missing.append("service_credential")
            if route == "gateway" and not services.gateway.access_confirmed:
                missing.append("gateway_access_confirmation")
        rows[capability] = {"route": route, "fields_complete": not missing, "missing": missing,
                            "authentication": auth, "account_access": "not_run",
                            **_adapter_status(capability, route)}
    missing = []
    if not credential_present(services.jev.api_key):
        missing.append("typesafe_credential")
    if services.jev.model is None:
        missing.append("model_selection")
    rows["review"] = {"route": "jev", "fields_complete": not missing, "missing": missing,
                      "account_access": "not_run", **_adapter_status("review", "jev")}
    for capability in ("asr", "tts"):
        missing = []
        if not services.speech.project_id:
            missing.append("google_project")
        if capability == "tts" and not services.speech.tts_voice:
            missing.append("voice_selection")
        provider = services.speech.asr_provider if capability == "asr" else services.speech.tts_provider
        route = f"{provider}_stt_v2" if capability == "asr" else "google_gemini_enterprise_tts"
        rows[capability] = {"route": route,
                            "fields_complete": not missing, "missing": missing,
                            "authentication": "google_adc_not_checked", "account_access": "not_run",
                            **_adapter_status(capability, route)}
        if capability == "tts":
            rows[capability].update(model=services.speech.tts_model,
                                    location=services.speech.tts_location,
                                    release_stage="preview")
    return {
        "scope": "offline_configuration_only", "capabilities": rows,
        "core_fields_complete": all(rows[name]["fields_complete"] for name in CORE_CAPABILITIES),
        "live_ready": False, "inference_verified": "not_run",
        "runtime_mode": settings.providers.generation,
        "runtime_external_calls_allowed": settings.providers.allow_external_calls,
        "runtime_paid_api_allowed": settings.providers.allow_paid_api,
        "metadata_opt_in": services.probe.allow_metadata,
        "legacy_generic_key_present": credential_present(settings.providers.api_key),
        "note": "Fields and installed executables are not login, entitlement, inference, or product acceptance evidence.",
    }


def initialize_private_env(root: Path, destination: Path) -> None:
    """Create the blank, tracked template once. Never inspect another credential file."""
    try:
        content = (root / ".env.development.example").read_bytes()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(destination, flags, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(content)
    except FileExistsError:
        raise ServicePreparationError("private_env_already_exists") from None
    except OSError:
        raise ServicePreparationError("private_env_creation_failed") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("nonfinite_number")


def _catalog(body: bytes, provider: str) -> tuple[str, set[str]]:
    try:
        data = json.loads(body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        return "invalid_json", set()
    collection, key = ("models", "name") if provider == "jev" else ("data", "id")
    items = data.get(collection) if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) > 1000:
        return "invalid_catalog", set()
    names = set()
    for item in items:
        name = item.get(key) if isinstance(item, dict) else None
        if not isinstance(name, str) or not MODEL_ID.fullmatch(name):
            return "invalid_catalog", set()
        names.add(name)
    return "catalog_valid", names


def probe_models(settings: ServiceSettings, names: list[str], *, transport=None) -> dict[str, Any]:
    """Explicit, bounded GET-only diagnostics. Caller must still supply CLI consent.

    `transport` is a test seam; no fake transport is selected in production.
    Presence in a model catalog does not prove per-operation model access.
    """
    if (not names or len(names) != len(set(names))
            or any(name not in {"gateway", "jev", "openai"} for name in names)):
        raise ServicePreparationError("invalid_service_selection")
    if not settings.probe.allow_metadata or len(names) > settings.probe.max_requests:
        raise ServicePreparationError("metadata_not_authorized_or_request_budget_exceeded")
    # Validate every requested operation before creating a network client.
    for name in names:
        config = getattr(settings, name)
        if not credential_present(config.api_key):
            raise ServicePreparationError("selected_service_credential_missing")
        if name == "gateway" and not settings.gateway.access_confirmed:
            raise ServicePreparationError("gateway_access_not_confirmed")
    import httpx  # Existing development dependency; no network work at module import.

    results = []
    with httpx.Client(timeout=settings.probe.timeout_seconds, trust_env=False,
                      follow_redirects=False, transport=transport) as client:
        for name in names:
            config = getattr(settings, name)
            row: dict[str, Any] = {"service": name, "attempts": 1, "catalog_valid": False,
                                   "status": "not_run", "inference_verified": "not_run"}
            started = time.monotonic()
            try:
                with client.stream("GET", config.base_url + "/models", headers={
                    "Authorization": "Bearer " + config.api_key.get_secret_value(),
                    "Accept": "application/json", "Accept-Encoding": "identity",
                }) as response:
                    code = response.status_code
                    row["http_status"] = code
                    if code != 200:
                        row["status"] = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(
                            code, "redirect_refused" if 300 <= code < 400 else
                            "service_unavailable" if code >= 500 else "unexpected_status")
                    elif response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                        # Do not accept compressed bodies in this small diagnostics surface.
                        # The size limit applies to bytes that will be parsed, not an unbounded expansion.
                        row["status"] = "encoded_response_refused"
                    else:
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            if time.monotonic() - started > settings.probe.timeout_seconds:
                                row["status"] = "timeout"
                                break
                            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                                row["status"] = "response_too_large"
                                break
                            body.extend(chunk)
                        else:
                            row["status"], catalog = _catalog(bytes(body), name)
                            row["catalog_valid"] = row["status"] == "catalog_valid"
                            if row["catalog_valid"]:
                                selected = ({"review": config.model} if name == "jev" else {
                                    key: getattr(config, key + "_model") for key in ("text", "image", "vision")})
                                row["catalog_count"] = len(catalog)
                                row["selected_models_present"] = {
                                    key: (value in catalog if value is not None else None)
                                    for key, value in selected.items()
                                }
            except httpx.TimeoutException:
                row["status"] = "timeout"
            except httpx.HTTPError:
                row["status"] = "transport_error"
            results.append(row)
    return {"scope": "metadata_only", "results": results, "request_count": len(results),
            "live_ready": False, "inference_verified": "not_run",
            "note": "Only GET model catalogs. No completion, image, vision, speech or billing entitlement test."}
