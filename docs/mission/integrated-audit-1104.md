# MIRA 集成候选独立审计：2026-10-03 11:04 UTC

## 结论与范围

**该候选可以证明相当一部分离线控制、安全边界与资源管理已经实现，不能标为完整产品验收通过。** 独立对抗检查发现 3 项实质问题：开发原始录制的嵌套凭据过滤绕过、未来字幕提前呈现/记账、Codex 上下文与音频事实数量上限不匹配；另有错误提示被覆盖与非 ASCII token 处理的较小缺陷。未发现已审范围内可以复活旧音频/旧轮的控制绕过。

- 审计源码仅来自冻结目录 `<project-root>`；源码未修改。
- 需求依据：`docs/mission/requirements-and-acceptance.md`、`docs/NORTH_STAR.md`。已读 AGENTS 及指定基础文档。
- 捕获清单 1,277 项，捕获期间变更为空。独立重新校验 1,275 项哈希均未变化；按不读取 dotenv 的约束，2 个 dotenv 命名示例文件未读取/复核，不能把它们写成独立已校验。
- 既有 coherent-full 收据：10 个离线 lane 通过，741 Python、115 Node；source before/after digest 均为 `68110f45a1a05608a34183770850e3bc18afbbf840424eda279c06baa67121ef`。该收据明确 package、smoke 为 not_run；不含设备、浏览器、供应商验收。
- 本次另跑 52 个 Python 和 44 个 Node 定向检查，全部通过；独立新增对抗脚本仍复现以下缺陷。这说明已有测试未覆盖这些集成合同，不能用通过数量抵消缺陷。
- 无真实供应商、账号、ADC、私人认证文件、dotenv、浏览器或音频设备调用；未重试已拒绝的本地浏览器路线。HTTP/WS 测试为进程内 ASGI TestClient，无网络监听。
- 正在另线修复的启动/打包与 semantic Actor wiring 是冻结时已知未完项，本报告不将其重新包装成新回归。

## 优先发现（均以冻结版本为准）

### IA-01 · P1 · 开发原始录制会保存嵌套 JSON 凭据

**复现结果：** 直接录制合成文本 `{"api_key":"SYNTHETIC_UNKNOWN_CREDENTIAL_7719"}` 被正确拒绝；同一文本进入 `GenerationContext.user_text/user_inputs`，再由模型输入录制路径包装为 JSON 后，完整合成凭据却以 `privacy_review=approved` 写入原始文件。显式原始导出再次校验后仍包含它。普通诊断导出不包含该内容。

位置：
- `apps/api/src/mira/application/diagnostic_events.py:176–184` 先 JSON 序列化整个模型内容。
- `apps/api/src/mira/adapters/diagnostics/recorder.py:153–164` 对平面字符串过滤后自动赋予 APPROVED。
- `apps/api/src/mira/adapters/diagnostics/privacy.py:121–128,140–146` 正则不识别转义后的内部键。
- `apps/api/src/mira/adapters/diagnostics/privacy.py:167–190` 原始导出复核再次走同一平面过滤。

影响：USER-OBS-03 的凭据结构永不合格规则被违反。这不是无法保证识别所有口述秘密的泛化风险，而是已经支持的明确凭据结构被常规模型包装绕过。仅在显式开启原始录制后触发；默认仍关闭，未发现默认普通日志泄漏。

建议回归：嵌套/多重转义、Unicode 转义键与值、MODEL_INPUT/MODEL_OUTPUT、活动秘密和不确定 JSON；所有不确定结构拒绝或安全递归检查，安全对话仍可录制，普通导出继续排除原始内容。避免用无限解码或无界递归取代当前问题。

证据：`var/mission/independent-audit/1104/privacy-adversarial.py`、`.json`。这是保留缺陷现状的断言脚本，不是修复后应通过的安全验收。额外 8 种输入 × 3 条录制路径的独立矩阵有 18/24 项出现合成凭据留存；安全对话 2 项与默认关闭正控成立，见 `1104/privacy-matrix/summary.json`。同一矩阵将用于修复后复验，未扩大为所有秘密均能识别的承诺。

### IA-02 · P1 · 所有字幕立即呈现，先于对应语音

