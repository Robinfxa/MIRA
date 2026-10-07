"""Explicitly prepare private metadata pins for MIRA's public Codex runtime."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "tools"))

from codex_native_discovery import (  # noqa: E402
    NativeDiscoveryError,
    resolve_selected_executable,
)

from mira.adapters.generation.codex_support.preflight import (  # noqa: E402
    PreflightDiagnosticError, observe_public_metadata,
)
from mira.adapters.generation.codex_support.types import (  # noqa: E402
    PINNED_VERSION,
    CodexGenerationError,
    CodexLimits,
    CodexRuntime,
    current_codex_platform_pin,
)
from mira.bootstrap.development_usage import (  # noqa: E402
    parse_usage_profile,
    profile_caps,
)
from mira.config.loader import ConfigurationError as _UsageConfigurationError  # noqa: E402

_ENV_KEYS = frozenset((
    "HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "HTTP_PROXY", "HTTPS_PROXY",
    "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "CODEX_PERMISSION_PROFILE", "CODEX_NETWORK_PROXY_ACTIVE",
    "CODEX_SANDBOX_NETWORK_DISABLED",
))
MAX_ADMISSION_BYTES = 32 * 1024
_PROXY_KEYS = frozenset(("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
                         "https_proxy", "all_proxy"))
_AUTH_OR_ROUTE_OVERRIDE_NAMES = frozenset((
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION", "OPENAI_PROJECT_ID", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN",
    "CODEX_REFRESH_TOKEN_URL_OVERRIDE", "TYPESAFE_API_KEY",
))


class PreparationError(ValueError):
    """Fixed setup diagnostic; never include environment values or provider output."""


def _bounded_integer(value: str, *, maximum: int = 8) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if str(number) != value or not 1 <= number <= maximum:
        raise argparse.ArgumentTypeError(f"must be between 1 and {maximum}")
    return number


def _timeout_integer(value: str) -> int:
    return _bounded_integer(value, maximum=30)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Preparation may cause normal native account/catalog metadata traffic. It sends no dialogue, "
        "workspace files, authentication files, model turn, or tool request. The output displays the "
        "exact caller-selected request ceilings; they apply per app invocation in memory, restart "
        "with the same admission starts a fresh allowance, and they are not dollar caps. "
        "Successful metadata preparation does not prove login entitlement, quota, or inference readiness."))
    parser.add_argument("--prepare", action="store_true",
                        help="start the pinned native app-server for bounded metadata only (may contact account/catalog services)")
    parser.add_argument("--codex", type=Path, help="explicit official Codex executable path")
    parser.add_argument("--codex-home", type=Path, help="existing private Codex home")
    parser.add_argument("--runtime-cwd", type=Path,
                        help="existing empty private directory for native process cwd")
    parser.add_argument("--usage-profile", choices=("probe", "application"), default="probe",
                        help="explicit bounded usage profile; default probe preserves the historical 1–8 limits")
    parser.add_argument("--codex-requests", type=str,
                        help="required ceiling, 1–8 for probe or 1–100 for application, per app invocation")
    parser.add_argument("--session-turns", type=str,
                        help="required ceiling, 1–8 for probe or 1–100 for application, per app invocation")
    parser.add_argument("--input-jev-requests", type=str,
                        help="required billable request ceiling, 1–8 for probe or 1–100 for application")
    parser.add_argument("--output-jev-requests", type=str,
                        help="required billable request ceiling, 1–8 for probe or 1–100 for application")
    parser.add_argument("--input-jev-timeout-seconds", type=_timeout_integer,
                        help="required input JEV timeout ceiling, 1–30 seconds")
    parser.add_argument("--output-jev-timeout-seconds", type=_timeout_integer,
                        help="required output JEV timeout ceiling, 1–30 seconds")
    parser.add_argument("--probe-timeout-seconds", type=_timeout_integer, required=False,
                        help="maximum wall time for initialize/config-read metadata handshake")
    parser.add_argument("--confirm-policy-environment", action="store_true",
                        help="confirm this process's applicable OS proxy/certificate policy; separate from content authorization")
    parser.add_argument("--authorize-codex-and-jev-content", action="store_true",
                        help=("authorize entered dialogue and relevant prior application context to "
                              "native Codex/OpenAI and TypeSafe/JEV, plus generated candidate to JEV; "
                              "JEV is billable; request ceilings are per invocation, reset on restart, "
                              "and are not dollar caps"))
    parser.add_argument("--write-admission", type=Path,
                        help="create a new private 0600 admission JSON at this absolute path")
    return parser


def _require_invocation(args: argparse.Namespace) -> None:
    required = ("codex_requests", "session_turns", "input_jev_requests", "output_jev_requests",
                "input_jev_timeout_seconds", "output_jev_timeout_seconds", "probe_timeout_seconds")
    if any(getattr(args, name) is None for name in required):
        raise PreparationError("request_and_timeout_ceilings_required")
    try:
        profile = parse_usage_profile(args.usage_profile)
        caps = profile_caps(profile)
        for name in ("codex_requests", "session_turns", "input_jev_requests", "output_jev_requests"):
            maximum = caps.max_session_turns if name == "session_turns" else caps.max_provider_requests
            value = getattr(args, name)
            # main() and _prepare() both validate. Preserve exact validated ints
            # without interpreting bools or accepting a larger profile ceiling.
            if type(value) is int:
                if not 1 <= value <= maximum:
                    raise argparse.ArgumentTypeError("request ceiling out of range")
            elif type(value) is str:
                value = _bounded_integer(value, maximum=maximum)
            else:
                raise argparse.ArgumentTypeError("request ceiling must be an integer")
            setattr(args, name, value)
    except (ValueError, argparse.ArgumentTypeError, _UsageConfigurationError):
        raise PreparationError("usage_profile_request_ceiling_invalid") from None
    args.usage_profile = profile.value
    if args.codex_requests > args.session_turns:
        raise PreparationError("codex_request_ceiling_exceeds_session_turn_ceiling")
    if not args.confirm_policy_environment:
        raise PreparationError("policy_environment_confirmation_required")
    if not args.authorize_codex_and_jev_content:
        raise PreparationError("content_authorization_required_before_metadata_probe")


def _absolute_existing(path: Path, *, directory: bool) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise PreparationError("runtime_path_must_be_absolute_and_normalized")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError:
        raise PreparationError("runtime_path_missing") from None
    if stat.S_ISLNK(metadata.st_mode):
        raise PreparationError("runtime_path_symlink")
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected:
        raise PreparationError("runtime_path_type_invalid")
    return resolved


def _proxy_is_safe(name: str, value: str) -> bool:
    if name not in _PROXY_KEYS or not value:
        return True
    try:
        parsed = urlsplit(value)
        return (parsed.scheme.lower() in ("http", "https", "socks5", "socks5h")
                and bool(parsed.hostname) and parsed.username is None and parsed.password is None
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def _public_environment(source) -> dict[str, str]:
    # Check key names only; never read, log, or copy API keys and route overrides.
    if _AUTH_OR_ROUTE_OVERRIDE_NAMES.intersection(source):
        raise PreparationError("api_key_or_provider_route_override_present")
    environment = {key: source[key] for key in _ENV_KEYS if key in source and source[key]}
    if any(not _proxy_is_safe(name, value) for name, value in environment.items()):
        raise PreparationError("proxy_userinfo_or_route_parameters_forbidden")
    if any("@" in environment.get(name, "") for name in ("NO_PROXY", "no_proxy")):
        raise PreparationError("proxy_userinfo_or_route_parameters_forbidden")
    return environment


def _resolve_inputs(args: argparse.Namespace, source_environment: dict[str, str]) -> CodexRuntime:
    try:
        platform_pin = current_codex_platform_pin()
    except ValueError:
        raise PreparationError("codex_platform_pin_unavailable") from None
    try:
        executable = resolve_selected_executable(
            args.codex, platform_pin, path_value=source_environment.get("PATH"))
    except NativeDiscoveryError as error:
        raise PreparationError(str(error)) from None
    codex_home_arg = args.codex_home
    if codex_home_arg is None:
        configured_home = source_environment.get("CODEX_HOME")
        codex_home_arg = Path(configured_home) if configured_home else Path.home() / ".codex"
    codex_home = _absolute_existing(codex_home_arg, directory=True)
    if args.runtime_cwd is None:
        raise PreparationError("runtime_cwd_required")
    runtime_cwd = _absolute_existing(args.runtime_cwd, directory=True)
    environment = _public_environment(source_environment)
    runtime = CodexRuntime(
        executable=executable,
        codex_home=codex_home,
        runtime_cwd=runtime_cwd,
        environment=environment,
        executable_sha256=platform_pin.executable_sha256,
        expected_config_sha256=None,
        policy_environment_confirmed=True,
        development_context=None,
    )
    return runtime


def _limits(args: argparse.Namespace) -> dict[str, int]:
    return {
        "codex_requests": args.codex_requests,
        "session_turns": args.session_turns,
        "input_jev_requests": args.input_jev_requests,
        "output_jev_requests": args.output_jev_requests,
        "input_jev_timeout_seconds": args.input_jev_timeout_seconds,
        "output_jev_timeout_seconds": args.output_jev_timeout_seconds,
    }


def _admission_document(runtime: CodexRuntime, limits: dict[str, int], config_sha256: str,
                        usage_profile: str = "probe") -> dict:
    return {
        "authorized": True,
        "route_kind": "public",
        "usage_profile": usage_profile,
        "runtime": {
            "executable": str(runtime.executable),
            "codex_home": str(runtime.codex_home),
            "runtime_cwd": str(runtime.runtime_cwd),
            "environment": dict(runtime.environment),
            "expected_config_sha256": config_sha256,
            "policy_environment_confirmed": True,
            "development_context": None,
        },
        "limits": limits,
    }


def _safe_parent_chain(parent: Path) -> None:
    current = Path(parent.anchor)
    uid = os.getuid()
    for component in parent.parts[1:]:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError:
            raise PreparationError("admission_parent_missing_or_unsafe") from None
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise PreparationError("admission_parent_missing_or_unsafe")
        if metadata.st_uid not in (uid, 0):
            raise PreparationError("admission_parent_missing_or_unsafe")
        writable_by_others = bool(metadata.st_mode & 0o022)
        safe_system_temp = (metadata.st_uid == 0 and bool(metadata.st_mode & stat.S_ISVTX)
                            and current in (Path("/tmp"), Path("/var/tmp")))
        if writable_by_others and not safe_system_temp:
            raise PreparationError("admission_parent_missing_or_unsafe")


def write_admission(path: Path, document: dict, *, content_authorized: bool = False,
                    repo_root: Path = ROOT) -> None:
    """Create one private admission file; reject existing targets and unsafe parents."""
    if (content_authorized is not True or type(document) is not dict
            or document.get("authorized") is not True):
        raise PreparationError("content_authorization_required_before_admission_write")
    if not path.is_absolute() or ".." in path.parts or path.name in ("", ".", ".."):
        raise PreparationError("admission_path_must_be_absolute")
    _safe_parent_chain(path.parent)
    repo = repo_root.resolve()
    target = path.parent / path.name
    if target == repo or repo in target.parents:
        raise PreparationError("admission_file_must_be_outside_repository")
    if target.exists() or target.is_symlink():
        raise PreparationError("admission_file_already_exists")
    data = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if not data or len(data) > MAX_ADMISSION_BYTES:
        raise PreparationError("admission_size_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created = False
    fd = -1
    try:
        fd = os.open(target, flags, 0o600)
        created = True
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            fd = -1
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        raise PreparationError("admission_file_already_exists") from None
    except OSError:
        if fd >= 0:
            os.close(fd)
            fd = -1
        if created:
            try:
                target.unlink()
            except OSError:
                pass
        raise PreparationError("admission_write_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


async def _prepare(args: argparse.Namespace, source_environment) -> dict:
    _require_invocation(args)
    runtime = _resolve_inputs(args, source_environment)
    limits = _limits(args)
    probe_limits = CodexLimits(startup_seconds=args.probe_timeout_seconds,
                               turn_seconds=args.probe_timeout_seconds)
    observed = await observe_public_metadata(runtime, timeout_seconds=args.probe_timeout_seconds,
                                             limits=probe_limits)
    result = {
        "status": "metadata_observed",
        "route_kind": "public",
        "codex_version": PINNED_VERSION,
        "codex_model": "gpt-6-luna",
        "jev_model": "jev-1.13.0",
        "executable_sha256": observed.executable_sha256,
        "config_sha256": observed.config_sha256,
        "environment_sha256": observed.environment_sha256,
        "startup_notifications": dict(observed.startup_notifications),
        "request_ceilings": limits,
        "usage_profile": args.usage_profile,
        "dialogue_sent_during_preparation": False,
        "content_authorized_for_live_text_entry": True,
        "content_flow": ("entered dialogue and relevant prior application context to native "
                         "Codex/OpenAI and TypeSafe/JEV; generated candidate to TypeSafe/JEV"),
        "jev_billable": True,
        "request_ceilings_are_dollar_caps": False,
        "request_ceilings_scope": "per_app_invocation_in_memory; restart_starts_fresh_allowance",
        "inference_verified": "not_run",
        "account_entitlement": "not_assessed",
        "quota_or_dollar_cap": "not_assessed",
    }
    if args.write_admission is not None:
        if not args.authorize_codex_and_jev_content:
            raise PreparationError("content_authorization_required_before_admission_write")
        document = _admission_document(runtime, limits, observed.config_sha256,
                                       usage_profile=args.usage_profile)
        write_admission(args.write_admission, document,
                        content_authorized=args.authorize_codex_and_jev_content)
        result["admission_written"] = True
    else:
        result["admission_written"] = False
    return result


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if not sys.argv[1:]:
        print(json.dumps({"status": "unarmed", "metadata_probe": "not_run",
                          "admission_written": False, "next": "Run --help for explicit setup options."}))
        return 0
    if not args.prepare:
        parser.error("--prepare is required for every setup option")
    try:
        _require_invocation(args)
        result = asyncio.run(_prepare(args, os.environ))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (PreparationError, CodexGenerationError) as error:
        reason = str(error)
        if reason == "codex_executable_drift":
            next_step = ("Use the official native Codex CLI 0.159.2 executable for this platform; "
                         "this helper never updates or re-pins it.")
        elif reason == "codex_native_permissions_blocked":
            next_step = ("A matching native Codex executable was found, but its existing ownership, "
                         "write, execute, or symlink checks blocked it. Resolve the installation "
                         "permission issue through your normal software-management process.")
        elif reason == "codex_native_candidate_missing":
            next_step = ("The official wrapper was recognized, but no matching host-native package "
                         "was found in its known npm locations. Select a verified native executable "
                         "or use a supported official installation.")
        elif reason == "codex_native_candidate_ambiguous":
            next_step = ("More than one matching host-native package was found in the known npm "
                         "locations. Resolve the duplicate package installation and retry.")
        elif reason in {"codex_native_digest_mismatch", "codex_native_platform_mismatch",
                        "codex_native_layout_unexpected", "codex_wrapper_layout_unexpected",
                        "codex_wrapper_symlink_invalid", "codex_wrapper_symlink_unrecognized"}:
            next_step = ("The selected Codex path did not resolve to the verified native executable "
                         "for this host; select a supported official native installation.")
        elif reason == "codex_platform_pin_unavailable":
            next_step = "Use only a platform/architecture with an independently pinned official 0.159.2 binary."
        else:
            next_step = "Check the explicit flags and use the supported native Codex 0.159.2 executable."
        print(json.dumps({"status": "blocked", "metadata_probe": "not_verified",
                          "admission_written": False,
                          "reason": reason, "next": next_step,
                          **({"diagnostic": error.safe_details}
                             if isinstance(error, PreflightDiagnosticError) else {})},
                         sort_keys=True))
        return 2
    except (OSError, ValueError, TypeError):
        print(json.dumps({"status": "blocked", "metadata_probe": "not_verified",
                          "admission_written": False, "reason": "preparation_invalid"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
