# WP03: Click-start continuous listening lease

Status: bounded backend/session core with an explicit manual-turn control. This does not prove a real browser/device/provider session or acoustic echo cancellation.

## Intent

A deliberate click starts one finite microphone lease and one continuous STT stream. Silence does not stop the lease. Interim revisions and stable finals are provisional display text only; they never become Actor history, memory or a model/provider request by themselves. Google V2 speech-activity events and result offsets are retained for display hints only in this first version. They do not authorize input boundaries, since delayed final pieces can arrive after a VAD END.

The user explicitly chooses “send current utterance.” The client sends the exact currently displayed transcript revision plus a unique commit ID. The backend verifies that revision is still current, requires a nonempty stable-final suffix, and creates one exact one-use binding to the text. The frontend then submits through the existing `SessionController.input()`/`/inputs` path with its current `activity_seq`, presentation cutoff and receipt-prefix barrier. The microphone lease remains open after a manual commit. New interim/final text stays visible until the next manual commit or stop. A late tail is never silently discarded or automatically submitted as a second turn.

Continuous listening lifetime is independent of reply-turn activity/input/output epochs; ordinary PTT keeps existing actor epoch checks. Global Stop, lease Stop, permission loss, disconnect, deletion and app shutdown revoke the active microphone lease. Stop also revokes any commit ID not yet accepted by Actor.submit; exact retries of an input already accepted by the Actor remain idempotent.

## Given/When/Then

### WP03-001 Explicit authenticated lease
  - Given exact configured Origin/Host and a valid session ID, when a client sends first-frame `{type:"start",session_token,lease_id}` with no query string, then the server binds one unique lease to the authenticated session.
  - Given malformed/duplicate JSON, invalid token, invalid Origin/Host, any query parameter or missing continuous backend, when the WebSocket starts, then it is rejected before an STT stream can be dispatched.
  - Given a new lease for a session, when an older lease is active, then the older stream is cancelled and cannot publish transcript revisions afterward.
### WP03-002 Silence remains active
  - Given a ready lease, when the microphone sends silence PCM or no recognized speech arrives, then the WebSocket remains open until explicit stop, disconnect, session teardown or the visible finite cap.
### WP03-003 Transcripts are provisional
  - Given interim or final provider transcript results, when they arrive, then the backend emits monotonic current-pending transcript previews only; no Actor input, generation, memory, or per-word provider call occurs.
  - Given an offset-matched Google `SPEECH_ACTIVITY_END` and stable final result, when both are available, then the server may emit an `endpoint_pending` display hint only; no automatic input is submitted.
  - Given missing offsets, orphan activity END, a late result piece or a stale displayed revision, when a manual commit is requested, then the current preview remains available and the server rejects stale/no-final commits instead of silently losing or duplicating text.
### WP03-004 Manual one-use commit
  - Given the current display revision has stable final text, when the user explicitly sends `{type:"commit",lease_id,commit_id,revision}`, then the server atomically binds that `commit_id` to the exact text, lease, session and next segment sequence and returns `commit_ready`.
  - Given the same commit ID and revision again, when that exact commit result exists, then the same ready snapshot is returned. Reuse with a different revision/body is rejected. Delivery of that cached snapshot remains idempotent while its binding is pending, reserved or accepted; it never resets the consumed request identity or creates another Actor input. Revoked unaccepted bindings, another lease/session, changed revision and changed input request/body remain rejected.
  - Given the standard `/inputs` request contains `listening_utterance_id`, when its commit frame was delivered, then validation reserves that ID for only this exact request ID/text. `Actor.submit` success marks it accepted. Actor rejection leaves a retry reservation only while live; Stop revokes any not-accepted reservation. Exact accepted input retries remain idempotent after Stop.
  - Given a manual commit is accepted while the lease is active, when the stable suffix is cleared from the preview, then the microphone stream stays active, and subsequent transcript tails appear as fresh current-pending text for another explicit manual commit.
### WP03-005 Turn epoch isolation
  - Given a valid listening lease, when a normal Actor reply/new input advances activity/input/output epochs, then the lease remains active. Stop and teardown explicitly close it.
