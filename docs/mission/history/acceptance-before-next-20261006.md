# 1810之后整合前的历史验收记录

以下保留迁移前的说明，仅调整迁移后的相对链接。所有“当前”、默认值和通过数字均按原阶段理解，不覆盖新版[当前验收](../CURRENT-ACCEPTANCE.md)或同包START-HERE。

# 当前交付验收与已知缺口

核对日期：2026-10-06。当前是1515之后的Luna工具、订阅长聊与回归修订候选，最终包号、同一源码的 release 和干净还原结果以同包 START-HERE 为准。下方0438时代记录保留为历史证据，不作为当前软件仍受旧限制或已通过新功能的依据。

## 当前默认运行合同

本修订默认 `action_review_mode=luna_tools`。动作、换装、配饰、表情、场景与章节走真实函数调用、程序前提检查、实际呈现回执和一次工具结果续答；默认不构造JEV服务，不要求其凭据/健康检查，也不使用JEV分块。只有操作者明确选择 `legacy_jev` 才走历史兼容路径。

语义指代和角色意图由Luna判断，程序核当前输入/所引问题回执、有限章节前提、素材、预算、取消和幂等。模型语义仍可能理解错；不能把Mock意图测试说成已证明真实模型正确。合法普通正文与未执行的旧可选提案继续分开，旧字段不会被当作新工具执行。相认后已披露的作者canon保留为第一人称角色往事，不自动变成现实用户共同经历。

普通聊天1次模型请求；工具轮最多1个操作和1次续答，共2次。若工具前后都有语音，最多形成2个独立TTS cue，前一条尾块完成后才请求/播放后一条；普通字幕分块不增加TTS。订阅文字默认不设本机次数/轮数上限；显式有限值仍有效。Google、图片、官方API以及单次超时、并发、背压和取消边界保留原限制。

## 当前交付目标

- 手机、电脑连接同一私有服务，分别配对、独立临时会话；一端取消/刷新/过期不影响另一端。手机语音需要已有两端信任的HTTPS证书，实际网络、TLS和手机权限尚未验收。明文私网HTTP只支持操作者明确选择的文字测试。
- 订阅文字默认用真实空上限取消模型次数和文字轮数；显式本地无限可另取消聆听总时长及本地提交限制。Google、图片、官方API的有限预算与供应商硬限制、背压、取消保留。已复现旧20模型次数耗尽及重复错误轮询关麦，后续修复分别提供明确限额提示和一次性停止副作用；不自动重试或退计数。
- 普通合法正文与错误可选动作/剧情提案分别处理；损坏JSON、非法正文、工具协议错误仍明确失败。先前日志证实过本地候选校验失败；最新日志另确认动态图片runtime未启用、雨衣被旧UNKNOWN审核hold及照片关闭后续答取消。这些观察不等于本修订已在用户设备验证。
- 普通角色聊天保持第一人称，无需主动声明‘故事里’；明确询问AI或现实身份仍诚实。离线提示合同不等于真实模型自然度已通过。
- 固定照片已有用户真实成功观察；动态图片的订阅资格、实际调用及显示链仍未全面验证。启用项、数据同意、剩余进程预算和失败原因可通过check、startup_requested及脱敏日志核对，不自动转付费API。

## 最新1515用户观察边界

用户新日志确认固定照片两次实际软件呈现，后续雨衣/夹克也有匹配回执。旧启动默认20次模型请求在17个普通输入加3次工具续答后耗尽，随后3次输入在本地admission失败；并非这些请求发给模型后被拒。另有独立45/102字节正文JSON语法失败，缺原内容，不能宣称已修好该真实响应。

动态图片在用户显式启用后曾因旧container仍要求JEV导致启动失败，单文件热修已交付。后续新日志证明生成端口返回，但在独立读图前的本地图片校验区间失败；当时仅记录operation_failed，具体像素/尺寸/解码原因仍未知。新闭集诊断是定位能力，不等于真实图片链已成功；没有新增云端账户调用。

## 实际观察与未验证

用户已确认某些交付中的基本文字对话、固定照片显示及一次雨衣换装。用户也报告过无回复、说到换装却没有呈现、音频中途截断及重复出戏。没有证据将这些旧版观察视为本候选全部通过。当前仍缺同版本手机与电脑真实多轮、完整声尾/插话、断线恢复、动态图片及3–5分钟真实演示录像。代码原生人物保留用户已采用基准；局部通过不代表完整美术或音素同步验收。

准确配置与检查步骤见[双设备启动指南](../../development/PRIVATE-DEVICE-TESTING.md)。现有持久记忆、剧情库与会话档案仍按单一操作者配置使用；本轮不自动把两个设备的存档或scope合并。

## 历史修订事实与版本边界（0438之后、0721之前）


