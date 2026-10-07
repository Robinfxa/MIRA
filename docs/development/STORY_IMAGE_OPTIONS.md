# 可选剧情图片：订阅优先，保留显式 API

这是离线兼容实现，尚未验证账户资格、订阅用量、真实图像与像素审核、设备呈现或账单。普通 `--story` 仍然不生图，图片模型配置也不会自行开启图片。订阅优先不等于免费生图保证；账户是否可用及实际用量仍未知，失败不会自动使用付费 API。

本页完整命令用于支持 `--action-review-mode luna_tools` 的本版源码。工具由 Luna 选择，本机检查授权、参数、资源、当前状态及预算；生成后的 PNG 仍须另一次明确授权的 Luna 读图检查。迁移工具调用不会取消读图或扩大图片预算。若 CLI 不认识该选项，说明运行的入口不匹配本页，先核对同包 START-HERE、源码版本与实际命令。

## 本次运行是否开放动态图片

现有 `live_provider.py check` 及 `serve` 启动输出的 `story_images.readiness`
区分动态 custom-brief 工具和旧固定 catalog。检查不调用服务、不读取认证，
`scope=configuration_only`、`account_access=not_checked` 始终保留；
`enabled` 只表示本机声明齐全，不能证明订阅资格或图片已能生成。

`story_images.startup_requested` 逐项记录实际 CLI 选择：`story`、`story_images`、
`image_data`、`subscription_usage`、`custom_brief`、`api_spend`。这里都是布尔值，
不记录路径或凭据；没有传入的同意不会由程序补齐。这是启动请求的声明，
不是运行中图片已启用、已调用、已审核或已展示的证明。

- `disabled / feature_disabled`：未打开 `--story-images`。
- `missing_consent`：`missing_consents` 只列 `image_data`、`subscription_usage`、
  `api_spend`、`custom_brief` 中缺少的同意。动态工具需要已有 `--story` 及
  `--story-images --authorize-story-image-data-to-openai`
  `--authorize-story-image-subscription-usage --authorize-story-image-custom-brief`。
  这些参数只在操作者确实同意对应外传与用量后追加，不能自动补上。
- `enabled / configured`：动态工具配置具备；实际每次请求仍受原有预算、审核、
  当前剧情及取消边界限制。
- `legacy_catalog_only / legacy_mode`：明确选择旧模式，未开放可变 brief 工具。
- `budget_exhausted / dialogue_budget`：声明的生成调用限额不足一次工具选择加一次续答。
- `configuration_unavailable`：核对外层 `missing_fields / invalid_fields`；不回显值。

导出日志新增封闭 `image_readiness` 事件。`phase=definitions` 是 Actor 本轮候选能力；
`phase=request` 是适配器按原对话预算生成的最终工具请求体投影，
`generation_tool/fixed_photo_tool=advertised|absent` 对应该请求体实际工具表，
不是已发送或已成功的收据。`continuation` 明确没有后续工具。
`budget_exhausted` 的原因区分 `image_attempts/image_bytes/image_cost/process_budget/dialogue_budget`；
`process_busy` 是已有任务尚未结束。跨会话不会使耗尽的进程图片额度重新可用。

`phase=operation` 可记录最近本会话生成/独立读图端口返回或抛错：
`provider_observation=generation_error|review_error`，当次失败记 `provider_error`。
它只证明对应端口操作失败，不说明账户一定没有资格，也不猜远端错误内容。
本地解码失败仍是 `operation_failed`；返回图片不等于通过审核或呈现。
字段仅含固定枚举/计数，无 brief、正文、异常文本、路径、密钥或原始响应。
旧日志没有这些字段时，不能反推出当时图片未开启。所有观察都不增加额度、
重试、自动换路或在每句对话加入功能说明。

按这五种情况分别判断，不能统称「订阅生图失败」：

1. `runtime_disabled`、`generation_tool=absent`、图片次数/限额均为 `0`，且
   `provider_observation=not_observed`：当前观察的运行时没有动态图片能力。
   `fixed_photo_tool=advertised` 只说明固定照片工具可选。若没有准确版本和启动命令，
   不能进一步断言是漏参数、跑错目录或账户问题。
2. `missing_consent`：缺的是本机明确同意。按列出的字段核对，只有操作者实际
   同意后才补参数；这不是服务商权限被拒绝。
3. `budget_exhausted / process_budget`：该进程预算已耗尽。新会话的
   `image_attempts=0` 仍可能与 `process_remaining_jobs=0` 同时出现，不能重试
   或开新会话绕过。重启会重置本机预算，但不会重置供应商用量。
