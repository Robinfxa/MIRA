# MIRA · 原创角色互动开发版

**可运行的零密钥演示；真实服务、设备与完整互动验收仍有独立准入条件。**
MIRA 是一位26岁的原创虚构摄影师，场景是雨夜咖啡馆。当前实现包含原创 SVG 角色/场景、四态表现、表情与受控动作、文字输入、可取消音频传输/播放、独立语义审核，以及有界脱敏诊断和显式开发录制。离线排练中的按住手势只提交固定合成文本，不采集麦克风；真实语音入口仍待授权后的设备验收。

## 当前实现与验收边界

以下状态核对至 **2026-10-03 17:38 UTC**；各次测试和真实调用绑定各自源码快照。

- 默认 `mock` / `replay` 可离线启动，不读取私密 `.env`，不调用模型或真实语音服务。另有显式 `rehearsal`：固定口令、多轮呈现历史、预录英文合成音频及双语字幕，真实麦克风始终关闭。
- 受批准的既有原生 Codex 开发环境已通过实际 MIRA 适配器产出一份 `gpt-6-luna` 结构化候选；Google Speech-to-Text V2 已识别一段6.135秒的合成英文。JEV 有连接/解析证据。它们尚未组成通过审核的实时会话：JEV 中文校准未完成，精确 `gemini-3.8-flash-tts` 尚无可用音频，默认 live 工厂仍关闭。
- 字幕/动作通过应用生成的 cue 身份与对应语音关联。Stop、新输入和权限撤销先在本地阻断；软件渲染样本不证明用户听见，也不是逐字对齐。
- 普通日志无原文。开发原文录制需要单独开关与确认，保持可见标记；凭据结构与不确定内容拒绝记录。自动原始音频录制尚未开放，必须先通过针对该缓冲区的隐私审核。
- 独立审查已发现并修复字幕提前呈现、嵌套凭据过滤、累计音频上下文、错误文案和异常 token 等问题。每个后续阶段须重新冻结源码验证，旧阶段的绿色测试不能替代新版本验收。
- 真实浏览器/手机/扬声器/麦克风、完整3–5分钟交互录屏、真实模型表现与中文审核校准尚未完成。没有云部署或正式产品就绪声明。

[项目北极星](docs/NORTH_STAR.md) · [最终需求与验收](docs/mission/requirements-and-acceptance.md) · [当前版本与缺口](docs/mission/acceptance-status-1715.md) · [固定归档快速指引](docs/development/QUICKSTART.md) · [测试政策](docs/development/TESTING.md)

## 服务配置准备

在既有loader中加入具名服务配置和私密模板；提供默认无网络检查、显式有界模型目录检查。
**适配器代码与接入参数不代表账户开通或 live 准入。** 默认应用仍是 mock/replay；真实服务只能在显式装配、授权、预算和对应验收通过后使用。
[API环境与一次性准备](docs/development/API_ENV.md) · [Provider Matrix](docs/development/PROVIDER_MATRIX.md) · [当前交接](docs/handoff/ENV-01.md) · [规格](specs/features/ENV-01-development-services/spec.md)

```bash
python tools/api_env.py init     # 创建空.env；已有文件拒绝覆盖
python tools/api_env.py check    # 默认不联网；字段缺失退出2，不表示MVP失败
python tools/check.py --lane env --jobs 2
```

密钥仅在本机私密文件／进程提供，不发送聊天，不写进spec、日志、前端或截图。

## 历史基础阶段：增量分块测试

以下数字保留原阶段的历史含义，不是当前完整实现的测试总数。

默认开发检查改为affected；定向RED/GREEN不必先跑全量。9个默认离线块可并行，package/smoke留发布。
[测试工作流](docs/development/TESTING.md) · [FND03规格](specs/features/FND-03-scoped-quality/spec.md) · [验证](docs/changes/FND-03/verification.md)

最终本地181 Python＋20 Node、18条规格映射通过；4组真实RED/GREEN。定向示例与分块收据均在验证目录，未选检查明确not_run。

## 继承的开发示范

[SDD/TDD示范手册](docs/development/TDD-SDD.md) · [功能规格](specs/features/FND-02-fixture-replay/spec.md) ·
[开发日志](docs/development/LOG.md) · [本轮验证](docs/changes/FND-02/verification.md) · [最新交接](docs/handoff/FND-03.md)

FND-02是一个新adapter的完整例子，不是空目录：先写规格，真实RED/GREEN，再重构和集成。最终132 Python＋20前端通过；此前73 Python为基线，未伪造其TDD顺序。无新增依赖版本升级。

## 快速启动

需要 Python 3.11–3.13、Node.js 22.12+ 和锁文件声明的依赖。在工程根目录运行：

