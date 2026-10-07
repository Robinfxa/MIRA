import json
import sys
from uuid import uuid4

import uvicorn

from mira.config.loader import ConfigurationError, load_settings, project_root
from mira.entrypoints.http.app import create_app


_INVALID_FIELDS_PREFIX = "Invalid configuration fields: "
_SAFE_CONFIGURATION_FIELDS = frozenset({
    "http.host", "http.port", "http.allowed_origins",
    "runtime.timeout_seconds", "runtime.max_sessions", "runtime.max_turns",
    "runtime.max_effects", "runtime.journal_capacity",
    "providers.generation", "providers.review", "providers.replay_scenario",
    "providers.mock_delay_ms", "providers.allow_external_calls", "providers.allow_paid_api",
})


def _configuration_diagnostic(error: ConfigurationError) -> dict[str, object]:
    """Return public-safe details without exposing exception text or user values."""
    message = str(error)
    category = "invalid_configuration"
    fields: list[str] = []
    if message.startswith("Missing configuration file: "):
        category = "missing_configuration_file"
    elif message == "Invalid MIRA_PROFILE name.":
        category = "invalid_profile"
    elif message.startswith(_INVALID_FIELDS_PREFIX):
        category = "invalid_fields"
        # Loader validation paths are useful only when they match a known public
        # Settings field. Never forward arbitrary parts of an exception message.
        raw_fields = message[len(_INVALID_FIELDS_PREFIX):].split(", ")
        fields = [field for field in raw_fields if field in _SAFE_CONFIGURATION_FIELDS]

    return {
        "code": "configuration_error",
        "diagnostic_id": str(uuid4()),
        "category": category,
        "fields": fields,
        "message": "Configuration is invalid; startup stopped before opening the server.",
        "recovery": (
            "Check MIRA_PROFILE against config/profiles and review configured MIRA_* names and "
            "values in docs/development/API_ENV.md, then retry."
        ),
    }


def _report_configuration_error(error: ConfigurationError) -> None:
    sys.stderr.write(json.dumps(_configuration_diagnostic(error), separators=(",", ":")) + "\n")


def main() -> int | None:
    try:
        root = project_root()
        dotenv = root / ".env"
        settings = load_settings(root=root, env_file=dotenv if dotenv.is_file() else None)
        app = create_app(settings)
    except ConfigurationError as error:
        _report_configuration_error(error)
        return 2

    uvicorn.run(app, host=settings.http.host, port=settings.http.port,
                workers=1, access_log=False, ws_max_size=32768, ws_max_queue=8)


if __name__ == "__main__":
    raise SystemExit(main())
