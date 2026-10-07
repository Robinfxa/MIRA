# WP03 interrupted request continuation

Source baseline: immutable mira-natural-conversation-capture-20261005T1444Z. Scope: Actor/context and fixed generation instructions. Input wire fields are integrated by the sole HTTP/schema owner. No audio/frontend changes, provider calls, automatic memory recording, or classification calls.

## Requirements

### WP03INTENT-001 Preserve accepted intent and qualified facts
Given an accepted request, a partial presentation, and an explicit interruption supplement, when the supplement is accepted, generation receives the original request and accepted additions as one versioned request context. Existing reliable user_inputs, presented_effects, receipts, and software audio progress remain untouched. Generated reply text may be reused as an untrusted plan, but never becomes proof of display or hearing. PCM counts never imply a word prefix.

### WP03INTENT-002 Bounded accepted revision chain
Given three consecutive additions, each citing the latest accepted request ID and its original output epoch, all accepted inputs remain ordered with their IDs/source/epoch and revision. Unsent, provisional, and rejected inputs never join the chain. At most eight inputs and 32 KiB of input UTF-8 text; exceeding this starts an explicitly marked independent current request and retains ordinary factual history. Draft evidence is capped at eight text pieces and 16 KiB, deduplicated by stable identity with an explicit omitted-evidence flag.

### WP03INTENT-003 Stop, new topic, and Close have different effects
Stop revokes execution but retains the latest accepted intent so an explicitly linked later supplement may continue. Independent input or explicit new_topic starts a new chain without deleting historical input/presentation facts. Close rejects all new input and clears the transient chain. Model interpretation of current text can recognize a changed topic; there is no keyword classifier or extra model call.

### WP03INTENT-004 Scope, retries, and stale work
A continuation pointer resolves only against this Actor's latest accepted chain head. Unknown, stale, or foreign pointers accept ordinary valid current text without fetching other history. Exact retries include relation/pointer identity and do not append inputs, receipts, or generation calls. Changed retry metadata conflicts. Late cancellation-resistant results cannot update the current chain or revive grants.

## Resources, consumers, and evidence

Unique owner: actor lane for tests/unit/test_interrupted_intent.py; provider consumer: existing generation prompt serializer and shared review evidence serialization. HTTP integration tests are separately owned by http. Application contracts trigger conservative aggregate impact. Tests use synthetic providers and ASGI only, existing dependencies, no device or model-quality claim. RED/GREEN and affected receipts are saved outside the checkout under a unique append-only run directory. This source capture has no Git metadata, so affected uses a complete explicit file list rather than inventing a merge base.