```bash
sh scripts/dev
```

此命令**不会安装依赖**。先验证 `.venv` 和当前解释器的实际应用导入能力；不完整的 `.venv` 不会遮住可用的当前解释器。
缺依赖会退出 2 并提示显式安装。首次准备需要包注册表：`python3 tools/bootstrap.py`，只写项目 `.venv` 和 `node_modules`。
如果已在其他隔离环境安装依赖，用显式解释器路径，不自动扫描或猜测虚拟环境名称：

```bash
sh scripts/dev --python /absolute/path/to/ready/python
# Windows：python tools/dev.py --python C:\\path\\to\\python.exe（本轮未实测）
```

启动前检查合同、编译 TypeScript，再以单进程提供 API 和静态工作台。浏览器手动打开 `http://127.0.0.1:8000`；可用 `--port 8123` 改端口。
**默认演示固定为 mock，忽略根 `.env` 和进程中的 MIRA 服务配置／常用凭据变量**；不启用 live provider、付费调用或原文记录。`--no-bootstrap` 保留兼容，但现在所有启动都不自动安装。
归档可没有脚本执行位，所以推荐 `sh scripts/dev`，不要求 `chmod`。

### 有声离线排练（推荐演示入口）

```bash
sh scripts/dev --profile rehearsal
# 已验证可用的其他解释器可追加 --python /absolute/path/to/ready/python
```

页面常显 `OFFLINE · 固定互动排练`。这条路线只有 7 个固定口令和一个失败注入，不支持自由对话；目录外文字只得到明确口令提示，不被假装识别或转述。真实麦克风按钮保持关闭，独立「按住演练输入 · 不录音」只展示 listening 状态，松开后提交固定的「照片里有什么」，不会调用录音或 STT。

原始音频/文字录制默认关闭。8 段预先生成的英文合成声音共约 52.56 秒，来自本地 Flite `slt`，不是 Google 语音、真人声音或中文发音验收；中文翻译与完整英文句子按现有语音 cue 显示，非逐字对齐。音频只经既有 Actor、有效许可、认证音频流和唯一取消安全播放队列进入页面。

12:56 历史归档存在图片未就绪就记录呈现回执的问题。当前源码已加入可取消的图片就绪等待、最新许可复核与失败重试修复，并通过独立软件层复验；旧归档保持原样并附已知问题说明。前端还会等待已有呈现回执同步后再提交下一轮，Stop 不等待网络。直接 HTTP 调用方的相同屏障仍在修复。当前未验证浏览器实际绘制或用户看见。见[当前状态](docs/mission/acceptance-status-1715.md)。

按自己的节奏走一遍约 3–5 分钟的指引（包含观察、重复与停止，不是已录制的验收时长）：

1. 「你好」→「不要拍我」：观察好奇、微笑与相机放低。
2. 「看照片」：等语音与原创海岸/灯塔插画出现。
3. 「讲讲旅途」：讲话中点「停止回应」。声音、字幕不继续，已经看到的插画保留。
4. 按住「演练输入」，确认画面显示 listening 且没有麦克风请求；松开只发送「照片里有什么」。回应用实际呈现过的插画；新会话未看图就问，会先提示看图。
5. 「听雨」→「暖灯」：看环境和表情变化。用 `/fail` 测失败，再点「你好」恢复；输入目录外文字检查口令提示。

完整口令：`你好`、`不要拍我`、`看照片`、`照片里有什么`、`讲讲旅途`、`听雨`、`暖灯`、`/fail`。前后空格和改写也不会被当作识别成功。Stop、失焦、取消、关闭或更新的文字输入都会使待发送的合成输入失效。

这条路径用于验证受控体验，不证明真实模型、真实语音识别、物理扬声器听感、手机或真人 3–5 分钟互动录屏已经完成。[规格与实测边界](specs/features/DEMO-01-offline-rehearsal/spec.md) · [素材来源](docs/changes/DEMO-02-offline-speech-assets/README.md)

回放固定照片场景（不调用模型）：

```bash
sh scripts/dev --profile replay
# 其他现成 Python 环境同样追加 --python /absolute/path/to/ready/python
```

可以加 `--replay-scenario delayed-photo` 测停止，或 `--replay-scenario failed-tail` 测失败。
这只是固定生成夹具回放，不是自然语言理解或完整会话恢复。语音、账户、真实设备能力不能从本启动检查推出。

配置感知入口仍是 `PYTHONPATH=apps/api/src /path/to/ready/python -m mira`，它会按原 loader 读取根 `.env` 和进程配置；仅在已明确配置、授权和审核的开发流程中手动使用，不属于上述离线演示。live 工厂守卫不因启动工具改变而放宽。

