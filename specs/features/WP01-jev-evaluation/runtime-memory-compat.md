# Frozen JEV corpus and memory-aware runtime compatibility

The v2 JEV corpus release remains the historical no-memory artifact. Its corpus JSON,
preregistration, adjudication, release manifest, and original test bytes are preserved
under `archive-v2` where needed for verification. The current evaluator test adapter
uses the application-owned canonical DTO projections so an absent optional memory field
continues to match the old wire shape. Its integrity check resolves only the manifest's
self-referenced historical test path to the archived original; all other manifest hashes
are still checked against the current tree.

The legacy corpus codec accepts only the pre-memory context key set. It rejects
`memory_packet`, `memory_evidence`, and unknown or forged context fields. The frozen
corpus does not exercise, import, or authorize memory. No old manifest, preregistration,
fixture, adjudication, source golden, or budget ledger was rewritten.
