# ENV-03 Exact Google voice model selection

### ENV03-001 Exact TTS target
Given the current MIRA mission configuration, TTS selects gemini-3.8-flash-tts on aiplatform.googleapis.com in global. Legacy Cloud Text-to-Speech endpoints and substitute models are rejected rather than silently used.

### ENV03-002 Separate Google voice settings
STT remains Speech-to-Text V2 with independently selected location/model/language. TTS model/location/voice/style enter only through the existing typed loader. These public configuration values never imply successful authentication or live inference.

### ENV03-003 Accurate offline preparation
The offline preparation report identifies the exact Google Gemini Enterprise TTS route/model/location and Preview status; it does not call services or report live readiness. A quota project is optional configuration, not a requirement when the runtime identity can use the service project.

## Scope and owners
Director owns service_settings.py, loader.py, public development template and preparation report. Existing env lane owns test_provider_matrix.py. Consumers are the future Google speech adapters and bootstrap integration; no authentication, API enablement, billing or live request is authorized by this config change.
