# Codex／ChatGPT 订阅承载：本轮公开证据登记

**日期：2026-10-02。** 下表是本轮通过web读取的官方文档摘要与边界，非账户能力实测。没有登录用户账户、读取凭据或运行推理／生图。网页是会变化的来源；URL与读取日期用于定位，不冒充保存了完整原始响应。

| ID | 官方来源 | 本轮确认的最小事实 | 没有证明的内容 |
|---|---|---|---|
| CX1 | [Codex Authentication](https://developers.openai.com/codex/auth)（重定向到ChatGPT Learn） | ChatGPT订阅登录与API-key计费是不同认证模式；程序化工作流有独立建议 | 用户套餐、额度、登录状态；任意部署获得订阅许可 |
| CX2 | [Codex Image generation](https://developers.openai.com/codex/image-generation) | 内置生图消耗通用Codex额度；文档给出的平均消耗更高 | 自建应用可直接调用同一生图通道；所有CLI／SDK版本都有同一产物协议 |
| CX3 | [Codex App Server](https://developers.openai.com/codex/app-server) | 提供turn／thread、文本delta、结构化输出、interrupt及额度观察接口 | G03完整范围已经能提前发布；原生订阅生图的完整结果合同已验证 |
| CX4 | [ChatGPT plan usage Overview](https://developers.openai.com/siwc/token-sharing-open-source) | 专门授权可让符合条件的开源／本地应用使用用户计划执行eligible Responses请求；收费／远程应用有额外接入说明 | 任意商业网站可直接复用一个个人账号；该应用已经具备准入 |
| CX5 | [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference) | 该OAuth流程使用公开Responses端点，HTTP要求stream=true、store=false，并按账户取模型 | 任意Codex缓存令牌可替代该授权；与Codex原生额度桶绝对相同 |
| CX6 | [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) | 当前路线不支持image_generation等托管工具、音视频输入和部分常见字段；图像输入按模型能力 | 文本请求成功即代表生图成功；max_output_tokens等可无条件照搬 |
| CX7 | [Plan usage with Codex app-server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) | 文档给出app-server接该OAuth承载的方法；目录不等于权限，完成请求才证明当次访问 | 自动续历史符合本产品真实曝光账本；令牌刷新无需隔离处理 |
| CX8 | [Codex non-interactive](https://developers.openai.com/codex/noninteractive) | 有非交互执行与机器可读输出工作流 | 一次exec必然只有一次模型推理或达到实时目标 |

**关键消歧：** Codex产品内置生图、ChatGPT plan usage的Responses请求、Platform API key请求是三个能力与计费边界，不按“同一家供应商”混为一条路。CX2与CX6说的是不同通道，二者不冲突。

**技术决策与证据分开：** 选择薄OAuth请求、采用app-server桥接、独立生图worker、禁用未授权付费回退等是M09的应用设计或默认提案，不是官方声称它们已经适合MIRA。真实型号、原生图像工具、终态、产物传输与计费归属必须逐项探测。
