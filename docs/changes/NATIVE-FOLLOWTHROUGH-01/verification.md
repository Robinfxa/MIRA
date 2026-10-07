# Native follow-through repair: evidence and limits

Frozen origin: 355609fe43149a902eb1e5ace53a1e3879826a1d at mira-final-integration-20261006T1926Z. The original2012 source and native dialogue acceptance artifacts were not edited. This work uses mira-natural-followthrough-fix-20261006. No provider, credential, Mac, image-generation, visual, budget or image-job work was performed. The independent NATIVE-PHOTO-INTENT-01 instructions are separate commits.

## Diagnosis and final contract

Original turn11 recognized the fictional role and receipted the actual continuation invitation. Turn12 refused. Turn22 sent a default-scope global Stop while an unrelated image job was pending. Turn26 clearly reconsidered and accepted, but the model-visible contract only offered x.gift_offer/reopen_gift, creating another invitation; turn27 then supplied the second acceptance and completed actual handover. The defect is specifically refusal recovery, not ordinary active-offer acceptance.

A new native reopen_accept_gift on x.gift_accept requires exact current reliable input, the retained declined offer ID and its exact original effect reference. One optional typed declined_gift_offer records offer ID, effect ID/digest and its acknowledged gift_offer receipt. It is history, not an active offer. Both IDs reach the real production Responses request via facts.character_story.chapter; the same tool definition exposes the new enum and semantic distinctions. No string scanning grants semantic authority.

Global Stop still revokes pending grants. It now suspends a declined chapter while preserving its historical invitation identity. Only a fresh explicit reopen_accept_gift clears that suspension and stages a new handover; a plain accept_gift or mention cannot. Reply interruption keeps the historical reference. Exit/checkpoint reentry clears it, completed handover clears it, and a new offer receipt replaces it. Old checkpoint dictionaries without this additive field remain readable with no inferred reference. The public HTTP DTO is unchanged. Exact handover receipt alone completes the gift; preview or original invitation receipt never substitutes.

The camera has only its existing held resting/raised poses. perform_action explains that return_camera remains held and cannot put it on a table. A matching receipt reports pose, camera_held=true and placed_on_table=false. Pending results make no completed-motion assertion.

## Executed local evidence

All logs below are append-only under docs/verification/native-followthrough-01/runs; synthetic transport/tool choices are regression evidence, not provider or natural-model proof.

- 001-red: 12 failed, 7 passed. Missing typed reconsideration/projection and held-camera guidance.
- 002-green: same 19 tests passed, unchanged test bytes within the pair. This only covered refusal without the observed intervening global Stop.
- 003-targeted-cross-layer: 166 passed, baseline no-Stop version.
- 004-full-stop-red: 3 failed, 4 passed. Full refusal→globalStop→fresh reconsideration and cancelled handover→fresh acceptance failed as expected.
- 005-full-stop-green: same 7 tests passed, unchanged test bytes within the pair. Distinct new grant/receipt required; late old receipts rejected.
- 006-final-cross-layer: 180 passed, 2 failed. Existing 12,000-byte instruction capacity exposed an overlong independent photo-intent prompt; no budget/assertion was relaxed. The separate prompt-only fix and its verified 12-case pass are recorded in NATIVE-PHOTO-INTENT-01.

Final targeted/affected and independent audit results are reported separately against the frozen source manifest. No release, device or new natural-dialogue success is claimed here.

## Recorded cat-image contradiction only

Original turn21/invocation27 model arguments request a living orange cat. The production compiler string instead requires “an empty environment and inanimate objects.” Actual default Stop at turn22 cancelled that second job before controlled failure. The four exact source artifacts and hashes remain in mira-native-dialogue-acceptance-20261006/evidence/defects/cat-media-scope/finding.json. No animal pixel outcome or provider rejection is established. No animal/image scope policy or image compiler file was changed.

## Final frozen-source checks

Runtime/test freeze: 42089857dc4f68cf8676bb7e3a70e892462a7c56. Final targeted 007-final-cross-layer passed 182 cases. Independent external audit passed 35 cases (32 native-wire/Actor/ASGI boundaries and 3 old schema checkpoints), report /workspace/shared/mira-gift-reconsideration-audit-20261006/final-42089857/report.json; it verified unchanged source and excluded real model/device/image-provider claims.

Required affected run from355609fe completed with unchanged source digest af8ba281224e8f170450dfba3a8c8756cc0d5488e24957c133f0520603663a0a. All 10 runtime/test lanes passed: architecture7, domain36, env126, config50, actor40, providers4377, HTTP118, tooling304, continuous116, and web including strict build/Node tests. The original overall report remains FAILED because specs requires ### requirement headings and the two new specs used ##. No runtime or test failed in this run.

