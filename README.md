[English](README.md) | [简体中文](README.zh-CN.md)

# MIRA · Real-time character interaction in a rainy-night café

MIRA is an original fictional photographer, age 26. In a rainy-night café, you can type or speak with her, interrupt her replies, talk about photography, change her outfit and surroundings, and take on the role of her old friend Xiahe (夏禾) for a reunion and a photo-giving scene. The character and setting are the heart of the experience; the chat panel supports input and reading.

The project's core multimodal capability is **code-driven character animation**, complemented by a fixed lighthouse photo and optional background image generation. MIRA stays in character during everyday conversation. When explicitly asked about being an AI, existing in the real world, or where images come from, she should truthfully explain that she is an AI playing MIRA and identify the actual source of the assets.

## English branch: start with the character prompts

**[Explore the English character and story prompts →](docs/prompts/README.md)**

This branch provides an English README and English character prompts. It is not a complete localization of the application: existing UI labels, offline rehearsal triggers, and STT/TTS language settings have not all been translated or reconfigured. Chinese UI labels and exact rehearsal inputs are retained below where needed to operate the current application. For the runtime character instructions, see [`character_voice.py`](apps/api/src/mira/adapters/generation/codex_support/character_voice.py); the [story seed](apps/api/src/mira/adapters/story/assets/mira.story-seed.v1.json) and [Xiahe chapter](apps/api/src/mira/adapters/story/assets/xiahe-chapter.v1.json) define the authored story material. The [prompt guide](docs/prompts/README.md) explains how these sources fit together. The original Chinese project overview is preserved in [README.zh-CN.md](README.zh-CN.md).

**Source delivery baseline: the project submission source ZIP dated 2026-10-07, incorporating the 2012 baseline and three fixes for image review, natural conversational transitions, and default pairing-free access on the same Wi-Fi network. No separate patch installer is needed.** The frontend included in that package was compiled from the same frozen source; dependencies must be prepared separately. The user confirmed basic chat, the fixed photo, and one generated image with a proactive completion notification, but that feedback was not tied to an exact source digest. Full voice interaction, real interruption, mobile use, and the complete flow on the same version still require hands-on acceptance testing. The demo video is supplied separately by email: the user has recorded it, but it is not included in this package and has not been independently checked on their behalf. See the [verification notes](docs/submission/VERIFICATION.md) for the scope of historical releases, subsequent impact checks, and this packaging verification. The full release suite was not rerun for that package, and no new online demo or remote repository was published as part of that packaging work.

[Start here](START-HERE.md) · [First run / upgrading](FIRST-RUN.md) · [Submission checklist](docs/SUBMISSION-CHECKLIST.md) · [Recording guide](docs/development/DEMO-RECORDING.md) · [AI usage notes](AI_USAGE.md) · [Verification scope](docs/submission/VERIFICATION.md)

## What you can experience

- **Real-time conversation:** text and real microphone input that you explicitly enable, with voice, subtitles, and four states: idle, listening, thinking, and speaking.
- **Visible performance:** neutral, guarded, happy, and shy expressions; raising and putting down the camera; a black jacket, cream inner top, and amber raincoat; a camera hair clip and a star hair clip.
- **Changing scenes:** the café and a rain-streaked window. Camera actions change only the character's pose; they do not photograph the user.
- **The Xiahe chapter:** talking as strangers → explicitly identifying yourself as Xiahe → recalling how you chose test prints together → an invitation to receive a photo → one acceptance → actually handing over the photo on screen. Previewing the photo and completing the gift are recorded separately.
- **New images in the background:** request a fictional environment or still-life image with no people or animals, then keep chatting. MIRA gives one natural notification only after the image is actually displayed. You can separately hide the fixed photo, cancel a generation task, or stop everything.
- **No-key experience:** a local Mock mode and a fixed rehearsal with prerecorded audio, both clearly marked as offline.

## Current character artwork and development views

The first three images below are **offline renders of the current code**. They use the character composition functions from the same version and existing scenes, rasterized from SVG. They show the designs, outfits, and expressions present in the actual code. They are neither simulated product UI nor browser/device screenshots.

![Offline render of the current code: MIRA in the rainy-night café](docs/images/01-current-stage.png)

Three outfits: black jacket, cream inner top, and amber raincoat. This image is a visual reference, not a substitute for testing the actual outfit-changing interaction.

![Offline render of the three current outfits](docs/images/02-current-wardrobes.png)