**复现结果：** 一个通过真实 `parseSession` 校验的当前快照包含 speech 1 / subtitle 1 / speech 2 / subtitle 2。controller 仅打开 speech 1 且尚未收到任何 PCM，画面已显示 subtitle 2，两个字幕回执均已经排入历史。

位置：`apps/web/src/features/session/controller.ts:121–127` 同步执行全部非 speech grants；`:181–200` 单独逐个启动 speech。`EffectView` 当前没有明确的语音/字幕关联或时间组。

影响：PDF-08 的对应语音同步字幕不成立。仅最后字幕可见时，前面字幕甚至可能在同一 JS 任务内被覆盖但已登记“呈现”。如果未来动作/媒体同样依赖具体语音段，当前逻辑也没有时间分组来阻止提前消费。这是时序缺陷，不是 Stop 后旧网络结果复活的证据。

最低正确语义：有语音的字幕与对应 speech/cue 绑定，在它真正开始呈现时才显示并记账；未开始的下一段字幕在 Stop 时不得显示或记账。独立的纯文字范围仍可立即显示。动作/照片是否等语音，应由明确 cue/范围关联决定，不应按文本相同或把所有视觉动作一概延迟。已显示照片/环境仍须保留。

建议回归：双语音双字幕；暂停首包；首句播放期间授予下一范围；speech 2 开始前 Stop；无语音 text-only；语音失败；迟到 source/媒体回调；回执仅代表实际启动的对应呈现。

证据：`var/mission/independent-audit/1104/frontend-adversarial.mjs`、`.json`。

### IA-03 · P1（接入 live 前）· 32 秒语音事实即可阻断后续 Codex 轮次

**复现结果：** 通过真实 Actor/audio_progress 域转换提交 128 个单调 RENDERED 事实（每个 6,000 samples、24 kHz，共 32 秒）及 1 个 COMPLETED 事实。下一轮完整 129 条历史到达真实 Codex `build_prompt`，被拒绝为 `codex_context_invalid`，该轮变成 `generation_failed`。

位置：
- `apps/api/src/mira/application/session_actor.py:114–115` 向 GenerationContext 传完整追加式音频账本。
- `apps/api/src/mira/adapters/generation/codex_support/payload.py:77–79` 最多允许 128 条音频事实。
- 域账本允许 4,096 条，浏览器每个自然结束音频 buffer 产生事实；服务端每块最多 6,000 samples，因此该例使用正常块大小。

影响：PDF-01/09 的 3–5 分钟连续交互需要更长的有效上下文生命周期。该缺陷属于真实 carrier 接入时的已有合同不兼容；当前固定 Mock 不走 Codex，因此不能声称当前 Mock 32 秒后必然失败，也没有进行真实推理。

建议：模型上下文提供有界、每个 effect 的最新音频事实投影，完整账本仍用于实际呈现历史、诊断和重复检测。保留 rendered samples 与 terminal status，不能把部分播放升级成完成/听见。覆盖多轮累计事实、部分中断、completed 和无音频负控，并检查字节上限。

证据：`var/mission/independent-audit/1104/context-budget-adversarial.py`、`.json`。只调用真实 prompt validator，不启动 Codex。

### IA-04 · P2 · 安全错误指引被裸错误码覆盖

位置：`controller.ts:119–120`、`apps/web/src/app/main.ts:41–43`。

错误快照先调用 `view.update`，得到“生成超时，请重试。”；随后 `fail(new Error(snapshot.last_error))` 再调用 `view.error`，把同一输出覆盖为 `generation_timeout`。该次 UI 留下裸代码，丢失恢复方向；也没有关联到这次异步失败的用户可见诊断号。未发现私密异常文本通过这一路径泄漏，服务端值已有白名单。

建议回归：用实际 main view 行为验证最终用户可见文本，而不是仅测 `safeSessionError` helper。保留稳定错误码、恢复方式与可定位关联，避免恢复消息再被覆盖。与 IA-02 共用前端脚本证据。

### IA-05 · P3 · 非 ASCII WebSocket token 产生未处理 TypeError

位置：`apps/api/src/mira/application/sessions.py:38–40` 以 `secrets.compare_digest(str,str)` 比较；`entrypoints/http/media_routes.py:163–164,185` 允许此形状进入但没有处理 TypeError。

