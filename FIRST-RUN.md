# MIRA 首次使用与升级

本包是完整源码，已经整合图片审核、自然对话衔接和默认同 Wi-Fi 免配对三项修补。**不需要再运行旧补丁安装器。** 以下命令在解压后的源码根目录运行，适用于 macOS／Linux；Windows 尚未验证。

## 先判断：新装还是升级

- **之前已经跑通过真实对话／语音**：保留原有 `.env`、MIRA 登录和 Google ADC，直接看“已有用户升级”。无需为换源码重新登录、重新授权或新建证书。
- **第一次使用 MIRA**：先准备依赖，再体验无密钥版本；要使用真实服务时，再完成自己的配置、MIRA 登录和 Google 语音准备。

ZIP 包含源码、已有素材及同一冻结源码编译的 `apps/web/dist`；不包含 `.venv`、`node_modules`、私人 `.env`、登录文件或 ADC。预编译前端不代替 Python／Node 运行环境。

## 第一次：准备依赖与无密钥体验

先确认有 Python 3.11–3.13（含 venv／ensurepip）、Node.js 22.12+ 和 npm。首次安装依赖需要能访问 Python／npm 包注册表：

```sh
sh scripts/start --setup
sh scripts/start
```

`--setup` 显式调用现有 `tools/bootstrap.py`，按 `requirements/dev.lock` 和 `package-lock.json` 安装到本目录的 `.venv` 和 `node_modules`，完成后退出，不自动启动。然后单独运行 `sh scripts/start`。第一次会让你选：`1` 真实默认预设、`2` 离线排练、`0` 取消；以后复用本目录保存的选择。尚未准备真实服务时先选 `2`。启动会检查合同并重新构建前端，在这台电脑打开 http://127.0.0.1:8000；Ctrl+C 停止。

也可直接运行 `sh scripts/start --preset offline`。这是明确标记 `OFFLINE · 离线排练` 的固定内容，既不登录服务，也不采集真实麦克风或进行自由模型对话。原来的无密钥 Mock 入口 `sh scripts/dev` 和固定排练入口 `sh scripts/dev --profile rehearsal` 都保留。

全新电脑从安装工具到成功运行的 **≤15 分钟耗时尚未实测**；已有依赖时的一条命令启动不代表完成了这项计时。

## 第一次连接真实服务

### 1. 准备自己的私密配置

切换到真实预设并选择 `1`；即使之前选过离线，也用这一条：

```sh
sh scripts/start --preset live
```

确认真实预设后，启动器仅在根 `.env` 不存在时，以仅本人可读写的权限复制不含秘密的 `.env.example`；已有文件不覆盖。按缺项提示，在自己的本机编辑器里填写 `.env`，再运行同一入口。不要把私密配置发到聊天或加入源码包。当前真实订阅入口不要求 Codex CLI 或 JEV 密钥，也不会因缺少它们自动切换到官方付费 API。

公开模板还包含可编辑的常用启动预设。已有 `.env` 没这些字段时，继续使用相同默认值；不需要为升级覆盖原文件。日常改动可在自己的 `.env` 中保存，命令行明确选项优先：

| `.env` 字段 | 初始预设 |
|---|---|
| `MIRAAPP_PROVIDER` | `chatgpt_subscription`；其他路线使用原 CLI |
| `MIRAAPP_MODEL`／`MIRAAPP_SERVICE_TIER` | `gpt-6.1-sol`／`fast` |
| `MIRAAPP_VOICE`／`MIRAAPP_STORY`／`MIRAAPP_STORY_IMAGES` | 都为 `true`；可单独设为 `false` |
| `MIRAAPP_IMAGE_REVIEW_MODEL` | `gpt-6-luna` |
| `MIRAAPP_ADC_FILE` | `${HOME}/.config/gcloud/application_default_credentials.json` |
| `MIRAAPP_AUTH_STORE` | 留空，沿用 MIRA 默认登录存储；只有原本使用自定义存储才填写原路径 |

这些是启动选择，不是授权；真实服务的数据／用量范围仍由首次选择真实预设或 `--accept-live-profile` 明确接受。不要往 `.env` 添加授权键，也不要用 `source .env` 执行配置。Google 项目及语音的原字段继续由现有配置加载器读取。

Google 语音需要填写自己有权限的 `GOOGLE_CLOUD_PROJECT`；`GOOGLE_CLOUD_QUOTA_PROJECT` 按自己的项目设置填写，为可选字段。其他公开语音预设已写在模板：STT `chirp_3`／`us`／`cmn-Hans-CN`，TTS `gemini-3.8-flash-tts`／`global`／`aiplatform.googleapis.com`。声线必须明确配置；模板的 Gacrux 与风格说明见[Google 语音配置](docs/development/GOOGLE_VOICE_CONFIGURATION.md)。已有 Kore 选择不因升级自动更改。

