# MIRA offline rehearsal quickstart

Use one verified published source stage. For the current split delivery, keep its code ZIP, both asset ZIPs, split-source manifest, matching restore helper, SHA list and START-HERE together. Follow that START-HERE restore command into a fresh directory; the helper verifies all declared source bytes and modes. These sidecars ship beside the ZIPs, not inside the restored source. Older single-ZIP checkpoints retain their own documented restore formats; never mix parts/helpers from different stages or overwrite newer source with a historical checkpoint.

The current snapshot and acceptance boundary are in the bundled [README](../../README.md). This guide does not promise a completed live model/voice interaction or all-platform installation. No key is needed for the steps below.

## 1. Check prerequisites

Install Python 3.11–3.13 plus Node.js 22.12 or newer and npm from their official distributions. `python3 --version`, `node --version`, and `npm --version` must work in your terminal. Bootstrap installs locked project dependencies; it does not install Node/npm or change global packages.

A fresh project directory on the existing Linux host was actually tested with Python3.12.14 (ensurepip25.0.1), Node24.19.0 and npm11.9.0, with cold project-local caches. Original bootstrap finished in54.837 seconds; rehearsal became HTTP healthy3.518 seconds after launch. The whole recorded attempt through server cleanup took5m55s. This is not a fresh-OS or user-device guarantee. The0837 dependency set subsequently proved to lack Uvicorn WebSocket support; its HTTP rehearsal timing does not establish real microphone transport.

Check `python3 -m ensurepip --version` before bootstrap. One Python3.13.5 distribution here lacked ensurepip and failed before downloading anything; Python version alone is insufficient. Prefer an official Python distribution with venv/ensurepip. An existing trusted pip can explicitly target the new virtual environment with `EXISTING_PYTHON -m pip --python NEW_VENV_PYTHON install -r requirements/dev.lock`; this is an additional installation step, not evidence that the original one-command bootstrap succeeded. Do not change system Python or run a downloaded bootstrap script.

Linux is the tested runtime. macOS and physical phones await user acceptance. Windows is not currently an accepted target: the locked Starlette static-file implementation has a Windows-specific UNC-path advisory, so do not run this development server on Windows until that platform is separately remediated and tested.

## 2. Install locked dependencies and launch

From the extracted project root:

```sh
python3 tools/bootstrap.py
sh scripts/dev --profile rehearsal
```

Bootstrap needs the official package registries. The server launcher never installs dependencies, loads private `.env`, forwards provider credentials or calls live providers. It checks contracts, compiles the frontend and serves only loopback at `http://127.0.0.1:8000` on the computer where it runs. Open that address in your own browser on that computer; it is not a public link or a supported remote-preview promise. Stop with Ctrl+C.

If that local port is occupied, select a free port through the documented launcher option, such as `sh scripts/dev --profile rehearsal --port 8123`. This local setup option is not permission to bypass a browser or managed-network access restriction. For an already-ready interpreter, add `--python /absolute/path/to/python`. If `node` or `npm` is missing, install that prerequisite before bootstrap; selecting a different Python alone cannot resolve it.

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

No key or `.env` file is needed for rehearsal. The tracked `.env.example` and `.env.development.example` are templates, not real credentials or project IDs. For later, separately authorized service setup, `python tools/api_env.py init` creates the repo-root `.env` without overwriting an existing file (mode 0600 on POSIX); edit it locally and protect Windows file permissions separately. The service template names fields such as `OPENAI_API_KEY`, `TYPESAFE_API_KEY`, and `GOOGLE_CLOUD_PROJECT`, but contains no real key or project. Never commit, print, share, or copy authentication state into MIRA. Historical controlled native generation and isolated provider checks are documented in README. Runtime admission, complete live conversation, JEV quality and real device acceptance remain separate. A managed development context is not promised to be portable.

Ordinary diagnostics are bounded and sanitized; raw development recording is off by default. The optional development-recording settings require both `MIRA_DIAGNOSTICS__DEVELOPMENT_RECORDING=true` and `MIRA_DIAGNOSTICS__RECORDING_CONSENT=true`, plus a visible recording indicator. This covers only privacy-approved dialogue/logical-model content. Reviewed raw-audio staging is available only through the separately enabled development voice entry, with exact-buffer review and explicit persistence confirmation. The rehearsal never opens the mic.

Export ordinary diagnostics to a new local file with:

```sh
python tools/export_diagnostics.py --output var/diagnostics-export.zip
```

Including reviewed raw data is a separate, sensitive local export requiring both flags below; it neither enables capture nor authorizes sharing. Inspect any such archive before any separately authorized sharing.

```sh
python tools/export_diagnostics.py --output var/diagnostics-sensitive.zip \
  --include-reviewed-raw --confirm-sensitive-export
```

## Configuration failure and capacity recovery

The installed `mira` entry reports recognized configuration failures before opening the server: exit2, fixed `configuration_error`, a unique startup identifier, and safe declared field names when available. No values or traceback are reflected. This identifier belongs to the stderr event; a service log may not exist because startup stopped. Check the selected profile and declared fields, then retry. Unexpected programming failures are not silently disguised as configuration problems.

For an exact `429 session_capacity`, end the current or unused sessions before refreshing to create a new one. Repeating the same input cannot reset the local session/turn/microphone budget. Other429 responses remain generic; the UI does not invent a provider quota diagnosis.