离线 wheel 验证：`/path/to/ready/python tools/verify_package.py`。构建 Python 需要现成的 pip 与 `pyproject.toml` 固定版本的 setuptools、wheel（已列入开发锁文件）；必要时加 `--build-python /path/to/build/python`，运行烟测仍使用调用脚本的解释器。工具在临时副本编译前端、无网络构建／安装 wheel，并从安装目录验证配置、fixture、HTTP 与全部静态资源；不靠 checkout 的 PYTHONPATH 补资源。直接手动构建 wheel 前须先 `npm run build`，漏编译会明确失败。
实测和限制见 [STARTUP-01 验证](docs/verification/startup-01/verification.md)。

## 质量命令

```bash
python tools/check.py --list
python tools/check.py --files apps/api/src/mira/adapters/generation/replay/backend.py --plan
python tools/check.py --lane providers actor --jobs 2  # 精确相关块
python tools/check.py --affected --base <共同Git基点> --jobs 3  # 合并前
python tools/check.py --full --jobs 3      # 集成收口，不是每次修改
python tools/check.py --release --jobs 3   # 再加离线wheel与loopback
python tools/verify_tdd_evidence.py         # 原FND02历史完整性；公开归档不含其所需原日志
python tools/export_contracts.py --check
```

无Git的ZIP用`--files`或`--lane`；默认命令只检查Git工作区，已提交变更请带base。报告在`var/quality/<run>/summary.json`，未选块为not_run，没有测试结果缓存。

