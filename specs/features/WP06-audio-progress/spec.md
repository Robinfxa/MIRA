# WP06 Typed audio presentation progress and bounded media transport

### WP06-001 Speech is not a DOM receipt
Given a reviewed speech effect, when the client sends a legacy instantaneous visual receipt, then it is rejected with `audio_receipt_required`. Audio uses a separate typed software-render fact, never a claim of physical hearing, word alignment or user understanding.

### WP06-002 Exact monotonic audio identity
Given an issued speech effect, when progress is recorded, then effect ID, digest, output epoch and activity must match exactly. Audio and visual facts share one globally distinct local presentation sequence. Identical retransmission is idempotent; sample rate changes, backwards/non-advancing rendered counters, sequence reuse or rewriting a terminal fact fail closed. A session retains at most 4096 append-only audio facts, retaining duplicate detection at capacity. Status is explicitly rendered/completed/interrupted/failed.

### WP06-003 Stop fences and retained partial facts
Given Stop or reliable new input with a local presentation cutoff, when an old progress fact arrives, then it may add history only if at/below the original branch fence. It never restores grants or changes the new phase. The cutoff cannot erase acknowledged audio or visual facts. Partial counters remain in GenerationContext.audio_progress while full speech text is absent from presented_effects until explicit software completion. No counter-to-word inference is allowed.

### WP06-004 Completion and exposure
Given a sealed mixed speech/visual plan, when only one channel finishes, then the plan remains pending. It becomes idle only after completed audio and required visual receipts. Interrupted or failed audio retains established sample evidence without claiming the full text was presented. A current failed/interrupted fact revokes grants; all terminal facts independently cancel matching server synthesis. Old terminal facts remain history only.

### WP06-005 Approved origin-bound speech streaming
Given an injected synthesis provider and a current exact speech grant, when POST speech/{effect_id}/stream is called with session token and digest/epoch/activity, then only the server's approved text is synthesized. No arbitrary text parameter is accepted. One consumed effect cannot be streamed again. Mono PCM16 LE 24 kHz packets are contiguous and at most 12,000 decoded bytes; every outgoing frame rechecks the current actor authority. A completion trailer is distinct from a software-render receipt. Invalid provider format or failure emits a sanitized error and invalidates current output.

### WP06-006 Browser-compatible authenticated microphone
Given a browser WebSocket with allowed Origin and no URL parameters, when its bounded first message supplies a valid session token and exact current activity/input epoch, then it may open one bounded microphone stream. Tokens are never accepted in URLs. JSON/base64 PCM16 mono 16 kHz chunks have sequential packet numbers and contiguous sample offsets, at most 12,000 bytes each, eight queue credits, 60-second duration, and bounded pacing. Invalid identity/format/sequence, overflow and stale activity fail closed. Audio is ephemeral and not persisted.

### WP06-007 Transcripts are not turns
Given microphone audio, when transcription emits revisions, then revisions are returned to that authenticated stream only. Finish drains recognition and returns text/revision/had_final; empty/interim-only endings return no reliable text. Stop/cancel/disconnect/session deletion cancels the operation, including while final recognition drains. Neither a transcript nor completion automatically submits a reliable input or grants a new response.

### WP06-008 Local invalidation and provider lifecycle
Given a running stream, when Stop/new input/failure/session close revokes it, then buffered output is discarded and provider cancellation propagates. A provider that suppresses cancellation cannot emit late data or revive its old branch. A stale failure from a previous generation cannot revoke a newer microphone. HTTP response disconnect and WS teardown close owned iterators; bounded cleanup does not block local revocation indefinitely. Cancellation-resistant operations continue counting against the bounded operation limit until done.

### WP06-009 Explicit composition and truthful capability
Given default app construction, then both voice providers remain absent and media requests fail explicitly without mock audio. Explicit injection exposes presence as injected_unverified, not proven live or device functionality. The admitted Google factory requires caller-provided approved credentials/token source and exact voice settings, composes STT V2 plus gemini-3.8-flash-tts, permits optional quota project and caller-owned HTTP clients, never discovers ADC or reads environment/proxy settings, and closes only resources it owns. App voice_factory construction runs on the application lifespan event loop; construction outside a running loop fails before SDK resource creation. Default HTTP uses verified TLS and trust_env=False. CLI WebSocket ingress is bounded to 32 KiB frames/eight queued frames with access logs disabled.

## Scope, ownership, consumers and resources

Backend integration owns domain/models.py, transitions.py, contracts.py, session_actor.py, media_runtime.py, HTTP schemas/mappers/routes/app, bootstrap providers/container and the narrow CLI WebSocket limits. Frontend integration separately owns the one sink/controller/gate and uses generated types. Schema exports use tools/export_contracts.py only. Existing provider-owned adapters are unchanged.

Primary lanes: domain (test_audio_transitions), http (test_audio_progress, test_voice_http), actor and architecture; affected downstream providers/config/web belong to the director's shared-snapshot integration run. No concurrent full-suite run is launched by this worker. Baseline is the director's recorded 001-http-red source snapshot; 002 uses the identical first ten behavioral tests. Later additions are documented baseline coverage unless a specific RED/GREEN pair exists.

Synthetic test resources only: FastAPI TestClient, explicit test-only generation/review and media providers, deterministic thread/async barriers, temporary test directories and SDK constructor doubles. No credential acquisition, network/provider call, microphone permission, raw-audio persistence, physical device, semantic-reliability or original 164-case product acceptance is claimed.

### WP06-010 Cumulative model context without deleting history
Given many valid cumulative audio progress events for one immutable effect, generation and semantic context carry only its latest exact cumulative sample/status fact. The authoritative session ledger retains every event for audit, duplicate detection and software history. Partial/interrupted/failed facts never become completion or heard words; conflicting effect identities are never merged. Provider byte/effect budgets still fail closed for genuinely oversized context. This corrects the129-event next-turn regression without increasing limits or truncating user obligations.

The authenticated microphone boundary also rejects non-ASCII tokens as an ordinary session mismatch; malformed Unicode retains the DTO invalid-input error. Neither path reflects the supplied token or invalidates the valid session.
