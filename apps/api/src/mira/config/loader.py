"""Only this production module reads os.environ or dotenv.

Precedence, low to high: typed defaults < defaults.toml < profile.toml
< explicitly selected dotenv < process environment < test overrides.
No dotenv auto-discovery, no mutation of os.environ, no process-global cache.
"""
import json
import os
import re
import tomllib
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import ValidationError

from mira.config.settings import Settings

ENV_FIELDS = {
    "MIRA_ENVIRONMENT": ("environment",),
    "MIRA_HTTP__HOST": ("http", "host"),
    "MIRA_HTTP__PORT": ("http", "port"),
    "MIRA_HTTP__ALLOWED_ORIGINS": ("http", "allowed_origins"),
    "MIRA_RUNTIME__TIMEOUT_SECONDS": ("runtime", "timeout_seconds"),
    "MIRA_RUNTIME__MAX_SESSIONS": ("runtime", "max_sessions"),
    "MIRA_RUNTIME__MAX_TURNS": ("runtime", "max_turns"),
    "MIRA_RUNTIME__MAX_EFFECTS": ("runtime", "max_effects"),
    "MIRA_RUNTIME__JOURNAL_CAPACITY": ("runtime", "journal_capacity"),
    "MIRA_PROVIDERS__GENERATION": ("providers", "generation"),
    "MIRA_PROVIDERS__REVIEW": ("providers", "review"),
    "MIRA_PROVIDERS__REPLAY_SCENARIO": ("providers", "replay_scenario"),
    "MIRA_PROVIDERS__MOCK_DELAY_MS": ("providers", "mock_delay_ms"),
    "MIRA_PROVIDERS__ALLOW_EXTERNAL_CALLS": ("providers", "allow_external_calls"),
    "MIRA_PROVIDERS__ALLOW_PAID_API": ("providers", "allow_paid_api"),
    "MIRA_PROVIDERS__API_KEY": ("providers", "api_key"),
}


DIAGNOSTIC_FIELDS = ("enabled", "directory", "max_file_bytes", "max_files", "retention_seconds",
                     "queue_capacity", "development_recording", "recording_consent",
                     "raw_max_file_bytes", "raw_max_files", "raw_retention_seconds")
ENV_FIELDS.update({f"MIRA_DIAGNOSTICS__{name.upper()}": ("diagnostics", name)
                   for name in DIAGNOSTIC_FIELDS})


# Public service fields are enumerated here; arbitrary MIRA_* names remain errors.
SERVICE_FIELDS = {
    "routes": ("text", "image", "vision"),
    "codex": ("text_model", "image_model", "vision_model"),
    "gateway": ("base_url", "api_key", "access_confirmed", "text_model", "image_model", "vision_model"),
    "openai": ("base_url", "api_key", "text_model", "image_model", "vision_model"),
    "jev": ("base_url", "api_key", "model"),
    "speech": ("asr_provider", "tts_provider", "auth", "project_id", "quota_project_id", "stt_location", "stt_model",
               "stt_language_code", "tts_language_code", "tts_voice", "tts_endpoint",
               "tts_model", "tts_location", "tts_style"),
    "probe": ("allow_metadata", "max_requests", "timeout_seconds"),
}
ENV_FIELDS.update({f"MIRA_SERVICES__{group.upper()}__{name.upper()}": ("services", group, name)
                   for group, names in SERVICE_FIELDS.items() for name in names})
# Explicit SDK aliases, normalized per source layer before precedence is applied.
SERVICE_ALIASES = {
    "OPENAI_API_KEY": "MIRA_SERVICES__OPENAI__API_KEY",
    "TYPESAFE_API_KEY": "MIRA_SERVICES__JEV__API_KEY",
    "GOOGLE_CLOUD_PROJECT": "MIRA_SERVICES__SPEECH__PROJECT_ID",
    "GOOGLE_CLOUD_QUOTA_PROJECT": "MIRA_SERVICES__SPEECH__QUOTA_PROJECT_ID",
}


class ConfigurationError(ValueError):
    pass


def normalized_aliases(values: Mapping[str, str]) -> dict[str, str]:
    result = dict(values)
    for alias, target in SERVICE_ALIASES.items():
        if alias not in result:
            continue
        if target in result and result[target] != result[alias]:
            raise ConfigurationError(f"Conflicting credential/config aliases: {alias} and {target}")
        result[target] = result.pop(alias)
    return result


def reject_toml_secrets(data: Any) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in {"api_key", "access_token", "refresh_token", "private_key"}:
                raise ConfigurationError("Secrets cannot be declared in TOML profiles.")
            reject_toml_secrets(value)
    elif isinstance(data, list):
        for value in data:
            reject_toml_secrets(value)


def merge(base: dict[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "config/defaults.toml").is_file():
            return parent
    raise ConfigurationError("Cannot locate config/defaults.toml; pass an explicit project root.")


def load_settings(*, root: Path | None = None, env_file: Path | None = None,
                  environ: Mapping[str, str] | None = None,
                  overrides: Mapping[str, Any] | None = None,
                  load_legacy_jev: bool = True) -> Settings:
    if type(load_legacy_jev) is not bool:
        raise ConfigurationError("Legacy JEV configuration selection must be explicit.")
    root = root or project_root()
    source_env = dict(os.environ if environ is None else environ)
    file_env: dict[str, str] = {}
    if env_file is not None:
        if not env_file.is_file():
            raise ConfigurationError("Explicit dotenv file does not exist.")
        file_env = {k: v for k, v in dotenv_values(env_file, interpolate=False).items() if v is not None}
    if not load_legacy_jev:
        # The explicitly selected file is still read as a whole. Do not resolve,
        # validate or retain inactive legacy secrets/aliases in native mode.
        ignored = {name for name, location in ENV_FIELDS.items()
                   if location[:2] == ("services", "jev")} | {"TYPESAFE_API_KEY"}
        file_env = {key: value for key, value in file_env.items() if key not in ignored}
        source_env = {key: value for key, value in source_env.items() if key not in ignored}
    combined = normalized_aliases(file_env) | normalized_aliases(source_env)
    profile = combined.get("MIRA_PROFILE", "mock")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", profile):
        raise ConfigurationError("Invalid MIRA_PROFILE name.")
    config: dict[str, Any] = {}
    for path in (root / "config/defaults.toml", root / f"config/profiles/{profile}.toml"):
        if not path.is_file():
            raise ConfigurationError(f"Missing configuration file: {path.name}")
        with path.open("rb") as file:
            data = tomllib.load(file)
        reject_toml_secrets(data)
        config = merge(config, data)
    for key, value in combined.items():
        if not key.startswith("MIRA_") or key == "MIRA_PROFILE":
            continue
        location = ENV_FIELDS.get(key)
        if location is None:
            raise ConfigurationError(f"Unknown configuration variable: {key}")
        target = config
        for part in location[:-1]:
            target = target.setdefault(part, {})
        if key == "MIRA_HTTP__ALLOWED_ORIGINS":
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ConfigurationError("Allowed origins must be a JSON string array.") from None
        target[location[-1]] = value
    config = merge(config, overrides or {})
    if not load_legacy_jev and "services" in config:
        config["services"].pop("jev", None)
    try:
        return Settings.model_validate(config)
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        raise ConfigurationError(f"Invalid configuration fields: {fields}") from None
