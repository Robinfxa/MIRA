# Install and recover the 2026-10-03 archive checkpoint

This guide is for the immutable source-archive checkpoint published at commit [`54c1457cd897133e9ca0b3035fcd0a73ba8bef22`](https://github.com/Robinfxa/MIRA/commit/54c1457cd897133e9ca0b3035fcd0a73ba8bef22). It is a ZIP source archive, not an expanded Git checkout. The archive's expected SHA-256 is `cac357c3e5c21b283321a938a7c5d35e1ecaded5e65869d9aa21d7439f3ae37b`.

## Download and restore

From the exact commit above, download all seven files listed by its checkpoint: the ZIP, `MIRA-CHECKPOINT-MANIFEST-20261003T1158Z.json`, `restore-checkpoint-20261003T1158Z.py`, `SHA256SUMS-20261003T1158Z.txt`, `BACKUP-README-20261003T1158Z.md`, `KNOWN-GAPS-20261003T1158Z.md`, and `RELEASE-EVIDENCE-20261003T1158Z.json`. Keep them together. Verify them before extraction:

```sh
sha256sum -c SHA256SUMS-20261003T1158Z.txt
python3 restore-checkpoint-20261003T1158Z.py \
  mira-integration-20261003T1158Z.zip \
  MIRA-CHECKPOINT-MANIFEST-20261003T1158Z.json \
  ./mira-restored
cd mira-restored
```

Choose a destination that does not already exist. The verifier uses Python's standard library, checks the outer archive hash plus every expected archive path, file size, SHA-256 and stored Unix mode, rejects unsafe/non-regular members, and restores the files. On Windows, verify SHA-256 values with `Get-FileHash -Algorithm SHA256`; Windows executable-mode behavior was not tested. All archive files, including `scripts/dev`, are stored as mode 0644, so invoke the launcher with `sh scripts/dev` rather than executing it directly.

## Runtime and dependency setup

The project asks for Python 3.11–3.13; `.python-version` selects the 3.13 line. For a current patch, use the official [Python 3.13.16 release page](https://www.python.org/downloads/release/python-31316/) and its installer for your OS. On Windows, the page documents `py install 3.13` for the current 3.13 release. Historical startup evidence used Python 3.13.5, so a fresh install on a later patch is not a reproduction of that exact test environment.

The `.node-version` file names Node.js 22.16.0; the startup check accepts Node 22.12.0 or newer. Use the official [Node.js 22.16.0 download archive](https://nodejs.org/en/download/archive/v22.16.0) for that exact repository pin. The published startup verification records Node 24.19.0, so it did not validate the 22.16.0 pin specifically. Check both runtimes before setup:

```sh
python3.13 --version
node --version
npm --version
```

Install the locked development dependencies from the project root. This needs Python, Node/npm and package-registry access; it is intentionally not part of demo startup:

```sh
python3 tools/bootstrap.py
```

That command creates the project `.venv`, installs the exact Python versions in `requirements/dev.lock`, then runs `npm ci --ignore-scripts` for the exact TypeScript version in `package-lock.json`. If you prefer the explicit lock commands, use:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements/dev.lock
npm ci --ignore-scripts
```

On Windows PowerShell, the equivalent is `py -3.13 -m venv .venv`, `.\.venv\Scripts\python.exe -m pip install -r requirements\dev.lock`, and `npm ci --ignore-scripts`; start with `python tools/dev.py --python .\.venv\Scripts\python.exe --profile mock`. This path is documented but was not tested on Windows.

**Fresh dependency installation is not verified for this checkpoint.** Static inspection found that `package.json` says version `0.4.0`, while the root entry in `package-lock.json` says `0.4.1`; `npm ci` was not run here. If npm reports a lock/manifest mismatch, stop and keep the downloaded archive unchanged rather than editing the checkpoint to force installation.

## Start the offline demo

After dependencies are ready, run from the recovered project root:

```sh
sh scripts/dev --python .venv/bin/python --profile mock
```

For the fixed photo-tour replay fixture:

```sh
sh scripts/dev --python .venv/bin/python --profile replay \
  --replay-scenario photo-tour
```

Open `http://127.0.0.1:8000` in a browser. Use `--port 8123` to choose another permitted port (1024–65535). With a previously prepared Python environment, pass its explicit interpreter path instead of `.venv/bin/python`; the project still needs `node_modules/typescript/bin/tsc`. Windows can call `python tools/dev.py --python <path-to-python.exe> --profile mock` directly.

These profiles are explicitly offline: they do not load `.env`, forward common provider credentials, call a model, or permit paid calls/raw recording. This is configuration isolation, not an operating-system network or filesystem sandbox. Do not use `python -m mira` for this demo; it is the configuration-aware entrypoint. Real-provider use needs separate adapter, identity, data, budget and quality admission. Populating a config field does not enable it. A separate rehearsal of a newer profile is pending and is not verified by this archive or this guide.

## Common startup failures

- Exit 2, “Missing compatible Python/runtime dependencies” or “Selected Python is not usable”: check `python --version`, use Python 3.11–3.13, and point `--python` at an interpreter that can import the locked runtime packages. If dependencies are absent, run the explicit bootstrap above.
- Exit 2, “Missing Node.js or declared TypeScript compiler” or “Node.js 22.12+ is required”: check `node --version`; install an accepted Node release and run `npm ci --ignore-scripts`. Startup never installs tools automatically.
- Exit 2, “Startup command failed”: read the compiler/contract/server error immediately above it. If the port is occupied, retry on another port, for example `--port 8123`.
- Exit 2, “port must be an integer between 1024 and 65535” or an argparse usage error: correct the command/port.
- Ctrl-C stops the foreground server with exit 0.

The extracted ZIP does not contain Git history: use `tools/check.py --lane ...` or `--files ...` for local checks, not `--affected --base ...`. The historical `python tools/verify_tdd_evidence.py` command is unsupported from this public checkpoint because its raw FND-02 logs were intentionally excluded; this is documented in `docs/checkpoints/20261003T1158Z/KNOWN-GAPS.md`.

The compatibility health response reports the replay fixture family as `mode: "mock"`; that value does not distinguish a mock profile from replay.

## Diagnostics and secrets

The default local diagnostic export excludes reviewed raw dialogue/audio and does not contact or upload to a provider:

```sh
.venv/bin/python tools/export_diagnostics.py \
  --output var/diagnostics-export.zip
```

The destination must not already exist. Keep `var/` private and inspect the export before any separately authorized sharing; sanitized metadata can still be sensitive. Do not add `--include-reviewed-raw` or `--confirm-sensitive-export` for routine support. No credential file or API key is needed for mock/replay. Never put `.env`, tokens, service-account keys, auth caches, user recordings or exports in Git or in the public archive.
