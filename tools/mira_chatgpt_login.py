"""Loopback-only SIWC setup page. No authentication starts until an approved user click."""

from __future__ import annotations

import argparse
import hmac
import html
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.mira_auth.oauth import AuthError, CredentialStore, OAuthOwner  # noqa: E402


class LoginServer(HTTPServer):
    def __init__(self, port: int, store: CredentialStore):
        self.owner = OAuthOwner(store)
        self.attempt = None
        self.status = "Prepared; sign-in has not started."
        self.csrf = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), LoginHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class LoginHandler(BaseHTTPRequestHandler):
    server: LoginServer

    def log_message(self, *_):
        pass  # The callback query contains credentials. Never use default request logging.

    def respond(self, status: int, body: str, content_type="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.valid_host():
            self.respond(403, "Invalid host.")
            return
        path = urlsplit(self.path)
        if path.path == "/health":
            self.respond(200, "MIRA_AUTH_LISTENER_OK", "text/plain")
        elif path.path == "/status":
            self.respond(200, json.dumps({"status": self.server.status}), "application/json")
        elif path.path == "/":
            approved = self.server.owner.store.approved
            button = (f'<form method="post" action="/authorize"><input type="hidden" name="csrf" '
                      f'value="{self.server.csrf}"><button>Continue with ChatGPT</button></form>'
                      if approved else "<p>Waiting for explicit permission to store this connection.</p>")
            self.respond(200, '<!doctype html><meta charset="utf-8"><title>MIRA sign-in</title>'
                         '<h1>Connect MIRA to your ChatGPT plan</h1>'
                         '<p>This personal MIRA instance requests identity and plan-usage permission, '
                         'including a refresh token for continued access. It cannot read your ChatGPT chats.</p>'
                         f'<p>Private connection storage: {html.escape(str(self.server.owner.store.root))}</p>'
                         '<p>Review the permissions on OpenAI’s page yourself. Model access is not verified '
                         'until an inference request succeeds.</p>' + button
                         + f'<p>{html.escape(self.server.status)}</p>')
        elif path.path == "/auth/callback":
            attempt = self.server.attempt
            if attempt is None:
                self.respond(400, "No pending sign-in attempt.")
                return
            try:
                self.server.owner.complete(attempt, path.query)
                self.server.status = "Connected; plan permission granted. Inference is not verified."
                self.server.attempt = None
                self.respond(200, '<meta charset="utf-8"><title>MIRA connected</title>'
                             '<h1>MIRA connected</h1><p>You may close this tab. Inference is not yet verified.</p>')
            except AuthError as exc:
                self.server.status = str(exc)
                self.server.attempt = None
                self.respond(400, html.escape(str(exc)))
            except Exception:
                self.server.status = "Sign-in failed safely; no credentials were displayed."
                self.server.attempt = None
                self.respond(500, self.server.status)
        else:
            self.respond(404, "Not found.")

    def do_POST(self):
        if (not self.valid_host() or self.path != "/authorize"
                or self.headers.get("Origin") != self.server.origin):
            self.respond(403, "Cross-origin or invalid request rejected.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 2048:
                raise ValueError
            params = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            if len(params.get("csrf", [])) != 1 or not hmac.compare_digest(
                    params["csrf"][0], self.server.csrf):
                self.respond(403, "Invalid start request.")
                return
            if self.server.attempt is not None:
                self.respond(409, "A sign-in attempt is already pending. Restart the helper to cancel.")
                return
            # Check dependencies before starting authorization or creating any app files.
            import cryptography  # noqa: F401
            import jwt  # noqa: F401
            self.server.attempt = self.server.owner.begin(self.server.origin + "/auth/callback")
            url = self.server.attempt.authorization_url()
            self.server.status = "Waiting for user sign-in and consent."
            self.send_response(303)
            self.send_header("Location", url)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
        except AuthError as exc:
            self.respond(403, html.escape(str(exc)))
        except (ValueError, UnicodeError):
            self.respond(400, "Invalid start request.")
        except ImportError:
            self.respond(503, "PyJWT and cryptography are required before sign-in.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=1455)
    parser.add_argument("--allow-credential-storage", action="store_true",
                        help="Use only after the user approves this exact store and OAuth connection.")
    args = parser.parse_args(argv)
    try:
        store = CredentialStore(args.state_dir, Path(__file__).resolve().parents[1],
                                approved=args.allow_credential_storage)
        with LoginServer(args.port, store) as server:
            print(f"MIRA sign-in page: {server.origin}/", flush=True)
            print("No login or grant starts automatically. Stop with Ctrl+C.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (AuthError, OSError):
        print("MIRA sign-in helper could not start safely; check port and storage permissions.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
