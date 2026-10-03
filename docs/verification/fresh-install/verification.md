# Fresh dependency install and offline rehearsal startup

2026-10-03 UTC. Verification source: frozen public snapshot `<project-root>`. This run used an allowlisted disposable copy at `<private-workspace-path>`; it did not use the canonical checkout as its runtime.

## Scope and source isolation

Copied only these public source entries: `AGENTS.md`, `README.md`, `THIRD_PARTY.md`, `.node-version`, `.python-version`, `package.json`, `package-lock.json`, `pyproject.toml`, `setup.py`, `requirements/`, `config/`, `apps/`, `packages/`, `scripts/`, and `tools/`. Removed copied Python bytecode/cache directories. The `.env` files, `var/`, `.git/`, existing `node_modules` symlink, venvs, credential/authentication caches, capture manifest, tests, and prior verification logs were not copied or read. A fresh `node_modules/` and venv were created only in the disposable copy.

Before install, all 46 non-comment entries in `requirements/dev.lock` were exact `==` pins. `package-lock.json` contains one dependency, TypeScript 5.8.3, with a `resolved` URL on `https://registry.npmjs.org/`. No alternate index or mirror was used. Python pins do not include hashes; the npm lock does not include an integrity hash. The Python install was wheel-only to prevent source builds. Temporary empty npm user/global configuration files prevented loading private npm config; pre-existing proxy/CA environment was left opaque and unchanged.

Snapshot lock hashes:

- `requirements/dev.lock`: `1690dc3d5da7fa1e3bec0af5759b0af94aaa8dd9f5202c02547d635a2f04940b`
- `package-lock.json`: `11eb6a6d54ee8efaa04bf644199536d124ad1738b4efbec2957baad1612226f0`
- `package.json`: `c319a7d4621c91fdc2a4d76eaee5da6be2bb9bf4d0a1b2201fccb5a1342121e5`

## Installation and environment

- Python: `/usr/bin/python3.13` = 3.13.5. The distribution lacked `ensurepip`, so the initial stdlib `python -m venv` attempt failed before any install. The installed `uv 0.12.19` created an isolated venv; no system/global package changes were made.
- Successful isolated venv creation command: `UV_CACHE_DIR=<temporary-evidence-path> uv venv --no-config --no-project --clear --python /usr/bin/python3.13 .venv`. The first attempt to initialize uv's default cache failed because the default home cache directory is read-only; placing uv's cache under `/tmp` resolved that local filesystem issue without changing network or registry settings.
- Successful Python command, after the first un-escalated exec session was canceled by automatic review (no substantive refusal reason):

  `uv pip install --no-config --no-cache --only-binary :all: --python <private-workspace-path> --default-index https://pypi.org/simple -r <private-workspace-path>`

  Submitted as the exact scoped network install with `require_escalated`; reviewer accepted it. `uv` reported 46 resolved in 8.51 s, 46 prepared in 0.841 s, installed in 0.288 s, and downloaded required wheels from the official PyPI index. The first canceled attempt is not counted as a successful install.
- Node: 24.19.0; npm: 11.9.0. Successful command in the disposable copy, using separate empty user/global npm config files and an isolated cache:

  `npm --userconfig=<temporary-evidence-path> --globalconfig=<temporary-evidence-path> ci --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org/ --cache=<temporary-evidence-path>`

  Completed with `added 1 package in 6s`; install scripts, audit, and funding checks were disabled. `node_modules` contains only `typescript@5.8.3`.
- Local checks: `pip check` reported no broken requirements. Metadata comparison showed exact parity: 46 installed Python distributions / 46 lock entries. TypeScript reports 5.8.3.

## Fresh CLI startup and HTTP rehearsal

With a minimal process environment (PATH, locale, empty temporary HOME/TMPDIR; no MIRA/provider variables, credentials, proxies, or dotenv file passed), ran the documented shell entrypoint equivalent:

`sh scripts/dev --python .venv/bin/python --profile rehearsal --port <ephemeral-loopback-port>`

Measured 2.997 s from process launch to first successful loopback health response, including contract export check and TypeScript compilation. CLI/API checks passed:

- `GET /api/v1/health`: `status=ok`, `mode=rehearsal`; live LLM, live audio, and live image all false
- `GET /api/v1/voice-capabilities`: generation rehearsal, offline-fixture qualification, fixture speech enabled at 24 kHz, microphone disabled
- `GET /api/v1/diagnostics-status`: recording inactive
- Root HTML, compiled `/dist/app/main.js`, CSS, capture worklet, and both original SVG scene assets returned HTTP 200
- `/.env`, `/.git/config`, `/var/quality/private.json`, and `/auth.json` returned HTTP 404
- Created a local session, submitted the fixed `你好` rehearsal command, and streamed its authorized prerecorded fixture speech. Received 25 audio frames / 147,240 PCM samples at 24 kHz plus a complete frame; sample count matched the payload. Session was deleted afterward.

No real provider, browser, microphone, audio device, or user audio was used. The stream test confirms local fixture transport only; it does not establish audibility or user-perceived quality.

## Limits

This verifies one clean install and startup in the current Linux container with Python 3.13.5 / Node 24.19.0. It is not a fresh OS image, other-platform install, full test-suite/release run, live-provider check, or browser/device acceptance. This subtask changed no canonical code or lockfile; its only intentional canonical edit is this report.
