# MIRA 提示词精简与实际请求审查

核对时间：2026-10-06 16:12–16:30 UTC。基点为不可变的
`mira-luna-tool-integration-20261006T1431Z`（1515冻结源码）。本报告只审查
固定提示词、合成序列化请求与来源；不包含用户私聊、真实模型调用或语义质量评分。

## 可以落地的结论

1. **先修冲突，不再追加一层规则。** 默认 native 工具请求拼入共用 voice，
   其中旧换装段仍要求“同 cue 的 authored pose + independent review”。
   这与同一请求前面的工具唯一执行路径冲突。改为由当前 action contract
   提供可用操作；legacy 原有 pose/proposal 合同继续由自身请求提供。
2. **角色身份不等于每轮表演设定。** 原 FIRST_PERSON_MEMORY 强制使用一个
   authored detail；雨夜、灯塔、衣装又在事实和媒体说明里反复出现。
   改为只有回答当下话题才取用一个细节，没有最低设定用量。
   共用 voice 明确旧回复是“说过什么”的证据，不是必须继续模仿的文风模板。
3. **普通闲聊仍是第一人称。** 保留摄影师身份、有限兴趣、直率温暖、基础知识直接答、
   可缩小过长任务；普通场景问题不主动加“故事里／角色设定／现实里的我”。
   直接问 AI、真人、现实身体或素材来源时，仍简短如实回答。
4. **认人必须有状态变化。** 明确角色认领/确认应请求当前提供的 recognition
   操作，不能只在台词里说认出了。inactive/pending 不能提取 I/you 共同角色往事；
   actual recognition 后使用 released_role_canon 与 current beat。
   real_user_history、来源、披露与回执结构字段完全保留。
5. **JSON 正文和函数协议分别准确。** 自然台词只能处于 schema 的 effect value；
   完整 JSON、正确转义、无 fence/包装/额外说明。真实 function_call item 独立于
   台词 JSON，不能在台词或 effect 中模拟。shown、pending、failed 续答接收
   精确 function_call_output 与最新状态；不修复解析器，也不猜测曾经那条未知
   102-byte 真实输出是什么。

## 实际上下文与字节预算

使用同一合成输入，在基点与候选各抓取16个真正由 adapter 序列化的请求：
订阅/API × native/legacy × 已有问候/最近雨衣指代/已认可老友/pending recognition。
所有输入和输出均由本次测试自写，MockTransport 不联网。

| 项目 | 基点 | 候选 |
|---|---:|---:|
| 共用 CHARACTER_VOICE UTF-8 | 6,688 B | 6,141 B |
| native 固定基础 instructions | 10,002 B | 9,455 B |
| legacy author 所有flag最大组合 | 12,555 B | 11,712 B |
| 上述16请求最大 JSON body | 50,614 B | 50,109 B |

原有12,000 B断言只覆盖 speech/memory/story，未覆盖 images=True；全flag矩阵
实际暴露超限。现在16种组合全部低于原界限。65,536 B wire/prompt上限不变。
这里的请求上限是有限合成场景观察，不保证所有长会话都不会触及预算。

序列化仍是一份带明确来源的事实 JSON；user_inputs、presented_effects 和
accepted_prefix 不等价。短指代实验保留最新衣装建议，同时也保留较早的灯塔台词；
没有为了“变好看”删改历史。first_person_dialogue 的引用指向同一包中的真实行。
active 与 pending 由 typed speaker_contract 区分，未依靠文本像不像夏禾。

在这四种场景中，有9–10条相同 canon 事实同时出现在 author_policy 与 story
投影，主要衣装/性格等事实计数为2。这是实际重复的证据，也是内容显著性的可能
来源，**不是已证明的模型故障原因**。本切片只精简固定指令，不删除跨消费者共用的
来源字段；以后若去重，应由投影 owner 保持唯一来源和明确引用并重测各消费者。
本候选不宣称修复预算耗尽、缺工具、停止、网络或真实模型无输出。

## 公开来源与具体借鉴点

以下均在2026-10-06实际通过网页工具访问。技术结论以官方源码/文档为主；社区
issue 是作者的一手报告，未将其报告结果冒充我们复测或当前上游仍有的故障。

