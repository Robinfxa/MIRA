# Natural UI v2 verification

Source base: immutable frontend v1 `mira-natural-voice-ui-frozen-20261005T1318Z`. Backend-generated v2 TypeScript contract SHA256: `4361f089c585e6b1d8615ec286882f0f2555ca4fe46a4479ae06fa7aa798ff82`. The schema, generated contract, Python recognition service and playback sink remain owned by their respective slices.

All results below are offline and synthetic. Runs are append-only under `docs/verification/wp03-natural-ui-v2/runs/`. No dependencies, credentials, providers or hardware were installed or invoked.

| Evidence | Observed result |
| --- | --- |
| 001 → 002 | RED/GREEN: an utterance first observed during playback stays manual even after duplicate readiness, while a fresh activity after explicit interruption can auto-send |
| 003 → 004 | RED/GREEN: ordinary natural final/endpoint-pending text remains in recognizing state with manual fallback available |
| 005 → 006 | RED/GREEN: a synchronously reported microphone denial does not open a provider lease afterward |
| 007 → 008 | RED/GREEN: withheld earlier text survives a newer automatic send and transport failure before prefix reset |
| 009 → 010 | RED/GREEN: endpoint bases, correlated reset ordering and bounded recognition status |
| 011 → 012 | RED/GREEN: automatic cleanup after accepted utterance-count exhaustion does not emit a revoking user Stop; explicit Stop still does |
| 013 | 111 passed / 1 failed: existing manual fixture claimed segment 3 with a declared maximum of 2; corrected to valid segment 1 |
| 014 | 565 passed / 2 failed: legacy help-copy assertions no longer matched the natural-mode description; updated truthful text and expected labels |
| 015 | Complete web build and regression: 567 passed, 0 failed, source unchanged during the recorded run |

The final coherent architecture/affected result will be recorded separately after the backend v2 source freezes. A web-only pass does not establish backend integration or real-device acceptance. The independent ASGI-to-production-browser-client bridge is owned by the separate verifier.

## Final coherent affected check

After copying only the hash-verified backend1355 delta, `tools/check.py --files <owned UI paths> --jobs 3` passed architecture (7 tests) and the complete web lane (567 tests). Contract exports matched. The run started 2026-10-05 13:57 UTC with no source changes during execution. Receipt: `/workspace/shared/mira-natural-ui-v2-evidence-20261005T1357Z/016-affected/summary.json`. Backend/domain/provider/full-release and actual-device checks are not claimed by this affected run. This paragraph records the completed result after execution.
