# FND-03 design

`tests/quality.toml`提供owner/rules → `tools/quality_plan.py`做纯选择/Git边界 → `tools/quality_run.py`启动独立子进程 → 原pytest/Node/合同工具。
`tools/check.py`只装配CLI；`check_web.py`隔离输出；SDD只收集映射module。

owner改变不会改应用env/factory。默认相关块，小守卫常留；共享面或未知依赖扩大。test inventory遗漏/多归属、错误base/参数fail-closed。无Git要求显式输入。

并行块使用独立目录和进程；serial组仅在并行成功后运行。runner没有通过缓存，没有模型调用。多Agent仍需worktree，不将共享工作区的并发编辑视为安全。

FND03 spec与测试集合先于实现。四组RED/GREEN见verification；新增工具测试中实际并行用文件同步屏障确认两个子进程同时在运行，不以执行秒数断言性能。

CI复用selector产生matrix，独立job最多3个；本地每job1块，不叠加worker池。远端CI未运行。
