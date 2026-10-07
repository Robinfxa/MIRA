# Natural conversation v2 backend candidate

Natural mode retains strict offset coverage as a fast path and adds explicitly
labeled VAD/stable-final grace as a practical heuristic. Grace is not proof that
no late words remain. Missing-offset/still-interim boundaries half-close only
requests, drain finals to clean EOF, and resume from the exact next PCM sample
only after the sealed snapshot is consumed. New RPCs reserve independently from
the existing shared STT counter; all total lease caps remain unchanged.

Backend limits are `natural_grace_seconds=0.65` (0.25–2.0),
`drain_timeout_seconds=2.0` (0.1–5.0), `max_recognition_streams=12` (1–32).
The integration owner is adding finite public CLI/factory pass-through. This
backend freeze alone does not claim that launcher validation passed. Ready/status
report the actual limits, stream ordinal and reservation snapshots, not billed
cost. Pending audio is limited to32,000 samples/64,000 bytes and an independent
200-packet count;200 packets do not inherently equal two seconds.

Withheld old activity text remains recoverable; a later unambiguous activity can
submit its own suffix independently. Correlated resets identify their commit and
utterance. Late corrections retain original identity; new-RPC orphan finals cannot
modify old utterances. Exact accepted/reserved commit replays remain idempotent.
Finite caps preserve observed previews, and explicit Stop/replacement/Close can
still fence an outstanding terminal writer after the cap. Queue overflow emits a
visible reason rather than failing on a missing exception attribute.

Tasks completed in this slice: implementation, exact generated wire exports,
WP03-012/013 mappings, actual RED/GREEN for held-suffix and commit-retry defects,
actual RED/GREEN for limit-then-Stop fencing, and121 focused tests across continuous
unit/HTTP, real Google SDK mapping, production budget wrappers, diagnostics and
startup buffers. Three production-SDK/local-ASGI scenarios cover heuristic held
speech→fresh suffix, two missing-offset drained turns with exact PCM/budget2,
and a quiet stream's immediate reservation visibility. Additional ASGI cases
cover both queue bounds and new-stream orphan-final isolation.

Append-only receipts are external in
`mira-continuous-natural-v2-evidence-20261005T1323Z`. Independent WIP resource checks
found and verified repairs for terminal retention, orphan attribution and queue
termination; final source-bound independent acceptance and merged release checks
remain integration-owner work. No real provider, credentials, user microphone,
physical playback or acoustic interruption was exercised here.
