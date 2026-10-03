# DEMO-02 asset verification, 2026-10-03

Base: `ebb578dde665c9c7269e4a64b508182680b2fa66`.

- `docs/verification/demo-02-offline-speech/runs/001-red-missing-assets/`: same 15
  tests failed because production fixture assets/verifier did not yet exist.
  Assertions ran; this was not a collection/dependency error. Exit 1 expected.
- `docs/verification/demo-02-offline-speech/runs/002-green-assets/`: same tests
  passed, 15/15; exit 0. Both receipts report no source changes during their runs.
- `docs/verification/demo-02-offline-speech/runs/003-final-asset-integrity/`:
  final asset tests passed 15/15 again; no source changes during the run.
- `python tools/check_specs.py`: all 103 current requirements resolve to collected
  base test nodes, including the four DEMO-02 requirements; this is mapping validation,
  not execution evidence for other features.
- `python tools/generate_rehearsal_audio.py --check`: all eight clips verified
  with Python alone and no provider/FFmpeg invocation.
- Two independent local synthesis runs produced identical bytes for all 16 PCM/WAV
  files. All eight captions were unchanged between runs.

Measured totals: 1,261,440 mono frames, 52,560 ms, raw PCM 2,522,880 bytes and WAV
2,523,232 bytes. Peak magnitudes range from 14,090 to 21,523 (of 32,768); zero
saturated samples; 1,255,046 nonzero samples. Durations in milliseconds:

| greeting | camera | photo | detail | absent | story | rain | warm |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 6135 | 5185 | 6720 | 6075 | 4450 | 14715 | 4660 | 4620 |

Manifest SHA-256 at handoff:
`3da7ce448572cd0958bd4bc58676e19f393a5cca46c09280074e9c1e8a15d25c`.

The existing spec checker normalizes parameterized tests to their base node ID;
the DEMO-02 mapping follows that established contract. The first check with
parameter-suffixed IDs correctly failed and was corrected; tests were not renamed.

The quality plan initially stopped on another worker's in-progress unowned
`tests/integration/test_rehearsal_http.py`; no aggregate pass is claimed from that
attempt. Shared quality inventory and package-data wiring belong to integration.
This asset worker did not edit them. Final affected/full/package checks are
reported by the integration owner against the merged, frozen source snapshot.

Not run by this worker: physical listening, browser/device playback, human
intelligibility, Chinese speech, live Google/Codex calls, or full product acceptance.
The fixture tests prove resource integrity, not that any user heard an utterance.
