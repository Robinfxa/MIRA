# WP12 clothing dialogue refinement

Base: immutable `mira-live-regression-final-20261006T0542Z`, copied using its
1,374-file public capture whitelist. Owner: providers, already uniquely covered
by `tests/contracts/test_*.py` in `tests/quality.toml`; no test-policy edit needed.
Consumers: the fixed voice instructions shared by native, direct and direct-tool
generation. Resources: existing Python environment, synthetic HTTP transports,
in-memory Actor state and self-authored Chinese scenarios. Evidence and temporary
files remain outside the source. Use the exact changed-file list for affected
checks because this capture has no Git.

### WP12CLOTH-001 Relevant clothing language

Given ordinary conversation, wardrobe asset labels, palette and material metadata
inform the authored appearance but are not recurring dialogue. When clothing is
the user's topic, answer briefly with supported details; when it is not, continue
the topic without narrating an inventory. Source questions and AI identity remain
truthful. No new biography, relationship, body art, wardrobe or visual capability.

### WP12CLOTH-002 Contextual intent and existing control

Given an indoor scene and a wet outer layer, consider removing the outer layer
while retaining the existing inner layer. This is semantic guidance, never a
keyword-triggered action or an automatic raincoat substitution. Current preference,
weather and intended activity may instead make the existing raincoat appropriate.
When choosing an immediate change, propose the corresponding currently available
authored pose in the same cue with intended wording. No textual promise or future
intention substitutes for that proposal. Independent review, readiness and exact
receipts still govern every effect; tool continuations remain text-only.

### WP12CLOTH-003 Receipt-grounded appearance and bounded verification

Given pending, unavailable or unreceipted wardrobe work, no dialogue or accepted
prefix upgrades it to completed appearance. Last acknowledged appearance remains
historical software evidence, not automatic browser restoration. Six self-authored
scenarios exercise indoor wet clothing, explicit raincoat choice, removal, an outfit
question, pending/unavailable receipt state, and a digression. Actual direct-tool
request serialization and Actor receipts establish wiring and evidence boundaries;
injected prose does not establish live naturalness or model compliance. Future
human evaluation should judge the complete exchange against these three rules,
including whether controls are actually proposed and shown, rather than score
isolated words. No provider call or live model evaluation is authorized or run.
