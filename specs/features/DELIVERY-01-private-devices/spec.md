# DELIVERY-01: Explicit private two-device access

Base: immutable mira-xiahe-chapter-final-20261006T0721Z. Owner: private network/pairing slice.
Consumer: direct-provider launcher, HTTP and WebSocket admission, existing pairing UI.
Resources: offline Python/Node environment and synthetic ASGI only; no listening socket, providers, private files or certificate installation.
Tests: providers via existing tests/contracts/test_*.py unique owner in tests/quality.toml; HTTP/architecture affected integration.

### DELIVERY01-001: Default off and exact private authority
Given default loopback, when no private mode is requested, localhost behavior is unchanged. Explicit private mode binds only one private literal address and accepts exactly one canonical origin, scheme, host and port. Wildcard/public binds, mismatched ports, duplicate authorities, cross-origin and proxy-header spoofing fail before runtime.

### DELIVERY01-002: Separate temporary browser admission
Given two separate one-use private codes, when a browser pairs, only that browser receives a time-limited HttpOnly SameSite Strict cookie, Secure on HTTPS. No token enters URL/log. Wrong origins, reuse, expired/revoked credentials and unpaired session/socket creation fail. Cancelling one device must close its sessions without cancelling the other. Shared persistent memory/history remain single-operator only.

### DELIVERY01-003: Honest phone voice prerequisite
Given explicit private HTTP, when voice is requested, startup fails with trusted HTTPS guidance. HTTPS requires existing operator-provided cert/key paths and an exact URL whose certificate the devices already trust. No tunnel, trust/certificate/OS/firewall changes or deployment are performed. Actual phone/browser/microphone verification remains open.
