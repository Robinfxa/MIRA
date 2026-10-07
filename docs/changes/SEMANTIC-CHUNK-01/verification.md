# Semantic chunking verification

All provider, speech and user text in these runs is synthetic. No real provider,
authentication, device speech or browser-pixel acceptance is claimed.

- 001-red-prefix: new decorator behavior absent, 3 failed/2 passed; genuine test-first
  RED on the pass-through scaffold.
- 002-red-fifo-on-prior-build: final Node regression tests against the preserved
  pre-FIFO responsive build, 14 failed/3 passed. This is comparative old-build evidence,
  not a claim that every Node test was written before implementation.
- 003-green-fifo: same 17 Node regressions passed against the new compiled consumer.
- 004-green-core: 43 then-current core/wire tests passed.
- 005-red-speech-permission-timeout: real Actor reproduced lost tail with speech in
  first split range; this approach was not shipped.
- 006/007: English single-quote boundary bug reproduced and fixed, same test RED/GREEN.
- 008-green-text-only-safe-scope: 45 tests passed after excluding speech-bearing cues,
  including the exact timeout regression that previously lost text.
- 009/010: direct factory/CLI wiring RED then 50 checks passed with launcher/usage
  regressions included. Final new-suite total is 65 tests after adding actual two-turn
  budget-exhaustion and voice fallback checks.

The first affected run used an artifact directory inside the checkout and triggered
existing private-store path guards; it also caught a real legacy wire regression from
caption_chunk:null. The latter was fixed with explicit absent-metadata projections,
verified by 255 corpus/evaluator/core checks. A subsequent external-artifact affected
run passed all 11 selected lanes with no source drift at:
`/tmp/mira-semantic-chunking-affected-0625/summary.json`.

That intermediate pass predates final voice-scope, CLI and abort-helper integration.
The final source-stable affected run is recorded separately and is the handoff basis.
Package/smoke and live/device/real semantic-quality qualification are not selected.

Python ownership is the existing providers wildcard in tests/quality.toml; Node
ownership is its web wildcard. All six requirement headings have collectable pytest
links. The detailed FIFO behavior is exercised by the 17 named tests in
`tests/web/controller-semantic-chunks.test.mjs`; no Node title is misrepresented as a
pytest node or a physical reading/hearing claim.
