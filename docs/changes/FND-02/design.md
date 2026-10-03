# FND-02 实施设计

## 责任与依赖

`config/loader.py` → immutable ProviderSettings → `bootstrap/create_providers` → resource loader + ReplayGenerationBackend → 既有 GenerationBackend。

资源loader在adapter层；schema只接受固定fixture引用。生成adapter只负责时间与顺序，不读Settings或env，不写SessionState。等待依赖采用简单异步Callable注入，不新增通用Clock平台。默认await asyncio.sleep，测试使用event barrier。

SessionActor、审核、编译器与回执归约不因新增provider重写。每次generate的游标为局部变量，工厂构造的不可变脚本可被多个session安全读取。

## 文件变化

- config/settings.py、loader.py、profiles/replay.toml、.env.example：公开场景名与装配选择。
- adapters/generation/replay/{script.py,backend.py,fixtures/*.json}：加载/验证/序列输出。
- bootstrap/providers.py：唯一新增构造分支，继续拒绝live与外传／付费。
- tests/contracts、integration：共享port行为、取消、失败后事实、HTTP路径。
- specs/features/FND-02-fixture-replay：规格与测试映射。
- docs/changes/FND-02、development、verification：真实过程记录。

## 取舍

不让客户端提交JSON脚本，不支持任意文件路径，不把失败回放做成真实模型。按包资源交付，wheel需带fixtures。健康接口继续使用mock家族标识；增加字段并非本例必要，故保留wire及生成TS不变。

## 风险与验证

重复JSON键可能被通用parser静默覆盖，必须有负例。固定fixture不得成为任意live审批。停止测试必须区分任务取消、分支失效与呈现历史；暂停或停止provider不能自动标记被展示。精确延迟毫秒不是性能承诺。
