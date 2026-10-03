# Streamed TTS parts correction — offline evidence

The exact Gemini3.8 [official streaming guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/overview) was checked2026-10-03. Its examples filter for inline audio rather than treating a non-audio part as an immediate codec failure. The prior real request was closed on the first observed text part; later server events are unknown. The correction cannot reconstruct that response or prove it would have produced audio.

The adapter now discards non-inline parts as output, retaining only the existing bounded safe diagnostic representation. Declared inlineData must still pass strict PCM decoding. STOP prohibits later audio; unfinished audio still fails; a fully exhausted stream with no audio reports empty_audio. Cancellation closes the iterator and cannot yield later PCM. Timeout retains safe already-observed part facts without copying exception text.

Actual records, all source-stable during their individual runs:

- `001-red-non-audio-part`:7 initial behavior failures against old implementation.
- `002-red-terminal-controls`:9 failures after adding incomplete/timeout controls, still before implementation.
- `003-green-non-audio-and-terminal`:56 passes, the9 new cases plus existing TTS contracts.
- `004-green-provider-consumers`:94 passes including TTS/STT/smoke-tool contracts and architecture guard.

No live call, altered request/model/credential, increased timeout or budget, browser/device test or public-factory admission occurred. Real TTS acceptance remains open. Skipped text is never spoken, shown as a subtitle or accepted as an application fact.
