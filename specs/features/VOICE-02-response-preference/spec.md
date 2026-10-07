# VOICE-02: App-owned response modality

Base: immutable mira-silence-conversation-capture-20261005T1551Z. Owner: speech preference slice.
Consumers: SessionActor, HTTP SessionView, controller/single playback sink, direct subscription/API generation.
Resources: existing offline Python/Node dependencies only; no provider calls, credentials or user databases.
Tests: providers (contract glob) and web (web glob); affected expands for the owned domain/schema fields.

### VOICE02-001: Ordinary voice is independent of event review
Given authorized/configured speech and voice response mode, when optional JEV hangs, rejects or is unknown, text and speech are available before it. Optional controls still await their own existing review.

### VOICE02-002: Typed user preference survives turns
Given a reliable explicit mute command or visible mute control, when the next unrelated turn arrives, it stays text-only until an explicit unmute. A current-turn-only command expires on the next turn. Quotes, negation, model output, uncertain text and voice capability do not unmute.

### VOICE02-003: Local mute is prompt and irreversible for old audio
Given current playback or delayed PCM, when output mute is pressed, local playback stops before network completion, old audio cannot resume, text and microphone continue. The server revokes only output speech; unmute applies to a future input. Stop/close/new-turn and memory/privacy authority remain stronger.

### VOICE02-004: One strict generation request
Given text-only effective mode, both direct provider routes receive text-only instructions/capabilities and strict parsing. No extra generation or API fallback occurs. Application filtering enforces preference even for a malformed or untrusted proposal; existing schema validation still runs first.
