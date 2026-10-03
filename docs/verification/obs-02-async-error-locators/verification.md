# OBS-02 — 异步失败诊断定位

2026-10-03 12:16 UTC。基线为 director 冻结的 `20261003T1158Z`；不改变原截止时间。
范围是异步错误定位，不是产品/真实设备验收。

## 实现与定位约定

- `SessionState.last_error_diagnostic_id` 是独立、不可变的失败事实。`request_id` 仍仅代表
  当前输入授权；失败时正常归零。Stop/新输入清空错误码与定位号；旧轮次失败不能覆盖新轮次。
- 对真实 `DiagnosticSpan.context.request_id` 的合法 UUID 原文计算
  `h_ + SHA256(UTF-8 原文).hexdigest()[:32]`。应用与普通日志 sanitizer 共用唯一 hash 函数。
  无原始关联、格式不合法或原值只是 `constructor`/`__proto__`/另一个 hash 时返回 null；
  不猜 input command UUID，不使用轮询 HTTP 的新 ID，不生成未记录的“定位号”。
- 界面的 `h_...` 可原样精确匹配普通事件 JSONL 的 `context.request_id`。
  直接 HTTP 失败仍显示 `X-Request-ID` 原始 UUID；搜索普通日志前按上述约定 hash 一次。
  原始 UUID 的大小写/内容不额外规范化；必须 hash 实际返回值。已经是 `h_...` 的编号不要二次 hash。
- 同一 request 下可有 generation、input_review、output_review 等不同阶段，使用 stage/outcome
  进一步区分。TTS/麦克风拥有各自 HTTP/WS 请求上下文。playback receipt 失败显式记录对应
  playback 事件，快照携带该 receipt 请求的定位号。
- DTO 唯一 owner 仍是 `schemas.py`：只新增 SessionView、SpeechErrorFrame、MicrophoneError
  三个可选字段；由 canonical exporter 生成 OpenAPI/TypeScript，不手改生成物。
- 客户端 protocol 丢弃错误类型/格式/继承属性定位号，安全文案只使用 own-property 已知码。
  NDJSON 与 WebSocket 不再吞掉关联号；麦克风通用校验 catch 不覆盖已安全处理的错误。
  Stop/新输入本地立即清除错误显示；旧历史写入失败仍可提示，但不能覆盖当前轮次已有错误编号。

日志仍是 best-effort：定位号说明事件的实际关联上下文，不保证文件写入、保留或可导出。
丢弃/IO 状态仍由既有 diagnostics status 报告。未引入新的日志框架或持久会话权威。

## RED → GREEN 收据

最初先新增 spec 与测试，再执行旧实现：14 Python 失败、18 Node 失败；没有把导入/安装失败当
行为 RED。其后 playback 测试的后续新输入错误使用了 0 cutoff（前面已产生序号 1），改为 1，
不改实现的 cutoff 保护。又补充 semantic input review、stale media、mapper 和 stale UI 负控。

最终同一测试文件同时对原冻结基线/原 TS 构建与最终实现运行：

- Python：原基线 21 失败 → 最终 21 通过
- Node：原构建 19 失败 → 最终 19 通过
- `final-red-green-receipt.json` 记录准确命令、日志 SHA-256、测试 SHA-256、逐项源码前后 hash。
  本轮前后 20 个作用域文件一致；`source_unchanged=true`。基线没有被改写或人为制造失败。
- 最初与最终日志分别保留；最终结果不覆盖原始 RED。

## 受控链路证明

Python 实际 TestClient → middleware request correlation → SessionActor background generation/
legacy output review/typed semantic input review → pure failed state → SessionView → GET snapshot，
断言 UI 定位号与真实 sanitized FAILED 事件的 request 字段相同，而不是 command UUID 或 poll ID。

TTS 实际 NDJSON 路由与错误 snapshot 共享同一已记录定位号；STT 实际 WebSocket error 与
microphone/STT failed 事件对应；playback receipt 生成对应阶段失败记录。供应商异常只有合成
private marker，断言不会进入响应、快照或普通日志。

`http-error-fixture.json` 来自实际 HTTP 错误快照和已编码日志。Node 用其中实际 error code/id
运行真实 main.js、MiraApiClient、SessionController、parser 与安全渲染 helper；fetch、DOM、
AudioContext 为合成原语，会话 client/revision/activity 由 harness 重新绑定。最后 `[data-error]`
保留实际 backend locator 与中文重试文案；Stop 在尚未收到响应时即清空。
这验证跨层序列化与 DOM 赋值，不代表真实浏览器网络、像素 paint 或真实扬声器。

## 消费者回归

`var/quality/obs02-20261003T1215Z/summary.json`：显式 lanes，全程源码未变化。

- architecture 7；domain 32；actor 15；providers 664；HTTP 71；web 161，全部通过
- specs：96 requirements 的 test node 可收集；它不是行为执行数量
- 原麦克风 teardown 13 cases 包含在 providers 中；不能另加为覆盖总数
- exporter `--check` 最终通过
- scope-proof.json 通过 AST 对比证明 Actor close_media/open_microphone/close、MediaOperation
  cancel/own_consumers/values/_run/close、麦克风 reader/sender 未变化。compiler、cue validator、
  permit gate byte-identical；OpenAPI parsed delta 只有上述三字段。

较早一次 255 backend 定向消费者通过。第一轮全部 web 发现既有“旧历史写入失败应提示”断言，
现已保留该提醒但不覆盖新轮次错误。第一轮 providers 的 3 个 token 拒绝测试原本严格期望两个
字段；现严格要求三个字段且验证 locator 形状与 token 不反射，原拒绝码/会话存活断言不削弱。
这些中间失败日志保留。

本任务没有运行 Git、live provider、凭据/.env、真实浏览器/设备、全量 release 或发布。
`--lane` 是有边界的消费者检查，不冒充 `--affected` 或完整 release；director 负责后续冻结整体验证。
