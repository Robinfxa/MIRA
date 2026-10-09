# MIRA character prompts · English edition

[Project home](../../README.md) · [简体中文项目说明](../../README.zh-CN.md)

This branch defaults to English character dialogue and provides English authored character material. The runtime reads the source files linked below; this page is a navigation guide, not a second prompt that can drift out of sync.

## Start here

- [Character voice and tone](../../apps/api/src/mira/adapters/generation/codex_support/character_voice.py): first-person voice, personality, conversational continuity, clothing dialogue, truthful AI identity, and strict dialogue/output boundaries.
- [Default native-tool instructions](../../apps/api/src/mira/adapters/generation/direct_tools.py): `_TOOL_INSTRUCTIONS` selects English by default and defines tool use, one-operation turns, receipt-backed actions, role recognition, photo sharing, and failure wording. `_LEGACY_TOOL_INSTRUCTIONS` covers the optional legacy tool route.
- [Candidate-generation prompt](../../apps/api/src/mira/adapters/generation/codex_support/payload.py): `AUTHOR_INSTRUCTIONS` and the input/output contract for candidate effects, including the optional legacy path.
- [Character proposal contract](../../apps/api/src/mira/adapters/generation/codex_support/character_payload.py): finite story proposals and affect suggestions; proposals are never permission to act.

## Character, canon, and scene

- [Authoritative character facts](../../apps/api/src/mira/application/decision_contracts.py): `mira26_author_policy` and `character_author_policy` supply the same facts to generation and review.
- [Authored story seed](../../apps/api/src/mira/adapters/story/assets/mira.story-seed.v1.json): Mira's biography, tastes, first-person authored memories, disclosure boundaries, scene material, and editorial examples.
- [Canon selection](../../apps/api/src/mira/adapters/story/assets/canon-selection.v1.json): explicitly selected entries and the exact seed digest checked at startup.
- [Rain-scene graph](../../apps/api/src/mira/adapters/story/assets/story-graph.json): optional invitations, guards, examples, and receipt requirements.
- [Xiahe chapter source](../../apps/api/src/mira/domain/xiahe_chapter.py): `CHAPTER_CANON` is the runtime source of the four shared fictional recollections. [Chapter reference](../../apps/api/src/mira/adapters/story/assets/xiahe-chapter.v1.json) mirrors them and their source hash.
- [Runtime composition](../../apps/api/src/mira/bootstrap/character_story.py): loads the packaged assets and validates the selected canon's digest.

Xiahe is a fictional role the visitor chooses, never real-world identity verification. For protocol compatibility, the internal `role_name` token remains `夏禾`; English dialogue calls the character Xiahe. Do not translate this wire token or tool/enum identifiers. The default `luna_tools` route uses model-typed intent. The optional legacy validator still recognizes its existing Chinese statement patterns; this branch does not rewrite that validator or claim full English legacy-story support.

## What this edition changes

English is the default response language; the user may request another language. The English material preserves Mira's age, personality, authored history, current-scene perspective, disclosure boundaries, and finite plot. Ordinary scene dialogue stays in character; direct questions about AI identity, real-world presence, or image provenance still receive truthful answers.

Tool names, JSON keys, output schema, consent checks, budgets, Stop/cancellation, scene transitions, and actual-presentation receipts retain their original meaning. A spoken claim is not an action receipt. Translation does not authorize any provider call, image request, data transmission, or paid usage.

This is an English documentation-and-character-prompt edition, not complete product localization. UI labels, offline rehearsal fixtures, speech-recognition language, TTS voice settings, and historical development/verification documents may remain Chinese or retain their original language. Choose and validate suitable STT/TTS settings separately; no voice/model/account defaults or quotas are changed by translation. The seed's legacy `target_spoken_chinese_characters` field is preserved as editorial metadata, not reinterpreted as an English word limit.

Translated authored text has new content digests. Use a fresh ephemeral `--story` session for this edition; existing persistent Chinese story checkpoints are not silently migrated or overwritten. The checkpoint compatibility guards remain in place.

## Verification

See [English-edition verification](../changes/EN-01/verification.md) for the exact checks run and remaining limits. Static and offline checks do not establish English model quality, speech quality, browser/device behavior, or complete product acceptance. No live provider calls are part of this translation work.
