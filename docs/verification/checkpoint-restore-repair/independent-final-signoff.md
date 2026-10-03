# Independent final restore-helper signoff

Review date: 2026-10-03 UTC  
Reviewed helper SHA-256: `3fdb4eeebf61f608401cdf4e17ef5be2f56f5d811eeda9f1d3b704d7ad8517aa`

This final report is separate from `independent-refinement-review.md`, which records findings against the earlier 81d61d candidate. Existing checkpoint artifacts and earlier review evidence remain unchanged.

## Final checks

- Independently ran `tests/unit/test_quality_restore_checkpoint.py` against the final helper: **42 passed in 5.87s** with the repository Python 3.13 environment.
- Rechecked the previously found dot-member case: `relative_path('.')` now refuses it.
- Rebuilt the stub-prefixed, offset-rebased synthetic ZIP and verified the helper refuses it before producing output.
- Rebuilt a synthetic archive with a nonzero CEN disk-start marker and verified refusal before output.
- Rebuilt a ZIP with a ZIP64 end record and locator; it was refused before output (`zip_directory_bound`).
- Rechecked all six entries in the prepared checkpoint’s `SHA256SUMS`; all pass.

All new synthetic archives, manifests, outputs and sentinels stayed in one disposable temporary root. No Windows execution, network, UI, credentials or Git operations were used. The prepared archive and original assertion-based helper were not modified.

## Format scope

The final helper rejects the tested ZIP64 end-record/locator layout and the tested rebased-stub layout. Its bounded preflight is for ZIP32 central-directory records. A small valid per-member ZIP64 local header with ordinary ZIP32 central directory and EOCD is still accepted by `zipfile` and the helper; the output bytes/mode/hash remain checked. Describe the restriction specifically as ZIP64 end-directory layouts if that distinction matters. This is a bounded implementation detail, not a demonstrated integrity or extraction-path failure.

The added Windows device/forbidden-name rules were exercised through the host-independent path validator on Linux only. No platform runtime behavior is inferred from those tests.

## Disposition

I sign off the final candidate for the tested Linux/Python restore behavior: optimization no longer disables checks, the path and ZIP32-directory bounds tested here fail closed, and staged output is not left behind on tested failures. The tested ZIP64-end, multidisk-marker, and rebased-stub layouts are refused. This does not establish manifest authenticity, Windows/macOS runtime behavior, or hostile same-user filesystem race safety; use the authenticated manifest channel and documented private-parent/no-competing-writers condition.