进程内合成 WS 使用存在的 session ID、允许的 Origin、长度合法的中文 token，得到 TypeError，未走稳定认证错误。没有获得会话权限、没有调用 provider；这不是认证绕过。

建议：在公共边界将 token 限定为生成器实际使用的 ASCII URL-safe 字符/长度，或安全转换比较并统一拒绝；未知/不存在 session 也要保持一致。回归应断言安全拒绝、provider 零调用、无异常逃逸。证据：`boundary-adversarial.py`、`.json`。

## 已检查的合同与未证明事项

### Cancel / Stop / stale：离线控制路径有较强证据

- controller interrupt 同步 block → playback stop/disconnect → abort transport/capture，然后才发 stop/new input；generation/activity guards 覆盖异步结果。
- gate 检查 session/client/permit/revision、效果不可变身份、当前活动及 expected request；更高 permit 不能自动解除本地 Stop。
- Actor provider wait 不持有转换锁，旧 output epoch 不能产生新 grant；媒体读取同时等取消并丢弃迟到数据。关闭、停止和替换拥有不同诊断原因。
- 回执 cutoff 与音频 terminal facts 独立；旧的有效事实可以补充历史，不恢复 grant/phase。部分软件 rendered 不等于完整文字已被用户听见。
- 本次 44 Node/52 Python 定向覆盖中，旧输入、旧音频结束、旧采集准备、旧回执失败、Stop 与队列阻塞均无新回归。
- 这些仍是软件/合成音频节点证据，不能声称扬声器在真实手机上声学立即停止。

### HTTP / WS / token：未发现权限绕过

独立 ASGI 检查：跨会话 token 404；敌意 Origin 403；敌意 Host 400；超大控制 body 413；WS query token 和不允许 Origin 均 1008；删除后的 token 404。token 保存在浏览器内存，通过 HTTP header 或第一条 WS 消息传输，不进入 URL/持久化存储。静态服务仅 public/dist，错误响应和普通事件采用安全字段/代码。IA-05 是健壮性缺陷，不改变上述拒绝结果。

这是 loopback/单 worker 的能力 token 边界，不是生产公网身份系统。未做公网部署、安全渗透、浏览器级跨域或大规模负载验收。

### 诊断 / 原始录制

默认原始录制关闭；启用同时要求显式开关和 consent。原始目录与普通事件隔离；普通导出重新校验且排除原始内容；队列有条数/字节上限，文件轮转、保留期、权限和无 symlink 跟随已有实现与定向通过证据。日志 IO 故障不会阻止 Actor/取消路径。页面顶部有持续录制/未知状态提示。

IA-01 使“开启后的凭据过滤可靠”不能验收通过；IA-04 使“实际用户错误输出有恢复指导”不能验收通过。前端 TTS/STT transport 对供应商错误仍常退化为通用消息，真实故障定位体验需连同 live 集成复验。

### 原创场景与可见反馈

源码包含明确 26 岁角色、原创本地 SVG 背景/旅行插画、可分离脸/眼/相机图层，CSS 有四态运动、不同表情、相机放低/看雨动作、环境变化和 reduced-motion 分支。renderer 使用 textContent 与白名单视觉值，无外部媒体 URL 或可执行内容。Stop 保留已显示照片/环境。

这比仅状态枚举/DOM 占位更完整，但本次未看实际浏览器像素、移动布局或动画质量；不能把源码的可选状态数写成用户已辨认的通过数。固定图片加载失败/延迟时，renderer 目前只切 hidden 并立即回执，未见 load/error 驱动反馈或图片实际可用性回执；列为待真实媒体负控验证的实现缺口，未声称已实测图片失败。

## 需求矩阵（冻结候选）

