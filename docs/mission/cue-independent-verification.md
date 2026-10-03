# Cue / 字幕 / 错误指引独立复验

时间：2026-10-03 11:37 UTC。范围：IA-02、IA-04 的指定修复候选；不是整体验收或发布批准。

## 结论

- **IA-02 已复现的未来字幕提前显示/记账问题，在本次冻结候选上通过离线独立复验。** 真实编译器生成的两段 speech/subtitle/pose/scene，经 HTTP DTO 映射后进入真实 controller、gate、playback 与 scene executor；只有对应音频 source.start 成功后才显示该 cue 的视觉内容并产生回执。未来第二段不因已获 grant、接收 PCM 或第一段在播放而提前显示。
- **IA-04 裸错误码覆盖恢复指引的问题通过复验。** 使用实际 main.js、MiraApiClient、SessionController 的入口链，最终 DOM 文本保留安全恢复指引，合法 HTTP 诊断号保留，未知服务文本与不合法诊断号不反射。
- 本次另发现 `constructor` / `toString` / `__proto__` 会命中错误字典继承属性，最终显示原生函数或对象文本。已立即报告，修复负责人改为 own-property 查询；**原样独立断言在初始候选失败、最终候选通过**。
- **仍有明确边界：** 异步 `last_error` 尚无专属、用户可见的错误关联号；有 HTTP 失败关联号，不代表所有异步失败均可关联。真实浏览器像素、扬声器、手机、真实 TTS/STT、逐字同步、3–5 分钟连续录屏全部未执行。

## 来源、冻结与权限边界

已读 AGENTS、README、50h 计划、ENV-01、贡献/TDD/API 环境纪律与 v0.6 M04/M05 相关合同。由修复负责人明确确认生产与测试文件稳定后冻结。

证据根目录：`var/mission/independent-audit/cue-candidate/`。

- 初始快照 `source/`：109 个明确纳入的 Python/TypeScript、合同、配置与相关测试文件。`manifest.json` 保存捕获前、后与副本逐项 SHA-256，三者一致。
- 最终快照 `final-source/`：同 109 个文件。`final-manifest.json` 保存同样的三方哈希。相较初始快照，仅 `features/diagnostics/status.ts` 与 `tests/web/controller-cues.test.mjs` 变化，分别为继承属性修复与新增负控。
- 初始编译结果保留为 `initial-web-dist/`；最终编译结果为 `web-dist/`。无生产编辑；只写本报告与获准证据目录。
- `post-test-integrity.json` 在 11:37:02 UTC 再核对：初始/最终冻结副本均未变；canonical 的全部 109 项与最终冻结快照一致。
- Python 使用 canonical `.venv313/bin/python`，`PYTHONDONTWRITEBYTECODE=1`，明确 `PYTHONPATH` 指向冻结快照；pytest 禁用缓存。TypeScript 使用既有 `node_modules/.bin/tsc`，Node v24.19.0。
- 无浏览器 localhost/native 重试，无真实设备、服务商、凭据、dotenv、Git 或发布操作。没有修改 v1 gold/manifests，也没有运行或弱化 director 负责的 eval 表示迁移。

关键最终生产 SHA-256：

| 文件 | SHA-256 |
|---|---|
| application/compiler.py | `205a4e4b06a02b5ffa78ef1c063c008da92f33effe2eb0fc6d81e09c2e777271` |
| shared/cue-contract.ts | `51d3056bcc27f4520928979dcc68bd2b73632a0e53b3703897d94c789fbdce19` |
| shared/protocol.ts | `8b6887339b90f9664dc52e1da0a8ddb173a3360e3ab7d60463a8963adbb618bb` |
| presentation/permit-gate.ts | `e890e5fb9de85b40e53ecb2fd1af92fd674d5686c761d954ae0979eafac7ec91` |
| session/controller.ts | `53e787aa721fa2cfad920bb0302635b88d873d956d9b09249e435329092c478a` |
| diagnostics/status.ts | `1fe36eac34686efad960cdb2eac588b2d90141899a9d6906624a994aa8096cb3` |

