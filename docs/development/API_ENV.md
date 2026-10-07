# MIRA 开发 API 环境：一次准备，按能力接入

**版本：ENV-02 / foundation 0.4.1 · 2026-10-03。**
本次落实用户“设计开发env，把需要的API准备好”的要求。范围是配置、私密模板、离线检查与元数据探测；没有代办账户开通、读取私人凭据、实际推理、真实语音或生图。
架构G01–G06和原50小时T0不变。本切片不是一键自主开发器；下一步仍要实现live adapters和产品任务。

## 1. 三个环境，不混用

| 环境 | 接收什么 | 不接收什么 |
|---|---|---|
| 写代码的Codex | 当前任务、项目源码、离线测试权限、自己的受支持登录 | 整份运行时.env、用户其他仓库、产品角色线程 |
| MIRA服务进程 | 原loader产生的Settings、对应服务必要凭据、当前ContextPacket | 编程Agent的完整工具集和未呈现输出历史 |
| 测试进程 | 显式Settings、fixture、临时目录、合成transport | 真正模型调用、默认账号、共享私密HAR |

`.env`不是Codex原生配置。不要用`source .env`把所有服务密钥导出给开发Agent。产品原生Codex进程应使用独立任务环境、受限工具和重新构建的上下文；这项隔离的真实adapter尚未实现，文字约定不等于OS沙箱。
离线quality runner现在剥离常用服务key、token和Google凭据指针；直接运行pytest时仍须保持测试本身使用合成输入。移除env不禁止程序读取同一用户的磁盘认证缓存，严格隔离需实际沙箱与文件权限。

## 2. 开发所需API清单

| 能力 | 本版准备路线 | 凭据／字段 | 必须另验 |
|---|---|---|---|
| 主LLM | Codex订阅优先；原生／已获准本机网关二选一；标准API备用 | Codex受支持登录，或网关客户端key；精确text_model | G03完整候选、取消、输出终态与真实审核 |
| 图片生成 | 同样优先订阅carrier，独立于text配置 | image_model与实际产物接口；不是只有一句“生成了” | 真实图像、取消迟到、隔离、D-M |
| D-M读图 | 图像输入的独立审查请求 | vision_model及当前允许图像 | 实际像素输入、unknown、内容绑定；不可自我批准 |
| Input/Output Decision | JEV/TypeSafe | TYPESAFE_API_KEY、固定model | 中文、原语映射、超时与拒绝；不能由文本模型代替读图 |
| ASR | **已批准 MVP 路线** Google Speech-to-Text V2 | 项目、quota项目、ADC、区域、model、locale | 启用与IAM、gRPC、实际语言／区域、流式转写 |
| TTS | **已批准 MVP 路线** Gemini 3.8 Flash TTS on Gemini Enterprise Agent Platform (Preview) | 同项目/ADC，独立locale与voice；`aiplatform.googleapis.com` | 实际项目可用性、真实合成、播放、打断、同步字幕 |
| 可替换标准API | OpenAI Responses/Image API | 安全设置流程提供的OPENAI_API_KEY | 明确付费预算、每项能力独立验收；不自动回退 |

Google STT V2是为减少首轮身份系统而提出的开发默认，不宣称此前ADR已经锁定ASR供应商，也不改工厂。已有可用ASR不必为了此模板迁移。
Hindsight不是当前P0前置；不为了开发env另外购买记忆、向量库或视频服务。

**外部文档核查：**Codex区分订阅登录与API-key计费[S1]，内置图片使用Codex用量[S2]；JEV使用Bearer与`/v1/systemone`，有模型目录[S3]；Google STT V2与Gemini Enterprise TTS有各自API合同，语言、地区、账单及IAM须按实际项目验证[S5–S8]。这些事实不是本账户验证。


## 2.1 已批准的 MVP Provider Matrix

本轮将开发栈收敛为以下五项能力：

