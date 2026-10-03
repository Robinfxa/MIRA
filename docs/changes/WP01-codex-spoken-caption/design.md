# WP01 Codex spoken-caption gap

## Change boundary

The native adapter can currently accept one speech effect and zero subtitles, allowing
a completed spoken candidate with no visible caption. PDF-08 requires speech replies
with synchronized subtitles. Existing cue rules permit a subtitle to differ from its
speech peer because they associate effects through application-owned cue identity and
do not infer a pairing from text. The smallest safe Codex-specific change is therefore
to require exactly one separately authored subtitle whenever speech is present, while
leaving semantic correspondence to the existing independent JEV reviewer. Structural
parsing does not claim to prove that the subtitle describes the speech.

Only the Codex candidate parser is tightened. Speech remains an untrusted candidate
and still needs independent review, current epoch, compilation and presentation
authorization. Visual-only ranges remain legal. No runtime admission/defaults or other
provider contracts are changed.

## Observable tests and resources

Owner block: providers (registered existing `tests/contracts/test_*.py` wildcard).
Consumers: Codex adapter output path and current cue/compiler/review consumers. Test
resources: local parser and synthetic JSON values; no native Codex process, auth, model
inference, payment, external request, or device.

Given a speech candidate with no subtitle, parsing rejects it. Given one speech and one
explicit subtitle, parsing preserves both distinct effects even when worded differently;
JEV remains responsible for content review. Given no speech, standalone subtitle and
authored visual controls continue to parse normally.

Common baseline: `ebb578dde665c9c7269e4a64b508182680b2fa66`. The feature's own RED and
GREEN receipts are under `docs/verification/wp01-codex-spoken-caption/runs/`; the final
verification note names what was and was not run.
