# Confirmed known issue: 14:48 checkpoint history-delivery ordering

This additive notice applies to the immutable `mira-integration-20261003T1448Z.zip` (SHA-256 `d2d5dee52eab6127d53a24195e8d22a10d3ba91458dc8c4e8b6e64a6b96a1a43`). It accompanies the checkpoint at publication and supplements its embedded known-gaps and release evidence without rewriting the archive.

## Confirmed after the recorded release suite

An independent real local HTTP rehearsal test reproduced this ordering defect: a delayed receipt for a photo that has already been presented can be accepted only after the next generation context was captured. The resulting follow-up can incorrectly say the photo was never opened, even though authoritative presentation history becomes true when the delayed receipt arrives.

This is a fact-delivery versus generation-snapshot ordering problem. No stale media replay was observed in this test. The earlier load/decode/readiness and Stop suppression corrections remain separately verified; they do not close this newly reproduced history-delivery race.

The recorded **1,155 Python + 185 Node / 12-lane passes** remain truthful for those executed tests. They are not complete causal-history or product acceptance. A later stage is assigned to repair this defect; this frozen checkpoint does not contain that repair.

## Source binding and limits

Independent reproduction was reported against snapshot manifest SHA-256 `bea6109c080504e9ea9dafd67fa5c3190bfc7eba7a12691887dbb6a846f22787` and controller SHA-256 `361b196c1be60e3d2bfe1459ee359d1fe9d46b21cc0bf3a4fd21f4171c2e5e4e`.

This was a software/real local HTTP reproduction, not an observed user browser/device incident. Real browser pixels, microphone/speakers, live-provider/runtime admission, JEV quality and 3–5 minute recording gates remain open as documented. Original archives, source and prior receipts are unchanged.