| 能力 | Provider 家族 | 默认承载 | 备用／边界 |
|---|---|---|---|
| 主 LLM | OpenAI | Codex subscription carrier 优先 | 显式 `openai_api` 可替换；不自动付费回退 |
| 图片生成 | OpenAI | Codex / OpenAI image capability | 最终图片仍需隔离、D-M与当前许可 |
| D-M 实际读图 | OpenAI | 视觉能力的独立请求 | 不接受生成器自评替代实际像素检查 |
| ASR | Google Cloud | Speech-to-Text V2 | 真实项目／区域／语言和流式行为需实测 |
| TTS | Gemini Enterprise Agent Platform (Preview) | `gemini-3.8-flash-tts` over `aiplatform.googleapis.com` | 真实 voice、区域、取消与设备尾部需实测 |

`Input/Output Decision` 仍按已批准 G05 保留 JEV/TypeSafe 为当前独立判断路线；本次 provider 收敛没有把它悄悄并入主 LLM。若后续要将 DecisionBackend 也改为 OpenAI，需要单独记录该后端变更及中文判断对照。

这里的“OpenAI”是能力家族，“Codex subscription / openai_api”是承载与计费路线。三项能力可以共享同一供应商家族，但仍分别配置模型与验收；文本成功不证明生图或视觉检查可用。

## 3. 文件与入口

```text
.env.development.example                 # 公开空模板，不自动加载
.env                                     # 本机私密，gitignore，init创建0600
config/profiles/development.toml         # 非敏感差分，应用仍mock
apps/api/src/mira/config/service_settings.py # 强类型参数
apps/api/src/mira/config/loader.py        # 唯一env入口与明确别名
 tools/api_env.py                        # init / check / metadata
 tools/api_environment.py                # 纯检查＋有界GET，无推理
 tests/unit/test_service_configuration.py
 tests/unit/test_api_environment.py      # 独立env lane，合成transport
```

依赖通过现有`tools/bootstrap.py`显式安装；当前 Google、HTTP、认证辅助与构建依赖已在 requirements 锁文件中固定。安装依赖不代表允许真实服务调用；各适配器仍需要独立准入。

```bash
# 项目根目录，先具有已声明的Python开发依赖
python tools/api_env.py init
# 本机编辑私密.env，只填必要项；不要发给聊天或加入commit
python tools/api_env.py check
```

`init`不覆盖任何既有目标，也不跟随目标符号链接。POSIX设置0600；Windows权限还需ACL管理，不能把chmod语义当跨平台保证。
已有.env只按空模板补字段，不删除原文件。可以为开发检查显式选择仓库外私密env：`--env-file /absolute/private/path.env`。
当前 `sh scripts/dev` 是隔离的 Mock/回放演示入口，不读取根 `.env` 或进程中的应用配置，也不自动安装依赖。需要已有环境时可传 `--python /path/to/python`。显式配置感知入口 `python -m mira` 才通过 loader 读取根 `.env`；仓库外文件仍须由服务装配显式传给 `load_settings(env_file=...)`，dev 脚本没有私密 env 文件参数。配置字段齐全不会解除真实服务的准入守卫。

## 4. 各项怎样一次性准备

### 4.1 Codex订阅

用户本人通过现有Codex支持的登录流程确认账户及workspace；CLI可在本地运行`codex login status`，无登录时才`codex login`。[S1]
不要复制auth.json或OAuth token进MIRA配置。开发工具只检查可执行文件是否可发现，不自动执行Codex、不读取认证缓存、不创建新会话。
将实际选定的主生成、图片、视觉型号分别登记到`MIRA_SERVICES__CODEX__*MODEL`。这些是能力记录，不保证同一个carrier允许对每项显式选型；不可配置的内置图像型号需按实际返回登记。

原生是当前安全起点，**没有否认已有CLIProxyAPI等实现**：本机网关是已保留的替代carrier。选择网关时明确设置routes，填loopback base URL、网关自己的应用key和三种model，并确认IC-01及访问范围后设`ACCESS_CONFIRMED=true`。这个位只是应用的准入记录，不是法律或供应商授权证明。
本工具不自动安装网关、不提取登录token、不轮换账号、不选择其他人的网关。为减少误发，URL目前只接受数字loopback＋明确端口＋`/v1`；跨机器服务需要独立设计准入，而不是绕过校验。