- [MaiBot 当前 Bot 配置](https://docs.mai-mai.org/manual/configuration/bot-config)，
  页面显示更新2026-10-06；访问约16:14 UTC。人格、行为和回复风格分别配置，
  人格建议1–2句；群聊示例也避免总重复身份或生硬找话题。借鉴职责分离和降低重复，
  不复制随机一两个字/符号的回复，也不采用群聊动态发言门控。
- [官方 replyer 模板](https://raw.githubusercontent.com/Mai-with-u/MaiBot/main/prompts/zh-CN/maisaka_replyer.prompt)，
  文件页面未提供可核对发布日期；访问约16:13 UTC。当前模板由身份、当前聊天话题、
  reply_style、可选参考和输出要求组成。借鉴“当前话题优先＋短核心”，而非整段移植。
- [官方 planner 模板](https://raw.githubusercontent.com/Mai-with-u/MaiBot/main/prompts/zh-CN/maisaka_chat.prompt)，
  日期未提供；访问约16:13 UTC。planner 明确负责决策且不代角色发言，正式回复
  有独立工具。借鉴内部决策与外部台词分工；MIRA继续自己的有限函数工具架构，
  不复制通用多工具循环、自动等待、额外回复模型或分析输出。
- [官方 replyer 实现](https://raw.githubusercontent.com/Mai-with-u/MaiBot/main/src/chat/replyer/maisaka_generator_base.py)，
  日期未提供；访问约16:25 UTC。_build_personality_prompt 与 _select_reply_style
  分开；_extract_guided_bot_reply 用 typed source_kind 识别自身历史，而非昵称。
  借鉴结构来源优先。该源码默认人设空值时有“是人类”回退，本项目不采用。
  同文件当前代码已处理未知 reply_style，不能沿用旧issue断言当前仍崩溃。
- [社区 issue #2069](https://github.com/Mai-with-u/MaiBot/issues/2069)，
  发表2026-09-23；访问约16:14 UTC。作者报告表情标签作为自身正文回灌导致模仿，
  并报告其局部修复。借鉴审查真实序列化历史/来源标签，防止把渲染或上下文问题
  全归因于人设提示。未获取或复制其用户原始私聊。
- [社区 issue #2051](https://github.com/Mai-with-u/MaiBot/issues/2051)，
  发表2026-09-15；访问约16:14 UTC。报告越界风格枚举导致回复生成中断。
  借鉴区分协议、消费错误和对话风格质量；不能凭“没回复”归因角色提示。
  本项目保留严格合法正文边界，不采用同义枚举修复或自由JSON猜测。
- [SmartPoke 插件作者 README](https://github.com/TAIY2020/smart_poke_plugin)，
  未提供可核对发布日期；访问约16:14 UTC。作者将额外回复腔调默认留空，描述了
  硬塞讽刺风格冲淡原人设的问题。只借鉴避免重复叠加风格；不引入其随机延迟、
  概率动作、回退文字池或上下文写入机制。
- [官方更新日志](https://docs.mai-mai.org/changelog/)，页面显示2026-10-06更新；
  访问约16:12 UTC。1.3.4记录请求超时重复消耗修复；8月条目记录自身消息来源和
  tool-message问题。它支持分开核对版本/协议/预算与prompt，不证明MIRA存在同样bug。

2025-03-21的[人设讨论#518](https://github.com/Mai-with-u/MaiBot/discussions/518)
也已查看，但它是旧版广泛OC写作清单，无当前运行链证据，不作为本修订技术依据。
2026-06-04的[讨论#1790](https://github.com/Mai-with-u/MaiBot/discussions/1790)
只有导入人格skill的提问且无回复，不能据此声称存在成熟导入实践。

## 验证与下一次真实观察

最终定向检查333 passed（13个模块）。新增合同测试40项：真实RED为36 failed/4 passed，失败来自
缺少精简合同/超预算；修订后同集合全部通过。较早一次测试脚手架用错helper参数，
仅记作harness错误，不当作业务RED。所有合成回复只证明运输/解析和保留证据，
不能证明模型会选择正确动作或自然说话。

`fixtures/editorial-cases.json` 提供12个自写正反例和状态条件，用于后续人工阅读：
重复问候、普通知识、有限兴趣、日常场景、直接AI问句、衣装短指代、角色认领、
已释放老友canon、pending/failed结果、素材来源、新画面请求。例句不是标准答案，
不会注入运行时提示，也不作为关键词评分器。

下一次获准的真实互动应先核对实际运行版本、当轮可用工具、typed角色状态、
request/result/receipt以及预算诊断，再阅读整段对话。应观察是否接住最新话题、
不循环开场、不插入无关衣装/灯塔、明确认领是否确实调用recognition、pending是否
如实表达。未获得真实调用授权前，不运行评审模型或将私人语料发给外部服务。

## 广域检查实际状态

已结束的一次 affected 共运行7个lane：architecture、actor、http、specs通过；
config失败2项、tooling失败7项、providers失败31项（3,945 passed）。来源前后
digest相同，无运行中源码变化。该run保留，不能标成全量通过。

providers中的11项是改写后两个旧提示词契约的精确断言不再匹配：
`test_character_embodiment_perspective.py` 10项与
`test_jev_interaction_completion_scope.py::test_generation_instructions_allow_ordinary_chat_without_fabricating_user_facts`。
最终版补回简短明确的普通场景身体第一人称规则与canon不限制闲聊的区别，
并把断言更新为同等语义的新措辞；没有恢复旧pose+review指令。
随后同批相关13模块333项通过，含这11项与全部40项新增合同。

其余29项来自此临时验证树的放置/复制条件：测试basetemp位于checkout内，
触发认证存储、记忆、配对、checkpoint必须在checkout外的既有守卫；
缺少复制的setup.py、CI文件、公开.env样例及Node构建依赖。未改这些守卫，
未把该失败算作业务RED，未为了本切片再次运行大套。最终完整gate由集成人在
完整合并树上运行，并使用checkout外的验证目录。

最终证据：`evidence/focused-final.txt`；16个最终合成请求及flag字节矩阵：
`evidence/final-captures/summary.json`；保留失败：`evidence/affected/summary.json`
及各lane stdout；完整失败node清单：`evidence/*-failed-nodes.txt`。
这些本地路径属于实施记录，正式发布时由集成owner选择同版本证据。
