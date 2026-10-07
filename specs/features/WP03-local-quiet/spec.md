# WP03 Local quiet turn taking

Owner: web lane (tests/web/*.test.mjs); consumers: SessionController, BrowserAudioTransport, main UI; baseline: immutable mira-natural-conversation-capture-20261005T1444Z. Backend schema owner is implement_local_silence_endpoint. No provider, microphone, account, dependencies or device validation. Synthetic PCM and injected clocks only. Output evidence remains outside checkout.

- Given natural readiness explicitly supports client endpoints, when meaningful local sound is followed by 700 ms captured quiet (tunable 250–2000 ms), request bounded server final drain independently of Google END, punctuation, final offsets or ASR timing. Low speech with real ASR text has a backup path; noise alone cannot create Input.
- Given renewed speech before commit, cancel the exact endpoint and keep its text; after accepted input retain correction identity and never automatically retry it.
- Given no final or unavailable drain, show a finite, recoverable status and preserve transcript text. Stop/Close/new lease fence all continuations.
- Given a pending reply, gate only its first dispatch on local quiet. Continued user speech supersedes it. Software PCM overlap is distinct from fetching and remains conservative. The existing single playback queue owns all packets after start.

## Observable cases

- LQ-001: captured quiet requests an endpoint without Google END or final and revisions do not reset silence.
- LQ-002: steady low background before and after speech reaches captured quiet without waiting for lease expiry.
- LQ-003: resumed voice cancels the exact pending endpoint and drain timeout preserves text.
- LQ-004: quiet gates one initial dispatch and keeps all reply packets on the same existing PCM queue.
- LQ-005: voice supplement names the interrupted request and a later ordinary text request remains independent.