- **已交付基线：** `20261006-0438` 包已完成其本地离线检查和还原。其 START-HERE 记录 1,365 文件、13/13 release lanes、4,237 JUnit cases（含 subtests）、906 Node，以及该版本独立最终验收 26 项；这些为原收据引用，本次文档没有重跑。Capture SHA-256 为 `5ebd8d6f574e386c8030a1d819c4a9610a497acd7448531e9eabac0585a3e14c`；release summary 为 `fbb60847f65dd9a216b8ca143d4f1014448dc5156b3729f8be864f2671ed2c6f`；final acceptance 为 `bbebe368cc453e2f096392b5557afed94bdb450b78dea02ec7ad3195c5dd5752`。它们不是本修订的新收据。
- **本修订格式修补：** 默认直连工具路径已加入原生 `text.format` / `json_schema` 请求，按文字/语音、剧情与工具续答选择封闭结构，保留本地 strict JSON、能力、许可与回执检查；不加请求次数、不自动重试或转 API。0438 没有此修补。真实订阅端是否支持所用 schema、是否消除先前 78/72 字节语法失败，仍待同账户复测。没有新 runtime 依赖，不要求操作者安装 `jsonschema` 或重新登录。
- **播放重叠自动提交修补：** 默认自然模式继续记录播放期间的声音/安静及转写；即使早期插话检测未触发或未成功，合格最终语句也可先本地停旧回复再精确提交一次。仅显式保守模式要求逐段核对播放重叠。Stop/关闭、新请求、修订/续说及原有限预算保持，未证明声学回声或同设备完整语音已通过。此变更需要自身冻结检查，不继承0438或格式修订的旧通过收据。
- **确实发生的用户观察：** Mac 的独立 MIRA OAuth 和早期基本文字聊天已由用户确认；0221 修复后固定照片已确认显示。早期声音曾开始播放但被截断。这些证明相应局部体验，不是当前工具、生图、完整语音、全部造型或全产品通过。
- **当前主入口：** `tools/live_provider.py`，订阅优先、官方 API 显式备用，各自授权，不依赖 Codex CLI。默认代码原生 renderer；普通正文独立呈现，JEV负责可选事件及显式文字分块。有限自然转写自动提交和本地插话已经有软件实现，不再是只有手动发送的旧版本；完整设备质量仍未关闭。
- **本页不宣称：** 已有完整手机验收、同版本麦克风→角色→完整可听回复与打断、3–5 分钟实录、生成图账户/像素审核/显示通过、整体美术批准或完整长期记忆/人格学习。

## 原 PDF 必需项及条件项：当前状态

依据是 [6 页原 PDF 的逐项解释](../requirements-and-acceptance.md)，原文件 SHA-256 为 `d71be58c6c66191124e56ba77901913b79fabb2896cdfffb4a5cdf9569042db6`。PDF 核心要求与后来追加功能分开；下面“软件具备”不等于真实体验已验收。PDF 的连续 3–5 分钟产品体验和交付录屏是两项要求，离线成片不能替代真实模型/麦克风主链。

| 原 PDF 项 | 当前能力/实际证据 | 未关闭及下一步 |
|---|---|---|
| PDF-01–05：成年原创角色、场景主体、完整入口、移动/桌面与四态 | 26 岁设定、场景/角色/字幕/文字/语音入口、响应式布局和四态代码已接；有早期 Mac 局部观察。 | 同版连续 3–5 分钟与真实手机/桌面可用性、四态可辨性仍待实测。桌面窄视口不算真手机。 |
| PDF-06、09、25：文字、多轮及页面→服务端→模型 | 用户确认早期基本聊天；直接服务与当前会话上下文已有实现。新修订补格式约束。 | 最新语法失败后的真实复测、连续多轮和状态一致性未完整关闭；HTTP 200、登录或 schema 请求本身不是运行通过。 |
| PDF-07–08：真实麦克风、可听回复与同步字幕 | Google STT/TTS、有限连续监听、PCM 队列、cue 绑定已接；历史听到短回复。 | 同一设备实际麦克风输入、完整可听回复及对应字幕尚须验收，历史组件探针不能拼成完整通过。 |
| PDF-10–16：新语音打断、本地停声、取消旧回复/未呈现结果、继续倾听、迟到隔离与方式说明 | 本地先行 Stop、明确打断按钮、有限声音活动触发、转写身份/旧结果隔离有软件实现；README 解释了保留明确按钮的理由。 | 正在出声时开始新语音、实际声尾、新输入继续处理与迟到不复活，须一次完整真机走查；没有声学回声消除保证。 |
| PDF-17–21：结构化指令、≥3 表情、≥2 非说话状态、环境变化与对话视觉事件 | 四情绪、衣饰、举机/放回、有限头肩转向、雨窗/暖灯及固定照片通路已接；固定照片在 0221 获局部确认。 | 同版真实对话触发、至少三表情和两种非说话状态的可辨实际画面，以及用户美术认可仍待验证。有限 2D yaw 不等于完整 rig。 |
| PDF-22：至少一个多模态分支 | 核心选用代码角色动画；静态 Pixi 全帧保留显式回退。 | 在完整真实互动中验收动画与字幕/语音、取消及降级；技术名称不是合格证明。 |
| PDF-23：选视频时的生命周期 | 未选择视频分支。 | 本分支不适用，不能记为已通过的视频功能。 |
| PDF-24：启用生成媒体时的生成中/失败 | 后来追加可选图片工具、生成与独立读图、pending/held/failed 和回执路径。默认关闭。 | 启用后须验收真实账户生成、等待、失败恢复、取消与显示；当前账户支持未验证，不能再把生成图片功能整体写成“未选所以无需验收”。 |
| PDF-26：超时/断线/音频/媒体失败反馈与恢复 | 安全固定诊断、独立文字保留、Stop 与失败恢复有软件检查；新修订约束生成格式。 | 当前格式修补及各种适用错误在真实设备的恢复体验仍待验证，不能用旧 UNKNOWN 阻塞解释所有新失败。 |
| PDF-27–28：无私密 key 体验、服务/素材来源及凭据排除 | `mock/replay/rehearsal` 有明确标签，不读私密配置；来源、许可和交付排除已有记录。 | 每次最终发布仍须对确切包核对来源/秘密边界；无 key 演示不替代 live 主链。 |
| PDF-D01–D02：源码与演示/清晰启动说明 | 0438 完整三分包加四个 sidecar 已交付；本修订 README 已统一启动。 | 新修订须配套冻结、检查及同阶段恢复包；不能引用旧包作为新代码已发布证据。PDF 不要求特定托管平台。 |
| PDF-D03：一条命令或 ≤15 分钟启动 | 锁依赖就绪后 `sh scripts/dev` 一条命令；历史 Linux 冷项目记录另存。 | 当前版本从声明前提开始计时。既有依赖/旧 Linux 时间不等于全新 Mac/系统保证。 |
| PDF-D04：3–5 分钟可播放实录 | [录制指南](../../development/DEMO-RECORDING.md) 已有。 | **尚无实际成片。** 须实际录制互动、画面/状态、出声中断、所选多模态和失败/降级，并标明版本/模式。 |
| PDF-D05–D07：README、AI_USAGE、未完说明 | 本修订对齐入口、模块、流程/取舍、来源、人工观察、真实 AI 错误、未完项、投入口径与两周方向。 | 文档完整性不补足设备/服务验收；人工工时未单独计量，不杜撰完成比例或姓名。 |

