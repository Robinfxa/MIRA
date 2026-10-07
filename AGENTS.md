# MIRA 实施纪律

先读 README → docs/mission/CURRENT-ACCEPTANCE.md → docs/development/TESTING.md → 本次任务相关的固定源码与规格。原50小时计划、FND交接和ENV-01记录保留历史含义，不覆盖最新需求、当前功能或实际接入证据；仅在任务需要时阅读对应v0.6模块。
不要重建通用框架。当前是可运行开发版，真实浏览器、用户设备和录屏仍待验收，不能声称完整产品已完成。先完成最新PDF必需项及实际验收，再考虑长期记忆等可选架构。

## 必守

- domain不依赖HTTP、SDK、env；application只依赖domain与ports；concrete adapter只在bootstrap装配。
- 环境只从config/loader.py进入；不在import阶段建立资源；不增加全局Settings或ServiceLocator。
- schema owner：entrypoints/http/schemas.py；导出后运行contract check，禁止手改generated TS／OpenAPI。
- 协议、domain/transitions.py、bootstrap三个共享写面由唯一集成负责人收口。
- Stop本地先行；任何旧结果不得复活。用户可靠输入与真实已呈现历史不随取消删除。
- 当前会话优先产品：正常启动使用Luna原生函数工具，普通文字/语音不等待可选操作成功；默认不构造JEV，也不由JEV裁决动作或分块。程序保留当前状态、素材、数据/用量许可、严格schema、Stop、幂等与真实呈现回执；字幕使用确定性边界。JEV只属于显式legacy_jev兼容路径，Fixture只服务Mock。
- 不读私人认证文件、开发工作区，不自动切付费API。配置字段存在不等于调用授权。
- 不将内存诊断日志说成持久回放；不将DOM占位回执说成实测音频或用户理解。
- 所有新测试结果归foundation或对应WP，原164条仍按实际逐项执行状态维护。
- 每个行为定向RED/GREEN；合并前 `python tools/check.py --affected --base <共同基点> --jobs 3`。不要每次全量。
- 新测试登记 tests/quality.toml 的唯一owner；spec中写块、消费者、资源与基点。共享面扩大、未知不跳过。
- full/release仅集成/发布收口；多Agent独立worktree，报告不可混源码快照。当前测试政策 docs/development/TESTING.md。

## 不做

本窗口不新增账号池、通用编排平台、长期人格学习、现场视频或第二个播放主控。
未接provider必须明确失败，禁止为了演示成功偷偷返回mock。

## 本轮以后按这个SDD/TDD范例开发

先读CONTRIBUTING.md与docs/development/TDD-SDD.md。新功能先spec/Given-When-Then与可观察测试，再实际RED/GREEN；用唯一run ID保存日志，不覆盖证据。没有历史RED的已有代码只记baseline。
traceability.json中的node ID必须可收集；映射不等于已执行。不允许给不存在的测试填passed。固定fixtures不变成通用脚本或live审核绕过。新增profile必须走loader/显式factory，不能在Actor里按provider分支。
本地提交仅用于交接与复验，不自动推送远端。后续重点是WP03/04真实可取消表现，停止继续扩建基础平台。


## 开发服务环境 ENV-01

先读 docs/development/API_ENV.md。`api_env.py check`无网络且从不宣称live_ready；metadata只在明确授权下GET所选目录。
禁止cat/打印.env、认证缓存、完整headers或ADC文件；不将密钥写入prompt/开发记录。根.env是私密运行配置，不是Codex原生配置。
不得source整份.env进开发Agent环境；标准API备用key不应意外改变开发Codex的登录计费方式。
服务字段齐全不等于factory可用；现有live守卫保留。下一任务实现真实adapter，不通过删除守卫把fixture审核套给live内容。
固定回放测试保持离线。Google项目和region是配置，ADC状态是unknown直到对应受控探针验证。
保持原T0和剩余时间；不再重写OAuth、探针平台或调度器。

## 2026-10-04 11:21 后续独立记忆切片

用户追问架构书记忆是否完成后，项目负责人已恢复有界的M06后续实施，与用户进行0952实机测试并行。0952全部源码/公开投影/七文件归档保持不可变；当前源码是下一阶段，不能把WIP混入已验收包。先做明确同意的本机作用域化证据存储、可逆更正/忘记及可操作CLI，默认不自动记录，不新增provider调用或凭据权限。召回不授予动作/披露权限；不能把存储核心、CLI或ContextPacket存在写成已经接入自然会话或完整人格学习。验证输出只追加保留，不自行清理任何日志/receipt。

## 2026-10-04 12:58 后续 Actor 记忆接入

用户已延长10小时至22:58:44 UTC，并要求继续原架构未完模块。本目录是从已发布1212公开投影复制出的下一阶段，1212源码、公开投影和七文件交付不得改动。本切片接入显式启用的有界只读记忆到Actor及生成/审核证据，读取scope由本机操作方固定，HTTP和模型不能选择。传给Codex和TypeSafe/JEV的记忆内容须有单独明确授权，不能继承本地记录或旧对话原文录制同意；本轮只合成离线验证，不读真实用户记忆、不调用provider、不自动记录。必须验证Stop/新输入/Close、版本漂移、跨scope、日志隔离和默认关闭。静态代码/合成验收不等于真实记忆对话质量已验收。美术分析与这条代码切片分开，不抢同写面。
