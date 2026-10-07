# UI-03 Pending send lifecycle

Base: 0550 plus UI-01 responsive page and UI-02 transport errors. Owner: web (existing tests/web/*.test.mjs quality rule). Consumer: actual compiled main and continuous-listening teardown. No provider calls or browser-pixel acceptance.

### UI03-001 A queued send belongs to its original user intent
A message may wait for microphone teardown. Stop, Close, pagehide, a newer send, or another input intent fences the old continuation before controller.input. Ordinary typing does not cancel an intentional submitted message. Stop restores known-not-sent text only when the draft is still unchanged and empty. A newer draft is never overwritten. Preset commands use the same fence. Controller generation fencing remains independently responsible after dispatch.

Independent original two-test RED and final thirteen-case GREEN are retained by the final integration evidence.

### UI03-002 Capability discovery and closure refresh the same controls
Initial disabled state is recomputed after capabilities arrive, using the last authoritative continuous-listening view. Exhausted starts, capture conflicts, review recording, missing support and closed sessions remain disabled. PTT and continuous buttons cannot become enabled again from a late closed-state publish.