4. `configured_not_live_verified`、`internal_unverified`、
   `subscription_entitlement=not_checked`：本机配置具备，私有后端和账户资格
   仍未知。离线测试、登录成功或普通聊天成功都不能补成图片资格已通过。
5. `phase=operation` 且 `generation_error` 或 `review_error`：已有对应端口
   尝试失败。它可能发生在认证、网络、响应处理等不同阶段，不证明远端一定
   收到请求或订阅服务本身故障。仅有 `operation_failed` 也可能是本机解码失败。

复测时保留同包版本、脱敏启动声明与本次 `image_readiness` 事件即可；不要提供
认证文件、原始请求/响应或完整环境文件。先看到动态工具实际进入本次请求体，
再区分生成、读图与呈现回执，模型文字承诺不代替任何一步。

## 订阅路线

从已准备依赖的项目根目录运行下面这一条完整命令。先替换两个绝对路径；已有
自选 MIRA 登录存储时追加原 `--auth-store /absolute/private/mira-session.json`。
只有对话、Google 语音、图片数据、可变 brief 和订阅用量均已明确同意，且已有
MIRA 登录与 Google 配置/ADC 时才执行。Google 配置须有明确项目及本版支持的
TTS 声线（`Kore` 或 `Gacrux`）；不要把真实配置写进命令或诊断。已有更小预算
继续用更小值。

<!-- subscription-voice-story-image-start -->
```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
  --provider chatgpt_subscription --model gpt-6-luna \
  --action-review-mode luna_tools \
  --env-file /absolute/private/mira.env --authorize-provider-data \
  --voice --adc-file /absolute/private/application_default_credentials.json \
  --authorize-google-voice-data-and-spend \
  --stt-requests 10 --tts-requests 20 --stt-max-seconds 120 --tts-max-seconds 30 \
  --story --story-images --story-image-review-model gpt-6-luna \
  --story-image-max-attempts 1 \
  --authorize-story-image-data-to-openai \
  --authorize-story-image-subscription-usage \
  --authorize-story-image-custom-brief
```
<!-- subscription-voice-story-image-end -->

`.venv/bin/python` 可替换为已准备好的兼容 Python 绝对路径，入口没有 `--python`
参数。启动不会自动打开麦克风，仍须在浏览器启用。Google 语音授权含服务用量，
不是免费语音承诺。将同一命令中的 `serve` 改为 `check` 可核对全部声明；
检查会验证环境配置及 ADC 文件元数据，但不读取 ADC 内容、不刷新登录、
不请求模型或启动语音。

这会选择 `chatgpt_subscription` 图片路线，请求固定为 `gpt-image-2`、`auto`、一张 1024×1024 不透明 PNG。订阅兼容服务若实际返回 1024×1024、1536×1024 或 1024×1536，仍须通过完整解码和独立审核；按真实宽高审核、保存并显示，不拉伸为方图。其他尺寸仍拒绝，API 路线仍遵守其方图请求。上例明确选 Luna 做独立实际像素审核；省略 `--story-image-review-model` 时沿用当前 `--model`。模型标识有效不代表该账户/兼容接口支持读图。生成和审核都走订阅兼容路线，任何一项失败都不会改用 API。

- 图片数据同意：OpenAI Codex Images 内部兼容接口接收已释放的有限虚构场景说明；独立 Codex Responses 请求接收规范化 PNG、绑定信息和审核标准。
- 订阅用量同意：明确允许上述生成与审核使用订阅路线。项目不知道实际 quota 消耗，也不保证此私有兼容调用属于任何公开套餐权益。
- 默认每进程只准入 1 个图片任务，没有自动重试；图片和读图不会同时借用 API key。
- 不填写美元规划金额或远端读图 token 上限。订阅分支拒绝这些不适用参数，不把本机限制伪称套餐上限。

订阅图片只接收已有 MIRA `CodexOAuthCredentialSource`，不会复制 Codex/Hermes 登录文件，不新增登录或凭据发现。`serve` 在所有必要同意通过后才构造这个无副作用 source，生成与读图共享它；文字同为订阅时也复用它。只在未来实际用户操作调用 `get_credentials` 时读取既有 MIRA store。关闭、拒绝或 `check` 不构造/读取这个 source。订阅图片分支不访问 API settings/key；本机显式 env 仍由既有统一 loader 解析，并非新增按路线过滤整个配置文件的机制。

