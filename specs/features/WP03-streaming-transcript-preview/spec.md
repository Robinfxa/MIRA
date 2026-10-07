# Streaming transcript preview

A live microphone may display bounded recognizer revisions in a dedicated provisional region. They are user input in progress, not assistant output, presented history, or automatic model input.

## Requirements

### STP-001: provisional, stream-bound preview
Given an authenticated microphone stream, when the client receives a valid transcript revision, then an optional typed callback may display its text in a separate listening preview, bounded to 2,000 characters and rendered only as text. Revisions must match the current stream/generation and increase strictly. A preview is visibly labeled provisional and is never copied into the message composer, transcript history, receipts, or model/provider input.

### STP-002: finish is the only causal input boundary
Given interim or segment-final revisions, when the user finishes or cancels capture, then preview is cleared. Only one validated `complete` packet received after the client finish control may resolve the final transcript and enter the existing input path, exactly once. A final revision arriving before finish remains provisional.

### STP-003: invalidate stale preview
Given stop, new input/stream, permission denial, error, disconnect, transport close, or controller close, when local cancellation happens, then preview is cleared immediately and callbacks from older generations/streams are ignored. Existing callers that omit revision callbacks continue to work.

### STP-004: safe ephemeral timing
Given a microphone stream, when local transport stages occur, then the existing view hook may receive only bounded numeric counts, a stream correlation ID, and per-client monotonic elapsed milliseconds for dispatch, first revision, first final revision, client finish, and stream close. Values use the client's monotonic clock from PTT start and are not compared to server monotonic time. The client dispatch value marks browser WebSocket transport construction, not Google provider dispatch; server milestones begin with the server media-operation span. No transcript, PCM, headers, auth, absolute wall-clock values, or persistent raw log are added. Timing never affects input or cancellation.

## Verification scope

Owners: web for the browser callback/UI tests; providers for the existing MediaOperation diagnostic sink test. Consumers: browser audio transport, session controller, listening UI, and server media diagnostics. Resources: synthetic WebSocket, fake monotonic clock, DOM, and fake transcript source. No provider, real microphone, browser navigation, account, or paid call. Base: frozen 2026-10-04T16:59Z capture manifest SHA-256 `9f6e139d7895972aac4826fbd76cec2f56010c949f5146c8af7332d7293b98c2`.