## 后来明确追加的范围

这些不全是原 PDF 硬要求，但用户追加后仍须跟踪，不能用 PDF“可选”撤销。

| 范围 | 当前边界与剩余 |
|---|---|
| 直接订阅与 API 备用、MIRA 自己的 OAuth | 入口已有；已有有效登录/兼容依赖可复用，不复制其他工具认证。非公开订阅后端资格和格式兼容仍需账户实测，失败不转付费 API。 |
| 自然连续交谈、字幕分块、插话 | 有限自动提交、明确手动回退与本地插话已有；分块默认关闭，语音保持完整 cue。回声/噪声、端点质量、完整回复和实际打断待设备确认。 |
| 角色精度、衣饰、第一人称连续性和故事 | 代码原生为默认，四情绪/三衣装/两配饰、有限头肩 yaw 和四节点故事已有；当前输入优先，作者往事不当共同经历。整体美术与真实模型自然度未完整认可，未实现完整多角度/360°、音素同步或长篇完整剧情。 |
| Luna 图片工具、可变虚构 brief、独立看图 | 有工具调用/结果/一次续答及许可/回执软件闭环；custom brief 需单独同意，图片默认一任务/一次生成/至多一次读图。真实账户、质量、显示与额外往返延迟未验收。 |
| 记忆、会话档案与剧情 checkpoint | 三套独立 opt-in 参数/同意/配对已实现，见 [README](../../../README.md)。默认不自动记录；合成 SQLite/回执验证不等于长期真实质量。自动提取、整理、LearnedStance、Hindsight 与完整人格学习未完成。 |

优先次序：先完成当前格式约束的真实兼容/正常回复复测，再同版本验证完整语音与打断/恢复、手机和 3–5 分钟实录；追加图片/记忆/外观按实际范围分别验收。不给自动额外调用、扩大预算或读取私密库以制造通过。可分享的反馈限版本、操作步骤、安全错误类别与诊断编号。

## 历史记录阅读说明

以下完整保留原阶段叙述。出现“当前”“尚未”“下一阶段”均指对应历史日期，不覆盖本页顶部。较早 FINAL_START_GUIDE、DIRECT_PROVIDER_QUICKSTART 和 FINAL_ACCEPTANCE_GAPS 中的原生准入、整句审核阻塞、手动发送和旧发布状态同样保留历史意义；当前操作以 [README](../../../README.md) 与同包 START-HERE 为准。

# 历史候选摘要 — 2026-10-05 14:25 UTC

