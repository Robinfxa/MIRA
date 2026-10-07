# WP03 — Explicit bounded voice composition

Status: offline implementation slice; it does not grant live entitlement or new spend.

Scope: an opt-in factory for the existing `create_development_app(..., voice_factory=...)`
seam. It composes the existing Google voice bundle and wraps its two existing media ports.
No CLI or admission-manifest wiring is included in this slice.

Consumer: `create_development_app` through its existing `voice_factory` parameter.
Owner lane: `voice_composition`; baseline: current recovery source, synthetic tests only.
Resources: existing `create_google_voice`, `GoogleVoiceProviders`, and speech ports.

### WP03COMPOSITION-001 Explicit configuration and delayed construction

Given no caller authorization, missing opaque credentials/token provider, missing settings,
or a model/voice mismatch, when the development factory is created, then it fails clearly
before constructing a provider. The existing development app also rejects voice-required
mode when this factory is omitted. Given complete explicit
inputs, factory creation performs no provider/auth/network work; provider composition occurs
only when the returned factory is called from the application lifespan. The composition is
opt-in; absent `voice_factory` remains the existing offline/text-only default.

The supported selection is Google Speech-to-Text V2 `chirp_3` plus Gemini Enterprise
`gemini-3.8-flash-tts`, voice `Kore`, location `global`. The caller supplies any already
approved opaque credentials, asynchronous token provider, and optional HTTP client/CA/proxy
route. The helper never discovers ADC, loads environment/configuration, persists grants,
refreshes auth itself, retries, falls back, or opens a microphone.

### WP03COMPOSITION-002 Irreversible per-instance request reservations

Given finite positive request ceilings for one application voice instance, when an STT or
TTS stream attempt reaches dispatch, then one request slot is reserved before calling the
provider stream. Cancellation, provider uncertainty, or downstream close never refunds a
slot. Empty STT input does not dispatch and does not reserve a slot. Concurrent attempts
cannot oversubscribe the same instance.

### WP03COMPOSITION-003 Duration bounds and direct PCM delivery

Given finite TTS output and STT input duration ceilings, when PCM is streamed, then the
composition forwards each valid contiguous mono PCM16 packet as soon as it is validated,
without prebuffering. It never forwards the packet that would exceed the relevant per-instance
duration bound. STT over-limit PCM is not passed to Google. The existing typed adapter options
are narrowed before any SDK client is allocated; omitted bounds retain the existing factory
defaults. No input is retried or rerouted.

### WP03COMPOSITION-004 Lifecycle ownership and honest spend boundary

Given the application lifespan closes, when the wrapped voice bundle is closed, then the
underlying `GoogleVoiceProviders.close` is awaited once; repeated close is idempotent.
Request-count and audio-duration ceilings are per-instance technical guardrails, not a
dollar-spend ledger, billing estimate, or provider guarantee. Actual paid experiments remain
separately root-approved and ledger-bound. Tests use synthetic credentials, fake providers,
and fake PCM only; microphone and live inference are out of scope.
