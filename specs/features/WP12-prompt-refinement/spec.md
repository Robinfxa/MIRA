# WP12 prompt consolidation for native tools

Base: immutable mira-luna-tool-integration-20261006T1431Z (frozen 1515 source).
Owner: providers via existing tests/contracts/test_*.py unique-owner glob in
 tests/quality.toml. Consumers: shared author prompt, native tool and legacy tool
 requests, both direct provider routes, and CLI author instructions. Resources:
 existing Python environment, synthetic MockTransport, typed in-memory canon.
 No live model, paid calls, private corpus transmission or tool runtime changes.
 The integration owner performs affected checks against the final combined source.

### WP12PROMPT-001 One bounded author contract

Given any speech/memory/story/image flag combination, the fixed instructions stay
 below 12,000 UTF-8 bytes without increasing caps. Common voice must not prescribe
 legacy pose effects or JEV review on the native path. The current request's
 action contract alone selects available tool/proposal representations.

### WP12PROMPT-002 Continue the present conversation

Given a greeting, unrelated topic, or short follow-up after an outfit suggestion,
 instructions preserve first person, finite interests, ordinary factual answers,
 and the latest salient referent. They never require a canon detail, rain, cafe,
 lighthouse, clothing materials, plot invitation, or question on every turn.
 Prior awkward replies stay as attributed evidence, not examples to imitate.
 Explicit AI/reality/provenance questions remain truthful; no automatic labels.

### WP12PROMPT-003 State and canon outrank spoken recognition

Given a clear claim/confirmation of the authored friend role, request the supplied
 recognition operation. Prose acknowledgement alone does not activate the role.
 Typed pending/inactive state cannot yield shared role recollection. After an
 actual recognition receipt, released_role_canon and the current chapter remain
 first-person authored continuity, distinct internally from real user history.
 No projection fields, receipt requirements or state transitions are changed.

### WP12PROMPT-004 JSON dialogue and genuine function calls

Given any assistant message, dialogue stays inside the supplied JSON schema with
 correct escaping and no wrappers, fences, commentary or invented keys. Native
 function_call items are a separate protocol and must not be imitated in effects.
 A tool result and fresh facts govern the final text-only continuation; pending,
 failed and shown remain distinct. No parser repair or fabricated diagnosis of
 unknown real output is allowed.

### WP12PROMPT-005 Evidence limits

Offline request captures verify instructions, source fields, protocol and byte
 budgets only. Authored positive/negative examples are editorial cases, never live
 model measurements. Missing model output may come from local/provider budgets;
 prompt edits cannot establish the cause of the prior unidentified 102-byte output.

### WP12PROMPT-006 Choices without a reply template

Base for this follow-on: frozen1645 source at mira-post1515-integration-20261006T1623Z.
Owner remains providers through the existing tests/contracts/test_*.py glob.
Given a supplied character preference or concern relevant to the current topic,
the speaker can let it affect a choice or reason, without a scenery quota,
reaction-detail-question sequence, invented biography or forced plot. The same
first-person and truthful explicit-reality boundaries remain. Source labels and
technical statuses guide generation without becoming ordinary spoken lines.

Thirteen self-authored editorial pairs cover recurring greeting; off-plot hobby
and short follow-up; another photo with/without current generation capability;
indirect recognition, exact confirmation and released role canon; invited idle
topic; actual failure and pending result; explicit AI and ordinary why-here.
They are neither model outputs nor a semantic oracle. Both contrasts parse.
For each case, A and B traverse the real Direct Responses adapter with the same
synthetic context, tools and injected output; only instructions differ. Both
provider routes stay offline. Actual tool-result JSON is retained exactly.
The large-memory check keeps payload and instruction bounds separate and records
aggregate HTTP bytes; 65,536 is not asserted as a universal aggregate body cap.

No new calls, model, parser, timing, disclosure state, memory/security authority
or runtime topic gate. No external corpus is read or submitted. Subjective
improvement and genuine model tool choice remain not_run; the integration owner
performs affected/release checks on the final combined source.
