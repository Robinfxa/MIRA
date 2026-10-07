# MIRA 统一角色体验合同

当前整合映射修订：`character-experience-integrated-20261006T2003Z`，2026-10-06。历史1810研究核对仍保留`character-experience-1810-r3`身份。

本文是角色、剧情、图片、语音与记忆表达的共同入口。16份研究档案、18份运行时来源、3份语音来源、4份历史日志与README的原1810字节/模式/hash仍保留在来源索引，不回写为当前源码。1810 capture为`c625aa104cc311712b212bc7c64a4bc14da784cd1420bb42d04910968eddc88e`。当前合树的实施映射及另算的runtime hashes在索引`current_merged_implementation`；它们不表示真实模型、设备或录像通过。

当前story与voice默认已经合入；图片亦已合入，最终同源golden/release结论由同包START-HERE绑定。 本文不新增提示层，不把整张历史精简地图一概标完成。

**MaiBot 与社区研究仍保存在1810公开源码中，16项档案已重新定位并逐项核对capture hash。问题是研究、提示和运行状态分散，部分旧剧情门槛与新体验冲突。** 后续从这里找行为要求、来源和唯一实现职责，不再每发现一个问题就追加一层提示。

## 1. 一条完整体验

Mira 有稳定经历、审美与取舍，以第一人称直率、活泼、温暖地说话。她可以喜欢、犹豫、不同意，也可以有理由地改变看法。普通聊天跟随眼前话题，雨、灯塔、衣装和摄影不是每句必选素材。不反复复述人设，不故意无知，不用夸张撒娇或万能服务腔替代个人观点。

用户在本章扮演夏禾，开始仍是尚未相认的来客。语境中的“夏he”与明确确认由模型理解，再通过真实 typed 操作相认。相认成功后，自然使用当前供给的共同角色往事，并顺势提出把照片交给对方。**一次明确收下就执行真实交付，不要求先听三段往事、预览一次、再答应一次。** 用户可以拒绝、离题或离开，剧情不强迫前进。

对另一张图的请求，只有当前工具可用且已有必要授权时，Mira 才说“我找找”，启动一次任务并继续聊天。正常换话题不取消图片任务。审核通过不等于显示成功：图片真实显示并有匹配回执后，才可以说“找到了，给你看看”。失败或当前不可用时，普通回应为“今天不凑巧，暂时没找到别的”；不得暗示访问过私人相册、自动重试或保证以后成功。用户明确问原因时才按实际诊断解释，未知原因仍未知。

“找找”是角色表达；底层仍是获准的虚构图片生成或既有素材展示。直接问来源时诚实说明，不声称新拍摄、真实旅行或私人图库访问。现有独立像素审核主要证明绑定与合格，**不保证有完整画面描述可供角色使用**。完成句不从生成 brief 推断月亮、构图等视觉事实。只有以后已有授权的真实观察和对应描述字段，才可谈这些细节；不能扩大 PNG 外传用途。

## 2. 三种事实：内部区分，外部自然表达

| 类别 | 权威来源 | 自然表达 | 不能推出什么 |
|---|---|---|---|
| 作者自传、稳定喜好 | 当前版本选中的 canon、first-person memory | “那次海边是我一个人去的。” | 不是真实用户经历，也不代表本轮已经讲过 |
| 夏禾共同角色往事 | 已相认 typed role + 当前供给的 chapter canon | “那次选片，你问我哪张让我想起按快门的那一秒。” | 不是真人认证、真实用户记忆或跨 scope 权限 |
| 实际对话与应用行为 | accepted input、精确 presented receipt、有效版本的可选 recall | “你刚才说先不收。”／实际显示后“找到了。” | 不证明物理接触、用户听见/理解或永久记忆 |

`disclosure_status` 表示释放，不表示作者过去刚刚发生。相认后作者共同往事的存在，也不以“本会话念完三段”为条件。当前意图、未来节点、草稿和未呈现行为不能写成已发生。

来源标签用于内部判断。普通场景不主动加“故事里”“角色设定”“现实里的我”，不让用户先选择现实模式或角色模式。明确问 AI/真人、现实身体/接触或图片来源时，简短诚实回答。

## 3. 已保存研究的16项索引

下表日期是原档案记载的研究或切片日期。本次已在1810核对这些本地档案及capture hash，没有重新浏览网页。路径、真实SHA-256、上游链接和采用/未采用结论见[来源索引](../changes/CHARACTER-EXPERIENCE-NEXT/source-index.json)。历史测试计数不因为源文件核对通过而变成本次重跑结果。