The only subsequent source-fingerprint changes are those two specs' heading levels. A separate specs-only run passed after that correction. The 10 unaffected large lanes were not repeated, as directed. Evidence and exact source correspondence are in /workspace/shared/mira-natural-followthrough-fix-evidence-20261006T2111Z: affected/summary.json (original overall failure retained), spec-heading-fix/summary.json (pass), source-manifest.json (runtime freeze), final-source-manifest.json, final-runtime-manifest.json, and validation-correspondence.json. No claim of a single all-green affected report or release/package/smoke run is made. The documentation-only descendant preserves every runtime/test hash from the audited freeze.

## Initial checkpoint compatibility finding (superseded below)

The first candidate was backward reading only, not arbitrary downgrade compatible. New code reads the verified schema3/4/5 fixtures and old chapter dictionaries with the new field absent. With explicitly enabled/authorized persistence, existing StoryCheckpointStore.save actually writes declined_gift_offer (including null) into its schema6 chapter JSON. Loading in new code preserves the historical reference; StoryRuntime.from_snapshot and normal reentry then clear that reference, active role and offer authority. The original2012 reader355609fe rejects new chapter dictionaries because it requires an exact field set, even when the additive field is null. Do not reuse a checkpoint newly written by this revision when downgrading to2012. Default ephemeral --story does not write a store. No migration or real user store access was performed. A synthetic temporary SQLite save/load and exact original-reader check is recorded in checkpoint-directional-compatibility.json in the external evidence directory.

## Measured capacity, unchanged limits

Existing affected-provider large-context receipts were reused without rerunning the group. Both chatgpt_subscription and openai_api measured the same UTF-8 sizes: start instructions11,757 bytes; continuation instructions11,926 bytes under the unchanged <12,000 test bound (74 bytes below the boundary). Largest single prompt55,836 bytes under65,536 (9,700 bytes remaining); continuation's fresh prompt55,806. Initial HTTP body74,661 bytes; full continuation body129,272 bytes under131,072 (1,800 bytes remaining). Sources: affected/providers/pytest-tmp/test_all_shared_canon_recent_d0/wire-sizes.json and corresponding d1 in the external evidence directory. These are the maxima of the exercised large-context fixtures, not a guarantee for every possible input. Additional instructions or fields must respect both duplicated continuation prompts and whole-body limits; no bound was raised.


## Final persistence boundary

The integration owner requested avoiding that unnecessary downgrade break. The final revision changes only adapters/memory/story.py::_story_to_dict: serialize the existing chapter, then omit declined_gift_offer from the local serialization copy, including null. The current runtime and model projection still carry the reference; nothing mutates the live ChapterState. The persisted schema remains6 and the original2012 reader can read new valid checkpoint bytes. New load has no transient reference; normal reentry still clears role/offer authority. New code continues to accept previous schemas and the additive-field read path, without migration. The initial incompatible finding/report above remains historical evidence only.

Actual 008-checkpoint-red: four failures across dormant and declined snapshots (portable omission/reentry cases and exact original2012 SQLite-reader cases). Same 009-checkpoint-green: four passed. All stores are fresh synthetic private temporary SQLite files; the old reader runs from frozen355609fe with bytecode writes disabled and reads these new synthetic files only. The real user's database was never accessed. External exact-reader test source lives under checkpoint-compatibility/test_original_2012_reader.py in the external evidence directory; portable regression is tests/contracts/test_native_reconsideration_checkpoint.py.

The persistence-only revision2a5eb85 passed incremental affected verification against ca1c6a8: all7 selected architecture/config/Actor/providers/HTTP/tooling/specs lanes passed. Its direct checkpoint consumer run010 passed112 tests. The requested third checkpoint state was verified separately: the full decline→globalStop→current reopen_accept→new handover receipt ending completed was saved, and the frozen2012 actual SQLite reader read completed successfully without modifying the file (012-completed-checkpoint-old-reader, 1 passed). Run011 was a collection/configuration error from invoking only an external test without the project's pytest config; its logs are retained, and it is not behavioral RED evidence. No additional large group was run for this third state.

A separate native-agent run on the preserved42089857 source established the full observed Stop path in actual unscripted choices: revision-04-gift-stop-reaccept turn7 selected x.gift_accept/reopen_accept_gift with the retained exact offer/effect, rendered and receipted a new handover, and reached completed with one continuation and no second invitation. Evidence is in mira-native-dialogue-acceptance-20261006/revision-04-gift-stop-reaccept; the bridge owns that original evidence. This is distinct from the synthetic tests and does not certify provider images, real-device audio or release readiness.
