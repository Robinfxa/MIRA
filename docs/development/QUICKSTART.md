# MIRA offline rehearsal quickstart

This guide restores and runs the **14:48 offline rehearsal** from its pinned archive. The public [14:48 commit](https://github.com/Robinfxa/MIRA/commit/e123a169cacf6e1432e2b85952508070e725c9c0) contains backup files, not an expanded app tree. Use this exact commit rather than a moving branch.

The frozen release and restored projection each passed 1,155 Python tests and 185 Node tests across 12 local release lanes. A later local HTTP rehearsal reproduced a remaining ordering issue: a delayed receipt for an already-presented photo can arrive after the next prompt's context is captured and lead to an incorrect “not opened” follow-up. This evidence is not live-provider, browser/device, or product acceptance. See the [14:48 known-issue notice](../mission/acceptance-status-1448.md) and the archive's `KNOWN-ISSUE-ADDENDUM-20261003T1448Z.md`.

## 1. Fetch and safely restore

The pinned commit includes the archive, manifest, checksum list, safety notice, and replacement restore helper. It supersedes the historical assertion-based helpers in the earlier backups.

```sh
git init mira-checkpoint
cd mira-checkpoint
git remote add origin https://github.com/Robinfxa/MIRA.git
git fetch --depth 1 origin e123a169cacf6e1432e2b85952508070e725c9c0
git checkout --detach FETCH_HEAD
git rev-parse HEAD
sha256sum -c SHA256SUMS-20261003T1448Z.txt
python3 restore-checkpoint-explicit-20261003T1448Z.py \
  mira-integration-20261003T1448Z.zip \
  MIRA-CHECKPOINT-MANIFEST-20261003T1448Z.json \
  ../mira-restored-1448
cd ../mira-restored-1448
```

`git rev-parse HEAD` should print the pinned commit above. On macOS, use `shasum -a 256 -c SHA256SUMS-20261003T1448Z.txt`. The restore destination must not already exist; use a private existing parent directory without competing writers. The helper uses Python's standard library, validates hashes and safe paths explicitly, stages the output, and runs no archive code. Do not use the older `restore-checkpoint-20261003T1158Z.py`, `...1236Z.py`, or `...1256Z.py` helpers: their security checks use `assert`, which Python optimization can disable. SHA-256 checks establish consistency with the published list, not who authored the files or their authenticity.

## 2. Install declared dependencies and launch

The README documents Python 3.11–3.13 and Node.js 22.12 or newer; this checkpoint pins Python 3.13 and Node 22.16.0. With a compatible Python and Node/npm on `PATH`, install the locked development dependencies into the project `.venv` and `node_modules`:

```sh
python3 tools/bootstrap.py
sh scripts/dev --profile rehearsal
```

Bootstrap needs package-registry access and does not install global packages. The launcher itself never installs packages, loads `.env`, forwards common provider credentials, or calls live providers; it builds the contracts and frontend, then serves on loopback at `http://127.0.0.1:8000`. If port 8000 is busy, use `sh scripts/dev --profile rehearsal --port 8123`. For an already-ready interpreter, add `--python /absolute/path/to/python`.

A clean dependency install and rehearsal startup were verified for the earlier 12:56 source snapshot in one prepared Linux container (Python 3.13.5 and Node 24.19.0); its dependency manifests match this archive. The 14:48 snapshot has its own release-suite results. This is not fresh-operating-system setup evidence, a setup-time promise, or all-platform acceptance. If dependencies are missing, run bootstrap explicitly; it is not part of server startup. Stop the local server with Ctrl+C.

## 3. Try the finite rehearsal

The command set is fixed; this is not free conversation, live speech recognition, or Google voice synthesis:

```text
你好
不要拍我
看照片
照片里有什么
讲讲旅途   # press Stop during the response to test cancellation
听雨
暖灯
/fail      # inject a failure; send 你好 to recover
```

The eight original prerecorded clips are synthetic English Flite/slt audio totaling 52.56 seconds, not human or Google recordings and not a Chinese voice-quality check. The labeled hold-to-rehearse control only shows simulated listening; it never requests the microphone, and release submits the fixed text `照片里有什么`.

## 4. Keep configuration and diagnostics separate

No key or `.env` file is needed for rehearsal. The tracked `.env.example` and `.env.development.example` are templates, not real credentials or project IDs. For later, separately authorized service setup, `python tools/api_env.py init` creates the repo-root `.env` without overwriting an existing file (mode 0600 on POSIX); edit it locally and protect Windows file permissions separately. The service template names fields such as `OPENAI_API_KEY`, `TYPESAFE_API_KEY`, and `GOOGLE_CLOUD_PROJECT`, but contains no real key or project. Never commit, print, share, or copy authentication state into MIRA. A structured candidate has now been produced through an approved private Codex development context; public live-factory admission, JEV quality, Google voice, and real browser/device acceptance remain separate. That development route is not promised to be portable.

Ordinary diagnostics are bounded and sanitized; raw development recording is off by default. The optional development-recording settings require both `MIRA_DIAGNOSTICS__DEVELOPMENT_RECORDING=true` and `MIRA_DIAGNOSTICS__RECORDING_CONSENT=true`, plus a visible recording indicator. This covers only privacy-approved dialogue/logical-model content. Runtime/UI raw-audio capture is unfinished and unavailable in this checkpoint; the rehearsal never opens the mic.

Export ordinary diagnostics to a new local file with:

```sh
python tools/export_diagnostics.py --output var/diagnostics-export.zip
```

Including reviewed raw data is a separate, sensitive local export requiring both flags below; it neither enables capture nor authorizes sharing. Inspect any such archive before any separately authorized sharing.

```sh
python tools/export_diagnostics.py --output var/diagnostics-sensitive.zip \
  --include-reviewed-raw --confirm-sensitive-export
```
