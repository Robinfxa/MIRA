# Important: use the explicit restore helper

This additive notice supersedes restore instructions using the historical assertion-based helpers in the 11:58, 12:36 and 12:56 stage backups. Those originals used Python assertions for integrity/path checks; `python -O` or `PYTHONOPTIMIZE` disables them. Do not use those historical helpers for restoration. Original ZIPs, manifests, helpers and checksum files are preserved unchanged for historical integrity.

Use `restore-checkpoint-explicit-20261003T1448Z.py` with the archive and manifest for the stage you choose:

`python3 restore-checkpoint-explicit-20261003T1448Z.py mira-integration-STAGE.zip MIRA-CHECKPOINT-MANIFEST-STAGE.json NEW_EMPTY_DESTINATION`

Replace STAGE consistently with `20261003T1158Z`, `20261003T1236Z`, `20261003T1256Z` or `20261003T1448Z`. The new destination must not exist; use a private existing parent directory without competing writers. The helper runs no archive code. Review project origin before executing restored files.

The replacement checks hashes, bounded sizes, regular-file modes and safe paths explicitly, stages verified output, and commits only after validation. It rejects the tested executable-style/rebased ZIP prefixes and malformed/multidisk central-directory layouts. ZIP64 end-directory layouts are unsupported; small bounded per-member ZIP64 local headers with ordinary ZIP32 central directory/EOCD are permitted. This is not a blanket claim that every ZIP64 encoding is rejected.

Final exact helper SHA-256: `3fdb4eeebf61f608401cdf4e17ef5be2f56f5d811eeda9f1d3b704d7ad8517aa`.

The separate final independent signoff reports 42 directed cases and independent malformed-format checks on Linux/Python. Windows/macOS runtime behavior and hostile same-user races are untested. Hashes prove consistency with a manifest, not its authorship: obtain the manifest/helper through the verified repository commit and check the published checksum file.
