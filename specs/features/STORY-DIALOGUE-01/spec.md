# STORY-DIALOGUE-01: Separate control intent from character speech

Baseline: frozen1645 source copied to an isolated repair tree. The new device diagnostic
has no build identifier; it contains metadata only and cannot prove the wording or TTS.
Owner: providers, uniquely registered by tests/contracts/test_*.py in tests/quality.toml.
Consumers: native tool preparation, Actor conversation compiler, native Responses,
chapter/invitation receipt reducers, optional speech and conversation archive.
Resources: offline synthetic fixtures and existing Python only. No credentials, user
computer, real providers, budgets, retries, image code or external transmissions changed.

### STORYDIALOGUE01-001

Given any native draft_cue, including natural-looking text and internal directions in any
language, when a dialogue-backed story/question/invitation tool is accepted, do not
compile or grant that argument. Return pending with awaiting_dialogue immediately, with
shown=false. Continue exactly once; only separately authored assistant dialogue enters
the normal compiler. Only this path may create subtitles, speech or remembered utterances.

### STORYDIALOGUE01-002

Given valid current finite prerequisites, bind the actual complete continuation subtitle
(up to the existing 500-character story bound) to chapter/invitation or role-question
metadata. These steps use one whole caption; ordinary deterministic caption splitting
stays unchanged. Only its exact actual receipt advances the state. A receipt arriving
before plan seal is valid own-state progress; repeat acknowledgement is idempotent.

### STORYDIALOGUE01-003

Given malformed, missing, overlong or failed continuation, do not advance the optional
step. Legal ordinary dialogue remains available. Stop, new input and Close fence pending
bindings and late completion. Recognition and gift scenes retain their distinct actual
receipts; tool requests, photo previews and pending feedback are not successful handover.
Pending recognition feedback stays natural without claiming an unreceived completion.

### STORYDIALOGUE01-004

Given actual continuation dialogue, only that dialogue may reach synthetic TTS, a receipted
archive and next-turn context. Tool control prose stays out of all three. Existing
history is not rewritten or purged by text heuristics; any earlier persisted contamination
requires separately authorized repair. No provider or real-device quality claim follows
from these offline structural checks.

### STORYDIALOGUE01-005

Given the exact pending/awaiting_dialogue application result, project the finite
awaiting_dialogue label into the existing closed diagnostic reason field. Actual Actor
observations must survive privacy encoding, metadata export and read validation without
carrying control text. Old pending records without this reason remain valid; arbitrary
reason strings and structures remain rejected. This is observability only and creates
no presentation receipt, state transition or extra model request.
