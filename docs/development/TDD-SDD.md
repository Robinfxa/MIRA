# FND-02：可照着做的 SDD／TDD 示范

> 当前测试频率已由FND03调整为定向/affected/收口三级，见[TESTING.md](TESTING.md)。下表是历史事实，不能照抄为每次修改都跑全量。

本例解决一件小事：**把受控生成回放接入已有配置、工厂、port、Actor和回执链**。继承基础不重写，真实模型和语音仍未接入。

## 1. 三个入口

规格：[spec.md](../../specs/features/FND-02-fixture-replay/spec.md)。
实施记录：[proposal](../changes/FND-02/proposal.md) → [design](../changes/FND-02/design.md) → [tasks](../changes/FND-02/tasks.md) → [verification](../changes/FND-02/verification.md)。
真实运行证据：[runs](../verification/fnd-02/runs/)；追加日志：[LOG.md](LOG.md)。

SDD在本工程指Spec-Driven Development。写规格不是证明功能完成；TDD必须真正看到测试因缺失／错误行为失败，再用实现让相同测试通过。这里未调用OpenSpec CLI，不把文件目录冒充某个工具的运行结果。

## 2. 实际发生的开发顺序

| 阶段 | 真实命令结果 | 证据目录 |
|---|---|---|
| 继承基线 | 73 Python＋20前端通过 | 001-baseline |
| 功能RED | 8失败／1通过：replay配置与工厂路径不存在 | 002-red-replay |
| 最小GREEN | 相同9项通过 | 003-green-replay |
| 资源负控RED | 2失败／36通过：重复JSON键被末值覆盖 | 004-red-script-hardening |
| 负控GREEN | 相同38项通过 | 005-green-script-hardening |
| 共享catalog重构／集成 | 120 Python通过 | 006-refactor-and-integration |
| 规格映射接入质量门 | 130 Python＋20前端通过 | 007-quality-with-sdd |
| 可复用工具RED | 2失败／10通过：映射检查器写死当前feature ID | 008-red-reusable-sdd-check |
| 工具GREEN | 相同12项通过 | 009-green-reusable-sdd-check |
| 记录防覆盖负例 | 重复run ID退出1，旧证据未改 | 010-reject-evidence-overwrite |
| 离线wheel验证 | 构建成功，三份fixture从wheel中可读 | 011-offline-wheel |
| 完整质量门 | 132 Python＋20前端，TS及合同通过 | 012-final-quality |
| 真实loopback HTTP | 合成fixture创建/输入/许可/回执/停止/重传/删除通过 | 013-loopback-replay |
| 最终源码质量门 | 132 Python＋20前端及合同／规格映射通过 | 014-final-quality |

这是累计回归，不能把各行passed相加当样本量。132包含继承73与本轮59；20前端为既有测试重新执行。001不是TDD RED，原FND-01不能倒补为测试先行。

## 3. 一条规格怎样穿过工程

以FND02-006为例：尾部失败不能把整轮标为完成，已有回执事实需要保留。

`spec.md FND02-006`
→ `test_script_failure_is_not_a_clean_end`
→ `test_failed_tail_preserves_only_receipted_history[False/True]`
→ `ReplayGenerationBackend` 的故意失败
→ 既有 `SessionActor` 失败归约
→ 已发许可撤销／已呈现事实保留。

实现没有复制Actor、HTTP或数据库。测试的关键区别是“有回执/没回执”，而不是断言一句日志含有success。

## 4. 为什么异步测试不靠sleep猜时序

`tests/support/barriers.py` 用Event精确建立先后：首候选已被消费 → 下一步等待 → 停止／回执 → 释放或取消。

测试中的timeout只防止挂死，不意味着真实网络或设备在该时限内达标。现有HTTP轮询测试使用短轮询等状态，不拿它制造竞态；真实声音仍未验证。

## 5. 配置与工厂示范

`ProviderSettings`只表达类型与可公开默认；`loader.py`处理优先级；`create_providers`选实现；Replay adapter接收已解析不可变脚本和可注入等待函数。输入永远不能变成任意文件路径。fixture catalog只有一份，不在生成器和审核器各复制一份。

新增第二个真实provider时复制这套分工，不复制fixture白名单审核。真实输出需要真正审核与准入，不得将factory失败降为“返回Mock成功”。

## 6. SDD检查器检查什么

`traceability.json`列10个稳定requirement ID与可收集的pytest node ID。`tools/check_specs.py`核对规格标题、ID唯一、测试存在；不存在、缺失映射、跨feature误用会失败。

检查器不计算语义充分性，也不会因为有映射就把任务改成passed。测试和实测结果在verification记录，不藏在JSON的人工status字段里。

## 7. 如何重看真实RED，而不是故意破坏最终代码

完整包附 `docs/verification/fnd-02/development.bundle`，是仅本地Git历史。请clone到另一个目录，再按 `history.json` 的commit切换，原交付目录保持GREEN。

```bash
git clone docs/verification/fnd-02/development.bundle <temporary-evidence-path>
cd <temporary-evidence-path>
git switch --detach <history.json中RED对应的commit>
python -m pytest tests/contracts/test_replay_generation.py -q
```

历史commit可复验失败；不要为“演示RED”修改已交付代码或覆盖记录。复验依赖仍按锁文件安装；没有声称所有平台已验证。

## 8. 记录的信任边界

`record_check.py`保存完整输出、退出码、UTC时间、解释器／平台、源码前后摘要与Git基点，不导出环境变量。`verify_tdd_evidence.py`检查输出hash、前后源码未变、RED/GREEN测试文件相同。

这是本地完整性与过程证据，不是密码学上不可伪造的第三方证明。独立人工验收、远端CI、真实账户和手机设备测试仍未进行。