| 需求组 | 本次状态 | 证据与边界 |
|---|---|---|
| PDF-01/09 连续 3–5 分钟 | not_run；IA-03 为接入阻断 | 无连续真实录制，Codex 历史上限已复现 |
| PDF-02–04 场景主体/入口/移动优先 | implemented / browser not_run | SVG/布局/输入源码存在，不能代替窄屏/桌面像素检查 |
| PDF-05/17–22 四态/表情/动作/环境/动画 | implemented / visual acceptance not_run | 存在真实图层与 CSS 变化；内容 cue 仍受 IA-02 影响 |
| PDF-06 文字输入 | offline pass subset | Mock 输入—审核—许可—视觉控制有离线证据 |
| PDF-07 真实麦克风 | blocked/not_run | 浏览器采集/WS/STT adapter 合成证据；ADC/真实设备待验 |
| PDF-08 语音与同步字幕 | fail | IA-02；无真实扬声器验收 |
| PDF-10–15 打断/失效 | offline pass subset | 软件控制守卫较强；真实声学停止/新语音闭环待验 |
| PDF-23/24 视频/动态生图 | not_applicable to selected animation branch | 当前采用角色动画；不把静态素材当运行时生图 |
| PDF-25 真正模型闭环 | blocked/not_run | Codex live 401、Google ADC pending、JEV 中文未校准；不重试这些资源 |
| PDF-26 故障反馈与恢复 | partial/fail | IA-04；媒体资源失败与真实断网恢复仍需 UI 验证 |
| PDF-27 无私人 key 模式 | explicit offline subset | Mock/replay 标签、fixture 限定审核、无静默付费/live 回退；完整无钥匙有声核心体验尚待接线 |
| USER-OBS-01/02 诊断定位/有界日志 | partial | 日志实现/定向测试通过；IA-04 与真实关联体验未验 |
| USER-OBS-03/04 原始录制与隔离 | fail / default-off pass | IA-01；普通导出隔离、默认关闭和独立同意已验证 |
| PDF-28/D01–D07 交付材料 | incomplete/not_run | 启动/打包另线修复，完整源码—录屏对应、干净启动、3–5 分钟录屏、README/AI_USAGE 最终收口未完成 |

## 下一次收口必须建立的证据

1. 修复 IA-01/02/03，并将合成负控加入对应唯一 owner 的测试；重新冻结，跑 affected，再由集成负责人跑一次 coherent full/release。
2. 对 IA-04/05 做真实入口输出回归，不能仅测 helper 或内部异常。
3. 在获准且可用环境完成实际页面 → 真实模型 → 可听语音 → 字幕/动作 → PTT 打断 → 新输入；明确账号/模型/JEV 限制。
4. 桌面与窄屏分别记录；真实手机另记。执行延迟、断连、权限拒绝、TTS/图片失败与恢复。不能绕过已拒绝的浏览器限制。
5. 按实际版本录制连续 3–5 分钟；完成干净启动计时与最终材料。自动化测试不填写为人工验证。

## 证据命令