这些字段只是配置，不证明 API 已启用、项目有权限、账单可用或模型有资格。新用户应在自己的 Google 项目确认 Speech-to-Text 与 Vertex AI 服务、用量和权限；本包不会替用户开服务、修改账单或扩大权限。

### 2. 检查 MIRA 自己的登录

```sh
.venv/bin/python tools/provider_login.py status
```

它只检查本机 MIRA 登录记录，不联网、不刷新，也不验证模型资格。若已有记录，先沿用它；换源码不要求再次 OAuth。

仅在确实没有 MIRA 登录，并决定授予 MIRA 独立订阅访问时，由本人运行：

```sh
.venv/bin/python tools/provider_login.py login
```

阅读终端提示，输入 `LOGIN` 后，在它给出的官方页面亲自完成一次性验证码授权。不要把验证码、密码或登录文件放进聊天、录屏或仓库。这是 MIRA 自己的登录，不复制其他应用的认证。该订阅兼容后端不是公开 API 合同，资格、配额与可用性仍由服务方决定。

用户原命令使用默认 MIRA 登录存储，不需要添加 `--auth-store`。仅当原来就使用自定义 MIRA 存储时，继续用原路径，例如 `tools/provider_login.py --auth-store /absolute/existing/mira-session.json status`，并在 live 命令中沿用同一路径。

### 3. 保留或准备 Google ADC

当前完整命令使用已有的：

```text
$HOME/.config/gcloud/application_default_credentials.json
```

如果此前语音已经正常工作，继续用这一份 ADC，或把 `--adc-file` 改为原有绝对路径；不要为了升级再登录或复制它。ADC 必须是本人拥有、仅本人可读写的普通文件，不能把它放进交付包。

