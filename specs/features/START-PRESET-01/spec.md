# START-PRESET-01: one local first-use launcher

Base: frozen 2012 source plus the three accepted repair sets, final source assembled 2026-10-07.
Owner: launcher tooling only; existing providers contract glob owns the focused tests.
Consumers: unchanged tools/live_provider.py, tools/dev.py, tools/bootstrap.py and the existing configuration loader.
Resource bounds and provider budgets are inherited unchanged; no new runtime, auth implementation, package dependency or provider request.

### STARTPRESET01-001 Exact convenience defaults
Given a portable source archive, previewing the live preset produces the owner's exact subscription, model, tier, voice, story and image-review argument list. Explicit safe overrides and existing lower budgets survive. Preview never starts a service, writes files, installs packages, reads auth-store/ADC contents or grants consent.

The public .env.example contains a closed MIRAAPP_ launch-field set for provider, model, requested tier, voice/story/images, image-review model, ADC path and optional MIRA auth path. The launcher parses these with the existing python-dotenv package, interpolation disabled. Explicit CLI arguments win. The unchanged core loader continues to consume only its declared service fields; the independent MIRAAPP_ prefix neither relaxes that loader nor grants permission. Preview may read the selected .env and show validated nonsecret launch fields, never API keys, tokens or raw loader output.

### STARTPRESET01-002 First-use consent stays local
Given no local choice, interactive startup offers live data/usage acceptance, offline rehearsal, or cancel; an unattended process refuses implicit live use. Explicit acceptance or an interactive choice is remembered only for that checkout and local user/machine. Offline never receives live configuration or flags. Cancellation changes nothing. The portable archive excludes var and all credential/configuration material.

### STARTPRESET01-003 Preserve configuration and credentials
Given a live selection and a missing default .env, startup copies the public template exclusively with mode 0600. An existing .env is never changed, including its permissions. Custom missing files are not created. ADC HOME paths and spaces stay literal arguments. Metadata checks reject unsafe files without reading ADC/auth contents; no shell source/eval or automatic authentication occurs.

### STARTPRESET01-004 Fail clearly before startup
Given missing dependencies, login, ADC, Google project configuration or unsafe permissions, startup stops with fixed local guidance, without an API fallback. check is read-only and never claims live readiness. setup is an explicit project-local invocation of the existing locked bootstrap, never a startup side effect. Official API and additional sensitive opt-ins remain on the original CLI with their existing explicit consent requirements.
