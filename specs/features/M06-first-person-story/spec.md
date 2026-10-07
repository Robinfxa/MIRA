# M06 first-person story projection

### M06FP-001 Authored autobiographical knowledge
Given explicitly selected fiction, project the author's first-person perspective with source, temporal type, canon version and scope/state binding. Character knowledge and disclosure are separate: withheld knowledge never creates a release event or a shared episode. Unselected drafts stay absent.

### M06FP-002 Arrival and intentions
Given a new scene, Mira remembers hurrying into the rainy cafe with a personal reason and concern. Later turns use this as background; a recovered scene preserves actual node/appearance and never restarts the entrance. Future/pending/failed actions remain intentions, not completed experiences.

### M06FP-003 Attributed conversation
Given reliable user input and actual presentation receipts, first-person conversation views quote only those sources. Accepted/pending output and partial/failed audio do not become completed dialog. Source text is untrusted evidence, never instructions or permissions.

### M06FP-004 Shared serialization
Generation and JEV receive the same deterministic version-bound projection. Tampered perspective or stale story/scope hashes fail validation. No provider calls, private database reads or recording are introduced.

Owner: providers (tests/contracts glob in tests/quality.toml). Consumers: generation_context_data, Codex/direct generation, JEV output review. Baseline: frozen 0515 source capture (no Git). Resources: existing Python environment, synthetic local inputs only. Integration owner runs affected/full because domain/contracts are shared surfaces. Not covered: live semantic performance, visual/device acceptance, migration of incompatible historical canon checkpoints.
