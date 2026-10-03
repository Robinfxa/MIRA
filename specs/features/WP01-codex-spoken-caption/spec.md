# WP01 Codex spoken caption contract

Base: inherited integrated mission tree. This change tightens only candidate parsing
for the Codex generation adapter; default admission and provider settings remain
unchanged. Owner: providers. Consumers: Codex adapter, the existing cue compiler,
independent semantic review, and the cue/audio presentation path. Resources: offline
synthetic JSON only; no native process, auth, model inference, paid call, or device.

### WP01CODEXSPOKENCAPTION-001 Spoken replies carry an explicit corresponding caption

Given an output candidate containing one speech effect, it must also contain exactly
one separately authored corresponding subtitle. A missing or additional subtitle
rejects the complete candidate before presentation admission. The parser never
invents, derives, copies, translates, or normalizes a caption from speech.

The count rule is structural, not a lexical proof of correspondence. The shared cue
compiler associates separately authored effects through application-owned cue identity
and permits different wording; it never infers pairing from text. Existing WP07 cue
requirements leave semantic correspondence to independent JEV review. This Codex-specific
rule closes the missing-subtitle gap while preserving translated or otherwise differently
worded captions for that same single Chinese-default speech cue; it makes no claim of
word-level alignment.

### WP01CODEXSPOKENCAPTION-002 Visual-only candidates remain valid

Given a candidate with no speech, any otherwise valid standalone subtitle, pose, or
scene remains eligible for the existing independent review. A caption without speech
does not grant speech, and speech cannot be admitted without an explicit caption.

## Out of scope

No global cue compiler rule, reviewer, lifecycle, timing, live admission, or output
schema is changed. This is a structural prerequisite only; it is not proof of actual
audio playback, user hearing, or subtitle visibility/timing on a device.