Four expressions: neutral, guarded, happy, and shy. [Still frames of the four interaction states](docs/images/04-current-phases.png) are also available. Still images cannot establish that real voice, lip synchronization, or animation performance works.

![Offline render of the four current expressions](docs/images/03-current-emotions.png)

The following is a **historical screenshot from a real browser**. Its original filename carries the timestamp 2026-10-04 22:54:22; the time zone and exact build are unconfirmed. It shows the older `static-pixi` illustrated interface. Only the tab bar and developer tools were cropped out; the “connecting” indication and stopped subtitles remain. It does not represent the current running interface in this package or acceptance testing with a real model.

![Historical static-pixi browser interface, retaining the connecting and stopped states](docs/images/05-historical-browser.png)

See [image provenance](docs/images/PROVENANCE.md) for each image's mode, dimensions, source, and digest.

## Quick start

Run these commands from the root of the complete source tree. You need **Python 3.11–3.13 (including venv/ensurepip), Node.js 22.12+, and npm**. The commands below are for macOS/Linux; Windows has not been verified.

The ZIP includes the complete source, existing assets, and a precompiled `apps/web/dist` from the same version. It does not include `.venv` or `node_modules`. For initial dependency setup, the following tool uses the existing `requirements/dev.lock` and `package-lock.json` and requires access to the Python/npm package registries:

```sh
sh scripts/start --setup
```

After installation, use the standard entry point:

```sh
sh scripts/start
```

On the first run, choose `1` for the default live preset, `2` for the no-key offline rehearsal, or `0` to cancel. Later runs reuse the choice saved for this directory. If you previously chose offline mode, switch to the live preset with `sh scripts/start --preset live`. The live preset retains the original `gpt-6.1-sol` + Fast configuration, Google voice services, story mode, optional images, and `gpt-6-luna` image review. The first selection requires confirmation of the data-sharing and usage scope. If a new user has no `.env`, only a template without secrets is created; existing files are not overwritten. See [first run / upgrading](FIRST-RUN.md) for login, ADC, and missing-configuration handling.

On the computer running the service, open **http://127.0.0.1:8000**. If the port is in use, append `--port 8123`; press Ctrl+C to stop the service. A normal launch checks contracts and builds the frontend, but does not install dependencies automatically. Only `--setup` explicitly installs them, and you must start the service separately afterward. The current default character renderer is `code-native-review`; explicitly select the older full-frame illustrations with `sh scripts/start -- --character-renderer static-pixi`.

You may reuse an existing compatible Python environment, but do not relocate an old `.venv`. A new source directory also needs its own frontend dependency setup:

```sh
sh scripts/start --python /absolute/path/to/ready/python
```

For no-key audio and failure rehearsals:

```sh
sh scripts/start --preset offline
```

The page displays `OFFLINE · 离线排练` (“offline rehearsal”). Supported inputs include `你好` (“hello”), `不要拍我` (“don't photograph me”), `看照片` (“show the photo”), `照片里有什么` (“what's in the photo?”), `讲讲旅途` (“tell me about the trip”), `听雨` (“listen to the rain”), `暖灯` (“warm light”), and `/fail`. This route uses fixed text and prerecorded English speech synthesized with Flite/slt. The “按住演练输入” (“hold for rehearsal input”) control does not record audio or initiate open-ended model conversation. The original Mock entry points, `sh scripts/dev` and `sh scripts/dev --profile rehearsal`, remain available. Mock mode likewise does not read private configuration, call services, or capture a real microphone.

Once dependencies are ready, one command starts the application. Installation time on a new computer depends on its tools and network. **There is currently no complete timing evidence demonstrating installation in 15 minutes or less.**

## Connect real models, voice, and images

The standard `sh scripts/start` entry point passes the selected subscription preset to the existing `tools/live_provider.py`; it does not depend on the Codex CLI. `--dry-run` only shows the final arguments, and `--check` only performs local preflight checks. Neither starts a live service. The default `luna_tools` is the name of the native function-tool protocol; `--model` selects the actual conversation model. The normal route does not construct JEV and requires no JEV credentials. Only explicitly selecting `legacy_jev` in the original CLI uses the legacy compatibility route.

### 1. Reuse configuration and an existing login

