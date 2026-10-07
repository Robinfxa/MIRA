# PTT bounded startup audio buffering

Base: immutable conversation-first 0550 source snapshot. Application media owner
surface is changed only in this worker copy; the integration owner merges it.
The existing providers test glob owns new contract tests. HTTP/media, Stop, and
the Google STT adapter are consumers; public protocol and SDK security are unchanged.
Tests use synthetic PCM and fake transports. No credentials or provider calls.

### PTTSTARTUPBUFFER-001 Bound queued audio by duration as well as packet count

Given real-time 20ms PCM frames and a recognizer whose first request waits one
second, when the recognizer starts draining, then all accepted frames reach it in
order without a local limit failure or silent loss. The queue has both a two-second
PCM bound and a finite packet bound; an indefinitely slow consumer still fails.

### PTTSTARTUPBUFFER-002 Retain cancellation, pacing, and lifetime limits

Given queue capacity exhaustion, Finish, or Cancel, when the stream terminates,
then Finish drains every accepted frame and Cancel clears immediately. Neither
waits for buffer capacity. Consumption releases buffer capacity; pacing, contiguous
sequence, bounded packets, and the sixty-second input ceiling remain enforced.

Local synthetic behavior does not establish the exact cause of a metadata-only
user failure or claim Google, physical microphone, or playback acceptance.