首次使用且还没有 ADC 时，由本人按 [Google 本地 ADC 说明](https://cloud.google.com/docs/authentication/set-up-adc-local-dev-environment)完成所选账户的授权。已有 gcloud 工具时，相关本人操作是 `gcloud auth application-default login`。普通 gcloud 登录不等于 ADC 已就绪；项目权限、quota project 与实际语音可用性仍须分别确认。本次交付没有代办这些认证、权限或系统操作。

### 4. 启动真实文字、语音、剧情和图片

准备完成并选过真实预设后，常用命令是 `sh scripts/start`。首次选 `1` 表示接受该预设明确列出的数据处理与用量范围；之前保存了离线选择时，用 `sh scripts/start --preset live` 切换。已经决定使用这套预设时，也可显式运行 `sh scripts/start --accept-live-profile`。它不会替你完成登录或打开浏览器麦克风。

默认预设来自用户已经使用的以下完整命令；保留底层 CLI，方便查看与复现。它使用默认 MIRA 登录存储、项目 `.env`、已有 ADC，以及独立图片审核 `gpt-6-luna`：

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

默认 TTS 仍为 20 次／每次最多 30 秒，图片仍为 1 个任务，单次 STT RPC 最多 120 秒。订阅文字、本机连续聆听及共享 STT 次数没有本机固定次数上限；供应商配额、费用、超时和资源限制照常生效。已有更小预算继续通过原有限参数保留；不为启动或录屏扩大预算。

图片的四个启用／授权开关为 `--story-images` 与三个 `--authorize-story-image-…` 参数。`--story` 本身只开启临时剧情。固定灯塔照片无需图片服务；新图支持无人、无动物的虚构环境与静物。不要在图片描述里附私人资料。

真实预设下，`sh scripts/start --dry-run` 读取所选 `.env` 的启动预设并查看最终参数，不写配置或保存选择，不安装依赖或启动服务。`sh scripts/start --check` 同样读取预设与配置做本地校验，对登录／ADC 只查路径、属主及权限，不读 token／ADC 内容，不刷新、不联网、不启动；通过不等于真实服务可用。保存的选择若是离线，这两个命令也按离线处理，不读 `.env`；需要查看真实预设时追加 `--preset live`。底层完整命令也可以把 `serve` 改为 `check`，检查所选配置及声明，不调用模型或打开麦克风。

常用调整无需改源码：

```sh
sh scripts/start --env-file /absolute/path/to/existing/.env
sh scripts/start --port 8123
sh scripts/start --no-voice --no-story-images
sh scripts/start -- --loopback-only
```

`--python` 可指定已有兼容解释器，`--adc-file` 可指定原 ADC 路径；`--model`、`--service-tier`、`--story-image-review-model` 可显式覆盖 `.env` 里的模型选项。`--voice`／`--no-voice`、`--story`／`--no-story`、`--story-images`／`--no-story-images` 可覆盖相应预设。支持的有限预算、网络与 renderer 参数放在 `--` 后，例如 `sh scripts/start -- --tts-requests 10` 保留更小预算；入口不透传额外路线或授权开关。官方 API 等其他路线仍须用原 `live_provider.py` 命令及独立授权。

## 已有用户升级

1. 停掉旧服务，保留旧源码和私密文件，将新 ZIP 解压到独立目录；不要用旧补丁覆盖新包。
2. 在新目录运行 `sh scripts/start --setup`，或复用兼容的现有 Python 解释器。不要搬迁旧 `.venv`；新目录仍需自己的前端依赖。常用入口可以加 `--python /absolute/path/to/ready/python`；直接用 `live_provider.py` 时则替换命令开头的解释器，它没有 `--python` 参数。
3. 继续指向原有 `.env` 和 ADC：若 `.env` 留在旧目录，使用 `sh scripts/start --env-file /absolute/path/to/existing/.env`，必要时加原 `--adc-file`。已有 MIRA 默认登录位于应用的私密用户存储，不因源码目录改变而需要重新登录；原自定义 `--auth-store` 继续沿用。
4. 在新目录首次选择真实预设，或加 `--accept-live-profile` 明确接受该预设后启动。核对终端实际地址；先在 Mac／服务电脑试基本文字和固定照片，再按需要开启麦克风。新图默认只有一个任务，不用重复生成来测试启动。

持久记忆、会话档案和角色存档也继续使用原有路径、授权及本机配对，不自动迁移或开放给 LAN。普通 `--story` 是临时剧情，不等于启用持久库。

## Mac 和同一 Wi-Fi 手机怎么打开

普通 `serve` 默认选择唯一可确认的活动物理 Wi-Fi／以太网私网 IPv4：

- **Mac／服务电脑**：打开 `http://127.0.0.1:8000`，原语音功能保留。真实麦克风仍需本人点击并允许浏览器使用。
- **手机**：打开终端打印的 `http://PRIVATE_IP:8000`，默认无需配对，是独立临时会话。手机上的 127.0.0.1 指向手机本身。
- **手机 HTTP 没有语音**：既不能录音，也不会合成回应声音；后端不为该入口提供 STT／TTS，不能靠隐藏按钮或声音偏好绕过。手机语音仍需已有、两端都信任的 HTTPS 和原语音授权。

若多网卡或无法确认地址，终端会打印 `WARNING` 和“局域网未启用，仅本机”，本机仍能使用。确认电脑当前私网 IP 后，可用 `sh scripts/start -- --private-bind 192.168.2.13`；不需要手机访问则用 `sh scripts/start -- --loopback-only`。使用底层完整命令时直接追加相应参数。不要把这两项合用，也不要填写通配或公网地址。

只在可信私人网络使用；能访问地址的人可能消耗已启用额度。16 个浏览器身份／临时会话是本机资源上限，所有入口共享同一个 provider runtime 与原预算，TTS 20 次、图片 1 次不会按设备翻倍。HTTP 内容未加密，免配对不等于账号验证。

手动配对为可选路线：使用 `--require-device-pairing`、已有私密 `--device-pairing-dir`、精确 `--device-origin` 和相应网络参数。HTTP 配对同样只支持文字。已有可信 HTTPS、持久库边界及详细操作见[设备指南](docs/development/PRIVATE-DEVICE-TESTING.md)；不需要为本包安装证书、绕过证书警告或调整系统网络。

## 缺项时怎么处理

| 现象 | 下一步 |
|---|---|
| 找不到 Python、venv、Node 或 npm | 先准备上述版本的工具，再运行 bootstrap；包内不自带它们 |
| 提示缺少 Python／TypeScript／esbuild 依赖 | 在新源码根目录完成 bootstrap；仅有预编译 dist 不代替依赖 |
| `.env` 不存在或配置缺项 | 首次选择真实预设后按提示填写新建模板；老用户用 `--env-file` 指向原文件，不覆盖旧配置 |
| 提示需要 MIRA 登录 | 先检查 `provider_login.py status`；确实没有记录时才本人完成登录 |
| Google ADC／权限／项目不可用 | 保留错误提示，核对自己选择的 ADC、project 与 quota project；配置检查不能证明服务资格 |
| 手机找不到页面 | 核对终端本次地址、两台设备所在网络及是否打印了本机回退警告；地址可达性尚需实际设备确认 |
| 手机 HTTP 没有麦克风或声音 | 这是当前边界；用 Mac 的 127.0.0.1 语音入口，或使用已有可信 HTTPS |
| 图片或声音额度耗尽 | 保留实际反馈，继续可用的文字／固定照片；不要把资源上限当 provider 额度，也不要自动提高预算 |

真实服务不可用时，可先用 `sh scripts/dev` 或固定离线排练继续检查界面；保留对应模式标识，不能记为真实模型／语音验收。

演示视频随邮件另附（用户已录制，本包未包含且未代验）。视频是否覆盖 3–5 分钟及必需片段、同版本手机、真实可听语音、声学打断与连续会话仍待实际核对。录制步骤见[录制指南](docs/development/DEMO-RECORDING.md)，已验证范围见[验证说明](docs/submission/VERIFICATION.md)。
