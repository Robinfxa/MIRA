"""Run the explicitly admitted, text-first MIRA development app on loopback."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_ADMISSION_BYTES = 32 * 1024
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class EntryError(ValueError):
    """Safe user-facing error; never includes file contents or credentials."""


@dataclass(frozen=True, slots=True)
class AdmissionLimits:
    codex_requests: int
    session_turns: int
    input_jev_requests: int
    output_jev_requests: int
    input_jev_timeout_seconds: float
    output_jev_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class Admission:
    authorized: bool
    route_kind: str
    runtime: object
    limits: AdmissionLimits
    usage_profile: str = "probe"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _bounded_timeout(value: object, name: str) -> float:
    if type(value) not in (int, float) or value <= 0 or value > 30:
        raise EntryError(f"{name} must be finite and between 0 and 30 seconds.")
    if type(value) is float and not math.isfinite(value):
        raise EntryError(f"{name} must be finite and between 0 and 30 seconds.")
    return float(value)


def _count(value: object, name: str, usage_profile: str = "probe") -> int:
    try:
        from mira.bootstrap.development_usage import validate_count
        from mira.config.loader import ConfigurationError

        return validate_count(value, usage_profile, name=name)
    except ConfigurationError:
        maximum = 100 if usage_profile == "application" else 8
        raise EntryError(f"{name} must be an integer between 1 and {maximum}.") from None


def _private_external_file(path: Path, *, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise EntryError(f"{label} must be an absolute path outside the repository.")
    try:
        info = path.lstat()
        repo = ROOT.resolve()
        resolved = path.resolve(strict=True)
    except OSError:
        raise EntryError(f"{label} is unavailable; use a private file outside the repository.") from None
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
            or resolved != path or resolved == repo or repo in resolved.parents
            or not hasattr(os, "getuid") or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise EntryError(f"{label} must be a private owner-only regular file outside the repository.")
    return path


def _read_admission(path: Path) -> Admission:
    path = _private_external_file(path, label="Admission file")
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_ADMISSION_BYTES:
            raise EntryError("Admission file has an invalid size.")
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except EntryError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise EntryError("Admission file is not valid bounded JSON.") from None
    legacy_fields = {"authorized", "route_kind", "runtime", "limits"}
    current_fields = legacy_fields | {"usage_profile"}
    if type(document) is not dict or set(document) not in (legacy_fields, current_fields):
        raise EntryError("Admission file has unknown or missing fields.")
    usage_profile = document.get("usage_profile", "probe")
    try:
        from mira.bootstrap.development_usage import parse_usage_profile
        from mira.config.loader import ConfigurationError

        usage_profile = parse_usage_profile(usage_profile).value
    except ConfigurationError:
        raise EntryError("Admission usage profile is unsupported.") from None
    if document["authorized"] is not True or document["route_kind"] not in ("public", "managed"):
        raise EntryError("Admission file is not explicitly authorized for a supported route.")
    runtime_data = document["runtime"]
    limits_data = document["limits"]
    runtime_fields = {"executable", "codex_home", "runtime_cwd", "environment",
                      "expected_config_sha256", "policy_environment_confirmed",
                      "development_context"}
    limit_fields = {"codex_requests", "session_turns", "input_jev_requests",
                    "output_jev_requests", "input_jev_timeout_seconds",
                    "output_jev_timeout_seconds"}
    if type(runtime_data) is not dict or set(runtime_data) != runtime_fields:
        raise EntryError("Admission runtime fields are unsupported.")
    if type(limits_data) is not dict or set(limits_data) != limit_fields:
        raise EntryError("Admission limit fields are unsupported.")
    if (type(runtime_data["expected_config_sha256"]) is not str
            or _DIGEST.fullmatch(runtime_data["expected_config_sha256"]) is None
            or runtime_data["policy_environment_confirmed"] is not True):
        raise EntryError("Admission is missing its config pin or policy confirmation.")

    from mira.adapters.generation.codex_support.types import (
        ApprovedDevelopmentContext, CodexRuntime,
    )

    route_kind = document["route_kind"]
    context_data = runtime_data["development_context"]
    context = None
    if route_kind == "public":
        if context_data is not None:
            raise EntryError("Public admission must not include managed context fingerprints.")
        environment = runtime_data["environment"]
        if type(environment) is not dict or "CODEX_HOME" in environment:
            raise EntryError("Public admission must not override CODEX_HOME.")
    else:
        context_fields = {"route_value_sha256", "observed_home_mode", "managed_environment_sha256"}
        if type(context_data) is not dict or set(context_data) != context_fields:
            raise EntryError("Managed admission needs its explicit pinned context.")
        try:
            context = ApprovedDevelopmentContext(**context_data)
        except (TypeError, ValueError):
            raise EntryError("Managed admission context is invalid.") from None
    try:
        runtime = CodexRuntime(
            Path(runtime_data["executable"]), Path(runtime_data["codex_home"]),
            Path(runtime_data["runtime_cwd"]), runtime_data["environment"],
            expected_config_sha256=runtime_data["expected_config_sha256"],
            policy_environment_confirmed=True,
            development_context=context,
        )
    except (TypeError, ValueError):
        raise EntryError("Admission runtime is invalid or contains unsupported environment fields.") from None
    if route_kind == "managed" and runtime.environment.get("CODEX_HOME") != str(runtime.codex_home):
        raise EntryError("Managed admission does not pin CODEX_HOME to its approved home.")
    limits = AdmissionLimits(
        _count(limits_data["codex_requests"], "Codex request ceiling", usage_profile),
        _count(limits_data["session_turns"], "Session turn ceiling", usage_profile),
        _count(limits_data["input_jev_requests"], "Input JEV request ceiling", usage_profile),
        _count(limits_data["output_jev_requests"], "Output JEV request ceiling", usage_profile),
        _bounded_timeout(limits_data["input_jev_timeout_seconds"], "Input JEV timeout"),
        _bounded_timeout(limits_data["output_jev_timeout_seconds"], "Output JEV timeout"),
    )
    if limits.codex_requests > limits.session_turns:
        raise EntryError("Codex request ceiling cannot exceed the session turn ceiling.")
    return Admission(True, route_kind, runtime, limits, usage_profile)


def _load_settings(env_file: Path, *, port: int):
    from mira.config.loader import load_settings

    env_file = _private_external_file(env_file, label="Explicit MIRA env file")
    try:
        settings = load_settings(root=ROOT, env_file=env_file, environ={}, overrides={
            "http": {"host": "127.0.0.1", "port": port,
                     "allowed_origins": [f"http://127.0.0.1:{port}",
                                         f"http://localhost:{port}"]},
        })
    except (OSError, ValueError):
        raise EntryError("Explicit MIRA config could not be loaded; values were not printed.") from None
    return settings


def _declared_status(settings, admission: Admission) -> dict:
    return {
        "armed": False,
        "declaration_checked": True,
        "admission_authorized": admission.authorized,
        "route_kind": admission.route_kind,
        "usage_profile": admission.usage_profile,
        "model": "gpt-6-luna",
        "jev_model": settings.services.jev.model,
        "jev_credential_declared": settings.services.jev.api_key is not None,
        "speech_enabled": False,
        "microphone_enabled": False,
        "voice_required_factory": "not_available_in_cli",
        "limits": {
            "codex_requests": admission.limits.codex_requests,
            "session_turns": admission.limits.session_turns,
            "input_jev_requests": admission.limits.input_jev_requests,
            "output_jev_requests": admission.limits.output_jev_requests,
            "input_jev_timeout_seconds": admission.limits.input_jev_timeout_seconds,
            "output_jev_timeout_seconds": admission.limits.output_jev_timeout_seconds,
        },
        "inference": "not_run",
        "live_ready": False,
        "native_metadata_preparation_may_have_contacted_codex": True,
        "quota_or_entitlement_verified": False,
        "spend_dollar_cap": None,
    }


def _check_settings(settings, admission: Admission, *, require_jev: bool) -> None:
    if settings.services.jev.model not in (None, "jev-1.13.0"):
        raise EntryError("This entry is pinned to JEV model jev-1.13.0.")
    if require_jev and settings.services.jev.api_key is None:
        raise EntryError("The explicit env file must declare MIRA_SERVICES__JEV__API_KEY.")
    if require_jev and settings.services.jev.model != "jev-1.13.0":
        raise EntryError("The explicit env file must select JEV model jev-1.13.0.")


def _prepare_frontend() -> None:
    node = shutil.which("node")
    compiler = ROOT / "node_modules/typescript/bin/tsc"
    bundler = ROOT / "node_modules/esbuild/lib/main.js"
    if node is None:
        raise EntryError("Serve requires Node.js 22.12+ installed first; bootstrap cannot install that prerequisite.")
    if not compiler.is_file() or not bundler.is_file():
        raise EntryError("Serve needs the locked TypeScript/esbuild dependencies. Run python tools/bootstrap.py explicitly; no packages were installed.")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("MIRA_") and key not in {
                       "PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY", "TYPESAFE_API_KEY",
                       "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
                       "GOOGLE_CLOUD_QUOTA_PROJECT", "CODEX_ACCESS_TOKEN", "ACCESS_TOKEN",
                       "AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                   }}
    try:
        version = subprocess.run([node, "--version"], cwd=ROOT, env=environment,
                                 check=True, timeout=10, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        version_match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", version.stdout)
        if version_match is None or tuple(map(int, version_match.groups())) < (22, 12, 0):
            raise EntryError("Serve requires Node.js 22.12+; no packages were installed.")
        subprocess.run([sys.executable, str(ROOT / "tools/export_contracts.py"), "--check"],
                       cwd=ROOT, env=environment, check=True, timeout=45,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        subprocess.run([node, str(ROOT / "tools/build_web.mjs")], cwd=ROOT,
                       env=environment, check=True, timeout=90,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except EntryError:
        raise
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise EntryError("Frontend contract/build preparation failed; serve did not start.") from None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "serve"):
        command = subcommands.add_parser(name)
        command.add_argument("--env-file", type=Path, required=True,
                             help="explicit private MIRA .env outside this checkout")
        command.add_argument("--admission", type=Path, required=True,
                             help="private explicit Codex/JEV admission JSON outside this checkout")
        command.add_argument("--port", type=int, default=8000)
        command.add_argument("--memory-db", type=Path,
                             help="existing private local memory SQLite file; default disabled")
        command.add_argument("--memory-scope-config", type=Path,
                             help="private operator-owned scope config outside the checkout")
        command.add_argument("--memory-scope", type=str,
                             help="one local scope alias; never chosen by browser or model")
        command.add_argument("--authorize-memory-to-codex-and-jev", action="store_true",
                             help="allow selected stored evidence to Codex and TypeSafe JEV; does not record dialogue")
        command.add_argument("--authorize-local-memory-management", action="store_true",
                             help="separately permit explicit local save/correct/soft-forget/restore in the paired UI; no automatic recording")
        command.add_argument("--create-local-operator-pairing", action="store_true",
                             help="explicitly create a one-use 0600 pairing file for this memory launch; never printed or placed in a URL")
        if name == "serve":
            command.add_argument("--voice-required", action="store_true",
                                 help="refuse; CLI has no admitted in-process voice bundle")
    return parser


def _memory_options(args):
    values = (args.memory_db, args.memory_scope_config, args.memory_scope)
    authorized = args.authorize_memory_to_codex_and_jev
    pairing_requested = args.create_local_operator_pairing
    if not authorized and all(value is None for value in values):
        if args.authorize_local_memory_management:
            raise EntryError("Local memory management requires explicitly configured memory mode; it does not enable recall or transmission by itself.")
        if pairing_requested:
            raise EntryError("Local operator pairing is available only with explicitly enabled memory recall.")
        return None
    if not authorized or any(value is None for value in values):
        raise EntryError("Memory recall needs all three memory options and explicit consent to send selected stored evidence to Codex and TypeSafe JEV; local recording consent is separate.")
    if not pairing_requested:
        raise EntryError("Memory recall requires --create-local-operator-pairing; serve creates a private one-use file, check creates nothing.")
    from mira.config.loader import ConfigurationError
    from mira.config.memory import load_memory_recall_options

    try:
        return load_memory_recall_options(database=args.memory_db,
            scope_config=args.memory_scope_config, scope_alias=args.memory_scope,
            authorized_transmission=True, checkout_root=ROOT)
    except ConfigurationError as error:
        # These fixed config codes contain no file contents or private scope IDs.
        raise EntryError(str(error)) from None


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    if not args_list:
        print("Unarmed: no configuration or admission files were opened; no provider calls were made.")
        parser.print_help()
        return 0
    try:
        args = parser.parse_args(args_list)
        if not 1024 <= args.port <= 65535:
            raise EntryError("Port must be between 1024 and 65535.")
        if args.command == "serve" and args.voice_required:
            raise EntryError("Voice-required mode needs an admitted in-process voice factory; none is loaded by this CLI.")
        memory_options = _memory_options(args)
        admission = _read_admission(args.admission)
        settings = _load_settings(args.env_file, port=args.port)
        _check_settings(settings, admission, require_jev=args.command == "serve")
        if args.command == "check":
            status = _declared_status(settings, admission)
            if memory_options is not None:
                status["memory_recall"] = {"configured": True, "transmission_authorized": True,
                    "recipients": ["Codex generation", "TypeSafe JEV output review"],
                    "database_opened": False, "automatic_recording": False,
                    "operator_pairing_required": True, "pairing_file_created": False,
                    "local_management_requested": args.authorize_local_memory_management,
                    "local_management_opened": False}
            print(json.dumps(status, sort_keys=True))
            return 0

        _prepare_frontend()
        from mira.adapters.generation.codex_support.types import CodexRuntime
        from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
        from mira.bootstrap.development_app import create_development_app, jev_transport_from_settings
        import uvicorn

        if type(admission.runtime) is not CodexRuntime:
            raise EntryError("Admission runtime did not validate.")
        settings = settings.model_copy(update={
            "http": settings.http.model_copy(update={"host": "127.0.0.1", "port": args.port,
                "allowed_origins": (f"http://127.0.0.1:{args.port}",
                                    f"http://localhost:{args.port}")}),
        })
        pairing = None
        pairing_path = None
        if memory_options is not None:
            from tools.operator_pairing_file import create_pairing_material, PairingFileError
            from mira.entrypoints.http.operator_pairing import OperatorPairing
            try:
                material = create_pairing_material(memory_options.database.parent, checkout_root=ROOT)
                pairing = OperatorPairing(material.code, tuple(settings.http.allowed_origins))
                pairing_path = material.path
                del material
            except (PairingFileError, ValueError):
                raise EntryError("operator_pairing_setup_failed; no memory reader or server was started.") from None
        transport = jev_transport_from_settings(settings)
        app = create_development_app(
            runtime=admission.runtime, settings=settings, route_kind=admission.route_kind,
            input_transport=transport, output_transport=transport, authorized=admission.authorized,
            decision_policy=USER_DEVELOPMENT_0_6_V2,
            usage_profile=admission.usage_profile,
            codex_request_limit=admission.limits.codex_requests,
            session_turn_limit=admission.limits.session_turns,
            input_request_limit=admission.limits.input_jev_requests,
            output_request_limit=admission.limits.output_jev_requests,
            input_timeout_seconds=admission.limits.input_jev_timeout_seconds,
            output_timeout_seconds=admission.limits.output_jev_timeout_seconds,
            **({"memory_options": memory_options, "operator_pairing": pairing,
                "authorize_local_memory_management": args.authorize_local_memory_management}
               if memory_options is not None else {}),
        )
        print("Starting admitted MIRA development app on http://127.0.0.1:" + str(args.port)
              + "; text-only capability enabled; one worker; request ceilings from admission.",
              flush=True)
        if memory_options is not None:
            print("Open the local page and enter the one-use code from this private file: " + str(pairing_path), flush=True)
            print("Pairing expires after five minutes. The code is never printed or included in the URL; restart to obtain a new one. Local attackers with access to your OS account or browser are outside this boundary.", flush=True)
            print("Memory recall enabled: selected manually stored evidence may be sent to Codex generation and TypeSafe JEV output review. Automatic recording remains off.", flush=True)
        if args.authorize_local_memory_management:
            print("Local memory management enabled after pairing: each change needs explicit confirmation. Soft-forget retains original text; enabled recall may later send selected records to Codex/JEV.", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, access_log=False,
                    ws_max_size=32768, ws_max_queue=8)
        return 0
    except EntryError as error:
        print(f"Entry error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    # Tools invoked from the repository root use a fixed source path, never discovery.
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "apps/api/src"))
    raise SystemExit(main())
