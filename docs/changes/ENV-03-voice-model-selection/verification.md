# ENV-03 verification

The exact user-selected Gemini 3.8 Flash TTS target is now typed configuration: aiplatform.googleapis.com, global, gemini-3.8-flash-tts. Old Cloud TTS endpoint and alternate model/location are rejected. Optional style uses the existing loader. Offline reports distinguish Preview/configuration from actual access. Quota-project configuration is optional. No live call, authentication grant, permission change or paid request occurred.

- 001-red: 4 failed, 7 passed; missing exact target, unsupported loader fields and incorrectly required quota project. Actual pytest exit 1.
- 002-green (attempt): 1 failed, 69 passed. An unrelated attempted default JEV model in the public template conflicted with the existing blank-template contract. That out-of-scope change was removed. This run is a recorded failure, not a green claim.
- 003-green: 70 env-related tests passed, actual pytest exit 0.

Evidence: docs/verification/env-03/runs/ (immutable recorder entries). The initial existing route assertion was updated to match the new target, so no byte-identical full test-file claim is made across RED/GREEN. The newly added behavior cases are retained. Full integration and actual voice probes remain separate and not run for this slice.
