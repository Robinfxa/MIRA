# A4 双文档差分、来源分歧与不可照搬默认值

**地位：编辑性整合记录，不是新增架构批准。** 本章公开说明哪里只是证据补全，哪里存在不能靠编辑替用户作出的路线选择。源文件与旧ADR均保留原字节；不重新核验线上版本。

## 1. 源文之间的差分登记

| ID | 架构书v0.5 | 借鉴书v0.1 | 本版明确处理 | 状态／落点 |
|---|---|---|---|---|
| IC-01 | M09 §2.1明确限制反向调用私有backend-api等方式替代正式接入 | §02/§08推荐CLIProxyAPI兼容入口及现成订阅桥接 | 两者不静默合并成已批准路线；保留源码可复用结论与首联调建议，同时保留原限制；实际配置触及该限制时先作具体carrier裁定 | **待承载准入**；M09 §2.4／§13、实施S01 |
| IC-02 | 原生程序化图片、产物与取消被统一列为项目未验证 | C02/C03/C07–C09提供已有实现、事件、产物与测试入口 | 收窄“未知”为目标版本／账户／MIRA合同未测；不再把生态基本能力作为从零研究项 | **来源补全**；M09 |
| IC-03 | v0.5对专门ChatGPT plan usage路线记载托管工具限制 | Codex原生／社区图片有另一条实现 | 分开认证、承载与计费对象；一种接口限制不推导为所有订阅路线都不能生图 | **对象消歧**；M09，旧官方资料仍按原日期 |
| IC-04 | M05已有单Actor、JEV和单人声仲裁 | Pipecat/LiveKit有自己的会话、播放控制 | 复用服务与执行设施；不同时开启第二个生成触发者或许可权威 | **适配差分**；M04/M05 |
| IC-05 | G03要求连续已批准语义范围及必要条件不丢失 | AIRI存在多TTS与空结果跳序路径 | 借序列缓存；不照搬默认并发或跳过必需失败片段 | **适配差分**；M03/M05 |
| IC-06 | 持续affect、非语音回应、G04收势独立于audio_end | Charivo按音频结束释放表情且动作音轨可发声 | 选择低层renderer／hook或最小patch；口型与affect分权，伴随人声仍受统一仲裁 | **适配差分**；M03/M06 |
| IC-07 | 共同经历以真实呈现为依据 | Codex提示已显示、线程含全量生成；Hindsight可自动记对话；OLVT用heard_response | 原生提示不当回执；显式上下文和记忆写入；字符串补身份／partial／unknown | **适配差分**；M01/M06/M09 |
| IC-08 | A2有146条未执行记录 | RI有18条且原文说明未并入架构 | 本版显式合并为164条来源／拟验收记录；前146条保持全部字段，RI原文保留并映射来源 | **目录整合**；A2/A6 |
| IC-09 | M09以候选和未验证状态表达承载 | 借鉴书有16项目、10个固定提交关键源码 | 继承原阅读范围与证据等级，不将“可定位”升为通读／安装／测试／账户／许可已验收 | **证据地位保持**；A5 |
| IC-10 | 代码、模型、素材分别有授权边界 | render-live2d为复合许可；部分包许可尚未深核 | 保留分包与素材许可待核对；不输出本项目可商用等新结论 | **准入记录**；A5/实施S03 |

IC-01不阻止完成架构书，也不是否定社区代码。它只阻止本次文档整合替用户新增一项接入边界例外。其余表项均从两份源文有据归并，不把编辑性映射称为实测结论。

## 2. 源码／机制默认值的逐项差分


本章把“需要适配”写成可检查的差分，避免泛泛声称外部项目都不够用。部分差分来自实际代码，部分是由MIRA合同推导的接入风险，表中分开注明。

