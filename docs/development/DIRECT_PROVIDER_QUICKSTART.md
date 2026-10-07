# Direct provider startup

Current subscription `gpt-6-luna` now requests Fast by default (2.5x included subscription usage; no speed guarantee). Add `--service-tier standard` to opt out. Other model/API defaults are unchanged. See [requested tier, provider confirmation and bounded local check](DIRECT_SERVICE_TIER.md).

This source provides two explicit routes. Neither requires the Codex executable,
an app-server process, a binary pin, or a native-environment admission file.
The user has completed MIRA login and exercised text and partial voice on their Mac
in earlier builds. This candidate's new integration still needs device confirmation.
`check` proves only local configuration, never current account eligibility or a
successful conversation. New public launchers use the currently adopted code-native
character by default; `--character-renderer static-pixi` selects the explicit fallback.

## 1. Install and configure

Use the package's START-HERE to restore and run `python tools/bootstrap.py`.
Keep your existing private `.env` and existing MIRA/Google setup. Do not
copy another app's auth file or send credentials in chat. The explicit env file
may be inside this project, but must be owner-readable/writable only and excluded
from Git. No automatic login occurs on startup or on `check`.

The default `luna_tools` route does not need JEV credentials or a JEV health
check. Only an explicitly selected `--action-review-mode legacy_jev` uses the
historical JEV configuration and its separately authorized recipients.

Choose a model actually available to your chosen account/route; no model catalog
or entitlement check is performed implicitly, and no substitute model is chosen.

## 2A. Subscription login and direct text

```sh
.venv/bin/python tools/provider_login.py login
```

Read the displayed warning and confirm LOGIN only if you want this separate
MIRA session. Open the official link and enter the temporary device code there.
This grants MIRA ongoing access; credentials are stored in its own private local
app-data directory, unencrypted and excluded from the project. No Codex/Hermes
credential discovery or copy is used. The implementation targets the private
ChatGPT/Codex subscription Responses backend: its support, terms, quota and
account eligibility are not the official public OpenAI API contract. Login
completion alone does not prove model access.

On macOS the default session is under
`~/Library/Application Support/MIRA/auth/openai-codex-session.json`.
Linux uses `~/.local/share/mira/auth/openai-codex-session.json`.

```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py check \
  --provider chatgpt_subscription --model YOUR_MODEL --env-file .env

PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
  --provider chatgpt_subscription --model YOUR_MODEL --env-file .env \
  --authorize-provider-data
```

`--authorize-provider-data` acknowledges sending dialogue and tool context to
the selected OpenAI service. TypeSafe/JEV is used only in explicitly selected
legacy review mode. It does not enable memory recall or raw recording. An expired MIRA
session may refresh automatically at an explicitly requested generation call.

## 2B. Official API billing route

Add your own official OpenAI API key locally:

```text
MIRA_SERVICES__OPENAI__API_KEY=<enter locally>
```

```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py check \
  --provider openai_api --model YOUR_API_MODEL --env-file .env

PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
  --provider openai_api --model YOUR_API_MODEL --env-file .env \
  --authorize-provider-data --authorize-api-billing
```

This route sends requests only to `https://api.openai.com/v1/responses` and can
incur API charges. It never uses the subscription session, and subscription
failure never enables it. Arbitrary third-party endpoint/key forwarding is not
implemented. Request counts below are technical limits, not dollar guarantees.

## 3. Browser and finite voice

Open the printed loopback URL. The default port is8000; choose `--port` if it is
already in use. Do not terminate an unknown process or open the app to a network
by changing system/firewall settings. Remote/LAN serving is not enabled here.

For Google voice, retain the Google fields from [API_ENV](API_ENV.md) and supply
your own existing ADC path with separate audio/text transmission and spend
consent. Append to either `serve` command:

```sh
  --voice --adc-file /absolute/path/to/application_default_credentials.json \
  --authorize-google-voice-data-and-spend \
  --stt-requests 10 --tts-requests 20 --stt-max-seconds 120 --tts-max-seconds 30
```

The microphone still requires a click and browser permission. Normal continuous
listening keeps silence packets and provisional text, then submits an eligible
final utterance after the configured quiet/drain policy. Manual Send remains a
fallback. Stop closes the microphone and stops the reply. Recognition-stream
handover remains bounded and consumes the admitted shared service budget; at a
limit capture stops visibly and retains recognized drafts. Headphones are
recommended. Offline tests do not establish device acoustics, audibility or latency.

The subscription route defaults to no local text-generation request or text-turn
ceiling (both are null). Explicit `--generation-requests N` and `--turns N` keep
finite limits. The official API route still defaults to20 requests/20 turns.
Native Luna mode uses zero JEV requests; only explicit legacy mode uses JEV.
Google, image and default listening budgets remain finite and separate. These
local counters are not account billing controls; provider quotas still apply.

## Recovery and limits

- `provider_login.py status` checks only the MIRA store, without refresh/network.
- `logout` creates a local signed-out state. A recoverable backup remains;
  provider-side grant revocation is not claimed, and an already dispatched
  in-flight request cannot be recalled by local logout.
- `restore-backup` is explicit; no silent fallback to old credentials occurs.
- `forget` needs a separate DELETE confirmation and permanently removes only
  MIRA's local active/backup records, not the provider's grant.
- Native tool results distinguish pending, held and failed from shown. A held
  optional operation leaves legal dialogue available and never invents a receipt.
  Default mode has no JEV semantic gate or automatic provider retry.
- The local memory console remains separately usable without any model login.
  Memory recall is off by default and available through explicit options; existing recorder consent
  does not authorize sending stored memory through these new recipients.
- This implementation has synthetic auth/HTTP/ASGI verification. Real login,
  complete direct voice dialogue, Windows/macOS auth behavior and user-device
  visual/audio acceptance remain to be checked on the actual release.


## 可选的配对记忆

当前直连入口提供独立授权的本机作用域记忆召回及可选手动管理。默认关闭；语音组合额外披露Google TTS接收方。请按[直接服务记忆](DIRECT_MEMORY.md)添加完整选项，不继承旧Codex开发环境的同意或认证。软件组合只使用合成记录验收，真实记忆与设备行为仍待用户验收。
