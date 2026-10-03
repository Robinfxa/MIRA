# Independent recheck: media readiness correction

Captured the corrected files before any test run into `corrected-source/` and `tests/`. The exact SHA-256 values are in `SHA256SUMS.corrected`; post-run `sha256sum -c` passed for every captured corrected file (`20261003T1403Z-corrected-hash-check.txt`). Frozen 12:56 baseline hashes are also recorded and rechecked. No production source was edited.

## Cross-version observer

`cross-version-observer.mjs` is an async adaptation of the original `../repro.mjs` observer: it models a mounted image with `complete`, `naturalWidth`, load listeners, and a controllable `decode()` promise. This is needed because the correction added `EffectExecutor.prepare(effect, signal)`. The same observer file was run unchanged against both builds:

- Baseline: 12:56 source compiled to `/tmp`; output is in `20261003T1402Z-baseline-observer.json`.
- Corrected: a disposable source tree was constructed from the 12:56 tree plus the captured `ports.ts`, `scene-executor.ts`, and `controller.ts`, then compiled to `/tmp`; output is `20261003T1402Z-corrected-observer.json`.

It confirms the expected contrast. Baseline immediately exposed the figure and recorded one receipt for slow, broken, and late-load cases. Corrected source kept slow and broken attempts hidden with zero receipts. Late load and late decode after Stop, new input, permit revocation, or close remained hidden with zero receipts. A successful decode revealed once and produced one receipt; the ready image stayed visible after Stop. The reproduction uses only synthetic DOM/image/transport stubs, not an actual image decode or browser.

## Corrected checks

- Focused readiness + cue tests: **43/43 passed**, output `20261003T1357Z-focused-corrected.tap`.
- Full copied web suite: **182/182 passed**, output `20261003T1359Z-web-full-rerun.tap`. The first isolated attempt omitted the static HTML/public fixtures and had three fixture-path failures; copying those unchanged files from the frozen snapshot fixed the test assembly, and the full rerun passed.
- Readiness tests cover initial decode, slow load, broken/errored/decode-failed/timed-out resources, repeated snapshots/load events, Stop/new input/revocation/close, uncooperative preparation callbacks, bounded preparation count, and one shared pending browser decode. Cue tests still require actual source submission before cue-bound captions/controls; independent standalone visuals remain independent.
- `history_state_probe.py` uses the real unchanged `record_receipt`, `SessionState.presented_effects`, and rehearsal `fixture_for`: no receipt ⇒ `absent`; a receipt ⇒ `trip_photo` in history and `detail`. The domain and rehearsal backend hashes are identical between corrected and 12:56 source. Output: `20261003T1400Z-history-state.json`.

The parent’s reported count was 184; this independent run counted 182 Node tests in the captured 12:56 + correction web tree. All 182 passed. No actual-browser painting, provider, credentials, network, or human-viewing claim was tested.

## Recovery caveat found

An additional direct executor probe found that `decodeResource()` caches the raw `image.decode()` promise in a `WeakMap` even after rejection. With a controlled image whose first `decode()` rejects transiently and whose next call would resolve, two `prepare()` attempts both fail and `decode()` is called only once. The saved repro is `decode-retry-probe.mjs`; output is `20261003T1408Z-decode-retry.json`. Pending decodes should remain single-flight, but a settled rejected promise may need eviction if the UI promises a retry on the same mounted image. The existing suite proves safe failure/no receipt and that the next photo question enters without restoring history; it does not test retry after a transient decode rejection. This does not undermine the false-history fix, but limits recovery for that case.
