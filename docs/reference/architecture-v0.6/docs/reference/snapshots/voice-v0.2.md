# 实时角色化语音 AI：架构设计方案 v0.2

**日期：2026-10-02**  
**状态：Revised Design / 待实现与 PoC 验证，不是已实现系统**  
**修订基线：architecture-v0.1.md；协议版本：0.2（不与 0.1 事件／配置静默混用）**  
**主路线不变：Streaming ASR + JEV + Luna + Streaming TTS + 可取消播放运行时**

本版按用户确认的运行时修订更新原设计，保留 22 节组织、供应商适配层、单 Session Actor、单播放仲裁器、角色目标和原有实验基线。不引入模型训练、微调、内部表示读取、原生全双工模型改造或新的常驻服务。

本轮六项改动：**输入／输出队列分治；暂停与永久取消分离；表达策略前移并持续复用；首段检查与 TTS 隔离并行实验；按播放进度限制生成领先量；通话表达与等待语许可补强。** 改动已同时写入状态合同、配置、故障处理、指标和验收条目，不能只替换架构图。

**证据边界：**[S01]—[S12] 及 §2 的供应商描述继承 v0.1 的来源记录，本轮是文档修订，没有重新联网核验这些产品事实，也未核实账户、运行付费推理或测得性能。配置中的厂商／模型名称是待接入核验的候选，不是可用性保证。新增内容是本项目设计决策；数值是可配置实验起点。

`CHANGELOG.md` 提供逐项落点、破坏性协议迁移与验收映射；`config.example.yaml` 是配置合同草案，不是可运行应用；`design-validation.md` 仅记录本次实际完成的文档／配置静态检查。原版在包内 `baseline/` 原样保存。

---

## 1. 架构结论与边界

采用“持续收音 + 事件驱动运行时 + 两个语义决策点 + 可撤销推测分支”的可组合架构。

- **Character Plane** 定义角色如何理解关系、选择措辞、保持人物逻辑。
- **Intelligence Plane** 由 Luna 生成内容、执行必要推理；复杂工具工作通过受控接口执行。
- **Semantic Control Plane** 由 JEV 判断当前输入、候选回答、表演意图与等待语音适配性。
- **Performance Plane** 由定制 TTS 与预制音频共同提供声音。
- **Realtime Runtime** 独占版本管理、截止时间、取消、缓冲、播放授权和观测。模型提供判断，代码执行规则。

JEV 是主要语义控制组件，而不是被边缘化为偶尔调用的工具；但它不是音频帧调度器，也不能越过新鲜度、安全或会话隔离检查。

当前范围明确排除重新训练／微调 ASR、LLM 或 TTS，排除读取模型内部表示和修改模型解码；不做多候选猜测树，不默认加入 Voice Conversion，不依赖尚未完成接入验证的 Decisions API。音频双向传输不等于已经实现自然的全双工社交互动。

v0.2 的三个不变量：**状态更新不等于分支失效；允许提前合成不等于允许外传或播放；模块职责独立不等于必须串行等待。** 所有新增策略落在原有模块内，不新增“表达计划服务”或“语义同步服务”。

**不要预先认定全部瓶颈都在 Luna。** 本项目要测量的是“首个可用文本片段 + 决策 + 首段非静音音频 + 实际播放”，而不只是 LLM 的首 token。

## 2. 供应商能力基线（继承 v0.1，待接入复核）

| 组件 | v0.1 记载的能力 | 本方案使用方式 | 尚待验证 |
|---|---|---|---|
| JEV | TypeSafe 官方定义为结构化概率判断模型；同一 state 的独立问题可并行回答，彼此看不到答案。[S01][S02] | 输入状态判断、输出片段判断、表演与垫音选择 | 中文语音转写场景准确度、部署区域 p50/p95、限流与取消行为 |
| Luna | `gpt-5.6-luna` 官方模型页列出 streaming、function calling、structured outputs；音频不支持。[S03] | 主文本生成模型；模型名由配置指定 | 首个可朗读片段延迟、角色一致性、不同 reasoning effort 的收益 |
| OpenAI 文本流 | Responses API 提供 `response.output_text.delta` 等事件。[S04] | 适配成内部 `llm.text_delta`，其他事件不进入朗读路径 | 本账户并发、速率限制和不同上下文长度表现 |
| Google TTS | 官方文档提供双向流式合成；首次请求发送配置，后续发送输入。[S05][S08] | 首选验证 Chirp 3 HD 的流式路径 | 指定 voice/语言/区域的 TTFA、持续输出、取消与长会话限制 |
| Google 自定义声音 | Instant Custom Voice 支持流式使用，包含 `cmn-CN`，需 allowlist。[S07] | 获取权限后验证中文角色音色；权限未获批前用预设音色做链路测试 | 权限、授权材料、相似度、跨语种一致性 |
| Google 表演控制 | Chirp 3 HD 有语速、停顿等控制；流式请求不支持 SSML。[S06] | 建立 capability map，按实际支持映射 | 任意 emotion/intonation 标签不能视作原生参数；按模型实测 |
| Decisions API | v0.1 未完成稳定 API contract、账号可用性和实测验证 | 只预留 DecisionBackend 接口 | 不作为 MVP 依赖 |

TypeSafe 发布文中的 70–500ms 是官方报告范围，不是本项目 SLA；其说明也限定了测试环境。[S01] 不能把之前讨论中的第三方速度数字直接写成系统保证。

**一个影响设计的明确边界：** Google 的通用消息定义包含某个字段，不等于所有 voice 都支持它；Chirp 3 HD、Instant Custom Voice、其他 Google TTS 模型不能混成一套能力表。

本轮不据此增加厂商能力承诺，也不把同行架构或论文结果写成系统优势。每次启用实际 provider、model、voice、region 组合前，仍需执行 §22 的 live gate；不通过则保持候选／unknown。

## 3. 总体逻辑架构

```text
客户端：麦克风 → 回声处理 / 本地 VAD → Streaming ASR
                  │                        │
                  │ 本地暂停／停止         ▼
                  │               Transcript State Store
                  │                        │
                  │       ┌────────────────┴──────────────┐
                  │       ▼                               ▼
                  │  JEV Input Decision              角色 / 记忆检索
                  │       │
                  │       ├─ 话轮、候选有效性、推测意图
                  │       └─ 可复用表达策略 ───────┐
                  │                              │
                  │      Session Actor / Speculation Controller
                  │                        │     │
                  │                        ▼     │ 措辞约束
                  │                     Luna ◀───┘
                  │                        │
                  │           Incremental Chunker / 冻结片段 FIFO
                  │                        │
                  │      ┌─────────────────┴─────────────────┐
                  │      ▼                                   ▼
                  │ JEV Output Decision             首段 TTS 隔离合成
                  │      │                          （实验默认关闭）
                  │      ├─ 默认：批准后 → TTS                │
                  │      └─ 实验：批准 + 隔离音频就绪 ─────────┘
                  │                        │
                  │             已批准、仍有效的音频
                  │                        ▼
                  └──────────────▶ Playout Arbiter ◀── 带任务依据的 filler
                                           │
                                    AudioWorklet → Speaker
                                           │
                        实际播放进度／暂停回执 → Session Actor

共享：输入快照、表达策略、分支有效性、播放位置、计算预算。
表达策略同时约束 Luna / Performance Adapter / filler；它不是播放许可。
```

预制音频和真正回答汇入**同一个播放仲裁器**。正文、倾听反馈、等待垫音和操作说明使用不同的 speech-act 许可；不能各自启动互不协调的播放器。MVP 的重叠 backchannel 仍默认关闭。

实验路径只允许第一个冻结片段在内容审批期间送 TTS，且必须先通过不可跳过的外传与合成授权。结果仅在服务端隔离队列保存，不能提前发送给客户端；详见 §6.5、§9.4。默认路径仍然先审再合成。

## 4. 服务形态：逻辑分层，物理上先保持简单

第一版采用一个异步服务进程，内部多个模块；每个 session 一个状态所有者，即 **Session Actor**。网络调用是异步任务，结果回到该 session 的事件队列，由状态所有者串行应用。

```text
Session Actor
  ├── transcript state
  ├── floor / turn state
  ├── active generation + candidate validity
  ├── input snapshot coalescer / frozen output FIFO
  ├── expression policy + validity scope
  ├── pause state / branch validity / fresh playout permits
  ├── input/output decision jobs
  ├── TTS stream + audio queue
  ├── filler policy + deadlines
  └── delivered ledger
```

Actor 不同步等待 JEV、Luna 或 TTS；它启动任务后继续处理收音、取消和播放器事件。这样避免“正在 await 模型，所以不能打断”。

MVP 不在音频热路径上引入 Kafka、跨服务数据库事务或重量级工作流编排。对象存储用于预制音频，数据库用于角色版本、授权记录和会话摘要，不参与每个音频块的播放决策。

停止、撤销许可等控制事件不能排在无限积压的媒体任务之后；媒体队列必须有界。Actor 是本会话语义状态的唯一写入者，客户端只拥有即时音频抑制与本地停止锁等必要本地状态，二者按 §11 的协议协调。

采用框架时，必须声明话轮决定、生成触发、取消和实际音频输出的唯一执行者。可以复用传输、音频、取消设施，但不能让框架默认话轮机制与 JEV 策略分别启动同一回答。是否复用由接口合同测试决定，不在本版强制迁移供应商或框架。

