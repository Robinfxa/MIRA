"""Offline, synthetic auth tests; no account, secrets, or network required."""

import os
import tempfile
import threading
import time
import unittest
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from tools.mira_auth.oauth import (
    ISSUER,
    RESOURCE,
    SCOPES,
    Attempt,
    AuthError,
    CredentialStore,
    OAuthOwner,
    validate_identity,
)
from tools.mira_chatgpt_login import LoginServer


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.attempt = Attempt("http://127.0.0.1:1455/auth/callback", "urn:uuid:test")

    def test_registration_uses_actual_app_and_pkce(self):
        params = parse_qs(urlsplit(self.attempt.authorization_url()).query)
        self.assertEqual(params["client_id"], ["dynamic_agent_client"])
        self.assertEqual(params["agent_name_hint"], ["MIRA"])
        self.assertEqual(params["resource"], [RESOURCE])
        self.assertEqual(params["scope"], [SCOPES])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertNotIn(self.attempt.verifier, self.attempt.authorization_url())

    def test_returning_login_reuses_registration(self):
        self.attempt.client_id = "oaiapp_synthetic"
        params = parse_qs(urlsplit(self.attempt.authorization_url()).query)
        self.assertEqual(params["client_id"], ["oaiapp_synthetic"])
        self.assertNotIn("agent_name_hint", params)

    def test_valid_callback_retains_issued_registration(self):
        query = urlencode({"state": self.attempt.state, "code": "synthetic-code",
                           "client_id": "oaiapp_synthetic"})
        self.assertEqual(self.attempt.accept_callback(query),
                         ("synthetic-code", "oaiapp_synthetic"))

    def test_wrong_state_and_duplicate_state_are_rejected(self):
        with self.assertRaises(AuthError):
            self.attempt.accept_callback("state=wrong&code=test&client_id=oaiapp_test")
        with self.assertRaises(AuthError):
            self.attempt.accept_callback(urlencode({"state": self.attempt.state})
                                         + "&state=wrong&code=test&client_id=oaiapp_test")

    def test_denial_and_registration_swap_are_rejected(self):
        with self.assertRaises(AuthError):
            self.attempt.accept_callback(urlencode({"state": self.attempt.state,
                                                   "error": "access_denied"}))
        self.attempt.client_id = "oaiapp_existing"
        with self.assertRaises(AuthError):
            self.attempt.accept_callback(urlencode({"state": self.attempt.state,
                                                   "code": "test", "client_id": "oaiapp_other"}))

    def test_used_callback_cannot_be_replayed(self):
        query = urlencode({"state": self.attempt.state, "code": "synthetic-code",
                           "client_id": "oaiapp_synthetic"})
        self.attempt.accept_callback(query)
        with self.assertRaises(AuthError):
            self.attempt.accept_callback(query)

    def test_non_loopback_and_changed_callback_path_are_rejected(self):
        for uri in ("http://localhost:1455/auth/callback", "https://example.com/auth/callback",
                    "http://127.0.0.1:1455/callback", "http://127.0.0.1:1455/auth/callback?q=x"):
            with self.subTest(uri=uri), self.assertRaises(AuthError):
                Attempt(uri, "urn:uuid:test").authorization_url()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.checkout = self.base / "checkout"
        self.checkout.mkdir()
        self.root = self.base / "private"

    def test_unapproved_owner_cannot_start_or_create_files(self):
        store = CredentialStore(self.root, self.checkout)
        with self.assertRaises(AuthError):
            OAuthOwner(store).begin("http://127.0.0.1:1455/auth/callback")
        with self.assertRaises(AuthError):
            store.write("session.json", {"synthetic": True})
        self.assertFalse(self.root.exists())

    def test_atomic_private_store_and_stable_host(self):
        store = CredentialStore(self.root, self.checkout, approved=True)
        host = store.host_id()
        self.assertEqual(host, store.host_id())
        store.write("session.json", {"synthetic": True})
        self.assertEqual(store.read("session.json"), {"synthetic": True})
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "session.json").stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob(".mira-auth-*")))

    def test_checkout_and_symlink_stores_are_rejected(self):
        with self.assertRaises(AuthError):
            CredentialStore(self.checkout / "auth", self.checkout)
        self.root.symlink_to(self.checkout, target_is_directory=True)
        with self.assertRaises(AuthError):
            CredentialStore(self.root, self.checkout)

    def test_world_readable_credentials_are_rejected(self):
        store = CredentialStore(self.root, self.checkout, approved=True)
        store.write("session.json", {"synthetic": True})
        os.chmod(self.root / "session.json", 0o644)
        with self.assertRaises(AuthError):
            store.read("session.json")

    def test_missing_plan_scope_never_saves_session(self):
        store = CredentialStore(self.root, self.checkout, approved=True)
        def transport(url, form=None):
            if form is None:
                return {"keys": []}
            return {"id_token": "synthetic-id", "access_token": "synthetic-access",
                    "refresh_token": "synthetic-refresh", "token_type": "Bearer",
                    "scope": "openid", "expires_in": 3600}
        owner = OAuthOwner(store, transport=transport,
                           verifier=lambda *_: {"sub": "synthetic-user"})
        attempt = owner.begin("http://127.0.0.1:1455/auth/callback")
        with self.assertRaisesRegex(AuthError, "plan usage was not granted"):
            owner.complete(attempt, urlencode({"state": attempt.state, "code": "synthetic",
                                               "client_id": "oaiapp_synthetic"}))
        self.assertIsNone(store.read("session.json"))

    def test_completion_returns_safe_metadata_only(self):
        store = CredentialStore(self.root, self.checkout, approved=True)
        calls = []
        def transport(url, form=None):
            calls.append((url, form))
            if form is None:
                return {"keys": []}
            return {"id_token": "synthetic-id", "access_token": "synthetic-access",
                    "refresh_token": "synthetic-refresh", "token_type": "Bearer",
                    "scope": SCOPES, "expires_in": 3600}
        owner = OAuthOwner(store, transport=transport,
                           verifier=lambda *_: {"sub": "synthetic-user"})
        attempt = owner.begin("http://127.0.0.1:1455/auth/callback")
        result = owner.complete(attempt, urlencode({"state": attempt.state, "code": "synthetic",
                                                    "client_id": "oaiapp_synthetic"}))
        self.assertEqual(result, {"connected": True, "plan_usage_granted": True,
                                  "inference_verified": False})
        self.assertEqual(calls[0][1]["redirect_uri"], attempt.redirect_uri)
        self.assertEqual(calls[0][1]["client_id"], "oaiapp_synthetic")


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError as exc:
            raise unittest.SkipTest("PyJWT/cryptography not installed in this interpreter") from exc
        cls.jwt = jwt
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key(), as_dict=True)
        jwk["kid"] = "synthetic-test-key"
        cls.jwks = {"keys": [jwk]}

    def token(self, **changes):
        claims = {"iss": ISSUER, "aud": "oaiapp_test", "sub": "synthetic-user",
                  "nonce": "synthetic-nonce", "iat": int(time.time()),
                  "exp": int(time.time()) + 60}
        claims.update(changes)
        return self.jwt.encode(claims, self.key, algorithm="RS256",
                               headers={"kid": "synthetic-test-key"})

    def test_valid_signature_identity_and_nonce(self):
        claims = validate_identity(self.token(), "oaiapp_test", "synthetic-nonce", self.jwks)
        self.assertEqual(claims["sub"], "synthetic-user")

    def test_wrong_audience_issuer_nonce_and_expiry_fail_closed(self):
        for claims in ({"aud": "other"}, {"iss": "https://example.com"},
                       {"nonce": "wrong"}, {"exp": int(time.time()) - 10}):
            with self.subTest(claims=claims), self.assertRaises(AuthError):
                validate_identity(self.token(**claims), "oaiapp_test", "synthetic-nonce", self.jwks)


class PreparedListenerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.private = base / "private"
        self.server = LoginServer(0, CredentialStore(self.private, base / "checkout"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        with closing(HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)) as connection:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read().decode()

    def test_prepare_is_read_only_and_page_has_no_sign_in_button(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn("<button>", body)
        self.assertIn(("Cache-Control", "no-store"), headers)
        self.assertFalse(self.private.exists())
        self.assertIsNone(self.server.attempt)

    def test_rebinding_host_and_cross_origin_start_are_rejected(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("POST", "/authorize", body="csrf=wrong",
                                      headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertFalse(self.private.exists())

    def test_unapproved_start_and_callback_never_create_credentials(self):
        self.assertEqual(self.request("POST", "/authorize", body="csrf=" + self.server.csrf,
                                      headers={"Origin": self.server.origin})[0], 403)
        status, _, body = self.request("GET", "/auth/callback?code=synthetic-private-code")
        self.assertEqual(status, 400)
        self.assertNotIn("synthetic-private-code", body)
        self.assertFalse(self.private.exists())


if __name__ == "__main__":
    unittest.main()
