# M09 后端承载、订阅额度与 Codex 适配

> **v0.6整合说明：** 原架构合同继续有效；本章新增“复用落点”只将借鉴书的既有证据和建议接到本章。具体技术栈未由本次整合自动批准；差分见A4，源码原阅读范围见A5。


**地位：** D7同意G05／G06联合路线，并提出LLM和生图优先使用Codex usage、同时预留API接口。已确认的是接入优先级与媒体／判断边界；本章分别保留v0.5官方资料记录、借鉴书源码依据与应用细化提案。确切承载路线、权限、预算阈值和原生生图协议待验证。不是全部字段已冻结，也不是新的导演Agent。
**依据：** D7；G56R；CX1–CX8；OS-REF §02/§07/§08及OS-C01–C11。G01–G04保持不变；外部资料本版未重新在线核验。

## 1. 先分开模型、承载和计费

| 维度 | 回答的问题 | 本产品处理 |
|---|---|---|
| 逻辑能力 | 是主生成、有限语义判断、图片生成，还是D-M检查？ | 由各模块合同定义，不随认证方式改变 |
| 模型 | 本次实际执行的型号和版本是什么？ | 按已验证配置选择并记录；不把Codex当成固定模型名 |
| 承载 | 原生Codex、订阅OAuth Responses、社区兼容网关，还是Platform API？ | 独立adapter与能力记录 |
| 计费与额度 | 消耗哪个账号／workspace／额度桶，是否额外付费？ | 单独政策与观察，不能仅凭使用HTTP API推断 |

“免费高效”在D7中是成本与性能偏好，不写为已验证事实。已有订阅的包含额度可能减少新增API账单，但仍受总量、套餐和账户规则约束；本书不保证零成本或更低延迟。[CX1–CX2]

## 2. 原三类承载与社区兼容候选：不把认证互换当作等价

### 2.1 原生 Codex 订阅承载

通过官方Codex登录及支持的本地集成接入，采用隔离配置和受限执行环境。CLI/app-server可作为适配候选；原生内置生图的订阅消耗有官方文档依据，但**v0.5未核验目标安装版本与账户全链；借鉴书随后补充了原生工具、真实产物和SDK的源码入口，本版据此转入接入验证，不再把程序化能力描述成生态空白**。[CX1–CX3]

因此CodexImageBackend已有可定位实现作为首接入候选；实际MIRA endpoint、选定版本和账户仍未验证。工具未执行、只返回“图片已生成”、没有实际产物或调用改走API，都不能上报订阅生图成功。v0.5原约束为：“不得用UI抓取、共享账号、反向调用私有backend-api或复制用户认证文件来替代正式接入。”本次未取得解除该限制的新决定，继续保留。借鉴书提出社区兼容网关为首联调建议；若选定配置实际依赖该限制涵盖的接入方式，不能仅凭开源实现存在就视为准入。**两文分歧登记IC-01，具体carrier在授权／维护边界明确前不自动启用；它不否定现成代码可作为借鉴或条件候选。**

### 2.2 ChatGPT plan usage 的公开 Responses 承载

v0.5资料记录了官方对符合条件的开源／本地应用提供的专门授权计划用量路线；本版仅继承该日期的记录，未重新验证。它使用公开Responses端点和应用自己的授权，不意味着任意缓存令牌都是通用API-key。[CX4–CX5]

**v0.5保留提案：** 对只需文本／结构化计划的主生成，若应用与账户满足该路线条件，优先比较“直接订阅Responses”与“Codex app-server承载”。前者可避免不需要的编码工具循环；这是假设中的简化收益，需要实测，不自动等于更快。该优化不改变D7的订阅优先偏好，但确切路线及额度桶由能力探测后固定。

v0.5所引预览在当时文档中要求stream=true、store=false，并自带上下文；部分常见请求字段不支持，image_generation等托管工具和音视频输入不在该路线支持面。[CX5–CX6] 因此 **订阅Responses文本可用 ≠ 同一接口可订阅生图**。也不能把不支持的max_output_tokens当成服务端硬预算；缺少原生上限时应用采用截止／累计输出上限与取消，并如实记录已经发生的费用或不确定消耗。

