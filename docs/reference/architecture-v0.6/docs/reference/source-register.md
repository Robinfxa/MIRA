# 来源登记与引用说明

**本次性质：在v0.4基础上回填D7的G05／G06同意与Codex usage优先偏好；归档G56R，并单独核查CX1–CX8官方文档。** 对原资料中的供应商、论文和框架陈述保留其原有证据边界；除CX1–CX8明确登记范围外，本书不重新核验原论文、框架及TypeSafe现状。GitHub方法参考读取固定提交的相关段落，不声称审计全部仓库或验证运行源码。

## 1. 本地材料

| 引用ID | 文件／位置 | 本书使用范围 | 地位 |
|---|---|---|---|
| REQ | [需求书原PDF](snapshots/requirements.pdf)，第1–6页 | 场景、语音、打断、多模态、交付与非目标 | 用户提供的产品任务依据 |
| V02 | [语音v0.2](snapshots/voice-v0.2.md)，§1–22 | 主控制基线、队列、授权、暂停／失效、TTS、filler、指标与验收 | Revised Design，待实现／PoC |
| MIRA | [人格记忆架构v0.1](snapshots/mira-memory-persona-v0.1.md)，§0–22 | 人格、来源、当前事实、剧情、Beat、回执与记忆 | 建议架构，未实现／效果测试 |
| SCENE | [角色／场景研究](snapshots/character-scene-research.md)，§1、§5–10 | 渲染边界、真实资产、能力映射、取消与验证 | 研究建议，不是稳定性认证 |
| COMPANION | [长期陪伴研究](snapshots/companion-research.md)，重点§3、§13–19 | 连续性、事实／理解分离、关系边界、分层评测 | 研究，不是全部功能批准 |
| PEER | [语音同行修订建议](snapshots/voice-peer-amendments.md)，§1–8 | 单仲裁、输入完整性、通话表达、分项实验 | 建议修订，不是已实施变更 |
| H1 | [Grill01](../history/grill-01.md) | 初始整合、判断目录、运行流程、G01–G06提案 | 历史草案 |
| H2 | [Grill02](../history/grill-02.md) | G01确认、非语音完成、quiet、G01.1提案 | 历史草案；G01.1状态由D2更新 |
| H3 | [Grill03](../history/grill-03.md) | G01.1确认、ResponseContract、G02-A细稿 | 历史草案；G02后由D4选择A，原历史不改写 |
| G3R | [G03生成承载论证v0.1](../history/g03-generation-argument-v0.1.md)，§0–14 | A／B／C比较、语义充分范围、前缀审核、封口、TTS依赖与14条拟执行用例 | 确认前的历史论证，原文不改；其路线后由D5确认，细节不整体冻结 |
| G4R | [G04停止范围／画面保持与恢复论证v0.1](../history/g04-interruption-argument-v0.1.md)，§0–14 | 停止／保持矩阵、收势、因果重新开始、条件恢复、routine与24条拟验收用例 | 确认前历史原文；后由D6批准政策，细节与能力不整体冻结 |
| G56R | [G05／G06联合论证v0.1](../history/g05-g06-joint-argument-v0.1.md)，§0–14 | 判断原语、D-M、受控图片与30条用例；保留原研究时点 | 确认前历史；D7修改主LLM／生图接入优先级，原文不回写 |
| D0–D7 | 本次可见对话；原文与摘要在A1／对应ADR | 既有决定与D7联合批准、订阅优先偏好 | 精确回复见ADR-0007；具体wire／账户／费用不被自动批准 |
| CX1–CX8 | [Codex／计划用量证据登记](codex-plan-usage-evidence-2026-10-02.md) | 本轮官方认证、订阅与生图能力、接口限制 | 公开文档读取，不是账户或性能验证 |

快照按挂载文件原字节复制，hash见`source-manifest.json`。原文中的历史链接、来源代码和“当前”表述仍属于原文写作时点，不变成本版重新核验的事实。本书不会因为附带原文就追认其中所有建议。G3R中的“G03待裁定”和“预期改动”保留为确认前历史；其当前状态以ADR-0005及模块正文为准。G4R的“待用户裁定”同样保留历史；G04当前由ADR-0006及M04承载。

## 2. ValueHermes固定提交方法参考

仓库：`Robinfxa/ValueHermes`。  
固定提交：`f141ccf842ffed23d33dba73e4da99b5703ccff8`。  
v0.1通过GitHub连接读取下表范围；本版沿用该固定提交的已登记方法参考，**没有重新读取GitHub或核验仓库现状**。不查询私有资料的公共替代来源。

