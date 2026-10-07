# Explicit local development entry

`tools/live_dev.py` starts the existing MIRA ASGI application with the real, injected Codex and JEV adapters. It is a local development entry for one admitted app process, not a public deployment path. The ordinary `create_app()` and `create_providers()` live guard remains in place.

## Prepare and run

Use your own supported Codex CLI installation and login. Create a private MIRA env file outside the checkout through the existing loader conventions, and configure the fixed JEV model `jev-1.13.0` plus your TypeSafe key. The app entry does not auto-discover `.env` files or copy Codex/Google credentials. See [local runtime admission preparation](RUNTIME_PREPARATION.md) for the separate metadata-only admission step and its required confirmations.

With Python 3.11–3.13 and the declared dependencies already installed:

```bash
python tools/live_dev.py check \
  --env-file "$HOME/.config/mira/development.env" \
  --admission "$HOME/mira-runtime-admission.json"

python tools/live_dev.py serve \
  --env-file "$HOME/.config/mira/development.env" \
  --admission "$HOME/mira-runtime-admission.json" \
  --port 8000
```

The no-argument command only reports the unarmed help state. `check` reads the two explicitly named private files and reports declarations; it makes no provider request. Its status is always `armed=false`, `declaration_checked=true`, and `live_ready=false`. `admission_authorized` only reflects that the explicitly declared admission passed parsing; it is not runtime or account readiness. Declared model/key metadata does not verify provider credentials, quota, entitlement, or inference. `serve` validates the admission and config, checks contract exports, rebuilds the TypeScript app, then binds only to `127.0.0.1` with one worker. It fails before serving if the compiler, runtime dependency, JEV config, or static build is missing. It never installs packages or loads Python modules/plugins named by user input.

The admission file is strict, private JSON outside the repository. Public-route admissions contain `route_kind=public`, a pinned config digest, an explicit policy confirmation, and `development_context=null`; they do not set `CODEX_HOME` in the child environment. The separately approved managed route must carry its own explicit pinned context. Its factory also accepts Codex's omitted `CODEX_HOME` default only when a canonical absolute `HOME` binds `runtime.codex_home` to `HOME/.codex`; it neither inserts an override nor inspects the filesystem at composition time. Filesystem, ownership, and fingerprint validation remains deferred until production runtime validation before process spawn. Neither route is inferred from local paths or ambient proxy settings.

## Text-only behavior

The CLI serves with speech and microphone capabilities disabled. Codex receives a text-only output schema and the parser rejects any returned speech effect. A new on-screen sentence is a standalone subtitle effect; authored pose and scene effects can accompany it. The existing presentation gate and renderer handle the text. A speech-bound caption still waits for real audio submission, so the app never silently drops speech and treats its caption as an independent reply.

`--voice-required` exits with a clear error because this fixed CLI has no admitted voice factory. A caller may use `create_development_app()` directly with an already-authorized in-process voice factory and voice bundle; typed Google ADC/project/model fields by themselves do not construct or admit voice. The app reports actual speech and microphone availability through the existing `/api/v1/voice-capabilities` endpoint.

## Data, limits and portability

The separate admission step requires `--authorize-codex-and-jev-content` as well as `--confirm-policy-environment` before it can write a runnable admission. Entered dialogue and relevant prior MIRA application context go to native Codex/OpenAI and TypeSafe/JEV; generated candidate content also goes to TypeSafe/JEV. JEV requests may be billable. No workspace files or authentication files are uploaded by this entry.

Codex requests, JEV requests and turns have finite caller-declared ceilings and per-request timeouts. The app consumes allowances before each provider request; failures and cancellations do not restore them. These ceilings apply to one running app instance. Restarting with the same admission starts a fresh in-process allowance; this is not a persistent cross-restart ledger and is not a dollar cap. Declarations do not establish quota, account entitlement, a spend limit, or provider readiness.

The cloud development environment's earlier successful inference does not establish that another machine, Codex account, Google project, ADC identity, or JEV account has quota or access. This source's public admission preparer supports only the reviewed native Codex CLI 0.159.2 pins for Linux x86_64, macOS arm64, and macOS x86_64; it does not auto-repin and does not support Windows or Linux arm64. The frozen 09:52 delivery remains Linux-only, so use a matching later source/package rather than transplanting this helper alone. Actual Mac startup, metadata, login, inference, and user-device acceptance remain unverified. This local one-worker in-memory app is not a portable public deployment or a complete product acceptance run.

## Diagnostic behavior at the real entry

The development app preserves the configured sanitized local diagnostics recorder, including bounded rotation, stable error codes and correlated request IDs. It distinguishes a provider response contract error from a semantic rejection or an uncertain review. Raw dialogue/audio recording remains off at startup even if the incoming configuration requested recording; use the existing explicit visible recording consent flow when appropriate. `check` remains configuration-only and does not prove inference or write a provider success record.
