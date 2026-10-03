# <FND-04>：<一个可独立验收的行为>

状态／授权范围／架构来源：
目标与非目标：

### FND04-001 <行为名称>
Given：明确前提。
When：一个事件或操作。
Then：可观察结果、状态变化、不可发生的副作用。
异常／取消／重复／迟到：

## 合同与责任
port、唯一状态owner、config入口、schema owner、factory装配点。
外部服务／费用／隐私授权：未验证就不补默认许可。

## 追踪
traceability.json：feature=FND-04；spec路径；requirements[]只有id/tests。
测试node ID必须实际可收集，参数化case可以映射到参数化之前的函数node ID。

## 测试分块（实现前填写）
所属lane：
变更路径→必须跑的消费者/合同lane：
最小RED命令与同一集合GREEN命令：
合并前共同base与affected plan：
fixture隔离（tmp/端口/产物/模型替身）：
serial或外部账户/真机检查（默认不启用）：
full/release触发条件与本次未跑范围：