### WP03-006 Finite resource caps and visible end
  - One active lease/session; default lease limit 120 seconds (clamped to profile/provider max), <=1,920,000 PCM16 samples, <=12 manual commits, 2,000 code points of current pending text, <=12,000 bytes/chunk, audio queue <=8 packets, event queue <=32, revisions <=10,000; one provider stream per lease and no retry/rollover.
  - When any duration, sample, queue, output, revision, manual-commit or per-session/application lease-start ceiling is reached, then the server sends a visible stop/rejection and revokes the active microphone.
  - Counts are technical lease starts/reservations, not billed dollars; no live provider/account call was made for tests.

### WP03-007 Shared PTT/continuous STT attempt ceiling
  - Given an explicitly admitted provider bundle, when PTT and continuous listening alternate or start concurrently, then both reserve from the exact same irreversible per-launch STT counter; empty/invalid first audio does not consume an attempt; a valid reservation is never refunded after cancellation or an unknown outcome.
  - Given an application profile declares up to100 STT attempts, when the continuous lease starts, then its finite application lease-start cap is set from that same declaration instead of silently retaining the old probe ceiling8; probe remains capped at8.
- **Evidence:** synthetic wrappers/adapters only, no real billing or live service call.

### WP03-008 Overload and commit-cap terminal events
  - Given a bounded output queue is full, when a revision cannot be enqueued, then previews are discarded and the client still receives a visible `stopped(output_limit)` terminal frame.
  - Given the per-lease manual commit count reaches its cap, when the final allowed snapshot is returned, then it remains submit-capable through history-pending/accepted retry semantics and a visible `stopped(utterance_limit)` follows; no extra automatic user turn is generated.


## Frontend behavioral requirements

See [continuous UI specification](spec-web.md) and traceability-web.json; these Node cases are executed by the web lane, not Python collection.

### WP03-009 Terminal preview retention and duplicate final callbacks
  - Given production Google SDK finals arrive after an activity END, when EOF or a provider failure follows before the HTTP writer can drain its queue, then the latest already-observed preview is sent once before the terminal frame. It remains provisional, has its original revision/finality, and creates no commit or Actor input.
  - Given a final callback repeats the same offset and text after newer interim text, when it is received, then neither the interim preview nor its revision changes. Identical words at a new offset remain a new occurrence.
  - Given explicit Stop, permission loss, replacement, disconnect, or Close, when a late callback or terminal write races with cancellation, then no old transcript is revived. Recovery uses a new explicit input; no provider retry or automatic lease rollover occurs.
  - Owner: continuous lane (existing unit and integration test files); consumers: HTTP WebSocket and continuous UI. Base: immutable 0703 restore (1,134 files). Resources: synthetic PCM, installed Google SDK response objects, local ASGI only; no provider/auth/browser/device calls. Directed evidence is appended outside the source snapshot.

### WP03-010 Explicit natural mode with proved audio coverage
  - Given a client explicitly starts `mode: natural` on a capable continuous backend, when the latest BEGIN/END activity has no active speech, no outstanding interim, and no incomplete provider batch, then automatic eligibility additionally requires every pending final portion to have known increasing offsets belonging to that same activity, exact full pending-text coverage, and a final offset at or beyond END within accepted PCM.
  - Given that evidence, when the endpoint is ready, then emit one `utterance_ready` with a deterministic lease-scoped utterance UUID, exact global lease revision, text and BEGIN/END/final offsets. This is eligibility only: it does not itself create an Actor input.
  - Given the client sends an automatic `commit` with that utterance UUID, an independent commit UUID and the exact revision, then revalidate the current endpoint under the state lock and bind the existing one-use input authority. A newer BEGIN, interim, final, Stop or replacement rejects the obsolete candidate. The commit-ready response echoes the utterance UUID. Manual fallback omits it; old clients default to manual mode.
  - Given missing, out-of-order, cross-activity or incomplete offset evidence, when speech pauses or punctuation appears, then remain in provisional/manual fallback. Neither a proximity tolerance nor an arbitrary timer proves complete speech coverage. Final offsets are not guaranteed to align with Google VAD offsets, so not every real sentence is guaranteed automatic eligibility.
  - Given one SDK response contains final and interim portions, then validate its entire structure before yielding, retain both batch-complete and pending-interim flags, and concatenate all consecutive interim portions. Illegal multiple-final or final-after-interim Google batches fail before exposing any partial candidate.