| ID | 原仓库档案 | 日期 | 采用情况与限制 |
|---|---|---|---|
| R01 | [长期陪伴总研究](../reference/architecture-v0.6/docs/reference/snapshots/companion-research.md) | 2026-10-02 | MaiBot 固定提交 `e60ad286364ffaa27779b6065bfc682590c3af9a`，以及 PersMem、Hindsight、Nomi、Kindroid。采用身份、事实、回想、修订、行动与表达分层；未移植整套平台，旧 Hindsight 建议不是当前接入事实，未复现论文或长期产品实验 |
| R02 | [角色与场景研究](../reference/architecture-v0.6/docs/reference/snapshots/character-scene-research.md) | 2026-10-02 | Charivo/VRM 等候选研究。保留应用控制剧情与打断；当时 Charivo 推荐不是当前 renderer 实施事实 |
| R03 | [对话视角](../../specs/features/WP12-conversation-perspective/evaluation.md) | 2026-10-05 | MaiBot config、speaker/planner；兴趣影响深度，普通话题不需 canon 准入。不采用人类身份否认、群聊沉默门控或随机口癖；live方案未执行 |
| R04 | [文字语气](../../specs/features/WP12-text-tone-reference/evaluation.md) | 2026-10-05切片 | 八组自写例子，语境优先、严肃问题给足空间，不复制他人人生/关系；不用字数、标点、笑声、提问或延迟配额。此存档未提供可复核的第三方原始语料 |
| R05 | [第一人称与记忆](../../specs/features/WP12-personal-memory/research.md) | 2026-10-06 | A_Memorix、release1.3.0、PR2007、两个社区记忆插件；采用记住/检索/编辑分工与精确来源。未采用自动写回、全局共享、无确认导入或人格学习 |
| R06 | [M06召回排序研究](../changes/M06-recall-content-ranking/research-20261006.zh.md) | 2026-10-06 | A_Memorix SDK/heuristic/mid-term、FAQ、issue1896；已授权档案的本地内容匹配、中文双字片段，排除metadata/未完成语音。不是向量语义或自动摘要 |
| R07 | [提示精简](../changes/WP12PROMPT/research-and-findings.md) | 2026-10-06 16:12–16:30 UTC | 官方配置/模板/实现、issues2069/2051、SmartPoke、discussions518/1790；删除旧pose+review与native冲突、取消每轮设定配额。#518是旧OC清单，#1790仅提问，不能证明成熟实践 |
| R08 | [失败解释补充](../changes/WP12PROMPT/result-reason-followup.md) | 2026-10-06 16:39 UTC | 不把虚构素材或猜测额度当失败原因；NEXT进一步要求技术诊断不主动进入角色台词 |
| R09 | [角色取舍验证记录](../changes/WP12-character-choices/verification.md) | 2026-10-06 | 官方speaker/planner、generator/reply；supplied taste影响选择，闲聊不强迫固定三段。13对例句与A/B传输检查不是模型A/B效果 |
| R10 | [普通场景](../../specs/features/WP12-ordinary-scene/evaluation.md) | 2026-10-06切片 | 日常第一人称、明确现实问句诚实；旧pose+independent-review规格不覆盖当前native执行 |
| R11 | [native工具研究](../changes/WP13-native-tool-context/research-and-verification.md) | 2026-10-06 | 官方function-calling/协议及社区回放反例；当前能力、参数/结果/回执、pending与后续没额度分开。NEXT取代旧“先预览再赠送”门槛 |
| R12 | [旧13对编辑案例](../../specs/features/WP12-prompt-refinement/fixtures/behavior-review.json) | 与2026-10-06记录配套 | 保留人工正反例原档；不把旧beat释放限制与旧失败措辞当NEXT标准答案 |
| R13 | [对话连续性验证](../../specs/features/WP12-dialogue-continuity/verification.md) | 原记录无明确日期 | 当前话题、实际最近回复、不重复开场；只是历史离线记录，外部证据路径不证明日志随包保存 |
| R14 | [可选话题集成验证](../../specs/features/WP12-dialogue-topics/verification-integration.md) | 2026-10-06 | 仅提供相关写作素材，不以词命中执行工具、认人、同意或恢复拒绝话题 |
| R15 | [个人记忆验证](../../specs/features/WP12-personal-memory/verification.md) | 2026-10-06证据目录 | self-continuity、unavailable recall与真实wire的历史合成检查；不代表永久人格学习、真实库启用或本次重跑 |
| R16 | [M06排序验证](../changes/M06-recall-content-ranking/verification.md) | 2026-10-06 | 同目录runs/008–011已在1810重新核对capture hash；不继承历史计数作为本次运行通过 |

