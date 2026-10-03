# MIRA 实施纪律

先读 README → docs/plans/50-hour-delivery.md → docs/handoff/ENV-01.md → 对应v0.6模块与固定源码。
不要花时间重建通用框架。当前是foundation，不是完整产品。

## 必守

- domain不依赖HTTP、SDK、env；application只依赖domain与ports；concrete adapter只在bootstrap装配。
- 环境只从config/loader.py进入；不在import阶段建立资源；不增加全局Settings或ServiceLocator。
- schema owner：entrypoints/http/schemas.py；导出后运行contract check，禁止手改generated TS／OpenAPI。
- 协议、domain/transitions.py、bootstrap三个共享写面由唯一集成负责人收口。
- Stop本地先行；任何旧结果不得复活。用户可靠输入与真实已呈现历史不随取消删除。
- Fixture审核只服务Mock，不批准任意真实内容。真实review缺失不得放行。
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