| 引用ID | 路径与v0.1登记读取范围 | 采用的设计方法 |
|---|---|---|
| VH00 | `docs/architecture/00-master-design-book.md`，1–58行，重点§00–01 | 总书＋模块＋附录、来源与愿景分离、明确未决、生命周期×构件 |
| VH03 | `docs/architecture/modules/03-domain-state-store.md`，1–28行 | 状态契约先于执行节点，章节职责不混写 |
| VH05 | `docs/architecture/modules/05-blueprint-engine-control-plane.md`，9–45行 | 资产／确定性解释器／控制面分离，状态边界和唯一写入 |
| VH14 | `docs/architecture/modules/14-transparency-and-judgment.md`，17–49行 | 每条新判断通道审查权力，受限且可验证的语义判断 |

以上文件blob SHA分别为 `e826e74a289cd7b30d45af872fe9a2928de689f6`、`e392dd09c498555c8a970fb21d51e2c978a959d7`、`155cd5435fc79db3d87615796fa897a579e9e20c`、`790208909f95495339ba097623dca6a9e9b850ee`；它们是来源身份，不是本地副本的hash或完整阅读证明。总书SHA沿用前轮该固定提交的读取记录。

固定引用可由以下路径定位：

```text
https://github.com/Robinfxa/ValueHermes/blob/f141ccf842ffed23d33dba73e4da99b5703ccff8/docs/architecture/00-master-design-book.md
https://github.com/Robinfxa/ValueHermes/blob/f141ccf842ffed23d33dba73e4da99b5703ccff8/docs/architecture/modules/03-domain-state-store.md
https://github.com/Robinfxa/ValueHermes/blob/f141ccf842ffed23d33dba73e4da99b5703ccff8/docs/architecture/modules/05-blueprint-engine-control-plane.md
https://github.com/Robinfxa/ValueHermes/blob/f141ccf842ffed23d33dba73e4da99b5703ccff8/docs/architecture/modules/14-transparency-and-judgment.md
```

本版不移植投研业务、金融判断规则、正式／advisory账别、固定三库、L2子进程或完整DAG。不因架构方法参考而假定MIRA部署在Hermes插件中。前轮引用的ValueHermes评测／恢复教训保留在H1历史；本版相关技术正文仍直接以V02、MIRA与Grill条文为依据。

## 3. 引用与边界

正文采用`[V02 §11]`等人类可读引用，指向本表材料与原章节；它们不是供应商API参数，也不是工具引用占位符。案例台词、枚举和内部结构保留来源原有“建议／提案”地位。

当前包不复制ValueHermes整个私有仓库或实验明细，不含API凭据或字体文件。需求PDF与用户上传的文本快照用于来源复核；工程正文以分章架构为主，历史草稿仅追溯。

## 4. 本轮新增的公开证据

CX1–CX8的URL、读取日期、最小事实与不足集中在[证据登记](codex-plan-usage-evidence-2026-10-02.md)。不打包用户凭据或从网上拷贝的登录资料。本版继续沿用ValueHermes固定提交方法，未重新调用GitHub；G56R引用的SSR14只是已登记历史教训，不重启历史实验。

Codex产品订阅登录、专门授权的ChatGPT plan usage与Platform API-key分别按官方范围使用；接口文档存在不证明本应用或本账户已获得访问。M09的程序结构和安全默认是本产品细化，不冒充厂商验证结论。


## v0.6整合来源：架构基线与开源借鉴

| 本版别名 | 材料 | 地位 |
|---|---|---|
| ARCH-05 | [架构书v0.5原阅读版](../history/edition-v0.5/MIRA_架构全书_v0.5.md)及原分章 | 已确认架构和既有细稿；原八ADR保留 |
| OS-REF | [开源借鉴书v0.1原阅读版](../history/open-source-reference-v0.1/MIRA_开源实现借鉴书_v0.1.md)及15分章 | 现成实现证据和首联调建议；不自动批准具体栈 |
| OS-C01–C20 | 借鉴书固定源码／符号记录 | 原commit与阅读范围详见[A5](../architecture/appendices/A5-open-source-evidence-and-licenses.md) |
| OS-W01–W20 | 借鉴书项目／公开文档记录 | 本版未重新联网验证，保留原证据日期 |
| OS-VH01 | ValueHermes方法记录 | 私有材料只保留来源索引，不复制其正文 |

借鉴书中旧B1/B2/B3分别指ARCH-05、REQ和MIRA原稿；本书引用保留其来源关系。v0.6日期为2026-10-03，来源阅读记录2026-10-02不变。不得将技术支持／许可证／模型型号记录解释为本轮最新验证。

本轮编辑性新增的是模块映射、差分IC表、WP与RI追踪和统一构建，不新增上游事实。IC-01明确保留来源间承载边界分歧，其余适配差分均能回指相应源文。
