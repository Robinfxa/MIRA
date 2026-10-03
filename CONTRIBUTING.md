# 开发约定：一个受限闭环，分块而非次次全量

先读 README → 50h计划 → `docs/handoff/FND-03.md` → 对应架构与固定源码。
规格及历史示范见 `docs/development/TDD-SDD.md`；当前测试政策以 `docs/development/TESTING.md` 为准。

## 一个变更

1. 先spec/Given-When-Then和失败/取消语义，声明port、config、共享owner。
2. 同时声明测试块、关联消费者、资源和共同Git基点；具体登记在tests/quality.toml。
3. 定向RED→实现→同一测试GREEN。收集失败/安装错误不是业务RED。
4. 合并前跑affected，不每次全量；共享面自动扩展，未知不静默忽略。
5. 更新traceability、tasks、verification、LOG、handoff，明确本次未跑范围。

```bash
python -m pytest tests/unit/test_actor.py::test_uncooperative_provider_result_cannot_revive_stop -q
python tools/check.py --lane actor providers --jobs 2
python tools/check.py --affected --base <共同基点> --jobs 3
# 仅集成候选/发布收口，不是每次修改
python tools/check.py --full --jobs 3
python tools/check.py --release --jobs 3
```

ZIP无Git时用`--files <改动路径...>`；有Git默认只读工作区，已提交改动必须带base。先`--plan`查看范围。纯文档no_checks不是测试通过。

每个测试文件唯一owner；临时目录/报告/前端构建按run和lane隔离。多Agent用独立worktree并共享机器预算；不并发修改schemas.py、transitions.py、bootstrap。禁止同一目录边改边用旧收据证明GREEN。

## 编码约束不变

domain纯函数；application依赖ports；adapters处理IO；bootstrap选择实现；仅loader读应用env。Public DTO单点导出。真实/已批准/已呈现不混同；fixture不能审核live。异步竞态用Event屏障，超时仅防挂。不要为每个对象添factory或BaseService。

## 证据

记录器用唯一ID，禁止覆盖：

```bash
python tools/record_check.py --feature fnd-04 --id 001-red --expect-exit 1 -- python -m pytest tests/具体测试.py -q
python tools/record_check.py --feature fnd-04 --id 002-green -- python -m pytest tests/具体测试.py -q
```

不把凭据、私人数据、真实Provider调用放进原样保存输出的记录器。旧FND02日志由`verify_tdd_evidence.py`复核；FND03收口另有实际报告，不回写旧测试。

改变G项政策、外传/付费/账号/部署范围先明确授权；既有合同内的窄实现不另开大型评审。自检不是独立人工验收，workflow存在不是远端执行。没有自动push。
