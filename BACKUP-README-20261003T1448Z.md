# MIRA corrected stage: 2026-10-03 14:48 UTC

This sanitized recoverable source archive contains 543 frozen source/document files plus checkpoint metadata. Earlier archives stay unchanged. It is an archive checkpoint; an expanded Git source tree and remote CI are separate publication outcomes.

## Result

**1,155 Python + 185 Node tests; all 12 local release lanes passed** on the frozen candidate and again on its extracted public projection, with no source drift. Includes offline wheel/install and actual local HTTP smoke. The image-readiness/decode-retry, Stop access, live-admission wording and restore-safety corrections are included. Read `KNOWN-GAPS-20261003T1448Z.md` for closure evidence and acceptance limits.

The frozen acceptance-status document was written before the green release; current timestamped release evidence records the later verified pass without rewriting that document. Later provider observations and attribution documents are separate and do not change this frozen source or its runtime admission.

## Safe restore

1. Download this stage ZIP, manifest, `restore-checkpoint-explicit-20261003T1448Z.py` and the associated files/checksum list. Verify `SHA256SUMS-20261003T1448Z.txt` using `sha256sum -c` or equivalent.
2. Obtain the manifest through the verified repository commit. Hashes alone do not establish authorship.
3. Run `python3 restore-checkpoint-explicit-20261003T1448Z.py mira-integration-20261003T1448Z.zip MIRA-CHECKPOINT-MANIFEST-20261003T1448Z.json ./mira-restored` in a private parent directory without competing writers. The destination must not exist. The helper validates explicit bounds, paths, hashes and modes before committing staged output. It runs no project code.
4. Read the restored README and `docs/checkpoints/20261003T1448Z/KNOWN-GAPS.md`. Prepare declared dependencies separately, then use `sh scripts/dev --profile rehearsal` for the explicit offline rehearsal or the normal documented mock startup.
5. With an existing declared dependency environment, `python tools/check.py --release --jobs 3` runs local offline checks. TypeScript must be available under the restored project's declared `node_modules`; dependencies and private credentials are not included.

All captured public source modes are preserved in ZIP metadata. The helper checks/restores Unix modes; the project documents `sh scripts/dev` rather than relying on executable bits. ZIP64 end-directory layouts are unsupported; bounded small ZIP64 local members are permitted. Windows/macOS runtime and hostile same-user writers remain outside verified scope.

## Historical helper warning

Use the new explicit helper for older stage archives too. Do not use the original assertion-based restore helpers from earlier backups. See `RESTORE-SAFETY-NOTICE-20261003T1448Z.md` and the separate final independent signoff. Original archives/checksums are preserved.

## Offline rehearsal and boundaries

Eight original synthetic English clips total 52.56 seconds. The archive includes both PCM/WAV forms, the generator and provenance. The finite command catalog, synthetic listening control and existing Actor/permit/caption/audio path do not establish live generation, microphone recognition, physical sound, Chinese speech, actual browser/device behavior or a 3–5 minute acceptance recording.

Private runtime configuration belongs in the ignored local `.env`, initialized with `python tools/api_env.py init`; never upload it or credentials. The default demo ignores private config. Live admission, paid calls, true voice and JEV quality remain separate gates.

## Exclusions

Raw logs, user PDF, auth/runtime/private diagnostics and incident material, generated evidence and duplicate workspaces are excluded. The exact 16 declared synthetic audio fixture files are included. Nine documentation files have explicit machine-path sanitization with before/after hashes. Setup link check: 40 checked, 39 present; historical FND-02 raw-log directory intentionally omitted. The old FND-02 evidence verifier requires those absent logs, while the current release suite is independently green.