### 4.2 JEV

由用户在TypeSafe自己的控制台取得该服务key，放在本机`TYPESAFE_API_KEY`或其MIRA具名等价字段，两者同层不写冲突值。[S3]
固定model从账户实际目录选择。不要把示例中`latest`当冻结生产版本，也不要认为JSON合法等于中文行为合格。
评价入口是POST `/v1/systemone`；本版工具**只会GET `/v1/models`**，不会评价用户数据。

### 4.3 Google语音

本地开发优先由用户设置ADC，不下载并塞进仓库一份service-account私钥。[S6]
当前精确TTS模型是Gemini Enterprise Agent Platform预览模型，通过Vertex AI Generative AI的`aiplatform.googleapis.com`在`global`位置调用；它不是Cloud Text-to-Speech模型。[S8]
在有权限的项目内，按官方流程确认Speech-to-Text与Vertex AI API已经启用、账单和最小IAM可用；命令示例：

```bash
# 用户本人操作；不是本工具自动执行的setup
# 项目和计费未确认前，不执行启用或真实推理
 gcloud auth application-default login
 gcloud services enable speech.googleapis.com aiplatform.googleapis.com --project=YOUR_PROJECT_ID
```

`texttospeech.googleapis.com`只用于另行选择的Cloud Text-to-Speech模型；不要用它来准备此处的`gemini-3.8-flash-tts`路线。

项目与quota项目填写到私密env。ADC登录与gcloud当前账户可能不同；不能仅凭gcloud登录成功判断SDK已可调用。[S6]
建议初始ASR配置`chirp_3 / cmn-Hans-CN / us`，TTS独立用`cmn-CN`，声线留空直到实际可用列表确认。[S4–S5, S8]
模板中的项目/地区/声线是配置，**ADC、IAM和语音调用均未探测**。本工具不读取Google认证文件，也不通过metadata命令假装验证音频。
如果由部署环境使用`GOOGLE_APPLICATION_CREDENTIALS`，它属于Google SDK的进程配置；本loader不会把dotenv里的任意变量写入进程环境，不能只填在.env里就声称ADC生效。

### 4.4 标准API备用

OpenAI key使用本轮ChatGPT安全设置入口或组织已有安全发放流程，密钥不经过对话正文。本机注入`OPENAI_API_KEY`即可被唯一loader识别；存在key不代表选择了该路线，更不代表付费授权。
不把备用key加到开发Codex的全局环境，以免改变它的认证/计费路径；服务进程仅取得自己需要的值。
本版不自动设置`allow_paid_api=true`，也不创建付费项目或购买额度。

## 5. 准备检查怎么读

`check`只检查当前实际配置。字段缺失退出2；字段齐全退出0，但输出始终包含`live_ready=false`与`inference_verified=not_run`。
原生Codex/Google认证标为managed-not-checked；输入了一个token只能标为supplied，不是verified。
`core_fields_complete`仅覆盖text/review/asr/tts字段，image/vision分别列明；不允许拿它替代图片D-M。
`adapter`只表示所选能力路线上是否存在明确的开发入口，与字段完整、登录／账户权限、真实推理和默认应用工厂装配分开：Codex原生text与JEV review指向`tools/live_dev.py`；Google STT V2与Gemini TTS指向`tools/live_voice.py`，均标为`implemented_in_explicit_development_entry`，同时`default_provider_factory_composed=false`。这只是代码存在及有界开发入口的状态；报告仍将`account_access`标成`not_run`，始终不声称已登录或验证服务。gateway／OpenAI通用text、image、vision仍标为`not_implemented`，不能因为某个Codex路线有实现就整体翻转。
显式传入`--env-file`但文件不存在时，check返回固定原因码`explicit_env_file_missing`和选择正确文件／初始化项目模板的下一步；不会退回读取项目根`.env`，也不回显路径、文件内容或原始校验错误。
缺什么就补什么；可选图片缺项不能阻止离线语音播放器任务。字段齐全与存在显式开发入口都不表示服务已就绪；完整live交付仍要有对应账号权限、明确准入和真实产品验收。

