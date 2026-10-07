# WP03 default local voice interruption slice

2026-10-05 22:46 user direction: voice interruption is enabled by default for a new natural-listening lease. This supersedes the earlier explicit-headphone default below. Current base: immutable `mira-integration-20261005T2238Z`; this change is isolated in `mira-default-barge-20261005T2248Z`. The legacy local `headphones` enum means enabled energy-based interruption, never detected or user-verified hardware.

Current owner: default-barge worker owns only the web UI/controller, relevant compiled-web tests, and this documentation. Existing `web` lane glob uniquely owns all changed Node tests; no quality-owner change is required. Backend/shared contracts, runtime budgets and accepted appearance remain byte-identical. No new resources or providers.

New observable contracts:
- Loading the actual page selects “语音插话开启（建议耳机）” without starting capture or creating a listening lease. The user still clicks Start and the browser still controls microphone permission.
- Natural listening without an explicit option enables the existing 160 ms detector. Manual mode and explicit `guarded` remain conservative; mode is frozen for each lease. The UI offers “关闭语音插话（扬声器／按钮打断）”.
- A bounded burst guard suspends automatic interruption only when three automatic attempts (including failed local stops) occur within 32,000 captured samples (2 seconds from first to third). Spaced legitimate interruptions do not exhaust a lease count. The same microphone lease, transcription and manual interruption remain available. The existing interrupt button visibly offers explicit re-enable; it clears the burst guard in the same lease but cannot reset malformed/stale-capture invalidity. No timer, recognition rotation, quiet period or AEC report clears a pause. A fresh user-started lease starts a fresh guard.
- AEC false/unknown never proves no echo. Brief, stale, malformed and latched repeated sound cannot interrupt. Sustained residual echo may still qualify until a rapid repeated pattern trips the guard; slower echo can still qualify; software cannot distinguish an identical microphone waveform from human speech.
- Stop/mute/new-turn/close, exact continuation identity, accepted input and actual presented history retain existing controller fences. Existing duration, samples, stream/utterance/request budgets are unchanged.

## Earlier slice background (superseded defaults)

Base: immutable `mira-plain-chat-capture-20261005T1935Z`, manifest SHA-256 `76c514140f2a5eae9576e11279e913c0cfeb82f7294b361e660c442adad25761`.

Owner: local-barge-in worker owns four audio files and two web test files. Director owns continuous-listening/controller/main integration, mode selector, continuation fixes and quality/traceability integration. Web lane uniquely owns `tests/web/*.test.mjs`; no new dependencies, provider calls, permissions, schemas, service budgets or playback sink.

## Intended behavior

- Given explicitly selected guarded mode, energetic capture overlapping reply playback cannot qualify an automatic interruption.
- Given enabled interruption (`headphones` compatibility value) for this lease, contiguous fresh 16 kHz mono capture at RMS >= max(600, clamp(noiseFloor,40,300) * 4) for 2,560 samples qualifies once. This is sound-energy evidence, not speech identity or proof of no echo.
- Given fewer than 160 ms above threshold, a candidate resets without interruption. Rearm needs 3,200 samples (200 ms) below max(180, boundedNoiseFloor * 2). All counters use samples, no native timers.
- Given old sequence, missing/overlapping sample interval, malformed PCM, or same-capture-context delivery age over 200 ms, the detector stays invalid until its owner explicitly resets/replaces it; unknown overlap remains for review.
- Given Stop, permission loss, Close or a new microphone lease, the owner drops/reset detector state and stale callbacks cannot act. Recognition child-stream rotation keeps the same lease and capture sample clock, so it must not reset sequence history.
- Given a mode change, stop the active lease and require a fresh Start; never promote previously guarded overlap. The selector recommends headphones and never states that they were detected. It must not infer output hardware from labels or identifiers.
- Only after `interruptReply()` succeeds synchronously and the sole reply PCM owner is idle can the caller promote the qualified exact range. Older overlapping ranges remain untrusted. The local detector performs no transport, commit, model request or history mutation.
- Accepted automatic input retains utterance/revision/commit identity and sends the existing accepted commit ID to SessionController; request continuity and actual presented facts remain governed by existing fences.