- **当前交付与真实观察：** 1325完整恢复修复包已通过13/13离线release、2,859 pytest cases＋13 subtests、505 Node、完整还原和本机启动，并已交用户。用户先前已确认真实文字与声音开始播放；完整回复被截断的问题仍待新包实机反馈，不能仅据队列修复宣布关闭。
- **自然对话候选：** 一次明确开麦后，稳定转写通过偏移覆盖、VAD/final宽限或有限流关闭排空形成有身份和修订的候选，再进入正常输入。宽限是启发式；临时文字不逐字调用模型。支持有限续流，每个RPC实际占用原共享STT次数，不重置lease总样本/时长。
- **打断与保留：** 软件播放期间的重叠文字留待核对；精确hold确认不建输入，允许后续新活动继续。明确“打断回应，继续听我说”保留麦克风；全局Stop/关闭释放。没有声学回声识别，不宣称用户开口自动区分于扬声器。晚到修订留在原句，失败/未知发送不自动重试。
- **软件证据：** 后端预算与资源冻结切片已有41项独立检查；最新实际ASGI/Actor与编译传输、控制器、PCM队列组合的多场景预验已通过。整合源码还须固定最终manifest，重新独验和release；不能跨切片合并绿色统计作最终通过。
- **角色说话：** speaker v3把第一人称、兴趣/知识边界、选择回复深度、自然不确定或不接长任务带入剧情外聊天；不强迫回咖啡馆、不重新引入JEV聊天准入。普通虚构身体状态可自然聊，明确现实身份/身体问题保持诚实。92项聚焦和76个作者编写ASGI话轮证明接线，未证明真实模型从此不会出戏。
- **角色绘制：** 1413代码原生头颈/肩部依赖链接入审阅入口，保持同一身体与衣装状态、眼嘴和取消生命周期。该方向已有用户审阅，整体像仍不通过；用户14:20–14:22新提的头部右移、嘴唇与右斜方肌连接在隔离后续修改，不冒称已包含。
- **尚待验收：** 同版本真实自动多轮识别→角色→完整可听回复、自然端点质量、声学回声/打断、手机软键盘/音频、角色精度及3–5分钟实录。没有新付费provider调用、读取真实凭据或自动保存用户聊天。完整长期记忆/人格学习仍未完成。

以下是保持各自含义的历史证据。

# 历史验收摘要 — 2026-10-05 13:25 UTC

- **实际用户观察：** 用户 Mac 已确认文字沟通成立；12:49 明确听到了 Mira 的声音，但反馈只听到一小段、后续被截断。这个观察证明实际播放开始，尚未证明完整回复或持续语音通过。
- **已交付基线：** 0703 七文件完整包已交付，独立还原 1,134 文件；该冻结版本的 13/13 离线 release lanes、2,816 pytest cases＋13 subtests、478 Node 通过。12:33 获准后的单下载 ZIP 已保存在 Google Drive，内含原七文件，源字节不变。0703 网页 GitHub 上传失败，没有该版远端提交。
- **本次音频恢复候选：** 生产传输、控制器及播放器组合复现小 PCM 包的第 51 包撞到 50 包队列上限，远早于帧数预算；新代码按实际接收容量等待播放进度，保持原上限，并通过独立 22 项边界检查。尚不能断言这是用户实机截断的唯一原因，新包仍需完整发布检查和设备复测。
- **输入与失败恢复：** 已观测的转写尾段在自然结束/服务失败时保留；同修订的端点提示不再覆盖较完整的临时文字；重复 final 不抹去较新的 interim。明确 Stop/新流仍隔离旧结果。手势同步准备播放、未发送草稿保留及局部 JSON 值错误的准确诊断也进入候选；不进行自动额外模型请求。
- **精确重试：** 独验发现旧0703中，同一连续输入被接受后重送commit误报已撤销。新候选只让同一缓存快照保持幂等，已消费请求身份不重置；改变请求、正文、修订或作用域仍拒绝。不会自动重试或重复生成。
- **连续交谈缺口：** 本候选仍是点击持续聆听、手动发送。端点提示是输入转写状态，不是 JEV 分块或评分。自然自动提交在独立下一切片，尚未纳入本包，也未通过 Google 实机验证。
- **文字、JEV与记忆：** 普通正文独立呈现，JEV负责可选事件及显式有限文字分块；speech仍是完整 cue 的 PCM 流。第一人称作者往事、未来计划和实际共同经历保留来源，默认不自动记录用户聊天；完整M06/人格学习未完成。
- **美术与最终验收：** 三衣装、四情绪、两配饰的软件路径已有，人物脸颈、身体衣料、发束和自然运动仍未获用户认可。完整真实麦克风→自动转写提交→角色→完整可听回复、多轮打断、手机体验与同版本3–5分钟实录仍待完成。软件合成检查不能代替这些结果。

以下是各自冻结阶段的历史证据，不覆盖上述现状。

# 历史验收摘要 — 2026-10-05 06:34 UTC