## 5. 输入路径：ASR 不只是输出字符串

### 5.1 客户端捕获

采集时记录单调时钟、音频采样位置、输入采样率、通道数与序号。保留实际格式，由适配器做一次必要的重采样；不能把 48kHz 的音频标成 16kHz。

回声处理和本地 VAD 持续运行，角色说话时也不关闭麦克风。所有角色音频，包括本地 filler，都必须纳入同一个回声处理与实测方案，否则 filler 可能被 ASR 识别成用户输入。

仅文本 ASR 会丢失部分语气、笑声、重叠说话等信息。MVP 保留原始短时音频窗口与基础声学事件，后续需要时再增加专门的音频理解侧路；不假设 JEV 能从没有提供的音频中恢复这些信息。

### 5.2 内部 ASR 事件

以下均为**本项目内部协议**，不是任何供应商的请求格式。

```json
{
  "schema_version": "0.2",
  "type": "asr.hypothesis",
  "session_id": "s-example",
  "input_epoch": 12,
  "activity_seq": 31,
  "turn_id": "u-12",
  "input_revision": 7,
  "segment_id": "seg-3",
  "text": "我觉得这个方案不错，但是",
  "segment_final": false,
  "provider_stability": null,
  "audio_end_sample": 96000,
  "sample_rate_hz": 16000,
  "clock_id": "client-audio-clock"
}
```

`provider_stability` 没有提供时必须为 unknown/null，不能伪造为 1。标准化后的 `input_revision` 是当前逻辑输入话轮的转写快照版本；`activity_seq` 是客户端观测到的新声音／停止事件序号，二者不得混用。`input_epoch` 在语义上确立新的用户话轮时由服务端分配，不因一个疑似噪声立即递增（§11）。

Google 文档明确区分：`stability` 表示 interim 转写是否可能改变；`is_final` 只说明相应片段不再修订，不表示用户整个回合已经结束。[S09]

因此三件事必须分离：

```text
转写是否稳定 ≠ 语义是否完整 ≠ 用户是否让出了话轮
```

### 5.3 JEV Input Decision

输入包括：当前转写与最近修订、已有 final 片段、静音长度、最近用户话轮、角色正在播放什么、是否存在未播候选、候选依赖的输入版本，以及明确的对话规则。

同一次请求中的问题设计为独立的语义维度：

| 判断 | 建议输出 | 执行者 |
|---|---|---|
| 当前句子是否完成 | Noul / 概率 | Runtime 结合声学状态判断话轮 |
| 用户是否明确继续、纠正、停止 | Choice，含 unknown | Runtime 更新 floor |
| 是否值得开始推测 | Choice: wait / retrieve / generate | Speculation Controller |
| 当前候选是否仍适用于新输入 | Noul，提供候选与完整最新上下文 | Candidate validity gate |
| 回答工作类型 | Choice: direct / explanation / reasoning / tool | LLM 配置与延迟预测特征 |
| 哪类短反馈合适 | Choice，含 none | Preamble Controller |
| 是否不适合娱乐化表达 | Noul / 具体场景分类 | Character/Performance policy |
| 当前交流行为与展开方式 | Choice，含 unknown；解释／短答／先问清 | 现有 Character Plane 的表达策略 |
| 是否需要改变既有表达方式 | Choice；保持／调整／保守默认 | Performance Adapter 与 Luna 上下文 |

增加问题不等于增加一个新服务或多次串行请求。输入 state 带已播放前缀、当前表演状态和真实计算阶段；声学线索只使用实际测得且带时间位置的数据。

同一请求的多个答案不能暗中互相依赖。例如“如果上一题选 A，再按 A 回答下一题”不是并行问题；需要把条件完整写入各题，或者在代码中组合独立结果。[S02]

### 5.4 输入调用节奏：只合并完整快照

不要逐音频帧、逐 token 调用 JEV。输入语义明显变化、声学结束候选、显式停止或待播候选需要再验证时触发。输入判断采用 **一个 in-flight + 一个 latest pending 完整快照**；最新快照包含所有必要上下文，所以可替代尚未执行的旧快照。

原始 ASR delta 不得直接用 latest-only 覆盖。先应用修订、去重与累计，再构建可自足的状态快照。显式停止、客户端暂停回执、输出审批结果也不是可丢弃的 ASR 快照；它们作为控制事件单独处理。

结果必须匹配该判断读取的输入版本、角色版本和分支依赖。新输入已经到达时，不用旧结果重新授权播放；必要时只提取仍可复用的非授权偏好，并重新检查适用范围。取消 HTTP 请求不保证供应商停止计算。

Debounce、频率上限和超时均配置化。输出片段使用不同队列合同（§8.4），不得复制输入 latest-only 策略。

### 5.5 声音活动不自动废弃回答

客户端声音事件先触发可撤销的播放暂停和活动序号更新；服务端随后区分噪声、附和、兼容补充、事实纠正或新话题。未分类前不恢复声音；保留工作只意味着暂不删除，不能视作语义有效。

新转写出现时撤销当前授权并重新验证；兼容性确认可以保留同一个 generation，关键事实变化则使受影响的未播后缀失效。默认供应商不支持局部取消／精确对齐时，保守地失效整个未播分支（§12）。

## 6. Speculative Generation：能提前算，但不能提前相信

### 6.1 三种工作深度

**S0 预取：**只做只读、有限成本的上下文和记忆检索。

**S1 文本推测：**为当前输入快照开始 Luna 生成，结果不进入用户可见历史。

**S2 音频推测：**默认先通过内容检查再开始首段 TTS，音频保持可丢弃。§6.5 的独立实验允许首段内容检查与隔离合成并行；不能省略外传授权、最终内容批准或播放许可。

MVP 每个 session 同时最多一个 speculative generation；只预合成第一段。先证明单候选收益，再考虑多候选树。

### 6.2 候选的依赖

```text
candidate_id
  ├── origin_input_revision
  ├── validated_for_input_revision
  ├── character_revision
  ├── context_revision
  ├── output_epoch
  └── budget / cancellation token
```

如果用户从“这个不错”补成“这个不错，但是我绝对不会买”，旧候选不能因为文本前缀相同就继续播放。检查对象必须是**回答对最新完整输入是否仍成立**。

### 6.3 新输入到来时

第一步撤销未播候选的播放资格，不一定立即扔掉计算。随后区分：只改标点、增加兼容细节、改变关键条件。能证明兼容的候选可以在当前 revision 上重新授权；不确定时重算。

“重新验证”本身有延迟，也必须记入预算。不能宣称所有 JEV 和 Luna 的耗时都被流水线自动隐藏。

当一个尚未播放的 chunk 被重写，它之后基于旧前缀生成的文本和音频也应失效；不能只替换中间一段却保留逻辑上依赖它的后半段。

### 6.4 推测预算

设置每轮最大重启次数、每 session 推测并发、每轮 token/音频预算和无收益停止条件。超过预算后关闭本轮推测，等待最终输入；不通过无限重试“追赶”变化的转写。

推测阶段不发送消息、不付款、不写长期记忆、不进行外部不可逆操作。只读工具也需要权限与配额，因为它们并不是零成本。

### 6.5 首段检查与 TTS 并行：独立、默认关闭的实验

这项实验优化的是**候选已形成后的串行依赖**，与“用户说完前的推测”是不同开关。即使 `speculation.enabled=false`，也可以在完整输入后测试 `review_tts_overlap.enabled=true`；反之，两者可以分别关闭，便于归因。

入场条件必须全部满足：

1. 当前内容已通过不得绕过的隐私、安全、权限及供应商外传／合成检查；高风险、敏感或资格未知时走默认先审路径。不用“最终不会播放”作为外传理由，也不把一个轻量分类器当全部许可证明。
2. 第一段文本已冻结，内容、规范化文本摘要值、片段版本和 TTS 实际使用的表达参数固定。JEV 必须审查与合成完全相同的内容及相关上下文。
3. 已有当前可用的表达策略和已核实默认参数，不再等待另一份风格结果。必须等风格结果的场景不具有这部分并行收益。
4. 有服务端隔离音频预算；供应商可在该输入粒度产出音频，且取消和流等待行为已探测。

```text
Frozen chunk #0
  ├─ JEV 内容判断 ──────────────┐
  └─ TTS → 服务端隔离音频队列 ──┤
                               ▼
               内容通过 + 当前输入有效
                               ▼
                  提升为可发送音频
                               ▼
                    客户端播放许可
```

同一流在首段审批完成前，**不得接收第二个未批准片段**，也不向客户端发送任何隔离 PCM。首段批准后，已有隔离音频可提升，后续返回包按已批准首段来源处理；后续文本仍先批准再推入流。没有精确文字—音频对齐时，不能靠猜包边界把未批准内容混进已有可播放流。

首段被拒绝、文本修改、表达参数必须修改、依据失效或超时：取消旧合成流，废弃隔离音频及相关未播后缀，按新版本重新生成；不能修改摘要值后沿用旧批准。音频预算耗尽时关闭本次实验并按失败／重启合同收口，不无限保存。

若供应商只能在 `finish_input` 后返回首音频，本轮可能需要在首段后新开流，应记录额外开流及韵律成本；不宣称“一条连续流”不受影响。无法可靠管理等待、隔离或取消的 adapter 不启用本实验。

