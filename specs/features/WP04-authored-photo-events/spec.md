# WP04 authored camera/photo events

Owner: authored visual events. Baseline: frozen 20261005T1444Z capture. Consumers: generator, JEV, Actor, renderer readiness; lifecycle and articulated renderer supplied by separate owners. No provider calls, credentials, new dependency, device capture or arbitrary media paths. External append-only synthetic evidence: /workspace/shared/mira-authored-photo-events-evidence-20261005T1522Z. Test owner: providers (tests/contracts/test_authored_photo_events.py); web lifecycle tests remain lifecycle owner.

### APE-001 Exact authored event vocabulary
Given a mixed chat cue, when camera_raise or trip_photo is proposed, the exact bounded event parses. camera_raise means raising the held camera to chest level only; trip_photo is an authored original illustration, never a newly taken or user's photo. Other media IDs, paths and URLs fail closed.

### APE-002 Ready, reviewed optional effects
Given a supported, source-verified renderer and existing pinned local illustration, when optional JEV review allows, only the exact event is granted. Missing capability/resource, UNKNOWN or REJECT leaves chat available. Story mode is not required.

### APE-003 Completed facts and idempotence
Given valid issued events, only matching successful completion receipts become next-turn software presentation facts. Wrong, after-Stop and duplicate receipts cannot invent completion. Same-target requests after a confirmed endpoint produce no repeated action grant/episode.

### APE-004 Interrupted physical uncertainty
Given ready was completed, raise was issued but cancelled halfway, and the user asks to return ready, the old ready receipt is historical; current camera position is uncertain. The return must be allowed through review and a new completion clears uncertainty. No new partial wire protocol is introduced.

### APE-005 Asset identity
Given a catalogue label with missing or changed source bytes, camera motion is unavailable. Readiness binds exact authored source paths, source hashes and renderer hash; the photo binds fixed local SVG bytes. Static fallback cannot qualify camera_raise. Readiness is software availability, never visual approval.

### APE-006 Sequential target preservation (V3 correction)
Given an acknowledged camera endpoint and an ordered cue of camera controls, retain every target change in sequence. Suppress only a camera target equal to the endpoint after the preceding retained controls. A raise followed by return must preserve the return, and raise/return/raise must preserve all three. Initial physical uncertainty preserves the first recovery target; only subsequent equal targets can be removed. Projection here is an untrusted proposal sequence, not acknowledged history. Repeated trip_photo remains idempotent once shown or already retained for this cue; an uncompleted photo may retry after Stop.

### APE-007 First request for an available authored object
Given the pinned local trip_photo is READY but has never been displayed, a current request may resolve the exact authored.trip_photo identity under mira-input-authored-objects-v1. This permits subsequent optional-event review, not presentation or a completed fact. The referent has no presentation effect ID. Missing/unavailable/untyped readiness, a different capability, an invented receipt or an unknown object fails before provider classification. Legacy question revisions retain presented-only resolution. A real successful display receipt is still required before either generator or reviewer sees exposure as completed history.

### APE-008 Explicit local photo dismissal
Given a displayed or preparing authored illustration, when the user chooses the accessible close-photo control, the browser hides it and fences all photo grants through the current activity immediately. It does not stop chat, microphone, continuous listening, character motion, or audio. The typed app update bypasses optional event review and queues behind existing factual deliveries; next input waits for its acknowledgement. Failed synchronization keeps the local photo hidden and reports the unavailable sync without interrupting those owners.

### APE-009 Visibility and historical exposure
Given a successful show receipt followed by dismissal, generation and optional JEV review receive presented=true and visible=false with a close-only visibility revision. Presentation receipts and historical effects remain byte-for-byte unchanged. An exact repeated dismissal request is idempotent even after a later re-show; altered identity/revision, wrong session/token and extra wire fields fail closed. No LLM hide effect, arbitrary media path, or second control platform is introduced.
If dismissal occurs during either manual-memory or conversation-archive recall, current visibility and its revision are refreshed under the Actor lock immediately before model dispatch. Bound historical evidence remains historical; it cannot overwrite the newer local display fact.

### APE-010 Late work and later re-show
Given photo decode, generation, or optional review already in flight, dismissal blocks the current activity's photo from resurfacing or issuing a late false receipt. Stop does not reverse dismissal. A genuinely later accepted input can review and show the authored photo again, with a new receipt and preserved past exposure. Rehearsal reports a previously shown closed photo as closed, rather than still visible or never displayed.

Implementation slice: frozen baseline mira-camera-photo-capture-20261005T1734Z, isolated tree mira-photo-visibility-next-20261005T1746Z. Consumers: domain transitions, Actor, context/JEV, public DTO, existing browser gate/receipt queue, SceneEffectExecutor, app control. Resources: existing pinned local illustration only. New Python tests belong to the existing providers lane via tests/contracts/test_*.py; compiled browser tests belong to the existing web lane. Evidence is append-only in mira-photo-visibility-evidence-20261005T1746Z. Full release/package/provider/device/paint acceptance remains separate.
