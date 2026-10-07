# WP03 recovered voice lineage

Owner: web lane (tests/quality.toml tests/web/*.test.mjs). Consumers: SessionController, continuous listening, actual composer; backend uses the existing continuation DTO. Base: frozen1935 capture 76c514140f2a5eae9576e11279e913c0cfeb82f7294b361e660c442adad25761, 1,224 source files. Resources: shared pinned Node/Python runtime; no installs, services, provider calls, browser, credentials or private data.

Given playback overlaps a supplement, an explicit reply interruption, and a delayed finalized preview held for review, when the user restores that exact preview into an empty composer and sends it, then it is an explicitly reviewed continuation of the original accepted input, with no fabricated ASR commit capability. The original input and actual presentation receipts remain facts.

Capture local session/request/output-epoch causality alongside bounded playback sample ranges before delayed ASR results. Mixed, missing, stale, other-session or superseded targets never silently become the current parent. Recovery uses lease/utterance/revision identity, never text equality. Editing a restored supplement remains visibly marked as reviewed edited text; an explicit new-topic action detaches its target. Stop/Close/error fence old continuations. Ordinary composer messages stay independent. Keep all existing limits, receipt barriers, late-callback and duplicate fences.

New tests run through actual compiled main, controllers, playback and synthetic DOM/transport. This proves software behavior only, not actual device audio or human perception. Full/release and real providers are not run in this isolated slice.

## Explicit post-Stop recovery supplement

An issued local source identity describes the accepted parent; it is not permission to execute. Stop cancels old composer teardown, fact waits and automatic callbacks without declaring a new topic. After Stop, natural reply completion or output-only mute, a fresh reviewed Send may continue the same accepted parent. A known pre-dispatch history failure retains the source and draft for retry, but never bypasses the failed or pending receipt barrier. The source is consumed when a newer input is actually dispatched; uncertain post-dispatch outcomes cannot restore it. The exact HTTP409 `history_pending` contract is a definite pre-acceptance rejection with unconsumed request identity: it restores only that reviewed source for a new manual click, never automatic retry. Close/new session and copied or forged objects remain invalid.