### 2.3 Platform API-key 承载

保留标准文本、视觉和图片API适配接口，认证、请求字段、额度和错误语义各自独立。API是可切换承载，不是未经用户允许的自动花费兜底。[CX1]

保守执行默认建议为：`api_fallback_requires_explicit_permission`。尚未获得额外支出授权时，订阅不可用就显示故障／额度状态、使用合规受控素材或同协议Mock／回放，不偷偷注入环境中的OPENAI_API_KEY，不自动购买credits／reset，不以换账户绕限额。此项是防止越过现有授权的执行边界，不声称用户已经选择了某个具体预算数值。

### 2.4 社区兼容承载：已有代码与尚未接受的具体路线分开

借鉴书建议CLIProxyAPI为订阅HTTP与生图首联调候选，Pi为TypeScript嵌入式文本备选；它们不是必须依次调用的代理链，也不等于官方通用API承诺。具体源码、读到的范围与适配差分见本章§13及A5。

**状态：候选已明确、账户与路线准入未完成。** M09 §2.1的原接入限制没有被本次整合静默撤销。IC-01需在选定配置上明确处理；符合现有边界的原生Codex承载和显式API接口继续保留。既不把“有实现”写成“无实现”，也不把“有源码”写成“所有部署均获授权”。

## 3. G05与G06在订阅优先下的落位

| 能力 | 本版方向 | 保留接口／条件 |
|---|---|---|
| 主LLM生成 | Codex／ChatGPT订阅额度优先 | GenerationBackend；API-key可切换；所选模型能力、中文风格和G03承载须实测 |
| 实时Input／Output Decision | 保留G05中JEV首接入与中文门槛 | 本次没有授权为了统一额度而移除JEV；其他文本判断须经验证后才可作为可用备选，不实质拒绝后换裁判抽签 |
| 动态图片 | Codex额度优先；原生及社区现成实现分别按路线准入 | ImageBackend；标准Image API保留；接口不齐时在线能力关闭，不以手工图冒充自动链 |
| D-M实际图像检查 | 保持直接读图和受限结构化结果 | 订阅OAuth／Codex视觉能力可作首探候选；独立验证任务，API可切换；具体承载尚未冻结 |
| ASR与TTS | 沿用语音v0.2的独立适配合同 | 没有因Codex登录而自动获得实时收音／定制声音能力 |

“优先用Codex的LLM”不意味着强行使用某个今天的推荐模型，也不宣称原Luna候选一定在当前账号可见。模型选择、承载与付费来源分别登记；更换型号需重新校准，不声称是零差异换底座。

## 4. Backend合同与能力探测

以下是应用字段提案，非官方schema：

```text
GenerationBackend.generate(context_packet, response_contract, execution_context)
  -> 有序候选数据 / 明确终态 / usage观察
ImageBackend.generate(approved_media_spec, execution_context)
  -> progress / actual_artifact / 明确终态 / usage观察
VisionReviewBackend.review(actual_artifact, review_contract, execution_context)
  -> 结构化观察 / unknown / failure
ExecutionContext
  -> request、session、generation、input/output依据、deadline、cancel、route_revision
```

CapabilityRecord分别记录接口可见、账户授权、完成请求、输入模态、结构化输出、真正增量候选、取消范围、产物传输、工具权限、重试、usage与预算控制能力。每项unknown不默认支持；目录可见不能替代实际完成请求证明。[CX3、CX7]

BillingPolicy与执行资格相互独立：费用获准不代表内容获准；剩余额度大也不能覆盖G04停止。

## 5. 接G03：只能把受控候选送进范围审核

app-server文档有文本delta、outputSchema及turn终态，可以构成验证起点；但这三者组合不自动证明完整表演范围能在turn结束前正确产出。[CX3]