Keep your existing private `.env`, Google ADC, and **MIRA's own login**. The examples below retain the user's original command setup: the project-root `.env`, the existing Google ADC path, and MIRA's default login store, without adding `--auth-store`. Keep an existing custom `--auth-store` path only if your original command already used one. A valid existing login does not need a new OAuth authorization. Do not copy another application's authentication or `source` an entire `.env` into your development environment. See the [first-run instructions](FIRST-RUN.md) for first-time login and the distinction between a fresh installation and an upgrade.

In a new environment, running `sh scripts/start --preset live` and choosing the live preset copies the public `.env.example` only if `.env` does not exist, saving it with owner-only read/write permissions. Existing configuration is left intact. The template contains the existing non-secret voice preset; you must fill in missing items such as your Google project yourself. See the [first-run instructions](FIRST-RUN.md) and [Google voice configuration](docs/development/GOOGLE_VOICE_CONFIGURATION.md). Configuration and ADC must be regular files owned by you, with read/write access restricted to you. Do not put keys, authentication files, pairing codes, or private conversations in the repository, screenshots, or recordings.

Common model choices, the Fast tier, voice/story/image switches, and the ADC path can be saved in `.env` fields named `MIRAAPP_*`. The template already contains the original preset; leave custom `MIRAAPP_AUTH_STORE` empty to retain the default login store. Existing configurations without these fields continue to use the original defaults, and explicit CLI arguments take precedence. Presets do not replace authorization for data sharing or usage. `--dry-run` reads these presets to display the final arguments. See the [first-run instructions](FIRST-RUN.md) for the field-to-switch mapping.

The following command checks only MIRA's local login record. It does not connect to the network, refresh credentials, or verify model eligibility:

```sh
.venv/bin/python tools/provider_login.py status
```

Only if MIRA genuinely has no login and you decide to grant it independent access, run the following command and follow the local instructions to authorize it on the official page:

```sh
.venv/bin/python tools/provider_login.py login
```

Place a custom store path before the subcommand, for example `tools/provider_login.py --auth-store /absolute/private/mira-session.json status`. The subscription route uses a non-public compatibility backend. Eligibility, quota, and long-term compatibility remain subject to the service provider.

### 2. Text + story

The following retains the currently selected `gpt-6.1-sol` and explicit Fast tier. Replace the example path with your own existing private configuration. `--authorize-provider-data` means you agree to send conversation data and controlled tool context to the selected OpenAI service.

```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
  --provider chatgpt_subscription --model gpt-6.1-sol --service-tier fast \
  --env-file /absolute/path/to/existing/.env \
  --authorize-provider-data --story
```

Remove `--story` to disable the authored storyline. Replacing `serve` with `check` in the same command checks only the selected configuration and declarations. It does not send model requests, read the login store, open the microphone, or establish that the account works. `live_provider.py` has no `--python` argument; to reuse an environment, replace `.venv/bin/python` at the start of the command. Fast is a requested service tier, not a guarantee of speed or the provider's actual metering. Select Standard explicitly with `--service-tier standard`.

### 3. Voice + story + optional new images

The live preset in `sh scripts/start` comes from the full command below, which the user has already used. It explicitly selects `gpt-6-luna` for image review. It uses the project-root `.env` and existing ADC. If your files are elsewhere, specify them with the entry point's `--env-file` / `--adc-file`, or change the corresponding paths below. Before running it, you must have agreed to external transmission of conversation data, Google's audio/text processing and service usage, and the scope of image data, subscription usage, and external transmission of variable fictional descriptions in this session. **Keep any lower limits you already have.** The packaging process did not read or migrate these files, reauthorize access, or change system or certificate settings.

```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
  --provider chatgpt_subscription --model gpt-6.1-sol --service-tier fast \
  --env-file .env --authorize-provider-data \
  --voice --adc-file "$HOME/.config/gcloud/application_default_credentials.json" \
  --authorize-google-voice-data-and-spend \
  --story --story-images \
  --authorize-story-image-data-to-openai \
  --authorize-story-image-subscription-usage \
  --authorize-story-image-custom-brief \
  --story-image-review-model gpt-6-luna
```

This command retains the original defaults: `luna_tools`, 20 TTS requests at no more than 30 seconds each, 120 seconds per STT RPC, and one image task. It does not increase those limits. The four image-enabling/authorization switches are `--story-images` and the three `--authorize-story-image-…` arguments. For voice + story only, remove those four switches and `--story-image-review-model gpt-6-luna`. `--story` alone does not enable image generation. The fixed lighthouse photo requires no image-service call.

