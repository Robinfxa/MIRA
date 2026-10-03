## 范围与owner
- Spec/工作包、修改的port/config/schema：
- base commit（覆盖已提交改动，不能只看clean worktree）：
- tests/quality.toml所属块／受影响消费者：
- 独占资源或平台／网络限制：

## 实际证据
- [ ] 规格和映射可收集，新测试有唯一分块owner
- [ ] 同一测试的真实定向RED/GREEN（无RED则如实记录）
- [ ] `check.py --affected --base ... --plan`已核对
- [ ] 运行相关块并保存summary；未选范围写not_run
- [ ] 取消、迟到、重复、失败按本次合同覆盖
- [ ] 共享面/未知路径扩展；源码指纹一致，无跨快照拼接通过
- [ ] LOG/handoff与未完项更新，无凭据、隐式付费或第二主控

命令、结果与报告：
未执行块／设备／账户／人工／远端CI：
full/release仅集成或发布owner执行，本次是否适用及结果：
