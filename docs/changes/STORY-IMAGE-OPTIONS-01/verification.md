# STORY-IMAGE-OPTIONS-01 offline verification

2026-10-05. Implementation source: isolated `mira-story-image-options-20261005T2321Z`, copied from immutable 2308. Runtime and provider adapter source files were not modified in this slice. `tests/quality.toml` is unchanged because its existing providers contract glob already uniquely owns the new test module. No actual user environment/credential file was read. No installation, login/account flow or live provider call occurred.

- `docs/verification/story-image-options-01/runs/001-red`: 24 directed failures, including the missing default-disabled declaration (KeyError), absent explicit CLI arguments and absent bootstrap behavior. Tests were collected/executed; this is not a collection-error RED.
- `002-green`: 105 passing synthetic tests across optional-image options, existing direct launcher and Fast service tier. The runtime fake was updated to the agreed explicit `operation_admission` protocol after the runtime owner finalized that interface.
- `003-wiring-green`: 112 passing tests in the same three modules, including seven additional startup/composition/key-isolation cases. New file contains 31 parameter-expanded cases. These later added cases are regression coverage, not a claim of individually recorded RED.
- First affected run `var/quality/b66eccae27564d0b93b335073b4d4581/summary.json` is retained as failed. The default in-checkout pytest basetemp correctly triggered existing private-memory/auth-path guards in config/providers/tooling tests. Those guards were not altered.
- Corrected affected run used `--output-dir /workspace/scratch/96ff05e059bf/mira-story-image-options-quality-20261005T2330Z` outside the source checkout. All nine selected lanes passed: architecture, env, config, actor, providers, http, tooling, specs and continuous. The receipt reports unchanged source before/after. Domain, web, package and smoke were explicitly not run. This is affected-scope verification, not release/full acceptance.

Exact affected command, from the isolated source directory:

```sh
/workspace/scratch/96ff05e059bf/mira-image-runtime-20261005T2253Z/.venv/bin/python tools/check.py \
  --files apps/api/src/mira/bootstrap/story_image_provider.py tools/live_provider.py \
    tests/contracts/test_story_image_options.py \
    specs/features/STORY-IMAGE-OPTIONS-01/spec.md \
    specs/features/STORY-IMAGE-OPTIONS-01/traceability.json \
  --jobs 2 \
  --output-dir /workspace/scratch/96ff05e059bf/mira-story-image-options-quality-20261005T2330Z
```

A separate explicit cross-tree constructor/ownership smoke is saved at `mira-story-image-composition-check-20261005T2330Z/{check.py,result.json,sources.json}` outside this source. It imports actual lifecycle runtime, actual repaired adapters and this bootstrap while replacing `httpx.AsyncClient` with a failure sentinel. It confirmed exact `StoryImageRuntime` type, distinct session instances, shared process gate, persistent exhaustion after Close, actual adapter construction, zero HTTP-client allocations and zero external calls using only a synthetic SecretStr. It is an interface smoke with recorded source hashes, not a claim of full same-tree integration or actual image/review quality.

The integration owner must combine the matching runtime hook, app factory, repaired adapters/dependency declaration, and this bootstrap/CLI in a new isolated tree and run its own same-tree checks. Preserve frozen 2308 and published artifacts. Actual API data transmission/spend remains unapproved; configuration examples and offline consent flags are not live authorization. Private memory, arbitrary user picture briefs, reference images, provider account availability, actual pixel-review quality and real presentation remain outside this verification.