如果文字选择 `openai_api`，必须明确写 `--story-image-provider chatgpt_subscription` 或 `openai_api`。这使额外订阅认证路线成为显式选择，不根据现有 API key 自动发现另一条认证路线。

## 保留的 API 路线

`--story-image-provider openai_api` 继续要求明确图片模型、独立读图模型、`low`/`medium`/`high` quality、图片数据/API花费同意和正数规划预留。API key 只由现有 loader 的 `services.openai.api_key` 提供，不接受 CLI key。文字的 API 同意不能替代图片同意。

以下是明确选择 API 文字和动态图片的完整备用命令；替换模型标识和环境路径，
仅在另行同意 API 计费后运行。金额是本机规划数字，不是定价预测：

```sh
PYTHONPATH=apps/api/src .venv/bin/python tools/live_provider.py serve \
  --provider openai_api --model YOUR_API_TEXT_MODEL \
  --action-review-mode luna_tools \
  --env-file /absolute/private/mira.env \
  --authorize-provider-data --authorize-api-billing \
  --story --story-images \
  --story-image-provider openai_api \
  --story-image-model gpt-image-EXPLICIT-MODEL \
  --story-image-review-model EXPLICIT-VISION-MODEL \
  --story-image-quality low \
  --authorize-story-image-data-to-openai \
  --authorize-story-image-custom-brief \
  --authorize-story-image-api-spend \
  --story-image-reservation-microusd 60000 \
  --story-image-total-reservation-microusd 100000
```

`microusd` 是百万分之一美元；以上 US$0.06/US$0.10 仅作为准入规划，不是服务商强制限额。API 独立读图保留 128–512 输出 token 请求上限，默认 512。API 从不自动改用订阅，订阅从不自动改用 API。现有 key 或文字成功都不证明图片能力可用。

## 声明与资源边界

`check` 只检查声明，不构造适配器、credential source 或 HTTP client，不读取认证 store，不解开 API secret，不调用模型，也不打开记忆库。

- `disabled`：图片默认关闭，图片分支无配置/凭据读取。
- `unavailable`：缺失/非法项只返回固定字段名，check 退出 2；不回显值、路径或密钥。
- `configured_not_live_verified`：声明齐全，仍是 `live_verified=false`、`inference=not_run`、`account_access=not_checked`。

订阅额外输出 `compatibility=internal_unverified`、`subscription_entitlement=not_checked`、`subscription_quota_consumption=unknown`、`planning_reservation_status=not_applicable`；两个美元字段为 null。`review_max_output_tokens=null`、`review_remote_token_cap=unavailable`：私有 Responses 接口没有在本实现请求或验证远端 token 硬上限。本地审核 JSON 最多 8192 字节，并有响应字节/时限限制；这不限制远端实际计算或订阅消耗。

## 所有会话共享的有限预算

`--story-image-max-attempts` 仍为每进程 1–4 次获准任务，默认 1；每次最多一次图片生成和一次独立读图，无自动重试。整个生成→解码→读图只允许一个任务在途，其他请求直接拒绝。取消后要等底层协程结束才释放占用；重新创建/关闭会话不会重置进程次数或预留。重启进程会重置本机计数，计数并非账户级持久额度。

每个图片产物仍最多 8388608 字节，进程字节预留默认 8388608、最多 33554432。生成响应默认/最多 12000000 字节，读图响应默认/最多 65536 字节。完整任务默认 120 秒，生成 90 秒，读图 45 秒；各项都必须有限、大于 0 且不超过 120 秒，完整任务可能先到期。未提高任何原有限额。

第一次 provider await 前保守预留任务次数、读图机会和完整图片上限字节。失败、取消、解码失败、未知远端结果或尚未 HTTP dispatch 的失败均不退款。API 另外预留操作人指定规划金额；订阅仅在内部通用准入使用零 cost units，对外显示不适用。最早耗尽的限制阻止下次任务，增加尝试次数不自动增加字节/金额预算。所有限制都不是美元、套餐额度、远端取消或远端 token 保证。

默认只允许已释放虚构场景。单独授权 custom brief 后，另接收本轮至多 600 个
Unicode 字符的虚构环境/物件描述；不自动附加聊天全文、私人记忆、隐藏人物设定
或参考图片，也不开放任意路径/URL。字符串检查不能证明语义合格，生成后的实际
像素检查仍须通过全部绑定及内容条件。软件兼容和合成 tests 不能代替真实图片与
独立像素审查、服务权限、内容质量和设备验收。
