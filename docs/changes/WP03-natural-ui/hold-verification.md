# Held finalized utterance acknowledgement: verification

Base: immutable frontend1358 plus backend1419 dependency delta. Only browser/UI files and their tests are owned by this slice; Python/schema/generated output remain backend-owned. Generated TypeScript SHA256: `baf7c9e01511d1856a70336489a17a82d36f81f1526fe7e459fd6783e5784488`.

Append-only directed receipts are under `docs/verification/wp03-natural-ui-hold/runs/`:

- 001 RED → 002 GREEN: exact held-candidate acknowledgement, duplicate tuple reuse, no Input creation, fresh automatic turn, mismatch/failure/Stop/Close retention.
- 003 RED → 004 GREEN: an earlier hold promise cannot cancel a later hold when acknowledgement and fresh candidate arrive in one host task.
- 005: 95 focused controller, parsed transport and compiled page tests passed. Page tests use real session/continuous/playback classes with injected device primitives.
- 006: complete TypeScript build and web regression passed, 585 tests.
- 007 affected: after copying only hash-verified backend1419 changes, architecture (7 tests, including generated-contract drift guard) and the complete web lane (585 tests) passed with no source changes during execution. Receipt: `/workspace/shared/mira-natural-ui-hold-evidence-20261005T1420Z/007-affected/summary.json`.

The independent preliminary real ASGI/Actor-to-compiled-UI 12-case audit also passed on its copied stable combination. Its final signoff must use the director's immutable merged source. This document does not claim actual Google, physical audio, browser-device or mobile acceptance. Full/release and unrelated backend lanes are not claimed by the UI affected run. This verification document was written after the run; runtime files match its recorded hashes.
