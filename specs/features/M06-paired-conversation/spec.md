# M06 paired conversation entry

Base: frozen conversation-archive-next-20261005T1633Z. Owners: providers (entry/storage contracts), http (paired lifecycle), web (paired UI). Consumers: direct CLI, bootstrap, Actor's existing conversation binding, schema exports. Only synthetic SQLite/ASGI/frontend tests; no external providers, user credentials, or real databases.

### M06PC-001 — Explicit local persistence
Given default startup, no transcript database is opened. When the operator explicitly chooses a dedicated private database, fixed scope and transcript persistence consent, the existing one-use local pairing must succeed before opening it. Check creates no database or pairing file. Manual/story consent never enables this path.

### M06PC-002 — Specific reentry and recipients
Given a paired local archive, the operator can inspect bounded source sessions and explicitly select one prior session before starting chat. Sending its bounded recall requires separate selected OpenAI route plus JEV consent. Voice additionally requires separate Google-derived-speech consent. No scope/path can come from HTTP/model text. Current Actor permissions, ledgers and microphone state are not restored.

### M06PC-003 — Truthful capture and local correction
Accepted inputs and software receipts reach durable local storage through the existing binding. The UI reports pending/saved/unavailable/revoked honestly; operational persistence failures do not block ordinary chat. Confirmed revision-bound input correction/soft-forget/restore uses the existing SQLite CAS and operation identifiers. Old versions remain available locally for reversible correction. Exact local source-version provenance suppresses derived receipt recall through A→B→C and later dependent receipts, while independent user inputs and raw receipt facts remain. Changes affect future archive eligibility, not in-process accepted input or already-sent provider data.

### M06PC-004 — Lifecycle and privacy
Unpaired, cross-origin, cross-scope and path-alias attempts fail. Revoke disables future capture and recall immediately; Stop does not claim an in-flight write was undone. Restart can recall only the explicitly selected same-scope prior session. Manual memory/story remain independent. All pages and requests are bounded; output/logs reveal no scope or storage path.
