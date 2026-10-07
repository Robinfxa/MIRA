# WP12CP: explicit known canon checkpoint compatibility

Base: frozen mira-luna-tools-final-20261006T0323Z plus the exact two authored
assets from mira-story-topics-next-20261006T0312Z. Only synthetic local stores,
no provider, credentials, settings, real database, or installation. Providers
lane owns tests/contracts/test_story_canon_upgrade.py and its schema-5 regression
companion through the same unique glob;
HTTP, bootstrap, and application are consumers. One SQLite transaction, 1 second
lock wait, at most 4096 archived episodes / 4 MiB per inspection. No full/release
claim; affected source checks required before handoff.

### WP12CP-001 Read-only, exact known source
Given a schema-5 or schema-6 canon-2 checkpoint with the pinned four-node graph/hash and
canon hash, dry-run validates the complete row and archive, reports counts and
a compare-and-swap digest, and changes no file. Other revisions, hashes, malformed
or inconsistent payloads fail closed. Ordinary load is still strict and exposes
a safe actionable known-upgrade error only after the checkpoint validates. The
explicit supported schema set is independent of the latest writer version. Old
schema 5 is decoded using only its known fields; the new chapter default exists
in memory, not as a read-time rewrite. Schema 3/4 ordinary read compatibility does
not authorize this canon migration; unknown schemas and corruption remain closed.

### WP12CP-002 Explicit atomic upgrade preserves evidence
Given the unchanged preview digest, explicit commit saves the complete original
checkpoint row in append-only history and rebinds only current state/affect to
canon 3, with a new story revision. Exact old episode bytes, receipt IDs, graph,
appearance, progress, and provenance remain. Pending grants and scene-specific
RAM consent are fenced, never credited as presented. The upgraded checkpoint can
load, resume, and save; duplicate receipts cannot create new evidence. A schema-5
source stays schema 5 with its exact field shape during this canon-only upgrade;
only a later accepted state revision saved normally writes schema 6. Exact same-
revision retries and inspections never silently change disk schema.

### WP12CP-003 Idempotence and reversal
An exact retry does not append another upgrade or change state. An explicitly
previewed rollback restores the original row only while both checkpoint and
archive still match the committed upgrade. It retains upgrade and rollback
history. Further progress, stale previews, foreign scope and corruption reject.
A restored upgrade cannot be applied again under the same one-shot migration ID.