On the Mac/service computer, continue to use the original voice entry point at **http://127.0.0.1:8000**. On a phone, open the `http://PRIVATE_IP:8000` address printed in the terminal; no pairing is required. By default, ordinary `serve` selects a private IPv4 address only when exactly one active physical Wi-Fi/Ethernet address can be confidently identified. If it cannot determine one, it prints a `WARNING` and continues serving locally. To specify an address, append only `--private-bind 192.168.2.13`, replacing it with the computer's current address. To serve only the local machine, append `--loopback-only`. Do not combine the two.

With the standard entry point, put networking and finite-budget arguments after the separator, for example `sh scripts/start -- --private-bind 192.168.2.13`, `sh scripts/start -- --loopback-only`, or `sh scripts/start -- --tts-requests 10`. The entry point passes through only supported networking, finite-budget, and renderer arguments. Continue using the original CLI for other routes and additional authorizations.

Phone access over HTTP strictly supports only text and enabled image features. The backend exposes no STT/TTS ports for that session, and voice cannot be enabled through sound preferences or WebSocket. Phone voice requires HTTPS that is already configured and trusted by both devices. See the [device guide](docs/development/PRIVATE-DEVICE-TESTING.md) for the existing TLS parameters and voice authorization. Manual pairing is optional and requires `--require-device-pairing`, `--device-pairing-dir`, and an exact `--device-origin`. HTTP pairing does not support voice either.

The image-generation route receives fictional scene descriptions that have been cleared for release; the separate image-reading route receives a normalized PNG, binding information, and review criteria. Variable descriptions are limited to 600 characters and support only environments or still lifes without people or animals. They do not include the full conversation, private memories, reference images, URLs, or file paths. Do not put private information in descriptions. Subscription image requests use `gpt-image-2` / `auto`. By default, the independent image-reading model follows the selected conversation model; you can explicitly select an authorized model with `--story-image-review-model`.

The official API is a separately selected route requiring your own API configuration and billing consent. A failed subscription request does not automatically switch to it:

```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
  --provider openai_api --model YOUR_API_MODEL \
  --env-file /absolute/path/to/existing/.env \
  --authorize-provider-data --authorize-api-billing --story
```

### Current default budgets

| Item | Default and boundaries |
|---|---|
| Subscription text | No local cap on model requests or text turns; optionally set finite limits with `--generation-requests N` and `--turns N` |
| Continuous listening / Google STT | No default local caps on duration, sends, starts, continuations, or shared STT request counts; each recognition RPC lasts at most 120 seconds and may be continued |
| Google TTS | 20 requests per process, at most 30 seconds each |
| New images | One task per process: one generation + at most one independent image-reading call, with no automatic retry |
| Official API text | Defaults to 20 generations and 20 turns |

There is no need to add `--local-unlimited`. Having no local cap does not mean the service is free, nor does it remove provider quotas, timeouts, concurrency limits, or queue limits. Continuous Google recognition continues to incur usage until the user stops it or a service limit/failure ends it. You can still set finite limits with options such as `--stt-requests`, `--listen-max-seconds`, and `--listen-max-utterances`. See `serve --help` for the full list.

Ordinary chat usually takes one model request. A tool turn uses at most one tool and two model requests. The completion notification after an image is actually displayed may also use one tool-free model continuation and the existing TTS allowance. Failures/cancellations do not refund finite counters. Restarting resets only local counters; these values are neither an account ledger nor hard monetary spending caps.

Anyone on the same trusted private network who can reach the address may consume the enabled allowances. All entry points share one provider runtime and the original budgets. **The limit of 16 independent temporary browser sessions is a resource limit, not a provider-request allowance. Adding devices does not multiply the 20-request TTS allowance or the one-image allowance.** Persistent modes using `--memory-db`, `--story-db`, or `--conversation-db` retain the original local single-operator and pairing boundaries; they do not expose LAN access by default. Ordinary `--story` uses a temporary story session.

## How voice and interruption work

1. The user clicks “开始自然对话” (“start natural conversation”) in the browser and grants microphone access. Audio is sent to Google STT; interim transcription is only a preview.
2. After local detection of valid speech followed by roughly 700 milliseconds of silence, the system enters a bounded finalization phase. Only a qualifying final transcript is submitted as a turn. Text can also be entered at any time.
3. The server generates a complete candidate response and controlled tool requests. Content confirmed as executable is handed to the frontend. Google TTS supplies the voice, alongside subtitles and the character's four states.
4. Voice interruption is enabled by default: new voice activity can first stop old and queued audio locally, then submit the new input. Old results must not reappear in later turns. The “打断回应，继续听我说” (“interrupt the reply and keep listening”) button keeps the microphone active. Global Stop/close releases the microphone and stops related unfinished tasks.