**批准用于发布，外传许可用于调用，二者不互相替代。** 此实验仅作为低风险、授权输入的可回退 PoC；默认配置关闭。

## 7. Character Plane 与 Luna 生成路径

### 7.1 角色不是“把所有话都用活泼语气念出来”

角色配置分三层：

| 层 | 内容 | 更新方式 |
|---|---|---|
| Character Bible | 人物逻辑、价值取向、措辞习惯、禁用套路、示例对话、诚实边界 | 人工审核、版本化 |
| Session Character State | 当前话题、对用户的已知称呼、近期情绪表达、互动节奏 | 根据已确认对话更新 |
| Performance Intent / 表达策略 | 当前交流行为、展开方式、语气与速度意图、等待语适配性 | 在话题／语境显著变化或表演段边界更新；不逐片段随机重判 |

表达目标使用具体规则，例如“默认先用一两句回应，用户追问再展开”“普通聊天不机械列出首先其次最后”“保持轻快但在严肃语境切换为直接、克制”。不要求假装真人，不把关系设定当真实世界事实。

预制等待音由 runtime 负责，所以 Luna 默认不再额外生成固定“嗯，我想想”开场；但对实际问题有意义的简短回应可以保留。

### 7.2 Prompt 布局与缓存

建议布局：稳定角色规则、通话表达合同与少量范例 → 已确认对话 → 短动态状态／当前有效表达策略 → 当前输入快照。固定前缀有利于缓存，但是否命中还取决于实际缓存边界和请求配置，应记录真实 usage，不能只看字符串相似。[S10]

不为追求缓存保留已被用户纠正的错误事实。生成中的 speculative response 与正式对话账本隔离。

### 7.3 Luna Adapter

提供内部接口：

```text
generate(context, input_snapshot, character_revision,
         expression_policy, model_config, generation_id, cancel_token)
    → TextDelta | ToolIntent | Completed | Failed
```

只把面向用户的文本 delta 送给 chunker；工具参数、内部推理数据、控制标记和错误载荷不能送去朗读。流未正常结束时，保留已播放前缀，但废弃尚未验证的半句话。[S04]

首版普通聊天 A/B 比较 `none` 与 `low` 等模型支持的 reasoning effort；复杂任务保留更充分推理的通道。不能为降低 TTFT 固定降低所有任务的推理质量。[S03]

### 7.4 通话表达合同（属于现有 Character Plane）

稳定人物事实和长期习惯仍然版本化；通话表达规则单独明确但不形成第二套人格：不朗读动作描写；普通聊天先给完整、包含必要限定的短回应再展开；用户要求长解释时正常展开；不把主观情绪猜测写成用户事实；严肃话题降低调侃；运行时负责等待语，避免 Luna 重复“我想想”。

例如优先生成“可以试，但我们得先确认它的打断行为”，而不是先发布“可以试”，再把必要限制推迟到下一段。首段必须是实质内容，不用泛泛开场冒充首答。

### 7.5 表达策略前移与有效期

输入侧 JEV 的一次状态判断可给出独立的 speech act、展开方式、语气范围和垫音类别；代码组合成当前表达策略。同一份策略分别约束 Luna 措辞、Performance Adapter 和 filler 选择，不新增一个阻塞式规划调用。

```text
ExpressionPolicy（内部字段，非供应商 API）
  policy_revision
  scope: turn | performance_span
  input_epoch / based_on_revision
  character_revision / context_revision
  speech_act / response_shape / style / pace_intent
  allowed_waiting_acts
  validity: valid | unknown | expired
```

策略是偏好，不是内容审批或播放许可。只在当前作用域、人物和语境仍兼容时复用；输入最后改口、严肃程度改变、明确风格要求变化时重新判断。已确定的事实和安全边界不受“角色更俏皮”的偏好覆盖。

策略尚未完成时，Luna 可以使用仍有效的上一策略；没有有效上一策略时使用经审核且适合当前风险边界的保守默认。不得为等一个轻微风格偏好阻塞已允许的生成。风格迟到只影响尚未固定参数的合成或下一次生成，不为装饰性变化重启正确回答。语境发生实质变化则走输入有效性检查，而不是伪装成风格更新。

输出 JEV 只在形成实际文本后判断内容资格与显著偏离，并在必要时更新表达偏好；角色漂移检查在自然边界或回合结束执行，不默认逐 token 反复审查。

## 8. 输出分段与 JEV Output Decision

### 8.1 四种边界不能混用

```text
LLM token
  ≠ 可以独立判断的语义片段
  ≠ TTS 输入单元
  ≠ TTS 返回的音频 packet
```

Chunker 从持续文本中选择候选边界；JEV 判断内容是否适合发布，并复核是否明显偏离当前表达策略；TTS 默认继续接收多个已批准片段。§6.5 只允许首段在隔离区提前合成，不能改变播放发布资格。音频 packet 按自己的时间轴播放。

### 8.2 Chunker 原则

优先完整短句，其次可自然停顿的分句。首段可以更短，后续片段可以更长。长度与等待时间只是候选触发条件，不能覆盖语义约束。

特殊处理否定、转折、条件、数量单位、人名、日期、小数、引号、代码和 URL。不要把“我不认为……”拆到用户以为系统认同，也不要把“可以，但前提是……”只播前半段。

过了 chunk 等待阈值却没有安全边界时，继续等待或选择短反馈，不能强行切字。

### 8.3 JEV Output Decision

输入包含原用户输入、角色状态、已播放前缀、当前候选、有限后续文本，以及真实 tool 状态。

```json
{
  "release": "allow",
  "speech_act": "answer",
  "style": "thoughtful",
  "pace_intent": "normal",
  "needs_following_context": false,
  "persona_fit": "acceptable",
  "unsupported_claim": false
}
```

这是内部归一化结果。真实 TypeSafe 原语与返回概率由 adapter 保留，不能把示例当厂商 SDK。

代码做最终组合。内容是否可发布、是否仍基于最新输入属于 hard gate；风格选择属于 preference。风格超时只能复用仍有效的上一策略或经审核的保守默认；内容检查未通过则不能以“默认 allow”跳过。输入语境已实质变化时，旧风格和旧内容都不得自动复用。

JEV 对输出事实的判断不是外部事实验证器；没有证据就不能证明某个答案正确。高风险或依赖工具的事实需要相应证据才能发布。

### 8.4 输出队列：未冻结候选可替换，冻结片段必须保序

| 数据 | 合同 |
|---|---|
| 原始 LLM delta | 有序累积，不能 latest-only 覆盖 |
| 正在组装的同一候选 | 冻结前可修改；修改增加版本 |
| 已冻结待审片段 | 有界 FIFO；编号、文本版本、内容摘要值固定 |
| 判断结果 | 按片段编号和精确版本归还；乱序到达不能乱序发布 |
| 独立风格偏好 | 作用域内可合并，不携带或覆盖正文 |

每个冻结片段至少带 `generation_id / output_epoch / chunk_id / sequence / text_revision / text_digest / basis_input_revision / policy_revision`。摘要值由固定版本的文本规范化方式计算；外部检索结果或文本里的字符串不能伪造审批身份。

“一个 output in-flight”可以保留，但 pending 必须是有界有序片段队列，不是 latest-only。批量判断可把连续片段作为一个请求的输入，并明确返回每段范围；同一请求内问题不能暗中依赖其他问题的输出。

例：A“这个方案可以做”、B“但必须先确认授权”、C“然后测试延迟”。A 正在判断时，C 到达不能覆盖 B。若 B 未通过，则 B 及依赖它的后续片段暂停／失效，不能跳过 B 播放 C。运行时只推进**连续已批准前缀**；多段共同表达一个条件时，可以作为一个不可拆审批单元。

若实现选择累计快照而不是逐段队列，必须包含所有未处理正文及片段范围，并以相同的连续前缀规则发布；不接受含义模糊的 `latest pending`。

### 8.5 队列背压与内容截断

冻结队列满时先停止冻结更多候选，将后续 delta 保存在另一个有界文本缓冲。暂停读取网络并不代表供应商停止解码；整个未播文本缓冲、token 预算或等待上限达到硬边界时，取消分支、显式记录截断原因，废弃所有未播尾部，以已播放账本决定是否续接。

禁止丢掉中间片段后继续发布后面的片段；禁止把缓冲截断当正常完成而发布缺少条件的半句话。截断、拒绝、超时都要有明确事件，不能静默“跳过一个 item”。恢复只从确认上下文和有效输入重建。

## 9. Performance Adapter 与 Streaming TTS

### 9.1 每个 voice 都有能力记录

```text
provider + model + voice_revision + locale + region
  → input_streaming
  → output_streaming
  → custom_voice
  → supported_controls
  → control_scope: stream | segment | request
  → cancel_scope: stream | context | none
  → supports_hold_between_inputs / observed_idle_timeout
  → produces_audio_before_finish_input
  → alignment_support
  → sample_format
```

未知能力不按支持处理。`playful`、`rising` 是本项目表演意图，不是普遍存在的 TTS 参数。

对 Google 首选路径：语速按已验证的 streaming config 使用；停顿依指定 markup 规则使用；任意情绪、音高、重音不承诺可直接设置。SSML 不发送到不支持它的流式接口。[S06]

### 9.2 流的生命周期

```text
open(config) → push(approved text)* → finish_input → drain → close
                                    ↘ cancel_all
```

