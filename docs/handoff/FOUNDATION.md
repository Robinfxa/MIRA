> FND-01历史交接；当前版本请先读[FND-02](FND-02.md)。

# FND-01 开发交接

## 起点

这是用户授权的基础架构搭建，不是完整MVP。50小时窗口不重新计时。
代码在本交付工程中，未写用户Mac、未创建远端仓库、未修改ValueHermes。

## 已做

typed配置和profile；显式env入口；create_app/build_container/create_providers；
纯域转换与Protocol；Mock生成与只批准固定fixture的review；短锁串行状态；
HTTP创建/输入/停止/回执/诊断/删除；会话能力token；完整许可子集；
浏览器本地停止、代际检查、去重、占位执行器；OpenAPI与TS导出；测试与计划。

## 未做（不能用工作台外观替代）

真实Codex／JEV／API adapter，ASR/TTS/麦克风，字符/音频对齐，角色模型和原创美术，
完整G03语义上下文算法、现场生图及D-M、真实媒体依赖、持久状态、完整回放、移动设备音频验证。
public port/多worker/公网生产部署也未开放。

## 已知实现界限

HTTP轮询供Mock联调，不是低延迟音频transport。
当前Receipt表示瞬时Mock DOM应用证据；没有started/partial/completed音频范围。
SessionActor用内存与有限budget，stop fence保留在session内；页面刷新新建会话，不重放旧内容。
Journal只存元数据，无法单靠它重建完整内容，不能声称实现完整event sourcing。
Mock通过fixture分支触发，不是自然语言语义判断，不能映射成JEV通过。

## 下一位开发者先做什么

从WP03/04固定计划的真实可取消表现接入开始，沿用现有ports/factory，不另建session。
并行按WP01固定一个获准carrier，先验证真实文本/终态/取消，再接真实review；
不要把fixture review用到真实provider。单次输入的id/活动序号和停止cutoff需端到端保留。

共享文件 owner：schemas.py、domain/transitions.py、bootstrap/*。
每个补丁先运行基础测试，再增加该接缝真实/负面证据。原v0.6 catalogue不批量标绿。