所有脚本均存于 `var/mission/independent-audit/1104/`，运行时 cwd 必须为冻结目录；Python 使用 canonical `.venv313/bin/python` 与 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps/api/src`。

- `privacy-adversarial.py`：原始凭据过滤负控；只用合成标记，生成独立私有临时目录。
- `context-budget-adversarial.py`：真实域事实 → 真实 Codex prompt validator 的数量合同负控，无 subprocess/live。
- `frontend-adversarial.mjs`：schema-valid 多段字幕提前消费与 UI 错误覆盖；由冻结 TS 编译到证据目录。
- `boundary-adversarial.py`：无网络 ASGI HTTP/WS 权限和畸形 token 检查。
- `scoped-pytest.log` / `scoped-junit.xml`：52 passed。
- `scoped-node.log`：44 passed。
- `integrity.json`：1,275 个允许读取的捕获项未变化。

以上是独立审计发现和证据，不是发布批准，不自动适用于后续正在修改的 canonical。

## 后续独立复验：IA-01 隐私修复候选（2026-10-03 11:25 UTC）

此节是集成负责人另行批准的窄范围复验，**不改写上面的 11:04 冻结缺陷证据，不代表其他发现已修复或新版本全量通过**。

- 候选输入：`var/mission/obs-02-candidate-1123/apps/api/src`，由隐私修复负责人提供的冻结源码副本。
- 隐私文件 SHA-256：`c855de70f45df3ad3aa18c52d9c6ec8ed61f4c8dbe06551ec4ce7c0878175179`。另核对 recorder、export、diagnostic_events，4 个生产文件均与移交哈希一致。
- 使用**同一份未修改的 24 项独立矩阵**：原冻结版 18 项凭据留存失败 → 修复候选 0 项凭据留存失败；普通诊断导出始终没有合成凭据；安全对话 2 项仍保存；默认原始录制仍关闭。
- 相邻正负控全部成立：含引号/换行的已注入活动秘密在模型 JSON 包装中被递归移除，review 标为 redacted；未经原音频隐私审核的数据拒绝；仅开关、缺 consent 不能启用；人工写入的历史 unsafe nested-credential raw 记录被显式原始导出重新校验并跳过。
- 静态复核：JSON 解码后的键/值、嵌套字符串和 prose 片段均接受有界审核；异常结构、重复键、非有限数与深度/节点/字节预算超限按不确定拒绝。未发现该候选对默认普通事件日志或会话控制的范围扩大。
- 修复负责人报告 61-case RED/GREEN 与 108 项回归通过；本次**未独立重跑这些数字**。移交 manifest 列出的新测试文件未复制到其冻结候选，独立验证只报告实际执行的矩阵、相邻控制与生产哈希。
- 结论：IA-01 的已复现结构化凭据绕过在此候选上通过独立窄范围复验。仍不得保证识别所有秘密、所有编码、同形字符或音频中的口述秘密；原始录制不因这次测试自动获准开启。

复验证据：`var/mission/independent-audit/privacy-candidate-1123/summary.json`、`adjacent-summary.json`；脚本为 `privacy-candidate-check.py` 与 `privacy-adjacent-controls.py`，旧版失败矩阵仍保留在 `1104/privacy-matrix/summary.json`。

## 后续独立复验：IA-03 / IA-05 集成负责人修复（2026-10-03 11:26 UTC）

按负责人批准，从 canonical 复制 71 个 Python 源文件至 `var/mission/independent-audit/director-candidate-1125/apps/api/src`；捕获前/后/副本哈希一致。未重新执行整个集成或真实 provider。

- **IA-03 已复现案例通过**：原样 128 × 6,000-sample rendered + completed；完整 session 账本保留 129 条；下一轮模型上下文只有对应效果最新 1 条，真实 `build_prompt` 接受，next phase 为 ready、无 last_error。相邻检查证明 interrupted 与实际 samples 原样保留，部分语音仍不列入 fully presented；身份不一致的事实不被错误合并。
- **IA-05 已复现案例通过**：相同非 ASCII WS token 返回 `type=error, code=session_not_found`，不再 TypeError；原跨会话、Origin、Host、query token、body bound、delete revocation 对照均继续正确拒绝。
- 关键生产哈希：contracts `b87f3358490f9ad46d560fdceac67c8dd88a1c9cd449fa33441ef4dc1039ca7d`；sessions `608dcb774cb818cb55af4517daa97580b49099e580f154a88b1278603bfde2e4`；Actor 与 decision_runtime 等全部哈希见该目录 manifest。
- 证据：`context-budget-fixed.json`、`projection-adjacent.json`、`boundary-fixed.json`。原始 11:04 失败脚本及结果保持不变。

本次只关闭上述确定案例在指定候选上的缺陷，不宣称 3–5 分钟产品/真实音频验证通过；IA-02/04 的 cue/error 修复未在此时独立验收。

## IA-01 最终修复哈希独立确认（2026-10-03 11:29 UTC）

隐私修复负责人随后修正了继承正则在长重复输入下的二次耗时，提供最终冻结副本 `var/mission/obs-02-candidate-1127`。本次已对**最终 privacy.py SHA-256 `e02331f91faf7b04e6b75a986121e1fe80794b3af7bbb9617eec7b4df5678d7b`** 重新执行：

- 不变的 24-case 独立矩阵：0 credential-retention failures；安全内容 2 项和默认 OFF 保持。
- 相邻活动秘密、显式 consent、未经审核音频、历史原始导出重校验：全部通过。
- 已移交的结构化隐私测试：本次独立实跑 **63 passed in 0.37s**，含两个定时子进程 regex guard。
- Manifest 的 4 个生产文件及 1 个测试文件均存在且哈希匹配；不存在前一副本的测试文件遗漏。

证据为 `var/mission/independent-audit/privacy-candidate-1127/` 中 summary、adjacent-summary、tests.log 与 junit.xml。该最终哈希替代 11:23 候选作为 IA-01 窄范围独立闭合依据。原始 11:04 问题及所有负控证据保留。IA-02/04、集成 full/release 和设备/live/录屏验收仍由后续专门收口负责。
