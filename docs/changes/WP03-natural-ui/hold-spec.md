# Resume recognition after a held finalized utterance

Base: immutable frontend1358 and backend1355. Owner: existing web lane. The root requested this narrow follow-on after the backend reproduced a deadlock: a finalized recognizer waits for commit, while the browser withholds the candidate because it overlaps playback. Fresh microphone frames then queue without opening the next bounded recognizer stream.

Given a finalized candidate is retained for manual review, the client may send an exact utterance-token/revision hold acknowledgement through the backend-owned protocol. Its text remains in the visible bounded held-preview list; the operation creates no session Input binding and no model call. A successful acknowledgement allows only the already-declared bounded provider continuation, preserving request and capture caps.

Duplicate readiness and duplicate acknowledgements must not repeat continuation. Conflicts, stale identity, Stop, Close and transport failure preserve retained text and fence old callbacks. The hold operation is independent of automatic commit; no rejected or uncertain hold may become a hidden model retry. Ordinary grace-held activity suffix behavior remains unchanged.

Validation covers controller duplicate/failure/cancellation races, parsed transport correlation, and the separate real ASGI-to-browser-client bridge. This source and its append-only receipts remain separate from frozen1358. No provider or hardware acceptance is implied.

## Deferred hold after an earlier commit

Given a newer finalized candidate arrives while an older commit is pending, it remains visibly held in one explicit candidate queue independent of model-input attempt tracking. When the older commit or hold settles, the client acknowledges the exact current candidate once, including a strictly newer revision of the same attempted token. It never retries a model input. Stop, Close, an already-held tuple and reached commit caps prevent new work; if a newer recognition revision invalidates the queued candidate, capture ends visibly and retains its text. This follow-on is based on immutable frontend1420 and has separate RED/GREEN and ordering-matrix evidence.
