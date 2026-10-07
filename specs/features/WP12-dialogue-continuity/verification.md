# Dialogue continuity: software evidence and limits

The frozen0221 Actor submits the complete accepted-input tuple and the actual
presentation-ledger projection. Its direct adapter serializes this evidence into
facts. Short synthetic conversations keep all rows: the bounded-context branch does
not run, and the second input's first-person story frame is ongoing_scene.

A private, local reconstruction of the reported eight-turn conversation was run on
both the frozen and patched implementations, for both direct routes with story on
and off. The previous reply and current short follow-up were retained in all cases.
These were mocked SSE outputs and synthesized subtitle receipts, not captured
requests from the user's device; they do not prove its exact runtime state. Private
source text and request captures remain outside the deliverable source tree.

Source-level contributors addressed here:

- The old greeting guidance instructed an introduction for every ordinary greeting
  and supplied an introduction example. It now decides from the ongoing exchange,
  without a copyable opening. Continuity guidance explicitly follows recent quoted
  inputs/replies and separates available image capabilities from topic choice.
- The first-person shortcut spent four reference slots on speech/subtitle rows,
  yielding two distinct texts when both modalities matched. It now selects four
  distinct same-turn texts, preserving the chosen row's identity and modality.
  The complete ledger remains unchanged; repeated text on separate turns remains
  separately referenced. Existing omission counts remain exact, without new wire
  fields, a semantic summary or proof of hearing.

No fixed fallback containing the reported repetitive sentence was found in the
source. The direct adapter returns parsed provider text without a canned corrective
replacement. This establishes a prompt/context repair candidate, not a proven
single cause or a demonstrated improvement in live model behavior.

Directed RED: 10 failures / 5 passes on the new 15 cases. Eight failures asserted
missing prompt-contract guidance; two exposed the reply-reference contract.
The four Actor/direct-transport cases already passed before the patch, which is
negative evidence for short-session history loss. An intermediate run had 14 passes
and a prompt-length-budget failure; its receipt is retained. After shortening the
redundant memory addendum, all 15 cases passed. Nearby voice/story/context regression:
90 passed. The initial affected run exposed six exact JEV wire-size regressions from
redundant new count fields and one unavailable Node-dependency build. The fields were
removed to retain the existing wire shape and the supplied existing dependencies were
attached, with no installation or budget/test relaxation. Final directed RED/GREEN
and affected results are retained separately. The added test file is uniquely owned by the existing
providers glob in tests/quality.toml; ownership configuration did not change.

The required affected plan selects architecture, config, actor, providers, HTTP,
tooling and specs from the recorded local base. Its final result is in the external,
source-fingerprinted quality receipt. No full/release, real provider, Mac, browser,
voice quality, alternate-image availability or photo presentation is claimed here.
