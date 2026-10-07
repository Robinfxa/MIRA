# Natural conversation usability follow-on

Base: immutable v1 frontend `mira-natural-voice-ui-frozen-20261005T1318Z`, paired with strict backend `mira-continuous-natural-frozen-20261005T1312Z`. The v1 evidence remains unchanged. Work is isolated in the v2 directory; no provider, device, account, deployment or additional budget authority is implied.

## Required behavior

1. Preserve the strict source-offset path. Accept additional server endpoint bases only after the backend-owned schema exports their exact discriminants and basis-specific bounds. Short stable-final/VAD grace is described as a heuristic, never exact speech completion. Bounded stream finalization remains distinguishable.
2. Show ordinary listening, recognizing, sending and sent states. Recognition settlement or stream continuation stays visible without presenting every ordinary phrase as a mandatory manual review. Manual send remains available as a fallback; unchanged finite lease and shared request caps remain visible.
3. During owned reply playback, withhold overlapping utterances. Keep that utterance manual-only even when duplicate readiness arrives after playback ends. The explicit “打断回应，继续听我说” action stops only the reply, retains capture, and permits a fresh non-overlapping activity to auto-submit. It does not claim acoustic echo cancellation or automatic voice interruption.
4. After backend acknowledgement, only an explicitly correlated server reset (commit ID, utterance token and exact reset revision) may advance the preview without invalidating its own accepted input. A real newer input, Stop, Close or uncorrelated revision still fences the old operation.
5. Any backend discard/skip needed to isolate a withheld overlap must use its exact utterance identity and retain its text for user review. Never feed the skipped echo to the model. Fresh activities cannot inherit old overlap as permanent manual-only status.

Tests belong to the existing web lane. The v2 source and receipt IDs are separate from v1. Node/DOM, injected audio and ASGI integration establish software behavior only; hardware acoustics, browser activation and real recognizer timing remain unverified.
