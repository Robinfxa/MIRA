# Literal conversational text repair — 2026-10-05

Ordinary reply strings such as `<3`, `2 < 3`, backtick examples, URLs and `A / B`
previously failed the entire generated candidate as `codex_effects_unsupported`.
The parser now treats speech/subtitle as literal data and retains its existing
forbidden C0/DEL check. The fixed author instruction permits the same inert text.
Actions still use exact typed effects; this does not add HTML, automatic links,
URL fetching, path access, command execution or an effect kind.

## Scope and tasks

- Copied and verified only the 1,222 paths/modes in the frozen 18:58 source inventory
  into the isolated 19:26 next-stage tree. The baseline/release files remain unchanged.
- Added CHAT01-004/005 before implementation and updated the superseded lexical
  restriction in WP01CX-004. Existing provider/web test ownership applies.
- Added parser, native transport and actual direct-ASGI cases, including story on/off,
  both direct routes, speech enabled/disabled, held optional actions, strict JSON,
  structured authority fields, cue cardinality and size/control-character boundaries.
- Extended the compiled scene-executor test to assert literal textContent and reject
  any HTML setter, with no scene/action/photo change.
- Changed only the shared parser's text character filter and corresponding author
  wording in production code. Public schemas, JEV, authority, readiness, receipts,
  Stop, TTS and frontend implementation are unchanged.

## Recorded directed evidence

The unique evidence root is `mira-plain-chat-evidence-20261005T1926Z`, a sibling of
the next-stage source directory. Raw logs and test artifacts are not in this checkout.

The same `tests/contracts/test_plain_chat_literals.py` ran with the existing runtime:

- `001-red`: exit 1; 44 failed, 19 passed. Failures are the lexical text rejection and
  old prompt rule, not test collection or missing dependencies.
- `002-green`: exit 0; all 63 passed after the parser/prompt edit.
- Both receipts contain full before/after source fingerprints and unchanged test
  file hashes. Source did not change during either run.

The expanded existing scene test is a safety regression, not a newly claimed RED.
The prompt's existing 12,000-byte maximum is tested for all speech/memory/story
combinations; no limit is raised.

## Handoff and remaining verification

`changed-source-manifest.json`, `source-inventory.json`, `change.patch` and
`affected/summary.json` in the external evidence root bind the exact final source
and affected run. Read the generated summary for actual final status/counts rather
than inheriting any earlier green result. The affected invocation uses explicit
changed files because the isolated inventory copy has no Git metadata.

Required affected lanes are architecture, config, actor, providers, HTTP, tooling,
specs and web. Domain, env, continuous, package and smoke are unselected for this
narrow handoff; complete release checks belong to integration. No install, network,
real provider, credential access, user data, browser pixel or device audio test ran.
Synthetic authored outputs establish parser/transport behavior, not future model
reply quality or actual listening. Existing device and complete-product acceptance
gaps remain open.