## Processing diagnostics

Capture reports only `echoCancellationRequested: true`, browser support boolean or null, and track-reported boolean or null. Unknown, false and non-boolean future modes are not silently upgraded to true. Read only sample rate and echo cancellation fields; never enumerate devices, read labels/IDs, serialize all settings or change constraints. Reset diagnostics on stop. Optional diagnostics failures must not retain resources or break ordinary capture.

Same-context chunk delivery age is local metadata only; it is not microphone-to-ear latency, never reaches server PCM packets, and does not prove acoustic silence. A 160 ms qualification target takes 160–200 ms of captured sound at the current 40 ms framing, plus unbounded browser scheduling/hardware delay. Input deliveries delayed over 200 ms decline automatic interruption. Existing 700 ms quiet endpoint, finite provider drain and all service limits remain unchanged.

## Sources and limits

The Media Capture specification defines requested constraints, support and current settings separately. AEC `true` lets the browser choose what audio to remove and requires an attempt; it does not certify echo absence: https://w3c.github.io/mediacapture-main/#dom-mediatracksettings-echocancellation

Web Audio output timestamps provide an estimated output clock mapping, not an acoustic echo path: https://webaudio.github.io/web-audio-api/#dom-audiocontext-getoutputtimestamp . The existing separate capture/playback contexts expose neither an aligned reference nor adaptive cancellation, so this slice cannot guarantee safe speaker auto-barge-in and does not add a signal-correlation platform.

Synthetic tests cover thresholds, ranges, fences and privacy. Wired/Bluetooth headphones, speaker leakage, real microphone permission loss, browser AEC behavior, soft voice/noise and physical audio interruption remain not_run device acceptance. A loud sustained noise or residual leak can qualify with automatic interruption enabled; use guarded mode/manual interruption if it does. No new raw audio is retained or exported.

## 2026-10-06 correlated interruption transcript repair

Base: immutable 0114 capture, SHA-256 61f0a635cce3e8096ab21d193d3e2d7c970c857390efabc2a44f5d2f3e745598 (1307 files). Owner: this frontend slice; `web` lane glob owns compiled-controller tests. Changes are limited to continuous-listening, session/controller, main wiring and related tests/docs. No service schema, provider, permission, sample/stream/utterance budget or second audio owner.

- Given fresh PCM that qualifies the existing detector and a successful local reply Stop, preserve bounded source interval and exact original request capability until the later endpoint/final. The server-confirmed utterance sample interval determines which same-request captured ranges belong with that evidence, including a softer prefix and internal pauses. Neither a fixed prefix-duration cutoff nor a PCM quiet frame splits a finalized phrase. An already settled source interval cannot join a later utterance; the settlement fence advances only after a matching server commit-ready or hold acknowledgement, never from PCM quiet or the provisional ready candidate. The unchanged lease sample limit bounds the interval and only one numeric interruption evidence record is retained. Do not discard captured PCM or pre-Stop words.
- Given a final covering this evidence, carry its entire server-confirmed text once into the original request continuation, including when begin_offset precedes Stop. A late revision stays attached to that utterance, never becomes a new input. A newer unrelated turn, Stop/Close/revocation or fresh lease cannot inherit evidence.
- Preserve unrelated/unknown overlap and incomplete/failed interruption as review. No phrase/keyword grants interruption or endpoint authority. The same microphone waveform and ASR text can originate from a user or echo; no transcript containment/keyword or speculative echo rule gates successful barge-in. Scheduled/queued speech before any source submission does not taint the user phrase, and local interruption still cancels it before a pending resume can start.
- Same microphone lease and contiguous PCM delivery survive reply-only interruption and child recognition stream rotation; existing delivery, quiet endpoint, revision, commit and burst limits remain effective.

Synthetic compiled controller/main/playback tests are software evidence only. Real-device user/echo discrimination, browser AEC and physical sound remain unverified. The user's installed version is not established by the status wording.
