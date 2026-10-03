# ENV-01 验证收口

状态：本地离线验证完成；**没有真实服务或账户验收**。产品架构v0.6和50小时原T0不变。

## 实际过程

| 阶段 | 结果 | 原记录 |
|---|---|---|
| typed service config RED | 11失败／15通过 | 001-red-service-config |
| 同组GREEN | 26通过 | 002-green-service-config |
| API准备工具首RED | 28失败；大payload参数名导致冗长日志，原文保留 | 003-red-api-preparation |
| 参数展示ID缩短后的canonical RED | 28失败 | 004-red-api-preparation-named-cases |
| 相同测试GREEN | 28通过 | 005-green-api-preparation |
| 压缩响应负控RED | 1失败／31通过 | 006-red-compressed-response |
| 同组GREEN | 32通过 | 007-green-compressed-response |
| 离线子进程凭据隔离RED | 1失败 | 008-red-offline-credential-isolation |
| 同组GREEN | 1通过 | 009-green-offline-credential-isolation |

四组配对核对同一测试文件摘要和命令。003不是被抹除的历史：只修改参数显示ID后重新记录004，配对以004/005为准。全部九份输出摘要与运行前后源码一致性已检查。本地证据不等于独立第三方证明。

## 收口结果

先执行architecture/env/config相关块；最后集成只执行一次full，240项Python（181继承＋59新增）、20项Node及TypeScript strict通过，28条规格链接可收集。随后只执行package/smoke尾检，不重复full；两次源码摘要一致。

原始分块报告在本目录上两级的 `verification/env-01/lanes/`。未选中的块仍为not_run，不累计passed数字。工具读取全新空模板实际退出2并报告缺字段、live_ready=false；未创建真实私密.env。

所有目录HTTP测试都是httpx.MockTransport与合成凭据；唯一本地网络验证是继承的loopback fixture smoke。没有调用外部模型目录、推理、图像、Google或Codex。OpenAI安全key UI已打开，仅此不证明用户已经创建或安装key。

application/domain/HTTP公共协议、live工厂与前端产品逻辑未改。当前工厂继续拒绝未实现live组合；仅填.env不能使产品变成live。真实adapter、语义审核与音频接入仍属于后续产品任务。

## 限制与后续

实际login/ADC/IAM、模型与声线可用性、费用预算、fresh install、远端CI、真机音频均未验证。配置里的metadata上限只限制本次GET次数，不是账户费用硬上限；清理环境变量不是OS隔离。

Next：用户在本机完成必要字段和授权；开发Agent在既定ports/factory实现live，而不是继续扩建配置管理平台。产品164条验收目录保持原not_run。

归档只包含日志、JUnit和收据，不携带pytest临时目录、合成子仓库、cache和编译临时产物；原执行目录在本机var，归档收据的命令路径保留实际运行位置。打包复核发现初次复制夹带这些scratch后已移除，没有修改原输出或测试状态。

## Live工厂拒绝文案回归（2026-10-03）

仅更新`create_providers`拒绝live选择时的诊断文案，没有启用provider、改变配置选择、创建fallback或发出外部调用。适配器代码已存在；live启动仍因应用工厂尚未完成经验证的显式组合与准入而拒绝，环境字段自身不构成授权。提示用户执行离线配置检查并查看当前服务设置说明。

- 规格：新增ENV01-011；既有配置测试文件覆盖Codex/API generation与JEV/API review四种拒绝组合。
- RED：`010-red-live-startup-error`，相同回归的4个参数例均因旧的“不实施”文案断言失败。
- GREEN：`011-green-live-startup-error`，相同测试与断言4 passed。
- 定向回归：配置、服务配置、fixture、replay和rehearsal相关5个既有测试文件共73 passed；覆盖Mock／回放／排练以及外部和付费调用守卫。
- 规格收集：111个requirement链接可收集；这不是额外执行测试或live验收。

本次没有网络、账户、凭据、UI、浏览器或真实provider调用；定向记录器保留运行时HEAD元数据，没有提交或推送。未验证真实服务、账户或设备。
