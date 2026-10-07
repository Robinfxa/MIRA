# STORY-REPLY-01: PTT reply fence preserves presented conversation choices

Base d29ae4adbe174cfbaf7ec5cfebcde852d69486e9 remains frozen. This incremental branch owns only domain/story.py, application/actor_story.py and native_character_tools.py. The image/Actor owner applies two separate Actor hunks: route scope=reply to reply_fence(epoch,presented_effects) after the output/cutoff fence, and use native_role_question_current for question advertisement. Public Stop schema/frontend remain that owner's work. Unique providers owner is existing tests/contracts/test_*.py. No provider calls, dependency/budget change or fake reliable input.

### STORYREPLY01-001: Reply-only output boundary
Given a presented gift offer, reply_fence moves to the exact next output epoch, clears unpresented pending state immediately, and preserves role/offer/suspension and reliable input/history. One next acceptance can hand over. Global Stop retains its revocation semantics; pending old recognition/offer receipts can only reconcile historical facts, never reactivate current role or offer. The Actor still rejects receipts outside its real presentation cutoff.

### STORYREPLY01-002: Next actual user input after PTT
A presented x.ask_role question keeps its original effect/source epoch. Only an exact chain of reply control frames extends the frontier before the next actual user input. That input consumes the opportunity, even if its reply is stopped. Confirmation uses the original reference and current reliable input; wrong, unseen, superseded, consumed, cross-session or skipped-epoch references stay invalid. A global Stop clears it. No arbitrarily old/future epoch admission.
