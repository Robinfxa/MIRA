# IMG-ADAPTER-01 v2: audited adapter boundary repairs

Current repaired source: mira-story-image-adapters-v2-20261005T2309Z. The original 2252 source, 2301 handoff, independent 2302 audit and every prior log remain unchanged. The initial 95-test result in verification.md is historical and did not satisfy the subsequent independent gate.

The untouched independently authored 120-case audit now passes in full. The owned suite now passes 124 cases (original 95 plus 29 regressions/compatibility cases). These are separate runs, not a count of unique requirements. Final records report zero source changes during execution.

## Repaired behavior

- A per-request cancellation/deadline fence checks pending task cancellation and the absolute deadline after HTTP/client entry, each received body piece, terminal iteration, stream cleanup, client cleanup, JSON parsing and immediately before adapter results. An injected transport that catches CancelledError cannot turn a cancelled/expired operation into success. No retry or extra request was added. This cannot forcibly stop code that never returns.
- PNG container verification is followed by bounded validation of one complete zlib stream, including Adler checksum/end, no unused compressed tail or second stream, and exact header-derived filtered raster length. Each temporary decompressed output is at most 64 KiB. This also rejects oversized decompressed data and extra raster bytes hidden inside an otherwise complete stream. It interprets no filters or pixels: Pillow still verifies, decodes, converts and re-encodes the raster.
- All supported opaque modes convert through a validated RGBA image before RGB canonicalization. Fully opaque palette tRNS byte arrays preserve every pixel without triggering Pillow's direct palette-to-RGB warning. Nonopaque pixels still fail.
- Valid split IDAT, Adam7 interlacing and packed 1/2/4-bit palette rows continue to decode through Pillow.

## Actual repair evidence

- 006-independent-audit-red: unchanged independent tests reproduced 13 failures and 107 passes.
- 007-owned-regressions-red: 22 failures and 1 pass covering the reported defects, cleanup cancellation and decompressed-size overflow.
- 008-independent-audit-green: all 120 independent cases passed after first repair.
- 009-owned-regressions-green: all 23 added cases passed, exact same test-file hash as 007.
- 010-raster-envelope-red: two tests proved a complete stream could still hide extra uncompressed raster data.
- 011-raster-envelope-green: those two tests passed after exact declared-length validation; same test-file hash as 010.
- 012-v2-owned-final: original tests plus all 29 new regression/compatibility cases, 124 passed.
- 013-independent-final: unchanged independent 120-case suite, 120 passed after the final decoder refinement.

Evidence directory: docs/verification/img-adapter-01/runs/. Independent test SHA-256 remains 6393ec9b9d67548fe560bcfd59e3907ed9943b153634578881ba481a240e4219, equal to its original audit RED record. repair-evidence.json records its exact source and comparison. The independent suite stays external and was not rewritten or weakened.

Interpreter remains the previously approved Pillow12.3.0 image-test environment. No installation, credentials, provider calls, runtime/frontend changes or live activation occurred. Ports/domain overlays are excluded from the integration delta. The director owns final integrated/independent gate decisions and full/package/release checks.