Google 要求首个消息配置、后续消息输入；因此不能假设每个 chunk 都能在同一流里修改 voice 或 speaking rate。[S05][S08]

默认一个有效 generation 尽量使用一个连续 TTS stream，表演参数在一个语音段内尽量稳定；这不是“一旦开流就永不重开”的保证。确实需要换 voice/全局配置时，在自然边界结束旧流、再开新流，接受相应开流和衔接代价。

不要默认每个小片段一个并行 TTS worker，否则会引入乱序、角色声音漂移、句间韵律断裂和重复开流成本。

### 9.3 音频与文本对齐的诚实边界

供应商可能只返回 PCM，不返回精确逐字时间。一个音频 packet 也未必对应一个输入 chunk。

本项目强制精确到 stream 与 sample 的取消与播放记录；文本对齐则记录 `exact / estimated / unknown`。没有对齐时，不虚构“用户已听到第 23 个字”。

若无法局部取消某个 TTS 输入，任何已发送片段失效都取消整个旧流与未播尾部。之后基于确认已播放的前缀及末段不确定范围续接，不重播完整旧回答；缺少对齐时不能保证逐字零重复。

### 9.4 隔离音频提升与流完整性

实验首段在服务端 `review_quarantine` 中保存；它不是客户端 jitter buffer，也不是已批准音频。JEV 通过后，只有精确文本／参数版本一致、分支仍有效、外传许可仍有效时才能提升为正常音频。审批拒绝或超时立即关闭对应流并清理隔离区。

同一流不得混入第二个未批准文本。已发送内容后来失效且不能按真实对齐局部切除时，关闭整条流并取消未播尾部。不能拿字数比例或网络包号冒充文本对齐。首段无法在保持流输入开放时生成音频的 provider，必须把重开流成本计入实验，或禁用该路径。

### 9.5 三个进度位置与领先窗口

分别记录文本已生成范围、音频已合成 sample 范围、客户端已输出／估计输出的 sample 范围。明确哪些是可测值、哪些是估算；没有文字—音频对齐时，不计算伪精确“还领先多少字”的指标。

| 阶段 | 可实施控制 | 不能假设 |
|---|---|---|
| Luna 文本领先 | 输出长度、token／字节预算、取消与基于已播前缀续接 | 暂停消费流会暂停远端生成 |
| TTS 合成领先 | 根据待播音频时长设置高低水位，暂停送入后续已批准文本 | 不继续 push 文本就不会再有在途音频到达 |
| 播放器调度领先 | 只预调度短且可撤销的音频范围，逐步检查许可 | 蓝牙／系统设备内部缓冲可全部瞬时清空 |

先使用固定、可调的水位建立基线。自适应模式作为独立实验：稳定解释可使用较大准备量；近期有反复插话／纠正时使用较小准备量；用户长讲且转写不稳定时只保留预算内预取／文本推测，不进行新的音频推测。表达计划决定说法，不直接改变安全水位。

高水位停止继续送文本，低水位恢复；单次 push 的文本也有上限。已经送入 provider 的文本仍可能继续产生音频，所以所有服务端音频队列设共同硬上限；突破上限就按分支取消合同处理，不丢中间音频并假装续流。

隔离合成、暂停保留、正常 ready queue 应合并计量（同一段音频移动队列不重复计费），另记客户端播放缓冲。暂停预算到期或不支持安全恢复时，取消旧分支；不通过无限合成等待用户结束。

## 10. 预制等待语音系统

### 10.1 设计目标

降低等待的不确定感、维持角色连贯性，但不把 filler 算成答案，也不以不断垫音掩盖故障。

需要更正前面讨论的一点来源解释：OpenAI 的 Realtime prompting 指南鼓励在合适的工作场景用简短 preamble，但示例也明确建议避免反复 “Hmm”“Let me think”等 filler。[S11] 因此本项目的角色化“嗯/我想想”是**有边界的产品实验**，不是直接照抄官方推荐。

### 10.2 三种语音行为

| 行为 | 作用 | 允许时间 |
|---|---|---|
| Backchannel | 表示仍在听，不取得话轮 | 用户讲话中的适当间隙；MVP 默认关闭 |
| Thinking filler | 有限地填补回答等待 | 已获话轮、答案未就绪、语境允许时 |
| Operational preamble | 告知真实正在进行的动作 | 对应动作确实开始或获准时 |

“对”“是的”含有认同含义，不能作为通用加载声。“我查一下”只在确实查询时使用。“这个肯定能做”是实质断言，不是安全垫音。

### 10.3 音频资产

预先制作少量高质量、多韵律的短片段。与正文使用同一授权声源、voice revision 和响度规范；会话开始前下载并解码到客户端内存，避免首次播放才解码。

```text
FillerAsset
  asset_id / voice_revision / locale / content_hash
  transcript / speech_act / style
  duration_samples / sample_rate_hz
  safe_exit_samples[]
  semantic_effect
  prerequisites / forbidden_contexts
```

`safe_exit_samples` 是人工或离线标注的自然退出点，不能任意切半个词。资产换声音版本后重新生成、审核、失效旧缓存。

### 10.4 JEV 选择，Runtime 决定何时播

JEV 在用户讲话期间输出工作类型、语境适配性、允许的 speech act 或资产候选；它不需要精确预测毫秒。

Runtime 预测的是**距离第一段真正可播放答案还有多久**，而非仅 Luna TTFT。输入包括已经过时间、LLM 是否已有文本、chunk 是否批准、TTS 是否开始、网络/供应商历史分位数、工具状态和客户端队列。

当前请求的真实 cache hit、服务器队列和内部负载未必可见；只使用已经观测到的值，不把预测当作事实。

### 10.5 截止时间策略

```text
用户声学结束候选出现
  → 记录本轮 deadline
  → 继续判断话轮与生成答案

到 deadline：
  用户仍说话 / 新活动阻断 / 输入或任务版本失效 / 无新鲜许可 → 不播
  实质答案已就绪 → 优先播答案
  filler 不适合 / 本轮已播过 → 保持短静默或 UI 状态
  filler 合适、资产已加载、许可有效 → 播一个短片段
```

预测只帮助预选；deadline 与真实 runtime 状态决定是否执行。确认话轮较晚时，不能为了追赶 deadline 抢话。

初版每轮最多一个 thinking filler，设置跨轮冷却与资产去重。超过真实任务超时进入明确失败/进度反馈，不能循环“嗯”。

### 10.6 与答案抢占

答案在 filler 尚未开始时准备好：取消 filler。

答案在 filler 已开始时准备好：在最近自然退出点切换，并限制最大等待尾部。不要为了完整播放一个长“我想想”拖延已经完成的答案。

用户插话：正文先按 §12 暂停／失效；filler 立即停止并取消未播尾部，不受自然退出点约束；使用很短淡出抑制爆音。thinking filler 不因正文后来恢复而从半句话继续播放，也不再次消费本轮次数。

本项目分别记录 `filler_added_answer_delay_ms`、重复率、误触发率以及用户是否因 filler 再次开口。短静默有时比不合时宜的表演更好。

### 10.7 等待语许可必须绑定有效工作

```text
WaitingAudioPermit
  permit_id / permit_revision / session_id
  input_epoch / validated_revision / observed_activity_seq
  task_id / generation_id / output_epoch
  wait_reason: first_answer | tool_wait
  task_version / speech_act / asset_id / voice_revision
  current_expression_policy_revision
  expiry / single_consumption_key
```

这些是已有任务与许可的引用，不新增一个“发言依据服务”。只有任务确实仍未完成、语境适合、资产已解码、角色声音版本有效且当前 speech act 获许可时才可播放。倒计时不是发言理由；用户说“算了”后，即使 deadline 到达也不播。

`first_answer` 在正文已经开始后失效；音频中途欠载不重新触发首答 filler。真实工具等待使用对应 task 状态并遵守每轮预算，不能虚构工具正在运行。Backchannel 保持独立许可和默认关闭，不能借正文暂停恢复机制偷偷启用重叠输出。

次数、冷却和去重按**逻辑用户话轮**计数，不随 generation 重启清零。客户端许可消费与播放回执幂等；回执丢失时先查询／保持已占用状态，不重新播放同一个 asset。已实际输出的 filler 写入 Delivered Ledger，未播的预选资产不写成已说话。

## 11. Commit Boundary 与版本协议（0.2，破坏性语义修订）

### 11.1 计算资格、内容资格、播放资格相互独立

```text
默认：DRAFT → CONTENT_APPROVED → SYNTHESIS_ALLOWED → AUDIO_READY
                                                        │
                                                   新鲜播放许可
                                                        ▼
                                                DELIVERED_ESTIMATED

实验：FROZEN + EXPORT/SYNTHESIS_AUTHORIZED
          ├─ 内容审批 ─────────────────┐
          └─ TTS → AUDIO_QUARANTINED ──┤
                                      ▼
                 审批与输入有效性通过 → AUDIO_READY → 新鲜播放许可
```

在实验路径中，不能从 `SYNTHESIS_ALLOWED` 推断内容已经批准。`PAUSE_OUTPUT` 撤销播放许可但可以暂存工作；`INVALIDATE_BRANCH` 永久废弃该分支。已输出的声音不可撤销，尚未输出的每个 sample 都仍受有效许可约束。

