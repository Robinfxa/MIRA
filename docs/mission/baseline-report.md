# MIRA 云端锁定基线报告

## 当前结论

**通过：245 Python 测试 + 20 Node 测试，10 个默认离线块全部通过。** 规格检查另验证 28 个 requirement-to-test 链接，链接检查不计为测试执行。

- 时间：2026-10-03 09:10:03–09:10:09 UTC；完整 baseline 命令退出 0，外层耗时 5.23 秒。
- 基准提交：`ebb578dde665c9c7269e4a64b508182680b2fa66`。
- 实际源码：此提交的独立 git-archive 快照，位于 `var/mission/baseline-pinned-20261003T090648Z/source-ebb578d`。主工作目录允许其他开发继续，不混用其后续变更。
- 源码前后摘要相同：`aa77f9d6b8ea823af3e344a1d1d0319eabce259b3883eeca379048f8c8521dc5`；`changed_during_run=[]`。
- **package、smoke、真实服务、浏览器/真机音频、原 164 条产品验收：not_run。** 本报告不是完整产品或 live 准备通过。
- 全量机器收据：[summary.json](../../var/quality/baseline-pinned-full-20261003T091005Z/summary.json)。
- 完整命令/时间/退出码：[full-pinned.result.json](../../var/mission/baseline-pinned-20261003T090648Z/full-pinned.result.json)。

## 已准备的环境

| 项目 | 实际结果 |
|---|---|
| Python | 项目 `.venv313/bin/python`，3.13.5 |
| Python 锁 | requirements/dev.lock 的 25 个版本全部精确匹配 |
| Node.js / npm | 已有 Node 24.19.0 / npm 11.9.0；满足 package.json 的 >=22.12.0 |
| TypeScript | 项目 node_modules，5.8.3，匹配现有 lock |
| 依赖准备 | 官方 PyPI/npm；项目范围；未做全局安装；npm 使用 --ignore-scripts |

[精确版本清单](../../var/mission/baseline-pinned-20261003T090648Z/environment-inventory-pinned.json)。初次创建的 `.venv` 是未装依赖的 Python 3.12 环境，**不要使用**；当前正确解释器是 `.venv313/bin/python`。未改动启动器或配置来隐藏此差异。

系统 Python 3.13 缺少 ensurepip；`.venv313` 建立后，通过既有主运行时 pip 的受支持 `--python .venv313/bin/python` 目标选项安装锁定依赖，没有安装系统软件包或运行下载的 bootstrap 脚本。

## 本次实际验证

所有命令使用 `.venv313/bin/python`，cwd 为上面的固定提交快照。完整 argv 和 cwd 均在每个 result.json 中。测试使用无服务凭据的最小环境；HOME/TMPDIR 和生成输出均隔离到 var/mission 或 var/quality。

| 顺序 | 命令摘要 | 退出码 | 结果 |
|---|---|---:|---|
| 1 | python -m pytest --collect-only -q -o cache_dir=<独立目录> | 0 | 245 个测试收集成功；收集本身不是执行 |
| 2 | python tools/export_contracts.py --check | 0 | OpenAPI / TypeScript 合同一致；只读，未重写产物 |
| 3 | python tools/check.py --lane architecture providers web --jobs 2 --output-dir <唯一目录> | 0 | 47 Python + 20 Node；相关初检通过 |
| 4 | python tools/check.py --full --jobs 2 --output-dir <唯一目录> | 0 | 所有 10 个默认离线块通过 |

全量分块计数：

| 块 | Python 测试数 | 失败/错误/跳过 | 状态 |
|---|---:|---|---|
| architecture | 7 | 0 / 0 / 0 | passed |
| domain | 20 | 0 / 0 / 0 | passed |
| env | 64 | 0 / 0 / 0 | passed |
| config | 18 | 0 / 0 / 0 | passed |
| actor | 15 | 0 / 0 / 0 | passed |
| providers | 40 | 0 / 0 / 0 | passed |
| http | 20 | 0 / 0 / 0 | passed |
| tooling | 61 | 0 / 0 / 0 | passed |
| specs | 不计执行 | 28 个映射要求引用可收集 node | passed |
| web | 不计 Python | strict TypeScript 构建；20 Node，0 失败/跳过 | passed |
| package / smoke | 0 | 未选择，不继承旧结果 | not_run |

这些是 fresh 运行证据，没有继承 README 的历史通过数字。不同阶段重复执行的测试不相加。本次既有代码检查为 baseline，不倒补功能 TDD RED。

## 初次环境阻塞与恢复经过

原始主运行时为 Python 3.12.14，25 个声明包只有 7 个匹配、12 个不匹配、6 个缺失；pytest/pytest-asyncio 和 TypeScript 不可用。初次 selected/collection 失败的完整收据保留在 [原始证据目录](../../var/mission/baseline-20261003T090250Z-09dfad3d/)。它们是环境失败，不是业务行为 RED。

第一组安装命令为隔离服务凭据而使用过度精简的环境，遗漏了平台已经提供的标准代理/CA 基础设施变量，从而得到直接 DNS 失败。npm 另有一次 /dev/null 同时被设为两个配置文件的操作错误，已通过独立空配置文件更正。这些失败记录未删除或覆盖。

在获准使用 exec 的正式 escalation 通道后，同样的官方 registry、相同锁文件，保留既有标准代理/CA 配置但不显示值、不改变其内容，Python 和 npm 安装均退出 0。没有改 DNS、代理或网络设置，没有换 registry，也没有绕过拒绝。成功安装日志：
- [Python 安装收据](../../var/mission/baseline-pinned-20261003T090648Z/install-python-configured-route.result.json)
- [npm 安装收据](../../var/mission/baseline-pinned-20261003T090648Z/install-node-configured-route.result.json)

初始完整说明另存为 [initial-baseline-report.md](../../var/mission/baseline-pinned-20261003T090648Z/initial-baseline-report.md)，它是恢复之前的历史状态，以本报告当前结论为准。

## Python 版本相关的合同注意事项

未锁定的 Python 3.12 首次只读合同检查发现 8 处 HTTP 422 description：提交值 “Unprocessable Content”，3.12 导出值 “Unprocessable Entity”；派生 TypeScript 无差异。FastAPI 此处取 http.client.responses 的默认描述，实测 3.12/3.13 对应值不同。

恢复 Python 3.13.5 + 精确依赖锁后，同一源码的合同检查直接通过；**没有为清除漂移重写任何生成合同**。若后续仍需严格支持 Python 3.11–3.13 的一致导出，应由集成人决定是否固定响应描述并补跨版本测试；本次没有实施该变更。

## 安全与未测范围

已读项目必读文档及 quality runner/imported scripts 后运行。未读根 .env、私人认证缓存或密钥；未运行自动 dev/bootstrap、账户登录、API 元数据/推理调用。env 测试仅使用公开空模板、合成配置/transport 与测试临时文件。合同检查和全部默认块保持离线。

没有改生产代码、测试、规格、配置、锁文件或生成合同。写入范围是项目隔离依赖、唯一 var 证据/快照和本报告。没有 push、部署或支付。

**not_run**：release package/smoke、远端 CI、真实 provider/账户、麦克风/设备声音、浏览器真机交互、原始 164 条产品验收。PyJWT 2.13.0 / cryptography 50.0.0 只在原主运行时完成元数据盘点，不属于这次基线锁或 `.venv313`，尚未为项目增加依赖。
