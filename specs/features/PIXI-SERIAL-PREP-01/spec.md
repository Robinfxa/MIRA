# PIXI-SERIAL-PREP-01: ordered asynchronous visual preparation

Scope: preserve controller ownership of visual grants and receipts while a renderer
optionally prepares a texture or other backing resource asynchronously. No protocol,
domain, schema, permission-gate, audio-owner, or provider contract is added or changed.

Owner: `tests/web/controller-visual-preparation.test.mjs`, uniquely covered by the
existing `web` lane (`tests/quality.toml`). The tests use the real TypeScript
`SessionController` and synthetic ports with deferred promises. Existing media-readiness,
receipt-barrier, and speech-cue suites remain regression controls. This spec uses the
web sidecar because `tools/check_specs.py` collects Python tests only.

Consumers: `SessionController.presentVisuals`, `EffectExecutor.prepare/apply`, the
existing presentation gate, and the existing receipt transport. A successful resource
preparation is not itself a presented effect or receipt.

### SERIALVIS-001 Prepare, apply, and receipt visual grants in order

Given the executor has `prepare`, when multiple currently eligible non-speech visual
grants are active, then the controller calls `prepare` one at a time in grant order,
revalidates the generation and permit after each await, synchronously applies the same
grant, and only then consumes/enqueues its receipt. A later eligible grant cannot pass an
earlier unresolved preparation. Repeated snapshots do not duplicate preparations or
reorder apply/receipt history. Ports without `prepare` keep their synchronous apply path.

### SERIALVIS-002 Revocation and failure remain fail-closed

Given a preparation is pending, when Stop, a newer input, Close, or a revoking snapshot
invalidates its authority, then abort it immediately and ignore a late or uncooperative
completion without apply or receipt. If an authorized preparation fails, present no
effect or receipt, report safe local feedback once, and let later eligible grants
continue; unchanged polls cannot create a retry storm. Outstanding ignored-abort calls
remain bounded.

### SERIALVIS-003 Speech-cue captions remain tied to submitted audio

Given a subtitle depends on a speech cue, do not make it eligible before its matching
audio source has actually been submitted. Visual preparation must not await speech
completion or prevent `startSpeech` from beginning; once the controller opens the cue,
the subtitle enters the same ordered preparation and receipt path.

## Verification boundary

The behavior is covered with fake ports and delayed promises. Existing independent
controller suites provide media decode, receipt barrier, actual software-source
submission, caption gating, and speech phase regressions. These tests do not prove GPU
texture upload, browser paint, actual audio output, or user visibility.
