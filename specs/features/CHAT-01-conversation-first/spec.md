# CHAT-01 Conversation first, optional reviewed events

Base: immutable mira-conversation-capture-20261005T0515Z. Owner: providers;
consumers: Actor, direct provider bootstrap, character receipt reducer, HTTP/controller.
Resources: existing Python environment and injected synthetic transports only. No
provider calls, credentials, installs, new public schemas or additional state owner.

### CHAT01-001 Immediate bounded text
Given a schema-valid direct-provider complete cue, when generation completes, then
independently compiled subtitle grants are available before any JEV wait. This is a
deterministic complete-cue boundary fallback, not streaming JEV segmentation or a
guarantee of semantic text truth. Provider refusals and schema errors stay failures.

### CHAT01-002 Optional events
Given explicit pose/scene/story/affect proposals, JEV reviews only these events.
No o1–o6 or text relevance grades gate chat. UNKNOWN, REJECT, invalid response,
transport failures or stale observations hold events while text remains available.
Only permitted authored controls can be granted. Explicit app-owned text-only modality
keeps text and does not issue speech (VOICE-02). JEV no longer grants ordinary voice. No seal-time whole-response review is made.

### CHAT01-003 Authority and actual history
Stop, new input, permission revocation and context-version changes invalidate old
pending work. Only issued effects plus validated presentation receipts establish
actual scene/character/history for next-turn generation and JEV. Pending suggestions
are not completed episodes. Existing legacy native/mock review routes are unchanged.

Verification: tests/contracts/test_conversation_first.py (providers glob owner).
Real-provider quality, actual device voice, browser pixels and true JEV streaming
segmentation are not covered by this offline slice.

### CHAT01-004 Literal text is not an action
Given bounded, strict effects JSON, subtitle and speech values are literal data. Angle
brackets, emoticons, comparisons, slashes, URLs, paths, backticks, code/markup examples
and quoted effect JSON must survive unchanged. Native and direct generation, story
on/off and enabled speech share this rule. Author instructions permit these literals;
the existing maximum instruction-size test remains below 12,000 UTF-8 bytes.
Subtitles use textContent, never HTML or automatic links; TTS receives plain text.
Text does not execute code, fetch a URL, open a path or create another effect.

### CHAT01-005 Preserve structured boundaries
Given unknown effects, arbitrary pose/scene/media values, authority fields, invalid
story proposals, duplicate JSON keys, code-fenced outer JSON or out-of-bounds data,
generation still fails before yielding a candidate. The existing forbidden C0/DEL
characters (including CR), character/output-byte/effect limits, speech capability
and complete speech/subtitle cue rules remain unchanged. Optional controls still need
readiness, review and current authority; literal text alone establishes no presentation
receipt. Existing Stop and actual-history rules in CHAT01-003 remain in force.

2026-10-05 literal-text repair baseline: immutable
`mira-conversation-action-capture-20261005T1858Z`, exact 1,222-file source inventory.
Owner: providers via the existing `tests/contracts/test_*.py` registration; web sink
checks use the existing web owner. Consumers: native/direct generation, story parsing,
Actor/HTTP and subtitle presentation. Resources: existing Python/Node dependencies,
synthetic transports and disposable local test data only; no provider or device run.
Affected integration includes architecture, providers, config, actor, HTTP, specs,
tooling and web; unselected lanes and real-device acceptance are not claimed.
