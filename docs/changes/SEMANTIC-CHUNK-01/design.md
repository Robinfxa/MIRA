# Bounded post-completion semantic caption planning

Base: immutable `mira-conversation-first-capture-20261005T0550Z` (1091 captured
source files plus its capture manifest). This slice works only in its isolated /tmp
copy and never edits the frozen base.

## Source-backed consumer decisions

The direct Responses adapter emits only one terminal CandidateRange after structural
validation. This change does not expose token deltas or lower model first-token time.
M03 section 7 and M05 sections 4–6 distinguish complete semantic ranges, TTS input,
PCM packets and actual presentation; they do not equate every beat with a Google call
or authorize character-ratio audio alignment.

The application decorator yields an exact deterministic first sentence immediately
for an eligible ordinary text-only candidate. One bounded JEV request chooses among
application-enumerated partitions of only the unissued tail. JEV sees the complete
original caption and frozen-prefix extent. It cannot rewrite text, supply offsets,
judge content acceptability or grant permissions. A request digest plus nonce-bound
question and exact model/answer/usage validation prevent foreign or replayed choices.

At most four disjoint chunks reconstruct the original code-point string exactly.
JEV UNKNOWN, invalid, failed, timed-out or exhausted attempts preserve the complete
unissued tail. A cancellation-resistant call occupies one tracked slot and is never
awaited indefinitely by the caller. No retry or judge-shopping is introduced.

The compiler assigns independent cue/effect identity and binds application-owned
caption_chunk metadata into each effect digest. Metadata records group UUID, index,
start/end/total in Unicode code points and original UTF-8 SHA-256. The frontend checks
contiguous groups, immutable metadata and code-point lengths. Its real caption FIFO
applies one chunk at a time (800 ms minimum reading dwell), then allocates that chunk's
receipt and page-history observation. Timers cannot revive Stop/new-input/close or
revoked grants. No audio timing is inferred. The prepared-visual path now shares the
same apply/receipt/observer helper as the synchronous path.

## Deliberate voice and optional-event fallback

A recorded regression proved that placing the original speech in the first split
candidate is unsafe with the existing serial Actor: a speech-permission wait can
exhaust the turn timeout, causing sealing after only the first caption. All speech-
bearing candidates therefore retain their complete original cue. No additional
Google requests or chunker waits are added to voice. Progressive voice subtitles are
not implemented by this slice.

Story/affect/pose/scene/media candidates also stay whole. In particular, story
invitation reduction binds one exact original subtitle receipt. No new Actor writer,
permission bypass or false receipt is introduced.

## Actual entry and costs

The direct factory exposes boundary_request_limit=0 and boundary_timeout_seconds=0.4.
The public CLI offers --boundary-max-requests and --boundary-timeout-seconds for both
check and serve. Zero does not wrap generation and makes no boundary request. Positive
allowance uses the already admitted output JEV transport; probe cap8/application cap100
and a deadline in (0,2] are enforced before serving. check and serve disclose separate
input/event/boundary ceilings and their aggregate. These are technical attempt limits,
not dollar caps. Every eligible candidate uses at most one extra JEV request; Google
request count is unchanged. No provider/auth/network/install was exercised here.

Eligibility is exactly one subtitle, 24–4096 code points, at least three legal sentence
boundaries, and no speech or optional proposal/control. The first caption adds no JEV
wait after model completion; only later caption availability is deadline-bound. Actual
provider latency, semantic quality, browser pixels, reading/hearing and cost benefits
remain unverified. Upstream generation failures/whole-turn timeout retain existing
Actor failure semantics; this planner cannot convert invalid generation into success.