环境里同时存在多个 Python 时，用已验证且依赖完整的解释器绝对路径执行质量命令；不要仅凭 `.venv` 目录存在就认为可用。
14:48 已验证源码已完整展开至提交 `45b716d7ae80ce9d55934b81372dd1a7b411caf3`，543个源码文件的 Git blob 与模式逐项匹配，46个历史备份文件保留。其[首个真实远端 CI](https://github.com/Robinfxa/MIRA/actions/runs/37140155063)通过10个离线质量块；该次未跑 package/smoke。后续手动发布检查另有运行记录，不能在结果出现前称通过。更新中的源码必须重新冻结和验证。

## 工作台能验证什么

输入“不要拍我”“看照片”“听雨”进入固定Mock场景；`/fail`注入生成失败。
可查看activity/output/permit版本、有效集合和回执数。停止先在浏览器生效，旧结果不能恢复。
支持新请求、重复请求、会话能力token、范围累加、停止截止范围和迟到回执。

默认模式不会产生真实 ASR/TTS/LLM 请求。原创角色和旅行插画已实现，属于本地矢量素材，不能说成实时生图。真实语音代码、软件级取消测试和控制台能力标记，也不能代替账户、声卡、麦克风与完整需求验收。

## 目录入口

```text
apps/api/src/mira/
  domain/             纯模型、错误、状态转换
  application/        用例与会话生命周期；ports声明外部能力
  adapters/           Mock/回放、默认关闭的真实服务、私有诊断适配器
  config/             类型与唯一env读取入口
  bootstrap/          工厂、组合根、生命周期装配
  entrypoints/http/   DTO、映射、依赖、路由、app factory
apps/web/src/
  app/                浏览器组合根
  features/session/   transport与交互协调
  features/presentation/  本地许可门、cue身份与原创场景执行器
  features/audio/     唯一播放队列、可取消麦克风采集
  features/diagnostics/  实际录制状态与安全错误文案
  shared/             公开配置、协议验证、generated类型
config/               非秘密默认值与profile
packages/contracts/   自动导出的OpenAPI
requirements/         精确安装版本闭包
scripts/ tools/       启动、安装、合同导出、验证
tests/                unit、integration、architecture、web、browser
docs/                 50h计划、实施ADR、来源快照、交接与验证
```

完整文件树见 `docs/implementation/FILE_TREE.md`。

## 配置与抽象的约束

- `Settings`不可变；默认值→profile→显式dotenv→进程env→测试overrides；未知配置启动失败。
- 业务层不读env、不知道provider名称；仅 `bootstrap/providers.py` 选实现。
- `create_app(settings)`可注入依赖；没有全局容器、import-time连接或反射插件扫描。
- domain标准库限定，application不反向依赖adapters；有自动边界测试。
- 公共DTO单点定义，OpenAPI／TS只导出；新增schema先改owner，再跑drift check。
- live provider 不会因环境字段齐全而自行启用；显式装配仍须通过身份、质量、数据和预算准入，不会偷偷 Mock 或改走付费路线。

## 必读文档

[50小时计划](docs/plans/50-hour-delivery.md) · [实施ADR](docs/implementation/ADR-F001-foundation.md) ·
[配置约定](config/README.md) · [开发范例](docs/implementation/config-and-extension-guide.md) ·
[最新交接](docs/handoff/FND-03.md) · [原架构/复用 v0.6](docs/reference/architecture-v0.6/MIRA_架构全书_v0.6.md)

## 运行与安全界限

仅loopback＋单worker，内存会话，有限容量；停止与实例隔离是基础子集，不是生产认证系统。
浏览器token只在内存，诊断不输出用户原文/凭据；只服务明确public/dist文件，不服务仓库根。
刷新不恢复旧会话，关闭按钮释放本地session；完整持久化/隐私清除在WP05后续实现。

依赖来源与素材见THIRD_PARTY.md；AI使用与未进行的人工验证见AI_USAGE.md。
已在同一 Linux 环境的新隔离目录验证46个固定 Python 依赖、TypeScript5.8.3和启动；远端固定提交的10块CI也已通过。它们不代表全新操作系统、Windows/macOS、手机或物理音频验收。详见[安装证据与限制](docs/verification/fresh-install/verification.md)。

## 为什么选择按住输入

本 MVP 选择明确的按住/松开与停止控制，而不是自动 VAD：移动端更容易看清何时开始采集，能够利用用户手势解锁音频，并避免把背景声误作打断。真实路径仍需验证麦克风许可、识别结果、释放和新一轮衔接。离线 rehearsal 用单独标记的合成输入演练这些状态，不把它称为真实语音识别。

## 当前投入与后续两周计划

本轮从 2026-10-03 08:53:50 UTC 开始；截至本条记录 17:38 UTC，已用约8小时44分钟自然时间。多个 AI 执行项并行，累计计算时间和等价人工工时未统计，也没有把自动检查记作人工产品验收。24小时交付截止仍为2026-10-04 08:53:50 UTC。

以下是后续计划，不是已经完成或自动获准付费/部署的工作：

- 第1周：在已完成的软件图片就绪修复、原生结构化生成和英文 STT 连通基础上，完成精确 TTS 的实际音频与有界实时会话；用独立中文开发/保留样本验证 JEV 的误放行、拒绝和可用回应覆盖，不为通过而降低阈值。调用额度与数据范围继续按实际授权执行。
- 第 2 周：在主要桌面浏览器和至少一台真实手机上验证权限拒绝、后台切换、声音中断与下一轮输入；记录实际首包/取消时间和连续会话表现，完成同版本 3–5 分钟录屏、恢复演练和最终来源/秘密检查。扩展浏览器、中文声音体验和素材表现；部署或外部分享仍按实际授权执行。

### 当前缺口与下一步

- Codex：16:43已通过实际适配器完成一份 `gpt-6-luna` 结构化候选；独立 fixture 拒绝它，未签发呈现许可。随后补上必需的显式字幕合同，147项相关离线检查通过，新字幕合同尚无新的原生调用证据。既有开发环境的额度归属与可移植性未知；独立私有环境的401记录保留，未复制凭据或静默切换付费API。
- Google：ADC、项目、五项权限与所需两个 API 启用状态已验证；英文合成 STT 一次成功，中文与麦克风仍未验收。TTS 首个已观察文本 part 曾触发客户端提前关闭，后续未知；最新一次 HTTP200 后超时。离线解析修正已通过，仍无真实可用 TTS 音频。七次保守预税保留共USD0.978560，税费未知，后续付费调用已停止；计费状态不能由API启用推断。
- JEV：连接与严格返回解析有成功证据，首个预注册中文诊断样例超时。新一组有界合成诊断已获批准并在准备，尚无新的实际结果；生产校准和呈现准入仍关闭，不降低阈值凑通过。
- 图片与历史：图片就绪/失败重试已通过软件层独立复验。前端延迟呈现回执屏障也通过实际前端到 HTTP 检查；服务端对直接调用方的相同约束仍在修复，不能说整个架构缺口已关闭。
- 体验：离线场景、固定声音及软件取消链已验证；当前浏览器像素、物理音频/麦克风、手机和连续 3–5 分钟录屏未验收。受支持的渲染/设备路径准备好后逐项观察，不能用模拟样本计数替代。
- 交付：14:48源码已完整展开并通过真实远端10块CI；下一阶段会排除未稳定改动，重新冻结、测试和发布。已有可恢复历史归档。原始音频的后端接线已有离线证据，审听/保存 UI 仍在开发，未计入本完成切片。长期人格/记忆、完整 storylet、G06 生图与 D-M 等原架构范围仍不完整；原164条验收目录仍按未执行记录，不能用单元测试数代替。最终录屏与源码版本关系尚未建立。
