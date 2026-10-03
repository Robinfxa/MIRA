# FND-02 验证收口

状态：本地代码和自动化检查已完成；独立人工、账户、设备及远端CI未执行。

| 项目 | 实际结果 | 收据 |
|---|---|---|
| 基线回归 | 73 Python/20前端 | 001-baseline |
| 第一RED/GREEN | 8失败1通过 → 同9项通过 | 002/003 |
| 第二RED/GREEN | 2失败36通过 → 同38项通过 | 004/005 |
| 重构／同port／Actor／HTTP集成 | 120 Python通过 | 006 |
| SDD映射与工具负例 | 130 Python/20前端 | 007 |
| 检查器可复用性RED/GREEN | 2失败10通过 → 同12项通过 | 008/009 |
| 禁止覆盖旧证据 | 重复run ID如预期拒绝，旧报告不变 | 010 |
| 离线wheel | 3份fixture资源均能从wheel加载 | 011 |
| 完整质量门 | 132 Python/20前端；TS strict/合同/10项spec映射 | 012 |
| 真实loopback HTTP | 合成fixture端到端请求及停止／重传通过 | 013 |
| 最终源码质量门 | 同132 Python/20前端及spec/合同通过 | 014 |

完整日志在 `../../verification/fnd-02/runs/`；`python tools/verify_tdd_evidence.py`检查每对命令、测试摘要相同、运行前后源文件未改。源文件快照和本地Git history可帮助复验；不是第三方签名的不可伪造证明。

新增59项Python用例不等于新增59个独立产品场景；参数化和回归重跑不叠加样本量。继承代码的TDD顺序unknown，本轮没有倒填。

检查范围：本地fixture、配置、工厂、port替换、原Actor、HTTP TestClient及独立loopback HTTP；socket connect负控证明所测fixture生成路径未连接网络，不是全系统形式化无网络证明。

wheel检查是包数据完整性验证，不是从零安装整个开发环境或全平台发布验证。未跑新浏览器布局、真实手机、语音设备、模型质量、公开服务。原foundation-report.json保存为FND-01历史，本次事实以本报告与新收据为准。
