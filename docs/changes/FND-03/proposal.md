# FND-03 proposal

用户要求TDD从一开始可分块并行，避免每次全量拖慢50小时开发。原tools/check.py串行执行全部Python、全库规格收集、共享dist构建与Node测试，CONTRIBUTING/AGENTS要求每次全量。

本切片只改开发反馈方式：明确块和消费者、定向RED/GREEN、affected合并、full/release收口。业务源码与协议、真实账户、功能范围不变；不用新测试框架或分布式平台。