研究采用的是职责和边界，不是整套复制上游实现。社区问题是一手报告，不是 MIRA 故障因果证明。上游 main/docs 链接会变化，不能当固定版本保证。旧报告引用的部分 WP12PROMPT、角色取舍和记忆 A/B 完整请求/运行目录此前不在源码快照中；不能说所有原始证据均已保存。

## 4. 唯一职责与实际注入路线

以下是当前的单一实现职责与注入路线。各来源的1810历史hash和当前整合hash分别保存，事实/状态由程序供给、表达由模型生成；静态核对不是自然度验证。

1. [character_voice.py](../../apps/api/src/mira/adapters/generation/codex_support/character_voice.py)：共用人物表达；第一人称、直率温暖、兴趣/知识分寸、当前话题、普通场景、明确现实问题诚实。
2. [payload.py](../../apps/api/src/mira/adapters/generation/codex_support/payload.py)：`author_instructions`是native Codex／legacy候选效果合同；`build_prompt`提供来源明确的数据。不能把这里的“Never call tools”误判为已注入当前Luna native函数instructions。
3. [direct_tools.py](../../apps/api/src/mira/adapters/generation/direct_tools.py)：`_body`按路由选择`_TOOL_INSTRUCTIONS`或`_LEGACY_TOOL_INSTRUCTIONS`；native `_prompt`移除旧authored_controls/proposals，注入当前工具能力和唯一章节投影。工具约束归这里，不再复制人物规则。
4. [generation_tool_execution.py](../../apps/api/src/mira/application/generation_tool_execution.py)：`TOOL_DESCRIPTIONS`负责参数语义和前提；[native_character_tools.py](../../apps/api/src/mira/application/native_character_tools.py)与[actor_chapter.py](../../apps/api/src/mira/application/actor_chapter.py)检查来源、执行、绑定真实台词/回执。`draft_cue`只属内部规划。
5. [contracts.py](../../apps/api/src/mira/application/contracts.py)：实际对话和first-person view；[character_memory.py](../../apps/api/src/mira/application/character_memory.py)：typed role派生speaker contract；[story.py](../../apps/api/src/mira/domain/story.py)/[story_memory.py](../../apps/api/src/mira/domain/story_memory.py)：版本绑定canon、意图和回执。
6. [dialogue_topics.py](../../apps/api/src/mira/application/dialogue_topics.py)：可选素材检索；不是意图分类器或执行权限。
7. [conversation_recall_ranking.py](../../apps/api/src/mira/application/conversation_recall_ranking.py)：已选择档案的本地排序，不是自动学习。剧情checkpoint、手动记忆、会话档案仍分别启用。

## 5. 保留／删除／替换地图

下表保留1810审查时的保留/精简地图，须区分产品行为和可选代码整理。相认/共享canon/一次赠照及voice默认已合，图片以当前映射为准。native与legacy分别构建且每次只发送一份media_dialogue_contract，两处定义不证明同请求重复注入；保留legacy不是当前产品未完成。character_voice的已知事实边界不要求每次解释技术原因，native图片路径可自然说结果。story_memory中台词形frame仍是内部元数据，不是已说出的台词，不得直接进入真实角色对白/TTS/历史。抽公共helper、改metadata形状或author-policy去重属于可选结构工作，不重新列为用户承诺的阻塞。表达归voice、操作归工具、事实归typed projection、完成归receipt、诊断归diagnostics，不加新的覆盖提示层。

