"""Prepare a private dev env; inspect fields offline; optionally GET model catalogs."""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api/src"))
from mira.config.loader import ConfigurationError, load_settings
from tools.api_environment import (
    ServicePreparationError, initialize_private_env, inspect_services, probe_models,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "check", "metadata"))
    parser.add_argument("--env-file", type=Path, help="explicit private file; default is project-root .env only")
    parser.add_argument("--service", nargs="+", choices=("gateway", "jev", "openai"),
                        help="metadata action only; explicit selection authorizes those GET requests")
    args = parser.parse_args()
    if args.service and args.action != "metadata":
        parser.error("--service is only valid for metadata")
    if args.action == "metadata" and not args.service:
        parser.error("metadata requires --service")
    path = args.env_file or ROOT / ".env"
    try:
        if args.action == "init":
            initialize_private_env(ROOT, path)
            print(json.dumps({"status": "blank_private_template_created", "secrets_created": False,
                              "live_ready": False, "next": "Fill local fields; then run check. Never paste credentials into chat."}))
            return 0
        # No parent search; an explicitly missing file is an error, never ignored.
        env_file = path if (args.env_file is not None or path.exists()) else None
        settings = load_settings(root=ROOT, env_file=env_file)
        if args.action == "check":
            report = inspect_services(settings, executable_available=shutil.which("codex") is not None)
            code = 0 if report["core_fields_complete"] else 2
        else:
            report = probe_models(settings.services, args.service)
            code = 0 if all(row["catalog_valid"] for row in report["results"]) else 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return code
    except ServicePreparationError as error:
        print(json.dumps({"status": "blocked", "reason": str(error), "live_ready": False}))
        return 2
    except (ConfigurationError, OSError, ValueError):
        # Do not serialize a raw validation error, path, HTTP body or input value.
        print(json.dumps({"status": "configuration_invalid", "live_ready": False,
                          "next": "Check variable names/aliases and values against the tracked template."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
