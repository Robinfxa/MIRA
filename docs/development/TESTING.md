# 分块测试：定向开发、影响面集成、全量收口

**当前政策 FND-03 / foundation 0.3.0。** 不再每次编辑后运行全量。此页取代旧示范里作为当时事实的“每次修改→check全量”约定；原RED/GREEN日志不回写。

## 1. 三个工作频率

| 时机 | 命令 | 范围与义务 |
|---|---|---|
| 一个失败行为 | `python -m pytest tests/unit/test_actor.py::test_uncooperative_provider_result_cannot_revive_stop -q` | RED/GREEN同一明确测试或小组；不要求全量 |
| 一个模块GREEN | `python tools/check.py --lane actor providers --jobs 2` | 精确所选块，其他块为not_run；不是合并覆盖证明 |
| 合并／交接 | `python tools/check.py --affected --base <共同基点> --jobs 3` | 已提交差分＋staged＋unstaged＋untracked；加相关下游及守卫 |
| 集成收口／版本候选 | `python tools/check.py --full --jobs 3` | 所有离线质量块；不是账户、真机或164条产品验收 |
| 发布收口 | `python tools/check.py --release --jobs 3` | full成功后串行wheel／本地HTTP；同样没有付费模型与真机 |

直接运行 `python tools/check.py` 默认只看当前Git工作区变更；**已提交的工作必须用共同base**，否则干净树会如实报告no_changes，并不会偷偷验证刚提交的改动。无Git的ZIP目录要求显式 `--files` / `--lane` / `--full`，不静默回到全量。

```bash
# 不执行，只看为什么选这些块
python tools/check.py --files apps/api/src/mira/adapters/generation/replay/backend.py --plan
# ZIP目录也可按显式改动面运行；此清单的完整性由提交者承担
python tools/check.py --files apps/api/src/mira/adapters/generation/replay/backend.py --jobs 3
# 新前端修改不会顺带运行所有后端功能测试
python tools/check.py --files apps/web/src/features/presentation/permit-gate.ts --jobs 2
python tools/check.py --list
```

## 2. 分块不是任意均分文件

ENV-01追加：`env`块只做离线配置、合成HTTP transport和私密文件初始化测试；`metadata` CLI不在任何自动块中。离线runner剥离本项目常用标准服务credential环境变量，仍不是文件系统／网络安全沙箱。

唯一分块／影响规则在 `tests/quality.toml`，不是应用 `.env`；没有第二套业务配置。

| 块 | 内容 | 常见调用者 |
|---|---|---|
| architecture | 分层、导入无副作用、导出合同只读检查 | 每次有代码影响均保留的小守卫 |
| domain | 纯状态转换 | 状态owner |
| config | loader／类型／装配边界 | 配置与工厂修改 |
| actor | Actor与回放Actor集成、取消与迟到 | 运行时owner |
| providers | fixture/replay端口合同、脚本输入、取消 | adapter owner |
| http | ASGI端点和回放HTTP | HTTP／bootstrap修改 |
| tooling | 分块、调度、规格链接负例 | 开发工具owner |
| specs | 仅collect规格实际引用的测试模块，验证node链接；不执行这些测试 | 规格改变与full |
| web | 单次独立TS strict构建＋Node测试 | 浏览器修改 |
| package / smoke | 离线wheel／真实loopback HTTP | 按需与release，默认不启动 |

一个自动测试文件恰有一个owner；配置可按文件或glob登记。新测试漏登记、重复归属、目标零命中、非法块名会失败，不能用绿色空结果掩盖遗漏。

影响规则是**显式保守依赖图**，不是声称自动分析Python动态import。adapter修改会带上config/actor/http消费者；domain、public DTO、ports、锁文件、全局fixtures与分块器改动扩大到全部离线块。未知文件显式全量兜底并提示补规则。

feature spec改变同时运行其 `traceability.json` 对应行为测试块，不仅检查链接。语义审核和行为测试不能被“规格文件存在”代偿。

## 3. 并行不互相污染

一个调度器最多同时启动`--jobs`个块（默认3、上限8）；块内不再开启pytest-xdist。测试自身的子进程与Node内部执行需要计入团队机器预算。没有依赖新增或分布式测试平台。

每个run使用唯一目录 `var/quality/<run-id>/<lane>/`：独立pytest basetemp、cache、JUnit、stdout/stderr、进程记录和TS输出。不写共享`apps/web/dist`；`export_contracts --check`只读，不生成文件。Node测试通过测试专用 `MIRA_TEST_WEB_DIST`读取该块构建；普通npm test仍可读取正常dist。

非并行块在同一计划的并行组成功后串行。当前smoke使用临时loopback端口，package在临时源码副本构建；不连接外部Provider。新真机、账户、付费测试必须单独准入，禁止混进默认glob里当普通单测。

多人/多Agent开发用独立worktree。共享schema、transitions、bootstrap仍由集成owner负责。多个worktree的jobs之和由owner配置，不能每个都开8。源码在一次运行中变化则标`source_changed`，不合并来自不同源码快照的绿灯。

## 4. 证据与失败政策

计划保存输入改动文件、选择原因和块；每块保存真实命令、pid、起止时间、退出码、输出hash和可用的JUnit计数。总收据明确 `selected_lanes`、`not_run`、源码前后摘要。没有成功结果缓存，未运行不能继承上次passed。

一个块失败不丢失其他独立块结果；超时、collection失败、pytest退出5、缺少命令、源码变化均不能成为整体通过。发布串行检查在前置失败后不启动，记not_run。只改普通文档或无差分会报告`no_checks`，不是“全量通过”。

运行目录已有则拒绝覆盖。此工具会保存完整stdout/stderr，所以**只用于本地合成测试，不运行真实凭据／私人数据**。POSIX超时清理进程组；Windows子进程树的清理仍未验证。

每次测试仍可套原有记录器：

```bash
python tools/record_check.py --feature fnd-04 --id 001-red --expect-exit 1 -- \
  python -m pytest tests/具体文件.py::test_case -q
# 保持同一测试集合与断言，改实现后以002-green再运行
```

SDD feature模板要求填写负责块、关联消费者、基准、资源和未选范围。PR填写actual command/report，而不是一律勾“全量通过”。

## 5. CI与收口边界

CI先用同一个selector生成差分matrix，单块job各用jobs=1，matrix max-parallel=3且fail-fast=false；普通PR不必重新执行无关块。共享面或未知差分仍扩大；workflow_dispatch显式完整收口。生成计划阶段不安装模型、不运行测试。此workflow仅编写，本轮未触发远端CI。

默认full与release只覆盖当前仓库离线检查，不能替代语义质量、实际音频与手机验收。现在套件较小，子进程启动也有成本；不承诺本机并行一定比串行更快。减少无关执行和未来避免线性串行增长才是此变更的目标。

## 6. 实现依据（官方机制；不替代本地结果）

- pytest: https://docs.pytest.org/en/stable/how-to/usage.html — 文件/node选择；不要在同一进程重复pytest.main当隔离。
- pytest: https://docs.pytest.org/en/stable/reference/exit-codes.html — 非零与无测试区分。
- pytest: https://docs.pytest.org/en/stable/how-to/tmp_path.html — 明确临时目录生命周期。
- Python: https://docs.python.org/3/library/subprocess.html — 独立子进程、timeout与POSIX进程组。
- Node: https://nodejs.org/api/test.html — 原生测试runner；本次实际使用Node22.16.0而非断言所有版本。

这些文档在2026-10-03查阅。真实结果见 `docs/changes/FND-03/verification.md`。
