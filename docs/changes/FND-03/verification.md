# FND-03 验证收口

范围：开发测试选择与调度，不是产品功能实现。当前基础工程0.3.0，架构v0.6与应用wire不变。

## 实际运行

| 记录 | 结果 | 解释 |
|---|---|---|
| 001 | 19项架构基线通过 | 没有先重复跑132项全量 |
| 002 → 003 | 40失败 → 相同40项通过 | 分块/影响选择与隔离执行的接口已有规格但行为未实现；不是collection错误 |
| 004 → 005 | 7失败 → 相同7项通过 | SDD限定映射module收集，不再隐藏全库collect |
| 006 → 007 | 1失败 → 相同1项通过 | 实测spec修改漏选providers/actor/http；补齐反向映射 |
| 008 | 5块，100项Python通过 | replay adapter影响集合；domain/tooling/specs/web与发布尾检未选 |
| 009 | 2块，7项Python＋20项Node通过 | 前端变更；没有运行其余后端块 |
| 010 | 初次完整离线收口180 Python＋20 Node通过 | 测试runner自身为共享面，因此集成时跑full |
| 011 | 两项发布尾检通过 | 临时源码wheel＋实际loopback HTTP，未跑真实服务 |
| 012 → 013 | 1失败 → 相同1项通过 | review发现pytest后缀`*_test.py`可能漏出inventory；负例先复现再修复 |
| 014 | 最终9块181 Python＋20 Node、18条规格映射通过 | 改过测试选择器后再次full收口，非每个业务修改都全量 |
| 015 | 两项发布尾检通过 | 与014源码摘要相同，未重复执行9个离线块 |

最终181 Python包括继承132与新增49；20个Node行为测试沿用既有断言，只改变构建导入以支持独立输出目录。不能把各次passed相加当独立样本。

JSON摘要：`../../verification/fnd-03/summary.json`；原始运行收据：`../../verification/fnd-03/runs/`；分块日志/JUnit：`../../verification/fnd-03/lanes/`。

四组RED/GREEN的命令与测试文件摘要一致；15份原始日志hash和源码前后摘要已核对。历史FND02的14份日志/3对红绿亦复核通过，原文件未改。证据是本地完整性与顺序记录，不是第三方证明。

## 并行和隔离证据

`test_two_lanes_really_overlap_and_get_isolated_temp_and_logs`启动两个真实合成子进程；每个先写标记并等另一个标记才结束，验证重叠、不同pid和不同temp/log。没有拿固定毫秒阈值当性能正确性。
`test_serial_lane_runs_after_parallel_group`验证发布/独占阶段在并行完成后；失败、timeout、缺binary、pytest退出5、源码变化和旧目录覆盖均有负例。

前端选择实际只运行architecture与web；构建写本次lane路径，不触碰共享apps/web/dist。package复制临时源码，smoke使用临时loopback端口。串行尾检不使用原会覆盖旧日志的local_http_smoke.py。

各summary保存真实elapsed时间；未做等价串行/并行A/B基准，不据此声称稳定N倍加速。

## 明确未执行

远端GitHub CI、全新依赖安装、浏览器布局与手机设备、真实Codex/JEV/ASR/TTS、独立人工验收、原164条产品验收。原product目录状态未改。没有用户电脑或远端写入。

Git历史包含继承基线、首组RED以及部分阶段提交；精确红绿序列以runs为准，不声称每个运行都有单独commit。本地bundle仅用于查证源码，不自动push。
