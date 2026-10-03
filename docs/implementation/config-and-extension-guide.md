# 新模块应该怎样接入

## 依赖方向

```text
HTTP / browser UI          bootstrap (唯一装配入口)
       ↓                         ↓
application / ports ← adapters / vendor SDKs
       ↓
     domain
```

domain：不可变模型、可回放转换、领域错误；不导入FastAPI、配置、SDK、数据库。
application：用例、异步任务生命周期、端口；不选provider、不读env、不访问框架全局对象。
adapters：实现真实I/O，负责格式转换和异常归一化；不能直接改SessionState。
bootstrap：选择具体实现、构造并注入、生命周期清理；此处允许知道两边。
entrypoints：校验外部输入、鉴权、调用用例、映射结果；不放业务判断。

## 示例：下一位开发者增加Codex adapter

1. 先读v0.6 M09/M10和固定上游入口，解决IC-01；复用官方/获准兼容承载，不重写认证。
2. 实现 `GenerationBackend.generate(context)`，只输出完整候选／真实终态；不直接发到浏览器。
3. 在 `bootstrap/providers.py` 添加显式构造分支与能力／权限检查；不在Actor里增加 `if codex`。
4. 配置字段只放 `config/settings.py` 和 `loader.py`，同步 `.env.example` 与配置测试。
5. 必须接真实review路线；**不可让FixtureReviewBackend批准live文本**。
6. 增加adapter合同测试：取消后迟到、异常断流、无完整输出、未呈现历史污染、无自动付费。
7. 只有获得相应授权再做账户验证；报告标明本次调用、失败、usage和版本。

## 示例：增加角色renderer

替换DomEffectExecutor为满足实际能力清单的执行器；禁止改写SessionActor权限规则。
模型动作先编译为允许能力；执行器报告真实开始、部分、完成与中断，不借`audio_end`完成所有效果。
保留旧照片／姿态是当前状态维持，不是重播旧grant；停止收势不得推进原业务效果。

## 最小抽象原则

只有实际外部依赖或需要替换的能力才开Protocol。没有真正调用者的通用基类不增加。
当前media端口是已批准WP02/03的明确接缝，未注册功能；不要为每张表、每个按钮新增factory。
不要把`utils.py`、`common.py`、`manager.py`作为未知代码的堆放处；按职责命名。

## 质量门

当前默认`check.py`按Git工作区选择affected；交接用`--base`覆盖已提交变更。定向测试/分块先行，`--full`和`--release`只在集成/发布收口。完整规则见 `../development/TESTING.md`。
`tests/architecture/test_boundaries.py` 强制业务层不读env、不依赖adapter／HTTP。
新环境／依赖变动必须复跑安装与平台验证；源码能读、测试存在和测试已执行是不同事实。

## 可运行参照

新增adapter时先看FND-02完整示范：adapters/generation/replay、config/profiles/replay.toml、bootstrap/providers.py、tests/contracts与specs/features/FND-02-fixture-replay。规格、真实RED/GREEN和失败收口在docs/development/TDD-SDD.md；不是把接口空声明算作实现。
