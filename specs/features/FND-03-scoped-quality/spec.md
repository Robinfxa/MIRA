# FND-03 增量分块质量门

状态：用户要求按变更并行分块；本规格是开发工具合同，不改变 G01–G06。

### FND03-001 按影响面选择
局部代码修改选择所属块、已知下游合同与小型架构守卫，不自动执行无关前端或全库测试。
### FND03-002 共享面与未知保守扩展
公开 DTO、领域状态、端口、全局 fixture、锁文件或测试分块规则改变扩大到全部离线检查。未映射路径显式说明并扩大；不是静默跳过。
### FND03-003 变更来源可靠
Git 比较包含基准后的提交、暂存、未暂存、未跟踪、删除与重命名两侧。无 Git/基准错误要求显式选择，不伪报无变更。
### FND03-004 测试归属完整
每个自动 Python/JS 测试文件恰有一个块；新文件漏登记、重复归属、错误块名或配置拼写使选择失败。
### FND03-005 有界并行及隔离
独立块可在独立进程并发；临时目录、pytest cache、JUnit、stdout/stderr、TypeScript产物按本次运行与块隔离。独占块排在并行组之后。
### FND03-006 不把失败或未运行当通过
任一块失败、超时、无测试退出或缺少命令不得成为整体通过；其余独立块收集结果；未选块标为 not_run。纯文档／无变更是 no_checks。
### FND03-007 同一源码与证据边界
每次运行记录选择依据、源码指纹、命令、时间和退出码；运行中源码变化使结果不可作为 GREEN。已有结果目录不覆盖，不借用旧绿色结果。
### FND03-008 开发和收口分层
定向 RED/GREEN 直接用 pytest node 或块；合并前按 affected；full为全部离线质量块；release再包含串行包与本地HTTP检查。均不含账户、付费或真机。

### Browser/package source boundary clarification (2026-10-03)
The existing unchanged-source condition includes authored public browser assets, the HTML
entrypoint, TypeScript build configuration and the package build hook, not only TS/Python.
Generated dist outputs remain excluded. A concurrent change to any such input must make
the run `source_changed`, even when each child command exits zero. Owner remains tooling;
consumers are every quality lane. This corrects fingerprint coverage, not test selection.
