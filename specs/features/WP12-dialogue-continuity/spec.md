# WP12 dialogue continuity

Base: verified frozen0221 source capture (1,318 files; capture-manifest SHA-256
22a4f2e26a113fdc5ed88419596a2444a83261e2747cf25d632cdb87145fb686), copied to
mira-dialogue-continuity-next-20261006T0245Z. Local base commit:
56bfd5dd91393a0ab6d58ec976de922c04fc997d. Evidence is outside the source tree.
Owner: providers, uniquely covered by tests/quality.toml's tests/contracts/test_*.py
owner. Consumers: generation_context_data, native Codex and both direct Responses
routes; actual ASGI/Actor receipts remain authoritative. Resources: existing Python,
synthetic in-memory HTTP transports, public authored canon, no provider or credential
reads. No Actor, contracts, JEV admission gate, topic whitelist, control permission,
new media capability, database, or provider request-count changes.

### WP12CONTINUITY-001 Current dialogue precedes opening and inventory

Given an ordinary greeting after already presented dialogue, the fixed speaker
instructions must continue that exchange, without an unconditional introduction or
copyable introduction example. A repeated greeting does not reset scene state.
Given a short follow-up after discussing a different photo, the speaker must use the
recent actual exchange to identify its referent and ask only if unclear. Available
photos constrain display capability, not conversational topics. No alternate asset
means a candid response, without invented media, user memories, trips or promises.
These are generative instructions, not an output classifier or canned replacement.

### WP12CONTINUITY-002 Recent distinct reply references retain source identity

Given matching speech/subtitle wording in one output epoch and activity, the bounded
first-person shortcut selects at most four distinct same-turn texts, rather than
letting both modalities consume the four slots. Exact source rows remain unchanged
in presented_effects; omitted row counts remain exact. Identical wording in different
turns remains separately referenced. No accepted-only draft or partial/failed audio
becomes a presented reply. Existing omission counts remain accurate without new wire
fields, an invented turn pairing, semantic summary, hearing, or durable memory.

### WP12CONTINUITY-003 Existing Actor and adapter carry the actual exchange

Given the reported repeated greeting and photograph-question excerpts, synthetic
responses through the actual Actor and direct adapter preserve reliable input order,
qualified prior replies and current user_text on the next request. A second greeting
has ongoing_scene, with the previous opening visible in source evidence. The short
follow-up retains the preceding other-photo question and reply. Ordinary text remains
available with no JEV call. Stopped/unreceipted output stays out of dialogue history.
The test deliberately injects responses, including bad repetition, and must not claim
the model generated or improved them. Its purpose is to establish the software wire.

### WP12CONTINUITY-004 Bounds and generation/review bindings stay explicit

Given a long synthetic session, every retained first_person_dialogue reference resolves
to the same exact source row after bounding/remapping. Omitted history stays explicit,
not a fabricated summary. Generation and review receive the same story/dialogue data.
Existing instruction/request budgets remain unchanged. This slice needs affected
provider/Actor/HTTP/config/architecture/spec checks; full/release, real provider quality,
Mac/browser/audio and dynamic image execution are not established by these checks.

## Live acceptance still required

A future authorized live conversation should include two greetings, a topic change,
other-photo request followed by “看看？”, and a return to an earlier detail. Evaluate
whole replies for contextual understanding, natural variation, factual limits and
absence of forced lighthouse/cafe callbacks. Matching keywords or a chosen sentence
cannot pass this layer; no live call is authorized or executed here.
