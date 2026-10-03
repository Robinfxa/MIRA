# FND-02：受控生成夹具回放

状态：本轮打样授权内的实施规格；独立人工验收尚未执行。版本：1。
基线：FND-01 的 `GenerationBackend`、`CandidateRange`、`FixtureReviewBackend`、SessionActor。
目标：提供一个可以复制开发方法的最小真实 adapter；不是上线一个新的 live provider。

## 范围

新增 `generation=replay`，从随包提供的场景读取完整固定候选，走原有生成→审核→许可→回执路径。场景在启动时选择；用户文字只触发该固定场景，不做语义路由。

这只是 **generation fixture replay**，不是完整会话恢复、HAR 自动重放、音频播放或真实模型语义验证。不得将原架构164条用例批量标绿。

### FND02-001 配置与显式装配

Given 无私人 key 的根配置，When `MIRA_PROFILE=replay` 或显式配置 generation=replay，Then 装配 ReplayGenerationBackend 和 FixtureReviewBackend；默认仍为 mock。配置优先级沿用 loader。Actor 不根据 provider 名称分支。

### FND02-002 有限、随包、无用户路径

场景名仅为 `photo-tour`、`delayed-photo`、`failed-tail`。禁止路径、URL、动态插件、用户工作区或凭据作为场景来源。资源仅在工厂构造期间读取；import 时不读资源、不连网、不读 env。

### FND02-003 冻结内容与输入验证

场景格式有明确版本、有限步骤和 `finish=complete|fail`；步骤只引用已审 fixture_id，不携带自由台词、URL或动作补丁。未知字段、未知fixture、空步骤、超过8步、负／过大延迟、超10秒总延迟、超过16KiB文件、错误类型、非法JSON、重复JSON键都拒绝。异常对外不回显原始输入或资源正文。

### FND02-004 顺序与实例隔离

Given photo-tour，When 调用 generate，Then 依次产出 photo、photo_caption；每次调用有独立游标。复用一个 backend 的两个会话不得互相消费、串数据。给定相同场景的候选值一致，但程序分配的effect身份仍由原编译器负责。

### FND02-005 取消语义

在等待下一步骤时取消，CancelledError 必须传播，不能转成自然结束。测试使用注入的等待函数和 asyncio.Event，不靠任意 sleep 猜时序。Actor 与本地许可仍负责永久失效；adapter 支持取消不替代旧结果防复活。

### FND02-006 失败与回执

failed-tail 先给出固定照片候选再报合成的 provider failure。不 seal 为成功，不再产生尾部；已经真实提交回执的照片事实保留。没有回执的已批准候选不得被写成已展示。

### FND02-007 审核不得绕过

所有回放候选走现有 fixture review；未知或被篡改的内容不通过。replay 不与 live review 混搭，不允许外传／付费开关，不隐式切换真实模型或付费后端。未实现的 codex/api/jev 仍明确拒绝。

### FND02-008 公共接口与运行地位

HTTP协议与前端控制合同不变。当前 health 的 `mode=mock` 表示固定替身家族（含回放），live_llm/live_audio/live_images 均为false；实际装配名称保存在本地配置。无需凭据可通过现有 HTTP 接口演示照片候选、停止、已呈现历史。未接音频或原创图像，不声称其能力。

### FND02-009 配置、资源、调用失败分层

未知配置由 ConfigurationError／配置schema拒绝；非法随包资源在装配时 fail-fast；演出中故意的 provider failure 经既有 Actor 归一为 generation_failed。只有同一候选身份和内容通过审核才可获许可，错误后不改名为 mock 正常回答。

### FND02-010 维护与交接证据

每项有测试 node ID 映射；至少保存功能缺失的 RED、同测试 GREEN、负控补强 RED/GREEN、重构回归和最终质量检查。记录命令、时间、exit code、源文件摘要及实际限制；不可事后编造之前已有代码的 TDD 历史。

## 不变项与后续

不改 domain 转移、不加API endpoint、不新增Session、不接模型账户、不启用语义恢复、不自动付费。素材仍是工程占位。精确语音/图像感知和生产持久化不属于本切片。

## 规格与实现关系

wire schema仍在既有HTTP DTO；内部资源格式由 `adapters/generation/replay/script.py` 定义，非公共模型供应商schema。
`traceability.json` 是映射索引，不是第二份行为规则；spec是否满足需要运行测试及审阅。
