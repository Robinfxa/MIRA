# TRUSTED-LAN-01: explicit trusted private network without pairing

Owner: this isolated implementation; shared HTTP/bootstrap/frontend surfaces have one writer.
Base: MIRA submission ZIP SHA256 761323180bd4b0cba8d34ebe12c7f04c7901f0f4ef8bb153203d357423a2d500, public manifest only.
Blocks: providers (CLI/ASGI contracts), web (compiled gate/controller), architecture; consumers: bootstrap, existing device session isolation, private HTTP boundary. Resources: injected providers, synthetic configuration, no credentials, network service or paid calls. Real device/TLS/provider acceptance remains unrun.

### TRUSTEDLAN01-001
Given explicit --require-device-pairing, private launch requires the existing private pairing directory and two separate one-use codes. The default behavior is superseded by DEFAULT-LAN-01. Existing loopback and memory modes are unchanged.

### TRUSTEDLAN01-002
Given --trusted-private-network-no-pairing with exact private-bind/origin, no pairing directory is accepted or created. Same-origin POST bootstrap issues an opaque process-local browser identity without code entry or claimed pairing. Maximum 16 active trusted identities (paired compatibility remains two); expiry eight hours; restart invalidates them and a fresh bootstrap works. HTTP text acknowledgement, trusted HTTPS for voice, origin/host/WS policy, ephemeral-only memory restrictions and service budgets remain unchanged.

### TRUSTEDLAN01-003
Given two browsers (even with identical client_instance_id), each owns one distinct session. A refresh replaces only its owner's session. Foreign bearer/session/socket access fails, revoked/expired identities lose their sessions, new browser admission fails when the 16-identity resource bound is reached. Stop/close must not activate a late bootstrap result.

### TRUSTEDLAN01-004
Given the trusted-mode page, the compiled frontend automatically establishes its browser identity before starting the actual session controller, displays a persistent network-risk label and no code form, preserves identity on refresh, and ends only its own identity on explicit close. Failure stays stopped and provides recovery.