### WP03-011 Late natural revisions retain original identity
  - Given a natural snapshot has been issued, when another nonduplicate final belongs to that activity, then retain the full amended original utterance with the same utterance UUID and commit UUID in `utterance_revision`; never append it to the next automatic turn.
  - Given a pending or reserved binding, when its text is amended, then revoke that binding and report its observed submission state. Given Actor already accepted it, then preserve actual accepted history and its exact retry authority. A reserved state is not proof that an in-flight Actor submission could not subsequently accept; the existing Actor acceptance boundary is not made atomic by this change.
  - Given a late correction and a newer current interim both await terminal delivery, then retain both bounded entities before EOF/error, each once by its own revision identity. Stop/permission loss/replacement/disconnect/Close clear both retained terminal forms.
  - Corrections always require review; they are never automatically submitted as second inputs. No provider model, authentication, request count, stream rollover or paid-call authorization changes.

Natural-mode implementation ownership: continuous application/HTTP/SDK and the
additive continuous port/schema/exported contracts are coordinated with the
integration owner. Existing unit/HTTP tests remain uniquely owned by the
continuous lane; SDK tests remain in providers. Shared wire/port changes require
merged full affected selection. Base is immutable terminal-fix1251, itself based
on the verified0703 restore. All directed receipts remain external to source.

### WP03-012 Natural grace and bounded recognition continuation
  - In explicit natural mode, preserve exact offset coverage as a fast path. A separately labeled `vad_final_grace` candidate may use configured provider-VAD/stable-final quiet grace without claiming mathematical or semantic completion. Fresh activity, interim, final revisions and cancellation reset or fence that decision.
  - Missing-offset or still-interim ENDs may half-close requests after grace and drain responses to clean EOF. Only a complete single-activity stream without unresolved interim/conflicting evidence yields `stream_finalized`; no arbitrary timeout counts as finality.
  - Captured continuation PCM remains bounded by 32,000 samples/64,000 bytes and, independently,200 packets including carried items. Resume only after the sealed snapshot is consumed, at the exact first not-yet-forwarded global sample, with per-RPC rebasing and no overlap/replay.
  - Every resumed RPC enters the existing irreversible shared STT reservation wrapper. Quiet streams expose the actual reserved used/remaining snapshot. No refund, lease duration/sample reset, cap increase, unlimited stream rollover or new provider authorization occurs. Exhaustion/drain timeout/overflow ends visibly and preserves observed text.
  - Effective provider/declaration caps constrain the actual audio buffer as well as the advertised limit. Substream count, grace and drain timeout are finite declared controls, never dollar budgets.

### WP03-013 Independent activity retention and recovery
  - A withheld older activity remains recoverable, while a new unambiguous activity can submit only its own suffix. Its commit/reset identifies the exact commit and utterance, so retained older preview text or a correlated reset cannot silently cancel a valid new input.
  - A natural VAD/final-grace gap may produce only a labeled heuristic attribution; it cannot silently become strict offset proof. Orphan results in a new RPC remain provisional, never revise a previous RPC's committed utterance.
  - Exact commit replay remains deliverable after reservation/acceptance without creating another Actor input; revoked or wrong-session/lease identities remain rejected.
  - Finite-limit terminal previews remain reachable by later global Stop/replacement/Close, which fence them before an outstanding writer can publish stale data. Queue overflow sends a typed visible terminal event, not an unclassified disconnect.

### WP03-014 Non-destructive held-drain continuation
  - Given a sealed stream-finalized candidate is withheld by the UI, an exact authenticated `hold(lease_id, utterance_id, revision)` retains its text without an Input binding, model turn or episode. It releases finite continuation only after the `utterance_held` success frame has been sent.
  - Exact active tuple replay returns the same held snapshot without reopening another RPC. Changed token/revision, stale candidate, revoked lease or exhausted retained-item cap rejects explicitly. Stop/Close rejects even a previously acknowledged tuple.
  - The held token cannot later become an automatic commit. New activity can independently submit its suffix even if the retained old final lacked offsets; old text remains recoverable and unsubmitted. A prior held END cannot authorize draining a new RPC that has not observed its own activity.
  - Lost/failed hold acknowledgment creates no automatic model retry and does not start another RPC. Both current preview and locally retained held text stay reviewable; raw-audio and request budgets are neither reset nor refunded.