应用适配只接收约定的候选输出通道；工具日志、工作计划、分析摘要、终端输出、“我来检查一下”等编码进度不进入角色字幕或TTS。若不能可靠区分通道或形成完整可审范围，则采用G03已批准A模式，在同合同下等整轮；不能为了保留流式名义而读裸JSON片段。

关闭与角色请求无关的shell、编辑、联网、MCP、插件及子代理工具。具体禁用能力必须从所选版本配置与隔离测试证明，`approvalPolicy=never`本身不等于没有工具。只读文件系统也不等于读不到用户隐私；运行环境不能继承用户日常开发目录、全量AGENTS.md、skills、插件和记忆。

G03的“一次主要生成”是本产品对话拓扑，不是一个Codex turn物理上必然只有一次模型请求。若代理内部调用工具、重试或子代理，必须记录真实任务和usage；主生成路径不允许固定额外导演。

## 6. 进程可预热，上下文不能被未播内容污染

**应用提案：** 本地桥接进程可以常驻减少重复初始化；每个主generation使用明确、隔离的上下文。优先采用显式当前ContextPacket，或创建没有旧未呈现输出的新thread；不把Codex完整thread历史当成MIRA有效对话史。

停止时，已经生成但尚未播放的文字可能仍在Codex线程里。如果直接thread/resume，下一轮可能误以为用户听过它。只有实际ExposureState和已确认用户输入是本产品重建上下文的依据；必要时丢弃执行thread并重建。派生缓存也要按角色／权限／用户／删除状态隔离。[M01；M04]

D-M另建受限验证上下文，给实际图像、允许规格和必要参考，不输入生成器的自我评价作为证据。相同底模的独立请求不自动成为统计独立裁判；控制关键内容范围和人工gold评测仍必要。

## 7. 接G04：本地先停，远端取消是另一条证据

```text
本地新活动／停止锁
  → 撤销当前资格，立即制止呈现
  → Actor失效或有界暂停分支
  → Backend取消（原生Codex可用turn/interrupt等已验证接口）
  → 所有晚到文本、文件、图片与通过结果继续按身份丢弃或隔离
```

interrupt请求成功或连接关闭都不证明供应商计算瞬时结束，更不清除本地停止锁。[CX3；M04] 若订阅认证刷新需要重启桥接，不能因此自动恢复旧turn或消费旧artifact；重新开始按G04因果关系与新控制实例合同。

程序可以回收独立失效worker，但不能为了取消一个用户的任务杀掉承载其他有效会话的共享进程。共享进程的调度和失效隔离是实现验证项。

## 8. 图片是独立慢任务，不继承编码工作区权限

媒体worker只获得已批准MediaRequestSpec、必要参考与隔离产物区，不提供全部人物秘密或用户开发环境。主生成只提出意图，不自行执行未获准工具；worker按受控规格调用内置图片能力，不成为第二个剧情导演。

产物必须取得实际字节，检查文件边界与内容身份，再走D-M和当前情境检查。不能信任模型返回的任意路径、symlink或“已保存”；不执行产物中的代码／脚本。所选现成实现接入MIRA后的图片请求—结果身份关联未验证前，在线图片关闭；离线Codex创作素材经过核准后仍可作为受控资源，但不是“运行时动态生图已完成”的证据。

图片检查可以使用订阅路线支持的实际图像输入（以真实账户及模型验证为准），不能通过生成描述替代。未经审核的中间预览不送入主展示。图片完成不发出新用户请求，也不覆盖停止／隐藏状态。[G06；M06]

## 9. 共享额度必须被当成有限资源

**应用提案：** 为主对话、D-M与图片分别设有界并发和任务队列，保留对话响应的调度优先级，防止生图占满本地任务槽。若共用套餐额度，配额隔离仅是本应用准入纪律，不制造独立供应商额度池；用户在IDE的用量也可能改变可用量。

使用可取得的account／usage通知做观察；不支持或返回缺失时写unknown，不解释为无限。记录auth_mode、route/model/version、usage来源、错误／额度状态与额外API支出是否获准。不将供应商额度百分比直接换算成精确tokens或钱；官方内置生图的平均更高消耗也不是本场景配额保证。[CX2–CX3]