### 11.2 分离声音观察、输入版本和分支有效性

| 字段／状态 | 所有者与含义 | 变化规则 |
|---|---|---|
| `activity_seq` | 客户端的本地新活动／停止观察序号 | 每次需要立即抑制输出的新声音事件或明确停止递增；重复消息用相同序号 |
| `input_epoch` | 服务端 Actor 分配的逻辑用户话轮 | 确立新的语义话轮才变化，疑似声音不直接改变它 |
| `input_revision` | 当前逻辑话轮的规范化转写快照版本 | ASR 修订／补充导致文本改变时递增；只是声音事件不伪造文字版本 |
| `output_epoch` | 服务端当前输出分支的代际 | 永久失效／替换旧分支后递增；单纯暂停不改变 |
| `generation_id` | 一次主模型生成及其输出依赖的标识 | 重生成产生新 ID；相同分支恢复不产生假新 ID |
| `permit_revision` | Actor 单调递增的播放控制版本 | 每次授予或撤销许可递增；客户端记住已见最高版本 |
| `branch_validity` | `valid / invalidated` | invalidated 是终态，不因迟到结果恢复 |
| `playout_state` | `ready / playing / paused / stopped / drained` | 与远端任务是否完成分开；任务完成的音频也可以暂停再恢复 |

`input_epoch` 不再由客户端 VAD 直接递增；这是与 v0.1 的关键不兼容项。新的声音先使本地旧许可失效，语义判断后再决定保留、续接或新话轮。当前收到的关键 ASR 修订也撤销相关资格，不必等待最终分类才阻止旧回答。

媒体包保留生成时的来源字段；恢复时通过新许可重新授权同一有效 stream，**不能把旧包的来源 revision 改写成最新版本以绕过检查**。origin 与 validated 是不同信息。

### 11.3 内部事件信封

以下字段是本项目合同，不是供应商 schema。`input_epoch` 在媒体包中表示其生成来源。

```json
{
  "schema_version": "0.2",
  "type": "tts.audio_packet",
  "session_id": "s-example",
  "input_epoch": 12,
  "output_epoch": 9,
  "generation_id": "g-9",
  "basis_input_revision": 7,
  "stream_id": "tts-9",
  "sequence": 41,
  "clock_id": "server-monotonic",
  "timestamp_ms": 100123.4,
  "trace_id": "trace-example"
}
```

音频 payload 另有 `format / rate / channels / first_sample / sample_count`；热路径使用二进制，不默认 JSON base64。媒体包自身不授予播放资格。隔离音频在内容批准前不离开服务端。

播放／恢复许可示例：

```json
{
  "schema_version": "0.2",
  "type": "playout.permit",
  "session_id": "s-example",
  "permit_id": "permit-28",
  "permit_revision": 28,
  "observed_activity_seq": 32,
  "input_epoch": 12,
  "validated_input_revision": 8,
  "output_epoch": 9,
  "generation_id": "g-9",
  "stream_id": "tts-9",
  "speech_act": "answer",
  "resume_from_sample": 19200,
  "sample_rate_hz": 24000,
  "reason": "revalidated_after_backchannel"
}
```

同一素材来源 revision 7 可以在新输入 revision 8 上被验证兼容；许可明确记录这一事实。不同 output_epoch 或已经作废的流不能这样恢复。`resume_from_sample` 来自输出回执与缓冲状态，不由文字长度猜测；不确定到无法安全恢复时走 §12 的保守重建。

### 11.4 播放前最终检查

```text
会话／客户端实例匹配
AND 本地没有显式停止锁、未决暂停或不允许的用户重叠讲话
AND permit.observed_activity_seq == local.current_activity_seq
AND permit_revision 不落后于已见控制版本且许可未撤销／过期
AND permit.input_epoch / validated_input_revision 对应已同步当前有效输入
AND packet.output_epoch / generation_id / stream_id 与许可和有效分支一致
AND 该音频所依赖的正文已批准且未被撤回
AND floor 允许该 speech act
AND sample 位置合法、不重复、顺序与播放账本兼容
```

客户端不运行云端语义判断；它检查 Actor 的授权与本地新观察是否一致。输入状态同步和 grant 有明确顺序，缺失时 hold 而不是猜测。明确停止在客户端设置 latch；不能被迟到 grant 清除，只能在用户后续新的有效交互中按协议解除。

期限使用声明的 clock 与可验证映射；没有可靠时钟映射时不得直接比较两台机器的单调时钟。每次回收／续发许可都在短调度窗口边界复核当前活动序号和控制版本，不以一次长授权放行全部缓冲。

可暂停分支的音频暂存区不是可播放队列；永久失效分支的迟到包立即丢弃。取消／撤销消息也携带单调控制版本，防止重传或乱序 grant 复活旧声音。

**保证边界：**本地停止观测后立即撤销本地资格；服务端新事实失效传播到客户端仍有网络延迟，设备已提交的尾部也不可撤回。这两部分单独计量，不能宣称远端取消发生的同一瞬间物理上绝无尾音。

## 12. 打断、暂停、恢复与播放缓冲

### 12.1 本地先停声音，不默认先废弃全部计算

疑似用户发声触发 `PAUSE_OUTPUT`：客户端递增 activity_seq，立即暂停／短淡出正文，撤销现有播放资格，记录输出进度并通知服务端；不等待 JEV、Luna 或 TTS 的网络响应。噪声、键盘、回声等是否需要先 duck 由已测本地策略决定，不以未经校准的固定音量阈值替代全部判断。

明确的停止按钮或确定的停止指令触发 `STOP`：本地 latch、清理可播放尾部并通知 Actor 永久失效当前分支，不等待一次额外的语义投票。未完全识别的可能停止词先立即暂停，判明后永久停止。

### 12.2 语义确认后的状态转移

| 事件／判断 | 播放处理 | 生成／缓冲处理 |
|---|---|---|
| 新活动，类别未知 | 立即暂停；旧许可不可再用 | 有界暂存仍未失效的工作 |
| 确认噪声／短附和，原回答仍有效 | 新鲜许可后从实际进度恢复 | 可保留同一 generation／stream |
| 补充兼容细节 | 保持暂停直到确认如何继续 | 仅在原回答仍回应当前输入时复用 |
| 纠正关键事实 | 不发布依赖旧事实的未播后缀 | 默认失效整条未播分支并续接；只有真实依赖和音频对齐允许时才局部保留 |
| 明确停止／换话题 | 停止、清理、旧分支不可恢复 | 取消旧请求并增加 output_epoch；后续新请求使用新 generation |
| 判定超时／不确定／保留预算耗尽 | 不以超时为“可以恢复” | 关闭优化，永久取消旧分支；等待明确输入再生成 |

“兼容补充”不是把新事实偷偷塞进仍在运行的普通文本 API。当前接口不能动态更新输入时，冻结已播前缀，取消旧请求，基于最新快照重新发起续接；不把任意 API 当作可暂停后原地编辑的模型。

### 12.3 暂停保留必须有预算

暂停期间，Luna／TTS 可能仍在计算。配置最大保留时间、追加音频预算和总文本／音频硬上限；达到任一边界就取消，不能无限生成等待用户说完。停止向 TTS push 文本只限制新增输入，不阻止已有输入继续产出；停止读取 LLM 流也不代表节省了模型计算。

暂停允许同时保留音频和文本，但不能让暂停分支的推测占满其他真实回答的配额。明确无效时立即停止，不为提高“复用率”继续保存。

### 12.4 恢复不是重新启用旧许可

恢复前必须满足：分支未永久失效；最新输入已检查兼容；新许可看到客户端最新 activity_seq；播放器游标与待播音频连续；内容批准仍有效。再从已确认输出位置续播，而不是重新播放整段。

音频播放位置与逐字对齐是两个问题：即使 TTS 没有逐字时间，只要客户端 sample 进度可靠，仍可恢复 PCM。若播放器不能确定设备输出尾部／剩余队列，不能猜精确位置或盲目重放；记录不确定范围，放弃自动恢复并从已确认完整语义前缀安排续接。自然度与尾音误差通过真实设备验收。

已经永久失效的分支，无论恢复开关、迟到判断或重连怎样变化都不能复活。`generation` 已生成完成也不等于分支失效，其有效但未播音频可以按上述规则恢复。thinking filler 被暂停后取消余部，不作为正文一样恢复。

### 12.5 三层缓冲与能力回退

| 缓冲 | 内容 | 策略 |
|---|---|---|
| 服务端推测／审批隔离／暂停暂存 | 尚未获得当前播放许可的工作 | 分别标记资格，统一有限预算；不得混作客户端可播数据 |
| 客户端 ready／jitter buffer | 已通过内容检查但仍需本地许可的音频 | 有界、保序、可以撤销未播区间 |
| 设备／系统输出 | 浏览器、音频驱动、蓝牙等已提交音频 | 记录实测尾部，不能假设全部可清空 |

v0.2 要实现独立的暂停／失效协议；`pause_resume.semantic_resume_enabled` 默认关闭，只有 adapter 与设备回执测试通过后才启用语义恢复。关闭时仍先执行即时本地暂停，随后保守取消；这不是恢复失败后偷偷继续播放。

不支持安全恢复的 provider／sink 使用 stop-and-regenerate 回退。缺少能力只牺牲复用优化，不能牺牲停止、权限、会话隔离和新鲜度。

