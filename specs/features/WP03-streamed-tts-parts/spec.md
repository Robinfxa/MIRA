# WP03 streamed TTS non-audio parts

Block: providers. Consumers: Google speech adapter, media runtime. Base: Google handoff17:22 UTC; owned TTS adapter SHA84fb1cd9e8a4f06651dd8a24b447e0eea58f640df07091f961cc00faf469ac22. No provider calls, changed request, model, credentials, budget, factory admission or second playback owner.

### WP03STREAMEDTTSPARTS-001

Given a valid streamed response with a non-inline part followed by validated PCM, continue the bounded stream and yield only PCM. Non-audio text is never speech, subtitles or application dialogue. An exhausted stream with no PCM fails empty_audio and retains only bounded sanitized diagnostic facts.

### WP03STREAMEDTTSPARTS-002

Given malformed declared inlineData, audio after STOP, blocked/incomplete completion or cancellation, existing failure/closure rules remain. Skipping a non-audio part must not skip validation of declared audio or revive canceled output. No raw response text is retained unless the existing explicit synthetic diagnostic option is enabled.

Official basis: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/overview (checked2026-10-03): streaming examples iterate parts and emit only present inline audio. This documents a parser strategy, not proof that the observed interrupted text-only response would later have returned audio.
