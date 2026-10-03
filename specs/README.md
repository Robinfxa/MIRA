# SDD：规格驱动开发的维护入口

本工程中的 SDD = Spec-Driven Development。规格写清输入、边界、可观测结果与失败；测试是规格的可执行例子；代码依赖现有 ports。不是重建工作流平台，也不把每个小修复变成一次 G 项评审。

当前可执行示范：[FND-02](features/FND-02-fixture-replay/spec.md)。基础架构仍由 `docs/reference/architecture-v0.6/` 与 ADR-F001 定义。本目录不复制整本架构，不更改 G01–G06。

## 单点归属

- 产品语义：v0.6 相应模块与原 ADR；产品路线变化才请求新决定。
- 功能行为：`specs/features/<ID>/spec.md`；稳定 requirement ID。
- 接口 schema：既有 `entrypoints/http/schemas.py`，不在 spec 复制另一份完整 JSON Schema。
- 实施理由与任务：`docs/changes/<ID>/{proposal,design,tasks,verification}.md`。
- 测试映射：功能目录 `traceability.json`；质量命令验证被引用的测试实际可收集。
- 命令事实：`docs/verification/fnd-02/runs/`；运行记录不覆盖。spec/test 存在不算通过。

## 最短闭环

限定一个行为 → 规格与 Given/When/Then → 写测试 → 运行并检查真实失败原因 → 最小实现 → 同测试通过 → 重构且行为不变 → 定向块／影响面检查 → 更新任务、开发日志和交接。只有集成／发布收口才执行 full/release；详见 `docs/development/TESTING.md`。

实际接口／语义分歧先说明；只在技术细节范围内的实现不反复让用户重新批准。不得补造旧提交的 RED、删除失败收据、把 AI 检查写成人工验收。