The design combines local stopping first with server-side cancellation/version checks so users do not have to wait for the network to reclaim their turn. The explicit interruption button is an understandable fallback. A conservative mode requiring manual confirmation of overlapping speech is also retained. Current volume/timing heuristics do not provide reliable speaker recognition or acoustic echo cancellation, so headphones are recommended. Actual audio tails, false triggers, and handling of new input still need real-device testing. Subtitle boundaries are deterministic and local, with no additional JEV calls. Mouth movement is state-based animation; phoneme synchronization has not been implemented.

“静音回应” (“mute replies”) turns off reply audio while continuing to show text, and the microphone may keep listening. “开启回应声音” (“enable reply audio”) restores sound starting with subsequent turns. This is an explicit text fallback; it is not proof that recovery from audio-service failures has been verified.

Ordinary input or reply-level interruption preserves background image tasks that have already been accepted. Targeted cancellation affects only the specified image/task. Global Stop has broader scope. States that were genuinely presented and reliable user input are retained; old output that was never presented cannot be treated as having happened.

## Character instructions and system structure

The model proposes actions. The application checks parameters, current assets, state prerequisites, and data/usage permissions. After the browser actually renders the result, it returns a presentation receipt. Saying “I've already given it to you” in dialogue is not a substitute for completing the action.

| Interaction goal | Structured tool / parameters |
|---|---|
| View the lighthouse photo | `show_photo(photo_id=trip_photo)` |
| Change outfit / hair accessory | `set_outfit`: `black_jacket`, `cream_inner_only`, `amber_raincoat`; `set_accessory`: `camera_clip`, `star_clip` |
| Expression / action | `set_emotion`: `normal`, `guarded`, `happy`, `shy`; `perform_action`: `raise_camera`, `return_camera` |
| Scene | `set_scene`: `cafe`, `rain_window` |
| Bounded story | `advance_story`: recognition, shared memories, invitation, acceptance/refusal, and other transitions, constrained by the current chapter state |
| Optional new image | `generate_story_image`; the corresponding `cancel_story_image` is offered only when a current task exists |

Available tools vary with the mode, budget, and current state. Xiahe is a fictional role the user chooses, not a verification of real-world identity. Shared memories are authored in advance. In MIRA's character backstory, she photographed the lighthouse on her own; their shared experience is choosing test prints after she returned to the café.

| Module | Purpose |
|---|---|
| `apps/web/src` | TypeScript frontend: scenes and code-driven character, audio/subtitles, input, stopping, and presentation receipts |
| `apps/api/src/mira/entrypoints/http` | FastAPI/WebSocket entry points, sessions, and device pairing |
| `apps/api/src/mira/application` | Session Actor, tool execution, background images, voice, and cancellation scheduling |
| `apps/api/src/mira/domain` | State, story, invitations, and facts about actual presentation, independent of HTTP/service SDKs |
| `apps/api/src/mira/adapters`, `bootstrap` | OpenAI/Google/storage adapters and explicit assembly |
| `tools`, `tests`, `specs` | Startup and recovery tools, partitioned offline checks, and behavioral specifications |

The full flow is: browser text/voice → Session Actor → selected model and bounded tools → state and permission checks → audio/subtitles/character/images → presentation receipt → next-turn context. Raw conversation and audio recording are off by default. Local memory, conversation archives, and character saves are enabled separately and explicitly; the application does not automatically save or learn a personality.

## Technology choices, models, and assets

| Choice | Purpose and trade-offs |
|---|---|
| TypeScript + code-native character, retaining a PixiJS fallback | The same editable parts express outfits, emotions, and actions, making cancellation manageable; character design, range of motion, and mouth animation remain limited |
| Python + FastAPI/WebSocket + per-session Actor | Keeps state, cancellation, and actual presentation in one control flow; currently targets local use and has not passed acceptance testing as a multi-user online service |
| Direct OpenAI subscription connection; explicitly selected official API alternative | These examples use `gpt-6.1-sol` + Fast; no automatic model switching, retries, or paid fallback |
| Google STT V2 `chirp_3` + `gemini-3.8-flash-tts` | Separates real recognition and synthesis to control input and playback; requires Google configuration, ADC, and usage authorization |
| Fixed assets + optional `gpt-image-2` | The fixed photo lets the main chapter proceed without waiting for generation; new images are generated asynchronously, and other chat capabilities remain available if generation fails |

