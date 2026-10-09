# EN-01 English edition: verification

Base: `67b0a0b9e9e4ea1b01da94a9d35330418821d9e9` (`main`). Work date: 2026-10-09. Independent English branch only; no merge, deployment or change to the default branch.

## Changes

- English-primary `README.md`; original Chinese preserved in `README.zh-CN.md`, with language links and a prominent [runtime prompt guide](../../prompts/README.md).
- English defaults for native-tool, legacy-tool and candidate-generation prompts, and English examples/voice guidance.
- English character facts, story-seed prose, rain-graph prose and the four runtime Xiahe memories; all wire identifiers, schemas, enum values, guards and state-machine behavior preserved.
- Updated exact seed/chapter hashes and the deliberately reviewed English `canon.waiting` binding. The latter guard still rejects changed canon, suspended state and active roles.
- Six focused English-edition tests, with the existing `providers` ownership glob in `tests/quality.toml`. Three first-person-memory assertions now check the equivalent English phrases; their fact, provenance, temporal and receipt assertions are unchanged.

## Offline checks

Final focused result: **215 passed** across 11 test modules (Python 3.12, pytest 8.4.2, pytest-asyncio 1.2.0). These are offline source/contract and synthetic runtime tests, not model-quality or device acceptance.

```sh
python -m pytest tests/contracts/test_english_prompts.py tests/contracts/test_xiahe_chapter.py tests/contracts/test_character_candidate_payload.py tests/contracts/test_character_first_person_voice.py tests/contracts/test_character_prompt_refinement.py tests/contracts/test_role_canon_speaker.py tests/contracts/test_native_character_tools.py tests/contracts/test_first_person_story_memory.py tests/contracts/test_story_context_composition.py tests/contracts/test_xiahe_chapter_actor.py tests/contracts/test_story_runtime_core.py -q
```

Test-only dependencies were installed in an isolated temporary directory and exposed through PYTHONPATH; repository dependency locks were not changed.

Additional checks completed:

- All nine README shell-command blocks are unchanged; every original Markdown link remains in the English README. Chinese backup preserves the original body.
- Non-string Python AST is identical across the seven translated runtime modules: no executable control-flow or schema changes. The only non-prose string change in the domain is the reviewed exact waiting-canon digest.
- JSON keys, collection shapes, identifiers, enums, booleans and numeric values are preserved; intended exceptions are `language=en` and content hashes.
- Seed selection hash is verified against final seed bytes. Chapter reference matches all runtime canon rows and its computed hash.
- All authored canon fits existing limits. Shared chapter passages stay below the 500-character bound. No application limit was raised.
- Four EN-01 requirements map to six collected tests. New tests are covered by the existing unique `tests/contracts/test_*.py` providers glob.

The narrow English tests were added after translation work began; this is regression evidence, not a claim of a complete test-first development history. A regression run detected JSON escaping in a translated quoted sentence; typographic quotation marks resolved it without changing story meaning, and the chapter hash was regenerated.

## Limits and unrun stages

The source was materialized from the pinned GitHub commit into a partial cloud checkout. The aggregate affected-check selector was attempted but could not produce a complete plan because not all unrelated test targets were present. Full/affected/release aggregates, web build, packaged-asset verification, and remote CI are not claimed as passed. The base branch has no GitHub Actions workflow; none was added.

No live OpenAI/Google/image calls, credentials, personal memory, persistent user checkpoints, browser/device, microphone, or TTS checks were used. Existing historical verification documents remain historical; this edition does not upgrade their acceptance status.

English is the default character language; users may request another language. UI labels, offline fixtures, speech recognition and TTS defaults are not fully localized. The optional legacy validator still recognizes its existing Chinese role-declaration patterns. The ordinary native-tool path is the English target. Internal `role_name` remains `夏禾`.

Translated authored content has new digests. Use a fresh ephemeral story session. Existing Chinese persistent checkpoints are not silently migrated or overwritten; compatibility checks remain in force.
