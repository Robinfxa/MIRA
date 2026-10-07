# Tool-result explanation follow-up

2026-10-06 16:39 UTC. Incremental change after prompt-refinement-final.patch.
Earlier final patch, capture metrics and verification records remain unchanged.

The existing Clothing dialogue section already says not to recite wardrobe labels,
colors or materials, to mention a relevant detail once, and to use the current
action contract for the requested change. Exact inner-layer target selection
belongs to the tool contract; this patch adds no clothing phrase templates.

A remaining gap was causal explanation after failure: the prior prompt forbade
false success but did not explicitly rule out treating fictional provenance as
a cause of a tool error. The shared voice now says to explain failure only from
the actual tool result, to acknowledge non-completion without guessing when the
cause is missing, and that fictional provenance alone is not a failure cause.
Explicit user questions about AI or asset provenance still get truthful answers.

Only character_voice.py, its existing request-contract test and this note change.
The test checks both provider routes and native/legacy initial and continuation
requests, including unavailable as well as shown/pending/failed results. It checks
exact output preservation and the fixed author rule; injected replies are not a
real-model semantic assessment. All 16 author capability combinations keep the
original 12,000-byte limit. No real conversation was sent to an external model.

RED: 40 failed / 4 passed from the missing new instruction.
Final focused rerun: 337 passed across the same13 relevant modules.
Evidence: evidence/result-reason-red.txt and evidence/result-reason-green.txt.
No broad aggregate rerun; final combined source validation belongs to integration.