## 13. 对话事实账本与长期记忆

分别维护：

```text
Generated Ledger       模型生成过什么
Synthesized Ledger     服务合成过什么
Delivered Ledger       设备估计播放了什么
```

下一次主对话上下文以已确认的用户输入和 Delivered Ledger 为基础，不把未播答案当成“已经告诉用户”。filler 记录为 dialogue act，不能丢掉后让 Luna 再重复同一句。

TTS 无逐字对齐时，Delivered Ledger 只声明已确认完整片段、被打断的片段和 sample offset。对不确定已播词序加 unknown，不用字数比例假装精确对齐。

重用供应商 conversation/previous response 引用前，确认它不会把被取消分支的完整回答带回上下文；否则使用自己维护的显式历史重建请求。

长期记忆只从确认后的用户事实与互动生成。推测内容、JEV 暂时猜测的情绪、未播放回答都不直接写入。记忆有来源、版本、用户纠正和删除入口。

暂停时记录游标和尾部不确定范围，不把整个暂停队列写成已说出。恢复时按 stream/sample 更新同一条交付记录，不重复追加整段历史；永久取消后保留交付前缀和显式截断标记。ExpressionPolicy、JEV 的暂时判断和未消费 filler 许可均不进入长期事实。

输出队列溢出或首段审批拒绝导致续接时，只使用真实已播账本；不能把“审核过但尚未播放”当作用户已听到。无逐字对齐时，续接上下文必须披露已知完整片段与不确定末段，不能保证一个未知单词也绝不重复。

## 14. 延迟模型与目标

### 14.1 统一定义

`t_end`：用户实际最后一个相关音节结束，由测试标注或客户端声学估计获得。  
`t_gate`：当前有效分支获得播放资格。  
`t_ready`：首段实质答案的非静音音频在客户端达到可播放条件。  
`D_sink`：从条件满足到实际输出的调度/设备残余延迟。

不含 filler 竞争时：

```text
L_answer = max(t_ready, t_gate) - t_end + D_sink
```

推测主要让 `t_ready` 提前；话轮判断优化 `t_gate`；播放器优化 `D_sink`。只有候选最后有效时，提前计算才算被隐藏。

Filler 另记 `L_feedback`，不能代替 `L_answer`。已有首 token 不代表已有语义安全片段，更不代表有可播放音频。

### 14.2 演算示例，不是 benchmark

| 时刻（相对用户结束） | 事件 |
|---:|---|
| -650ms | 开始当前有效候选生成 |
| -160ms | 首个候选文本片段形成 |
| -40ms | 输出检查完成，开始 TTS |
| +130ms | 第一段有效非静音音频在客户端就绪 |
| +180ms | 最新输入验证与话轮许可完成 |
| +220ms | 音频真正输出 |

这个例子成立的前提是用户后续没有推翻候选，且最新验证已经完成。若候选被推翻，必须按重算后的时刻计算。

另一种例子：+350ms 触发短 filler，+520ms 答案准备好，+570ms 到达自然退出点并开始正文。此时反馈延迟约 350ms，答案延迟约 570ms，而不是“系统 350ms 回答了”。

### 14.3 初版实验目标

以下为设计目标，需按浏览器、设备、语言、区域、网络和任务分别报告；不满足时如实记录。

| 指标 | 初版目标/策略 |
|---|---|
| 普通、无工具短回合实质回答延迟 | 挑战目标 p50 ≤ 500ms，p95 ≤ 1200ms |
| thinking filler 触发检查点 | 声学结束后约 350ms，必须同时满足话轮和语境许可 |
| 本地用户插话到输出静音 | p95 ≤ 150ms；蓝牙等设备单独分组 |
| 每轮 thinking filler | 最多 1 个，默认不使用重叠 backchannel |
| 过期 generation 重新出声 | 确定性/故障注入测试中为 0 |
| filler 导致答案额外等待 | 单独统计，限制自然退出尾部 |

用户继续说话却提前播放的样本应记作抢话错误，不能把负延迟当作好成绩。

### 14.4 首段检查／合成并行的局部预算

从同一冻结候选、参数和授权已确定的时刻计量：`D` 为内容检查实际等待，`T` 为该 TTS 路径取得首音频的实际等待。默认串行局部等待为 `D + T`；可并行且候选有效时约为 `max(D, T) + promotion_overhead`。

这不是整体端到端公式：隔离提升、向客户端发送、网络、floor 与设备仍须计入 §14.1 的 `t_ready / t_gate / D_sink`。`T` 如果只测服务端首包，就不能再称客户端首音频。前置外传检查和必须等待的风格判断也不是免费。

逐条 trace 计算收益，再统计分位数；不能把 D 的 p95 与 T 的 p95 简单取 max 当端到端 p95。检查拒绝、输入变化和流重启的样本必须纳入，不能只统计实验成功轮次。

## 15. Latency Harness 与观测

每条事件包含 trace/session/turn/generation/epoch/revision，以及所属 clock_id。不同机器的单调时钟不能直接相减。

记录的关键事件包括：

```text
client.audio_captured
asr.partial_received / asr.revised
decision.input_started / completed / stale
speculation.started / invalidated / reused
user.acoustic_end_estimated
turn.playout_allowed
llm.request_started / first_text / first_candidate
decision.output_started / completed
chunk.synthesis_allowed
tts.request_started / first_bytes / first_non_silent_audio
client.audio_ready
client.filler_started / ended
client.answer_started / stopped
client.interrupt_detected / server.cancel_applied
input.snapshot_coalesced
output.chunk_frozen / queued / approved / rejected / explicitly_invalidated
output.queue_high_watermark / hard_limit_reached
output.pause_requested / paused / resume_permitted / resumed / invalidated
playout.permit_granted / revoked / stale_rejected
expression.policy_created / reused / expired / late_preference_ignored
tts.quarantine_started / promoted / discarded
tts.feed_paused / resumed
filler.permit_expired / revoked / consumed / duplicate_rejected
```

客户端使用音频 sample 时间与 Web Audio 输出时间估计播放位置。`getOutputTimestamp()` 提供输出流位置与 performance clock 的映射，但这是估计；不能把 `play()` 或某次 JS callback 当作扬声器发声的实测。[S12]

严谨验收使用同一设备的音频 loopback 或外部录音，对齐用户最后音节与角色声音。线上保留误差边界，绝不把服务器首包当最终体验。

看板同时显示：首反馈/首实质回答 p50/p95/p99、打断尾音、抢话率、假打断率、回滚后残音、ASR revision、候选利用率、推测浪费、TTS underrun、角色漂移、filler 使用/重复/误触发率与每分钟成本。

不只看 `answer_start - semantic_end_confirmed`，因为它可能通过延后 semantic end 把等待隐藏在指标外。主指标从用户声学结束计算。

v0.2 额外记录：每轮取消与重启数、暂停至恢复耗时、误恢复率、输入快照合并量、冻结输出完整性、JEV 输出真正暴露的阻塞时长、并行合成节省的等待、审批失败浪费、paused retention 预算耗尽、TTS 重新开流次数、各层峰值队列字节／音频时长、连续表演变化频率。

效率结论必须同时报告延迟和错误／成本。播放 faster 但漏了限定句不算优化；恢复 faster 但继续说旧事实不算优化；服务器取消失败的残余计算也计入浪费。

## 16. 超时、故障与降级

| 故障 | 必须行为 |
|---|---|
| JEV 输入判断超时 | 关闭本轮激进推测，使用保守话轮策略；不要抢话 |
| JEV 输出风格迟到 | 复用仍有效策略或经审核的保守默认；不因装饰性偏好重启正确正文 |
| JEV 输出内容资格未知 | 停止发布；实验路径取消隔离 TTS，按已批准前缀／已播账本收口；不默认 allow |
| Luna 长等待 | 一个适配短反馈后保持真实进度；到上限显示/说明失败，不无限填充 |
| Luna 输出中途断流 | 保留已播前缀，废弃未完成片段；不重播全文 |
| TTS 中断 | 关闭旧 stream、清尾音，提供文本/明确错误；不悄悄切陌生声音 |
| ASR 长流重连 | 按音频时间和 segment 去重，避免重复用户话轮 |
| 播放端断开 | 服务端取消相关推理和 TTS，按最小策略保存确认账本 |
| 新 voice 权限失效 | 停用该声音与缓存；显式选择已获授权的替代 |
| 429 / 配额不足 | 降低推测与判断频率，bounded retry；不在热路径无限指数退避 |
| 老任务永久取消后又返回 | 分支代际和撤销记录检查后丢弃，不得复活 |
| 暂停后的在途音频返回 | 仅进入预算内暂存，不自行恢复或提升播放许可 |
| 输出冻结队列满／文本硬上限 | 不覆盖中间片段；先背压，硬上限时取消未播分支并显式截断 |
| 隔离首段被拒绝或版本改变 | 全部丢弃该流隔离音频，不把旧批准迁移到新文本 |
| 语义恢复判断超时 | 不自动恢复；保守取消并等待明确输入 |
| 恢复游标能力未知 | 禁止无证据重放，使用已确认前缀的续接回退 |
| TTS 等待新文本时断流 | 显式计为 reopen／失败，不偷偷拼接不同流或重复上一句 |
| filler 定时器已触发但任务取消 | 废弃许可，不播；generation 重启不重置本轮次数 |
| 协议版本不匹配 | 拒绝握手或显式重建新会话，不静默转换 0.1 epoch 语义 |

