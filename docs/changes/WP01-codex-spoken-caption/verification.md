# WP01 Codex spoken-caption verification

Actual synthetic/offline evidence is under
`docs/verification/wp01-codex-spoken-caption/runs/`; each report includes command,
captured output hashes and source-before/source-after fingerprints. No source changed
during any recorded run.

| Run | Command/result |
| --- | --- |
| `001-red-missing-caption` | Before the implementation, the dedicated test module had 1 failure/4 passes. The failure was the missing-caption case: parser did not raise. Exit 1 was expected. |
| `002-green-caption-required` | Same dedicated test module and unchanged test hash after the implementation: 5 passed. |
| `003-green-codex-consumers` | Dedicated module plus `test_codex_generation.py`, `test_codex_generation_hardening.py`, `test_codex_generation_process.py`, and `test_cue_compilation.py`: 100 passed. |

The RED test SHA256 was `42eac823ffa9e87c1ab3bf750f8a20830e7a6e0bca12e9b908599218c85c4a52`
for both 001 and 002. `payload.py` changed between the runs as intended: RED source
`08452916e6dfc67e7e4b39e192280059f4c27a4ddcc929f6938fd6397d5e095b`, final source
`ade3716788c05e9d8205305c3455e7476eeb5c037fa454a38dd5327084bcf3ca`. The source hashes
are repeated in each run's JSON receipt; the earlier native smoke and 142-check evidence
remain untouched and are not retroactively called RED.

`.venv313/bin/python tools/check_specs.py` reported 124 requirement links to collected
pytest nodes. This validates traceability only, not test execution.

The current existing providers wildcard already collects the new module. The director
owns any quality-registry adjustment and coherent affected integration. No full/affected/
release quality run, native Codex call, live semantic review, actual speech device,
browser, or human PDF-08 acceptance was run here. Admission/defaults were not changed.
