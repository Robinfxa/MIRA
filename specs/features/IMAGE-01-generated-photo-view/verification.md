# IMAGE-01 offline browser-software evidence

Final source: isolated `mira-generated-image-view-20261005T2251Z`, based on frozen `mira-integration-20261005T2238Z`. No frozen source, adopted appearance, providers, private credentials, network, installed dependencies or device operations were changed or used.

## Actual results

| Run | Result | Scope |
| --- | --- | --- |
| red-2253 | 2 failed, 1 passed | The initial three compiled tests observed missing generated-media reduction and a same-turn late generated grant passing the authored-only dismissal fence. |
| green-targeted-2300 | 56 passed | Same initial behaviors plus authored-photo readiness, visibility, scene-state and permit-gate regressions. |
| lifecycle-first-2303 | 37 passed | First-observed GREEN for additional real API/client/controller/executor synthetic PNG and decode-boundary scenarios; not historical RED. |
| grammar-red-2303 | 1 passed | Filename reflects an intended negative probe; actual result was GREEN. Trailing-newline rejection already worked. |
| web-2303 | interrupted, not a pass | The aggregate stalled at delayed main teardown. The new status callback looked up global document after the synthetic test removed it. |
| diagnose-locators-2305 | timeout | All 21 assertions completed but the process remained alive; not a pass. |
| locators-base-2306 | 21 passed | Same locator suite against the pre-feature compiled baseline completed. |
| final-image-locators-2307 | 60 passed, 1 failed | DOM status-node capture fixed teardown. A new positive late-grant test used too few fixed event-loop turns for real SHA completion. Replaced that timing assumption with an observable lifecycle milestone and a failure-only deadline. |
| image-locators-green-2309 | 61 passed | 40 generated-image tests/subtests plus 21 existing locator cases; no teardown stall. |
| web-2309 | 819 passed, 1 failed | Existing accessibility assertion required the authored photo's original close label. Restored it and switch the accessible label only while the generated image is displayed. |
| web-2310 | 820 passed | Complete web lane before the final older-activity revocation regression. |
| late-revocation-red-2312 | 1 failed | A stale older-activity snapshot could erase pixels already retained by local Stop. Displayed-resource reconciliation now follows the current-activity check; pending resources still revoke immediately. |
| web-2312 | 821 passed | Final complete web lane, strict TypeScript compilation, locally bundled application and all Node tests, including 41 generated-image cases/subtests. |

Final command (already installed local runtime; no installs):

```sh
/workspace/scratch/96ff05e059bf/mira-runtime-20261005T2230Z/.venv/bin/python tools/check_web.py \
  --output-dir /workspace/scratch/96ff05e059bf/mira-generated-image-view-evidence/web-2312
```

All logs and retained narrow compiled builds are in the separate `mira-generated-image-view-evidence` directory. Initial behavior logs are real observations, not a claim that later expanded test-file contents were historically run. The generated `contracts.ts` was copied unchanged from the backend owner's schema exporter; it is excluded from the frontend overlay to preserve that ownership. Existing inherited code-native vendor bundling warnings remain unchanged.

## Covered observable boundaries

- IMAGE01-001: real authenticated API request with exact resource/effect/epoch/activity/content digest; MIME/cache/redirect and bounded-reader failures; actual SHA256 over canonical synthetic PNG bytes; decoded-dimension check; immutable owned bytes; status projection is not a grant.
- IMAGE01-002: decoded visible DOM commit before receipt; text advances while the image is pending; one fetch/decode/receipt on repeated snapshots; late granted image after sealed text uses the same controller and leaves text unchanged; receipt barrier still fences the next input.
- IMAGE01-003: fetch, decode and pre-commit barriers crossed with Stop, newer input, Close, dismissal and revocation; same-turn pre-grant dismissal; fixed-photo replacement; visible image retention after Stop; release on dismissal/replacement/Close; reader cancellation, timeout and owned URL/listener cleanup.
- IMAGE01-004: honest safe textContent labels and accessible close label; isolated nonfatal image status; no character-state changes; all existing authored photo, speech, microphone, cue, main and teardown tests rerun.

This is software lifecycle evidence with tiny programmatically authored PNG fixtures and a controlled image decode boundary. It does not establish actual browser painting, a person seeing the image, visual quality, provider review quality or paid image capability. Backend integration, generated-contract check, affected/full/release checks and actual device acceptance belong to the integrated final tree and are not claimed by this frontend-only lane.
