# GV01: Explicit application Google voice configuration

## Scope and ownership

This isolated change starts from `mira-character-next-20261005T0325Z` (a source
copy without Git metadata). The integration owner owns bootstrap; this worker
changes only its separate copy. Provider tests are owned by the existing
`tests/contracts/test_*.py` rule in the `providers` quality lane. Affected
consumers are development/direct-provider composition, Actor, HTTP, and
continuous listening; no UI or public wire schema changes are needed.

All verification uses synthetic settings, opaque fake credentials, fake SDK
construction, and an in-memory HTTP transport. No network, ADC discovery,
token refresh, real synthesis, microphone access, or playback is authorized.
Request/duration budgets, endpoint, model, and consent requirements stay bounded
by their existing declarations. A named voice is configuration, not evidence of
account availability or listening quality.

## Given/When/Then

### GV01-001 Explicit application voice selection
- Given an admitted application profile with explicitly selected Kore or Gacrux,
  when its factory is invoked, then the exact selection reaches the existing
  Gemini 3.8 Flash TTS request. Existing Kore configuration remains Kore.
- Given a missing, unknown, malformed, or unselected voice, when the application
  factory is prepared, then it rejects before concrete provider construction.
- Given a probe profile, when Gacrux or another voice is selected, then the
  historical fixed-Kore guard still rejects before construction.
- Given a read-only launch check or actual application composition, when the
  shared settings validator is used, then it checks the same route/voice rules
  without credentials, resource allocation, or automatic configuration changes.

### GV01-002 Preserve approved content and request boundaries
- Given explicitly selected voice settings and an approved text,
  when the synthetic request is captured, then it contains exactly that text and
  the optional user-selected style, without an invented age or gender prompt.
- Given configured voice selection, when authorization is absent or a budget is
  exhausted, then existing admission and irreversible request ceilings apply.

### GV01-003 Locale limitation stays explicit
- Given a configured TTS language code, when the current exact Flash streaming
  request is built, then no language field is added and its text is unchanged.
  Language detection remains model-controlled, and configuration is not claimed
  to be applied.
- Current 3.8 migration documentation describes `languageCode` but the exact
  Flash streaming schema is not independently established by this change.
  Forwarding is deferred rather than guessing the accepted locale contract.

## Evidence sources

- Current voice catalog: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/overview
  lists Gacrux as Mature and Kore as Firm. Configuration does not establish audio
  quality or availability in this project.
- Migration field evidence and its limits:
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/migration-guide
  demonstrates a 3.8 Flash-Lite request and a shared schema statement; this is
  not an exact Flash streaming `cmn-CN` validation.
- Existing actual Google voice smoke and device acceptance remain not run in
  this change. Full/release verification is reserved for the integration owner.