- **实际文字：** 用户 Mac 已完成独立 MIRA OAuth 并明确确认文字沟通成立。最新 0550 诊断五轮生成全部成功、没有旧整句 JEV 审核；日志不证明每轮呈现或完整会话质量。
- **已交付：** 0550 七文件完整包已发用户；13/13 离线 release lanes、2612 pytest cases＋13 subtests、395 Node 与准确还原通过。此前远端已核实的 0317 完整归档继续保留。当前源码在其后，最终检查以同包 START-HERE 为准。
- **有界文字分块：** 默认关闭，显式 `--boundary-max-requests` 后按完整句即时首段与 JEV 有限尾段计划执行；文本保持完全一致，Stop/新输入栅栏保留。speech/事件候选完整cue，不宣称token流或语音逐段。
- **本次候选：** 第一人称作者往事/当前打算/真实共同经历分别保留来源；响应式页面与本页消息记录；取消、超时和异常中断明确区分；语音仅由自身权限判断，不被无关视觉歧义阻止。新行为均须在设备复测。
- **角色与故事：** 四情绪、三服装、两配饰的软件绘制和版本化回执路径已有；高精度、相似度、动作自然性未获用户认可。剧情只记合格实际呈现的结果，未来计划不写成已发生；长期自动记忆/人格学习未实现。
- **真实语音现状：** 用户已改正 TTS_LOCATION/VOICE 配置并启动。0364 最新生成在严格 JSON 加载失败，未进入 TTS；不能据此断言 Google 播放失败。新候选修复两类麦克风启动缓冲、连续按钮启用及 TTS 失败连带撤销独立文字，并增加固定 JSON 类型诊断；该真实 JSON 根因及语音听说仍未验收。
- **尚未完成：** 完整真实麦克风→转写→角色→可听语音、实际说话打断、手机触控/软键盘、同版本 3–5 分钟视频。历史独立 STT/TTS 成功和合成端到端不能拼接成此验收。

下面全部是较早版本的历史记录。只证明各自冻结版本，不覆盖本节事实。

## 历史摘要 — 2026-10-05 04:52 UTC

| 范围 | 当前证据与未关闭事项 |
|---|---|
| 0435固定软件与交付 | 1,075个源码/资源文件；13/13离线release lanes通过，2,544 pytest cases＋13 subtests、385 Node，114个安装资源与108个HTTP资源。独立安装/loopback及完整七文件恢复通过；状态为 `READY_VERIFIED_LOCAL_NOT_UPLOADED`，远端发布尚未确认。 |
| Mac直连与文字 | 独立MIRA OAuth成功，网页输入派发已修复，真实生成已进入输出审核。最近五轮仍为UNKNOWN／blocked，用户未看到回复，待重新导出的诊断核对；尚无成功的用户可见回复验收，不能据此认定具体审核根因。 |
| 代码角色与四情绪 | 三衣装、四情绪、两头饰及九个离线按钮已接正式renderer，并纳入0435软件检查。用户尚未认可眼睛不等大、颈部、身体比例和肩带等外形，正在分别修正；保持纯代码角色，不使用imagegen。软件回执不等于视觉认可。 |
| 真实设备与实录 | 完整浏览器/手机、麦克风→生成/审核→可听语音/字幕、实际出声中断及3–5分钟可播放录屏仍未完成。既有局部Mac观察和历史组件探针不能拼接为整体验收。 |
| 记忆与故事 | 显式手动记忆、配对召回和四节点剧情/合格经历有软件实现；完整M06、自动提取/人格学习、更长故事及跨剧情连续性仍未完成。 |

0435依据为04:45:47 UTC追加的 `final-ready-receipt.json` 与独立发布 `REPORT.md`；该通过结果只绑定未修改的0435。后续源码和美术修复须重新绑定验证，不改写冻结包。本次只核对文档，未新增provider调用。

原PDF与追加要求的完整78项编号继续沿用[剩余验收矩阵](../../development/FINAL_ACCEPTANCE_GAPS.md)，操作步骤及同版本设备清单见[启动指南](../../development/FINAL_START_GUIDE.md)。这两份指南分别核对到04:08和04:33，所述0317发布、response_headers／终态快照阻塞属于当时状态；当前软件/直连进度以上表为准，其余未完成验收继续保留。下方PDF-xx表和各阶段记录全部保留为历史证据，不作为当前已通过声明。

## 历史代码角色与剧情组合候选 — 2026-10-05 03:12 UTC

