# Verification: M06 recall content ranking

Executed 2026-10-06 in an isolated /tmp copy using the already available Python environment. Synthetic private temporary stores and httpx.MockTransport only; no provider, credential, real DB, .env, install, Mac, user Library or device access.

Final changes: new application/conversation_recall_ranking.py; import and ranking call only in conversation_archive.py; one new contract test file, this report, source research, feature spec and traceability. Test ownership is the existing unique providers glob tests/contracts/test_*.py in tests/quality.toml; no second owner or shared config edit.

## Observed results

- 008-final-red.txt: 7 behavioral failures, 1 pass using the unmodified baseline conversation_archive.py and final test file. Failures prove older Chinese preference/episode loss, metadata/Latin substring poisoning, uncompleted audio text winning selection, omitted corrected statement, both route wire paths losing recalled evidence after reopen, and Mira's own past first-person dialogue disappearing.
- 009-final-green-regression.txt: 118 passed across the new 8 tests and nine existing archive/Actor/manual-memory/story/projection/wire modules. The new native tests capture actual serialized request bodies through MockTransport for both chatgpt_subscription and openai_api; fixed synthetic response strings test plumbing, not model answer quality.
- 010-spec-links.txt: the four new requirements reference collected tests. This is link validation only.
- 011-architecture.txt: five selected dependency, environment-read and import-side-effect checks passed. Public contract export and full architecture lane were not run in this slice.

The definitive RED and GREEN share the final test file unchanged. Earlier runs remain retained: 001 and 003 had 6 behavioral failures/1 pass; 002 had two test-expectation failures because unrecognized chapter state is omitted rather than serialized with false; 004 passed 7 tests. An initial broad collection (005) lacked the copied tools directory; after supplying public tooling, 006 was 116 passed/1 failed because copied public renderer assets were absent. Adding the public resource inputs produced 007's 117 passes. These environment/setup attempts are not product regressions or hidden passes.

The shell redirected pytest output and then inspected the logs; individual process exit codes were not independently saved in these earlier commands. Counts above are from retained actual pytest summaries. Do not represent this as the project's full signed quality receipt. Integration owner must run the affected quality gate against the combined final source.

## Final regression command

The existing interpreter ran pytest -q -p no:cacheprovider on:

- tests/contracts/test_conversation_recall_content_ranking.py
- tests/contracts/test_conversation_archive.py
- tests/contracts/test_actor_conversation_archive.py
- tests/contracts/test_personal_memory_projection.py
- tests/contracts/test_personal_memory_unavailable_wire.py
- tests/contracts/test_memory_availability_wires.py
- tests/contracts/test_first_person_story_memory.py
- tests/contracts/test_story_persistence_independent_regression.py
- tests/contracts/test_actor_memory_recall.py
- tests/unit/test_scoped_memory.py

## Preserved and remaining limits

No eligibility, scope, stage, schema, byte/row bound, write behavior, grant, tool or prompt changes. Scope/session negatives and correction/forget invalidation pass existing regressions. Old recalled “我是夏禾” remains historical text while current typed role stays unrecognized; no newly acknowledged presentation appears. Unavailable recall drops old source text from actual requests.

Selection uses text overlap, not semantic understanding: first8192 query characters and64 distinct terms, eight whole output rows within the existing byte limit, and the existing finite scoped store/snapshot. Equal overlap scores prefer the newest source; free text negation alone does not automatically revise the local database. Explicit correction/forget operations remain the reliable suppression route. Manual SQLiteMemoryStore recall retains its prior matcher and is not changed by this patch. Long sessions, synonyms, out-of-window sources, live model character quality and real device behavior remain unverified.
