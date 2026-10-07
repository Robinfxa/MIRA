# Actual request-body resource boundary

### HTTPACTUALBODYLIMIT-001: Actual bytes before private routing
Both HTTP apps bound actual received bodies to32KiB, including missing or understated Content-Length. Oversize input gets a fixed413 error before any endpoint/private factory. Content and secrets are never reflected. Exactly32KiB remains valid; ordinary fragmentation is replayed unchanged to the downstream request parser.

### HTTPACTUALBODYLIMIT-002: Incomplete and non-HTTP streams
Reception is bounded by5seconds and1024fragments. Incomplete slow input gets408; fragment exhaustion gets413. A disconnected request never reaches a private handler. WebSocket/lifespan traffic passes unchanged so microphone streaming is unaffected.

Owner: http lane. No schema/model/credential/network-setting change. A real raw-ASGI pairing request without framing headers exposed the old header-only bypass; that RED is retained in independent and director reports. These are software resource tests, not live-browser acceptance.