当时推荐已备份组件为0247增量，恢复分支commit [614c322a](https://github.com/Robinfxa/MIRA/commit/614c322a0c39bf643986e215634e8276dcfc7ee3)，三项远端文件逐字节匹配。它依赖2219完整包，不是独立安装，也不是展开源码已更新。

本候选增加代码原语角色的实际页面装配与目录绑定；3衣装可绘制，4 phase独立于emotion，四情绪与两头饰已接几何，未实现转头/放低相机仍不可用。v5面部是审阅候选，用户已指出需要进一步形体修正，不是美术完成。

角色控制核心12文件已有176项定向/独立检查通过；5/10/20轮合成上下文保持有界，应用story模式默认输入32768/输出65536字节，普通开发探针仍16384/32768。字节上限不是美元上限，不改变外部调用账本。当前整体候选完整release以冻结后的同包START-HERE为准。

真实用户：Mac独立MIRA OAuth在修复HTTPX重复解压后完成，模型选择gpt-6-luna；尚无回复验收。网页连接故障仍在排查，不能据合成429/403重现认定用户原因。代码字符动画方向被认为可动，但造型仍未过用户审阅。没有新provider调用、读取真实记忆或新增授权。

以下保留原阶段记录，不能用其结果代替当前候选：

## 历史作者剧情整合阶段 — 2026-10-05 01:42 UTC

当时最新稳定持久备份为2353 direct paired-memory增量（1010源文件、13 release lanes通过，13文件delta）已于恢复分支[3ca3d70](https://github.com/Robinfxa/MIRA/commit/3ca3d70c364f010d414aa67219a038da2d72f26d)核对；它基于独立2219完整安装包。此处的新story/barge-in source尚未发布。

新合成证据包括生成/审核同版本作者上下文、真实ASGI YES/NO两轮、编译receipt→fiction episode、配对前不读库、checkpoint重开恢复、Stop不等SQLite。独立核心11反例完成，新增持久化/CLI仍待独立整体验收。角色经历不变成真实用户事实，默认没有自动原文记录。

单独V3骨骼审阅页存在已确认导出JSON失败；修正版V8的配置初始化、错误可见性、精确中性几何与眼嘴驱动逻辑已独验，仍无真实GPU/连续接缝验收。该预览与当前可安装应用源码分开，不能冒充当前应用已接新rig或4情绪换衣。

## 之前阶段的冻结记录

## Historical direct-provider stage — 2026-10-04 22:08 UTC

User clarified that the product connects directly to providers; native Codex is an optional development adapter. The next source adds explicitly selected subscription OAuth and official API-key Responses routes, separate MIRA-owned auth, and an application launcher. Offline synthetic HTTPX plus actual ASGI/Actor/JEV composition is being tested. No real OAuth grant, direct inference, microphone/playback or full direct-stage release has been verified yet.

At that stage, the latest immutable published component was 2103:984 files,13 release lanes,2127 pytest plus13 subtests,355 Node,107 installed-resource hashes. Root verified all seven archive files at [9b6a2b1](https://github.com/Robinfxa/MIRA/commit/9b6a2b1a38c8f29ab8c6108a4afec12ec92f224a). Initial upload was blocked pending per-match secret review; review was completed and the same upload succeeded. Expanded source/main were not changed. This backup includes finite click-start/manual-send continuous listening, not automatic gapless dialogue or the new direct provider.

New visual mesh/composition/transition artifacts remain review prototypes outside this application source. The approved twelve portraits remain the production assets; no layered rig is claimed.

## Preserved earlier-stage evidence

## Historical MIRA acceptance boundaries — 2026-10-04 20:57 UTC

Published1845 was the latest verified archive at that stage: all12 release lanes passed (2,010 pytest tests plus13 subtests,329 Node tests,package/HTTP smoke),962 restored file hashes/modes matched, and all seven delivery files were remotely verified at [a6de84e](https://github.com/Robinfxa/MIRA/commit/a6de84e3fc64767222bb8a312266be77ec6f71f0). This is an archive publication; expanded repository application code remains older. Prior stages remain immutable.

Published1845 adds the provider-free local memory console, actual-byte request guard, bounded official startup notifications, reviewed macOS npm-native discovery, provisional STT preview and separate numeric clocks, plus the optional table-free V3 background. Its independent local-console and native-resolution controls passed, including the actual pre-fix oversized-body/launcher failures and their repairs. It does not prove the user's Mac RPC issue was fixed or that the new background was visually accepted. Linux npm optional packages do exist;1845's misleading source comment was corrected in its START-HERE, and this next source corrects the comment without changing pins.

Next candidate2021 combines finite application usage and click-start continuous listening with explicit revision-bound manual send. Its exact983-file capture passed13 release lanes (2079 pytest plus13 subtests,342 Node;107 wheel resources/101 HTTP assets). The subsequent v3 frontend passed40 targeted and4 real local synthetic HTTP/WebSocket cases, including receipt-prefix, final-cap/Stop and PTT/raw-recording/audition boundaries. A confirmed Stop→Start unsent-preview loss was fixed with a bounded prior-preview list and explicit empty-composer restoration. The complete merged source still requires a fresh release/restore receipt. No paid provider call was added. The user reported the1845 offline page operating normally on their Mac at20:23 and saw an unwanted old foreground rain overlay when choosing the painterly background. This establishes only that observed offline interaction; all-frame visual, voice and full device acceptance remain open.


The next candidate's application usage profile and click-start/manual-send continuous listening remain subject to coherent integration and independent lifecycle acceptance. The original usage slice's double CLI validation failure is preserved and repaired; local software tests are not a new provider call or real microphone acceptance.

Memory editing remains explicit, paired, scoped and reversible. No automatic recording, personality learning or real memory-dialogue quality is established. User12:07–12:20 observed the offline portrait and whole-frame movement, reporting stiffness and background mismatch. Real microphone/audible continuous dialogue and the3–5 minute recording remain unaccepted.

A subsequent real TCP check found that a fresh0837 installation lacks a Uvicorn WebSocket implementation: health200 but legitimate microphone upgrade404. The isolated wsproto1.3.2 repair passed5 directed plus8 independent real-socket cases. That establishes software transport behavior only; no browser, microphone or provider was involved. The current slice also narrowly updates the optional auth helper's PyJWT pin to2.15.1. On an isolated Python3.12 runtime,21 original/new auth tests and7 independent boundary tests passed, with unchanged auth implementation; these repairs are included in the later full-green0952 and1212 archives. Published0837 remains immutable and superseded.
Normal text generation/review sealed subtitle+pose grants without presentation. Synthetic audio completed STT and generation/review but correctly stopped as UNKNOWN before TTS. Separately, fixed production TTS yielded3.24 seconds of complete PCM with1.274-second dispatch-to-first-PCM timing and no playback. See [exact provider evidence](../PROVIDER-EVIDENCE-20261004.md); none is a human device test.

## Published1515 recall and1659 manual management

Published1212 includes the explicit-consent local SQLite store/CLI and bounded
context preview, plus official Codex0.159.2 macOS arm64/x86_64 binary pins.
The user has observed the offline character on their Mac. Their live metadata
setup remains blocked at a protocol-envelope check; a separate two-file
sanitized diagnostic was delivered. A verified binary hash does not establish
account entitlement or portable live inference.

Published1515 adds opt-in text Actor recall and a local operator pairing
boundary. Only manual USER_STATEMENT records are eligible; default
startup does not read memory, and automatic recording/personality learning is
still absent. The1356 candidate exposed unauthenticated session access to the
configured scope and failed legacy-evaluator compatibility tests. These are
retained real failures. The fixes passed the new1515 coherent release and78
independent privacy/lifecycle checks;1212's earlier green receipt was not reused.

## Historical PDF core requirements

| Item | Implemented or actual evidence | Still unaccepted |
|---|---|---|
| PDF-01 continuous 3–5 min session | Interactive scene, text/voice seams and offline rehearsal exist. | No human-recorded continuous live session. |
| PDF-02 scene is visual focus | Pixi full-frame adult character and scene integration in source. | User12:07 observed the offline portrait; phone and all state combinations remain unverified. |
| PDF-03 background, character, captions, text and voice entry | UI and controls implemented; rehearsal supports fixed text. | Real-browser controls not user-verified; rehearsal input is simulated. |
| PDF-04 mobile-first and desktop | Responsive rules and 390×844 checklist exist. | No real-phone/Safari check; narrow desktop is only emulation. |
| PDF-05 idle/listen/think/speak states | Phase labels and character mappings with software tests. | User-perceived distinctions unverified; rehearsal listen is simulated. |
| PDF-06 text chat | One native Luna text probe sealed after 4 JEV 200 checks in 6.332s, with subtitle+pose grants. | Zero presentation receipts; no user-visible continuous live text session. |
| PDF-07 real microphone | Capture/PTT path exists; isolated wsproto repair passed real TCP authentication/close/limits after exposing the missing0837 dependency. | No human microphone/device input accepted. 07:29 synthetic-audio STT probe is not a user mic. |
| PDF-08 audible speech + matching subtitle | Offline cue subtitles and 8 prerecorded synthetic English Flite/slt clips (~52.56s total); historical TTS produced one complete 3.4s Chinese PCM artifact. | Independent production TTS succeeded; human playback/audibility/subtitle and natural whole-session checks remain open. 07:29 probe did not call TTS. |
| PDF-09 multi-turn continuity | Finite rehearsal steps and scene state exist. | No continuous human live multi-turn session. |
| PDF-10 interrupt by starting new speech | PTT/capture and software stop paths exist. | No real new-speech interruption while audible playback is occurring. |
| PDF-11 stop sound immediately | Local-first stop code/tests. | No physical acoustic tail measurement. |
| PDF-12 cancel/invalidate reply | Software cancellation/stale-result tests. | No human live-provider delay/interrupt result. |
| PDF-13 block pending caption/action/media | Gate and stale-callback tests. | No live browser/audio/media observation. |
| PDF-14 return to listen and handle new input | UI phases and PTT path exist. | Real microphone continuation after interruption untested. |
| PDF-15 late/rapid replies never revive | Race/cancellation tests. | No user-observed real-service race. |
| PDF-16 clear interrupt gesture/reason | Current published path uses hold-to-talk/Stop; user-requested click-start continuous listening is under development. | User understanding of live control untested. |
| PDF-17 structured effects drive image | Sealed text probe granted subtitle and look-at-rain pose. | That probe presented zero effects; no human-observed live effect. |
| PDF-18 ≥3 expressions | 12 Pixi action×expression frames include 4 expressions; mapping tests. | User has seen the offline character, but all12 frame combinations and phone rendering are not accepted. |
| PDF-19 ≥2 non-speaking actions | Camera-lowered and look-at-rain states are implemented. | Actual pixels/legibility unverified. |
| PDF-20 environment change | Rain/window and warm-light commands exist with tests. | User observed the optional drawn background and reported a foreground-rain layering defect; state-by-state acceptance remains pending. |
| PDF-21 content-driven visual event | Fixed photo event is tied to approved interaction; gate tests exist. | No live presented browser event verified. |
| PDF-22 one multimodal branch | Selected branch: Pixi character CSS motion plus state-driven12 full frames, with animated SVG fallback. Idle/listening/speaking compositor motion has no mouth-sync; software integration is accepted on0810, actual browser perception remains open. | Browser/GPU/phone/user perception still open. |
| PDF-23 video lifecycle | Video branch not selected. | N/A for selected animation branch. |
| PDF-24 generated-media lifecycle | Runtime generated media not selected. | N/A for selected animation branch. |
| PDF-25 page→server→model | One Luna+JEV text probe sealed permits in 6.332s, no presentation. | No successful user-visible live loop. **07:29 separately source-bound probe:** a 4.66-second synthetic English audio input produced the exact 79-character transcript. Native generation and four JEV HTTP 200 responses followed; final review returned UNKNOWN because o1/o2 confidence was .58/.55 (<.6). No TTS, playback or presentation; this was not a transport failure. |
| PDF-26 failure/recovery | `/fail`, error handling, and offline fallback have software tests. | No human live timeout/network/audio/media recovery accepted. |
| PDF-27 no-key demo | Fixed offline rehearsal is explicitly labeled and makes no provider calls. | User has seen the offline portrait and whole-frame movement; full scripted control/speaker acceptance and recording remain open. |
| PDF-28 sources/secrets | `THIRD_PARTY.md`, asset notes, templates and secret exclusion are present. | Audit the final exact delivery bundle before release. |

## Historical PDF delivery items

| Item | State | Needed to close |
|---|---|---|
| PDF-D01 source | **Verified1845 archive available:**962 files,12-lane release and exact restore passed; remote commita6de84e. Expanded repository code remains older. This candidate requires its own source-bound release. | Publish exact current source with matching three-part code/assets bundle and pair its ID with the video. |
| PDF-D02 startup route | **Documented:** matching restore manifests/helpers ship beside, not inside, each three-part source pack. | Verify the same-stage pack and instructions from a new destination. |
| PDF-D03 ≤15-minute clean start | **Linux fresh-project check passed:** Python3.12.14 with cold project caches, bootstrap54.837s and rehearsal readiness3.518s, whole attempt5m55s. User's clean OS/device remains untested; Python3.13.5 without ensurepip failed the original bootstrap. | Time restore, locked install, server-ready, browser open separately; record OS and tool versions. |
| PDF-D04 3–5-minute video | **Not run; no video file.** | User records an actual playable 3–5-minute take with interaction, changes, audible interruption, Pixi branch, and failure/recovery. |
| PDF-D05 README | **Present:** README links this current matrix and labels the older device checklist historical; elapsed calendar time is not human labor. | Keep the final stage and actual release result current; do not claim measured labor hours. |
| PDF-D06 AI_USAGE.md | **Present/candid:** AI work, examples, and no human acceptance recorded. | Add only actual human device/browser observations after run. |
| PDF-D07 gap disclosure | **Present:** README lists open browser, phone, audio, mic, live session and recording. | Update with observed results and next steps. |

## Historical closing conditions (2026-10-04)

1. At that stage, the new frozen source still required its own full release and restore checks before publication. Published1845 was then the latest verified archive and retained the WebSocket dependency repair. See the current summary above for 0435's completed local checks and unconfirmed remote publication.
2. Use one matching delivery's manifest/helper and all three ZIPs. Sidecars ship beside the ZIPs; a source tree does not contain its own self-referential archive manifest. Do not mix stages or hand-edit checksums.
3. Human browser/device acceptance and an actual 3–5-minute recording remain open. Follow [the recording guide](../../development/DEMO-RECORDING.md). Software state, an ASGI response, or a permit does not prove human perception. Never bypass a browser/network access restriction.

The07:17 failed receipt is retained: Python/spec lanes passed; web build refused its in-project artifact path; package/smoke were not run. The repair moves disposable web output outside the project, preserving the guard. Read the matching delivery START-HERE for the subsequent full release result. Older DEVICE-ACCEPTANCE and19:27 reports remain historical.

## Historical user-device setup facts (2026-10-04)

At20:47 the user applied the schema-aware remoteControl/status/changed patch to1845 on their Mac; the next prepare counted one accepted passive notification. The next blocker was config/read profile drift, and at20:56 the safe diagnostic identified `developer_instructions:null`: an inactive optional value, not a configured instruction. This source fixes the key-presence false rejection, with null/empty positive controls and nonempty/nested/malformed negative controls. A bounded diagnostic patch now distinguishes response shape/type, a known unsafe field, and named effective-config checks using fixed labels, type and emptiness only. It does not print config values or relax those decisions. This is not a claim of completed Mac metadata/model admission.

Optional painterly V3 now suppresses the old foreground rain animation while classic retains it; original rain-window/warm environment changes remain. The repair follows user feedback and software regressions, with the revised composite awaiting user review.