The default character is drawn in code. See the [asset notes](apps/web/public/scene/ORIGINAL-ASSETS.md) and [AI_USAGE](AI_USAGE.md) for the AI-assisted original sources of the café, fixed lighthouse illustration, and historical character PNGs. Offline audio is synthesized locally with Flite/slt. For major dependencies, licenses, and third-party notices, see the [attribution inventory](docs/development/ATTRIBUTION-INVENTORY.md) and [third-party notices](docs/development/third-party-notices/README.md). This document does not choose an overall open-source license for the project.

## What has been verified, and what remains

The package retains the historical complete 13-lane offline release receipt from the 2012 baseline, together with impact evidence for each of the three subsequent fixes. The final default-LAN aggregate run was interrupted when providers was about 98% complete: ten successfully checked blocks were retained, and only providers was rerun, with 4,523 tests passing. This was not a fresh full release run for this package. There were also five independent runs involving two AI agents and 63 natural-language inputs in total. They used the real production prompts and actually executed programmatic tools and presentation receipts from the compiled frontend, while external providers, images, and TTS were simulated. These runs are not equivalent to acceptance testing of the real `gpt-6.1-sol` subscription/paid services, audio, or devices. Packaging checks covered recovery sources, compiled artifacts, launch arguments, documentation, and archive completeness. See the [verification notes](docs/submission/VERIFICATION.md) for detailed provenance, independent review, and scope.

| Current status / issue | Next step |
|---|---|
| The user confirmed basic chat, the fixed photo, and one generated image with a proactive notification; the feedback is not tied to an exact source digest | Record the actual version, command, and device during recording, and recheck the complete main flow |
| Voice and automatic/manual interruption have implementations and offline evidence; complete audible replies, audio tails, and echo have not been tested on the same version | Record with headphones: interrupt during speech, keep listening, receive a new reply, and verify late results do not reappear |
| The three outfits, expressions, and scenes have software paths; overall art, naturalness, and mobile behavior still need acceptance testing | Record at least three distinguishable expressions, two non-speaking states, and one environmental change |
| Phone voice requires already-trusted HTTPS; private-network access is pairing-free by default, with optional explicit manual pairing. A narrow-viewport screenshot does not prove the phone microphone works | Perform real-phone checks using the [two-device guide](docs/development/PRIVATE-DEVICE-TESTING.md) |
| Image-generation eligibility, latency, and review remain dependent on external services; passing review does not mean the character understands every pixel-level detail | Preserve actual failure feedback, verify the single notification after display, and avoid inferring image contents from its description |
| The user has recorded a video and will attach it separately by email; it is neither included nor independently checked here. Clean-install timing and the latest remote repository still need confirmation | Check the video against the [recording guide](docs/development/DEMO-RECORDING.md) and enter the actual file/address in the submission checklist |
| Phoneme-based lip sync, reliable acoustic echo cancellation, and complete long-term personality learning are unfinished | Address them individually according to their value to the experience; do not list them as completed capabilities |

## Time invested and another two weeks of development

The author roughly estimates total investment at **about 100 hours, including AI runtime**: design 5, backend 30, character 30, integration 10, rework and changes of approach 20, and testing 5 hours. These are rough effort estimates by area, not a claim of 100 hours of personal labor or a continuous 100-hour development period. Verifiable iteration records cover 2026-10-03 through 2026-10-07. See [AI_USAGE](AI_USAGE.md) for the full first-person retrospective.

With another two weeks of development, the recommendation is to finish acceptance testing of the current experience before expanding capabilities:

- **Days 1–3:** freeze the version and complete desktop/mobile voice, interruption, and failure-recovery testing. Record first-turn latency, audio tails, and actual service usage.
- **Days 4–7:** use recordings to improve expression readability, action transitions, subtitle pacing, and false voice triggers. Prioritize blockers in the main flow.
- **Days 8–10:** improve image queuing/cancellation feedback and clearly communicate the boundaries of the model's image understanding. Make topic changes and responses after refusals feel more natural within the story.
- **Days 11–14:** time a clean installation, run device regressions and long-session checks, and complete asset provenance, repeatable recording procedures, and the final release receipt.

This is a proposed development path, not completed work or a promised delivery date.
