# DEMO-01 verification: authored offline rehearsal

2026-10-03. This is a finite, explicit profile through the existing Actor, compiler,
review, permits, authenticated PCM stream, presentation gate, cue release and single
browser playback sink. It is not a live provider or real speech-recognition demo.

## Directed evidence

Unique receipts are under `docs/verification/demo-01/runs/`:

- `20261003-1235-red-catalog`: 12 behavior failures before rehearsal profile/factory existed, zero source drift.
- `20261003-1244-green-catalog`: same 12 tests pass, zero drift.
- `20261003-1236-red-http`: 1 failure/1 pass; missing profile blocked real Actor/HTTP integration. The exception test's initial pass was incidental to the missing profile, not proof of the later injection guard.
- `20261003-1244-green-http`: 2 pass, authenticated PCM/cue/history/Stop flow plus explicit media injection guard.
- `20261003-1240-red-listening`: 4 failures before controller rehearsal input methods existed.
- `20261003-1241-green-listening`: attempted GREEN failed because the expanded schema required a main mode-label entry and TypeScript had not emitted a new controller. Retained as failed evidence; not a pass.
- `20261003-1241b-green-listening`: same 4 tests pass after successful strict TypeScript build.
- `20261003-1242-red-ui`: 1 fail/3 pass; explicit rehearsal controls not yet wired.
- `20261003-1244-green-ui`: same 4 tests pass with visible offline mode and synthetic input gesture routing.
- `20261003-1245-audio-negative-baseline`: 31 pass, including audio author's 15 asset tests and added exact-text/hash/path negatives. New negative checks were added after implementation and are baseline coverage, not fabricated historical RED.
- `20261003-1247-controller-regressions`: 71 Node tests pass using real controller/gate/playback logic and deterministic synthetic device/DOM seams. Existing error-locator DOM fixtures were extended with the four new HTML slots; error handling was not changed.

The broader first scoped run `var/quality/172231bb94a74273b7b8b6bd262a884e/summary.json`
had config/actor/providers/http/web pass but tooling fail on the director's concurrent
package-version RED. It is retained as an incomplete mixed-time integration check,
not a coherent whole-candidate pass. Final frozen affected verification belongs to
the following recorded run and director release review.

An initial unrecorded package invocation with a relative build-interpreter path
failed after staging changed working directory. The corrected absolute-path
invocation is recorded separately; the failure was not relabeled success.

## Observable scope

Seven exact commands, plus `/fail`; unknown input gets a fixed help caption and is
not echoed or spoken. Fixture review requires exact authored effects, fixture ID,
current command and actual presented-picture history. Speech accepts only exact
manifest captions and integrity-checked immutable PCM. Default mock/replay remain
compatible; injected providers cannot be combined with an offline rehearsal label.

Real microphone capability stays false. Synthetic listening stages only the visible
fixed command `照片里有什么`, clears through the existing local interruption owner,
and submits via the ordinary causal text-input path. Stop, close, newer text and
late stop acknowledgements cannot resurrect staged input. No second audio player,
parallel session, runtime synthesis, browser speech fallback or recognition exists.

The original local illustration depicts a coastal lighthouse. Captions and authored
English audio describe that asset. Picture questions require its actual presented
media history, not a proposed plan. Camera lowering, curious/warm/reflective faces,
rain and warm-light scene changes are explicit authored effects.

## Not run / not proven

No provider calls, credential reads, browser/UI operation, Git publishing, real
microphone permission, speaker listening, mobile device, Chinese TTS or live JEV
quality tests occurred here. The visible 3–5 minute guide is user-paced, including
inspection/repeated Stop; 52.56 seconds of fixed synthetic audio is not evidence of
an equivalent free-form conversation or completed recording. Existing software
sample facts do not prove physical hearing or word-level alignment.

## Final stable affected handoff

`python tools/check.py --affected --base ebb578dde665c9c7269e4a64b508182680b2fa66 --jobs 2`
completed against the final combined working source with `status=passed`, no changed
source files during the run, and no unrun selected lanes. Receipt:
`var/quality/4f707081447b46c0af75a52baf9daf18/summary.json`.
Shared schema and the existing accumulated diff conservatively selected all offline
lanes plus the serial installed-wheel and loopback smoke. This remains offline
software evidence, not browser/device/provider or physical-audio acceptance.

The immediately preceding run `5fb1eefb9a06436d9c5c873a8cbcb5a6` was correctly
invalidated by a concurrently added diagnostic acceptance test, which initially
raised a pytest helper-class collection warning. That worker fixed/froze its test,
then the final run above passed. No failed receipt was overwritten.

The additional installed-wheel run `docs/verification/demo-01/runs/20261003-1250-package`
passed with zero source drift: all eight hash-checked audio clips loaded from the
installed package, offline fixture capabilities reported correctly, microphone
stayed disabled, and no fixture asset was exposed as an unauthenticated public URL.
