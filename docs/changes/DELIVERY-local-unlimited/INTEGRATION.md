# Local-unlimited integration handoff

Base: immutable mira-xiahe-chapter-final-20261006T0721Z, manifest ce4a89d0be9f3e1fe3ea313be554a4adf0c0c2048083fe4fd7562c8a84b75807. Owned files are listed in the sibling manifest. The integration director owns the HTTP schema, generated contracts, browser controls, CLI/config/bootstrap and any merge with private-device HTTP access hunks.

## Operator behavior

Append `--local-unlimited` to the existing `tools/live_provider.py check/serve` command. This selects intentional `None` local turn, lease-duration, commit, lease-start and recognition-renewal limits. It overrides the old local `--turns` and `--listen-max-recognition-streams` quotas. Existing commands without the flag and the probe profile retain their finite defaults. `check` must display `local_interaction_policy=unlimited` and `turn_limit=null`; the local capability UI must show unlimited distinctly from finite service requests.

Google/API/service budgets are unchanged: chosen generation 20, STT 10, TTS 20, images 1 (or an existing smaller selection), finite per-RPC STT duration 120 seconds and per-TTS duration 30 seconds. A provider attempt is consumed irreversibly before dispatch. Failure, Stop, cancellation, browser reconnection and a new local lease do not refund or reset it. A whole application process restart still creates a new process-local technical ledger, as before; no automatic restart or reset is added, and this is not a provider financial ledger.

A long local listening lease rotates finite recognition RPCs, one at a time, using the same shared STT request budget. A duration boundary does not assert speech completion. Bounded PCM carry preserves exact packet order and every accepted final is retained. Natural client-silence settlement after a rollover includes earlier uncommitted final pieces. A half-close that cannot drain reaches the existing finite timeout; provider failures do not auto-retry. Shared service exhaustion produces the closed `service_budget_exhausted` stop reason, retaining recognized draft. Typing remains usable with the remaining generation budget; exhausting generation requests never creates more paid requests.

## Required schema/frontend changes (director-owned)

- `ContinuousListeningReady`: nullable `max_seconds`, `max_samples`, `max_utterances`, `max_streams_per_session`, `max_total_streams`, `max_recognition_streams`.
- Cumulative local counters (session/total lease starts, revisions, commit `segment_seq`, recognition stream index and absolute audio offsets) must not retain the old lifetime quota maxima. Keep integer shape, nonnegative/positive validation, per-message sizes and operational resource limits.
- Add closed `service_budget_exhausted` to stopped reasons; add `pending_capacity` to commit-rejected reasons. A pending-capacity rejection keeps current draft/lease available and requests backpressure recovery, never declares a revoked lease.
- Browser local wall timer and sample total stop only when a finite local limit is present. No finite service remaining budget becomes infinity. No automatic service reopening after exhaustion, errors or explicit Stop.
- Expose `SessionState.retired_user_inputs` and `presentation_floor` as retention metadata if the view displays history. Retention is recent exact context, not total recall. Generated contracts must come from schema export, not manual editing.
- Apply the exact sibling `shared-integration.patch` to the director's shared files; it changes no provider request ledger. HTTP listening-route logic is in the owned patch and intentionally does not alter `_origin_host_allowed`.

## Retention and expiry

In unlimited-local Actor mode, the newest 64 accepted inputs and corresponding reliable provenance are retained. Exact request retries are cached for the newest 64 accepted requests; after expiry the original stale activity is rejected, without redispatch. Retained generation context explicitly states omitted-input count and no complete recall. Latest actual control receipts and recent presentation facts keep original IDs, digests, epochs and receipt data; audio retains the exact newest cumulative software fact per retained effect. A proven complete presentation-prefix watermark prevents retired sequence reuse. Active branch concurrency, maximum effects, single-message sizes and current-turn timeouts remain finite.

Listening retains 64 exact commit results per lease and 128 recent lease identities per session. Expired local identities have no perpetual idempotency guarantee, but cannot recover old one-use input authority or refund/skip a provider attempt. One-use accepted/revoked bindings retire at 128 per session; pending or reserved bindings are never evicted and impose explicit `busy`/`pending_capacity` backpressure. Held unresolved text, finals, endpoint history, queues and provider cleanup remain bounded. No audio/transcript persistence or summary-model call is added.

An explicitly enabled conversation archive must report its prior snapshot saved before live history retirement. If a writer is pending or failed, the new input is rejected with `busy` before acceptance. After the same archive catches up, retry succeeds with absolute original source indices; no accepted input silently disappears from storage. This changes no persistence authorization or database selection.

## Evidence and limits

Directed initial missing-None behavior: three failed and one passed; after implementation all four passed. Additional audio-history test produced its own behavioral RED before exact latest-fact compaction. Final combined offline suite and spec-link results are in verification.md. All evidence uses synthetic text/audio and existing locked dependencies. No credentials, live provider, real database, device, network, installs, deployment, full/release or physical-phone acceptance occurred in this worker.
