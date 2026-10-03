# FND-03 交接：测试默认按影响分块

基础工程0.3.0；继承0.2.0；原50小时T0不重置。产品G项、应用源码和公共DTO保持不变。

## 已做

`tests/quality.toml`唯一登记9个默认离线块和2个发布块。`tools/check.py`默认Git工作区affected，支持显式files/lanes/base、plan/matrix、full/release。planner严格检查归属/差分，runner隔离进程/产物并有界并发，收据区分selected/not_run/source_changed。

SDD只collect映射module；spec改变反查对应测试owner。PR/模板/AGENTS/CONTRIBUTING和50小时计划已采用定向RED/GREEN→affected→收口full/release。现有fixture/ports/factory/Actor都不改。

## 下一位开发者

先读`docs/development/TESTING.md`。实现WP03/04时写最小spec、列出所属lane及消费者，使用具体node做RED/GREEN，合并前选共同base跑affected。新增测试必须有owner；别在迭代里反复full。

```bash
python tools/check.py --files apps/api/src/mira/adapters/generation/replay/backend.py --plan
python tools/check.py --lane providers actor --jobs 2
python tools/check.py --affected --base <共同基点> --jobs 3
```

ZIP无Git时显式files/lanes；默认clean tree不会验证已提交工作。多Agent独立worktree，不同时改核心共享owner，按整机预算分配jobs。精确lane通过不能冒充merge影响面已验证。

## 实测与限制

49项新增Python测试，最后181 Python＋20 Node、18条SDD需求映射通过；有4组真实RED/GREEN及15份原始记录。最终全离线与串行发布尾检对应同源码摘要；未选择/未运行保留not_run。未测试远端CI、fresh install、浏览器/手机/音频/真实服务。

当前还没有真实语音、原创角色或live模型；这个切片不提高产品验收完成度。接下来直接继续WP03/04，不再新增测试框架。