不要为提升吞吐轮换身份、改host ID或复制账号绕限制。免费额度、已购credits、额外API账单分开；不存在本轮批准的自动付费／自动充值。取消可能已有消耗，必须诚实。

## 10. 本地与公开演示的部署边界

**首探建议：** 用户本人控制的隔离本地环境。手机访问的是带本地会话认证的MIRA后端，不是裸Codex app-server；不要将个人认证面、任意prompt/command执行端口或token暴露到公网。

公开演示优先采用已要求的Mock／回放，或另行获准、按条件配置的API部署。开源／本地ChatGPT plan usage文档不能自动授权收费／远程多人服务；该类接入按官方适用范围另核验。[CX4；REQ第3–4页] 此处不把“本地”当“模型离线”，推理仍可能外传。

不读用户auth.json，不复制cookie，不让访客共享个人账号令牌；通过产品正式登录或应用自身的专门授权流程。实际认证方式对数据处理有不同影响，必须在路线记录里说明。[CX1、CX4–CX7]

## 11. 最小探测次序与回退

先按IC-01及本章§13明确承载边界，并使用现成接口而非自写认证／传输；再核验实际身份、套餐与模型访问；再验证一个文本结构化任务、真增量／封口和中断；然后独立验证订阅原生图片产物与实际读图检查。所有探测需要显式运行授权，本版没有执行。

若只有整轮结构化可用，选G03-A保守模式；若文本都不可用，使用同协议Mock／明确错误，不假称正常LLM；若原生图片接口不可用，保留受控素材并关闭在线图。API备用需要明确授权后才进入，不绕开内容拒绝或改变rubric。

G01–G04的正确性不因订阅优先而降级；首答延迟、真实取消尾部、整体调用量与资源隔离要分别测量。额度优先是一项经济约束，不是性能验收结果。

## 12. 当前仍需确认或验证的细节

实际Codex版本／SDK与图像工具合同、目标账户／workspace、应用是否符合计划用量接入条件、订阅额度桶、主模型和D-M型号、增量framing、工具关闭与工作区隔离、缓存／凭据生命周期、允许API支出的边界、预算水位、公开部署方式，均未因D7一句偏好而视为完成。

本章的路线候选和默认安全处置不把未知能力填成已支持，也不使受控图片范围重新悬置。具体接口验证失败应收窄运行能力，保留已经批准的领域架构。


---



> 本节继承借鉴书v0.1的代码记录和建议，源码阅读日期为2026-10-02，本版未重新拉取。文中“首联调建议”始终受§2.4及IC-01约束，不是对未接受认证方式的执行指令。C/W编号在本书加OS前缀；完整40位提交和读到的行范围由A5保存。

## 13. 复用落点：订阅文本、生图与原生SDK

### 13.1 三个项目覆盖三种接入形态

| 项目 | 最适合借什么 | 建议用途 |
|---|---|---|
| CLIProxyAPI | 订阅认证后的兼容HTTP网关、Responses流、图片端点转换 | 本地订阅接入的首个联调候选；减少自写网关 |
| 官方Codex | 第一方SDK／App Server、原生工具、生图事件与产物 | 原生任务适配及图片生命周期的规范参考／替代承载 |
| Pi（当前earendil-works/pi） | 无须引入整个Agent产品的provider模块 | 偏TypeScript且不愿增加代理进程时的嵌入式备选 |

