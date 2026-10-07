# VOICE-DEFAULT-UNLIMITED

Baseline: verified restored1810 source capture c625aa104cc311712b212bc7c64a4bc14da784cd1420bb42d04910968eddc88e. Owner: providers (new contract file via existing glob); continuous and web consumers. No provider/device requests, credentials or permission changes. TTS/API/image paid ceilings, queues, concurrency, request timeout and Stop fences stay bounded.

### VOICEDEFAULTUNLIMITED-001
Given the direct subscription entry with any selected model, when local voice limits are omitted, text limits and continuous lease duration/sends/starts/recognition streams plus shared STT request budget are true null. Shared attempts continue to count. Explicit finite opt-in values still exhaust exactly; API/TTS/image defaults remain finite.

### VOICEDEFAULTUNLIMITED-002
Given a continuous microphone lease, when a bounded provider RPC reaches its duration, rollover preserves all PCM/finals and waits for a quiet endpoint before submitting a whole utterance. Stop, provider errors and cancellation fence old callbacks without retry storms; text stays available. Two sessions own separate capture state and share one accurate STT counter.

## Compiled browser acceptance
Given a fresh or legacy browser form state, when the app initializes, barge-in is on with a headphone recommendation. Only a current explicit selection persists conservative mode. Default UI omits obsolete count ceilings; a configured finite ceiling and provider quota failures remain factual.
