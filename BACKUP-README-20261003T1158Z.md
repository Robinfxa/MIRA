# MIRA stage checkpoint: 2026-10-03 11:58 UTC

A sanitized, recoverable **source archive** from one immutable candidate. Earlier backups remain unchanged. This does not by itself establish an expanded Git source tree or remote CI.

## Verified result

**1,024 Python + 142 Node tests, all 12 local release lanes passed**, including offline wheel build/install and real loopback HTTP smoke. The original frozen candidate passed, then the public archive projection was extracted and rerun using existing declared dependency versions. Both runs reported unchanged source digests. The 432 projected source/document files preserve all functional code, tests, fixture data, v1 evaluation integrity files and current setup instructions. Six documentation files only replace machine-specific absolute paths with placeholders; their before/after hashes are recorded.

Read `KNOWN-GAPS-20261003T1158Z.md` for the explicit closure of earlier audit defects and current limits. No real browser/device, 3–5 minute interaction, live-provider, production-calibration, deployment or remote-CI acceptance is claimed.

## Restore and verify

Download `mira-integration-20261003T1158Z.zip`, `MIRA-CHECKPOINT-MANIFEST-20261003T1158Z.json`, `restore-checkpoint-20261003T1158Z.py` and `SHA256SUMS-20261003T1158Z.txt`, along with the other listed checkpoint files.

1. Compare the downloaded files with SHA256SUMS, for example `sha256sum -c SHA256SUMS-20261003T1158Z.txt`.
2. Use the included standard-library verifier/extractor: `python3 restore-checkpoint-20261003T1158Z.py mira-integration-20261003T1158Z.zip MIRA-CHECKPOINT-MANIFEST-20261003T1158Z.json ./mira-restored`. The destination must not exist. It validates archive SHA-256, exact nested member paths, file hashes and stored Unix modes; it restores modes on systems supporting chmod.
3. Read `mira-restored/README.md` and `mira-restored/docs/checkpoints/20261003T1158Z/KNOWN-GAPS.md`.
4. Prepare the declared Python/Node dependencies using the project setup instructions. Dependencies and credentials are not bundled. Existing approved environments can be reused via their explicit Python interpreter path; the restored project still needs its declared TypeScript dependency in `node_modules`.
5. Run the documented zero-key demo with `sh scripts/dev`, or the release checks with the chosen Python interpreter: `python tools/check.py --release --jobs 3`. These local checks do not grant live-provider or paid-call permission.

ZIP metadata preserves the frozen source modes exactly: every captured public source file is mode 0644, including `scripts/dev`, so use `sh scripts/dev` as documented. The supplied verifier restores and checks stored modes on Unix. Windows chmod/executable semantics were not tested.

## API keys and private setup

For local runtime configuration, use `python tools/api_env.py init` to create the ignored private `.env` from the blank example, then edit that file locally. Never upload `.env`, credentials or authentication caches. `api_env.py check` is offline and does not prove live readiness. The default `sh scripts/dev` intentionally ignores private runtime configuration and launches mock/replay. Consult the current project README/provider settings for the exact selected models; historical ENV documents describe earlier phases.

## Exclusions and historical evidence

Excluded 3603 captured paths before publication: runtime/auth/private diagnostics, raw logs, user PDF, generated previews/builds and duplicate snapshots. No symlinks were followed or archived. A category summary, documentation transformations and missing-link explanation are embedded under `docs/checkpoints/20261003T1158Z/`.

The 9 excluded quality-tracked entries are historical raw specification logs, not code or fixture assets; all 285 retained quality-tracked files match the frozen candidate byte-for-byte. The old FND-02 raw-evidence verifier needs omitted logs and is not supported in this public projection; the current release suite passed independently. This distinction prevents historical verification commands from silently appearing reproducible.