A later missing-offset activity in the same RPC may finalize after clean drain when all earlier activities already had strictly offset-covered snapshots through their END. Earlier grace-only/ambiguous gaps do not obtain this authority; one unresolved activity remains the limit.

### WP03-015 Client quiet requests bounded recognition finalization
  - Given an authenticated natural-mode start explicitly selects `client_endpointing: true`, when Google emits BEGIN, END or a final result, then these remain transcript/activity data until a client endpoint request; provider VAD grace cannot submit early or strand the lease waiting for a premature commit.
  - Given local microphone speech followed by the configured quiet interval, when the client sends `client_endpoint` with a unique endpoint ID and its exact sent-sample frontier, then the backend half-closes only after all PCM through that frontier is consumed. This request conveys UI intent, not semantic proof of speech, and never creates an Actor/model input by itself.
  - Given the bounded RPC drain completes with stable nonempty final text, when BEGIN, END, or result offsets were omitted, then emit `client_silence_finalized` with the exact endpoint ID, lease-scoped utterance/revision and bounded source interval. The ordinary exact commit and normal `/inputs` binding still apply.
  - Given speech resumes while the endpoint is queued, when its exact cancellation is received, then preserve PCM and the current stream; a replacement ID may choose a newer frontier. Once half-close starts it is irreversible: the status remains draining/completed and the UI holds that exact finalized candidate if speech resumed.
  - Given no stable final, empty/non-speech labels, incomplete text, failed delivery or an unresponsive provider, then terminate visibly with recoverable preview under the existing deadline rather than listening indefinitely. The default700ms local quiet is configurable250–2000ms and heuristic; the queue-to-drain timeout remains2 seconds by default, bounded100–5000ms.
  - Given repeated endpoint/commit/hold controls or late final callbacks, then preserve idempotence and exact original-utterance correction linkage; never silently create a second input, erase accepted input, or refund/increase the shared STT attempt counter. Continuation uses only existing explicit stream/time/count caps; legacy manual and natural clients remain compatible.
  - Owner: existing continuous lane test files; consumers: WebSocket route, generated contracts, quiet frontend and normal input barrier. Base: immutable1444 capture. Resource: installed Google DTOs, fake streaming RPC, synthetic PCM, local ASGI; no credentials/provider/microphone/browser/install or acoustic acceptance.


2026-10-06 default-overlap correction under WP03-015 (supersedes overlap-only manual gating):
  - Given the default natural mode and speech while reply PCM plays, when the early energy detector does not trigger or its stop attempt fails, then continue collecting the same phrase and quiet clock. At the normal qualified final endpoint, synchronously stop only the old reply before awaiting exact commit; submit its complete text once and preserve exact request continuation when recorded.
  - Given continuous speech or a resumed phrase, then do not submit its partial prefix; cancel/fence an older endpoint and preserve current text. Given a same-utterance duplicate/correction, Stop, Close or a newer input, then do not revive or duplicate the old final.
  - Given an explicit guarded mode, then overlap may require manual review. Default mode requires no acoustic classification or detector-success proof. Pure silence adds no endpoint; existing lease/sample/utterance and shared STT/TTS/generation limits remain unchanged, with no automatic renewal and ordinary text available after voice ends.
  - Owner: existing web lane (`tests/web/*.test.mjs`, unique owner in quality.toml). Consumers: compiled main, SessionController, ContinuousListeningController, capture/playback and unchanged commit protocol. Base: frozen response-contract source 20261006T0522Z. Resources: reused locked Node/Python runtime, synthetic PCM and transport only. No live services, credentials, user microphone, recordings or installations. Targeted RED/GREEN and affected-lane evidence are external to source; this is not device/acoustic acceptance.
