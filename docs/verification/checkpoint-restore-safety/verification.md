# Checkpoint restore helper safety audit

Date: 2026-10-03 UTC

## Scope

Audited the prepared helper at `<private-evidence-path>` against the archive/manifest contract documented in `BACKUP-README-20261003T1256Z.md`. The original public checkpoint directory was read-only for this audit; its files were not edited, repacked, replaced, or published.

The audit exercised only small synthetic ZIP files and manifests. It did not restore or read the contents of the public ZIP. The bounded harness is `audit_restore_helper.py`; it creates one fresh temporary root per run and removes it automatically. Both traversal sentinels are inside that root. Example:

```sh
python3 docs/verification/checkpoint-restore-safety/audit_restore_helper.py \
  <private-evidence-path>
```

Environment: Linux, Python 3.12. The Windows path assessment below is a path-library inspection only; no Windows execution is claimed.

## Result

The default interpreter rejects the tested corrupt/inconsistent inputs before creating the destination: bad outer archive SHA-256, incorrect member SHA-256, incorrect member byte count, a POSIX `../` member, an absolute POSIX member, and a duplicate ZIP member name.

All integrity and path-safety gates in the helper are implemented with `assert`. Running the same verifier as `python -O ...` or with `PYTHONOPTIMIZE=1 python ...` removes those gates. The synthetic cases confirmed:

- A manifest with an incorrect outer archive digest is restored successfully under both optimized forms.
- Incorrect member hash and byte-count fields are ignored under `-O`; payloads are restored successfully.
- A `../sibling-sentinel` path and a POSIX absolute path each overwrite a sentinel outside the destination, but still inside the harness's temporary root, under optimized execution.
- Duplicate ZIP names are accepted; the later entry overwrites the earlier extracted file.
- In those optimized runs the helper prints its normal “Verified and restored … hashes and stored modes checked” success message, even though those checks were disabled.

The destination-exists assertion is also removed, but the tested existing-directory case remains unchanged because the subsequent `destination.mkdir()` raises `FileExistsError` before writing. This is incidental refusal rather than an active verifier check.

There is a separate partial-output failure: a self-consistent archive containing the individually safe files `a` and `a/b` passes prevalidation, writes `destination/a`, then fails when it tries to create `destination/a` as a directory for the second member. The partially written final destination remains in place, so an operator could mistake it for a complete restore.

The helper uses `PurePosixPath` to screen manifest member names but later joins those names with the host `Path`. Inspection with `PureWindowsPath` shows that `..\\sibling-sentinel` has no `..` component under the POSIX parser but does under the Windows parser, and a drive-qualified `C:\\outside\\payload` is absolute to Windows. This suggests a Windows-specific escape risk; it was not executed on Windows and is not reported as a Windows runtime reproduction.

## Minimal corrective direction

Replace every security-relevant `assert` with an explicit condition and error path, including outer/archive member checks, path/type/mode checks, destination precondition, and post-write verification. Do not rely on assertions for any required behavior. Keep the full archive and manifest validation ahead of output creation.

Before extraction, also reject paths unsafe under the target platform and reject duplicate or normalized aliases and file/directory prefix conflicts. Extract into a private staging directory, verify the staged result, and promote it to the requested destination only after the whole restore succeeds; clean staging on every failure. Use a promotion operation with no-overwrite semantics where available, because the destination may appear between the initial check and final promotion.

## Integrity versus authenticity

The manifest's archive digest and per-member digests can establish consistency of the archive against that manifest, if all checks actually run. They do not establish who made the manifest or whether it is the intended release. The plain `SHA256SUMS` file is also not a signature: someone able to replace both archive and manifest can replace the checksum list too. Authenticity requires a separately trusted signature or checksum obtained through an authenticated independent channel. This audit makes no provenance/authenticity claim.

## Evidence integrity

Before and after testing, `sha256sum -c SHA256SUMS-20261003T1256Z.txt` in the public checkpoint directory passed for all six listed files, including the archive, manifest and restore helper. This verifies those bytes still match their adjacent checksum list; that list itself is not authenticated by this check.