降级只牺牲激进优化或表演细节，不能牺牲会话隔离、用户打断、内容权限和事实新鲜度。

## 17. 客户端、传输与部署

### 17.1 最小验证系统

建议 TypeScript 浏览器客户端 + AudioWorklet，Python 异步服务，供应商适配器和单进程 Session Actor。初期使用有界 PCM 流与独立控制通道的 WebSocket，便于精确验证 epoch、取消和播放回执；服务端长期复用供应商连接/客户端对象。

这是**受控网络 PoC**，不是“WebSocket 一定优于 WebRTC”的结论。TCP 丢包阻塞、移动网络和设备缓冲必须纳入真实网络验证。生产低延迟传输保留 WebRTC adapter，优先复用成熟实现，不手写 RTP/拥塞控制。实际目标若是移动网络，应在宣布性能达标前切到拟上线传输并复测。

媒体接口分离 `audio ingress / audio egress / control / playout acknowledgements`，不让业务状态机依赖某一种 socket。

### 17.2 安全与数据

API 凭据留在后端。客户端只拿 session scoped 令牌与无敏感数据的预制音频。原始麦克风音频默认不落盘；研究录音需明确同意和可配置保留期。敏感文本不直接进入常规日志。

声源必须为自有原创或已授权来源；供应商要求的 consent 不能被普通角色设定替代。[S07] 明确告知合成角色身份。用户输入、转写、检索内容都作为数据，不能覆盖 runtime 规则或改变工具权限。

### 17.3 扩容模型

多 session 时按 actor 分片路由，音频热状态不在每帧写数据库。先按活跃 session、在途调用与队列长度限流，再决定增加服务实例。

假设示例：100 个 session，用户讲话占比 0.4、角色讲话占比 0.4，输入判断 4 次/秒、输出判断 1 次/秒：

```text
JEV QPS ≈ 100 × (0.4 × 4 + 0.4 × 1) = 200
```

即约 12,000 RPM，且还未包括候选重验证。这是算术容量演示，不是已获服务额度。单次便宜/快速不等于任意高频并发都可行。

配额紧张时优先关闭低收益推测与冗余判断，不能让真正的回答排在大量猜测请求后面。

### 17.4 复用边界和迁移

仍使用一个异步服务和原有 adapters。可复用框架的收音、传输、重采样、输出回执与取消，但必须通过 pause/resume、JEV 话轮所有权和隔离音频控制的合同测试；不能在宿主框架自动响应同时再由 Session Actor 触发一次响应。

0.1 与 0.2 的活动／输入／输出版本语义不兼容。握手检查 schema_version；活跃会话不热转换，先结束旧会话并保存已确认账本，再新建 0.2 会话。历史事件按其原版本解释，不批量重写历史 epoch 值。迁移映射见 CHANGELOG。

## 18. 成本模型

```text
每分钟成本 = ASR 音频费用
           + JEV 所有输入与问题的费用
           + Luna 正常与被取消的推测生成费用
           + TTS 正常与被丢弃音频费用
           + 服务端、网络和存储
```

另记 speculative waste：被丢弃生成 token、被丢弃 TTS 音频秒数、无效 JEV 调用比例。取消可能减少后续工作，但不假设已发生的计算免费或自动退款。

预制 filler 的合成是一次性成本，但版本更换、缓存分发和资产审核仍有成本。第一版无需复杂学习型延迟预测器，历史分位数与 deadline 已足够建立基线；数据积累后再验证预测模型是否改善体验。

审批前合成增加了“最终未通过的 TTS”成本；暂停复用可能减少重生成，也可能因等待期间继续计算而增加成本，两者都需报告。表达策略复用减少的是重复决策和暴露等待，不宣称 token／费用必然按相同比例下降。

预算统计同时覆盖用户结束前的 speculation 与完整输入后的 review/TTS overlap；两个实验开关不共享一个错误的免费额度。暂停保留、重复开流和被取消的远端计算分别计量。

## 19. 测试与验收

### 19.1 对照实验

| 组 | 配置 | 要回答的问题 |
|---|---|---|
| A | 最终 ASR → Luna 流 → TTS，无推测/无 filler | 普通组合链路基线 |
| B | JEV 控制 + 输出分段，无推测/无 filler | JEV 与分段的成本、质量收益 |
| C | B + 单候选推测 | 实质回答是否更早，付出多少浪费与误判 |
| D | B + 预制 filler，无推测 | 仅等待表演是否改善主观体验 |
| E | C + filler | 两种优化叠加后的体验与抢占问题 |

原 A—E 基线保留。v0.2 在相同基础链路上一次只加入一个变化：恢复策略关闭／开启、表达策略逐段重判／持续复用、先审再 TTS／首段隔离并行、固定／自适应领先水位。每个比较固定其他实验开关，不把版本整体变化误归因到单一机制。

对照使用同一录音集、相同网络分组和可比输出长度；既有回放测试，也有真人可打断交互。统计冷启动、热连接、长上下文和故障时的结果，不能只选推测成功的轮次。

### 19.2 必测语料

覆盖中文口语、省略、拖长尾音、最后改口、否定/转折、数字金额、人名、英文夹杂、长思考停顿、用户附和、真正打断、背景电视、回声、严肃话题和长对话角色漂移。

语义相同但声学结束不同的样本、声学安静但语义未结束的样本都应存在。人工标注真实话轮边界和“此处是否适合 filler”，不能全靠 JEV 自己评分自己。

### 19.3 确定性不变量测试

```text
永久失效 output_epoch 的 PCM 永不重新进入可播放队列。
暂停但仍有效的 PCM 只能经看见最新本地活动的新许可恢复。
不合法/未授权的候选永不进入正文播放。
用户打断不等待 JEV/Luna/TTS 返回。
音频 packet 按 stream 与 sample/sequence 正确排序。
未播文本不会被记成已说出。
内容改写会使依赖的后续 chunk 失效。
同一 filler permit 不能重复消费。
filler 与正文不同时争用语音输出。
工具 preamble 不宣称未发生的操作。
输出冻结片段 FIFO 不因后续到达而丢掉中间限定句。
同一片段新旧文本版本的检查与音频不可混用。
隔离音频在内容批准前永不外发到客户端。
不准确对齐时不往可播放 TTS 流加入未批准文本。
明确停止锁不被迟到 resume grant 清除。
暂停、审批隔离、文本与音频队列都有硬预算。
超时不等于内容放行，也不等于用户已经让话。
旧 expression policy 不覆盖实质语境变化。
generation 重启不重置 filler 每话轮消费记录。
```

用可控 fake providers 测乱序、迟到、取消失败、超时、断网与重连；用真实 API 测性能。两类证据不能互相替代。

### 19.4 角色验收

角色身份、用词、回应节奏、情绪连续性由盲测听评与长对话样本评价。分别评估声音相似、表演自然、角色稳定，不把一种 embedding 分数当全部质量。

### 19.5 v0.2 行为切片（实施验收待执行）

| 编号 | 场景 | 必须断言 |
|---|---|---|
| Q-01 | ASR 增量到达更快于 JEV | 累积后再合并快照，不丢否定词；最多一份最新 pending |
| Q-02 | A 正审，B 等待，C 到达 | B 不被 C 覆盖，最终 A/B/C 有序发布或显式作废 |
| Q-03 | B 被拒绝、C 已完成 | C 不越过 B 发布；后缀被撤销或重新生成 |
| Q-04 | 队列与原始文本缓冲达硬上限 | 有界取消和截断事件，不静默漏句、不断开权限门槛 |
| P-01 | 用户短“嗯”，允许语义恢复 | 立即暂停，复核后新许可续播，不重复生成或重放整个片段 |
| P-02 | 用户纠正“周二”为“周三” | 依赖旧事实的后缀不得继续，基于已播前缀续接 |
| P-03 | 用户明确停止后旧 grant／包迟到 | 本地锁与分支失效共同拒绝旧音频 |
| P-04 | 新一次本地声音发生在 grant 传输中 | 旧 activity_seq 的 grant 被拒绝 |
| P-05 | 恢复请求前远端任务已经完成 | 有效音频仍可恢复；completed 不被误判成 invalidated |
| P-06 | 暂停超时或保留预算满 | 不自动恢复，取消分支并有明确回退 |
| P-07 | 设备回执不精确 | 报告未知范围；不能伪造逐字或 sample 精确恢复 |
| E-01 | 表达偏好晚到，正文正确 | 不因装饰变化重启；仅影响未来允许的范围 |
| E-02 | 轻快语境转为严肃话题 | 旧策略失效，不用旧风格当默认复用 |
| X-01 | 首段审批慢、TTS 先返回 | 仅服务器隔离，审批前零客户端音频外发 |
| X-02 | TTS 先完成后审批拒绝 | 清除隔离与该流；没有残音提升 |
| X-03 | 审批版本 A，合成文本／参数变 B | 不共享批准；旧流取消、新版本重审 |
| X-04 | 首段后还有未批准片段，无词对齐 | 第二个未批准片段不得加入该流 |
| X-05 | 无用户结束前推测，仅启用审批并行 | 可独立测量，两个开关不串为必需依赖 |
| H-01 | 已推给 TTS 的文本继续吐音频 | 硬预算仍有效，不因停止 push 就漏算在途音频 |
| H-02 | 模型忽略期望短答而持续生成 | token／字节预算收口，不靠暂停读 socket 假装远端停止 |
| F-01 | deadline 到前用户说“算了” | task/输入资格失效，绝不播放旧 filler |
| F-02 | 同轮 generation 重启和回执重传 | 每轮限额、许可幂等和去重仍成立 |
| F-03 | 正文中途音频欠载 | 不触发首答 thinking filler |
| M-01 | 0.1 客户端尝试接入 0.2 服务 | 握手显式拒绝／新建会话，不混用旧 epoch |

