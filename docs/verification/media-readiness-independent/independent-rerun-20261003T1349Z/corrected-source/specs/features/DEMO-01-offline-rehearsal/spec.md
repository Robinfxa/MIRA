# DEMO-01 Explicit offline rehearsal

This optional profile is an authored, finite interaction, not live LLM, TTS or speech recognition. Existing mock/replay contracts stay unchanged. No private configuration, service credential, network provider, raw recording or real microphone is activated by the demo launcher.

## Requirements

### DEMO01-001

Given explicit rehearsal profile, existing loader/factory creates a finite command generator and exact fixture reviewer. Mock remains default; live admission is unchanged.
### DEMO01-002

Given an exact command, produce only its authored speech, bilingual caption and relevant camera/expression/environment/media effects. Unknown text returns a fixed command hint without echo, speech or arbitrary approval. Review rejects changed content, wrong command context and foreign fixture IDs.
### DEMO01-003

Given a question about the picture, reference it only when its media effect is in actual presented history. Accepted but unpresented proposals are insufficient. Newer activity and Stop still revoke old output through the existing Actor and presentation gate.

For the browser's local trip illustration, emit that media receipt only after the mounted image is complete, has positive intrinsic width, and its `decode()` promise resolves. A failed resource, decode rejection, or bounded timeout leaves a first attempt absent from application history. Stop, new input, permit revocation, and close cancel pending preparation; a late load or uncooperative completion cannot reveal or receipt the old effect. Once a ready illustration has been revealed and receipted, Stop continues to preserve it. This is a decoded-resource/application-history condition, not evidence that a compositor painted pixels or that a person looked at or understood the image.
### DEMO01-004

Given authored speech, the registered offline synthesis adapter streams only exact manifest text with verified fixed PCM provenance through the existing authenticated Actor speech route. All packets have continuous 24 kHz PCM16 sample positions; arbitrary text and corrupted clips fail closed. Assets are installable package resources.
### DEMO01-005

Given the UI capability report, display OFFLINE rehearsal and English synthetic fixed audio plainly. Real microphone remains disabled. Synthetic listening uses a labeled hold control that stages one selected catalog text through existing stop/input causality, requests no microphone access, and never claims to recognize user speech. Stop, blur, cancellation, close and newer text invalidate the staged input.
### DEMO01-006

Given a user-directed walkthrough, the existing executor reaches listening (simulation labeled), thinking, actual queued speaking and idle; camera lowering, original local coast/lighthouse illustration, preserved photo after Stop, history-aware follow-up, rain/warm environment changes, injected failure and recovery remain visible. No automatic timeline or second playback controller.

## Scope / ownership / verification

Base: ebb578dde665c9c7269e4a64b508182680b2fa66. Owner: rehearsal worker, exclusive bootstrap/config/schema plus narrow controller/main/HTML edits, coordinated with director. SessionActor and domain transitions unchanged. Audio author supplies package assets. Director owns quality registration.

Primary blocks: providers (test_rehearsal_generation.py), http (test_rehearsal_http.py), web (rehearsal*.test.mjs plus existing controller tests). Consumers: config, actor, tooling startup and package. Resource: only local PCM fixtures; no provider accounts. Schema/package edits conservatively expand integration checks, run by director after a frozen candidate.

Directed tests must show real RED/GREEN with unique IDs. Software rendering and DOM harness checks do not prove physical hearing, a real microphone, browser/mobile rendering, Chinese speech quality or a 3–5 minute recorded human interaction. Walkthrough duration is a paced manual exercise, not generated free dialogue.

Frontend behavioral coverage also runs `tests/web/controller-main.test.mjs` and `tests/web/controller-voice.test.mjs`: Node tests exercise actual controller causality with synthetic transports and main gesture wiring. The Python traceability links below support the configuration/HTTP/catalog aspects; they are not browser/device evidence.

The media-readiness boundary has focused synthetic-DOM/controller coverage in `tests/web/controller-media-readiness.test.mjs`. Its recorded RED/GREEN run is under `docs/verification/media-readiness-repair/`; those stubs verify local readiness and cancel safety only, not real-browser paint or human perception. Existing Python history mappings remain unchanged and do not claim this frontend test as a Python check.