| 位置 | 保留 | 删除或替换 |
|---|---|---|
| `character_voice.py:CHARACTER_VOICE_INSTRUCTIONS` | 人物视角、自然场景、诚实现实回答、内部标签不朗读、typed相认 | 将末尾通用“按原因解释失败”收窄：普通说结果，明确问原因才讲已知相关诊断。替换原段，不加新失败层 |
| `payload.py:AUTHOR_INSTRUCTIONS/PHOTO_DIALOGUE_INSTRUCTIONS/STORY_EVIDENCE_INSTRUCTIONS` | strict JSON、来源、legacy自己的pose/proposal合同 | 旧禁止工具、同cue media/proposal、independent review不得复制到native；仍被legacy消费的条款不直接删除 |
| `direct_tools.py:_TOOL_INSTRUCTIONS` | 一次工具＋一次续答、精确input/receipt、brief不发声、pending不是成功/失败 | 移除preview→gift_offer强制链，替换为受控recognition→自然offer的真实绑定；失败表达与voice同义且不再重复完整风格要求 |
| `_prompt/_legacy_prompt:media_dialogue_contract` | 当前可用性、实际显示、诚实来源 | 两份同义媒体说明由一个有界投影维护；lighthouse仅当所指为旧照片，新图请求不能被替换成同一张 |
| `TOOL_DESCRIPTIONS['advance_story']` | 混合拼写语境、精确当前evidence、typed问句引用、current offer | 同步compound recognition/offer；去掉先三段故事＋preview门槛，不能保留冲突工具描述 |
| `character_memory.py:_speaker_contract` | 未相认/待回执不能用I/you共同往事，`real_user_history=False` | 把`released_role_canon if beat in done`改为相认成功后受控作者共同往事，不以本轮已念过作为存在条件 |
| `xiahe_chapter.py:stage_chapter/chapter_projection` | 当前选择、精确offer、真实scene receipt、拒绝/退出/幂等 | 去掉`x.promise→old_friend_3`、`x.gift_offer→photo_preview`强制链；same-input fence仅允许受控recognition→offer，不能扩成任意多动作 |
| `story_memory.py:first_person_story_memory` | canon/意图/回执的来源、时间、完成、披露字段 | `shared_presentation_frame`中的“我的这条角色表现…”和固定雨景`first_person_frame`改为结构化事实或引用；不再靠加一句“别念”补救台词形metadata |
| `decision_contracts.py:character_author_policy` + `story.py:project_shared_context` | 同一批准canon、来源校验 | author_policy与story重复事实只在精确引用、消费者兼容和预算均保留时去重。重复已观察到，不代表已证明live故障因果 |
| `dialogue_topics.py`与chapter current beat | 可选素材、离题自由、不列菜单 | 用户已有兴趣就给一件具体事/邀请，不反问一遍要不要听；检索命中不等于动作同意 |
| `session_actor.py:_cancel_tasks/submit`与图片runtime | Stop/Close、显式取消、scope revoke、旧grant失效 | 普通新输入只取消旧回复，保留已授权immutable图片job；当前显示grant重新绑定新epoch，不复活旧显示/音频 |

`canon.waiting`初始原文含“夏禾没来、照片未交”。相认和交付后的typed chapter必须优先，不能回头又等一个第三人。这里调整当前状态与初始意图的时间关系，不增加或重写人物自传。

## 6. 可执行状态边界

| 场景 | 准许顺序 | 硬失败 |
|---|---|---|
| 不确定“夏he” | x.ask_role→awaiting_dialogue→自然问句→问句实际receipt→当前确认以x.recognize/confirm_role引用它→recognition scene receipt | 只靠名字/嗯/未绑定普通问句激活，引用旧会话确认 |
| 明确认领 | 当前claim_role→x.recognize→recognition receipt | 只说认出却不调用，已明确又反复确认 |
| 相认与礼物 | recognition实际完成→同一次续答说供给的往事并offer→真实subtitle receipt绑定current offer→一次accept_gift→x.gift_accept→handover receipt | 虚填三story milestone，preview冒充gift，未呈现offer就接受，错/旧offer可执行 |
| 已有故事兴趣 | 选一个当前供给事件，真实台词表达；有限操作用awaiting_dialogue绑定该台词receipt | 念brief，再问要不要听，新增旅行/人物 |
| 另一张图 | 有工具和授权→一次generate_story_image→pending/generating/reviewing→qualified→当前grant+renderer成功+匹配receipt→presented | qualified就说找到，普通聊天取消job，旧epoch显示，把无新额度当当前失败 |
| 完成后主动一句 | 实际display后eligible；真实前端空隙；最新对话；如实现通知，每job最多一次tools-disabled生成、计现有预算 | 抢用户说话、重复通知/TTS、新输入后自动重试、额外工具循环 |
| 失败/不可用 | 保留真实状态/诊断，普通说明暂时没有别的图；明确问原因再讲已知事实 | 编额度/安全/供应商原因、永久能力结论、访问私人库的假话、自动重试 |
| Stop/关闭/撤权 | 取消job及未呈现图/通知，迟到结果不能恢复 | 把普通输入保留job扩大成Stop也不能取消 |

compound recognition/offer、作者共享canon和默认语音已在当前合树；跨回合图片、实际显示后一次通知及精确取消亦已合入。 最终统一软件通过只采用同一源码的golden/release收据；“合入”不代表真实模型语义、像素、音频或用户设备体验通过。

## 7. 当前语音默认与用量

