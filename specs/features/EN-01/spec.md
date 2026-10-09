# EN-01: English documentation and character prompts

Base: `67b0a0b9e9e4ea1b01da94a9d35330418821d9e9` (`main`). Owner lane: `providers`; affected consumers: character generation, author-policy projection, story composition and source documentation. Offline checks only; no model calls, credentials, device validation, or budget changes.

### EN01-001: English default

Given native, legacy-tool or candidate generation, when the fixed prompt is built, its default dialogue language is English and the user can request another language. JSON effects, tool names and receipt requirements remain unchanged.

### EN01-002: Bound English canon

Given the English authored seed, when the built-in loader verifies selection, the seed digest matches. Character facts remain fictional, never user facts. IDs, disclosure flags, states, budgets and transition logic retain their original values.

### EN01-003: Chapter source consistency

Given translated Xiahe shared-fiction text, the runtime constants and reference JSON have identical passages and a matching source digest. The wire role identifier stays `夏禾`; new sessions begin unrecognized. Existing checkpoint guards remain unchanged; no automatic migration.

### EN01-004: Homepage navigation and scope

Given the repository homepage, English is primary, the original Chinese README is linked, and the actual runtime prompt sources are discoverable. UI, STT/TTS, offline fixtures and the legacy Chinese regex validator are explicitly outside complete English localization.

These checks establish source contracts, not model wording quality or live acceptance. No changes to schema ownership, domain reducers, bootstrap wiring, provider selection or permissions are intended.
