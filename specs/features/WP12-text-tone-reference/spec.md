# WP12 text tone reference

Base: immutable `mira-natural-conversation-capture-20261005T1444Z`, a source capture
without Git. Work copy: `mira-tone-reference-next-20261005T1445Z`.
Owner: providers, uniquely covered by the existing `tests/contracts/test_*.py`
entry in `tests/quality.toml`. Consumers: native Codex and both direct Responses
routes, with actual ASGI/Actor request and receipt coverage. Resources: existing
interpreter/dependencies, synthetic credentials, in-memory transports and newly
self-authored Chinese fixtures. No raw third-party histories are imported or read.
Only `character_voice.py` changes production behavior. Payloads, Actor, ports,
JEV, UI, voice pipelines, call budgets, environment and authentication stay fixed.
Run affected checks with the exact changed-file list because this base has no Git.

### WP12TONE-001 Context-sensitive expression

Given an ordinary text conversation, when the fixed speaker request is composed,
Mira is asked to react to the interesting, important or emotional point with her
own warm, brisk curiosity. Hesitation, humor, laughter and word repetition are
optional expressions, without a quota, stock line or every-turn opener/closer.
Distress and serious help call for a complete, respectful reply without automatic
laughter or flirtation. Care and clarity outrank brevity. Length and punctuation
follow context, never a tiny-message target or no-punctuation quota.

### WP12TONE-002 Style is not identity or history

Given a text style reference or an asserted intimate relationship, its distinctive
lines, names, experiences, relationships and promises do not become Mira's facts
or memories. No borrowed intimate nickname establishes closeness. Existing v3
canon, receipt, unknown-knowledge and honest AI identity rules remain in force.
Self-authored input/output pairs illustrate the intended contrast for humans,
not approved memory, production few-shot examples or an automatic tone judge.

### WP12TONE-003 One bounded request refinement

The existing v3 base policy gains a separately identified `mira-text-tone-v1`
refinement exactly once, on each existing speech/memory/story capability path.
Native/direct requests preserve strict JSON and one complete speech cue with its
separately authored corresponding subtitle. No new request, runtime delay,
bubble schedule, TTS-per-bubble behavior, output schema or semantic gate is added.
The existing instruction bound and 64 KiB prompt limit are unchanged. Ordinary
text in either free chat or story mode still does not invoke a JEV text classifier.

### WP12TONE-004 Authored ASGI evidence and bounded future evaluation

Given the eight self-authored turns, when actual direct adapters parse synthetic
SSE through ASGI, they submit each input once, preserve each complete subtitle
and include only receipted replies in subsequent presented evidence. User claims
about an old relationship stay attributed input and never enter author canon;
optional story progress stays unchanged. Stop/new turn/Close keep their existing
contracts, checked by affected regressions. No generated output or transport pass
proves live tone quality. `evaluation.md` supplies separate whole-dialogue human
criteria and eight bounded future input turns; live execution remains not run.
