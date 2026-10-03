# Independent restore-helper refinement review

Review date: 2026-10-03 UTC  
Reviewed helper: `tools/restore_checkpoint.py`  
Reviewed SHA-256: `81d61d0d2edc6858971a3eba53a09b5d5499b33375f62eb893ccb91046dc569c`

This is a separate review record for the candidate above. It does not replace or rewrite earlier checkpoint evidence, RED/GREEN results, or reports. The prepared 12:56 source archive, original helper, manifest, and public sidecars were not modified.

## Independent checks

- Reran the targeted project suite against this exact helper: `35 passed in 5.38s` under the repository Python 3.13 environment.
- Reran tiny synthetic archive cases for valid restores and corruption/path/destination cases against both the unchanged prepared helper and this replacement. The replacement refused invalid outer/member hashes and sizes, relative/absolute traversal paths, duplicate ZIP entries, and existing destinations under normal Python, `-O`, and `PYTHONOPTIMIZE=1`. Valid synthetic content and Unix file modes restored under all three invocation forms.
- The old helper reproduced its expected optimized-mode hash/path/duplicate bypasses and its partial final output on the safe-name `a` / `a/b` conflict. The replacement refused that conflict without leaving a final destination or staging directory.
- The newly covered Windows device/forbidden-name cases are rejected on Linux as intended. `relative_path` accepts 64 components and refuses 65. This is path-rule inspection/testing only; no Windows execution is claimed.
- A wrong EOCD count, a test-only lowered central-directory byte cap, and an oversized central filename length each fail before `ZipFile` is instantiated. An ordinary ZIP comment is accepted.
- A standards-shaped ZIP64-end record and locator is refused before extraction, with `zip_directory_bound` because the classic EOCD directory-end equality fails before the later locator check. A nonzero EOCD disk marker is refused.
- SHA256SUMS verification for all six listed prepared-checkpoint artifacts still passes after these checks.

All generated archives, manifests, outputs, and sentinels were confined to fresh temporary roots that were automatically removed. No network, UI, credentials, or Git operations were used.

## Remaining format-scope findings

1. **Prepended-stub ZIP layout accepted.** A synthetic ZIP with an in-temp `MZ`-like prefix and rebased central-directory/local-header offsets restored successfully. The prefix was never executed. This demonstrates that the parser rejects common prepended archives with original relative offsets, but does not reject a prepended-stub layout whose offsets are rebased. If the helper must reject all self-extracting/stub-prefixed layouts, check local-header offsets (or file start) as well. Otherwise narrow the wording to the exact rejected offset/layout form. This is a format-claim mismatch, not an extracted-path escape.

2. **Central-directory per-entry disk marker not checked.** Patching a central-file-header `disk number start` from 0 to 1 while leaving the EOCD as a one-disk archive is an inconsistent/malformed marker. The helper accepts and restores the payload because the preflight currently does not inspect that field. The resulting file still matched the expected member hash; this does not demonstrate acceptance of a valid multi-volume archive. To claim all nonzero volume markers are refused, inspect CEN disk-start fields and ZIP64 disk-start extras, or narrow the claim to EOCD-level multi-disk rejection.

3. **Single-dot relative path admitted, then safely refused later.** `relative_path('.')` passes because `PurePosixPath('.').parts` is empty. As a regular file member, it fails when opening the staging root as a file; staging is removed and no final destination is left. Explicitly rejecting `.` would make the lexical path contract complete and give a stable fixed error.

The archive/member hashes establish consistency with the supplied manifest, not the manifest's authenticity. Existing private-parent/no-competing-writers and non-Windows-execution limits remain.

## Disposition

Integrity checks surviving optimized Python, the newly bounded central-directory scan, staged cleanup, and the Windows lexical cases passed independent tests. I do not give an unqualified green to broad “self-extracting” or “all multidisk marker” rejection claims at the reviewed SHA until those claims are narrowed or the corresponding fields/layouts are rejected. The candidate’s other verified results above remain valid for the tested Linux/Python environment.