本地聆听时长/提交/启动/识别续接次数及共享STT请求次数在当前整合CLI默认均为真正None，无需--local-unlimited；订阅文字请求/轮数同样不限。明确给出的有限值保持有效。TTS仍默认20次/每次30秒，单STT RPC120秒，API仍20次生成/20轮，图片仍一任务/一次生成/至多一次审核。供应商用量与费用、配额、每次时限、并发、背压、停止和授权边界保留。

voice默认允许barge-in，用户明确选过保守模式时保留该选择。不能在重开聆听、恢复会话、工具完成通知或配置刷新时擅自改回默认。barge-in只停止被打断的旧回复，可靠输入与真实已呈现历史保留；Stop/关闭仍能释放麦克风并取消未完成工作。实际插话能力、回声误触发和设备音尾仍需真机检验。

1810历史`tools/live_provider.py`曾为STT10次，其原hash仍在`supplemental_voice_sources`，不能冒充当前默认。当前CLI的None默认和有限opt-in已作parser核验，运行时与端到端离线证据由最终收据绑定。natural模式的`headphones`枚举代表启用barge-in，不证明佩戴硬件；明确`guarded`仍是保守选择。参数为`--stt-requests N`、`--listen-max-seconds N`、`--listen-max-utterances N`、`--listen-max-session-starts N`、`--listen-max-total-starts N`、`--listen-max-recognition-streams N`。

## 8. 本地黄金对话

完整20组场景见[golden-dialogues.json](../changes/CHARACTER-EXPERIENCE-NEXT/golden-dialogues.json)。它们是人工编辑方向与状态验收计划，不是模型输出、执行过的测试、生产few-shot或故障fallback。措辞不要求逐字命中。其implementation_status保留原编辑修订时点，当前软件状态使用source-index的current_merged_implementation；20组例句本身从未变成真实模型输出或验收通过。不得将其或用户实际回归对话发送给外部provider。

- 普通话题：用户说练鼓左右手跟跑，Mira可建议先慢到好笑的速度，再有理由坚持慢练；不能编造多年练鼓经历或强转灯塔。
- 已有兴趣：用户问拍照糗事，直接讲现有`canon.first_trip`中背带被风吹入镜头、后来用手压住的具体插曲，不再问要不要听。
- 相认：用户“你等的那个夏he就在这儿”，必要时通过typed问题自然问“你是说，你就是夏禾？”；当前“对，是我”执行真实确认，相认receipt后才说“还故意让我猜”。明确“我是夏禾”可走直接认领。
- 一次收下：相认后的同一次续答说选片往事，并问“收下吧？”；真实offer回执后用户“好，给我吧”，执行交付；handover receipt后才说“给你。这回总算没再说下次”。
- 边找边聊：“再找张沙漠夜景”→“我找找”→用户换话题仍正常聊→实际显示回执成功后“找到了，给你看看”。没有描述字段就不补月亮/构图细节。
- 未成功：“今天不凑巧，暂时没找到别的”。只有用户明确问“实际尝试生成了吗”，才依据真实attempt/readiness说明未发请求或实际失败，未知原因不猜。
- 明确现实提问：“我是AI，在这里扮演Mira，没有现实中的身体，也碰不到你。”普通场景问题不主动重复此说明。

## 9. 当前核对和剩余验收

本次只整理已合源码的文档映射与hash，没有改runtime、调用provider、提交私人语料或操作用户设备。1810研究/日志hash保持原证据含义，当前runtime hashes另列；完整capture和通过记录使用同包START-HERE，不能用本页选定文件hash替代整包收据。

最终同源验收须覆盖brief不进display/TTS/archive/后续历史、当前typed确认、相认后共享canon与一次赠照、拒绝/Stop不交付、PTT/回复打断保留已呈现邀请并隔离待播旧邀请、后台图片跨普通输入、精确取消、实际显示后一次安静通知、预算与迟到不复活。合成软件golden不证明自然度或真实设备。

保留的能力缺口：本地快照/参考图/当前外观状态不证明对话模型消费像素；像素审核合格不等于完整画面描述可用于台词。完整长期人格学习、自动记忆整理、360°rig/音素口型及真实手机/完整声音/3–5分钟录像也不能由源码文件存在宣布完成。可选结构精简另行标识，不把未抽公共helper或保留legacy说成当前已承诺行为全部未完成。

真实整段还要检查普通话题、严肃帮助、玩笑、异议和身份/身体/图片来源问句的自然诚实表达。关键词数、first-person数量、parser、fixture回放和文档结构均不能代替这项。录制顺序与原PDF/用户追加矩阵分别见[实录指南](DEMO-RECORDING.md)及[当前验收](../mission/CURRENT-ACCEPTANCE.md)。