三者是**互选或按能力分工的候选**，不是每轮依次调用的三道链路。首轮联调建议先试CLIProxyAPI的标准外部接口；确实需要原生Codex任务特性时再选官方承载。Pi不与网关叠一层相同职责的路由。[OS-C01](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_executor.go)–[OS-C11](https://github.com/earendil-works/pi/blob/9fba660cf1caca0ade5bea72269352416e595a19/packages/ai/src/legacy-api-aliases.ts)；[OS-W01](https://github.com/router-for-me/CLIProxyAPI)–[OS-W04](https://github.com/earendil-works/pi)

### 13.2 CLIProxyAPI：文本与生图都有实际实现

固定提交：`2044a01f422998de79a5da8015141b878886534d`。项目首页给出Codex OAuth、兼容Responses与流式/非流式入口；源码中的`CodexExecutor`明确是无状态执行器。认证刷新与WebSocket路径也有独立实现入口，借鉴书原核查对后两者只做符号定位，没有通读。[OS-W01](https://github.com/router-for-me/CLIProxyAPI) · [OS-C01](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_executor.go) · [OS-C04](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_executor_auth.go) · [OS-C05](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_websockets_executor.go)

**重点源文件不是只有README：**

| 文件／符号 | 借鉴书记录读到什么 | 我们怎样用 |
|---|---|---|
| `internal/runtime/executor/codex_openai_images.go` | `executeOpenAIImage`、`executeOpenAIImageStream`，区分直接图片路由及Responses工具路线，提取图片与usage，处理无图片和未完成断流 | 以现有images外部接口接ImageBackend；不自写底层SSE图片提取器 |
| 同文件 | 流式发送检查`ctx.Done()`，有partial-image处理路径 | 复用取消传播；MIRA仍在本地关闭资格，partial留隔离区 |
| `codex_openai_images_test.go` | 合成上游验证图片路径、请求和返回，包含可定位测试函数 | 从上游测试获得协议fixture；集成测试另跑，不称已通过 |
| `disable_image_generation_mode.go` | `chat`语义允许专用images入口、限制非images入口生图注入 | 让文本生成不擅自增加图片任务；配置名和默认值在锁版时核对 |

来源：[OS-C02](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_openai_images.go) · [OS-C03](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_openai_images_test.go) · [OS-C06](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/config/disable_image_generation_mode.go)。

**推荐形态：**MIRA只调用本地受保护的网关服务，前端不接触账户认证材料。把GenerationBackend和ImageBackend指向网关兼容入口；标准付费API仍是另一个显式配置profile，应用层上方合同不变。不要复制其OAuth、刷新、传输和各Provider转换进MIRA仓库。

**必须收紧的默认能力：**账号池、自动切换、自动重试、自动工具注入、遥测正文记录不是MIRA天然需要的功能。使用用户授权的账户和允许的用途；不采用轮换账户规避限额、不把个人订阅开放成公共匿名推理服务，也不因失败自动落到计费API。社区兼容实现与官方通用API承诺是两层，协议变更风险留在适配边界，不转化为“无法使用现成代码”。

**两个真实接缝。**第一，某些图片转换路线会先调用一个驱动模型再触发生图，源码有`resolveGPTImage2BaseModel`。这不是免费消失的一次调用；记录实际模型、attempt与usage，但它也不必成为MIRA每轮固定的第二个导演。第二，兼容协议不保证G03所有结构化字段原样保留，联调需检查输出schema、非正常终态和工具结果，而不是只测一条普通文字返回。[OS-C02](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_openai_images.go)

完成标准应改写为：已存在协议实现＋我们的固定版本联调与隔离验收，而不是“研究如何调用Codex usage”。

### 13.3 官方Codex：SDK和生图生命周期已经有源码

固定提交：`44dd77b71e88c78295736bffd3dc3b684c13be6d`。

TypeScript SDK的`Thread.runStreamed`建立结构化输出schema、传入取消signal，并逐条解析事件；`run`聚合最终消息、usage和失败。`local_image`也有明确输入类型。它是现成入口，不应再自己发明CLI stdout解析器。[OS-C07](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/sdk/typescript/src/thread.ts)

原生生图实现位于`codex-rs/ext/image-generation/src/tool.rs`：有生成／编辑、开始／失败／完成项，返回真实图片结果，并记录`saved_path`、请求身份与生成身份。`artifact.rs`定义生成图片目录与路径。这已经能支持“从源码反查产物在哪里、如何取得”的接入工作，不是只有一个界面按钮。[OS-C08](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/codex-rs/ext/image-generation/src/tool.rs) · [OS-C09](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/codex-rs/ext/image-generation/src/artifact.rs)

App Server官方文档提供事件驱动接入和中断接口，适合需要常驻连接与原生工具任务的承载；SDK与App Server应按实际事件粒度择一，不声称SDK的所有事件必然是逐token增量。[OS-W02](https://developers.openai.com/codex/app-server)

**不能原样复制的上游UI假设：**`artifact.rs`给模型的原生提示认为图片已向用户显示。对于MIRA，这句话不构成呈现回执。适配器取得结果后仍须隔离→D-M→当前情境重验→G02许可→客户端真实显示；不把原生提示或工具完成事件写入`photo_presented`。[OS-C09](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/codex-rs/ext/image-generation/src/artifact.rs)；B1 M01/M06

**线程和进程分开。**允许预热桥接进程；每次新生成必须用实际呈现重建的ContextPacket。不要因SDK支持继续thread，就让上次已生成但未播放的尾部继续作为“用户已听过”进入后续上下文。采用新thread、受控上下文重建或可证明等价的隔离方式，不依赖另一个Agent自带历史做事实权威。[OS-C07](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/sdk/typescript/src/thread.ts)；B3 §12.5

**主生成只挂所需能力。**编码进度、分析、工具日志不能进入角色TTS；不向角色生成任务暴露整个开发目录、任意命令和个人插件。生图作为受控独立慢任务可以使用原生工具，但模型临时多执行了一次工具，仍须记录，而不是藏在“单次主生成”表述内。

### 13.4 Pi：复用provider层，不引入完整coding-agent

当前项目入口为`earendil-works/pi`；旧`badlogic/pi-mono`资料需要检查重定向，不照抄旧包名。固定提交`9fba660cf1caca0ade5bea72269352416e595a19`中的`packages/ai/src/api/openai-codex-responses.ts`已经处理Codex Responses配置、事件转换、Abort组合、终态与额度错误分类。旧`streamOpenAICodexResponses`导出在检索到的alias里被标为弃用。[OS-C10](https://github.com/earendil-works/pi/blob/9fba660cf1caca0ade5bea72269352416e595a19/packages/ai/src/api/openai-codex-responses.ts) · [OS-C11](https://github.com/earendil-works/pi/blob/9fba660cf1caca0ade5bea72269352416e595a19/packages/ai/src/legacy-api-aliases.ts) · [OS-W04](https://github.com/earendil-works/pi)

它适合把底层provider直接嵌入TypeScript服务：传受控上下文和signal，接规范事件，之后仍走MIRA解析／范围审核。不要为了用provider顺便挂载完整TUI、shell loop和持久化编程会话。

借鉴书证据主要支持文本provider；**没有把Pi自动登记为同等完整的生图接口**。文本走Pi、图片走官方Codex或CPA，可以是能力分工，但不应同时引入多个互相覆盖的文本路由。

### 13.5 推荐的首个联调面

1. 用CLIProxyAPI固定版本启动仅本地可达、受认证保护的服务；由用户完成授权，不复制凭据到MIRA代码或浏览器。
2. GenerationBackend提交同一ContextPacket，记录真实输出事件、完成原因及取消；结构化增量不满足时使用已批准的G03-A，不另造降级主链。
3. ImageBackend调用专用图片入口，取得真实bytes／可验证产物身份；检查空结果、非正常结束、取消后迟到与未知usage。
4. D-M读实际图像，G02/G04管展示；API profile只在明确启用时调用。

这些是**建议实施顺序，不是原借鉴书或本版已经执行的命令或账户测试**。官方说明Codex生图消耗Codex用量；“已有额度优先”不等于无限免费或必然比API快。[OS-W03](https://developers.openai.com/codex/image-generation)


### 13.6 本章工作包与验收入口

WP01提供薄GenerationBackend，验证RI-01–RI-04；WP02提供图片实际产物与隔离，验证RI-05–RI-07。上下文隔离、真实终态、取消迟到和无隐式付费分别验证，不因普通文本请求成功就判定生图／D-M同样可用。原CX-P01–CX-P12及G56用例继续保留，RI不代替它们；具体route先过IC-01与S01。
