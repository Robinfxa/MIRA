# ENV-01 设计

依赖：service_settings → config/base；Settings组合services；原loader完成profiles/env/标准alias；tools/api_env调用loader，tools/api_environment接收typed settings。domain、application、HTTP wire及live factory保持不变。

优先级保持不变；别名按来源层归一再合并，同层冲突不取最后值。秘密类型不进入repr/model_dump，TOML递归禁secret字段。

工具分init/check/metadata。check无网络；metadata需命令动作、显式服务、配置许可、请求数、credential和网关准入，共同通过才发GET。内容不落报告。metadata结果不会写运行时状态或开启provider。

offline lane env归属两份新测试；config改动带env与既有消费者。quality runner剥离标准服务credential变量。本地文件权限不是独立沙箱；未来live子进程仍需文件与网络隔离。

本次不补候选fixture_id迁移、音频进度wire、真实provider、GoogleSDK或自主任务调度器。它们属于下一产品工作包，不用.env伪装为已实现。
