# UI-01: responsive character conversation

Baseline: immutable 20261005T0550Z capture, 1091 files, manifest db92e3ad87fea84c737f02efc89421785d3851c8a8a13040fed249d3e8551fc8.
Owner: web lane (existing tests/quality.toml tests/web/*.test.mjs rule). Consumers: compiled main, SessionController view observer, SceneEffectExecutor unchanged, existing consent/voice controllers. No schema, provider, renderer artwork or storage changes.

- Given a 1280 px viewport, the existing character stage remains the dominant first column and conversation is readable beside it. Given 390 or 320 px, stage precedes chat in one column; controls wrap without horizontal overflow. No fixed-height page or keyboard-trapping overlay.
- Given confirmed current input, show the user text. Given an actually applied and consumed subtitle, show the assistant text. Pending drafts, unapproved grants and stale completions never become chat facts. Stop and new input preserve shown messages. Retain at most 80 page-only messages; disclose evicted history. Do not persist text or add diagnostics containing it.
- Given IME composition or Shift+Enter, do not send. Enter submits an eligible textarea through the existing composer. Failed known-not-sent sends restore only an unchanged empty draft; newer drafts remain untouched.
- Given connecting/failed/closed state, writing a draft remains possible and sending is disabled. Existing system notices and error text stay visibly near the composer. Stop remains unique, usable before connection, high-contrast, and separate from reply-only interruption and manual transcript send.
- Given optional voice capabilities, only real capability events reveal continuous listening. No automatic microphone start. Finite caps, manual send semantics, consent and raw-audio privacy controls remain accurate.
- Secondary background, privacy and diagnostic panels use native keyboard-operable disclosures. Recording state remains visible outside settings. Text inputs use 16 px or greater on phones and all primary controls have at least 44 px targets.

Verification: actual compiled main executed against a DOM contract parsed from the shipping HTML; real controller lifecycle observer tests; existing web regression; affected architecture/web lanes and offline ASGI page/resource checks. Pixel/GPU/browser/device/audio checks are not run because browser access was denied. No alternate browser route.
