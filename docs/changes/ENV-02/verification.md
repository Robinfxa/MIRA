# ENV-02 Provider Matrix · Verification

Decision implemented in foundation 0.4.1:

- main LLM, image generation, and actual-image review use the OpenAI provider family;
- development carrier defaults remain `codex_native`, with explicit `openai_api` as an opt-in alternative;
- ASR and TTS are explicitly typed as `google_cloud` capabilities;
- JEV/TypeSafe remains the current Input/Output Decision route and is not silently merged into the main LLM.

No live account, inference, image, ASR, or TTS call was made in this change.

## TDD

The first corrected RED run of `tests/unit/test_provider_matrix.py` failed because `SpeechSettings` did not expose typed ASR/TTS provider fields and the offline report used a hard-coded speech route label. After implementing the provider fields and deriving report routes from them, the same five tests passed.

## Local verification

- targeted `env` lane: passed;
- full offline lanes: passed;
- 245 Python tests across pytest lanes passed; `specs` and `web` command lanes passed;
- package/smoke, real providers/accounts, browser/device audio, and independent human validation were not run for this small policy/config change.

The full run is integration evidence only; it does not change the project’s real-service readiness flags.