## 原缺陷复验方式

原始 `1104/frontend-adversarial.mjs` 是“断言缺陷存在”的历史脚本，不能将它绿色当修复验收。该文件原样复制为 `original-frontend-adversarial.mjs`，没有改动原始证据。

在新候选原样执行，该无 cue 元数据的双 speech/双 subtitle 集合被 `Ambiguous legacy speech cue` 拒绝，退出 1；见 `original-legacy-result.log`。这证明旧的模糊混合集合不再被作为合法计划消费，不是“原脚本通过”。

另以同一可观察场景验证新合同：两个完整范围，speech 1 尚未收到 PCM，subtitle 2 必须不显示也不回执；随后分别启动 source 1/2，检查各自字幕与控制精确到对应范围。`generate-compiled-fixture.py` 调用真实 `compile_range → immutable Effect → session_view → SessionView.model_dump(mode=json)`，产生 `compiled-fixture.json`，不是手写 cue 身份或按文案相等猜配对。字幕与 speech 故意采用不同文本，speech 在每段 effect 数组中的位置也不同。

## 实际场景结果

| 场景 | 结果与证据含义 |
|---|---|
| 两段 speech + 不同文案字幕 + pose + scene | PASS；source 1 前零视觉/回执；source 1 仅第一段三项；source 2 前第二段零回执；source 2 后仅新增第二段三项 |
| 独立无语音 photo/scene/text 范围 | PASS；立即呈现；Stop 后已有照片/环境保留；没有 speech 的伪视觉回执 |
| capabilities 延迟、unlock 延迟 | PASS；等待时零 speech stream、零 cue 视觉；条件就绪仅打开 speech，仍等实际 source |
| PCM 已接收但 source resume 尚未完成 | PASS；零视觉/回执；含 provider 已 finish 的情况；resume 成功后才开 cue |
| 无 PCM 即 provider 完成 | PASS；没有视觉或下一段；生成 failed audio fact（0 rendered），有恢复错误提示 |
| provider 首 PCM 前失败 | PASS；无视觉、无第二段；有恢复指引 |
| source.start 抛错 | PASS；无 caption/pose/scene 回执；failed fact 与播放失败提示 |
| 96,000-frame backpressure + 重复快照 | PASS；第 17 个 6,000-frame 写入等待；字幕不跳到第二段、不重复记账；Stop 释放等待并保留第一段环境 |
| 第一段已完成、第二段 PCM 前 Stop | PASS；第二段迟到 PCM 拒绝，字幕与 scene 不前进；已呈现第一段 scene 保留 |
| 第二段 PCM 等待 resume 时撤销 | PASS；旧 stream abort，未创建第二个 source；不丢已成立场景 |
| 第二段等待时新输入替换 | PASS；旧 resume 不能重活；新独立 scene/photo 保留，不被旧第二段覆盖 |
| 第一段播放中追加第二段 grant | PASS；追加许可不等于第二段开始显示 |
| 跨 cue、缺 speech、改 cue 引用、不同 epoch/activity | PASS；parser 和 gate 均拒绝且关闭执行资格 |
| 过长/空/非字符串字段、重复 effect ID、双 speech/双 subtitle | PASS；无可消费授权 |
| 混合 legacy + speech | PASS；模糊集合拒绝；孤立 legacy speech 与纯无语音 legacy 集合仍可用 |
| 调用者原对象、数组突变；后续 revision 改 cue 内容 | PASS；内部授权副本不受外部突变；effect 身份换内容被拒绝 |
| 已呈现字幕历史不带 speech peer | PASS；历史并非当前完整授权，不错误要求重放 speech |
| 模型提供 id/digest/cue_id/cue_speech_id | PASS；真实 parse_effects 拒绝；schema 不向模型开放这些字段 |
| 编译器元数据所有权 | PASS；每范围唯一 cue，精确 speech ID，digest 绑定 cue，domain Effect 不可变；双 speech/双 subtitle 范围拒绝 |

