# Browser presentation history retirement

Owner: web. Baseline: immutable mira-delivery-integration-20261006T0813Z
source snapshot, derived from mira-xiahe-chapter-final-20261006T0721Z.
Write surface: apps/web/src/features/presentation/permit-gate.ts only.
Consumers: SessionController, CancelSafePlayback and visual receipt allocation.
Resources: existing locked Node/TypeScript and offline synthetic PCM callbacks.
No installation, provider, credentials, real microphone or physical device work.
The existing tests/quality.toml web wildcard uniquely owns the new test file.
No contract or controller changes. This does not establish physical hearing.

### WEBGATERETENTION-001

Given arbitrarily many finite turns, when beginInput or Stop advances local
activity, all remembered effect identities, consumption and audio state from
older activities retire. Only this boundary proves no future local callback
may allocate their receipt. Global presentation sequence and permit/epoch
watermarks never reset. Late old snapshots cannot repopulate these collections.
The bound is the current finite activity's effects, independent of turn count.

### WEBGATERETENTION-002

Given an active turn, snapshot refresh, server presentation-floor compaction,
temporary grant removal or regrant must retain exact identity and one-shot
consumption. Same-turn changed content fails closed. A higher revision cannot
restore an older output epoch. No grant is dropped merely to meet a memory cap.

### WEBGATERETENTION-003

Given software-rendered speech prefix, controller block and synchronous sink
Stop allocate the exact interruption before beginInput/Stop captures cutoff
and retires the old activity. Block alone and server epoch revocation preserve
pending audio provenance until that terminal callback. New input, Stop and
saved old sink callbacks cannot turn the partial prefix into full completion.
Directed tests cover 160 gate turns and 125 actual compiled controller/gate/
playback turns, with 100 exact interruptions and 25 naturally drained speeches.
