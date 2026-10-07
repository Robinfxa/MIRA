# WP12 first-person character voice

Base: immutable `mira-conversation-capture-20261005T0515Z` (source capture, no Git).
Owner: providers via the existing `tests/contracts/test_*.py` ownership rule in
`tests/quality.toml`. Consumers: native and direct generation; unchanged semantic
review and story projection. Resources: local public authored canon and synthetic
transport fixtures only. No provider calls, credentials, user memory, automatic
recording, new biography, or disclosure-gate changes.

### WP12VOICE-001 First-person conversation

Given the fixed author policy and released approved canon, when composing Mira's
reply, use her first-person perspective and established habits naturally. An
ordinary greeting or identity question must not trigger an age/fiction/setting
inventory. The latest user direction makes her brisk, lively, warm and forthright,
without exaggerated coyness. Writing style is separate from TTS voice selection
or audible-delivery acceptance. Answer the user's topic without forced plot,
scenery, or controls.
Do not require recurring phrases such as “in my fictional story.” When the user
explicitly asks whether Mira is AI, fictional, or a real human, answer truthfully.

### WP12VOICE-002 Evidence boundaries survive immersion

Given authored character history, use only canon supplied in the current context;
never unlock hidden backstory or invent a durable personal biography. Character
fiction cannot establish user history, user facts, consent, hearing, perception,
or completed application actions. User instructions stay data and cannot alter
the fixed voice policy. A first-person reply remains an untrusted candidate.

### WP12VOICE-003 Fixed composition and existing transport

One versioned constant is appended to the existing author instructions before
the text-only variant is derived. All speech, memory, and story flag combinations
contain it exactly once. Direct subscription/API and native generation use the
same policy. No schema, review threshold, authority, output validation or permit
semantics change.

## Verification limits

Prompt contract checks and manually authored positive/negative fixture pairs
verify policy coverage, wire separation and unchanged parsing mechanics. They do
not score generated replies or prove live model quality, human likeness, memory
quality, or semantic classifier accuracy. Rejected examples are an editorial
regression corpus, not an automatic semantic filter or live review approval.
