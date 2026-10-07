# Natural conversation candidate

Click **开始自然对话** once to start microphone capture and prepare the existing reply playback sink. Speak normally; the interface shows listening, recognizing, sending and sent states. A completed candidate is automatically confirmed against the server's exact utterance identity and revision, then sent through the ordinary session input path.

The displayed time, send-count and recognition-attempt limits remain finite. Reaching a limit releases the microphone. Another capture lease requires a fresh click; loading the page never opens the microphone.

During MIRA's reply, **打断回应，继续听我说** stops the reply while keeping capture open. A later speech activity can become a new automatic turn. Text captured during software-owned playback is retained for review so it cannot turn into an automatic echo loop. This does not provide acoustic echo detection or automatic voice-based interruption during playback.

The manual-send button remains available for fallback. If endpoint evidence is unavailable, recognition changes a submitted utterance, or delivery is uncertain, the interface retains the text and explains what needs review. A correction stays linked to the original utterance and is never silently submitted as another turn. Retained previews can be copied into an empty composer without sending; existing drafts are never overwritten. Sending from the composer stops the continuous lease first.

## Endpoint behavior

- `offset_coverage`: a completed voice-activity interval and stable final offsets cover its end.
- `vad_final_grace`: closed voice activity plus stable final text and a configured short grace interval. This is a heuristic sentence boundary, not proof that the speaker will not continue.
- `client_silence_finalized`: an explicitly selected client quiet boundary has completed a bounded recognizer drain. It carries the exact endpoint ID and source interval, without requiring Google BEGIN/END or final offsets.
- `stream_finalized`: a bounded recognizer drain has completed. Missing final offsets are permitted only for this basis, with an exact bounded source interval.

All automatic candidates must carry a source interval within the audio already sent by this client. The browser’s configured local quiet timer may request a bounded recognition drain after local speech. It cannot create an input from punctuation, an interim, or a timer alone. The stable finalized snapshot still requires the existing exact commit and normal input binding. Status messages report bounded recognition continuation and current shared request-count snapshots. A provider continuation does not reopen microphone permission or create an unlimited session.

Selected client endpointing starts with `mode: natural, client_endpointing: true`; provider END/grace cannot precede the local quiet trigger. Default local quiet is700ms (configurable250–2000ms), a timing heuristic rather than a promise that someone has finished speaking. Queued endpoints can be cancelled when speech resumes. A half-close already in progress cannot be reversed; its exact result is retained with a hold when necessary. Empty/no-final recognition or a deadline failure stops visibly and keeps any observed preview recoverable.

When a finalized recognizer candidate is withheld for playback overlap, the browser acknowledges an exact token/revision `hold`. The server keeps that text, creates no conversation input, and releases the next bounded recognition attempt only after the acknowledgement is sent. Duplicate holds are idempotent; an unconfirmed or conflicting hold stops capture and leaves the preview recoverable.

The original text and later corrections are separate records. When earlier text was withheld during playback, a newer activity can submit only its own suffix; the earlier text remains available for manual review. The server's post-commit reset is accepted as such only when its commit ID, utterance ID and exact revision match the submitted candidate.

## Verification boundary

The shipping TypeScript, parsed WebSocket frames, synthetic DOM, session input and injected playback ownership are exercised offline. These checks do not establish real Google timing, browser-specific audio activation, microphone accuracy, physical speaker behavior, mobile behavior or end-to-end conversational quality. Actual-device acceptance remains outstanding.
