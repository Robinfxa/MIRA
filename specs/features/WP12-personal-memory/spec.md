# WP12PERSONAL — source-backed personal continuity

## Scope and ownership
Base: bd4d8aecba2f0f07fea9484a8fb3a872f15de852 (verified frozen 0221 plus six frozen dialogue-continuity files). Own character_memory.py, character_voice.py and the narrow first_person_dialogue call plus two unavailable-packet projection guards in contracts.py. No bootstrap, domain, schema, database, consent or tool mutation. The dialogue projection is the common consumer path for Luna generation and output JEV; input JEV already removes this optional perspective field.

Test owner: existing tests/quality.toml providers lane contracts glob. Consumers: generation, output review, input review exclusion, bounded conversation projection. Resources: existing Python, synthetic SQLite temporary files only when existing affected tests require them, no installs or provider calls. Evidence lives outside the source tree. contracts.py is a shared full-pattern, so affected validation must expand accordingly; full/release publication remains the integration owner's work.

### WP12PERSONAL-001 — An authored self with stable tastes
Given validated selected character canon, when projecting an in-scene conversation, identify enduring authored_trait entries by stable IDs resolving in the same approved_canon, not copied prose or newly inferred biography. Preserve canon version binding. An ordinary disagreement, one-off opinion or user claim cannot rewrite these preferences. Only supplied author fiction supports autobiographical first-person narration. Unselected, future or unrelated people’s content never becomes shared history.

### WP12PERSONAL-002 — Recall is an actual supplied source
Given default/no packet, failed recall, an attached empty result, or an attached bounded result, expose those distinctions without equating no packet to a disabled store or empty database. A completed query with no rows says nothing about all stored history. An unavailable status suppresses any leftover packet at the common canonical fact layer, so neither direct generation nor JEV receives it. Normal Actor read failures already clear the packet and preserve chat; this also guards direct consumers with contradictory contexts. Recalled inputs remain statements; receipts remain software presentation. No prompt can promise saving or perfect permanent recall. Current corrections and source revisions outrank stale memories.

### WP12PERSONAL-003 — One fact projection for both consumers
Given the same GenerationContext, generation and output JEV receive identical self-continuity and recall metadata. Input JEV does not receive this extra private evidence view. Source references survive bounded history projection; no private scope/path/session identifiers enter the new metadata. Default wire without story still receives no invented fictional self view.

### WP12PERSONAL-004 — Natural voice without repeated exposition
Use stable tastes and relevant autobiographical details to shape a reaction and a possible next topic; do not mechanically recite them or repeat an already presented anecdote. React as a continuing character with a point of view. Explicit real identity questions stay truthful. Keep inherited continuity and <12,000 UTF-8 instruction budget across all story/memory/speech combinations. Tests verify software contracts, not live persona quality.

## Sources and implementation decision
Research checked 2026-10-06. See research.md for current official MaiBot sources, concrete release/PR provenance, firsthand community practices, and intentionally rejected auto-write/privacy defaults. This slice improves the existing memory consumption path; it does not implement automatic extraction, summarization, semantic recall, or a second memory platform.