| 项目／来源 | 上游事实或接入风险 | MIRA的差分 |
|---|---|---|
| Codex产物提示 [OS-C09](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/codex-rs/ext/image-generation/src/artifact.rs) | 原生提示假设图片已显示 | 忽略该UI事实假设；隔离→D-M→许可→真实回执 |
| Codex线程 [OS-C07](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/sdk/typescript/src/thread.ts) | SDK可以继续同一thread | 新生成使用已呈现上下文，不能带入旧未播尾部 |
| Codex任务输出 [OS-C07](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/sdk/typescript/src/thread.ts)/[OS-C08](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/codex-rs/ext/image-generation/src/tool.rs) | 返回Agent事件、工具项和最终消息 | 严格分流，工具日志与JSON控制字段不朗读 |
| CLIProxyAPI图片转换 [OS-C02](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_openai_images.go) | 部分模式经驱动模型与工具获取图片 | 记录真实调用图与usage，不伪称纯直接生图无额外计算 |
| CLIProxyAPI生图控制 [OS-C06](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/config/disable_image_generation_mode.go) | 存在向非images入口注入生图的配置语义 | 文本入口禁止自由生图；图片经专门受控请求 |
| CLIProxyAPI重试／路由 [OS-W01](https://github.com/router-for-me/CLIProxyAPI) | 项目具有多Provider/账号与路由能力 | 锁定当前批准route，失败不擅自换付费源或轮换账户 |
| AIRI合成调度 [OS-C17](https://github.com/moeru-ai/airi/blob/731123861093abfd7fc34c0654ba9f99206ab944/packages/pipelines-audio/src/speech-pipeline.ts) | 默认多个TTS任务；空结果可推进sequence | 不照搬并发配置，不跳过必要条件片段 |
| Charivo [OS-C15](https://github.com/zeikar/charivo/blob/62f3a4369643d4e132cfc25104a15422e1155c05/packages/render/src/render-manager.ts) | audio:end释放表情 | 口型停而affect可持续，纯动作不等待不存在音频 |
| Charivo动作 [OS-C15](https://github.com/zeikar/charivo/blob/62f3a4369643d4e132cfc25104a15422e1155c05/packages/render/src/render-manager.ts) | muteSound需明确传递 | 人声统一入口，动作音轨不可旁路 |
| LiveKit [OS-C14](https://github.com/livekit/agents/blob/8de48c229655d10ca3df3274ba77c20eef50c6c1/livekit-agents/livekit/agents/voice/speech_handle.py) | 有不同中断来源和可禁止中断的状态 | 明确用户停止仍需MIRA强制收紧；不让工具持有期屏蔽停止 |
| Open-LLM-VTuber [OS-C18](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/conversations/conversation_handler.py) | 以heard_response字符串写中断历史 | 验证来源，补partial/unknown、字幕、图片与截止游标 |
| Hindsight包装器 [OS-W10](https://github.com/vectorize-io/hindsight) | 便利集成可自动保存对话 | 用显式SDK按可靠呈现事件retain，不自动存完整生成 |
| Hindsight重试 [OS-C19](https://github.com/vectorize-io/hindsight/blob/f7dd3f4fd7420f7beec60c32c965e5e5cf7be066/hindsight-clients/python/hindsight_client/hindsight_client.py) | 同步retain的operation_id不构成异步幂等 | outbox与异步operation身份对齐，避免叠加重复写入 |
| XState mailbox [OS-C20](https://github.com/statelyai/xstate/blob/fbee62e7c1586315ed478c2fedf530d7e0ff5a3e/packages/core/src/Mailbox.ts) | 串行处理本身没有本产品的媒体预算 | 控制事件不被媒体积压堵住；不推断自带优先撤销语义 |
| ink [OS-W13](https://github.com/inkle/ink/blob/master/README.md) | Continue推进解释器叙事状态 | 生成候选不提交呈现；重要剧情由回执约束 |
| 任意网络Mock [OS-W14](https://github.com/mswjs/msw)/[OS-W16](https://playwright.dev/docs/mock) | 可以直接返回任意成功结果 | 不绕过Actor和许可；故障与拒绝也要经过同一路径 |

这些差分大部分属于薄适配器或配置，而非重建上游。只有公共扩展点确实不能表达时才提交最小patch；为每个patch记录上游commit、原因、测试、移除条件。不要因一个表情释放策略不匹配就fork整套Live2D引擎。


## 3. 章节继承方式

v0.5的八份ADR、原146条验收记录、原来源快照和Grill字节保持。各M章增加“复用落点”，M09显式补足已有实现并公开IC-01；总书、M08、A1、A2和pending同步更新当前入口。借鉴书原件及各分章放在历史目录，不作为第二份可独立覆盖架构的规则书。

旧文本中本轮／当前厂商能力按源日期解释。v0.6新增的交叉表、RI关联、工作包owner与S索引均是可审查的文档整理，不冻结新schema、算法或技术栈。
