# Cloud reset and source recovery — 2026-10-03

At approximately21:48–21:50 UTC both the old execution workspace and desktop were replaced. Unpublished working source, private probes, local receipts and runtime state were not available in the new workspace. No attempt was made to recover credentials from terminal/session history.

## Verified retained baseline

GitHub commit `424b3bfbb4a9b21db9ffe15bf025cdbddfd10650` was cloned and checked clean with git fsck. Its published1955 archive SHA256 remained `96ee73994dad009060511ff6f4c1f998f86e72fa65c451773a8aa019ae546535`, and the independent offline demonstration was restored under Python -O with662 matching member hashes/modes.

## Unpublished work to reconstruct

- v2 referent applicability, tests and spec: original author reconstructing from the existing task context.
- Explicit text application, strict no-speech generation, public/managed runtime reader, launcher and setup docs: original author reconstructing.
- Metadata-only public preflight and private writer, including separate content/charge consent: original author reconstructing.
- TTS timing instrumentation and later documentation: recovery pending; earlier published successful TTS timing facts remain valid.
- New detailed JEV private-probe diagnostics: offline12-case result was observed before reset, but final artifact/hash was not saved; do not treat a reconstructed copy as the old one.
- Production JEV validation details/UI distinction: no code had been written before reset; this remains new work.

Historical test counts and real service observations were reported before the reset. They do not establish that reconstructed files are byte-identical or that current tests pass. Every reconstructed slice needs fresh hashes and tests. No old RED receipt is being fabricated.

## Service and budget boundaries

Recovering source does not restore or prove usable API keys, Google ADC or Codex login. Private credentials were intentionally excluded from Git. No new provider request is authorized merely by recovery.

The last observed JEV ledger held15 attempts and USD0.0159615960 conservative cumulative reservation/estimate. Google held8 attempts and USD1.281664 pre-tax reservation; the last one-shot scope was consumed. These totals must not be reset or silently refunded. Restored accounting must explicitly identify the retained aggregate evidence and preserve all unknown-cost reservations.

## Recovery checkpoint at 2026-10-04 00:00 UTC

The reconstructed v2, explicit text entry, public metadata preparation, TTS timing and production safe JEV diagnostics were frozen and tested again. The23:11 public projection passed all12 local release lanes (1416 Python and218 Node tests, plus package/startup), with742 source hashes unchanged. Its50-file UTF-8 delta bundle was published on the recovery branch at `b9acce5a7b9d86a55e8888b94f1488339555dde2`, then read back in full by the parent. Main remains the1955 baseline. Recovery bundles are full-text restore artifacts, not newly expanded app trees or remote application CI.

Further bounded changes have separate synthetic evidence: retaining sanitized logs in the real text entry, explicit historical JEV accounting, resource-bounded opt-in voice composition, and the approved exact readonly managed installation guard. The guard does not modify operating-system permissions or authentication. The operational JEV ledger now explicitly retains15 historical attempts and USD0.0159615960, with zero new rows; it does not invent lost individual records. Google’s8 attempts and USD1.281664 reservation remain unchanged. No new model/provider call has been made after reset. These later changes require their own frozen release and real acceptance; the pre-reset model outcomes are not new validation.
