"""Narrow Sign in with ChatGPT implementation; never reads Codex credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


class AuthError(Exception):
    """Only fixed non-secret messages are safe to expose."""


@dataclass(repr=False)
class Attempt:
    redirect_uri: str
    host_id: str
    client_id: str | None = None
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(64))
    created_at: float = field(default_factory=time.monotonic)
    consumed: bool = False

    def authorization_url(self) -> str:
        callback = urlsplit(self.redirect_uri)
        if (callback.scheme != "http" or callback.hostname != "127.0.0.1"
                or callback.path != "/auth/callback" or callback.query or callback.fragment
                or callback.username or callback.password or not callback.port):
            raise AuthError("Only the exact HTTP loopback callback is supported.")
        params = {
            "client_id": self.client_id or "dynamic_agent_client",
            "ext_agent_host_id": self.host_id,
            "response_type": "code", "redirect_uri": self.redirect_uri,
            "scope": SCOPES, "resource": RESOURCE, "state": self.state, "nonce": self.nonce,
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode(),
        }
        if not self.client_id:
            params["agent_name_hint"] = "MIRA"
        return AUTHORIZE_URL + "?" + urlencode(params)

    def accept_callback(self, query: str) -> tuple[str, str]:
        if self.consumed or time.monotonic() - self.created_at > 600:
            raise AuthError("This sign-in attempt has expired or was already used.")
        if len(query) > 16384:
            raise AuthError("Invalid callback.")
        params = parse_qs(query, keep_blank_values=True)
        if any(len(values) != 1 for values in params.values()):
            raise AuthError("Duplicate callback parameter.")
        state = params.get("state", [""])[0]
        if not hmac.compare_digest(state, self.state):
            raise AuthError("The sign-in state did not match.")
        self.consumed = True
        if "error" in params:
            raise AuthError("Sign-in was not authorized; no code was exchanged.")
        client_id = params.get("client_id", [self.client_id or ""])[0]
        code = params.get("code", [""])[0]
        if not code or not client_id or client_id == "dynamic_agent_client":
            raise AuthError("The callback did not include a complete registration.")
        if self.client_id and client_id != self.client_id:
            raise AuthError("The callback changed the selected registration.")
        if params.get("iss", [ISSUER])[0] != ISSUER:
            raise AuthError("The callback issuer did not match.")
        return code, client_id


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AuthError("Authentication endpoint redirected unexpectedly.")


def request_json(url: str, form: dict | None = None) -> dict:
    """Pinned public endpoints only; never include response bodies in errors."""
    if url not in (TOKEN_URL, JWKS_URL):
        raise AuthError("Authentication endpoint is not approved.")
    data = urlencode(form).encode() if form is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with build_opener(NoRedirect).open(Request(url, data=data, headers=headers),
                                          timeout=30) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise AuthError("Authentication response was too large.")
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                raise AuthError("Authentication response was invalid.")
            return parsed
    except (HTTPError, URLError, ValueError, OSError):
        raise AuthError("Authentication request failed; no credentials were displayed.") from None


def validate_identity(token: str, client_id: str, nonce: str, jwks: dict) -> dict:
    """Verify with PyJWT/cryptography, never custom signature cryptography."""
    try:
        import jwt
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise AuthError("The ID token signature format was not accepted.")
        candidates = [key for key in jwks.get("keys", []) if key.get("kid") == header["kid"]]
        if len(candidates) != 1:
            raise AuthError("The ID token signing key was not found uniquely.")
        key = jwt.PyJWK.from_dict(candidates[0], algorithm="RS256").key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=client_id,
                            issuer=ISSUER, options={"require": ["exp", "iat", "iss", "aud",
                                                               "sub", "nonce"]})
        if not isinstance(claims["nonce"], str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise AuthError("The ID token nonce did not match.")
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise AuthError("The ID token account was invalid.")
        return claims
    except ImportError:
        raise AuthError("PyJWT and cryptography are required before sign-in.") from None
    except AuthError:
        raise
    except Exception:
        raise AuthError("The ID token could not be verified.") from None


class CredentialStore:
    """One app-owned registration. A different account needs a separate store."""

    def __init__(self, root: Path, checkout: Path, approved: bool = False):
        self.root = root.absolute()
        self.checkout = checkout.resolve()
        self.approved = approved
        self._check_path()
        if self.root.resolve().is_relative_to(self.checkout):
            raise AuthError("Credential storage must be outside the checkout.")

    def _check_path(self):
        for item in (self.root, *self.root.parents):
            if item.is_symlink():
                raise AuthError("Credential storage cannot contain symlinks.")
        if self.root.exists():
            info = self.root.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise AuthError("Credential directory ownership is invalid.")
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise AuthError("Credential directory must have mode 0700.")

    def read(self, name: str) -> dict | None:
        self._check_path()
        if name not in ("host.json", "registration.json", "session.json"):
            raise AuthError("Unknown credential record.")
        path = self.root / name
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError:
            raise AuthError("Credential record could not be opened safely.") from None
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1024 * 1024):
                raise AuthError("Credential record permissions or size are invalid.")
            try:
                result = json.load(source)
                if not isinstance(result, dict):
                    raise ValueError
                return result
            except ValueError:
                raise AuthError("Credential record is invalid.") from None

    def write(self, name: str, record: dict):
        if not self.approved:
            raise AuthError("User approval is required before storing this connection.")
        if name not in ("host.json", "registration.json", "session.json"):
            raise AuthError("Unknown credential record.")
        self._check_path()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check_path()
        if (self.root / name).is_symlink():
            raise AuthError("Credential record cannot be a symlink.")
        fd, temporary = tempfile.mkstemp(prefix=".mira-auth-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as target:
                json.dump(record, target)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.root / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def host_id(self) -> str:
        record = self.read("host.json")
        if record:
            try:
                host = record["ext_agent_host_id"]
                if str(uuid.UUID(host.removeprefix("urn:uuid:"))).lower() != host[9:].lower():
                    raise ValueError
                return host
            except (KeyError, ValueError, AttributeError):
                raise AuthError("The saved host identifier was invalid.") from None
        host = "urn:uuid:" + str(uuid.uuid4())
        self.write("host.json", {"ext_agent_host_id": host})
        return host


class OAuthOwner:
    """Reusable auth owner. Construction and prepare mode have no network side effects."""

    def __init__(self, store: CredentialStore, transport=request_json,
                 verifier=validate_identity):
        self.store, self.transport, self.verifier = store, transport, verifier

    def begin(self, redirect_uri: str) -> Attempt:
        if not self.store.approved:
            raise AuthError("User approval is required before starting sign-in.")
        registration = self.store.read("registration.json") or {}
        return Attempt(redirect_uri, self.store.host_id(), registration.get("client_id"))

    def complete(self, attempt: Attempt, query: str) -> dict:
        if not self.store.approved:
            raise AuthError("User approval is required before exchanging credentials.")
        code, client_id = attempt.accept_callback(query)
        self.store.write("registration.json", {"client_id": client_id})
        response = self.transport(TOKEN_URL, {
            "grant_type": "authorization_code", "client_id": client_id, "code": code,
            "code_verifier": attempt.verifier, "redirect_uri": attempt.redirect_uri,
            "resource": RESOURCE,
        })
        id_token = response.get("id_token")
        access = response.get("access_token")
        refresh = response.get("refresh_token")
        if (not all(isinstance(value, str) and value for value in (id_token, access, refresh))
                or response.get("token_type", "").lower() != "bearer"):
            raise AuthError("The token response did not contain the required credentials.")
        claims = self.verifier(id_token, client_id, attempt.nonce, self.transport(JWKS_URL))
        previous = self.store.read("session.json")
        if previous and (previous.get("subject") != claims["sub"]
                         or previous.get("client_id") != client_id):
            raise AuthError("The signed-in account differs from the saved connection.")
        scopes = response.get("scope", "").split()
        if not {"chatgpt.tokens.use.direct", "resource.invoke"}.issubset(scopes):
            raise AuthError("ChatGPT plan usage was not granted; inference remains disabled.")
        expiry = response.get("expires_in")
        if (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
                or not math.isfinite(expiry) or expiry <= 0):
            raise AuthError("The token response expiry was invalid.")
        self.store.write("session.json", {
            "issuer": ISSUER, "subject": claims["sub"], "email": claims.get("email"),
            "client_id": client_id, "ext_agent_host_id": attempt.host_id,
            "id_token": id_token, "access_token": access, "refresh_token": refresh,
            "scopes": scopes, "expires_at": time.time() + expiry,
        })
        return {"connected": True, "plan_usage_granted": True, "inference_verified": False}
