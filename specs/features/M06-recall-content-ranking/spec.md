# Source-text ranking for opt-in historical recall

Baseline: immutable 20261006T1515 delivery source captured in mira-luna-tool-integration-20261006T1431Z. Owner: providers, already uniquely registered by tests/quality.toml's tests/contracts/test_*.py glob. Consumers: SessionConversationBinding, generation_context_data, native/legacy provider request serialization. Resources: synthetic temporary private SQLite, in-memory HTTP transport; no actual credentials, providers, browser, user libraries or private databases. All other lanes remain for integration owner.

### M06RCR-001: Chinese and Latin evidence ranking

Given an older exact preference or episode and at least eight newer unrelated rows, when an explicitly selected prior session is recalled with overlapping Chinese words or Latin words, relevant dialogue outranks unrelated recency. Chinese matching uses bounded character bigrams, not semantic understanding. Whole Latin words avoid substring matches. Only accepted/corrected input text or qualified subtitle/completed-speech text contributes. IDs, metadata, pose values and uncompleted audio text contribute no score. Equal scores prefer newer records. Exact rows, provenance, chronological output, eight-row and byte limits remain unchanged.

### M06RCR-002: Durable source and correction boundaries

Given authorized recording, closing/reopening the same scoped archive preserves sources, and source-text ranking improves the resulting serialized native request. Other scopes/sessions remain inaccessible. Corrected and forgotten original evidence stays suppressed; equal-topic newer denials outrank older affirmations. Ranking does not infer durable preferences, validate user claims or promote plans to completed events.

### M06RCR-003: Role and absence boundaries

Given an old archived role claim or future plan, a new unrecognized role remains unrecognized even when that old text is recalled. Source rows remain historical untrusted quotation; they cannot release shared canon or change current permissions/state. Unavailable recall excludes content on the wire. No setting, storage permission, network call, provider grant, summary, biography or self-personality learning is added.

### M06RCR-004: Explicit limits

Keep existing snapshot validation and candidate window, request/term work bounded, no full-corpus loading or DB scan expansion. Missing overlap may still choose recent fallback rows; synonyms, paraphrases and arbitrarily old or out-of-window material are not guaranteed. Exact source labels are internal grounding, not instructions for ordinary spoken dialogue.
