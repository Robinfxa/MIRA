# Google application voice configuration

The explicit `application` usage profile now accepts **Kore** or **Gacrux** for
the existing `gemini-3.8-flash-tts` route. Google describes Kore as **Firm** and
Gacrux as **Mature** in the current Enterprise voice catalog. The Cloud Gemini
voice catalog labels both voices female, but that separate catalog is not an
audio test of this exact 3.8 route.

User-selected application preset, recorded 2026-10-05 05:34 UTC. The public development template now contains these two settings:

```dotenv
MIRA_SERVICES__SPEECH__TTS_VOICE=Gacrux
MIRA_SERVICES__SPEECH__TTS_STYLE=御姐音，语调轻快，爽朗自然，咬字清晰，亲切有活力，不刻意压低嗓音或拖慢语速。
```

Existing private files are never rewritten. Apply these public fields to the explicitly selected private configuration and restart its server to use the preset. An existing Kore selection remains Kore. Missing voices do not silently default
to either voice. The historical `probe` profile and fixed Google smoke continue
to require Kore; this change does not rewrite their request policy.

The pure `validate_development_voice_settings(..., usage_profile="application")`
helper lets a launcher check the same fixed provider/model/endpoint/voice rules
before any credential loading or SDK allocation. It returns the original typed
settings and does not grant authorization or prove provider availability.

Approved speech text remains exactly the text passed to the adapter. The
existing optional short `TTS_STYLE` setting remains user-selected and travels as
`speechMetadata.style`; the implementation adds no age, sex, or persona prompt.
All existing data/spend consent, injected credentials, attempt ceilings, media
limits, cancellation, and no-fallback policy still apply. No new model, vendor,
endpoint, permission, or credential is introduced.

## Language limitation

This route still relies on the model's language detection. The existing
`TTS_LANGUAGE_CODE` setting is retained but **is not sent or applied** by this
implementation. In particular, a configured `cmn-CN` or `en-US` is not evidence
that an explicit language request was made.

The current 3.8 migration guide maps `voice.languageCode` to
`generationConfig.speechConfig.languageCode` and shows an `en-US` Flash-Lite
example. Its schema statement supports further investigation, but the referenced
generic streaming REST schema still exposes older voice shapes. This change
therefore does not claim to have verified the exact Flash streaming locale
contract and does not add that request field. No locale whitelist is invented.

## Sources and acceptance boundary

Official documentation checked 2026-10-05:

- [Current Enterprise TTS overview and voice catalog](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/overview)
- [Cloud Gemini TTS voice options](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)
- [Current 3.8 migration guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/migration-guide)
- [Streaming REST method](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1/projects.locations.publishers.models/streamGenerateContent)

Offline contract tests capture an actual serialized request using an in-memory
HTTP transport and synthetic credentials. They prove explicit voice selection,
unchanged content/style, no language field, fail-before-allocation validation,
probe compatibility, and existing budget/admission behavior. They do not prove
account entitlement, a mature listening impression, speech quality, real audio
generation, physical playback, or device acceptance. No provider call was made.
