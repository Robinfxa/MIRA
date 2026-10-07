> **历史归档说明 / Archive Notice**: 本文件所描述的历史发布包 ZIP 及对应的 `SHA256SUMS-*.txt` 校验文件已完整保留在 Git 历史与 `archive/pre-final-20261007` 归档分支中；当前 `main` 分支为主干展开源码，不在此保留指向旧 ZIP 的冗余清单。如需按历史包还原，请检出归档分支。

# MIRA integration checkpoint: 2026-10-03 11:04 UTC

**Stage status: offline-test-green with known interaction integration defects.**

New adversarial checks identified two open defects after the recorded run:
- Multi-range subtitle and visual effects can present before queued speech.
- A safe Chinese error message is overwritten by a stable error code.

The recorded 741 Python / 115 Node offline result remains valid; interaction acceptance is not complete. Fixes are assigned to a later checkpoint. This outer README and manifest contain the latest findings; the embedded archive metadata predates this update. The immutable source archive and its hash are unchanged.

This is a **sanitized source-archive backup**, not an expanded Git source tree or a release. Earlier baseline and WIP backups remain unchanged.

## Verified scope

The coherent local automated run passed **741 Python tests and 115 Node tests**, across 10 selected lanes. Before/after source digests match, and every covered source-file hash matches this archive. The archive contains 598 source/document files plus checkpoint metadata.

**Not run for this checkpoint:** packaging, smoke, live providers, browser/device audio, original architecture acceptance, and remote CI. The privacy-filtered projection was not rerun as a complete release. Historical project README and verification files describe earlier snapshots; this checkpoint's acceptance manifest records the current result.

## Restore

1. Download `mira-integration-20261003T1104Z.zip`, `MIRA-CHECKPOINT-MANIFEST-20261003T1104Z.json`, and `SHA256SUMS-20261003T1104Z.txt`.
2. Run `sha256sum -c SHA256SUMS-20261003T1104Z.txt` in the download directory (or compare SHA256 hashes with an equivalent tool).
3. Extract the archive into a new empty directory, preserving nested paths. The ZIP has a `mira-integration-20261003T1104Z/` top-level folder.
4. Compare member hashes with the manifest. Read `docs/checkpoints/20261003T1104Z/README.md`, the project README, and the relevant setup documentation before running anything.
5. Install declared dependencies according to project instructions. Supply private local configuration separately using the blank environment examples. No credentials, authentication stores, dependency folders or runtime state are included.

## Privacy and exclusions

Code, original application assets, blank environment examples, specifications and readable sanitized summaries are included. 679 source/evidence paths are excluded: raw verification logs, historical/generated previews, the raw supplied PDF, and evidence with machine-specific private paths. The archive includes an explicit exclusion record. No symlinks are followed; `node_modules` is not included. Some historical evidence links therefore intentionally refer to material retained privately.

## Publication status

This upload preserves a recoverable stage checkpoint. It does not establish browsable source publication, a release, live-provider readiness, a deployment, merge, or remote CI success.
