# WP12 ordinary scene dialogue

Base: immutable `mira-xiahe-chapter-final-20261006T0721Z`, copied from the
1,407-file public capture manifest. Owner: providers, uniquely registered by
`tests/contracts/test_*.py` in `tests/quality.toml`. Consumers: shared fixed
speaker instructions on native, direct Responses and direct-tool paths.
Resources: existing Python environment, synthetic HTTP/ASGI and in-memory Actor
state. No live model, authentication, private dialogue, new classifier or call.
The user's running build is unconfirmed; source findings are not a diagnosis of
which instructions that build sent. Changed-file affected checks apply to this
no-Git capture. Integration/release belongs to the director.

### WP12ORDINARY-001 Scene is the everyday conversational frame

Given ordinary location, reason, invitation, weather or clothing conversation,
respond in first person from the current approved scene without adding a reality
disclaimer or asking the user to choose role versus reality. Source labels remain
internal grounding metadata. Explicit AI/model/program, real-human, physical-world
presence/contact and source questions still receive brief truthful answers.
Meaning and context determine the distinction; generic intensifiers, question
prefixes and figurative speech never become a runtime keyword switch.

### WP12ORDINARY-002 Clothing follow-ups carry actionable intent

Given a presented suggestion of an available outfit and a current clear short
acceptance, resolve the referent from the actual dialogue. An immediate supported
change includes its authored pose in the same cue, subject to independent review
and exact readiness. An offer is not a completed change. Missing proposal,
unavailable resource, pending effect or missing receipt retains the earlier
acknowledged appearance. Indoor wet outerwear may be removed while retaining the
existing inner layer; no automatic raincoat substitution. Mention relevant details
once, without recurring palette/material narration. A final tool continuation
remains text-only. No invented clothing, walking, capture or displayed photograph.

### WP12ORDINARY-003 Preserve provenance, chapter and execution boundaries

The fixture suite uses self-authored analogues, not private dialogue. Actual
serialized requests preserve user input, attributed replies, selected canon,
internal provenance and receipt state without injecting expected responses into
runtime instructions. Ordinary replies use one request and no JEV text gate.
Chapter recognition/correction remains governed by the existing explicit role
claim and receipt contracts; no invented arriving third party. Supplied tools,
budgets, output schema, routes and source projections remain unchanged.

### WP12ORDINARY-004 Bounded offline evidence

RED/GREEN verifies the fixed prompt contract and its transport, not live semantic
quality. Synthetic good and bad dialogue are both parseable; tests do not claim
that prompt words force model compliance. An offline A/B request capture compares
the same synthetic cases before and after the patch. Later authorized live
evaluation must read whole exchanges for naturalness, truthful frame switching,
non-repetition, correct referents and receipt-grounded action claims; neither a
keyword tally nor a golden-sentence match proves success.