## 6. 有边界的元数据检查

先在用户确认访问的范围内填好相应key，再显式允许**本次目录GET**：

```bash
MIRA_SERVICES__PROBE__ALLOW_METADATA=true \
MIRA_SERVICES__PROBE__MAX_REQUESTS=1 \
python tools/api_env.py metadata --service jev
```

同样支持`--service gateway`或`--service openai`，一次最多三项，所有所选项先验证配置后才建HTTP客户端。默认不启用；普通check、full和release不会调用它。
只请求固定服务`/models`，不follow redirect、不读环境代理、不retry；有每操作空闲超时、响应迭代期限检查和256KiB结果限制。同步网络阻塞可能使墙钟超过迭代期限，不宣称这是硬实时总截止。
返回只保留状态、数量、所配置model是否出现在目录；不打印key、headers、返回正文或账户资料。错误保留401/403/429/服务失败/timeout/非法结果等区别。压缩响应拒绝；这不是通用HTTP网关。
目录成功退出0只表示这次目录合同成立；**不保证模型可推理、不保证生图、不保证订阅额度、不证明账户授权范围**。
`max_requests`是本次工具的GET次数上限，不是账户费用硬封顶，也不能代替未来真实调用共享预算。

## 7. Codex接手规则

1. 先读当前.env模板与本页，不读取或打印私密文件；检查只输出经过筛选的状态。显式`--env-file`必须指向现存文件；如果报`explicit_env_file_missing`，校正所选文件，或省略该选项使用项目根`.env`，需要新模板时先运行`init`。
2. 默认离线开发，按env/对应模块运行定向测试；metadata须有本次授权。
3. 别名、凭据与参数只通过loader；adapter接收不可变具名设置，不自行读环境变量。
4. 默认`create_providers`对live启动保持fail-closed；Codex/JEV/Google的显式开发入口不代表已接入默认运行时。不能删除准入保护或让FixtureReview批准live输出来冒充接通。
5. API真实小探针需后续明确调用范围和费用预算，并使用专门最小化日志；不要套会保存完整输出的record_check记录私人请求。
6. 下一步只实现既定产品适配器和音频/角色任务，不继续扩建env管理平台。

## 8. 外部来源（2026-10-03核查，不等于账户验证）

- [S1 Codex认证](https://developers.openai.com/codex/auth)：官方支持的登录与计费区分；当前页面重定向到ChatGPT Learn。
- [S2 Codex图片生成](https://developers.openai.com/codex/image-generation)：内置图片及用量；不据此证明本项目程序化全链已通。
- [S3 TypeSafe API](https://api.typesafe.ai/docs) 与 [Quickstart](https://docs.typesafe.ai/introduction/quickstart)：Bearer、System One与模型目录。
- [S4 Google流式TTS](https://docs.cloud.google.com/text-to-speech/docs/create-audio-text-streaming)：配置首帧/输入流与Chirp 3 HD。
- [S5 Google Chirp 3 STT](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)：V2流式、地区与语言列表，组合仍需实测。
- [S6 Google本地ADC](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment)：用户凭据、权限及本地文件风险。
- [S7 OpenAI模型目录](https://developers.openai.com/api/reference/resources/models/methods/list)：GET模型目录，不替代推理调用。
- [S8 Gemini 3.8 Flash TTS](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash-tts)：模型页列明Gemini Enterprise Agent Platform预览模型、`global` REST路径与`aiplatform.googleapis.com`。

原项目基础：v0.6 M09/M10；自主交接阻断评审H04/H05/H10；ENV-01 spec与本次verification。借鉴来源保留不重写。