这些是待实现测试合同，不是本设计交付时已经跑过的运行时测试。真实 API、中文人工标注与物理 loopback 仍是另三类验收；静态文档检查不能替代它们。

## 20. 建议实施阶段

**阶段 A（P0）：队列与播放合同。** 先以固定音频、可控 fake providers 验证输入完整快照、冻结输出 FIFO、版本 0.2、暂停／永久失效、新许可恢复、停止锁、账本和预算。先关闭语义恢复，在能力通过后开启恢复实验；不等待真实模型才能证明旧包不会复活。

**阶段 B：真实基础链路与声音早验收。** 接通一个 ASR、Luna、一个 TTS 和角色基本规则，建立无推测／无 filler 基线。尽早对目标授权声线做短样本及连续通话听评，预设声音仅代表链路通过，不代表角色音色达标。

**阶段 C（P1）：JEV 与表达策略。** 保留输入、输出两处判断，加入非阻塞的表达策略前移和作用域复用，输出检查保序。固定基础模型分别比较策略复用和逐段判断的收益。

**阶段 D（P1，实验）：首段检查／合成并行与领先量。** 完成外传许可、隔离区、版本匹配、取消和硬预算后，再开启 `review_tts_overlap`；与默认先审路径单独对照。固定水位先跑通，再按配置开启自适应水位；不同时打开全部优化。

**阶段 E：预制等待语与输入推测。** 等待语按任务、话轮、speech act 绑定许可并验证幂等；另行逐级启用只读预取、文本推测、首段音频推测，分别测候选利用率、浪费与抢话。A—E 对照矩阵仍保留，不因阶段顺序变化而删去基线。

**阶段 F：真实互动与上线条件。** 中文改口／附和／停止、长角色对话、外放回声、手机／蓝牙、生产传输和并发配额全部验收。更精细的重叠 backchannel、主动发言只有在误判数据足够时再启用。

每阶段的实施交付必须带代码、可重复测试、trace、参数和验收结论；本次文档交付不代表这些阶段已经完成。任何研究性优化都保留关闭开关，不放宽停止、隐私、内容资格和会话隔离。

## 21. 建议代码目录与接口

```text
client/
  audio/capture.ts
  audio/playout-worklet.ts
  audio/playout-arbiter.ts
  audio/filler-bank.ts
  session/epochs.ts
  transport/
server/
  runtime/session_actor.py
  runtime/events.py
  runtime/floor.py
  runtime/speculation.py
  runtime/deadlines.py
  runtime/delivery_ledger.py
  input/transcript_store.py
  decision/input_policy.py
  decision/output_policy.py
  generation/context_builder.py
  generation/chunker.py
  performance/capabilities.py
  performance/filler_policy.py
  adapters/asr/
  adapters/decision/
  adapters/llm/
  adapters/tts/
  telemetry/
characters/
  <character-id>/character.yaml
  <character-id>/voice_manifest.json
  <character-id>/filler_manifest.json
tests/
  unit/
  contract/
  playback/
  replay/
  live/
```

核心接口仅四类供应商适配：ASR、Decision、LLM、TTS；另外一个 transport/audio sink 接口隔离网络与播放器。不要一开始扩成通用 agent 平台。

所有示例字段需经内部 schema 检查；供应商 adapter 另做 provider contract test。模型 ID、locale、voice key、权限、速率限制和真实取消能力由 live gate 确认，不从本方案猜测。

v0.2 的变化继续落在这些文件：`session_actor/events/floor` 管暂停与代际；`input_policy` 管完整快照和表达策略；`output_policy/chunker` 管冻结队列；`speculation/tts adapter` 管首段隔离与预算；`playout-arbiter` 管许可、恢复、停止锁。帮助函数可以在原目录内按需拆分，不引入新的服务拓扑。

配置是版本化合同：移除 output latest-only 字段，显式定义 pause/resume、performance_plan、review_tts_overlap 和 lead_control。未知 schema 或旧字段不静默回落；迁移映射、默认实验开关和静态检查见设计包。

## 22. 发布前必须解决的开放项

| 开放项 | 阻塞什么 | 验证方式 |
|---|---|---|
| 自定义声音权限和音色质量 | “深度角色音色”产品验收 | 实际账户验证 + 听评 |
| JEV 中文话轮/改口判断与错误代价 | 激进推测和自动让话 | 标注集、回放、真人实验 |
| 指定 Google streaming voice 的逐段控制/对齐 | 精细情绪与精确文本账本 | contract probe 与音频分析 |
| Luna 首个安全片段而非 TTFT | 真实低延迟 | 分段 trace |
| 本地 filler 与正文一致的 AEC | 扬声器免耳机使用 | 外放、回声、双人说话测试 |
| 生产传输与移动/蓝牙设备缓冲 | 对外发布延迟目标 | 真实设备 loopback |
| 供应商并发和速率配额 | 多用户上线 | 账户额度与阶梯压测 |
| 暂停／恢复的输出游标与误打断判断 | 同一音频安全恢复 | sink contract、中文附和测试、真实设备回执 |
| 冻结片段 FIFO 与版本 0.2 握手 | 协议正确性 | Q/P/M 系确定性测试 |
| 先审后播但提前外传的授权边界 | 首段审批／TTS 并行 | 输入资格、供应商合同与服务端隔离测试 |
| TTS 首段早产出、等待新输入与断流行为 | 实验并行收益 | exact provider/voice probe，记录重开流成本 |
| 领先窗口对自然度与浪费的影响 | 自适应水位上线 | 固定／自适应同条件消融 |
| 表达策略作用域和严肃场景回退 | 角色持续性 | 长对话／语境切换盲测 |

### 最终验收原则

本系统不是“让模型更早说一个嗯”，而是：**正确判断何时能说，尽可能提前准备真实答案；准备不及时时给出适度反馈；新声音先控制播放，只有确实失效的工作才永久废弃；任何恢复都重新确认内容、输入和播放资格。**

运行效率来自避免无用等待和无用重算，不以漏句、抢话、未经批准外传、旧声音复活或角色表达漂移换取延迟成绩。


---

## 参考来源（继承 v0.1 的记录，本轮未重新联网核验）

以下出处保留原编号与用途，供后续接入复核。原版将来源核查日期记录为 2026-10-02；本版不把这个继承记录当作本轮新增验证。新增运行时合同来自用户确认的修订讨论，不声称由这些来源逐条证明。

[S01] TypeSafe AI, Introducing System One Models & Jev。用于模型定位、并行输出与官方速度口径，不作为本项目性能保证。  
`https://typesafe.ai/blog/introducing-system-one-models-and-jev`

[S02] TypeSafe AI 官方 skill，Build with TypeSafe。用于独立问题组合、概率含义、新鲜度校验和代码执行边界。  
`https://github.com/typesafe-ai/skills/blob/main/skills/typesafe-ai/SKILL.md`

[S03] OpenAI, GPT-5.6 Luna 模型页。用于 streaming、输入输出模态和 reasoning effort 能力。  
`https://developers.openai.com/api/docs/models/gpt-5.6-luna`

[S04] OpenAI, Streaming API responses。用于文本流事件与生命周期。  
`https://developers.openai.com/api/docs/guides/streaming-responses`

[S05] Google Cloud, Synthesize speech with bidirectional streaming。用于流式合成基本协议。  
`https://docs.cloud.google.com/text-to-speech/docs/create-audio-text-streaming`

[S06] Google Cloud, Chirp 3: HD voices。用于流式 SSML 限制、语速、停顿及配置范围。  
`https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd`

[S07] Google Cloud, Chirp 3: Instant Custom Voice。用于 allowlist、中文语言、流式自定义音色与授权记录。  
`https://docs.cloud.google.com/text-to-speech/docs/chirp3-instant-custom-voice`

[S08] Google Cloud, google.cloud.texttospeech.v1 RPC Reference。用于 StreamingSynthesize 请求生命周期；具体 voice 能力仍需按模型指南与 live probe 确认。  
`https://docs.cloud.google.com/text-to-speech/docs/reference/rpc/google.cloud.texttospeech.v1`

[S09] Google Cloud, google.cloud.speech.v2 RPC Reference。用于 interim/final/stability 的语义。  
`https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2`

[S10] OpenAI, Prompt caching。用于稳定前缀、缓存边界与真实命中记录。  
`https://developers.openai.com/api/docs/guides/prompt-caching`

[S11] OpenAI, Prompting Realtime models。用于区分有用 preamble 与滥用 filler；本项目角色垫音政策属于独立设计实验。  
`https://developers.openai.com/api/docs/guides/voice-prompting`

[S12] W3C, Web Audio API 1.1。用于输出时间戳估计与音频时钟语义。  
`https://www.w3.org/TR/webaudio/`
