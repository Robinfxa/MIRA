# Isolate speech failure from independently issued text

Base: /tmp/mira-firstperson-integration-20261005T0613Z source-specific snapshot, 2026-10-05 06:48 UTC.
Owners: domain (existing test_audio_transitions.py), web (new controller-speech-failure.test.mjs covered by tests/web/*.test.mjs), actor/http consumers. No provider calls, network, or dependencies added. Shared transition/controller files are handed to the integration owner as a patch.

Given an active independently authored subtitle cue and speech, when TTS or current playback fails before or after PCM, then preserve only the already-issued independent subtitle IDs/digests/epochs, retain exact receipts, stop speech and dependent actions, seal pending generation, and retain the visible diagnostic. Changed grant authority advances permit_revision. No text receipt or completed speech is invented. Legacy speech-dependent cues still fail closed.

Given Stop, new input, close, or a newer permit, when a late failure/preparation callback arrives, then it cannot restore old text or speech. Given a prepared independent subtitle, current audio failure does not abort its preparation. Following typed input can use the actual saved history.

Directed RED/GREEN evidence is saved under evidence/. Independent ASGI audit is run separately by the voice QA owner. Full affected/release checks belong to integration; this patch does not claim real device/audio acceptance.
