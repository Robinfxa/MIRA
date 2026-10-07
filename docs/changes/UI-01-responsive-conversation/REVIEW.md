# Responsive character conversation review candidate

This is an isolated next-stage proposal based on immutable capture 20261005T0550Z. It is not merged, published, browser-pixel-approved or device-approved. The assigned shared path points to /tmp/mira-responsive-redesign-next-20261005 because the shared disk filled during the first copy. Neither the capture nor the director's current source was edited.

## What changed

- At 1280 px, a 724.5 px character stage sits beside a 467.5 px conversation panel. Existing artwork, renderer code, expressions and body geometry are identical. At 390 and 320 px the same components stack, with a fitted SVG fallback and stage heights of 366.6 / 320 px. These are CSS intent/arithmetic, not measured browser pixels.
- Text becomes a 16 px multiline composer with Enter to send, Shift+Enter for a newline, and IME composition protection. Drafts remain editable during connection failure and known-not-sent input restores only an unchanged empty field, preserving newer typing.
- A page-only log holds the latest 80 accepted user messages / actually presented reply messages. It uses textContent, never HTML. It does not write browser storage or add chat text to diagnostics. Stop preserves shown messages and the current draft. Readers who have scrolled up are not forced back to the bottom.
- Stop stays unique and near the status at the top of the conversation panel. Reply-only interruption and manual confirmed-transcript send retain their separate controller paths. Optional continuous listening still appears only after actual capability discovery and never starts automatically; caps and consent disclosures remain unchanged.
- Recording state and errors remain visible. Background choice, recording consent, local memory and technical information move into secondary native details. Existing consent controls are unchanged and default-off.

## Preview

Actual HTML: apps/web/index.html. Actual compiled entry: apps/web/dist/app/main.js. No alternate/demo frontend or fake provider-ready state was introduced.

From this checkout on the current cloud computer:

```sh
cd /tmp/mira-responsive-redesign-next-20261005
sh scripts/dev --python /workspace/shared/mira-combined-runtime-0947/.venv/bin/python --profile mock --character-renderer code-native-review --port 8766
```

Then open http://127.0.0.1:8766 in an authorized browser. This command builds using the existing local node_modules; it installs nothing and uses the explicit offline mock profile. Omit the renderer flag to review the existing static Pixi / SVG branch. The command is supplied for review; no browser route was used to bypass the earlier localhost/file denial.

## Verified on this exact source

- Strict TypeScript and esbuild compile passed. Four inherited code-native vendor CommonJS-in-ESM warnings remain; they are not new UI failures.
- Affected selection passed: 7 architecture checks and all 409 web tests, including 4 new actual-controller observer tests and 10 compiled-main/actual-HTML contract tests. No source changed during that run.
- Actual ASGI application returned HTTP 200 for the page, CSS, compiled main, character manifest and offline health in both renderer modes. Private .env access stayed 404. No provider or credential calls occurred.
- All 90 pre-existing data hooks remain, 22 IDs are unique, every scene asset and renderer source plus embedded character SVG matches the base byte-for-byte.
- Declared foreground/background contrast ratios: Stop 8.57:1; assistant bubbles 9.69:1; user bubbles 7.95:1; panel secondary text 7.67:1. This checks specified solid colors, not a rendered-page accessibility audit.

Evidence: docs/verification/ui-01-responsive/final-affected/summary.json, web.stdout.txt, architecture.junit.xml; 018-final-asgi-preview.json; 011-static-checks.json. The original four-test RED was 3 failed / 1 passed; the same tests passed after implementation. Initial full web run exposed three outdated DOM/native-input assertions; input test doubles were updated for textarea requestSubmit, recording order now checks secondary settings placement, and the system notice remains directly beside the composer. Final affected regression is green.

Not run: actual browser screenshots/pixel layout, phone Safari/Chrome, software keyboard viewport behavior, physical audio/microphone, genuine provider conversation, original full release/package/smoke lanes. Do not claim complete product, visual approval or device acceptance.

## Integration seam

SessionViewPort has two optional page-projection callbacks: inputAccepted(text, requestId) and visualPresented(effect). Accepted input is observed only after authoritative snapshot installation validates current activity/request. Visual output is observed only after actual successful apply, gate.consume and receipt enqueue. These observers do not grant permission or replace receipts. The semantic chunk owner has incorporated this exact seam before its FIFO implementation. Keep its combined controller during integration instead of overwriting it with this older observer-only controller. The main.ts history projection supports the frozen caption_chunk shape {group_id, index, start, end, total, source_sha256}. Only actually presented contiguous code-point ranges within the same activity/output/group/source append to one bubble, preserving whitespace. Effect IDs deduplicate callbacks. A new activity or a missing range stays separate and does not fabricate text. This UI projection has synthetic software coverage; the semantic owner’s full backend/FIFO delivery must be integrated and retested separately.

## Review on a real device when access is available

At 320 / 390 px: scroll from the character to conversation, enter long Chinese text, confirm IME Enter does not send, use Shift+Enter, focus with the software keyboard, scroll the log, and ensure Stop remains reachable. At 1280 px: compare scene dominance and text legibility, then test long replies, repeated sends, Stop, failure/retry and all native disclosures. Verify raw recording warnings remain visible when settings are closed. These are pending checks, not completed observations.
