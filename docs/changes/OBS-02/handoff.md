# OBS-02 handoff

- Fixed the escaped/nested credential-envelope raw recording/export bypass at the shared
  privacy filter only. No Actor, bootstrap, HTTP, frontend, schema or port changes.
- New bounded structured review rejects uncertain JSON/envelopes and redacts injected values
  after decoding; inherited quadratic assignment/JWT regex scan corrected with token boundaries.
- Real RED/GREEN: 56 failed / 5 passed → same 61 passed; separate CPU regression 2 timed-out
  failures → same 2 passed. Final OBS + architecture regression: 110 passed.
- Receipt boundary is explicit owned-file hashes, not shared-workspace/full-product acceptance.
  See `docs/verification/obs-02/verification.md`, runs and pair-integrity.json.
- New 63-test contract file belongs to existing providers glob. OBS-02 spec has three
  collectible requirements. Final source hash and frozen candidate are in verification.
- Default raw off, explicit consent and audio attestation preserved. No real secrets, calls,
  audio capture, Git or publish. Bounded JSON recognition is not universal secret detection.
- Final-hash independent retest passed: unchanged 24-case matrix zero retained credentials,
  benign/default-off controls preserved, four adjacent controls passed, all 63 new tests
  independently passed. Canonical hashes equal frozen 11:27 candidate. Narrow ownership
  released to director, who owns aggregate affected/full/release and integration handoff.
