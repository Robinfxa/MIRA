# A5 开源项目、固定源码与许可证依据

**地位：继承借鉴书证据，不是依赖安装锁。** 16个项目记录全部保留；10个在源文中有固定提交的关键源码读取，另外6个为项目／文档级参考。固定提交不代表整仓通读。TypeSafe是服务依据，ValueHermes是私有方法参考，均不计入16个开源项目。

本版未重新访问这些远端；“已读”仅指原借鉴书在2026-10-02的记录。部分C入口只有符号检索，不能把它们与完整短文件读取等同。包内保存记录、URL、commit与阅读范围，不伪称包含上游源码字节。

## 1. 项目登记

| ID | 项目 | 完整review commit | 来源等级 | 建议用途 | 采用状态 |
|---|---|---|---|---|---|
| R01 | [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) | `2044a01f422998de79a5da8015141b878886534d` | key_source_read_at_pinned_commit | 订阅HTTP与生图首联调候选 | 推荐／未集成 |
| R02 | [官方Codex](https://github.com/openai/codex) | `44dd77b71e88c78295736bffd3dc3b684c13be6d` | key_source_read_at_pinned_commit | 第一方承载与原生产物参考 | 推荐／未集成 |
| R03 | [Pi provider层](https://github.com/earendil-works/pi) | `9fba660cf1caca0ade5bea72269352416e595a19` | key_source_read_at_pinned_commit | TypeScript嵌入式替代，不与CPA叠加 | 推荐／未集成 |
| R04 | [Pipecat](https://github.com/pipecat-ai/pipecat) | `cae1f51a4060b6acf679991e75374520069ef016` | key_source_read_at_pinned_commit | 音频基础首联调候选 | 推荐／未集成 |
| R05 | [LiveKit Agents](https://github.com/livekit/agents) | `8de48c229655d10ca3df3274ba77c20eef50c6c1` | key_source_read_at_pinned_commit | RTC/Agent替代与生命周期参考 | 推荐／未集成 |
| R06 | [浏览器VAD](https://github.com/ricky0123/vad) | 未固定 | documentation_only | 可选自动活动检测，不能取代让话判断 | 推荐／未集成 |
| R07 | [Charivo](https://github.com/zeikar/charivo) | `62f3a4369643d4e132cfc25104a15422e1155c05` | key_source_read_at_pinned_commit | 渲染模块首联调，许可证分包 | 推荐／未集成 |
| R08 | [AIRI](https://github.com/moeru-ai/airi) | `731123861093abfd7fc34c0654ba9f99206ab944` | key_source_read_at_pinned_commit | 顺序/取消/回调；不整仓接管 | 推荐／未集成 |
| R09 | [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | `992309c0aa19845960228f880013d4685fde93b5` | key_source_read_at_pinned_commit | 中断历史与角色闭环参考 | 推荐／未集成 |
| R10 | [three-vrm](https://github.com/pixiv/three-vrm) | 未固定 | documentation_only | 独立3D资产路线 | 推荐／未集成 |
| R11 | [Hindsight](https://github.com/vectorize-io/hindsight) | `f7dd3f4fd7420f7beec60c32c965e5e5cf7be066` | key_source_read_at_pinned_commit | 显式记忆SDK，不自动完整聊天入库 | 推荐／未集成 |
| R12 | [XState](https://github.com/statelyai/xstate) | `fbee62e7c1586315ed478c2fedf530d7e0ff5a3e` | key_source_read_at_pinned_commit | TS后端适用，不强制跨语言 | 推荐／未集成 |
| R13 | [ink](https://github.com/inkle/ink) | 未固定 | documentation_only | 复杂叙事作者工具，当前不必运行时引入 | 推荐／未集成 |
| R14 | [MSW](https://github.com/mswjs/msw) | 未固定 | documentation_only | 网络Mock和共享fixtures | 推荐／未集成 |
| R15 | [Playwright](https://github.com/microsoft/playwright) | 未固定 | documentation_only | 浏览器测试/HAR/诊断 | 推荐／未集成 |
| R16 | [fast-check](https://github.com/dubzzz/fast-check) | 未固定 | documentation_only | 属性测试/可控调度/反例 | 推荐／未集成 |

机器原表：[reference-registry.json](../../reference/opensource/reference-registry.json)，按原字节保留。其中`adoption_status`、`upstream_tests_run`、`mira_integration_tests_run`和`account_verified`没有升级。

## 2. 源码与文档的精确证据入口

本书统一使用OS-C01–OS-C20、OS-W01–OS-W20、OS-VH01，分别对应借鉴书原C/W/VH编号。保留原链接及阅读范围，避免与架构CX或其它历史编号冲突。

### OS-C01 · router-for-me/CLIProxyAPI · internal/runtime/executor/codex_executor.go

来源：[原记录入口](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_executor.go)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 完整短文件；CodexExecutor 壳层和无状态定位。

Git blob：`aeaee31e7255f29fe591476744abc29cdf0967f2`。

### OS-C02 · router-for-me/CLIProxyAPI · internal/runtime/executor/codex_openai_images.go

来源：[原记录入口](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_openai_images.go)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–275行；executeOpenAIImage、executeOpenAIImageStream及结果收集；另经代码检索定位partial_image分支，其余未通读。

Git blob：`65797a3ad4e135fc22772871d410aa2aa5e142c6`。

### OS-C03 · router-for-me/CLIProxyAPI · internal/runtime/executor/codex_openai_images_test.go

来源：[原记录入口](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_openai_images_test.go)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–120行；DirectOpenAIImageGenerationUsesImagesEndpoint合成上游测试，未执行。

Git blob：`5bcc970546cc7a6b0bac49aa5f9a48a3acfa1068`。

### OS-C04 · router-for-me/CLIProxyAPI · internal/runtime/executor/codex_executor_auth.go

来源：[原记录入口](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_executor_auth.go)。原阅读日期：2026-10-02；证据类别：`source_search`。

**原阅读范围：** 代码检索定位Refresh和resolveCodexConfig；未通读。未记录blob，不补造。

### OS-C05 · router-for-me/CLIProxyAPI · internal/runtime/executor/codex_websockets_executor.go

来源：[原记录入口](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/runtime/executor/codex_websockets_executor.go)。原阅读日期：2026-10-02；证据类别：`source_search`。

**原阅读范围：** 代码检索定位CodexAutoExecutor.ExecuteStream及HTTP回退；未通读。未记录blob，不补造。

### OS-C06 · router-for-me/CLIProxyAPI · internal/config/disable_image_generation_mode.go

来源：[原记录入口](https://github.com/router-for-me/CLIProxyAPI/blob/2044a01f422998de79a5da8015141b878886534d/internal/config/disable_image_generation_mode.go)。原阅读日期：2026-10-02；证据类别：`source_search`。

**原阅读范围：** 代码检索确认chat模式将生图限制在images端点；未通读。未记录blob，不补造。

### OS-C07 · openai/codex · sdk/typescript/src/thread.ts

来源：[原记录入口](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/sdk/typescript/src/thread.ts)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–205行（返回完整文件）；runStreamed、run、signal、outputSchema、local_image。

Git blob：`ead1767a9444a6f0ec568aabc890b3d07761b386`。

### OS-C08 · openai/codex · codex-rs/ext/image-generation/src/tool.rs

来源：[原记录入口](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/codex-rs/ext/image-generation/src/tool.rs)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–280行；生图／编辑、started／failed／completed、真实结果与保存路径。

Git blob：`d2777fb2023782ad7508fc4bddc097d33fb96359`。

### OS-C09 · openai/codex · codex-rs/ext/image-generation/src/artifact.rs

来源：[原记录入口](https://github.com/openai/codex/blob/44dd77b71e88c78295736bffd3dc3b684c13be6d/codex-rs/ext/image-generation/src/artifact.rs)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 完整文件；产物路径及已显示的原生UI提示。

Git blob：`6c6fce0f9812d88daf5a53880a77485c6eea6cb3`。

### OS-C10 · earendil-works/pi · packages/ai/src/api/openai-codex-responses.ts

来源：[原记录入口](https://github.com/earendil-works/pi/blob/9fba660cf1caca0ade5bea72269352416e595a19/packages/ai/src/api/openai-codex-responses.ts)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–175行；共享Responses工具、Abort组合、状态、重试与额度错误分类。

Git blob：`9c1831a021301c36f1669c326eb6c925a68ab11c`。

### OS-C11 · earendil-works/pi · legacy API aliases / fetch tests

来源：[原记录入口](https://github.com/earendil-works/pi/blob/9fba660cf1caca0ade5bea72269352416e595a19/packages/ai/src/legacy-api-aliases.ts)。原阅读日期：2026-10-02；证据类别：`source_search`。

**原阅读范围：** 检索定位弃用旧导出与新api入口；另检索packages/ai/test/fetch-option.test.ts，未执行。未记录blob，不补造。

### OS-C12 · pipecat-ai/pipecat · src/pipecat/transports/base_output.py

来源：[原记录入口](https://github.com/pipecat-ai/pipecat/blob/cae1f51a4060b6acf679991e75374520069ef016/src/pipecat/transports/base_output.py)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–185行；BaseOutputTransport、分块、sender、stop／cancel。

Git blob：`9fa039a198dcd656f82a8d4347b3f13463a0818d`。

### OS-C13 · pipecat-ai/pipecat · InterruptionFrame

来源：[原记录入口](https://github.com/pipecat-ai/pipecat/blob/cae1f51a4060b6acf679991e75374520069ef016/src/pipecat/frames/frames.py)。原阅读日期：2026-10-02；证据类别：`source_search`。

**原阅读范围：** 检索InterruptionFrame继承SystemFrame；未通读完整文件。未记录blob，不补造。

### OS-C14 · livekit/agents · livekit-agents/livekit/agents/voice/speech_handle.py

来源：[原记录入口](https://github.com/livekit/agents/blob/8de48c229655d10ca3df3274ba77c20eef50c6c1/livekit-agents/livekit/agents/voice/speech_handle.py)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–195行；独立scheduled/authorize/done/interruption状态、任务、回调与exception语义。

Git blob：`a65f4eac026b40f39812fa7c7f96474ef64c3aab`。

### OS-C15 · zeikar/charivo · packages/render/src/render-manager.ts

来源：[原记录入口](https://github.com/zeikar/charivo/blob/62f3a4369643d4e132cfc25104a15422e1155c05/packages/render/src/render-manager.ts)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–240行；事件生命周期、口型、表情释放、muteSound、订阅清理。

Git blob：`b93b68091aa5dda6bd673a51895178c4dcf1ee7b`。

### OS-C16 · zeikar/charivo · packages/render-live2d/LICENSE.md

来源：[原记录入口](https://github.com/zeikar/charivo/blob/62f3a4369643d4e132cfc25104a15422e1155c05/packages/render-live2d/LICENSE.md)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 完整许可说明；MIT自有代码、Cubism Core专有许可、Framework/Samples独立许可及模型分离。

Git blob：`1df67581fe89cbd43f25fd67f582048fb3f963d0`。

### OS-C17 · moeru-ai/airi · packages/pipelines-audio/src/speech-pipeline.ts

来源：[原记录入口](https://github.com/moeru-ai/airi/blob/731123861093abfd7fc34c0654ba9f99206ab944/packages/pipelines-audio/src/speech-pipeline.ts)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–205行；intent/owner停止、AbortSignal、有序合成结果、播放回调和null跳过路径。

Git blob：`f8f11ee0600da379dc4f9aca6502a4f6c6c6c1c7`。

### OS-C18 · Open-LLM-VTuber/Open-LLM-VTuber · src/open_llm_vtuber/conversations/conversation_handler.py

来源：[原记录入口](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/conversations/conversation_handler.py)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取70–165行；handle_individual_interrupt取消任务、heard_response和中断历史。

Git blob：`02780b486bcb13783bf9a3b04b2dcbb5d182665f`。

### OS-C19 · vectorize-io/hindsight · hindsight-clients/python/hindsight_client/hindsight_client.py

来源：[原记录入口](https://github.com/vectorize-io/hindsight/blob/f7dd3f4fd7420f7beec60c32c965e5e5cf7be066/hindsight-clients/python/hindsight_client/hindsight_client.py)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 读取1–160行；维护型client、内容类型、异步retain幂等条件、容量重试。

Git blob：`10a224555b674ddd70f6a79762f3ea4e3db2c4ee`。

### OS-C20 · statelyai/xstate · packages/core/src/Mailbox.ts

来源：[原记录入口](https://github.com/statelyai/xstate/blob/fbee62e7c1586315ed478c2fedf530d7e0ff5a3e/packages/core/src/Mailbox.ts)。原阅读日期：2026-10-02；证据类别：`source_read`。

**原阅读范围：** 完整短文件；入队、clear保留在处理节点与串行flush。

Git blob：`43a2a65e2ca52c3ebe2091496dc8541f16af97a1`。

### OS-W01 · CLIProxyAPI 项目首页／功能与许可

来源：[原记录入口](https://github.com/router-for-me/CLIProxyAPI)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** README、许可标识、OAuth／Responses／SDK与usage统计说明；未使用赞助商宣传作为依据。未记录blob，不补造。

### OS-W02 · Codex App Server 官方文档

来源：[原记录入口](https://developers.openai.com/codex/app-server)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** App Server 接入及事件／中断合同；重定向至learn.chatgpt.com。未记录blob，不补造。

### OS-W03 · Codex Image generation 官方文档

来源：[原记录入口](https://developers.openai.com/codex/image-generation)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 原生生图与使用额度说明；具体账户未验证。未记录blob，不补造。

### OS-W04 · Pi 当前项目入口

来源：[原记录入口](https://github.com/earendil-works/pi)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 从旧badlogic/pi-mono入口确认重定向；项目与MIT标识。未记录blob，不补造。

### OS-W05 · Pipecat 项目入口

来源：[原记录入口](https://github.com/pipecat-ai/pipecat)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 项目能力与BSD-2-Clause；具体源码见C12/C13。未记录blob，不补造。

### OS-W06 · LiveKit Agents 项目入口

来源：[原记录入口](https://github.com/livekit/agents)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 语音框架、Apache-2.0及模型许可区别；具体源码见C14。未记录blob，不补造。

### OS-W07 · Charivo 项目入口

来源：[原记录入口](https://github.com/zeikar/charivo)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 模块化接口示例与包级许可说明；具体源码见C15/C16。未记录blob，不补造。

### OS-W08 · AIRI 项目入口

来源：[原记录入口](https://github.com/moeru-ai/airi)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 产品及MIT许可；具体音频代码见C17。未记录blob，不补造。

### OS-W09 · Open-LLM-VTuber 项目入口

来源：[原记录入口](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 已有语音角色实现与MIT／素材许可分离；代码见C18。未记录blob，不补造。

### OS-W10 · Hindsight 项目入口

来源：[原记录入口](https://github.com/vectorize-io/hindsight)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** retain/recall/reflect与显式SDK、自动包装器区别；MIT；代码见C19。未记录blob，不补造。

### OS-W11 · XState 项目入口

来源：[原记录入口](https://github.com/statelyai/xstate)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** actors/statecharts与MIT；代码见C20。未记录blob，不补造。

### OS-W12 · three-vrm 项目入口

来源：[原记录入口](https://github.com/pixiv/three-vrm)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** VRM加载与渲染路线、MIT；本轮未审具体实现。未记录blob，不补造。

### OS-W13 · ink README

来源：[原记录入口](https://github.com/inkle/ink/blob/master/README.md)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 通过GitHub读取README 1–145行；编译器、运行时与inkjs分工；非固定commit。未记录blob，不补造。

### OS-W14 · MSW 项目入口

来源：[原记录入口](https://github.com/mswjs/msw)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 浏览器和Node网络层Mock、handler复用及MIT；非源码深审。未记录blob，不补造。

### OS-W15 · Playwright 项目入口

来源：[原记录入口](https://github.com/microsoft/playwright)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 浏览器测试及Apache-2.0；非源码深审。未记录blob，不补造。

### OS-W16 · Playwright Mock APIs

来源：[原记录入口](https://playwright.dev/docs/mock)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** HTTP路由、HAR录制与回放，非设备音频证明。未记录blob，不补造。

### OS-W17 · fast-check 项目入口

来源：[原记录入口](https://github.com/dubzzz/fast-check)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 属性测试与MIT；非源码深审。未记录blob，不补造。

### OS-W18 · fast-check Race conditions

来源：[原记录入口](https://fast-check.dev/docs/advanced/race-conditions/)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** 可控异步调度与竞态测试；不是所有浏览器物理调度的枚举。未记录blob，不补造。

### OS-W19 · 浏览器VAD项目

来源：[原记录入口](https://github.com/ricky0123/vad)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** MicVAD回调、Silero/ONNX Runtime底层；本轮未审实现或包级许可。未记录blob，不补造。

### OS-W20 · TypeSafe 官方API合同

来源：[原记录入口](https://docs.typesafe.ai/api)。原阅读日期：2026-10-02；证据类别：`documentation_read`。

**原阅读范围：** state/questions、Noul/Choice/Score、返回、错误；这是服务文档，不当作开源模型证据。未记录blob，不补造。

### OS-VH01 · ValueHermes 总设计书（私有方法参考）

来源：[原记录入口](https://github.com/Robinfxa/ValueHermes/blob/f141ccf842ffed23d33dba73e4da99b5703ccff8/docs/architecture/00-master-design-book.md)。原阅读日期：2026-10-02；证据类别：`source_document_read`。

**原阅读范围：** 读取1–44行；外部机制登记、三态对照与不自动承诺；不分发私有正文。未记录blob，不补造。

## 3. 许可证与分发物：源文观察，不是本项目准入结论

下表继承借鉴书§11.1，未作新法律或在线许可核查。代码、在线服务、权重、角色素材和声音分别有适用边界；来源没有支持的许可结论保持未核查。

| 项目 | 本轮许可依据 | 需要另记的对象 |
|---|---|---|
| CLIProxyAPI | 项目MIT [OS-W01](https://github.com/router-for-me/CLIProxyAPI) | 接入服务/账号条款不由MIT授权；不转授个人凭据 |
| 官方Codex | 项目Apache-2.0 | 在线模型、账户额度和输出素材不等于开源代码许可 |
| Pi | 项目MIT [OS-W04](https://github.com/earendil-works/pi) | 依赖与实际Provider服务分别记录 |
| Pipecat | 源码SPDX BSD-2-Clause [OS-C12](https://github.com/pipecat-ai/pipecat/blob/cae1f51a4060b6acf679991e75374520069ef016/src/pipecat/transports/base_output.py) | 云语音服务、模型和声音资产单独授权 |
| LiveKit Agents | 项目Apache-2.0 [OS-W06](https://github.com/livekit/agents) | turn detection模型等可能有独立模型许可 |
| Charivo | 主要自有代码MIT；render-live2d复合许可 [OS-C16](https://github.com/zeikar/charivo/blob/62f3a4369643d4e132cfc25104a15422e1155c05/packages/render-live2d/LICENSE.md) | Cubism Core/Framework/Samples、模型、纹理、动作分别登记 |
| AIRI | 项目MIT [OS-W08](https://github.com/moeru-ai/airi) | 集成模型/素材不因框架MIT而自动获许可 |
| Open-LLM-VTuber | 项目MIT，示例Live2D素材另有条款 [OS-W09](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 原创成年角色不能以demo角色代替 |
| Hindsight | 项目MIT [OS-W10](https://github.com/vectorize-io/hindsight) | 数据来源、模型服务和用户删除要求独立 |
| XState | 项目MIT [OS-W11](https://github.com/statelyai/xstate) | 第三方可视化服务不默认纳入 |
| three-vrm | 项目MIT [OS-W12](https://github.com/pixiv/three-vrm) | 每个VRM模型的作者及模型使用条款 |
| MSW | 项目MIT [OS-W14](https://github.com/mswjs/msw) | 回放fixture不能含私人密钥或未经许可素材 |
| Playwright | 项目Apache-2.0 [OS-W15](https://github.com/microsoft/playwright) | 浏览器分发物与测试素材需单独核对 |
| fast-check | 项目MIT [OS-W17](https://github.com/dubzzz/fast-check) | 随机反例中的私人输入需裁剪 |
| 浏览器VAD | 本轮未完成所选包的许可证深核 [OS-W19](https://github.com/ricky0123/vad) | JS包、Silero权重、ONNX Runtime各自核对 |
| ink／Web移植路线 | 本轮仅核查README，分发许可待锁版核对 [OS-W13](https://github.com/inkle/ink/blob/master/README.md) | ink、inkjs、作者故事和编译产物分别登记 |

上表是来源和交付检查表，不是法律意见，也不把某个框架的例外条件自动解释成我们的出版许可。不要分发依赖文件时剥掉上游要求保留的NOTICE/banner。



## 4. 来源包覆盖

借鉴书原Markdown、HTML、15个分章、项目JSON、RI原目录及检查文件均保存于`docs/history/open-source-reference-v0.1/`。架构v0.5原分章、导出、目录与工具保存于`docs/history/edition-v0.5/`。当前文档读取模块正文与本附录，不要求实施者在两个当前版本之间猜测。