对应独立脚本：`independent-causality.test.mjs`（34 cases）与 `check-model-metadata.py`（8 checks）。前者初始 31/34，唯一失败是以下三项错误字典问题；最终原样 34/34。

## 错误呈现入口：实际 main，而非仅 helper

`actual-main-errors.test.mjs` 直接加载最终构建的 main.js，使用真实 API client、controller、safe error helper 与 scene executor；仅 fetch、DOM 与 AudioContext 为明确合成原语。无真实浏览器。每次测试保存实际 `[data-error].textContent` 赋值序列，见 `actual-main-observations-initial.json` / `actual-main-observations-final.json`。

- `generation_timeout` 最终为“生成超时，请重试。”，未再覆盖成裸码。
- 任意未知 `last_error` 使用通用安全恢复文案，不反射合成 private marker。
- 新发现的 `constructor` / `toString` / `__proto__` 在初始候选分别输出原生函数文本或 `[object Object]`；最终均为通用安全恢复文案。controller 独立矩阵与 actual-main 两套相同断言均 RED→GREEN。
- HTTP 503 的合法 UUID `x-request-id` 原样出现在安全错误文案中；响应 body 中的合成 private marker 不出现。
- 不合法 request ID 含合成不可信字符串，不会显示；恢复方式仍保留。
- 异步 `last_error` 未附专属错误关联号，不能声称全部诊断关联已实现。该缺口不影响本次确认的“恢复文案不再被裸码覆盖”。

## 实际执行收据

| 检查 | 初始候选 | 最终候选 |
|---|---:|---:|
| 独立因果/协议/controller 场景 | 31 pass / 3 fail | 34 pass / 0 fail |
| 独立 actual-main 入口错误场景 | 4 pass / 3 fail | 7 pass / 0 fail |
| 独立 model/compiler metadata 检查 | 未执行 | 8 pass |
| 修复方 Node cue 测试独立重跑 | 24 pass | 27 pass |
| 修复方 Python cue 测试独立重跑 | 9 pass | 9 pass |
| 冻结 TypeScript 编译 | PASS | PASS |

这些是不同范围的收据，不能相加当成独立产品覆盖数。未独立重跑修复方报告的 142 全 web 或 266 backend 回归；未做 coherent full/release。

运行命令（cwd 为 canonical；`${E}` 为该证据目录绝对路径）：

```sh
node_modules/.bin/tsc -p "$E/final-source/apps/web/tsconfig.json" --outDir "$E/web-dist"
node --test "$E/independent-causality.test.mjs"
MIRA_MAIN_OBSERVATIONS='./actual-main-observations-final.json' node --test "$E/actual-main-errors.test.mjs"
MIRA_TEST_WEB_DIST="$E/web-dist" node --test "$E/final-source/tests/web/controller-cues.test.mjs"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$E/final-source/apps/api/src" .venv313/bin/python "$E/check-model-metadata.py"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$E/final-source/apps/api/src" .venv313/bin/python -m pytest -q -p no:cacheprovider "$E/final-source/tests/contracts/test_cue_compilation.py"
```

## 未证明与下一门槛

1. 本次是软件 source.start / natural onended 的受控证据，不是声卡已发声、用户已听见或逐字时间对齐。cue 是完整范围的开始同步，不提供词级时间戳。
2. main.js 的 DOM 替身能检查最终赋值与控制路径，不能证明真实画面已 paint、动画可辨认、无移动端遮挡或布局合格。
3. 照片/环境保留来自真实 reducer/executor 状态与 DOM 赋值；图片 load/error、真实资源像素与可访问性仍须浏览器验收。
4. 真正权限拒绝、autoplay 策略、音频设备中断、扬声器停止尾部、网络断连/恢复、真实 provider 的 PCM 格式与能力合同未验。
5. 3–5 分钟连续交互、真实手机/桌面分别录屏、干净包启动及其他审计项不由本次 cue 修复代偿。

最终判定：**指定 hash 的 cue 因果与安全错误文案离线合同通过；真实产品/设备验收仍开放。**
