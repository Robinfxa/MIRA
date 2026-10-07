"""Explicit local login/logout controls for MIRA's Codex subscription session.

Run with ``python tools/provider_login.py --help``. Importing this tool never
opens files, sends requests, or starts OAuth.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "src"))

from mira.adapters.auth.openai_codex import CodexAuthError, CodexSessionStore  # noqa: E402


WARNING = (
    "This starts a separate MIRA-owned OpenAI Codex subscription OAuth session. "
    "It is not the public OpenAI API v1 contract; terms, quota, and account eligibility "
    "for this private backend are unknown. No API-key fallback is used."
)
_SAFE_AUTH_ERROR_CODES = frozenset({
    "auth_store_path_invalid",
    "auth_store_must_be_outside_checkout",
    "auth_store_directory_not_private",
    "auth_store_lock_timeout",
    "auth_store_file_not_private",
    "auth_store_unreadable",
    "auth_store_invalid",
    "auth_store_version_unsupported",
    "auth_store_io_error",
    "oauth_token_response_invalid",
    "oauth_endpoint_rejected",
    "oauth_response_too_large",
    "oauth_redirect_rejected",
    "oauth_network_error",
    "device_code_request_failed",
    "device_code_response_invalid",
    "device_code_poll_failed",
    "device_code_denied",
    "device_code_expired",
    "device_code_timeout",
    "oauth_exchange_failed",
    "codex_subscription_login_required",
    "oauth_refresh_failed",
    "auth_backup_unavailable",
})


def _safe_auth_error_code(error: CodexAuthError) -> str:
    return error.code if error.code in _SAFE_AUTH_ERROR_CODES else "auth_operation_failed"


def _confirm(prompt: str, expected: str) -> bool:
    try:
        return input(f"{prompt} Type {expected} to continue: ").strip() == expected
    except (EOFError, KeyboardInterrupt):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--auth-store",
        "--store",
        dest="auth_store",
        type=Path,
        default=None,
        help="MIRA-owned session file path (default: app-private per-user location)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="start a user-approved device-code sign-in")
    commands.add_parser("status", help="read MIRA's local session state without refreshing")
    commands.add_parser("logout", help="disable MIRA's active session locally")
    commands.add_parser("restore-backup", help="explicitly restore a private local backup")
    commands.add_parser("forget", help="permanently remove MIRA's local session and backup")
    args = parser.parse_args(argv)
    store = CodexSessionStore(args.auth_store)
    try:
        if args.command == "login":
            print(WARNING)
            print(f"MIRA local session store: {store.path}")
            if not _confirm("Only continue if you want to sign MIRA into this subscription.", "LOGIN"):
                print("Login cancelled; no device code was requested.")
                return 0

            def show_code(url: str, code: str) -> None:
                # This is the only allowed display of the one-time user code. It is
                # not persisted, logged, or copied into a project artifact.
                print(f"Open {url} and enter this one-time code: {code}", flush=True)
                print("Waiting for approval. Press Ctrl+C to cancel.", flush=True)

            store.begin_device_login(on_user_code=show_code)
            print("MIRA's separate local session was saved. Model access is not verified.")
            return 0
        if args.command == "status":
            print("MIRA Codex subscription session: " + (
                "local session record present" if store.status() else "signed out"
            ))
            print("This checks only MIRA's own store; it does not verify provider validity or contact OpenAI.")
            return 0
        if args.command == "logout":
            if not _confirm(
                "This disables MIRA's local session only. It does not revoke the provider grant; "
                "a private recoverable backup remains.",
                "LOGOUT",
            ):
                print("Logout cancelled; no changes made.")
                return 0
            store.sign_out()
            print("MIRA's local session is signed out. Provider-side revocation is not claimed.")
            return 0
        if args.command == "restore-backup":
            if not _confirm(
                "This restores a previous MIRA-owned local session; it does not contact OpenAI.",
                "RESTORE",
            ):
                print("Restore cancelled; no changes made.")
                return 0
            store.restore_backup()
            print("MIRA's local backup was restored. Model access is not verified.")
            return 0
        if args.command == "forget":
            if not _confirm(
                "This permanently deletes only MIRA's local session and backup. "
                "It does not revoke provider-side tokens.",
                "DELETE",
            ):
                print("Deletion cancelled; no changes made.")
                return 0
            store.discard_local_session()
            print("MIRA's local session and backup were removed. Provider-side revocation is not claimed.")
            return 0
    except KeyboardInterrupt:
        print("Login interrupted; no credentials were printed or persisted.", file=sys.stderr)
        return 130
    except CodexAuthError as exc:
        # Only fixed allowlisted labels and bounded numeric fields may be shown;
        # never print response bodies, headers, arbitrary error values, or tokens.
        code = _safe_auth_error_code(exc)
        print(
            f"MIRA authentication operation failed safely (code: {code}); "
            "no credential details were displayed.",
            file=sys.stderr,
        )
        diagnostic = exc.safe_diagnostic()
        if diagnostic is not None:
            print("MIRA OAuth diagnostic: " + json.dumps(diagnostic, sort_keys=True), file=sys.stderr)
        return 2
    except OSError:
        print(
            "MIRA authentication operation failed safely (code: auth_store_io_error); "
            "no credential details were displayed.",
            file=sys.stderr,
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
